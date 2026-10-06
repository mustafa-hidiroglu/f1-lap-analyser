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
