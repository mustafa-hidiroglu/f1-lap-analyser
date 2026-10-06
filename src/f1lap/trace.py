"""Structure-of-Arrays lap containers.

Each channel is its own contiguous 1-D array, so per-channel kernels (interpolation, diffs,
reductions) stream through memory and vectorise cleanly.

Containers hold read-only *views*: arrays that are already contiguous with the right dtype are not
copied, and the caller's own arrays keep their flags. Callers must not mutate arrays after handing
them to a container.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

import numpy as np
import numpy.typing as npt

from f1lap import schema

# Channel dtype varies (float64 / int16, see `schema`), so arrays are typed loosely.
Array = npt.NDArray[Any]

_DISCRETE_INFO = np.iinfo(schema.DISCRETE_DTYPE)


class TraceError(ValueError):
    pass


@dataclass(frozen=True, slots=True)
class LapMeta:
    driver: str = ""
    lap_number: int | None = None
    lap_time_s: float | None = None
    source: str = ""  # e.g. "fastf1" or a file path
    year: int | None = None
    event: str = ""
    session: str = ""
    raw_length_m: float | None = None  # lap distance before any normalisation
    normalised_to_m: float | None = None  # set if distance was rescaled to a reference length


def _fill_gaps(values: npt.NDArray[np.float64]) -> npt.NDArray[np.float64]:
    """Forward-fill non-finite samples (back-fill a leading gap). Vectorised."""
    finite = np.isfinite(values)
    if finite.all():
        return values
    if not finite.any():
        raise TraceError("discrete channel has no finite samples")
    idx = np.where(finite, np.arange(values.size), 0)
    np.maximum.accumulate(idx, out=idx)
    idx[: int(np.argmax(finite))] = int(np.argmax(finite))
    return values[idx]


def _discrete(name: str, values: npt.ArrayLike) -> Array:
    raw = np.asarray(values)
    if raw.dtype == schema.DISCRETE_DTYPE or raw.dtype.kind == "b":
        return raw.astype(schema.DISCRETE_DTYPE, copy=False)
    if raw.dtype.kind not in "iuf":
        raise TraceError(f"channel {name!r} must be numeric, got dtype {raw.dtype}")
    v = _fill_gaps(raw.astype(np.float64, copy=False))
    if not np.array_equal(v, np.round(v)):
        raise TraceError(f"channel {name!r} has non-integer values")
    if v.min() < _DISCRETE_INFO.min or v.max() > _DISCRETE_INFO.max:
        raise TraceError(f"channel {name!r} out of {schema.DISCRETE_DTYPE} range")
    return v.astype(schema.DISCRETE_DTYPE)


def _coerce(channels: dict[str, npt.ArrayLike]) -> dict[str, Array]:
    unknown = channels.keys() - schema.CHANNELS.keys() - {schema.DISTANCE}
    if unknown:
        raise TraceError(f"unknown channels: {sorted(unknown)}")
    missing = schema.REQUIRED - channels.keys()
    if missing:
        raise TraceError(f"missing required channels: {sorted(missing)}")

    out: dict[str, Array] = {}
    n: int | None = None
    for name, values in channels.items():
        if name != schema.DISTANCE and schema.CHANNELS[name] is schema.Kind.DISCRETE:
            arr = _discrete(name, values)
        else:
            try:
                arr = np.asarray(values, dtype=schema.CONTINUOUS_DTYPE)
            except (TypeError, ValueError) as exc:
                raise TraceError(f"channel {name!r} is not numeric: {exc}") from exc
        if arr.ndim != 1:
            raise TraceError(f"channel {name!r} must be 1-D, got shape {arr.shape}")
        if n is None:
            n = arr.size
        elif arr.size != n:
            raise TraceError(f"channel {name!r} has {arr.size} samples, expected {n}")
        view = np.ascontiguousarray(arr).view()
        view.flags.writeable = False
        out[name] = view
    if not n:
        raise TraceError("trace is empty")
    return out


@dataclass(frozen=True, slots=True)
class LapTrace:
    """Raw, irregularly sampled lap telemetry."""

    channels: dict[str, Array]
    meta: LapMeta = field(default_factory=LapMeta)

    def __post_init__(self) -> None:
        object.__setattr__(self, "channels", _coerce(dict(self.channels)))

    def __len__(self) -> int:
        return int(self.channels[schema.DISTANCE].size)

    def __getitem__(self, name: str) -> Array:
        return self.channels[name]


@dataclass(frozen=True, slots=True)
class ResampledLap:
    """Lap on a uniform distance grid: sample `i` sits at `i * step_m` metres."""

    channels: dict[str, Array]
    step_m: float
    meta: LapMeta = field(default_factory=LapMeta)

    def __post_init__(self) -> None:
        if not self.step_m > 0:
            raise TraceError(f"step_m must be > 0, got {self.step_m}")
        object.__setattr__(self, "channels", _coerce(dict(self.channels)))

    def __len__(self) -> int:
        return int(self.channels[schema.DISTANCE].size)

    def __getitem__(self, name: str) -> Array:
        return self.channels[name]

    @property
    def grid_end_m(self) -> float:
        """Distance of the last grid sample (≤ the lap's true length, see `meta.raw_length_m`)."""
        return float(self.channels[schema.DISTANCE][-1])
