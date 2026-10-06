from __future__ import annotations

import json
from pathlib import Path

import numpy as np
import pytest
from conftest import MakeLap

from f1lap.cli import main
from f1lap.delta import compare, micro_sectors, summary
from f1lap.resample import nominal_length, resample_to_distance, rescale
from f1lap.store import write_lap
from f1lap.trace import LapMeta, LapTrace, ResampledLap


def _constant_speed_lap(
    speed_kmh: float, length: float = 1000.0, step: float = 1.0, lap_time: float | None = None
) -> ResampledLap:
    d = np.linspace(0.0, length, 201)
    trace = LapTrace(
        {"distance": d, "time": d / (speed_kmh / 3.6), "speed": np.full(d.size, speed_kmh)},
        LapMeta(driver=f"V{int(speed_kmh)}", lap_time_s=lap_time),
    )
    return resample_to_distance(trace, step)


def test_identical_laps_have_zero_delta(make_lap: MakeLap) -> None:
    lap = resample_to_distance(make_lap(), 1.0)
    cmp = compare(lap, lap)
    assert not cmp.delta_s.any()
    assert not micro_sectors(cmp).delta_s.any()


def test_constant_speed_delta_is_analytic() -> None:
    ref, oth = _constant_speed_lap(200.0), _constant_speed_lap(180.0)
    cmp = compare(ref, oth)
    d = cmp.distance
    np.testing.assert_allclose(cmp.delta_s, d / 50.0 - d / (200 / 3.6), atol=1e-9)
    assert cmp.final_delta_s > 0  # slower lap -> positive delta


def test_sector_deltas_sum_to_final_delta(make_lap: MakeLap) -> None:
    # Same sampling, other lap uniformly 1% slower -> delta(d) = 0.01 * t_ref(d).
    ref = resample_to_distance(make_lap(seed=1), 1.0)
    oth_trace = make_lap(seed=1)
    slow = LapTrace({**oth_trace.channels, "time": oth_trace["time"] * 1.01}, oth_trace.meta)
    cmp = compare(ref, resample_to_distance(slow, 1.0))
    sectors = micro_sectors(cmp, 25)
    assert len(sectors) == 25
    assert sectors.start_m[0] == 0.0 and sectors.end_m[-1] == cmp.distance[-1]
    np.testing.assert_array_equal(sectors.start_m[1:], sectors.end_m[:-1])
    assert sectors.delta_s.sum() == pytest.approx(cmp.final_delta_s, abs=1e-9)
    np.testing.assert_allclose(cmp.delta_s, 0.01 * ref["time"], atol=1e-9)


def test_sector_min_speed_matches_brute_force(make_lap: MakeLap) -> None:
    lap = resample_to_distance(make_lap(), 1.0)
    sectors = micro_sectors(compare(lap, lap), 7)
    d = lap["distance"]
    for i in range(len(sectors)):
        hi = d < sectors.end_m[i] if i < len(sectors) - 1 else np.ones(d.size, bool)
        mask = (d >= sectors.start_m[i]) & hi
        assert sectors.ref_min_speed[i] == lap["speed"][mask].min()


@pytest.mark.parametrize("count", [0, 10_000])
def test_sector_count_bounds(count: int) -> None:
    lap = _constant_speed_lap(200.0)
    with pytest.raises(ValueError, match="sector count"):
        micro_sectors(compare(lap, lap), count)


def test_compare_rescales_other_to_reference(make_lap: MakeLap) -> None:
    ref = resample_to_distance(make_lap(length=5000.0), 1.0)
    oth = resample_to_distance(make_lap(length=5100.0), 0.5)
    cmp = compare(ref, oth)
    assert len(cmp.other) == len(ref) and cmp.other.step_m == ref.step_m
    assert cmp.other.meta.normalised_to_m == 5000.0
    assert cmp.other.meta.raw_length_m == pytest.approx(5100.0)
    assert cmp.reference is ref  # reference never altered


def test_rescale_to_own_length_is_identity(make_lap: MakeLap) -> None:
    lap = resample_to_distance(make_lap(), 1.0)
    same = rescale(lap, nominal_length(lap))
    for name in lap.channels:
        np.testing.assert_allclose(same[name], lap[name], atol=1e-9)


def test_summary_is_json_serialisable() -> None:
    ref = _constant_speed_lap(200.0, lap_time=18.0)
    oth = _constant_speed_lap(190.0, lap_time=18.9)
    cmp = compare(ref, oth)
    report = json.loads(json.dumps(summary(cmp, micro_sectors(cmp, 4))))
    assert report["lap_time_delta_s"] == pytest.approx(0.9)
    assert report["max_loss_at_m"] == 1000.0 and report["max_gain_s"] == 0.0
    assert len(report["sectors"]) == 4


def test_cli_delta(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    ref = write_lap(_constant_speed_lap(200.0), tmp_path / "ref.parquet")
    oth = write_lap(_constant_speed_lap(180.0), tmp_path / "oth.parquet")
    out = tmp_path / "report.json"
    assert main(["delta", str(ref), str(oth), "--sectors", "5", "--json", str(out)]) == 0
    printed = capsys.readouterr().out
    assert "delta at line +2.000 s" in printed
    assert json.loads(out.read_text())["final_delta_s"] == pytest.approx(2.0)


def test_rescale_extrapolates_time_past_last_sample() -> None:
    # Stored grid stops at 1000 m of a 1000.9 m lap; stretching to 1001.5 m puts grid point
    # 1001 past the last stored sample. Time must keep advancing at 50 m/s, not hold.
    lap = _constant_speed_lap(180.0, length=1000.9)
    assert lap.grid_end_m == 1000.0
    stretched = rescale(lap, 1001.5)
    expected = 1001.0 * (1000.9 / 1001.5) / 50.0
    assert stretched["time"][-1] == pytest.approx(expected, abs=1e-9)
