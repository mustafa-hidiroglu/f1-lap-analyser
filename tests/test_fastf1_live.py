"""Live FastF1 test. Skipped by default; run with `uv run pytest -m network`."""

from __future__ import annotations

import asyncio
from pathlib import Path

import numpy as np
import pytest

from f1lap.ingest.fastf1_source import fetch_lap_async
from f1lap.resample import resample_to_distance

pytestmark = pytest.mark.network


def test_fetch_and_resample_real_lap() -> None:
    cache = Path(__file__).parents[1] / "cache"
    trace = asyncio.run(fetch_lap_async(2024, "Monza", "Q", "LEC", cache_dir=cache))
    assert trace.meta.lap_time_s is not None and 75 < trace.meta.lap_time_s < 90

    lap = resample_to_distance(trace, step_m=1.0)
    assert lap.meta.raw_length_m is not None and 5600 < lap.meta.raw_length_m < 5900  # ~5.79 km
    assert lap.meta.event == "Italian Grand Prix" and lap.meta.year == 2024
    assert np.isfinite(lap["time"]).all()
    assert np.all(np.diff(lap["time"]) > 0)


def test_monza_circuit_from_fastf1() -> None:
    from f1lap.circuit import detect_corners
    from f1lap.ingest.fastf1_source import circuit_from_session, lap_from_session, load_session

    ses = load_session(2024, "Monza", "Q", cache_dir=Path(__file__).parents[1] / "cache")
    circuit = circuit_from_session(ses)
    assert len(circuit.corners) == 11 and circuit.corners[0].x is not None
    lap = resample_to_distance(lap_from_session(ses, "LEC"), 1.0)
    pos = circuit.positions_on(lap)
    # Every detected braking corner lies near a FastF1 marker. Markers are hand-placed labels,
    # not apexes: Parabolica's (T11) sits 52 m after the lap's slowest point.
    for c in detect_corners(lap).corners:
        assert np.abs(pos - c.distance_m).min() < 60.0


def test_monza_corner_phases() -> None:
    from f1lap.circuit import corner_segments
    from f1lap.delta import compare
    from f1lap.ingest.fastf1_source import circuit_from_session, lap_from_session, load_session
    from f1lap.phases import compare_corners

    ses = load_session(2024, "Monza", "Q", cache_dir=Path(__file__).parents[1] / "cache")
    ref = resample_to_distance(lap_from_session(ses, "LEC"), 1.0)
    oth = resample_to_distance(lap_from_session(ses, "SAI"), 1.0)
    cmp = compare(ref, oth)
    corners = compare_corners(cmp, corner_segments(circuit_from_session(ses), ref))
    by_name = {c.segment.name: c for c in corners}
    assert by_name["T3"].reference.flat  # Curva Grande is flat out
    assert by_name["T1-2"].reference.apex_speed < 90  # first chicane
    assert sum(c.delta_s for c in corners) == pytest.approx(cmp.final_delta_s, abs=1e-9)
    assert cmp.final_delta_s == pytest.approx(cmp.lap_time_delta_s, abs=0.003)


def test_monza_lap_rating() -> None:
    from f1lap.rating import rate_fastf1_lap_async

    cache = Path(__file__).parents[1] / "cache"
    r = asyncio.run(rate_fastf1_lap_async(2024, "Monza", "Q", "LEC", cache_dir=cache))
    assert r.lap_time_s == pytest.approx(79.461, abs=1e-3)  # segment sums = official time
    assert r.drivers == 20 and r.laps > 50
    assert r.ultimate_s < 79.327 <= r.lap_time_s  # below pole; LEC was P3
    assert r.theoretical_best_s <= r.lap_time_s and 0 <= r.score <= 100
