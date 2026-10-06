"""Corner phases: where the driver lifts/brakes, the minimum-speed zone, throttle pickup, and how
much time each phase costs relative to a reference lap.

Each corner segment is split at five points (all distances on the lap's grid):

    approach | braking | mid | exit | straight
           entry   mid_start  mid_end   full_throttle

- entry: last point before the apex at full attack (throttle ≥ FULL_THROTTLE, brake off).
  "Braking" therefore includes lift-only corners.
- mid zone: the contiguous stretch around the apex within `mid_speed_tol` of the minimum speed.
  F1 drivers go from brake straight to throttle, so an input-based mid phase would be ~0 m;
  the minimum-speed zone is where the car is actually rotating at its slowest.
- full_throttle: first point after the mid zone back at full attack.

A multi-corner complex (e.g. a chicane) uses its overall slowest point as the apex. A corner
taken flat (full attack throughout the apex window) has every boundary at its marker, so its
whole time falls into approach + straight.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import asdict, dataclass
from typing import Any, Final

import numpy as np
import numpy.typing as npt

from f1lap import schema
from f1lap.circuit import Segment
from f1lap.delta import LapComparison
from f1lap.trace import ResampledLap

F64 = npt.NDArray[np.float64]

FULL_THROTTLE: Final = 95.0  # % — FastF1 reports full throttle as 99-100
BRAKE_ON: Final = 0.5
PICKUP_THROTTLE: Final = 20.0  # % with brake off counts as back on the throttle
APEX_SEARCH_M: Final = 150.0  # search for the apex this far either side of the corner markers
PHASES: Final = ("approach", "braking", "mid", "exit", "straight")


@dataclass(frozen=True, slots=True)
class CornerPoints:
    """Key points of one lap through one corner segment."""

    name: str
    entry_m: float  # lift or brake point
    brake_on_m: float | None  # None for lift-only / flat corners
    brake_off_m: float | None  # end of the first braking run (the release point)
    brake_applications: int  # separate brake applications in the segment (>1: re-applied)
    apex_m: float  # minimum speed
    mid_start_m: float
    mid_end_m: float
    pickup_m: float  # back on throttle (≥ PICKUP_THROTTLE, brake off)
    full_throttle_m: float  # back to full attack (segment end if never reached)
    entry_speed: float
    apex_speed: float
    exit_speed: float  # at full_throttle_m
    flat: bool  # taken at full attack throughout; points collapse onto the marker

    @property
    def bounds_m(self) -> tuple[float, ...]:
        """Inner phase boundaries: entry, mid_start, mid_end, full_throttle."""
        return (self.entry_m, self.mid_start_m, self.mid_end_m, self.full_throttle_m)


def _first(mask: npt.NDArray[np.bool_]) -> int | None:
    hits = np.flatnonzero(mask)
    return int(hits[0]) if hits.size else None


def _last(mask: npt.NDArray[np.bool_]) -> int | None:
    hits = np.flatnonzero(mask)
    return int(hits[-1]) if hits.size else None


def corner_points(lap: ResampledLap, seg: Segment, mid_speed_tol: float = 0.05) -> CornerPoints:
    step = lap.step_m
    n = len(lap)
    lo = round(seg.start_m / step)
    hi = min(round(seg.end_m / step), n - 1)
    if hi - lo < 2:
        raise ValueError(f"segment {seg.name} is too short")
    d = lap[schema.DISTANCE]
    speed = lap["speed"][lo : hi + 1]
    throttle = lap["throttle"][lo : hi + 1] if "throttle" in lap.channels else None
    brake = lap["brake"][lo : hi + 1] if "brake" in lap.channels else np.zeros(speed.size)
    braking = brake >= BRAKE_ON

    # Apex: slowest point near the corner markers (local indices from here on).
    a_lo = max(0, round((min(seg.apex_m) - APEX_SEARCH_M) / step) - lo)
    a_hi = min(speed.size, round((max(seg.apex_m) + APEX_SEARCH_M) / step) - lo + 1)
    if a_hi <= a_lo:
        a_lo, a_hi = 0, speed.size

    def at(i: int) -> float:
        return float(d[lo + i])

    attack = (
        np.zeros(speed.size, dtype=bool)  # speed-only data: never "flat", phases from speed
        if throttle is None
        else (throttle >= FULL_THROTTLE) & ~braking
    )
    applications = int(np.count_nonzero(np.diff(braking.astype(np.int8), prepend=0) == 1))

    if throttle is not None and attack[a_lo:a_hi].all():
        m = min(speed.size - 1, max(0, round(seg.apex_m[0] / step) - lo))
        v = float(speed[m])
        return CornerPoints(
            name=seg.name, entry_m=at(m), brake_on_m=None, brake_off_m=None,
            brake_applications=applications, apex_m=at(m), mid_start_m=at(m), mid_end_m=at(m),
            pickup_m=at(m), full_throttle_m=at(m), entry_speed=v, apex_speed=v, exit_speed=v,
            flat=True,
        )

    apex = a_lo + int(np.argmin(speed[a_lo:a_hi]))
    vmin = float(speed[apex])

    # Minimum-speed zone: contiguous run around the apex within tolerance of vmin.
    slow = speed <= vmin * (1.0 + mid_speed_tol)
    left = _last(~slow[:apex])
    right = _first(~slow[apex:])
    mid_start = 0 if left is None else left + 1
    mid_end = speed.size - 1 if right is None else apex + right - 1

    e = _last(attack[:mid_start])
    entry = 0 if e is None else e
    f = _first(attack[mid_end:])
    full = speed.size - 1 if f is None else mid_end + f

    b_on = _first(braking[entry:full])
    brake_on = None if b_on is None else entry + b_on
    brake_off = None
    if brake_on is not None:
        released = _first(~braking[brake_on:])
        brake_off = speed.size - 1 if released is None else brake_on + released - 1

    after = brake_off if brake_off is not None else entry
    if throttle is None:
        pickup = mid_end
    else:
        p = _first((throttle[after:] >= PICKUP_THROTTLE) & ~braking[after:])
        pickup = mid_end if p is None else after + p

    return CornerPoints(
        name=seg.name,
        entry_m=at(entry),
        brake_on_m=None if brake_on is None else at(brake_on),
        brake_off_m=None if brake_off is None else at(brake_off),
        brake_applications=applications,
        apex_m=at(apex),
        mid_start_m=at(mid_start),
        mid_end_m=at(mid_end),
        pickup_m=at(pickup),
        full_throttle_m=at(full),
        entry_speed=float(speed[entry]),
        apex_speed=vmin,
        exit_speed=float(speed[full]),
        flat=False,
    )


def analyse_corners(lap: ResampledLap, segments: Sequence[Segment]) -> list[CornerPoints]:
    return [corner_points(lap, s) for s in segments]


@dataclass(frozen=True, slots=True)
class CornerComparison:
    """One corner: both laps' key points and the time delta per phase.

    Phases are cut at the *reference* lap's boundaries, so the per-phase deltas sum exactly to
    the segment delta.
    """

    segment: Segment
    reference: CornerPoints
    other: CornerPoints
    phase_delta_s: F64  # aligned with PHASES

    @property
    def delta_s(self) -> float:
        return float(self.phase_delta_s.sum())

    def to_dict(self) -> dict[str, Any]:
        return {
            "name": self.segment.name,
            "start_m": self.segment.start_m,
            "end_m": self.segment.end_m,
            "delta_s": self.delta_s,
            "phase_delta_s": dict(zip(PHASES, map(float, self.phase_delta_s), strict=True)),
            "reference": asdict(self.reference),
            "other": asdict(self.other),
        }


def compare_corners(cmp: LapComparison, segments: Sequence[Segment]) -> list[CornerComparison]:
    """Phase-by-phase comparison of every corner segment."""
    step, n = cmp.reference.step_m, len(cmp.reference)
    out = []
    for seg in segments:
        ref = corner_points(cmp.reference, seg)
        oth = corner_points(cmp.other, seg)
        edges = np.array([seg.start_m, *ref.bounds_m, seg.end_m])
        idx = np.clip(np.round(edges / step).astype(np.intp), 0, n - 1)
        idx = np.maximum.accumulate(idx)  # phases may be zero-length, never negative
        out.append(CornerComparison(seg, ref, oth, np.diff(cmp.delta_s[idx])))
    return out
