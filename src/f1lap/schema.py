"""Canonical telemetry channel schema shared by ingestion, resampling and storage."""

from __future__ import annotations

from enum import Enum
from typing import Final

import numpy as np


class Kind(Enum):
    CONTINUOUS = "continuous"  # linearly interpolated
    DISCRETE = "discrete"  # zero-order hold, never interpolated


DISTANCE: Final = "distance"
TIME: Final = "time"

# Channel name -> interpolation kind. `distance` is the resampling axis and is not listed.
CHANNELS: Final[dict[str, Kind]] = {
    TIME: Kind.CONTINUOUS,  # seconds from lap start
    "speed": Kind.CONTINUOUS,  # km/h
    "throttle": Kind.CONTINUOUS,  # 0-100 %
    "brake": Kind.CONTINUOUS,  # 0-1 (FastF1 exposes on/off; exports may carry pressure)
    "rpm": Kind.CONTINUOUS,
    "x": Kind.CONTINUOUS,  # GPS/track coordinates, source units
    "y": Kind.CONTINUOUS,
    "z": Kind.CONTINUOUS,
    "gear": Kind.DISCRETE,
    "drs": Kind.DISCRETE,
}

REQUIRED: Final = frozenset({DISTANCE, TIME, "speed"})

CONTINUOUS_DTYPE: Final = np.dtype(np.float64)
DISCRETE_DTYPE: Final = np.dtype(np.int16)

# Accepted source column names (lower-cased) -> canonical channel.
ALIASES: Final[dict[str, str]] = {
    "distance": DISTANCE,
    "time": TIME,
    "speed": "speed",
    "throttle": "throttle",
    "brake": "brake",
    "rpm": "rpm",
    "ngear": "gear",
    "gear": "gear",
    "drs": "drs",
    "x": "x",
    "y": "y",
    "z": "z",
}


def dtype_for(channel: str) -> np.dtype[np.generic]:
    if channel == DISTANCE:
        return CONTINUOUS_DTYPE
    return CONTINUOUS_DTYPE if CHANNELS[channel] is Kind.CONTINUOUS else DISCRETE_DTYPE
