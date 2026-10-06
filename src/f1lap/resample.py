"""Distance-domain resampling.

Laps are compared along track distance, not time: every lap is mapped onto the same uniform grid
(`0, step, 2*step, ...` metres from the lap's first sample) so channel `i` of two laps refers to
the same point on track.

Kernels are vectorised NumPy (`interp`, `searchsorted`, `maximum.accumulate`) with no Python-level
per-sample loop; per channel the only allocations are the output and at most one mask/index
array of the same length.
"""

from __future__ import annotations

import math
from dataclasses import replace
from typing import Final

import numpy as np
import numpy.typing as npt

from f1lap import schema
from f1lap.trace import Array, LapTrace, ResampledLap, TraceError

F64 = npt.NDArray[np.float64]

# Tolerance so that e.g. length 5000.0 with step 0.1 still yields the 5000.0 m sample.
_GRID_EPS: Final = 1e-9
# Longest circuit (Nordschleife) is ~21 km; 2M samples covers it at 1 cm (~16 MB per channel).
MAX_GRID_SAMPLES: Final = 2_000_000
# Default largest gap between consecutive samples. Bigger jumps are treated as corrupt distance
# data; sparse exports or long telemetry dropouts can raise it via `max_gap_m`.
MAX_SAMPLE_GAP_M: Final = 500.0


def _check_positive(name: str, value: float) -> None:
    if not (math.isfinite(value) and value > 0):
        raise ValueError(f"{name} must be finite and > 0, got {value}")


def monotonic_mask(distance: F64) -> npt.NDArray[np.bool_]:
    """Rows to keep so distance is finite and strictly increasing.

    A sample is dropped if it is NaN or does not advance past every earlier kept sample
    (duplicates and GPS/integration jitter that steps backwards).
    """
    finite = np.isfinite(distance)
    d = np.where(finite, distance, -np.inf)
    running_max = np.maximum.accumulate(d)
    keep = np.empty(d.size, dtype=bool)
    if d.size:
        keep[0] = finite[0]
        keep[1:] = d[1:] > running_max[:-1]
    return keep & finite


def clean(trace: LapTrace, max_gap_m: float = MAX_SAMPLE_GAP_M) -> LapTrace:
    """Return a trace whose distance is finite, strictly increasing and starts at 0, with time
    measured from the first kept sample."""
    keep = monotonic_mask(trace[schema.DISTANCE])
    if keep.sum() < 2:
        raise TraceError("fewer than 2 usable samples after distance cleaning")
    channels = trace.channels if keep.all() else {k: v[keep] for k, v in trace.channels.items()}
    d = channels[schema.DISTANCE]
    max_gap = float(np.diff(d).max())
    if max_gap > max_gap_m:
        raise TraceError(
            f"distance jumps {max_gap:.0f} m between samples (limit {max_gap_m:.0f} m); "
            "corrupt distance, or raise max_gap_m for sparse data"
        )
    t = channels[schema.TIME]
    finite_t = t[np.isfinite(t)]
    t0 = float(finite_t[0]) if finite_t.size else 0.0
    if keep.all() and d[0] == 0.0 and t0 == 0.0:
        return trace
    return LapTrace({**channels, schema.DISTANCE: d - d[0], schema.TIME: t - t0}, trace.meta)


def distance_grid(length_m: float, step_m: float) -> F64:
    _check_positive("step_m", step_m)
    _check_positive("length_m", length_m)
    n = int(np.floor(length_m / step_m + _GRID_EPS)) + 1
    if n > MAX_GRID_SAMPLES:
        raise ValueError(
            f"{length_m:.0f} m at {step_m} m steps needs {n} samples (max {MAX_GRID_SAMPLES})"
        )
    return np.arange(n, dtype=np.float64) * step_m


def _interp_continuous(grid: F64, d: F64, values: Array) -> F64:
    finite = np.isfinite(values)
    if not finite.all():
        if finite.sum() < 2:
            return np.full(grid.size, np.nan)
        d, values = d[finite], values[finite]
    return np.interp(grid, d, values)


def _hold_discrete(grid: F64, d: F64, values: Array) -> Array:
    # Zero-order hold: the last sample at or before each grid point. Never fabricates values.
    idx = np.searchsorted(d, grid, side="right") - 1
    np.clip(idx, 0, d.size - 1, out=idx)
    return values[idx]


def resample_to_distance(
    trace: LapTrace,
    step_m: float,
    length_m: float | None = None,
    *,
    max_gap_m: float = MAX_SAMPLE_GAP_M,
) -> ResampledLap:
    """Resample `trace` onto a uniform distance grid starting at the lap's first sample.

    Args:
        trace: raw lap telemetry.
        step_m: grid spacing in metres.
        length_m: if given, the lap's distance is linearly rescaled so it ends at `length_m`
            (normalised track distance — removes racing-line length differences so laps align
            corner-for-corner). Pass the reference lap's `raw_length_m` when comparing laps.
        max_gap_m: largest accepted distance gap between consecutive samples.

    The true lap length is kept in `meta.raw_length_m`; the grid ends at the last whole step at or
    before the (possibly normalised) lap end.
    """
    _check_positive("step_m", step_m)
    if length_m is not None:
        _check_positive("length_m", length_m)

    trace = clean(trace, max_gap_m)
    d: F64 = trace[schema.DISTANCE]
    raw_length = float(d[-1])
    if length_m is not None:
        d = d * (length_m / raw_length)
    grid = distance_grid(length_m or raw_length, step_m)

    out: dict[str, Array] = {schema.DISTANCE: grid}
    for name, values in trace.channels.items():
        if name == schema.DISTANCE:
            continue
        if schema.CHANNELS[name] is schema.Kind.CONTINUOUS:
            out[name] = _interp_continuous(grid, d, values)
        else:
            out[name] = _hold_discrete(grid, d, values)
    meta = replace(trace.meta, raw_length_m=raw_length, normalised_to_m=length_m)
    return ResampledLap(out, step_m=step_m, meta=meta)
