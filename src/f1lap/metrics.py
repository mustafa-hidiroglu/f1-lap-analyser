"""Driver-input metrics: how the lap was driven, independent of any reference lap.

Lap level (time-weighted over the lap): full throttle, braking, coasting.
Corner level (from `phases.corner_points`):
- throttle smoothness on the exit ramp, from the *final* pickup (last time throttle comes up
  through PICKUP_THROTTLE with the brake off, so a chicane's first corner is excluded) to full
  throttle: net rise / total throttle movement (1.0 = a single monotonic push), ramp duration
  and rate, and lifts (drops of more than LIFT_PP points below the ramp's running maximum).
- braking steepness. FastF1 brake is on/off, so by default it is measured from the speed trace:
  peak deceleration (g) and its 10 -> 90 % rise time, from the lift point. Deceleration is a
  central difference over ±DECEL_HALF_WINDOW_S in time, which matches FastF1's ~4 Hz speed
  sampling (narrower windows amplify sampling steps: >7 g at Monza T1). The window also widens
  rise times by up to ~0.5 s; the bias is the same for every lap, so values compare between
  laps from the same source but are not absolute.
  When the brake channel carries real pressure (most braking samples fractional), the 10->90 %
  pressure rise time is reported as well.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import asdict, dataclass
from typing import Any, Final

import numpy as np
import numpy.typing as npt

from f1lap import schema
from f1lap.circuit import Segment
from f1lap.phases import (
    FULL_THROTTLE,
    PICKUP_THROTTLE,
    CornerPoints,
    braking_mask,
    corner_points,
    has_pressure,
)
from f1lap.trace import ResampledLap

F64 = npt.NDArray[np.float64]

G: Final = 9.81
DECEL_HALF_WINDOW_S: Final = 0.25
COAST_THROTTLE: Final = 10.0  # % — below this with brake off counts as coasting
LIFT_PP: Final = 10.0  # throttle points below the running max that count as a lift


@dataclass(frozen=True, slots=True)
class CornerMetrics:
    name: str
    flat: bool
    throttle_smoothness: float | None  # net rise / total movement on the exit ramp
    throttle_ramp_s: float | None  # pickup -> full throttle
    throttle_ramp_rate: float | None  # % per second
    throttle_lifts: int
    peak_decel_g: float | None
    decel_rise_s: float | None  # 10 -> 90 % of peak deceleration
    brake_rise_s: float | None  # 10 -> 90 % brake pressure (pressure data only)


@dataclass(frozen=True, slots=True)
class LapMetrics:
    driver: str
    lap_number: int | None
    lap_time_s: float
    full_throttle_s: float
    braking_s: float
    coasting_s: float
    brake_source: str  # "pressure" or "on/off"
    corners: tuple[CornerMetrics, ...]

    def pct(self, seconds: float) -> float:
        return 100.0 * seconds / self.lap_time_s

    @property
    def throttle_smoothness(self) -> float | None:
        """Ramp-time-weighted mean over corners with an exit ramp."""
        rows = [(c.throttle_smoothness, c.throttle_ramp_s) for c in self.corners
                if c.throttle_smoothness is not None and c.throttle_ramp_s]
        if not rows:
            return None
        s, w = np.array(rows).T
        return float((s * w).sum() / w.sum())

    def to_dict(self) -> dict[str, Any]:
        return {
            "driver": self.driver,
            "lap_number": self.lap_number,
            "lap_time_s": self.lap_time_s,
            "full_throttle_s": self.full_throttle_s,
            "full_throttle_pct": self.pct(self.full_throttle_s),
            "braking_s": self.braking_s,
            "braking_pct": self.pct(self.braking_s),
            "coasting_s": self.coasting_s,
            "coasting_pct": self.pct(self.coasting_s),
            "throttle_smoothness": self.throttle_smoothness,
            "brake_source": self.brake_source,
            "corners": [asdict(c) for c in self.corners],
        }


def deceleration(lap: ResampledLap) -> F64:
    """Longitudinal deceleration in m/s² (positive = slowing), per grid point."""
    t = lap[schema.TIME]
    v = lap["speed"] / 3.6
    h = DECEL_HALF_WINDOW_S
    accel = (np.interp(t + h, t, v) - np.interp(t - h, t, v)) / (2 * h)
    return -accel


def _rise_time(t: F64, values: F64, lo_frac: float, hi_frac: float) -> float | None:
    """Time from first crossing `lo_frac` to first crossing `hi_frac` of the slice's maximum."""
    peak = values.max(initial=0.0)
    if peak <= 0:
        return None
    lo = np.flatnonzero(values >= lo_frac * peak)
    hi = np.flatnonzero(values >= hi_frac * peak)
    if not lo.size or not hi.size:
        return None
    return float(t[hi[0]] - t[lo[0]])


def _corner(
    lap: ResampledLap, p: CornerPoints, decel: F64, braking: npt.NDArray[np.bool_],
    pressure: bool,
) -> CornerMetrics:
    if p.flat:
        return CornerMetrics(p.name, True, None, None, None, 0, None, None, None)
    step, t = lap.step_m, lap[schema.TIME]

    def i(m: float) -> int:
        return round(m / step)

    smooth = ramp_s = ramp_rate = None
    lifts = 0
    if "throttle" in lap.channels and p.full_throttle_m > p.pickup_m:
        a, b = i(p.pickup_m), i(p.full_throttle_m)
        off = (lap["throttle"][a:b] < PICKUP_THROTTLE) | braking[a:b]
        last_off = np.flatnonzero(off)
        if last_off.size:  # e.g. the second corner of a chicane: start at the final pickup
            a += int(last_off[-1]) + 1
        thr = lap["throttle"][a : b + 1]
        net = float(thr[-1] - thr[0])
        movement = float(np.abs(np.diff(thr)).sum())
        smooth = net / movement if movement > 0 else 1.0
        ramp_s = float(t[b] - t[a])
        ramp_rate = net / ramp_s if ramp_s > 0 else None
        dropped = (np.maximum.accumulate(thr) - thr) > LIFT_PP
        lifts = int(np.count_nonzero(np.diff(dropped.astype(np.int8), prepend=0) == 1))

    peak = decel_rise = brake_rise = None
    if p.brake_on_m is not None and p.brake_off_m is not None:
        a, b = i(p.entry_m), i(p.brake_off_m)
        peak = float(decel[a : b + 1].max()) / G
        decel_rise = _rise_time(t[a : b + 1], decel[a : b + 1], 0.1, 0.9)
        if pressure:
            brake_rise = _rise_time(t[a : b + 1], lap["brake"][a : b + 1], 0.1, 0.9)

    return CornerMetrics(
        p.name, False, smooth, ramp_s, ramp_rate, lifts, peak, decel_rise, brake_rise
    )


def lap_metrics(lap: ResampledLap, segments: Sequence[Segment] = ()) -> LapMetrics:
    """Lap-level input shares plus per-corner metrics for `segments` (if given)."""
    t = lap[schema.TIME]
    dt = np.diff(t)  # interval i classified by its starting sample
    thr = lap["throttle"][:-1] if "throttle" in lap.channels else None
    brake_on = (
        braking_mask(lap["brake"]) if "brake" in lap.channels else np.zeros(t.size, dtype=bool)
    )
    braking = brake_on[:-1]
    full = (thr >= FULL_THROTTLE) & ~braking if thr is not None else np.zeros(dt.size, bool)
    coast = (thr < COAST_THROTTLE) & ~braking if thr is not None else np.zeros(dt.size, bool)

    pressure = "brake" in lap.channels and has_pressure(lap["brake"])
    decel = deceleration(lap)
    corners = tuple(
        _corner(lap, corner_points(lap, s), decel, brake_on, pressure) for s in segments
    )
    return LapMetrics(
        driver=lap.meta.driver,
        lap_number=lap.meta.lap_number,
        lap_time_s=float(t[-1] - t[0]),
        full_throttle_s=float(dt[full].sum()),
        braking_s=float(dt[braking].sum()),
        coasting_s=float(dt[coast].sum()),
        brake_source="pressure" if pressure else "on/off",
        corners=corners,
    )
