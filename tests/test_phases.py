"""Corner phase detection on a hand-built corner where every key point is known exactly.

Corner at 1000 m on a 2000 m lap (1 m grid):
  full throttle to 689 m, brake 700-940 m, speed 300 -> 100 km/h over 700-950 m,
  V-shaped minimum 100 km/h at 1000 m (102 at 950/1050), throttle 50 % from 990 m,
  full throttle from 1100 m, speed back to 300 km/h by 1400 m.
"""

from __future__ import annotations

import json
from pathlib import Path

import numpy as np
import pytest

from f1lap.circuit import Circuit, Corner, Segment, corner_segments
from f1lap.cli import main
from f1lap.delta import compare, corner_table
from f1lap.phases import PHASES, analyse_corners, compare_corners, corner_points
from f1lap.store import write_lap
from f1lap.trace import LapMeta, ResampledLap

SEG = Segment("T1", 0.0, 2000.0, (1000.0,))


def _lap(
    brake: bool = True, flat: bool = False, inputs: bool = True, time_scale: float = 1.0
) -> ResampledLap:
    d = np.arange(2001.0)
    if flat:
        speed = 290.0 - 5.0 * np.exp(-(((d - 1000.0) / 60.0) ** 2))
        throttle = np.full(d.size, 100.0)
        brk = np.zeros(d.size)
    else:
        speed = np.select(
            [d < 700, d < 950, d <= 1050, d < 1400],
            [300.0, 300.0 - 0.8 * (d - 700), 100.0 + 2.0 * np.abs(d - 1000) / 50.0,
             102.0 + 198.0 * (d - 1050) / 350.0],
            300.0,
        )
        throttle = np.select([d < 690, d < 990, d < 1100], [100.0, 0.0, 50.0], 100.0)
        brk = ((d >= 700) & (d <= 940)).astype(float) if brake else np.zeros(d.size)
    time = np.concatenate([[0.0], np.cumsum(1.0 / (speed[1:] / 3.6))]) * time_scale
    channels = {"distance": d, "time": time, "speed": speed}
    if inputs:
        channels |= {"throttle": throttle, "brake": brk}
    meta = LapMeta(driver="TST", raw_length_m=2000.0)
    return ResampledLap(channels, step_m=1.0, meta=meta)


def test_points_on_known_corner() -> None:
    p = corner_points(_lap(), SEG)
    assert (p.entry_m, p.brake_on_m, p.brake_off_m) == (689.0, 700.0, 940.0)
    assert (p.apex_m, p.apex_speed) == (1000.0, 100.0)
    assert (p.mid_start_m, p.mid_end_m) == (944.0, 1055.0)  # speed ≤ 105 km/h
    assert (p.pickup_m, p.full_throttle_m) == (990.0, 1100.0)
    assert p.entry_speed == 300.0 and p.exit_speed == pytest.approx(102 + 198 * 50 / 350)
    assert p.brake_applications == 1 and not p.flat


def test_lift_only_corner() -> None:
    p = corner_points(_lap(brake=False), SEG)
    assert p.brake_on_m is None and p.brake_off_m is None and p.brake_applications == 0
    assert p.entry_m == 689.0 and p.apex_m == 1000.0


def test_flat_corner_collapses_to_marker() -> None:
    p = corner_points(_lap(flat=True), SEG)
    assert p.flat
    assert {p.entry_m, p.mid_start_m, p.mid_end_m, p.full_throttle_m, p.apex_m} == {1000.0}


def test_brake_reapplication_counted_but_release_is_first_run() -> None:
    lap = _lap()
    brk = lap["brake"].copy()
    brk[1010:1020] = 1.0
    p = corner_points(ResampledLap({**lap.channels, "brake": brk}, 1.0, lap.meta), SEG)
    assert p.brake_off_m == 940.0 and p.brake_applications == 2


def test_speed_only_data() -> None:
    p = corner_points(_lap(inputs=False), SEG)
    assert p.apex_m == 1000.0 and (p.mid_start_m, p.mid_end_m) == (944.0, 1055.0)
    assert p.brake_on_m is None and not p.flat


def test_phase_deltas_sum_to_segment_delta() -> None:
    ref, slow = _lap(), _lap(time_scale=1.01)
    cmp = compare(ref, slow)
    [cc] = compare_corners(cmp, [SEG])
    assert cc.delta_s == pytest.approx(corner_table(cmp, [SEG]).delta_s[0], abs=1e-12)
    assert (cc.phase_delta_s > 0).all()  # uniformly slower -> loses time in every phase
    assert set(cc.to_dict()["phase_delta_s"]) == set(PHASES)


def test_analyse_corners_on_circuit_segments() -> None:
    lap = _lap()
    circuit = Circuit("Test", 2000.0, (Corner(1, 1000.0),))
    [p] = analyse_corners(lap, corner_segments(circuit, lap))
    assert p.name == "T1" and p.apex_m == 1000.0


def test_cli_delta_prints_and_exports_phases(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    ref = write_lap(_lap(), tmp_path / "ref.parquet")
    oth = write_lap(_lap(time_scale=1.01), tmp_path / "oth.parquet")
    circuit = Circuit("Test", 2000.0, (Corner(1, 1000.0),)).save(tmp_path / "c.json")
    out = tmp_path / "r.json"
    assert main(["delta", str(ref), str(oth), "--circuit", str(circuit), "--json", str(out)]) == 0
    assert "braking" in capsys.readouterr().out
    report = json.loads(out.read_text())
    assert report["corners"][0]["reference"]["brake_on_m"] == 700.0
