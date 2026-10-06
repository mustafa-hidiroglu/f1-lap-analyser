"""Perfect lap: simulation, base, lap context, reasons and the base builder (all offline)."""

from __future__ import annotations

import asyncio
import json
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import numpy as np
import pandas as pd
import pytest

import f1lap.sim as simmod
import f1lap.simbase_build as builder
from f1lap import simbase
from f1lap.circuit import Circuit, Corner, corner_segments
from f1lap.context import LapContext, Span, flag_spans, session_kind, traffic_spans
from f1lap.explain import explain
from f1lap.resample import resample_to_distance
from f1lap.session import LoadedSession
from f1lap.sim import CarModel, SimError, simulate, solve, warp_to_line
from f1lap.trace import LapMeta, LapTrace, ResampledLap

LENGTH = 5000.0
APEXES = (625.0, 1875.0, 3125.0, 4375.0)  # minima of the synthetic speed profile


def _speed(d: np.ndarray) -> np.ndarray:
    return 200.0 + 100.0 * np.cos(2 * np.pi * (d - 625.0 - 625.0) / 1250.0)


def _lap(driver: str = "AAA", number: int = 1, *, scale: float = 1.0,
         slow: tuple[float, float, float] | None = None, shift_m: float = 0.0) -> ResampledLap:
    """Synthetic lap; `slow=(a, b, factor)` slows [a, b] metres; `shift_m`: the car really is
    `shift_m` further round than its (integrated) distance says — a distance misalignment."""
    d = np.arange(0.0, LENGTH + 0.5, 0.5)
    v = _speed(d + shift_m) * scale  # speed belongs to where the car really is
    if slow is not None:
        a, b, f = slow
        w = np.clip(np.minimum(d - a, b - d) / 40.0, 0.0, 1.0)  # smooth 40 m ramps
        v = v * (1.0 - (1.0 - f) * w)
    dt = np.diff(d, prepend=0.0) / (v / 3.6)
    t = np.cumsum(dt) - dt[0]
    dv = np.gradient(v, d)
    pos = d + shift_m
    trace = LapTrace(
        {
            "distance": d, "time": t, "speed": v,
            "throttle": np.where(dv >= -0.02, 100.0, 0.0),
            "brake": (dv < -0.02).astype(np.float64),
            "x": np.cos(2 * np.pi * pos / LENGTH) * 8000.0,
            "y": np.sin(2 * np.pi * pos / LENGTH) * 8000.0,
        },
        LapMeta(driver=driver, lap_number=number, lap_time_s=float(t[-1] + dt[0]),
                year=1999, event="Test Grand Prix", session="Qualifying"),
    )
    return resample_to_distance(trace, 1.0)


@pytest.fixture
def laps() -> list[ResampledLap]:
    # Each lap is slow somewhere different, so the perfect lap must combine them.
    return [
        _lap("AAA", 1, slow=(400, 900, 0.93)),
        _lap("BBB", 2, slow=(1600, 2100, 0.93)),
        _lap("CCC", 3, slow=(2900, 3400, 0.93)),
        _lap("DDD", 4, slow=(4100, 4600, 0.93)),
    ]


CIRCUIT = Circuit("Test", LENGTH, tuple(Corner(i + 1, a) for i, a in enumerate(APEXES)),
                  source="test")


# -- simulation -------------------------------------------------------------------------------

def test_solve_brakes_at_the_analytic_point() -> None:
    step, b = 1.0, 30.0
    vlim = np.full(2000, 80.0)
    vlim[1500:] = 20.0
    model = CarModel(accel_cap=10.0, power=1e9, drag=0.0, brake0=b, brake2=0.0, vmax=80.0)
    v, _, _ = solve(vlim, model, step)
    # The lap closes on itself (the slow end wraps to the start): find the braking point
    # before the slow zone at 1500 m.
    start = int(np.flatnonzero(v[:1500] >= 80.0 - 1e-9)[-1]) + 1
    expected = 1500 - (80.0**2 - 20.0**2) / (2 * b)  # 1400 m
    assert abs(start - expected) <= 2
    assert np.all(v <= vlim + 1e-9)


def test_simulate_combines_the_best_of_every_lap(laps: list[ResampledLap]) -> None:
    sim = simulate(laps[0], laps)
    fastest = min(lap.meta.lap_time_s or np.inf for lap in laps)
    assert sim.lap_time_s < fastest
    assert len(sim.calibration) == 4 and sim.lap.meta.driver == "SIM"
    # Nowhere is the perfect lap much slower than the best calibration lap at that point.
    best = np.max(np.vstack([lap["speed"] for lap in laps]), axis=0)
    # Never slower than any calibration lap (smoothing aside).
    assert np.max(best - sim.lap["speed"]) < 1.5
    assert set(np.unique(sim.lap["throttle"])) <= {0.0, simmod.GRIP_THROTTLE, 100.0}


def test_simulate_needs_enough_laps(laps: list[ResampledLap]) -> None:
    with pytest.raises(SimError, match="need 3"):
        simulate(laps[0], laps[:2])


def test_sanity_gate_rejects_implausible_laps(laps: list[ResampledLap],
                                              monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(simmod, "SANITY_GAIN", (0.0, 1e-6))
    with pytest.raises(SimError, match="implausible"):
        simulate(laps[0], laps)


def test_warp_undoes_a_local_distance_offset() -> None:
    ref = _lap()
    shifted = _lap(shift_m=15.0)
    inner = slice(200, len(ref) - 200)
    before = np.max(np.abs(shifted["speed"][inner] - ref["speed"][inner]))
    after = np.max(np.abs(warp_to_line(shifted, ref)[inner] - ref["speed"][inner]))
    assert before > 5.0 and after < 0.2 * before


# -- base -------------------------------------------------------------------------------------

def test_slug_and_key() -> None:
    assert simbase.slug("São Paulo Grand Prix") == "sao-paulo-grand-prix"
    key = simbase.SimKey(2021, "Mexico City Grand Prix", "Sprint Qualifying")
    assert key.relpath == Path("2021/mexico-city-grand-prix__sprint-qualifying.parquet")


def test_save_load_roundtrip(laps: list[ResampledLap], tmp_path: Path) -> None:
    sim = simulate(laps[0], laps)
    key = simbase.SimKey(1999, "Test Grand Prix", "Qualifying")
    path = simbase.save(sim, key, tmp_path)
    back = simbase.load(path)
    assert back.lap_time_s == pytest.approx(sim.lap_time_s)
    assert back.model == sim.model and back.calibration == sim.calibration
    assert back.lap.step_m == simbase.STORE_STEP_M
    resampled = np.interp(back.lap["distance"], sim.lap["distance"], sim.lap["speed"])
    assert np.max(np.abs(back.lap["speed"] - resampled)) < 0.5
    # Re-integrated time matches the stored lap time at the line.
    end_gap = (back.lap.meta.raw_length_m or 0) - back.lap.grid_end_m
    t_line = back.lap["time"][-1] + end_gap / (back.lap["speed"][-1] / 3.6)
    assert t_line == pytest.approx(sim.lap_time_s, abs=1e-6)
    assert path.stat().st_size < 120_000


def test_lookup_and_failures(laps: list[ResampledLap], tmp_path: Path) -> None:
    key = simbase.SimKey(1999, "Test Grand Prix", "Qualifying")
    assert simbase.lookup(key, [tmp_path]) is None
    simbase.save(simulate(laps[0], laps), key, tmp_path)
    assert simbase.lookup(key, [tmp_path / "missing", tmp_path]) is not None
    simbase.record_failure(tmp_path, key, "too few laps")
    assert simbase.failures(tmp_path) == {key.label: "too few laps"}
    simbase.record_failure(tmp_path, key, None)
    assert simbase.failures(tmp_path) == {}
    # Failures from an older model are retried; corrupt files are skipped, not fatal.
    old = {key.label: {"reason": "x", "version": 0}}
    (tmp_path / simbase.FAILURES).write_text(json.dumps(old))
    assert simbase.failures(tmp_path) == {}
    (tmp_path / key.relpath).write_bytes(b"not parquet")
    assert simbase.lookup(key, [tmp_path]) is None


class _Event(dict[str, Any]):
    year = 1999

    def __init__(self) -> None:
        super().__init__(EventName="Test Grand Prix")


def test_session_sim_uses_the_base_without_simulating(
    laps: list[ResampledLap], tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    key = simbase.SimKey(1999, "Test Grand Prix", "Qualifying")
    simbase.save(simulate(laps[0], laps), key, tmp_path)
    sd = LoadedSession(SimpleNamespace(event=_Event(), name="Qualifying"), user_base=tmp_path)

    def boom(*args: object, **kwargs: object) -> None:
        raise AssertionError("must not touch FastF1 or simulate")

    monkeypatch.setattr(LoadedSession, "calibration_laps", boom)
    assert sd.sim.lap.meta.event == "Test Grand Prix"


def test_session_sim_remembers_failures(tmp_path: Path) -> None:
    key = simbase.SimKey(1999, "Test Grand Prix", "Qualifying")
    simbase.record_failure(tmp_path, key, "only 1 timed laps")
    sd = LoadedSession(SimpleNamespace(event=_Event(), name="Qualifying"), user_base=tmp_path)
    with pytest.raises(SimError, match="only 1 timed laps"):
        _ = sd.sim


# -- lap context ------------------------------------------------------------------------------

@pytest.mark.parametrize(("name", "year", "kind"), [
    ("Qualifying", 2024, "qualifying"),
    ("Race", 2018, "race"),
    ("Sprint", 2022, "race"),
    ("Sprint Qualifying", 2021, "race"),  # 2021: the sprint race itself
    ("Sprint Shootout", 2023, "qualifying"),
    ("Sprint Qualifying", 2024, "qualifying"),
    ("Practice 1", 2024, ""),
])
def test_session_kind(name: str, year: int, kind: str) -> None:
    assert session_kind(name, year) == kind


def test_traffic_spans() -> None:
    frac = np.linspace(0.0, 1.0, 101)
    ahead = np.array(["VER"] * 30 + ["HAM"] * 30 + [""] * 41, dtype=object)
    gap_m = np.r_[np.full(30, 20.0), np.full(30, 200.0), np.full(41, 10.0)]
    speed = np.full(101, 180.0)  # 50 m/s: 20 m = 0.4 s, 200 m = 4 s
    spans = traffic_spans(frac, ahead, gap_m, speed)
    assert len(spans) == 1 and spans[0].what == "VER"
    assert spans[0].value == pytest.approx(0.4) and spans[0].end == pytest.approx(0.29)


def test_numpy_bool_flags() -> None:
    from f1lap.context import _flag

    assert _flag(np.bool_(True)) and not _flag(np.bool_(False))
    assert not _flag(None) and not _flag(float("nan")) and _flag(True)


def test_flag_spans() -> None:
    status = pd.DataFrame({"Time": [0.0, 105.0, 120.0], "Status": ["1", "2", "1"]})
    session_s = np.linspace(100.0, 200.0, 101)  # the lap runs from 100 s to 200 s
    spans = flag_spans(status, 100.0, 200.0, session_s, np.linspace(0, 1, 101))
    assert len(spans) == 1 and spans[0].what == "yellow flag"
    assert (spans[0].start, spans[0].end) == pytest.approx((0.05, 0.20))


# -- reasons ----------------------------------------------------------------------------------

def _report(rated: ResampledLap, laps: list[ResampledLap], ctx: LapContext | None = None) -> Any:
    sim = simulate(laps[0], laps)
    return explain(rated, sim, corner_segments(CIRCUIT, sim.lap), laps, ctx)


def test_calibration_lap_needs_no_excuses(laps: list[ResampledLap]) -> None:
    report = _report(laps[0], laps)
    costed = [f for c in report.corners for f in c.findings if f.cost_s is not None]
    assert {f.corner for f in costed} <= {"T1"}  # only where it was slowed (400-900 m)
    assert report.gap_s == pytest.approx(report.lap_time_s - report.sim_lap_time_s)


def test_slow_apex_is_found_where_it_happened(laps: list[ResampledLap]) -> None:
    rated = _lap("EEE", 9, slow=(1800, 1950, 0.85))  # T2 apex at 1875 m, 15 % slower
    report = _report(rated, laps)
    t2 = next(c for c in report.corners if c.name == "T2")
    kinds = {f.kind for f in t2.findings}
    assert kinds & {"apex_speed", "braked_late", "slow_exit", "phase_loss"}
    assert t2.excess_s > 0.1
    others = [f for c in report.corners if c.name != "T2" for f in c.findings
              if f.cost_s is not None and f.cost_s > 0.05]
    assert not others
    assert any("T2" in line for line in report.summary[1:])


def test_costs_never_exceed_the_corner_loss(laps: list[ResampledLap]) -> None:
    report = _report(_lap("EEE", 9, scale=0.95), laps)
    for c in report.corners:
        costed = sum(f.cost_s or 0.0 for f in c.findings if f.kind != "phase_loss")
        assert costed <= max(c.excess_s, 0.0) + sum(
            max(-v, 0.0) for v in c.phase_lost_s.values()) + 1e-6


def test_context_becomes_sentences(laps: list[ResampledLap]) -> None:
    ctx = LapContext(session_kind="race", lap_number=3, race_laps=57, compound="MEDIUM",
                     tyre_life=22, positions_gained=-1, car_behind="NOR", car_behind_gap_s=0.4,
                     traffic=(Span(0.10, 0.14, "VER", 0.6),),
                     flags=(Span(0.36, 0.40, "yellow flag"),))
    report = _report(_lap("EEE", 9, scale=0.97), laps, ctx)
    text = " ".join(f.text for c in report.corners for f in c.findings)
    assert "Close behind VER (0.6 s) through T1" in text
    assert "Yellow flag at T2" in text
    multi = LapContext(traffic=(Span(0.10, 0.40, "HAM", 0.3),))
    text = " ".join(f.text for c in _report(_lap("EEE", 9), laps, multi).corners
                    for f in c.findings)
    assert "Close behind HAM (0.3 s) from T1 to T2" in text
    lap_text = " ".join(f.text for f in report.lap_findings)
    assert "Lost 1 position" in lap_text and "NOR was 0.4 s behind" in lap_text
    assert "22 laps old — worn" in lap_text and "heavy fuel load" in lap_text


# -- builder ----------------------------------------------------------------------------------

def test_plan_year_keeps_competitive_past_sessions() -> None:
    sched = pd.DataFrame([{
        "RoundNumber": 1, "EventName": "Test Grand Prix",
        "Session1": "Practice 1", "Session1DateUtc": pd.Timestamp("2024-03-01 11:00"),
        "Session2": "Sprint Qualifying", "Session2DateUtc": pd.Timestamp("2024-03-01 15:00"),
        "Session3": "Sprint", "Session3DateUtc": pd.Timestamp("2024-03-02 11:00"),
        "Session4": "Qualifying", "Session4DateUtc": pd.Timestamp("2024-03-02 15:00"),
        "Session5": "Race", "Session5DateUtc": pd.Timestamp("2024-03-03 15:00"),
    }])
    now = pd.Timestamp("2024-03-02 20:00").to_pydatetime()
    planned = [p.session for p in builder.plan_year(sched, 2024, now)]
    assert planned == ["Sprint Qualifying", "Sprint", "Qualifying"]  # race not run yet


class RateLimitExceededError(Exception):
    pass


def _run(p: builder.Planned, out: Path, retry: bool = False) -> builder.Tally:
    tally = builder.Tally()
    asyncio.run(builder._build_planned(p, out, out / "cache", retry, tally))
    return tally


def test_builder_waits_out_rate_limits(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    calls: list[int] = []
    waits: list[float] = []

    def build_one(p: Any, out: Path, cache: Path) -> Path:
        calls.append(1)
        if len(calls) < 3:
            raise RateLimitExceededError("500 calls/h")
        return out / "x.parquet"

    async def sleep(s: float) -> None:
        waits.append(s)

    monkeypatch.setattr(builder, "build_one", build_one)
    monkeypatch.setattr(asyncio, "sleep", sleep)
    p = builder.Planned(2024, 1, "Test Grand Prix", "Qualifying")
    tally = _run(p, tmp_path)
    assert tally.built == 1 and len(calls) == 3
    assert waits == list(builder.RATE_LIMIT_WAIT_S[:2])
    assert simbase.failures(tmp_path) == {}


def test_builder_records_failures_and_resumes(tmp_path: Path,
                                              monkeypatch: pytest.MonkeyPatch) -> None:
    def broken(p: Any, out: Path, cache: Path) -> Path:
        raise SimError("only 1 timed laps")

    monkeypatch.setattr(builder, "build_one", broken)
    p = builder.Planned(2024, 1, "Test Grand Prix", "Qualifying")
    assert _run(p, tmp_path).failed == 1
    assert "2024 Test Grand Prix Qualifying" in simbase.failures(tmp_path)
    assert _run(p, tmp_path).skipped == 1  # a recorded failure is not retried by default
    assert _run(p, tmp_path, retry=True).failed == 1
    key = simbase.SimKey(2024, "Test Grand Prix", "Race")
    (tmp_path / key.relpath).parent.mkdir(parents=True, exist_ok=True)
    (tmp_path / key.relpath).write_bytes(b"")
    assert _run(builder.Planned(2024, 1, "Test Grand Prix", "Race"), tmp_path).skipped == 1


def test_builder_defers_network_errors(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    def offline(p: Any, out: Path, cache: Path) -> Path:
        raise ConnectionError("no route to host")

    async def sleep(s: float) -> None:
        return None

    monkeypatch.setattr(builder, "build_one", offline)
    monkeypatch.setattr(asyncio, "sleep", sleep)
    tally = _run(builder.Planned(2024, 1, "Test Grand Prix", "Qualifying"), tmp_path)
    assert tally.deferred == 1 and simbase.failures(tmp_path) == {}


def test_builder_defers_load_errors(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    def glitch(p: Any, out: Path, cache: Path) -> Path:
        raise KeyError("DataNotLoadedError-like")  # not a SimError: may be transient

    monkeypatch.setattr(builder, "build_one", glitch)
    tally = _run(builder.Planned(2018, 14, "Italian Grand Prix", "Race"), tmp_path)
    assert tally.deferred == 1 and simbase.failures(tmp_path) == {}


def test_session_remembers_its_sim_error(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    calls: list[int] = []

    def no_laps(self: LoadedSession, k: int = 8) -> list[ResampledLap]:
        calls.append(1)
        return []

    monkeypatch.setattr(LoadedSession, "calibration_laps", no_laps)
    sd = LoadedSession(SimpleNamespace(event=_Event(), name="Qualifying", laps=[1, 2]),
                       user_base=tmp_path)
    for _ in range(2):
        with pytest.raises(SimError, match="no valid timed laps"):
            _ = sd.sim
    assert len(calls) == 1
    assert "1999 Test Grand Prix Qualifying" in simbase.failures(tmp_path)  # laps, none valid
    empty = LoadedSession(SimpleNamespace(event=_Event(), name="Race", laps=[]),
                          user_base=tmp_path)
    with pytest.raises(SimError) as info:
        _ = empty.sim
    assert not info.value.permanent  # nothing loaded: maybe a network glitch, not recorded
    assert "1999 Test Grand Prix Race" not in simbase.failures(tmp_path)
