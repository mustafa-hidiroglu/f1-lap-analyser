from __future__ import annotations

import numpy as np
import pytest
from conftest import LAP_LENGTH_M, MakeLap

from f1lap.resample import distance_grid, monotonic_mask, resample_to_distance
from f1lap.trace import LapTrace, TraceError


def test_linear_channel_is_exact() -> None:
    d = np.array([0.0, 0.4, 3.7, 10.0])
    trace = LapTrace({"distance": d, "time": d / 50.0, "speed": 2.0 * d + 1.0})
    lap = resample_to_distance(trace, step_m=1.0)
    grid = np.arange(11.0)
    np.testing.assert_array_equal(lap["distance"], grid)
    np.testing.assert_allclose(lap["speed"], 2.0 * grid + 1.0, atol=1e-9)
    np.testing.assert_allclose(lap["time"], grid / 50.0, atol=1e-12)


def test_different_sample_counts_share_grid(make_lap: MakeLap) -> None:
    a = resample_to_distance(make_lap(n=3000, seed=1), step_m=1.0)
    b = resample_to_distance(make_lap(n=7000, seed=2), step_m=1.0)
    assert len(a) == len(b) == int(LAP_LENGTH_M) + 1
    np.testing.assert_array_equal(a["distance"], b["distance"])
    # Same underlying smooth profile -> resampled speeds agree closely.
    np.testing.assert_allclose(a["speed"], b["speed"], atol=0.5)


def test_discrete_channels_never_fabricate_values(make_lap: MakeLap) -> None:
    trace = make_lap(n=500)
    lap = resample_to_distance(trace, step_m=0.5)
    for ch in ("gear", "drs"):
        assert lap[ch].dtype == np.int16
        assert set(np.unique(lap[ch])) <= set(np.unique(trace[ch]))


def test_discrete_zero_order_hold() -> None:
    d = np.array([0.0, 10.0, 20.0])
    trace = LapTrace(
        {"distance": d, "time": d, "speed": d, "gear": np.array([3, 4, 5])}
    )
    lap = resample_to_distance(trace, step_m=5.0)
    np.testing.assert_array_equal(lap["gear"], [3, 3, 4, 4, 5])


def test_non_monotonic_samples_dropped() -> None:
    d = np.array([0.0, 1.0, 1.0, 0.5, 2.0, np.nan, 3.0])
    keep = monotonic_mask(d)
    np.testing.assert_array_equal(keep, [True, True, False, False, True, False, True])

    speed = np.array([0.0, 10.0, 999.0, 999.0, 20.0, 999.0, 30.0])
    lap = resample_to_distance(LapTrace({"distance": d, "time": d, "speed": speed}), 1.0)
    np.testing.assert_allclose(lap["speed"], [0.0, 10.0, 20.0, 30.0])


def test_nan_in_channel_is_bridged() -> None:
    d = np.arange(5.0)
    speed = np.array([0.0, np.nan, 2.0, 3.0, 4.0])
    lap = resample_to_distance(LapTrace({"distance": d, "time": d, "speed": speed}), 1.0)
    np.testing.assert_allclose(lap["speed"], d)


def test_normalised_length_rescales_values() -> None:
    d = np.linspace(0.0, 200.0, 401)
    trace = LapTrace({"distance": d, "time": d / 50.0, "speed": d.copy()})
    lap = resample_to_distance(trace, step_m=1.0, length_m=100.0)
    assert len(lap) == 101 and lap.grid_end_m == 100.0
    # Grid point g on the normalised lap is raw distance 2g.
    np.testing.assert_allclose(lap["speed"], 2.0 * lap["distance"], atol=1e-9)
    assert lap.meta.raw_length_m == 200.0 and lap.meta.normalised_to_m == 100.0


def test_nonzero_start_is_shifted() -> None:
    d = np.array([1000.0, 1001.0, 1002.0, 1003.0, 1004.0])
    trace = LapTrace({"distance": d, "time": d - 1000.0, "speed": d - 1000.0})
    lap = resample_to_distance(trace, step_m=1.0)
    np.testing.assert_array_equal(lap["distance"], np.arange(5.0))
    np.testing.assert_allclose(lap["speed"], np.arange(5.0))
    norm = resample_to_distance(trace, step_m=1.0, length_m=8.0)
    np.testing.assert_allclose(norm["speed"], np.arange(9.0) / 2.0)


def test_grid_includes_endpoint_despite_float_error() -> None:
    grid = distance_grid(0.3, 0.1)
    assert grid.size == 4


def test_too_few_samples_rejected() -> None:
    d = np.array([1.0, 1.0, 1.0])
    with pytest.raises(TraceError):
        resample_to_distance(LapTrace({"distance": d, "time": d, "speed": d}), 1.0)


@pytest.mark.parametrize("step", [0.0, -1.0, float("inf"), float("nan")])
def test_bad_step_rejected(make_lap: MakeLap, step: float) -> None:
    with pytest.raises(ValueError):
        resample_to_distance(make_lap(n=100), step)


def test_outputs_are_contiguous_and_readonly(make_lap: MakeLap) -> None:
    lap = resample_to_distance(make_lap(), 1.0)
    for arr in lap.channels.values():
        assert arr.flags.c_contiguous
        assert not arr.flags.writeable
