"""A loaded FastF1 session with memoised, resampled laps.

Extracting and resampling telemetry dominates analysis time (~60 ms per lap; a qualifying
session has ~90 valid laps), so laps, the circuit and the reference lap are computed once per
session and reused across comparisons and ratings. Not thread-safe: use from one thread.
"""

from __future__ import annotations

from functools import cached_property
from pathlib import Path
from typing import Any

import numpy as np

from f1lap.circuit import Circuit, Segment, corner_segments, detect_corners
from f1lap.ingest.fastf1_source import (
    LapSelector,
    circuit_from_session,
    lap_from_row,
    load_session,
    pick_lap,
    valid_rows,
)
from f1lap.resample import resample_to_distance
from f1lap.trace import ResampledLap


class LoadedSession:
    def __init__(self, ses: Any, step_m: float = 1.0, quick_threshold: float = 1.07) -> None:
        self.ses = ses
        self.step_m = step_m
        self.quick_threshold = quick_threshold
        self._laps: dict[tuple[str, int], ResampledLap] = {}

    @classmethod
    def load(
        cls, year: int, event: str | int, session: str, *, cache_dir: Path, step_m: float = 1.0
    ) -> LoadedSession:
        return cls(load_session(year, event, session, cache_dir=cache_dir), step_m)

    def lap(self, driver: str, lap: LapSelector = "fastest") -> ResampledLap:
        return self._resampled(pick_lap(self.ses.laps, driver, lap))

    def _resampled(self, row: Any) -> ResampledLap:
        key = (str(row["Driver"]), int(row["LapNumber"]))
        if key not in self._laps:
            self._laps[key] = resample_to_distance(lap_from_row(self.ses, row), self.step_m)
        return self._laps[key]

    @cached_property
    def valid_laps(self) -> list[ResampledLap]:
        """Accurate, not deleted, no pit in/out, within `quick_threshold` of the fastest lap."""
        rows = valid_rows(self.ses, self.quick_threshold)
        return [self._resampled(row) for _, row in rows.iterlaps()]

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
