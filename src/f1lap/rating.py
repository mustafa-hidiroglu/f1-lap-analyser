"""Lap rating: a lap against the driver's own theoretical best and against the field.

All laps are put on one reference grid and cut into the same corner segments. Segment times form
a (laps x segments) matrix; bests, ranks and percentiles are vectorised over it.

- theoretical best: the driver's best time in every segment, across their valid laps, summed.
- ultimate lap: the best time in every segment across all laps in the set, summed.
- rank / percentile: the rated lap's segment time against every *other* driver's best time in
  that segment (1 = fastest; percentile 100 = faster than all of them).
- score: mean segment percentile (0-100). Seconds are the primary result; the score is a
  scale-free summary for ranking laps and drivers.
"""

from __future__ import annotations

import asyncio
from collections.abc import Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import numpy as np
import numpy.typing as npt

from f1lap import schema
from f1lap.circuit import Segment
from f1lap.delta import align
from f1lap.ingest.fastf1_source import LapSelector
from f1lap.resample import nominal_length
from f1lap.trace import ResampledLap

F64 = npt.NDArray[np.float64]


@dataclass(frozen=True, slots=True)
class LapEntry:
    driver: str
    lap_number: int | None
    lap_time_s: float | None

    @classmethod
    def of(cls, lap: ResampledLap) -> LapEntry:
        return cls(lap.meta.driver, lap.meta.lap_number, lap.meta.lap_time_s)

    @property
    def label(self) -> str:
        return f"{self.driver} L{self.lap_number}" if self.lap_number else self.driver


@dataclass(frozen=True, slots=True)
class SegmentTimes:
    """Time spent in each segment by each lap: `times[lap, segment]`."""

    laps: tuple[LapEntry, ...]
    names: tuple[str, ...]
    bounds_m: F64  # segment edges, len(names) + 1
    times: F64

    def index(self, driver: str, lap_number: int | None) -> int:
        for i, e in enumerate(self.laps):
            if e.driver == driver and e.lap_number == lap_number:
                return i
        raise LookupError(f"no lap {lap_number} for {driver!r} in the set")


def segment_times(
    laps: Sequence[ResampledLap], reference: ResampledLap, segments: Sequence[Segment]
) -> SegmentTimes:
    """Segment times of every lap, on `reference`'s grid. Only boundary samples are gathered."""
    if not laps or not segments:
        raise ValueError("need at least one lap and one segment")
    edges = np.array([segments[0].start_m] + [s.end_m for s in segments])
    idx = np.clip(np.round(edges / reference.step_m).astype(np.intp), 0, len(reference) - 1)
    if np.any(np.diff(idx) <= 0):
        raise ValueError("segments must be at least one grid step long and in order")
    d = reference[schema.DISTANCE]
    bounds = d[idx]
    # The grid stops up to one step short of the line; if the last segment reaches the grid end,
    # extend it to the lap's full length so segment times sum to the complete lap time.
    end_gap = nominal_length(reference) - float(d[-1]) if idx[-1] == d.size - 1 else 0.0
    if end_gap > 0:
        bounds = bounds.copy()
        bounds[-1] += end_gap
    at_edges = np.empty((len(laps), idx.size))
    for i, lap in enumerate(laps):
        t = align(reference, lap)[schema.TIME]
        at_edges[i] = t[idx]
        if end_gap > 0:
            at_edges[i, -1] += end_gap * (t[-1] - t[-2]) / (d[-1] - d[-2])
    return SegmentTimes(
        laps=tuple(LapEntry.of(lap) for lap in laps),
        names=tuple(s.name for s in segments),
        bounds_m=bounds,
        times=np.diff(at_edges, axis=1),
    )


@dataclass(frozen=True, slots=True)
class LapRating:
    lap: LapEntry
    names: tuple[str, ...]
    lap_times: F64  # the rated lap, per segment
    own_best: F64  # driver's best per segment
    own_best_lap: tuple[int | None, ...]  # lap number that set each own best
    field_best: F64  # best of all laps per segment
    field_best_by: tuple[str, ...]  # who set it, e.g. "NOR L18"
    rank: npt.NDArray[np.intp]  # 1 = fastest among drivers
    percentile: F64  # share of other drivers slower, 0-100
    drivers: int
    laps: int  # laps in the comparison set

    @property
    def lap_time_s(self) -> float:
        return float(self.lap_times.sum())

    @property
    def theoretical_best_s(self) -> float:
        return float(self.own_best.sum())

    @property
    def ultimate_s(self) -> float:
        return float(self.field_best.sum())

    @property
    def score(self) -> float:
        return float(self.percentile.mean())

    def to_dict(self) -> dict[str, Any]:
        return {
            "driver": self.lap.driver,
            "lap_number": self.lap.lap_number,
            "lap_time_s": self.lap_time_s,
            "official_lap_time_s": self.lap.lap_time_s,
            "theoretical_best_s": self.theoretical_best_s,
            "time_left_s": self.lap_time_s - self.theoretical_best_s,
            "ultimate_s": self.ultimate_s,
            "gap_to_ultimate_s": self.lap_time_s - self.ultimate_s,
            "score": self.score,
            "drivers": self.drivers,
            "laps": self.laps,
            "segments": [
                {
                    "name": self.names[i],
                    "time_s": float(self.lap_times[i]),
                    "own_best_s": float(self.own_best[i]),
                    "own_best_lap": self.own_best_lap[i],
                    "lost_to_own_best_s": float(self.lap_times[i] - self.own_best[i]),
                    "field_best_s": float(self.field_best[i]),
                    "field_best_by": self.field_best_by[i],
                    "lost_to_field_s": float(self.lap_times[i] - self.field_best[i]),
                    "rank": int(self.rank[i]),
                    "percentile": float(self.percentile[i]),
                }
                for i in range(len(self.names))
            ],
        }


def rate(st: SegmentTimes, target: int) -> LapRating:
    """Rate lap `target` of `st` against its driver's laps and every other driver's bests."""
    lap = st.laps[target]
    rated = st.times[target]
    drivers = tuple(dict.fromkeys(e.driver for e in st.laps))
    owner = np.array([drivers.index(e.driver) for e in st.laps])

    # Best time per (driver, segment), vectorised per driver.
    best = np.full((len(drivers), len(st.names)), np.inf)
    for k in range(len(drivers)):
        best[k] = st.times[owner == k].min(axis=0)

    me = drivers.index(lap.driver)
    mine = np.flatnonzero(owner == me)
    own_arg = mine[st.times[mine].argmin(axis=0)]
    field_arg = st.times.argmin(axis=0)

    others = np.delete(best, me, axis=0)
    n_others = others.shape[0]
    rank = 1 + (others < rated).sum(axis=0)
    percentile = (
        100.0 * (others > rated).sum(axis=0) / n_others if n_others else np.full(rated.size, 100.0)
    )
    return LapRating(
        lap=lap,
        names=st.names,
        lap_times=rated,
        own_best=best[me],
        own_best_lap=tuple(st.laps[i].lap_number for i in own_arg),
        field_best=st.times[field_arg, np.arange(len(st.names))],
        field_best_by=tuple(st.laps[i].label for i in field_arg),
        rank=rank.astype(np.intp),
        percentile=percentile.astype(np.float64),
        drivers=len(drivers),
        laps=len(st.laps),
    )


def rate_fastf1_lap(
    year: int,
    event: str | int,
    session: str,
    driver: str,
    lap: LapSelector = "fastest",
    *,
    cache_dir: Path,
    step_m: float = 1.0,
) -> LapRating:
    """Rate one lap of a FastF1 session against the whole session's valid laps.

    Reference grid and corner segments come from the session's fastest lap and FastF1's circuit
    markers (falling back to telemetry-detected corners). Blocking — see `rate_fastf1_lap_async`.
    """
    from f1lap.circuit import corner_segments, detect_corners
    from f1lap.ingest.fastf1_source import (
        circuit_from_session,
        lap_from_session,
        load_session,
        session_laps,
    )
    from f1lap.resample import resample_to_distance

    ses = load_session(year, event, session, cache_dir=cache_dir)
    target = resample_to_distance(lap_from_session(ses, driver, lap), step_m)
    laps = [resample_to_distance(t, step_m) for t in session_laps(ses)]
    key = (target.meta.driver, target.meta.lap_number)
    if key not in {(x.meta.driver, x.meta.lap_number) for x in laps}:
        laps.append(target)  # e.g. a deleted or slow lap the session filter dropped

    reference = min(laps, key=lambda x: x.meta.lap_time_s or np.inf)
    try:
        circuit = circuit_from_session(ses)
    except (LookupError, ValueError):
        circuit = detect_corners(reference)
    st = segment_times(laps, reference, corner_segments(circuit, reference))
    return rate(st, st.index(*key))


async def rate_fastf1_lap_async(
    year: int,
    event: str | int,
    session: str,
    driver: str,
    lap: LapSelector = "fastest",
    *,
    cache_dir: Path,
    step_m: float = 1.0,
) -> LapRating:
    """Non-blocking wrapper for UIs: runs the session load and rating in a worker thread."""
    return await asyncio.to_thread(
        rate_fastf1_lap, year, event, session, driver, lap, cache_dir=cache_dir, step_m=step_m
    )
