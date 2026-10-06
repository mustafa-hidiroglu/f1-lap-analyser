"""FastF1 session telemetry -> `LapTrace`.

`fastf1` is imported lazily: it is slow to import and only needed when fetching.
"""

from __future__ import annotations

import asyncio
from pathlib import Path
from typing import TYPE_CHECKING, Any, Literal

from f1lap.circuit import Circuit, Corner
from f1lap.ingest import trace_from_columns
from f1lap.trace import LapMeta, LapTrace

if TYPE_CHECKING:
    import pandas as pd

LapSelector = int | Literal["fastest"]


def trace_from_frame(frame: pd.DataFrame, meta: LapMeta) -> LapTrace:
    """Convert a FastF1 telemetry DataFrame (e.g. `Lap.get_telemetry()`) to a trace."""
    return trace_from_columns({str(c): frame[c].to_numpy() for c in frame.columns}, meta)


def pick_lap(laps: Any, driver: str, lap: LapSelector) -> Any:
    driver_laps = laps.pick_drivers(driver)
    if driver_laps.empty:
        raise LookupError(f"no laps for driver {driver!r}")
    if lap == "fastest":
        picked = driver_laps.pick_fastest()
        if picked is None:
            raise LookupError(f"no timed lap for driver {driver!r}")
        return picked
    rows = driver_laps.pick_laps(lap)
    if rows.empty:
        raise LookupError(f"driver {driver!r} has no lap {lap}")
    return rows.iloc[0]


def load_session(year: int, event: str | int, session: str, *, cache_dir: Path) -> Any:
    """Load a FastF1 session with laps and telemetry (blocking network/disk I/O)."""
    import fastf1

    cache_dir.mkdir(parents=True, exist_ok=True)
    fastf1.Cache.enable_cache(str(cache_dir))
    fastf1.set_log_level("WARNING")
    ses = fastf1.get_session(year, event, session)
    ses.load(laps=True, telemetry=True, weather=False, messages=False)
    return ses


def lap_from_session(ses: Any, driver: str, lap: LapSelector = "fastest") -> LapTrace:
    return lap_from_row(ses, pick_lap(ses.laps, driver, lap))


def session_laps(ses: Any, quick_threshold: float = 1.07) -> list[LapTrace]:
    """Every valid lap in the session: within `quick_threshold` x the fastest lap, accurate,
    not deleted (track limits), and not a pit in/out lap."""
    return [lap_from_row(ses, row) for _, row in valid_rows(ses, quick_threshold).iterlaps()]


def valid_rows(ses: Any, quick_threshold: float = 1.07) -> Any:
    """Session laps that are accurate, not deleted, not pit in/out, and within
    `quick_threshold` x the fastest lap."""
    laps = ses.laps.pick_quicklaps(quick_threshold).pick_wo_box()
    valid = laps["IsAccurate"].eq(True) & ~laps["Deleted"].eq(True)  # missing flag -> False
    return laps[valid.to_numpy()]


def lap_from_row(ses: Any, row: Any) -> LapTrace:
    lap_time = row["LapTime"]
    meta = LapMeta(
        driver=str(row["Driver"]),
        lap_number=int(row["LapNumber"]),
        lap_time_s=None if lap_time != lap_time else float(lap_time.total_seconds()),  # NaT-safe
        source="fastf1",
        year=int(ses.event.year),
        event=str(ses.event["EventName"]),
        session=str(ses.name),
    )
    return trace_from_frame(row.get_telemetry(), meta)


def circuit_from_frame(
    corners: pd.DataFrame, length_m: float, name: str, meta: dict[str, Any]
) -> Circuit:
    """Build a `Circuit` from FastF1's `CircuitInfo.corners` frame (pure, offline-testable)."""
    frame = corners.dropna(subset=["Distance"]).sort_values("Distance", kind="stable")
    frame = frame.drop_duplicates(subset=["Distance"], keep="first")
    if frame.empty:
        raise LookupError(f"no corner distances available for {name}")
    return Circuit(
        name=name,
        length_m=length_m,
        corners=tuple(
            Corner(
                number=int(row.Number),
                distance_m=float(row.Distance),
                letter=str(row.Letter or ""),
                x=float(row.X),
                y=float(row.Y),
            )
            for row in frame.itertuples(index=False)
        ),
        source="fastf1",
        meta=meta,
    )


def circuit_from_session(ses: Any) -> Circuit:
    """Corner markers from FastF1, measured along the session's fastest lap."""
    info = ses.get_circuit_info()
    if info is None:
        raise LookupError("FastF1 has no circuit info for this session")
    # Same reference lap and telemetry FastF1 uses for the marker distances.
    ref = ses.laps.pick_fastest().get_telemetry(frequency="original")
    name = str(ses.event["EventName"])
    meta = {"year": int(ses.event.year), "rotation_deg": float(info.rotation)}
    return circuit_from_frame(info.corners, float(ref["Distance"].iloc[-1]), name, meta)


def fetch_lap(
    year: int,
    event: str | int,
    session: str,
    driver: str,
    lap: LapSelector = "fastest",
    *,
    cache_dir: Path,
) -> LapTrace:
    """Download (or read from cache) one lap's merged car + position telemetry.

    Blocking network/disk I/O — use `fetch_lap_async` from async code.
    """
    return lap_from_session(load_session(year, event, session, cache_dir=cache_dir), driver, lap)


async def fetch_lap_async(
    year: int,
    event: str | int,
    session: str,
    driver: str,
    lap: LapSelector = "fastest",
    *,
    cache_dir: Path,
) -> LapTrace:
    """Non-blocking wrapper: runs the FastF1 load in a worker thread."""
    return await asyncio.to_thread(
        fetch_lap, year, event, session, driver, lap, cache_dir=cache_dir
    )
