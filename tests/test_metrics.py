"""Driver metrics on the hand-built corner from test_phases (see its docstring)."""

from __future__ import annotations

import json
from pathlib import Path

import numpy as np
import pytest
from test_phases import SEG, _lap

from f1lap.circuit import Circuit, Corner
from f1lap.cli import main
from f1lap.metrics import G, deceleration, lap_metrics
from f1lap.phases import has_pressure
from f1lap.store import write_lap
from f1lap.trace import ResampledLap


def _with(lap: ResampledLap, **channels: np.ndarray) -> ResampledLap:
    return ResampledLap({**lap.channels, **channels}, lap.step_m, lap.meta)


def test_lap_input_shares() -> None:
    lap = _lap()
    t = lap["time"]
    m = lap_metrics(lap)
    # full: d < 690 and d >= 1100; braking: 700-940; coasting (throttle 0, brake off): 690-700
    # and 941-990. Interval i is classified by its starting sample.
    assert m.full_throttle_s == pytest.approx(t[690] - t[0] + t[2000] - t[1100])
    assert m.braking_s == pytest.approx(t[941] - t[700])
    assert m.coasting_s == pytest.approx(t[700] - t[690] + t[990] - t[941])
    assert m.lap_time_s == pytest.approx(t[-1])
    assert m.brake_source == "on/off" and m.corners == ()


def test_clean_exit_ramp() -> None:
    [c] = lap_metrics(_lap(), [SEG]).corners
    assert c.throttle_smoothness == 1.0 and c.throttle_lifts == 0
    t = _lap()["time"]
    assert c.throttle_ramp_s == pytest.approx(t[1100] - t[990])
    assert c.throttle_ramp_rate == pytest.approx(50.0 / (t[1100] - t[990]))


def test_lift_on_exit() -> None:
    lap = _lap()
    thr = lap["throttle"].copy()
    thr[1020:1040] = 30.0  # 50 -> 30 -> 50 -> 100: net 50, movement 90
    [c] = lap_metrics(_with(lap, throttle=thr), [SEG]).corners
    assert c.throttle_smoothness == pytest.approx(50 / 90)
    assert c.throttle_lifts == 1


def test_ramp_starts_at_final_pickup() -> None:
    # Throttle drops out completely (as in a chicane's second corner): ramp restarts after it.
    lap = _lap()
    thr = lap["throttle"].copy()
    thr[1020:1031] = 0.0
    [c] = lap_metrics(_with(lap, throttle=thr), [SEG]).corners
    t = lap["time"]
    assert c.throttle_smoothness == 1.0 and c.throttle_lifts == 0
    assert c.throttle_ramp_s == pytest.approx(t[1100] - t[1031])


def test_deceleration_constant_4g() -> None:
    # v(s) = sqrt(v0² - 2as) is exact constant deceleration; central difference is exact for it.
    a, v0 = 4 * G, 90.0  # stops after v0²/2a = 103 m
    d = np.arange(0.0, 95.0, 0.1)
    v = np.sqrt(v0**2 - 2 * a * d)
    t = (v0 - v) / a
    lap = ResampledLap({"distance": d, "time": t, "speed": v * 3.6}, step_m=0.1)
    inner = (t > 0.3) & (t < t[-1] - 0.3)  # ±0.25 s window fully inside the data
    np.testing.assert_allclose(deceleration(lap)[inner], a, rtol=1e-9)


def test_peak_decel_and_rise_on_known_corner() -> None:
    [c] = lap_metrics(_lap(), [SEG]).corners
    # 300 -> 100 km/h linear in distance: a = v * 0.8/3.6 per s, 1.89 g at the instant of
    # brake-on. The ±0.25 s window averages over that step, so the measured peak sits ~20 m in.
    assert c.peak_decel_g is not None and 1.7 < c.peak_decel_g < 1.89
    assert c.decel_rise_s is not None and 0 < c.decel_rise_s < 0.5
    assert c.brake_rise_s is None  # on/off brake data


def test_brake_pressure_rise() -> None:
    lap = _lap()
    brake = lap["brake"].copy()
    brake[700:720] = np.linspace(0.0, 1.0, 20)  # pressure ramps over 20 m
    assert has_pressure(brake) is False  # still mostly 0/1: not pressure data
    pressure = np.where(brake > 0, 0.6, 0.0)
    pressure[700:720] = np.linspace(0.0, 0.6, 20)
    assert has_pressure(pressure)
    m = lap_metrics(_with(lap, brake=pressure), [SEG])
    [c] = m.corners
    t = lap["time"]
    # 10 % / 90 % of 0.6 are first reached at samples 702 and 718 of the linear ramp.
    assert m.brake_source == "pressure"
    assert c.brake_rise_s == pytest.approx(t[718] - t[702])
    assert m.braking_s == pytest.approx(t[941] - t[701])  # braking from 5 % of peak pressure


def test_flat_corner() -> None:
    [c] = lap_metrics(_lap(flat=True), [SEG]).corners
    assert c.flat and c.throttle_smoothness is None and c.peak_decel_g is None


def test_lap_smoothness_weighted_and_json() -> None:
    m = lap_metrics(_lap(), [SEG])
    assert m.throttle_smoothness == 1.0
    d = json.loads(json.dumps(m.to_dict()))
    assert d["full_throttle_pct"] == pytest.approx(m.pct(m.full_throttle_s))
    assert d["corners"][0]["name"] == "T1"


def test_cli_metrics(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    a = write_lap(_lap(), tmp_path / "a.parquet")
    b = write_lap(_lap(brake=False), tmp_path / "b.parquet")
    circuit = Circuit("Test", 2000.0, (Corner(1, 1000.0),)).save(tmp_path / "c.json")
    out = tmp_path / "m.json"
    assert main(["metrics", str(a), str(b), "--circuit", str(circuit), "--json", str(out)]) == 0
    printed = capsys.readouterr().out
    assert "full throttle" in printed and "decel g" in printed
    assert len(json.loads(out.read_text())) == 2
