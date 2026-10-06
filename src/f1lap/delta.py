"""Delta-time against a reference lap, and micro-sector breakdown.

Sign convention: deltas are `other - reference`, so a positive value means the compared lap is
slower (losing time) at that point.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any

import numpy as np
import numpy.typing as npt

from f1lap import schema
from f1lap.resample import nominal_length, rescale
from f1lap.trace import ResampledLap

if TYPE_CHECKING:
    from f1lap.circuit import Segment

F64 = npt.NDArray[np.float64]


@dataclass(frozen=True, slots=True)
class LapComparison:
    """Two laps on an identical distance grid plus the delta-time trace between them."""

    reference: ResampledLap
    other: ResampledLap
    delta_s: F64  # other.time - reference.time at each grid point

    @property
    def distance(self) -> F64:
        d: F64 = self.reference[schema.DISTANCE]
        return d

    @property
    def final_delta_s(self) -> float:
        """Delta at the last grid point (≤ one step before the line)."""
        return float(self.delta_s[-1])

    @property
    def lap_time_delta_s(self) -> float | None:
        """Official lap-time difference, when both laps carry one."""
        ref, oth = self.reference.meta.lap_time_s, self.other.meta.lap_time_s
        return None if ref is None or oth is None else oth - ref


def _same_grid(a: ResampledLap, b: ResampledLap) -> bool:
    return (
        a.step_m == b.step_m
        and len(a) == len(b)
        and nominal_length(a) == nominal_length(b)
    )


def align(reference: ResampledLap, other: ResampledLap) -> ResampledLap:
    """`other` on `reference`'s grid (distance rescaled to the reference length if needed)."""
    if not _same_grid(reference, other):
        other = rescale(other, nominal_length(reference), reference.step_m)
    if len(other) != len(reference):
        raise ValueError("laps could not be aligned onto a common grid")
    return other


def compare(reference: ResampledLap, other: ResampledLap) -> LapComparison:
    """Put `other` on `reference`'s grid and diff lap time.

    The reference lap is never altered: its nominal length and step define the shared grid.
    """
    other = align(reference, other)
    delta = other[schema.TIME] - reference[schema.TIME]
    delta.flags.writeable = False
    return LapComparison(reference, other, delta)


@dataclass(frozen=True, slots=True)
class SectorTable:
    """Per-sector comparison (Structure of Arrays, one entry per sector)."""

    names: tuple[str, ...]
    start_m: F64
    end_m: F64
    ref_time_s: F64
    other_time_s: F64
    delta_s: F64  # other - reference time spent in the sector
    ref_min_speed: F64
    other_min_speed: F64

    def __len__(self) -> int:
        return int(self.start_m.size)

    def rows(self) -> list[dict[str, Any]]:
        cols = {
            "start_m": self.start_m,
            "end_m": self.end_m,
            "ref_time_s": self.ref_time_s,
            "other_time_s": self.other_time_s,
            "delta_s": self.delta_s,
            "ref_min_speed": self.ref_min_speed,
            "other_min_speed": self.other_min_speed,
        }
        return [
            {"name": self.names[i], **{k: float(v[i]) for k, v in cols.items()}}
            for i in range(len(self))
        ]


def micro_sectors(cmp: LapComparison, count: int = 25) -> SectorTable:
    """Split the shared grid into `count` equal-length sectors and time each lap through them.

    Sector deltas sum exactly to `cmp.final_delta_s` (both laps start at t=0, d=0).
    """
    n = len(cmp.reference)
    if not 1 <= count <= n - 1:
        raise ValueError(f"sector count must be in [1, {n - 1}], got {count}")
    bounds = np.round(np.linspace(0, n - 1, count + 1)).astype(np.intp)
    return _table(cmp, bounds, [f"S{i}" for i in range(1, count + 1)])


def corner_table(cmp: LapComparison, segments: Sequence[Segment]) -> SectorTable:
    """Per-corner-complex comparison; `segments` from `circuit.corner_segments` on the reference."""
    if not segments:
        raise ValueError("no segments")
    edges = np.array([segments[0].start_m] + [s.end_m for s in segments])
    bounds = np.round(edges / cmp.reference.step_m).astype(np.intp)
    np.clip(bounds, 0, len(cmp.reference) - 1, out=bounds)
    if np.any(np.diff(bounds) <= 0):
        raise ValueError("segments must be at least one grid step long and in order")
    return _table(cmp, bounds, [s.name for s in segments])


def _table(cmp: LapComparison, bounds: npt.NDArray[np.intp], names: Sequence[str]) -> SectorTable:
    starts = bounds[:-1]
    ref_t, oth_t = cmp.reference[schema.TIME], cmp.other[schema.TIME]
    d = cmp.distance
    return SectorTable(
        names=tuple(names),
        start_m=d[starts],
        end_m=d[bounds[1:]],
        ref_time_s=np.diff(ref_t[bounds]),
        other_time_s=np.diff(oth_t[bounds]),
        delta_s=np.diff(cmp.delta_s[bounds]),
        ref_min_speed=np.minimum.reduceat(cmp.reference["speed"], starts),
        other_min_speed=np.minimum.reduceat(cmp.other["speed"], starts),
    )


def _label(lap: ResampledLap) -> dict[str, Any]:
    m = lap.meta
    return {
        "driver": m.driver,
        "lap_number": m.lap_number,
        "lap_time_s": m.lap_time_s,
        "year": m.year,
        "event": m.event,
        "session": m.session,
        "source": m.source,
    }


def summary(cmp: LapComparison, sectors: SectorTable) -> dict[str, Any]:
    """JSON-serialisable comparison report."""
    return {
        "reference": _label(cmp.reference),
        "other": _label(cmp.other),
        "grid": {
            "step_m": cmp.reference.step_m,
            "samples": len(cmp.reference),
            "length_m": nominal_length(cmp.reference),
        },
        "final_delta_s": cmp.final_delta_s,
        "lap_time_delta_s": cmp.lap_time_delta_s,
        "max_gain_s": float(cmp.delta_s.min()),
        "max_gain_at_m": float(cmp.distance[int(cmp.delta_s.argmin())]),
        "max_loss_s": float(cmp.delta_s.max()),
        "max_loss_at_m": float(cmp.distance[int(cmp.delta_s.argmax())]),
        "sectors": sectors.rows(),
    }
