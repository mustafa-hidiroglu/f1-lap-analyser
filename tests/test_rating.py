from __future__ import annotations

import json
from pathlib import Path

import numpy as np
import pytest
from conftest import MakeLap

import f1lap.explain
import f1lap.rating
from f1lap.circuit import corner_segments, detect_corners
from f1lap.cli import main
from f1lap.rating import LapEntry, LapRating, SegmentTimes, rate, segment_times
from f1lap.resample import resample_to_distance
from f1lap.sim import SimError
from f1lap.trace import LapTrace


def _times(rows: dict[tuple[str, int], list[float]]) -> SegmentTimes:
    return SegmentTimes(
        laps=tuple(LapEntry(d, n, sum(t)) for (d, n), t in rows.items()),
        names=("A", "B", "C"),
        bounds_m=np.array([0.0, 100.0, 200.0, 300.0]),
        times=np.array(list(rows.values())),
    )


ROWS = {
    ("AAA", 1): [10.0, 20.0, 30.0],
    ("AAA", 2): [10.5, 19.5, 30.2],  # AAA best: 10.0, 19.5, 30.0 -> theoretical 59.5
    ("BBB", 1): [9.8, 20.1, 30.5],
    ("CCC", 1): [10.2, 19.0, 29.9],
}


def test_rate_against_own_best_and_field() -> None:
    st = _times(ROWS)
    r = rate(st, st.index("AAA", 1))
    assert r.lap_time_s == 60.0
    assert r.theoretical_best_s == pytest.approx(59.5)
    assert r.own_best_lap == (1, 2, 1)
    assert r.ultimate_s == pytest.approx(9.8 + 19.0 + 29.9)
    assert r.field_best_by == ("BBB L1", "CCC L1", "CCC L1")
    # Others' bests: BBB 9.8/20.1/30.5, CCC 10.2/19.0/29.9. AAA L1 (10/20/30) beats exactly one
    # of them in every segment -> rank 2, 50th percentile throughout.
    np.testing.assert_array_equal(r.rank, [2, 2, 2])
    np.testing.assert_allclose(r.percentile, [50.0, 50.0, 50.0])
    assert r.score == pytest.approx(50.0)
    assert r.drivers == 3 and r.laps == 4


def test_rated_lap_compared_with_other_drivers_only() -> None:
    # AAA L2 (10.5/19.5/30.2): slowest of three in A, beats BBB in B and C. AAA L1 is faster in
    # A but does not count against it: a driver is never ranked against themselves.
    st = _times(ROWS)
    r = rate(st, st.index("AAA", 2))
    np.testing.assert_array_equal(r.rank, [3, 2, 2])


def test_single_driver_set() -> None:
    st = _times({("AAA", 1): [1.0, 2.0, 3.0], ("AAA", 2): [1.1, 1.9, 3.0]})
    r = rate(st, 0)
    assert r.drivers == 1 and r.score == 100.0
    assert r.theoretical_best_s == pytest.approx(5.9)


def test_index_unknown_lap() -> None:
    with pytest.raises(LookupError):
        _times(ROWS).index("ZZZ", 1)


def test_to_dict_is_json_serialisable() -> None:
    st = _times(ROWS)
    d = json.loads(json.dumps(rate(st, 0).to_dict()))
    assert d["time_left_s"] == pytest.approx(0.5)
    assert d["segments"][1]["field_best_by"] == "CCC L1"


@pytest.mark.parametrize("length", [5000.0, 5000.6])
def test_segment_times_sum_to_lap_time(make_lap: MakeLap, length: float) -> None:
    traces = [make_lap(length=length, seed=s) for s in range(3)]
    laps = [resample_to_distance(t, 1.0) for t in traces]
    ref = laps[0]
    st = segment_times(laps, ref, corner_segments(detect_corners(ref), ref))
    assert st.times.shape == (3, 4)
    np.testing.assert_allclose(
        st.times.sum(axis=1), [t["time"][-1] for t in traces], atol=2e-3
    )
    assert st.bounds_m[-1] == pytest.approx(length)


def test_segment_times_of_slower_lap(make_lap: MakeLap) -> None:
    t = make_lap(seed=4)
    ref = resample_to_distance(t, 1.0)
    slow = resample_to_distance(LapTrace({**t.channels, "time": t["time"] * 1.02}, t.meta), 1.0)
    st = segment_times([ref, slow], ref, corner_segments(detect_corners(ref), ref))
    np.testing.assert_allclose(st.times[1], st.times[0] * 1.02, rtol=1e-9)


def test_cli_rate(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    st = _times(ROWS)
    canned = rate(st, 0)

    def fake(*args: object, **kwargs: object) -> LapRating:
        return canned

    monkeypatch.setattr(f1lap.rating, "rate_fastf1_lap", fake)

    def no_sim(*args: object, **kwargs: object) -> None:
        raise SimError("only 1 timed laps")

    monkeypatch.setattr(f1lap.explain, "explain_fastf1_lap", no_sim)
    out = tmp_path / "r.json"
    assert main(["--config", str(tmp_path / "x.toml"), "rate", "2024", "Monza", "Q", "AAA",
                 "--json", str(out)]) == 0
    printed = capsys.readouterr().out
    assert "theoretical best 59.500 s" in printed and "score 50/100" in printed
    assert "no perfect lap: only 1 timed laps" in printed
    assert json.loads(out.read_text())["driver"] == "AAA"
