from __future__ import annotations

import importlib.util
import json
import math
from pathlib import Path
from types import ModuleType

import numpy as np
import pytest

from f1lap.server import default_cache_dir

ROOT = Path(__file__).parents[1]


def _load() -> ModuleType:
    spec = importlib.util.spec_from_file_location("web_export", ROOT / "tools" / "web_export.py")
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


we = _load()


def test_bin_round_trip(tmp_path: Path) -> None:
    path = tmp_path / "x.bin"
    time = np.array([0.0, 1.25, np.nan])
    speed = np.array([312.34, np.nan, 0.0])
    gear = np.array([8.0, 3.0, np.nan])  # 3 bytes: the next column must be re-aligned
    brake = np.array([0.0, 0.5, 1.0]) * 100
    rpm = np.array([11999.6, np.nan, 70000.0])  # out of range clips below the sentinel
    layout = we.write_bin(path, [
        ("A.time", "f32", 1.0, time),
        ("A.gear", "u8", 1.0, gear),
        ("A.speed", "u16", 0.1, speed),
        ("A.brake", "u8", 1.0, brake),
        ("A.rpm", "u16", 1.0, rpm),
    ])
    assert [c["dtype"] for c in layout] == ["f32", "u8", "u16", "u8", "u16"]
    assert all(c["offset"] % 4 == 0 and c["count"] == 3 for c in layout)
    assert layout[2]["scale"] == 0.1
    raw = path.read_bytes()
    assert np.frombuffer(raw, "<u1", 3, layout[1]["offset"])[2] == 255
    assert np.frombuffer(raw, "<u2", 3, layout[2]["offset"])[1] == 65535
    assert np.frombuffer(raw, "<u2", 3, layout[2]["offset"])[0] == 3123

    cols = we.read_bin(path, layout)
    np.testing.assert_allclose(cols["A.time"], time, equal_nan=True)
    np.testing.assert_allclose(cols["A.speed"], [312.3, np.nan, 0.0], equal_nan=True)
    np.testing.assert_array_equal(cols["A.gear"], gear)
    np.testing.assert_array_equal(cols["A.brake"], [0.0, 50.0, 100.0])
    np.testing.assert_array_equal(cols["A.rpm"], [12000.0, np.nan, 65534.0])
    assert not path.with_name("x.bin.tmp").exists()


def test_slugify() -> None:
    assert we.slugify("Italian Grand Prix") == "italian-grand-prix"
    assert we.slugify("São Paulo Grand Prix") == "sao-paulo-grand-prix"
    assert we.slugify("  Emilia Romagna  Grand Prix!") == "emilia-romagna-grand-prix"


def test_clean_strips_non_finite() -> None:
    out = we.clean({"a": float("nan"), "b": [np.float64(1.234567), np.inf], "c": np.int64(3)})
    assert out == {"a": None, "b": [1.2346, None], "c": 3}
    json.dumps(out, allow_nan=False)


def _cached_monza_q(cache: Path) -> bool:
    return any((cache / "2024").glob("2024-09-01_Italian_Grand_Prix/*Qualifying"))


@pytest.mark.skipif(not _cached_monza_q(default_cache_dir()),
                    reason="2024 Monza Q not in the FastF1 cache")
def test_export_cached_monza_q(tmp_path: Path) -> None:
    import fastf1

    cache = default_cache_dir()
    fastf1.Cache.offline_mode(True)  # cached only: never hit the network here
    try:
        event = next(e for e in we.schedule(2024, cache) if e["location"] == "Monza")
        server = we.Server(cache)
        try:
            doc = we.export_session(2024, event, "Q", tmp_path, cache, server)
        finally:
            server.close()
    finally:
        fastf1.Cache.offline_mode(False)

    folder = tmp_path / "2024" / "16-italian-grand-prix"
    on_disk = json.loads((folder / "Q.json").read_text())
    assert on_disk == doc
    assert doc["key"] == "Q" and doc["session"] == "Qualifying" and doc["step_m"] == 5
    assert doc["reference"]["driver"] == doc["fastest"] == "NOR"
    assert math.isclose(doc["length_m"], (doc["samples"] - 1) * 5, abs_tol=5)
    assert set(doc["circuit"]) >= {"name", "corners", "segments", "track", "rotation_deg"}
    assert len(doc["drivers"]) == len(doc["laps"]) == 20
    times = [d["lap_time_s"] for d in doc["drivers"]]
    assert times == sorted(times)
    lap = doc["laps"]["LEC"]
    assert set(lap) == {"metrics", "corners", "rating", "perfect"}
    assert "traces" not in lap["perfect"]
    assert len(lap["corners"][0]["bounds_m"]) == 4
    assert doc["perfect"]["available"] is True

    cols = we.read_bin(folder / "Q.bin", doc["binary"]["columns"])
    assert doc["binary"]["file"] == "Q.bin"
    names = {c["name"] for c in doc["binary"]["columns"]}
    assert {"NOR.time", "NOR.speed", "NOR.throttle", "NOR.brake", "NOR.gear", "NOR.rpm",
            "sim.time", "sim.speed", "sim.throttle", "sim.brake"} <= names
    assert all(v.size == doc["samples"] for v in cols.values())
    assert cols["NOR.time"][0] == 0 and abs(cols["NOR.time"][-1] - 79.3) < 0.2

    index = we.write_index(tmp_path, {(2024, 3, "R"): "boom"})
    [event_out] = index["seasons"][0]["events"]
    assert event_out["sessions"] == [{"key": "Q", "name": "Qualifying",
                                      "path": "2024/16-italian-grand-prix/Q.json", "drivers": 20}]
    assert index["failures"] == [{"year": 2024, "round": 3, "session": "R", "error": "boom"}]
