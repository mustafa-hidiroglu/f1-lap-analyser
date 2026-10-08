"""The shipped perfect-lap base covers every season with telemetry (2018-2026)."""

from __future__ import annotations

import pytest

from f1lap import simbase
from f1lap.sim import MODEL_VERSION

# Competitive sessions (qualifying + race, plus sprint sessions) of a season, at the very least.
MIN_PER_SEASON = {year: 30 for year in range(2018, 2026)} | {2026: 20}  # 2026: season ongoing


@pytest.mark.parametrize("year", sorted(MIN_PER_SEASON))
def test_every_season_is_in_the_base(year: int) -> None:
    files = sorted((simbase.PACKAGE_BASE / str(year)).glob("*.parquet"))
    assert len(files) >= MIN_PER_SEASON[year], f"{year}: only {len(files)} perfect laps"
    events = {f.stem.split("__")[0] for f in files}
    assert len(events) >= MIN_PER_SEASON[year] // 2  # one per track, not one track many times


def test_base_files_load_with_the_current_model() -> None:
    for path in sorted(simbase.PACKAGE_BASE.glob("*/*.parquet"))[::25]:  # a sample: ~25 files
        sim = simbase.load(path)
        assert sim.version == MODEL_VERSION
        assert sim.fastest_lap_s is not None and sim.lap_time_s < sim.fastest_lap_s
        key = simbase.SimKey(sim.lap.meta.year or 0, sim.lap.meta.event, sim.lap.meta.session)
        assert simbase.PACKAGE_BASE / key.relpath == path  # the lookup key finds the file
