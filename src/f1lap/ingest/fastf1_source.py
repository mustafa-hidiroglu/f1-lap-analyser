"""FastF1 session telemetry -> `LapTrace`.

`fastf1` is imported lazily: it is slow to import and only needed when fetching.
"""

from __future__ import annotations

import asyncio
from pathlib import Path
from typing import TYPE_CHECKING, Any, Literal

from f1lap.ingest import trace_from_columns
from f1lap.trace import LapMeta, LapTrace

if TYPE_CHECKING:
    import pandas as pd

LapSelector = int | Literal["fastest"]


def trace_from_frame(frame: pd.DataFrame, meta: LapMeta) -> LapTrace:
    """Convert a FastF1 telemetry DataFrame (e.g. `Lap.get_telemetry()`) to a trace."""
    return trace_from_columns({str(c): frame[c].to_numpy() for c in frame.columns}, meta)


def _pick_lap(laps: Any, driver: str, lap: LapSelector) -> Any:
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
    import fastf1

    cache_dir.mkdir(parents=True, exist_ok=True)
    fastf1.Cache.enable_cache(str(cache_dir))
    fastf1.set_log_level("WARNING")

    ses = fastf1.get_session(year, event, session)
    ses.load(laps=True, telemetry=True, weather=False, messages=False)
    picked = _pick_lap(ses.laps, driver, lap)

    lap_time = picked["LapTime"]
    meta = LapMeta(
        driver=str(picked["Driver"]),
        lap_number=int(picked["LapNumber"]),
        lap_time_s=None if lap_time != lap_time else float(lap_time.total_seconds()),  # NaT-safe
        source="fastf1",
        year=year,
        event=str(ses.event["EventName"]),
        session=str(session),
    )
    return trace_from_frame(picked.get_telemetry(), meta)


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
