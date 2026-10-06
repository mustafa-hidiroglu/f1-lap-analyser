"""Sidecar protocol tests. Sessions are faked with synthetic laps (no FastF1 / network)."""

from __future__ import annotations

import asyncio
import json
import subprocess
import sys
from functools import cached_property
from pathlib import Path
from typing import Any

import numpy as np
import pytest
from conftest import MakeLap

from f1lap.binary import read_soa, write_soa
from f1lap.circuit import Circuit, Corner, Segment, corner_segments
from f1lap.resample import resample_to_distance
from f1lap.server import INVALID_PARAMS, METHOD_NOT_FOUND, PARSE_ERROR, Server, encode
from f1lap.trace import LapMeta, LapTrace, ResampledLap


class FakeSession:
    """Duck-types `LoadedSession` with three synthetic drivers."""

    def __init__(self, make_lap: MakeLap) -> None:
        self._laps: dict[str, ResampledLap] = {}
        for seed, (drv, scale) in enumerate((("AAA", 1.0), ("BBB", 1.01), ("CCC", 1.02))):
            t = make_lap(seed=seed)
            meta = LapMeta(driver=drv, lap_number=seed + 1,
                           lap_time_s=float(t["time"][-1] * scale))
            trace = LapTrace({**t.channels, "time": t["time"] * scale}, meta)
            self._laps[drv] = resample_to_distance(trace, 1.0)

    def lap(self, driver: str, lap: Any = "fastest") -> ResampledLap:
        if driver not in self._laps:
            raise LookupError(f"no laps for driver {driver!r}")
        return self._laps[driver]

    @property
    def valid_laps(self) -> list[ResampledLap]:
        return list(self._laps.values())

    @property
    def reference(self) -> ResampledLap:
        return self._laps["AAA"]

    @cached_property
    def circuit(self) -> Circuit:
        corners = (Corner(1, 625.0), Corner(2, 1875.0), Corner(3, 3125.0), Corner(4, 4375.0))
        return Circuit("Synthetic", 5000.0, corners, source="test")

    @property
    def segments(self) -> list[Segment]:
        return corner_segments(self.circuit, self.reference)

    def info(self) -> dict[str, Any]:
        return {"event": "Synthetic", "drivers": [{"code": d} for d in self._laps]}


SES: dict[str, Any] = {"year": 2024, "event": "Synthetic", "session": "Q"}


@pytest.fixture
def server(make_lap: MakeLap, tmp_path: Path) -> Server:
    srv = Server(tmp_path, keep_traces=2)
    srv._sessions[(2024, "synthetic", "q")] = FakeSession(make_lap)  # type: ignore[assignment]
    return srv


def _rpc(server: Server, method: str, rid: int | None = 1, **params: Any) -> dict[str, Any]:
    msg: dict[str, Any] = {"jsonrpc": "2.0", "method": method, "params": params}
    if rid is not None:
        msg["id"] = rid
    reply = asyncio.run(server.handle(json.dumps(msg)))
    assert reply is not None
    # Every reply must survive the strict encoder the app relies on.
    return dict(json.loads(encode(reply)))


def test_ping(server: Server) -> None:
    assert _rpc(server, "ping")["result"]["protocol"] == 1


@pytest.mark.parametrize(
    ("raw", "code"),
    [
        ("not json", PARSE_ERROR),
        ('{"jsonrpc": "2.0", "id": 1, "method": "nope"}', METHOD_NOT_FOUND),
        ('{"jsonrpc": "2.0", "id": 1, "method": "rate", "params": []}', INVALID_PARAMS),
        ('{"jsonrpc": "2.0", "id": 1, "method": "rate", "params": {"year": "x"}}',
         INVALID_PARAMS),
        ('{"jsonrpc": "1.0", "id": 1, "method": "ping"}', -32600),
    ],
)
def test_errors(server: Server, raw: str, code: int) -> None:
    reply = asyncio.run(server.handle(raw))
    assert reply is not None and reply["error"]["code"] == code


def test_notification_gets_no_reply(server: Server) -> None:
    raw = json.dumps({"jsonrpc": "2.0", "method": "ping"})
    assert asyncio.run(server.handle(raw)) is None


def test_app_error_for_unknown_driver(server: Server) -> None:
    reply = _rpc(server, "compare", **SES, reference={"driver": "ZZZ"}, other={"driver": "AAA"})
    assert reply["error"]["code"] == -32000 and "ZZZ" in reply["error"]["message"]


def test_bad_lap_selector(server: Server) -> None:
    reply = _rpc(server, "rate", **SES, driver="AAA", lap="slowest")
    assert reply["error"]["code"] == INVALID_PARAMS


def test_compare(server: Server) -> None:
    res = _rpc(server, "compare", **SES, reference={"driver": "AAA"},
               other={"driver": "BBB", "lap": 2})["result"]
    assert res["final_delta_s"] > 0  # BBB is 1 % slower
    assert [c["name"] for c in res["corners"]] == ["T1", "T2", "T3", "T4"]
    assert len(res["metrics"]) == 2 and len(res["circuit"]["track"]["x"]) > 900
    cols = read_soa(Path(res["traces"]["path"]), res["traces"]["columns"])
    np.testing.assert_allclose(cols["delta"][-1], res["final_delta_s"])
    assert cols["ref.gear"].dtype == np.int16 and cols["oth.speed"].size == cols["distance"].size


def test_trace_files_are_pruned(server: Server) -> None:
    for _ in range(4):
        _rpc(server, "compare", **SES, reference={"driver": "AAA"}, other={"driver": "CCC"})
    assert len(list((server.cache_dir / "traces").glob("*.f1soa"))) == 2


def test_rate(server: Server) -> None:
    res = _rpc(server, "rate", **SES, driver="BBB")["result"]
    assert res["driver"] == "BBB" and res["drivers"] == 3
    assert res["score"] == pytest.approx(50.0)  # beats CCC, loses to AAA everywhere
    assert res["reference"]["driver"] == "AAA"


def test_encode_replaces_non_finite() -> None:
    line = encode({"jsonrpc": "2.0", "id": 1, "result": {"a": float("nan"), "b": [np.inf, 1]}})
    assert json.loads(line)["result"] == {"a": None, "b": [None, 1]}


def test_soa_roundtrip(tmp_path: Path) -> None:
    cols = {"f": np.linspace(0, 1, 7), "g": np.array([1, 2, 3], dtype=np.int64)}
    layout = write_soa(tmp_path / "x.f1soa", cols)
    assert all(c["offset"] % 8 == 0 for c in layout)
    back = read_soa(tmp_path / "x.f1soa", layout)
    np.testing.assert_array_equal(back["f"], cols["f"])
    assert back["g"].dtype == np.int16 and back["g"].tolist() == [1, 2, 3]


@pytest.mark.parametrize("stdout_kind", ["pipe", "file"])
def test_stdio_process(tmp_path: Path, stdout_kind: str) -> None:
    requests = "\n".join([
        json.dumps({"jsonrpc": "2.0", "id": 1, "method": "ping"}),
        "garbage",
        json.dumps({"jsonrpc": "2.0", "method": "ping"}),  # notification: no reply
    ]) + "\n"
    cmd = [sys.executable, "-m", "f1lap.server", "--cache-dir", str(tmp_path)]
    if stdout_kind == "pipe":
        out = subprocess.run(cmd, input=requests.encode(), capture_output=True, timeout=60).stdout
    else:
        with (tmp_path / "out.txt").open("wb") as fh:
            subprocess.run(cmd, input=requests.encode(), stdout=fh, stderr=subprocess.DEVNULL,
                           timeout=60, check=True)
        out = (tmp_path / "out.txt").read_bytes()
    lines = [json.loads(x) for x in out.decode().splitlines()]
    assert [x.get("id") for x in lines] == [1, None]  # stdout carries protocol lines only
    assert lines[1]["error"]["code"] == PARSE_ERROR


def test_compare_sides_from_different_sessions(server: Server, make_lap: MakeLap) -> None:
    other = FakeSession(make_lap)
    server._sessions[(2026, "synthetic", "q")] = other  # type: ignore[assignment]
    res = _rpc(server, "compare", **SES, reference={"driver": "AAA"},
               other={"driver": "AAA", "year": 2026})["result"]
    assert res["final_delta_s"] == pytest.approx(0.0, abs=1e-9)  # same synthetic lap
    assert list(server._sessions)[-1] == (2026, "synthetic", "q")  # other side used its year


def test_progress_notifications(server: Server) -> None:
    sent: list[dict[str, Any]] = []
    server.notify = sent.append
    server._progress("Reading laps", 25, 900)
    assert sent == [{"jsonrpc": "2.0", "method": "progress",
                     "params": {"message": "Reading laps", "done": 25, "total": 900}}]
