"""Telemetry sources -> `LapTrace`."""

from __future__ import annotations

from collections.abc import Mapping

import numpy as np
import numpy.typing as npt
import pandas as pd

from f1lap import schema
from f1lap.trace import Array, LapMeta, LapTrace, TraceError


def _to_seconds(values: npt.ArrayLike) -> Array:
    """Float seconds from float, timedelta64, or text timedeltas ("0 days 00:01:02.345")."""
    arr = np.asarray(values)
    if arr.dtype.kind in "OUS":
        try:
            return arr.astype(np.float64)  # numeric text, e.g. "1.5"
        except (TypeError, ValueError):
            pass
        try:
            arr = pd.to_timedelta(arr).to_numpy()
        except (TypeError, ValueError) as exc:
            raise TraceError(f"cannot parse time column: {exc}") from exc
    if arr.dtype.kind == "m":
        seconds = arr.astype("timedelta64[ns]").astype(np.float64) / 1e9
        seconds[np.isnat(arr)] = np.nan
        return seconds
    return arr.astype(np.float64)


def trace_from_columns(columns: Mapping[str, npt.ArrayLike], meta: LapMeta) -> LapTrace:
    """Build a trace from source columns, mapping known aliases and ignoring the rest.

    `time` may be float seconds, timedelta64 or timedelta text; boolean `brake` becomes 0.0/1.0.
    """
    channels: dict[str, npt.ArrayLike] = {}
    for col, values in columns.items():
        name = schema.ALIASES.get(col.lower())
        if name is None or name in channels:
            continue
        channels[name] = _to_seconds(values) if name == schema.TIME else values
    return LapTrace(channels, meta)  # type: ignore[arg-type]  # coerced in __post_init__
