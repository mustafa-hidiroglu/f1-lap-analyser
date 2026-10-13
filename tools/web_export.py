"""Offline exporter for the static web app: precomputes every past Qualifying and Race session
into `web/public/data/` (see `.omc/autopilot/spec.md`, "Data contract").

    uv run python tools/web_export.py --years 2024 2025 2026 [--sessions Q R]
        [--out web/public/data] [--only "2024:Monza:Q"] [--force]

Per session: one JSON (circuit, drivers, per-driver metrics / corners / rating / perfect-lap
report) and one little-endian Structure-of-Arrays `.bin` with every driver's fastest lap on the
session reference lap's grid, thinned to `STEP_M`. Resumable: sessions already on disk are
skipped unless `--force`, and `index.json` is rebuilt from disk after every session.
"""

from __future__ import annotations

import argparse
import json
import logging
import os
import re
import sys
import time
import unicodedata
from dataclasses import asdict
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any, Final

import numpy as np
import numpy.typing as npt

from f1lap import schema
from f1lap.delta import align
from f1lap.explain import explain_session_lap
from f1lap.ingest.fastf1_source import pick_lap
from f1lap.metrics import lap_metrics
from f1lap.phases import analyse_corners
from f1lap.rating import rate_session_lap
from f1lap.resample import nominal_length
from f1lap.server import Server, default_cache_dir
from f1lap.session import LoadedSession
from f1lap.sim import SimError
from f1lap.trace import ResampledLap

STEP_M: Final = 5
SESSIONS: Final = {"Q": "Qualifying", "R": "Race"}
#: A session counts as past (data published) this long after its scheduled start.
SETTLE: Final = timedelta(hours=4)
ALIGN: Final = 4

#: dtype name -> (numpy dtype, missing-value sentinel; None = NaN)
DTYPES: Final[dict[str, tuple[np.dtype[Any], int | None]]] = {
    "f32": (np.dtype("<f4"), None),
    "u16": (np.dtype("<u2"), 0xFFFF),
    "u8": (np.dtype("<u1"), 0xFF),
}
#: Per-driver channels: suffix -> (dtype, scale). Value = raw * scale.
LAP_COLUMNS: Final = {
    "time": ("f32", 1.0),
    "speed": ("u16", 0.1),
    "throttle": ("u8", 1.0),
    "brake": ("u8", 1.0),
    "gear": ("u8", 1.0),
    "rpm": ("u16", 1.0),
}
SIM_COLUMNS: Final = ("time", "speed", "throttle", "brake")

log = logging.getLogger("web_export")


# -- binary SoA ---------------------------------------------------------------------------------


def encode_column(values: npt.ArrayLike, dtype: str, scale: float) -> npt.NDArray[Any]:
    """`values / scale` as `dtype`; NaN becomes NaN (floats) or the dtype's max (ints)."""
    np_dtype, sentinel = DTYPES[dtype]
    v = np.asarray(values, dtype=np.float64) / scale
    if sentinel is None:
        return v.astype(np_dtype)
    finite = np.isfinite(v)
    raw = np.clip(np.round(np.where(finite, v, 0.0)), 0, sentinel - 1)
    return np.where(finite, raw, sentinel).astype(np_dtype)


def write_bin(
    path: Path, columns: list[tuple[str, str, float, npt.ArrayLike]]
) -> list[dict[str, Any]]:
    """Write `(name, dtype, scale, values)` columns atomically at 4-byte-aligned offsets;
    returns the layout for the session JSON."""
    layout: list[dict[str, Any]] = []
    chunks: list[bytes] = []
    offset = 0
    for name, dtype, scale, values in columns:
        arr = encode_column(values, dtype, scale)
        pad = -offset % ALIGN
        chunks.append(b"\0" * pad)
        offset += pad
        layout.append({"name": name, "dtype": dtype, "offset": offset, "count": int(arr.size),
                       "scale": scale})
        chunks.append(arr.tobytes())
        offset += arr.nbytes
    _atomic_write(path, b"".join(chunks))
    return layout


def read_bin(path: Path, layout: list[dict[str, Any]]) -> dict[str, npt.NDArray[np.float64]]:
    """Decoded columns (float64, sentinels as NaN), as the web client reads them."""
    raw = path.read_bytes()
    out: dict[str, npt.NDArray[np.float64]] = {}
    for col in layout:
        np_dtype, sentinel = DTYPES[col["dtype"]]
        arr = np.frombuffer(raw, dtype=np_dtype, count=col["count"], offset=col["offset"])
        v = arr.astype(np.float64) * col["scale"]
        if sentinel is not None:
            v[arr == sentinel] = np.nan
        out[col["name"]] = v
    return out


# -- JSON ---------------------------------------------------------------------------------------


def slugify(text: str) -> str:
    ascii_text = unicodedata.normalize("NFKD", text).encode("ascii", "ignore").decode()
    return re.sub(r"[^a-z0-9]+", "-", ascii_text.lower()).strip("-")


def clean(value: Any, digits: int = 4) -> Any:
    """JSON-safe copy: non-finite floats -> None, floats rounded, numpy scalars unwrapped."""
    if isinstance(value, bool | np.bool_):
        return bool(value)
    if isinstance(value, float | np.floating):
        return round(float(value), digits) if np.isfinite(value) else None
    if isinstance(value, np.integer):
        return int(value)
    if isinstance(value, dict):
        return {str(k): clean(v, digits) for k, v in value.items()}
    if isinstance(value, list | tuple):
        return [clean(v, digits) for v in value]
    return value


def _atomic_write(path: Path, data: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(path.name + ".tmp")
    tmp.write_bytes(data)
    os.replace(tmp, path)


def _write_json(path: Path, obj: Any) -> None:
    text = json.dumps(obj, separators=(",", ":"), allow_nan=False, ensure_ascii=False)
    _atomic_write(path, text.encode())


# -- schedule -----------------------------------------------------------------------------------


def schedule(year: int, cache_dir: Path) -> list[dict[str, Any]]:
    """Events of `year` with the start (UTC) of each Q/R session."""
    import fastf1

    fastf1.Cache.enable_cache(str(cache_dir))
    fastf1.set_log_level("WARNING")
    sch = fastf1.get_event_schedule(year, include_testing=False)
    events = []
    for row in sch.itertuples(index=False):
        starts: dict[str, datetime | None] = {}
        for i in range(1, 6):
            name = getattr(row, f"Session{i}", None)
            key = next((k for k, v in SESSIONS.items() if v == name), None)
            if key is not None:
                start = getattr(row, f"Session{i}DateUtc", None)
                starts[key] = None if start is None or start != start else (
                    start.to_pydatetime().replace(tzinfo=UTC))
        events.append({
            "round": int(row.RoundNumber),
            "name": str(row.EventName),
            "country": str(row.Country),
            "location": str(row.Location),
            "date": row.EventDate.date().isoformat(),
            "slug": f"{int(row.RoundNumber):02d}-{slugify(str(row.EventName))}",
            "starts": starts,
        })
    return events


def _matches(event: dict[str, Any], query: str) -> bool:
    q = query.strip().lower()
    if q.isdigit():
        return int(q) == int(event["round"])
    return any(q in str(event[k]).lower() for k in ("name", "location", "country"))


# -- one session --------------------------------------------------------------------------------


def _grid(values: npt.NDArray[Any], stride: int) -> npt.NDArray[np.float64]:
    return np.asarray(values[::stride], dtype=np.float64)


def _lap_columns(lap: ResampledLap, stride: int) -> dict[str, npt.NDArray[np.float64]]:
    """The web channels of an aligned lap (missing channels as NaN; brake as 0-100)."""
    n = len(lap.channels[schema.DISTANCE][::stride])
    out = {}
    for name in LAP_COLUMNS:
        v = _grid(lap[name], stride) if name in lap.channels else np.full(n, np.nan)
        if name == "brake" and np.isfinite(v).any() and np.nanmax(v) <= 1.0:
            v = v * 100.0  # on/off (or interpolated 0-1) brake -> percent
        out[name] = v
    return out


def _perfect(sd: LoadedSession, driver: str) -> dict[str, Any]:
    """`explain_session_lap(...).to_dict()`, or `{"error": ...}` (as `Server._perfect`)."""
    try:
        return explain_session_lap(sd, driver, "fastest").to_dict()
    except SimError as exc:
        return {"error": str(exc)}
    except Exception as exc:
        log.exception("perfect-lap comparison failed for %s", driver)
        return {"error": f"perfect-lap comparison failed: {type(exc).__name__}: {exc}"}


def _circuit(server: Server, sd: LoadedSession) -> dict[str, Any]:
    out: dict[str, Any] = clean(server._circuit(sd, sd.reference))
    if "track" in out:
        out["track"] = {k: clean(v, 1) for k, v in out["track"].items()}
    return out


def export_session(
    year: int, event: dict[str, Any], key: str, out_dir: Path, cache_dir: Path, server: Server,
) -> dict[str, Any]:
    """Load, analyse and write one session; returns the session JSON (already on disk)."""
    sd = LoadedSession.load(year, event["round"], SESSIONS[key], cache_dir=cache_dir)
    ref = sd.reference
    stride = max(1, round(STEP_M / sd.step_m))
    samples = len(ref.channels[schema.DISTANCE][::stride])

    drivers: list[dict[str, Any]] = []
    laps: dict[str, Any] = {}
    columns: list[tuple[str, str, float, npt.ArrayLike]] = []
    for r in sd.ses.results.itertuples(index=False):
        code = str(r.Abbreviation)
        try:
            lap = align(ref, sd.lap(code, "fastest"))
            row = pick_lap(sd.ses.laps, code, "fastest")
            entry = {
                "metrics": lap_metrics(lap, sd.segments).to_dict(),
                "corners": [asdict(c) | {"bounds_m": list(c.bounds_m)}
                            for c in analyse_corners(lap, sd.segments)],
                "rating": rate_session_lap(sd, code, "fastest").to_dict(),
            }
        except Exception as exc:  # one driver must not sink the session
            log.warning("  skip %s: %s: %s", code, type(exc).__name__, exc)
            continue
        entry["perfect"] = _perfect(sd, code)
        laps[code] = entry
        compound = row["Compound"]
        drivers.append({
            "code": code,
            "team": str(r.TeamName),
            "color": f"#{r.TeamColor}" if isinstance(r.TeamColor, str) and r.TeamColor else None,
            "position": None if r.Position != r.Position else int(r.Position),
            "lap_number": lap.meta.lap_number,
            "lap_time_s": lap.meta.lap_time_s,
            "compound": compound if isinstance(compound, str) else None,
        })
        for name, values in _lap_columns(lap, stride).items():
            dtype, scale = LAP_COLUMNS[name]
            columns.append((f"{code}.{name}", dtype, scale, values))
    if not drivers:
        raise RuntimeError("no driver lap could be exported")
    drivers.sort(key=lambda d: d["lap_time_s"] if d["lap_time_s"] is not None else np.inf)

    try:
        sim = align(ref, sd.sim.lap)
        perfect: dict[str, Any] = {"available": True, "sim_lap_time_s": sd.sim.lap_time_s}
        sim_cols = _lap_columns(sim, stride)
        for name in SIM_COLUMNS:
            dtype, scale = LAP_COLUMNS[name]
            columns.append((f"sim.{name}", dtype, scale, sim_cols[name]))
    except Exception as exc:
        perfect = {"available": False, "error": str(exc)}

    folder = out_dir / str(year) / event["slug"]
    layout = write_bin(folder / f"{key}.bin", columns)
    doc: dict[str, Any] = clean({
        "year": year,
        "round": event["round"],
        "event": event["name"],
        "location": event["location"],
        "country": event["country"],
        "date": event["date"],
        "session": SESSIONS[key],
        "key": key,
        "step_m": STEP_M,
        "samples": samples,
        "length_m": nominal_length(ref),
        "fastest": drivers[0]["code"],
        "reference": {
            "driver": ref.meta.driver,
            "lap_number": ref.meta.lap_number,
            "lap_time_s": ref.meta.lap_time_s,
        },
        "drivers": drivers,
        "laps": laps,
        "perfect": perfect,
        "binary": {"file": f"{key}.bin", "columns": layout},
    })
    doc["circuit"] = _circuit(server, sd)
    _write_json(folder / f"{key}.json", doc)
    return doc


# -- index --------------------------------------------------------------------------------------


def write_index(out_dir: Path, failures: dict[tuple[int, int, str], str]) -> dict[str, Any]:
    """Rebuild `index.json` from the sessions on disk plus `failures` (minus exported ones)."""
    seasons: dict[int, dict[int, dict[str, Any]]] = {}
    done: set[tuple[int, int, str]] = set()
    for path in sorted(out_dir.glob("*/*/*.json")):
        key = path.stem
        if key not in SESSIONS or not path.with_suffix(".bin").exists():
            continue
        try:
            doc = json.loads(path.read_text())
        except (OSError, ValueError):
            continue
        year, rnd = int(doc["year"]), int(doc["round"])
        done.add((year, rnd, key))
        event = seasons.setdefault(year, {}).setdefault(rnd, {
            "round": rnd,
            "name": doc["event"],
            "country": doc.get("country"),
            "location": doc["location"],
            "date": doc.get("date"),
            "slug": path.parent.name,
            "sessions": [],
        })
        event["sessions"].append({
            "key": key,
            "name": SESSIONS[key],
            "path": path.relative_to(out_dir).as_posix(),
            "drivers": len(doc["drivers"]),
        })
    for events in seasons.values():
        for ev in events.values():
            ev["sessions"].sort(key=lambda s: list(SESSIONS).index(s["key"]))
    index = {
        "generated_at": datetime.now(UTC).isoformat(timespec="seconds"),
        "step_m": STEP_M,
        "seasons": [
            {"year": y, "events": [seasons[y][r] for r in sorted(seasons[y])]}
            for y in sorted(seasons, reverse=True)
        ],
        "failures": [
            {"year": y, "round": r, "session": k, "error": e}
            for (y, r, k), e in sorted(failures.items()) if (y, r, k) not in done
        ],
    }
    _write_json(out_dir / "index.json", index)
    return index


def _load_failures(out_dir: Path) -> dict[tuple[int, int, str], str]:
    try:
        index = json.loads((out_dir / "index.json").read_text())
        return {(int(f["year"]), int(f["round"]), str(f["session"])): str(f["error"])
                for f in index.get("failures", [])}
    except (OSError, ValueError, KeyError, TypeError):
        return {}


# -- CLI ----------------------------------------------------------------------------------------


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--years", type=int, nargs="+", default=[2024, 2025, 2026])
    ap.add_argument("--sessions", nargs="+", choices=list(SESSIONS), default=list(SESSIONS))
    ap.add_argument("--out", type=Path, default=Path("web/public/data"))
    ap.add_argument("--only", help='one session, "YEAR:EVENT:Q|R" (EVENT = round or name part)')
    ap.add_argument("--force", action="store_true", help="re-export sessions already on disk")
    ap.add_argument("--cache-dir", type=Path, default=Path(os.environ.get(
        "F1LAP_CACHE_DIR", default_cache_dir())))
    args = ap.parse_args(argv)
    logging.basicConfig(level=logging.INFO, stream=sys.stdout, format="%(message)s")
    logging.getLogger("fastf1").setLevel(logging.WARNING)

    years, keys, query = args.years, args.sessions, None
    if args.only:
        y, query, k = args.only.split(":")
        years, keys = [int(y)], [k.upper()]
    out_dir: Path = args.out
    out_dir.mkdir(parents=True, exist_ok=True)
    failures = _load_failures(out_dir)
    server = Server(args.cache_dir)
    now = datetime.now(UTC)
    t_run = time.monotonic()
    exported = skipped = failed = 0
    try:
        for year in years:
            try:
                events = schedule(year, args.cache_dir)
            except Exception as exc:
                log.error("%d: schedule failed: %s: %s", year, type(exc).__name__, exc)
                continue
            for event in events:
                if query is not None and not _matches(event, query):
                    continue
                for key in keys:
                    start = event["starts"].get(key)
                    label = f"{year} R{event['round']:02d} {event['name']} {key}"
                    if start is None or start + SETTLE > now:
                        continue  # not held (yet)
                    folder = out_dir / str(year) / event["slug"]
                    if not args.force and (folder / f"{key}.json").exists() and (
                            folder / f"{key}.bin").exists():
                        skipped += 1
                        continue
                    log.info("%s: exporting", label)
                    t0 = time.monotonic()
                    try:
                        doc = export_session(year, event, key, out_dir, args.cache_dir, server)
                    except Exception as exc:  # one session must never abort the run
                        failed += 1
                        failures[(year, event["round"], key)] = f"{type(exc).__name__}: {exc}"
                        log.error("%s: FAILED after %.0f s: %s: %s", label,
                                  time.monotonic() - t0, type(exc).__name__, exc)
                    else:
                        exported += 1
                        failures.pop((year, event["round"], key), None)
                        size_j = (folder / f"{key}.json").stat().st_size
                        size_b = (folder / f"{key}.bin").stat().st_size
                        log.info("%s: %d drivers, perfect=%s, %.0f KB json + %.0f KB bin in %.1f s",
                                 label, len(doc["drivers"]), doc["perfect"]["available"],
                                 size_j / 1024, size_b / 1024, time.monotonic() - t0)
                    write_index(out_dir, failures)
    finally:
        server.close()
    write_index(out_dir, failures)
    log.info("done in %.0f s: %d exported, %d already on disk, %d failed",
             time.monotonic() - t_run, exported, skipped, failed)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
