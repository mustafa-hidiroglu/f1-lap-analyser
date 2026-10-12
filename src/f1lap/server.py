"""JSON-RPC 2.0 sidecar for the macOS app: newline-delimited JSON over stdin/stdout.

- One request or response per line. stdout carries protocol only; anything else a library prints
  is redirected to stderr (the app logs it).
- The event loop never blocks: all FastF1/pandas work runs on one worker thread (which also
  serialises access to the non-thread-safe session objects), so `ping` stays responsive while a
  session loads.
- Up to `max_sessions` loaded sessions are kept (LRU) with their resampled laps memoised.
- Lap traces are written as Structure-of-Arrays binary files (`binary.write_soa`) and returned
  as a path plus layout, not as JSON arrays.

Methods: ping, schedule, session, compare, rate. While a request runs, the server may send
`progress` notifications (`{"method": "progress", "params": {"message", "done"?, "total"?}}`).
"""

from __future__ import annotations

import argparse
import asyncio
import contextlib
import json
import logging
import os
import sys
import threading
import uuid
from collections import OrderedDict
from collections.abc import Callable
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Final

import numpy as np

from f1lap import schema
from f1lap.binary import write_soa
from f1lap.circuit import corner_segments
from f1lap.delta import compare, corner_table, summary
from f1lap.explain import explain_session_lap
from f1lap.ingest.fastf1_source import LapSelector
from f1lap.metrics import lap_metrics
from f1lap.phases import compare_corners
from f1lap.rating import rate_session_lap
from f1lap.session import LoadedSession
from f1lap.sim import SimError
from f1lap.trace import TraceError

PROTOCOL_VERSION: Final = 1
def default_cache_dir(platform: str = sys.platform, env: dict[str, str] | None = None) -> Path:
    """The per-user cache: ~/Library/Caches/f1lap (macOS), %LOCALAPPDATA%\\f1lap\\Cache
    (Windows), else $XDG_CACHE_HOME/f1lap or ~/.cache/f1lap."""
    env = dict(os.environ) if env is None else env
    if platform == "darwin":
        return Path.home() / "Library" / "Caches" / "f1lap"
    if platform == "win32":
        local = env.get("LOCALAPPDATA")
        return (Path(local) if local else Path.home() / "AppData" / "Local") / "f1lap" / "Cache"
    xdg = env.get("XDG_CACHE_HOME")
    return (Path(xdg) if xdg else Path.home() / ".cache") / "f1lap"


DEFAULT_CACHE: Final = default_cache_dir()
TRACK_STEP_M: Final = 5.0  # track-outline resolution sent as JSON
MAX_LINE: Final = 1 << 20

log = logging.getLogger("f1lap.server")


class RpcError(Exception):
    def __init__(self, code: int, message: str) -> None:
        super().__init__(message)
        self.code = code


INVALID_PARAMS: Final = -32602
METHOD_NOT_FOUND: Final = -32601
PARSE_ERROR: Final = -32700
INVALID_REQUEST: Final = -32600
INTERNAL: Final = -32603
APP_ERROR: Final = -32000  # analysis failed (bad lap, missing data, ...)


def _param(p: dict[str, Any], name: str, *types: type, default: Any = ...) -> Any:
    if name not in p:
        if default is ...:
            raise RpcError(INVALID_PARAMS, f"missing param {name!r}")
        return default
    value = p[name]
    if isinstance(value, bool) or not isinstance(value, types):
        raise RpcError(INVALID_PARAMS, f"param {name!r} has wrong type")
    return value


def _lap(p: dict[str, Any]) -> LapSelector:
    lap = _param(p, "lap", int, str, default="fastest")
    if isinstance(lap, int):
        return lap
    if lap != "fastest":
        raise RpcError(INVALID_PARAMS, "lap must be an integer or 'fastest'")
    return "fastest"


def _lap_ref(p: dict[str, Any], name: str) -> tuple[str, LapSelector]:
    ref = _param(p, name, dict)
    return _param(ref, "driver", str), _lap(ref)


@dataclass
class Server:
    cache_dir: Path
    step_m: float = 1.0
    max_sessions: int = 3  # a cross-year comparison holds two, plus one being rated
    keep_traces: int = 20
    #: Sends a protocol message from the worker thread (set by `serve`); None drops progress.
    notify: Callable[[dict[str, Any]], None] | None = field(default=None, repr=False)

    def __post_init__(self) -> None:
        self._sessions: OrderedDict[tuple[int, str, str], LoadedSession] = OrderedDict()
        self._worker = ThreadPoolExecutor(max_workers=1, thread_name_prefix="f1lap-worker")
        self._methods: dict[str, Callable[[dict[str, Any]], Any]] = {
            "schedule": self.schedule,
            "session": self.session,
            "compare": self.compare,
            "rate": self.rate,
        }

    # -- dispatch -------------------------------------------------------------------------------

    async def handle(self, raw: str) -> dict[str, Any] | None:
        try:
            msg = json.loads(raw)
        except json.JSONDecodeError as exc:
            return _error(None, PARSE_ERROR, f"invalid JSON: {exc}")
        if not isinstance(msg, dict) or msg.get("jsonrpc") != "2.0" or "method" not in msg:
            return _error(None, INVALID_REQUEST, "not a JSON-RPC 2.0 request")
        rid = msg.get("id")
        params = msg.get("params", {})
        try:
            if not isinstance(params, dict):
                raise RpcError(INVALID_PARAMS, "params must be an object")
            result = await self.call(str(msg["method"]), params)
        except RpcError as exc:
            return _error(rid, exc.code, str(exc))
        except (TraceError, LookupError, ValueError) as exc:
            return _error(rid, APP_ERROR, str(exc))
        except Exception as exc:  # report, keep serving
            log.exception("internal error in %s", msg.get("method"))
            return _error(rid, INTERNAL, f"{type(exc).__name__}: {exc}")
        return None if rid is None else {"jsonrpc": "2.0", "id": rid, "result": result}

    async def call(self, method: str, params: dict[str, Any]) -> Any:
        if method == "ping":
            return {"protocol": PROTOCOL_VERSION, "cache_dir": str(self.cache_dir)}
        fn = self._methods.get(method)
        if fn is None:
            raise RpcError(METHOD_NOT_FOUND, f"unknown method {method!r}")
        loop = asyncio.get_running_loop()
        return await loop.run_in_executor(self._worker, fn, params)

    def close(self) -> None:
        self._worker.shutdown(wait=False, cancel_futures=True)

    # -- sessions (worker thread only) ----------------------------------------------------------

    def _session(self, p: dict[str, Any]) -> LoadedSession:
        year = _param(p, "year", int)
        event = _param(p, "event", str, int)
        name = _param(p, "session", str)
        key = (year, str(event).lower(), name.lower())
        if key in self._sessions:
            self._sessions.move_to_end(key)
            return self._sessions[key]
        self._progress(f"Loading {year} {event} {name} (first load downloads it)")
        loaded = LoadedSession.load(year, event, name, cache_dir=self.cache_dir, step_m=self.step_m)
        loaded.progress = lambda done, total: self._progress(
            f"Reading {total} laps of {year} {event} {name}", done, total)
        self._sessions[key] = loaded
        while len(self._sessions) > self.max_sessions:
            self._sessions.popitem(last=False)  # free the least recently used session
        return loaded

    # -- methods (worker thread) ----------------------------------------------------------------

    def schedule(self, p: dict[str, Any]) -> list[dict[str, Any]]:
        import fastf1

        fastf1.Cache.enable_cache(str(self.cache_dir))
        sch = fastf1.get_event_schedule(_param(p, "year", int), include_testing=False)
        events = []
        for row in sch.itertuples(index=False):
            sessions = [
                str(getattr(row, f"Session{i}")) for i in range(1, 6)
                if isinstance(getattr(row, f"Session{i}", None), str)
                and getattr(row, f"Session{i}")
            ]
            events.append({
                "round": int(row.RoundNumber),
                "name": str(row.EventName),
                "country": str(row.Country),
                "location": str(row.Location),
                "date": row.EventDate.date().isoformat(),
                "format": str(row.EventFormat),
                "sessions": sessions,
            })
        return events

    def session(self, p: dict[str, Any]) -> dict[str, Any]:
        return self._session(p).info()

    def compare(self, p: dict[str, Any]) -> dict[str, Any]:
        # Each side may name its own year/event/session (e.g. one driver at one track across
        # seasons); the reference side's session supplies the circuit and corner segments.
        sd, ref = self._side(p, "reference")
        _, oth = self._side(p, "other")
        cmp = compare(ref, oth)
        segments = corner_segments(sd.circuit, cmp.reference)
        report = summary(cmp, corner_table(cmp, segments))
        report["corners"] = [c.to_dict() for c in compare_corners(cmp, segments)]
        report["metrics"] = [
            lap_metrics(cmp.reference, segments).to_dict(),
            lap_metrics(cmp.other, segments).to_dict(),
        ]
        report["circuit"] = self._circuit(sd, cmp.reference)
        columns = {schema.DISTANCE: cmp.distance, "delta": cmp.delta_s}
        for prefix, lap in (("ref", cmp.reference), ("oth", cmp.other)):
            columns |= {f"{prefix}.{k}": v for k, v in lap.channels.items() if k != schema.DISTANCE}
        report["traces"] = self._write_traces(columns)
        return report

    def rate(self, p: dict[str, Any]) -> dict[str, Any]:
        sd = self._session(p)
        driver, lap = _param(p, "driver", str), _lap(p)
        result = rate_session_lap(sd, driver, lap).to_dict()
        result["perfect"] = self._perfect(sd, driver, lap)
        result["circuit"] = self._circuit(sd, sd.reference)
        result["reference"] = {
            "driver": sd.reference.meta.driver,
            "lap_number": sd.reference.meta.lap_number,
            "lap_time_s": sd.reference.meta.lap_time_s,
        }
        return result

    # -- helpers --------------------------------------------------------------------------------

    def _side(self, p: dict[str, Any], name: str) -> tuple[LoadedSession, Any]:
        side = _param(p, name, dict)
        sd = self._session(p | {k: side[k] for k in ("year", "event", "session") if k in side})
        return sd, sd.lap(*_lap_ref(p, name))

    def _perfect(self, sd: LoadedSession, driver: str, lap: LapSelector) -> dict[str, Any]:
        """The lap vs the session's perfect lap, with reasons; `{"error": ...}` if the session
        has none (too few laps, unreliable telemetry)."""
        self._progress("Comparing with the perfect lap")
        try:
            report = explain_session_lap(sd, driver, lap)
        except SimError as exc:
            return {"error": str(exc)}
        except Exception as exc:  # the rating itself must still be returned
            log.exception("perfect-lap comparison failed")
            return {"error": f"perfect-lap comparison failed: {type(exc).__name__}: {exc}"}
        cmp = compare(sd.sim.lap, sd.lap(driver, lap))
        out = report.to_dict()
        columns = {
            schema.DISTANCE: cmp.distance,
            "delta": cmp.delta_s,
            "sim.time": cmp.reference[schema.TIME],
            "lap.time": cmp.other[schema.TIME],
            "sim.speed": cmp.reference["speed"],
            "lap.speed": cmp.other["speed"],
            "sim.brake": cmp.reference["brake"],
            # Missing, not zero: a zero brake would read as never braking (the replay then
            # places the braking points on deceleration), a zero throttle as a lift all lap.
            "lap.brake": cmp.other["brake"] if "brake" in cmp.other.channels
            else np.full(len(cmp.other), np.nan),
            "sim.throttle": cmp.reference["throttle"],
            "lap.throttle": cmp.other["throttle"] if "throttle" in cmp.other.channels
            else np.full(len(cmp.other), np.nan),
        }
        # One racing line for the replay: the driver's own, else the perfect lap's. Patchy GPS
        # (under 95 % finite) would draw straight chords, so it falls through.
        for line in (cmp.other, cmp.reference):
            if "x" in line.channels and "y" in line.channels and min(
                    np.isfinite(line["x"]).mean(), np.isfinite(line["y"]).mean()) >= 0.95:
                columns |= {"x": line["x"], "y": line["y"]}
                break
        out["traces"] = self._write_traces(columns)
        return out

    def _progress(self, message: str, done: int | None = None, total: int | None = None) -> None:
        if self.notify is not None:
            params: dict[str, Any] = {"message": message}
            if total is not None:
                params |= {"done": done, "total": total}
            self.notify({"jsonrpc": "2.0", "method": "progress", "params": params})

    def _circuit(self, sd: LoadedSession, lap: Any) -> dict[str, Any]:
        segments = corner_segments(sd.circuit, lap)
        positions = sd.circuit.positions_on(lap)
        out: dict[str, Any] = {
            "name": sd.circuit.name,
            "source": sd.circuit.source,
            "rotation_deg": sd.circuit.meta.get("rotation_deg", 0.0),
            "corners": [
                {"label": c.label, "distance_m": float(d)}
                for c, d in zip(sd.circuit.corners, positions, strict=True)
            ],
            "segments": [
                {"name": s.name, "start_m": s.start_m, "end_m": s.end_m} for s in segments
            ],
        }
        if "x" in lap.channels and "y" in lap.channels:
            stride = max(1, round(TRACK_STEP_M / lap.step_m))
            out["track"] = {
                "distance": lap[schema.DISTANCE][::stride].tolist(),
                "x": lap["x"][::stride].tolist(),
                "y": lap["y"][::stride].tolist(),
            }
        return out

    def _write_traces(self, columns: dict[str, np.ndarray]) -> dict[str, Any]:
        directory = self.cache_dir / "traces"
        path = directory / f"{uuid.uuid4().hex}.f1soa"
        layout = write_soa(path, columns)
        old = sorted(directory.glob("*.f1soa"), key=lambda f: f.stat().st_mtime, reverse=True)
        for stale in old[self.keep_traces :]:
            with contextlib.suppress(OSError):  # Windows: still open in the app; next time
                stale.unlink(missing_ok=True)
        return {"path": str(path), "columns": layout}


def _error(rid: Any, code: int, message: str) -> dict[str, Any]:
    return {"jsonrpc": "2.0", "id": rid, "error": {"code": code, "message": message}}


class _Stdio:
    """Protocol transport: request lines in from stdin, reply lines out to `proto_out`.

    Normally asyncio pipes. Windows' proactor loop cannot attach to the anonymous pipes a
    parent process hands its child (nor can any loop to a regular file), so there a reader
    thread feeds lines to the loop and one writer thread writes replies in order: the loop
    itself never blocks on stdio either way.
    """

    def __init__(self, proto_out: int, threaded: bool) -> None:
        self.out = os.fdopen(proto_out, "wb", buffering=0)
        self.threaded = threaded
        self._reader: asyncio.StreamReader | None = None
        self._writer: asyncio.StreamWriter | None = None
        self._lines: asyncio.Queue[bytes] | None = None
        self._write_pool: ThreadPoolExecutor | None = None
        self._closed = False

    async def open(self) -> None:
        loop = asyncio.get_running_loop()
        if self.threaded:
            lines: asyncio.Queue[bytes] = asyncio.Queue()
            self._lines = lines
            self._write_pool = ThreadPoolExecutor(max_workers=1, thread_name_prefix="f1lap-out")

            def pump() -> None:  # daemon thread: blocking reads stay off the loop
                stdin = sys.stdin.buffer
                while True:
                    line = stdin.readline(MAX_LINE)
                    if len(line) == MAX_LINE and not line.endswith(b"\n"):
                        # Over-long: drop the rest rather than handle its pieces as requests.
                        while (rest := stdin.readline(MAX_LINE)) and not rest.endswith(b"\n"):
                            pass
                        line = b"<request over MAX_LINE dropped>\n"  # answered as a parse error
                    with contextlib.suppress(RuntimeError):  # loop closed: nothing to feed
                        loop.call_soon_threadsafe(lines.put_nowait, line)
                    if not line:
                        return

            threading.Thread(target=pump, name="f1lap-in", daemon=True).start()
            return
        reader = asyncio.StreamReader(limit=MAX_LINE)
        await loop.connect_read_pipe(lambda: asyncio.StreamReaderProtocol(reader), sys.stdin)
        self._reader = reader
        try:  # pipe / socket / tty: non-blocking transport with back-pressure
            transport, protocol = await loop.connect_write_pipe(
                asyncio.streams.FlowControlMixin, self.out)
            self._writer = asyncio.StreamWriter(transport, protocol, None, loop)
        except ValueError:  # regular file (e.g. `> log.txt`): writes never wait on a reader
            pass

    async def readline(self) -> bytes:
        """The next line, or b"" at EOF."""
        if self._lines is not None:
            return await self._lines.get()
        assert self._reader is not None
        return await self._reader.readline()

    def send(self, data: bytes) -> None:
        """Queues `data` without waiting (progress lines are tiny). Call from the loop."""
        if self._closed:  # a late progress line after shutdown: nobody is reading
            return
        if self._write_pool is not None:
            self._write_pool.submit(self.out.write, data)
        elif self._writer is not None:
            self._writer.write(data)
        else:
            self.out.write(data)

    async def write(self, data: bytes) -> None:
        """Writes `data`, waiting for the reader to take it."""
        if self._write_pool is not None:
            await asyncio.get_running_loop().run_in_executor(self._write_pool, self.out.write, data)
        elif self._writer is not None:
            self._writer.write(data)
            await self._writer.drain()
        else:
            self.out.write(data)

    def close(self) -> None:
        self._closed = True
        if self._write_pool is not None:
            self._write_pool.shutdown(wait=True)  # flush queued replies first
        if self._writer is not None:
            self._writer.close()
        else:
            self.out.close()


async def serve(server: Server, proto_out: int, threaded: bool | None = None) -> None:
    """Read requests from stdin until EOF; write each response as one line to `proto_out`.

    `threaded` picks thread-backed stdio (default: on Windows, or when `F1LAP_THREADED_STDIO`
    is set, which lets the Windows path be tested elsewhere).
    """
    if threaded is None:
        threaded = sys.platform == "win32" or bool(os.environ.get("F1LAP_THREADED_STDIO"))
    loop = asyncio.get_running_loop()
    io = _Stdio(proto_out, threaded)
    await io.open()
    pending: set[asyncio.Task[None]] = set()

    def notify(msg: dict[str, Any]) -> None:
        # Worker-thread progress hops onto the loop, so stdout is only ever written from there.
        with contextlib.suppress(RuntimeError):  # loop already closed: drop it
            loop.call_soon_threadsafe(io.send, encode(msg))

    server.notify = notify

    async def respond(line: str) -> None:
        reply = await server.handle(line)
        if reply is not None:
            await io.write(encode(reply))

    try:
        while line := await io.readline():
            if line.strip():
                # Bad UTF-8 becomes a parse error for that request, not the end of the server.
                task = asyncio.create_task(respond(line.decode(errors="replace")))
                pending.add(task)
                task.add_done_callback(pending.discard)
        if pending:
            await asyncio.gather(*pending)
    finally:
        server.close()
        io.close()


def encode(reply: dict[str, Any]) -> bytes:
    """One protocol line. Non-finite floats become null (strict JSON, as Swift's decoder needs);
    anything unserialisable becomes an internal error so the request still gets a reply."""
    try:
        text = json.dumps(_finite(reply), allow_nan=False)
    except (TypeError, ValueError) as exc:
        log.exception("unserialisable reply")
        text = json.dumps(_error(reply.get("id"), INTERNAL, f"unserialisable result: {exc}"))
    return text.encode() + b"\n"


def _finite(value: Any) -> Any:
    if isinstance(value, float | np.floating):
        return float(value) if np.isfinite(value) else None
    if isinstance(value, np.integer):
        return int(value)
    if isinstance(value, dict):
        return {k: _finite(v) for k, v in value.items()}
    if isinstance(value, list | tuple):
        return [_finite(v) for v in value]
    return value


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(prog="f1lap-server", description=__doc__.split("\n")[0])
    ap.add_argument("--cache-dir", type=Path, default=Path(os.environ.get(
        "F1LAP_CACHE_DIR", DEFAULT_CACHE)))
    ap.add_argument("--step", type=float, default=1.0, help="grid spacing in metres")
    args = ap.parse_args(argv)

    # Keep the real stdout for protocol messages; route every stray print to stderr.
    proto_out = os.dup(1)
    os.dup2(2, 1)
    sys.stdout = sys.stderr
    logging.basicConfig(level=logging.INFO, stream=sys.stderr,
                        format="%(asctime)s %(name)s %(levelname)s %(message)s")
    args.cache_dir.mkdir(parents=True, exist_ok=True)
    asyncio.run(serve(Server(args.cache_dir, args.step), proto_out))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
