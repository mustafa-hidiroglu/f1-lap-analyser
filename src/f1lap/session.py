"""A loaded FastF1 session with memoised, resampled laps.

Extracting and resampling telemetry dominates analysis time (~11 ms per lap; a qualifying
session has ~90 valid laps, a race ~900), so laps, the circuit and the reference lap are
computed once per session and reused across comparisons and ratings. Not thread-safe: use
from one thread.
"""

from __future__ import annotations

from collections.abc import Callable
from functools import cached_property
from pathlib import Path
from typing import Any

import numpy as np

from f1lap import simbase
from f1lap.circuit import Circuit, Segment, corner_segments, detect_corners
from f1lap.context import LapContext, lap_context
from f1lap.ingest.fastf1_source import (
    LapSelector,
    circuit_from_session,
    lap_from_row,
    load_session,
    pick_lap,
    valid_rows,
)
from f1lap.resample import resample_to_distance
from f1lap.sim import CALIBRATION_LAPS, SimError, SimLap, simulate
from f1lap.trace import ResampledLap, TraceError


class LoadedSession:
    def __init__(
        self, ses: Any, step_m: float = 1.0, quick_threshold: float = 1.07,
        user_base: Path | None = None,
    ) -> None:
        self.ses = ses
        #: Where perfect laps simulated on demand are saved (None: simulate, don't save).
        self.user_base = user_base
        self._sim_error: SimError | None = None  # cached_property does not cache exceptions
        self.step_m = step_m
        self.quick_threshold = quick_threshold
        self._laps: dict[tuple[str, int], ResampledLap] = {}
        #: Called as `progress(done, total)` while `valid_laps` is built (set by the server).
        self.progress: Callable[[int, int], None] | None = None

    @classmethod
    def load(
        cls, year: int, event: str | int, session: str, *, cache_dir: Path, step_m: float = 1.0
    ) -> LoadedSession:
        return cls(load_session(year, event, session, cache_dir=cache_dir), step_m,
                   user_base=cache_dir / "simbase")

    def lap(self, driver: str, lap: LapSelector = "fastest") -> ResampledLap:
        return self._resampled(pick_lap(self.ses.laps, driver, lap))

    def _resampled(self, row: Any) -> ResampledLap:
        key = (str(row["Driver"]), int(row["LapNumber"]))
        if key not in self._laps:
            self._laps[key] = resample_to_distance(lap_from_row(self.ses, row), self.step_m)
        return self._laps[key]

    @cached_property
    def valid_laps(self) -> list[ResampledLap]:
        """Accurate, not deleted, no pit in/out, within `quick_threshold` of the fastest lap.
        Laps whose telemetry cannot be resampled are left out."""
        rows = [row for _, row in valid_rows(self.ses, self.quick_threshold).iterlaps()]
        laps = []
        for i, row in enumerate(rows):
            if self.progress is not None and i % 25 == 0:
                self.progress(i, len(rows))
            try:  # e.g. a car whose distance channel is unusable (ALB, 2025 Monza race)
                laps.append(self._resampled(row))
            except (KeyError, ValueError, TraceError):
                continue
        return laps

    def calibration_laps(self, k: int = CALIBRATION_LAPS) -> list[ResampledLap]:
        """The `k` fastest valid laps, resampling only those (a race has ~900 valid laps)."""
        rows = valid_rows(self.ses, self.quick_threshold)
        if rows.empty:
            # FastF1's accuracy check can fail for a whole session ("all laps marked as
            # inaccurate", e.g. without position data): fall back to quick non-pit laps.
            rows = self.ses.laps.pick_quicklaps(self.quick_threshold).pick_wo_box()
        rows = rows[rows["LapTime"].notna().to_numpy()].sort_values("LapTime")
        laps: list[ResampledLap] = []
        for _, row in rows.iterlaps():
            try:  # some drivers have no car telemetry at all (seen in 2018): take the next lap
                laps.append(self._resampled(row))
            except (KeyError, ValueError, TraceError):
                continue
            if len(laps) == k:
                break
        return laps

    @cached_property
    def sim(self) -> SimLap:
        """This session's perfect lap: from the shipped base, else the user base, else simulated
        now and saved to the user base. Raises `SimError` if the session cannot produce one."""
        if self._sim_error is not None:
            raise self._sim_error
        try:
            return self._find_or_simulate()
        except SimError as exc:
            self._sim_error = exc
            raise

    def _find_or_simulate(self) -> SimLap:
        key = simbase.SimKey.of_session(self.ses)
        bases = [simbase.PACKAGE_BASE] + ([self.user_base] if self.user_base else [])
        found = simbase.lookup(key, bases)
        if found is not None:
            return found
        for base in bases:
            reason = simbase.failures(base).get(key.label)
            if reason:
                raise SimError(reason)
        calib = self.calibration_laps()
        try:
            if not calib:
                raise SimError("no valid timed laps in this session",
                               permanent=len(self.ses.laps) > 0)
            sim = simulate(calib[0], calib)
        except SimError as exc:
            if self.user_base and exc.permanent:
                simbase.record_failure(self.user_base, key, str(exc))
            raise
        if self.user_base:
            # Return the stored form, so the first rating matches every later one.
            return simbase.load(simbase.save(sim, key, self.user_base))
        return sim

    def lap_context(self, driver: str, lap: LapSelector = "fastest") -> LapContext:
        """Traffic, flags, tyres and position fights around one lap."""
        return lap_context(self.ses, pick_lap(self.ses.laps, driver, lap))

    @cached_property
    def reference(self) -> ResampledLap:
        """The session's fastest valid lap: defines the shared grid and segments."""
        return min(self.valid_laps, key=lambda x: x.meta.lap_time_s or np.inf)

    @cached_property
    def circuit(self) -> Circuit:
        try:
            return circuit_from_session(self.ses)
        except (LookupError, ValueError):
            return detect_corners(self.reference)

    @cached_property
    def segments(self) -> list[Segment]:
        return corner_segments(self.circuit, self.reference)

    def info(self) -> dict[str, Any]:
        """Event, drivers and every lap with its validity — what a lap picker needs."""
        laps = self.ses.laps
        # From the lap flags, not `valid_laps`: listing laps must not resample ~90 of them.
        rows = valid_rows(self.ses, self.quick_threshold)
        valid = set(zip(rows["Driver"].astype(str), rows["LapNumber"].astype(int), strict=True))
        res = self.ses.results
        drivers = [
            {
                "code": str(r.Abbreviation),
                "team": str(r.TeamName),
                "color": f"#{r.TeamColor}" if isinstance(r.TeamColor, str) and r.TeamColor
                else None,
                "position": None if r.Position != r.Position else int(r.Position),
            }
            for r in res.itertuples(index=False)
        ]
        lap_rows = []
        for r in laps.itertuples(index=False):
            lap_time = r.LapTime
            lap_rows.append(
                {
                    "driver": str(r.Driver),
                    "lap": int(r.LapNumber),
                    "time_s": None if lap_time != lap_time else float(lap_time.total_seconds()),
                    "compound": None if not isinstance(r.Compound, str) else r.Compound,
                    "personal_best": bool(r.IsPersonalBest is True),
                    "valid": (str(r.Driver), int(r.LapNumber)) in valid,
                }
            )
        return {
            "year": int(self.ses.event.year),
            "event": str(self.ses.event["EventName"]),
            "session": str(self.ses.name),
            "drivers": drivers,
            "laps": lap_rows,
        }
