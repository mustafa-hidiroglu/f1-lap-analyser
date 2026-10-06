from __future__ import annotations

from collections.abc import Callable

import numpy as np
import pytest

from f1lap.trace import LapMeta, LapTrace

LAP_LENGTH_M = 5000.0

MakeLap = Callable[..., LapTrace]


def speed_profile(d: np.ndarray) -> np.ndarray:
    """Smooth synthetic speed trace (km/h) with a few 'corners'."""
    return 200.0 + 100.0 * np.cos(2 * np.pi * d / 1250.0)


def gear_profile(d: np.ndarray) -> np.ndarray:
    return np.clip((speed_profile(d) // 40).astype(np.int16), 1, 8)


@pytest.fixture
def make_lap() -> MakeLap:
    """Irregularly sampled lap: `n` sorted random distances over `length` metres."""

    def _make(n: int = 4000, length: float = LAP_LENGTH_M, seed: int = 0) -> LapTrace:
        rng = np.random.default_rng(seed)
        d = np.sort(rng.uniform(0.0, length, n))
        d[0], d[-1] = 0.0, length
        speed = speed_profile(d)
        dt = np.diff(d, prepend=0.0) / (speed / 3.6)
        return LapTrace(
            {
                "distance": d,
                "time": np.cumsum(dt),
                "speed": speed,
                "throttle": np.clip((speed - 150.0) / 1.5, 0.0, 100.0),
                "brake": (np.gradient(speed, d) < -0.2).astype(np.float64),
                "gear": gear_profile(d),
                "drs": np.where(d < 800.0, 12, 0),
                "rpm": speed * 40.0,
                "x": np.cos(2 * np.pi * d / length) * 800.0,
                "y": np.sin(2 * np.pi * d / length) * 800.0,
            },
            LapMeta(driver="TST", lap_number=7, lap_time_s=81.234, source="synthetic:test"),
        )

    return _make
