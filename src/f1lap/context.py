"""What happened around one lap: traffic, position fights, flags, tyres, pit stops.

Positions along the lap are stored as *fractions* of the lap (0-1), so they map onto any grid
(the rated lap's, or the perfect lap's, which may have a slightly different length).

`lap_context` reads a FastF1 session; the pure helpers below it take plain frames and arrays so
they can be tested offline.
"""

from __future__ import annotations

import contextlib
from dataclasses import asdict, dataclass, field
from typing import Any, Final

import numpy as np
import numpy.typing as npt
import pandas as pd

F64 = npt.NDArray[np.float64]

TRAFFIC_GAP_S: Final = 1.0  # car ahead closer than this (in time) = in its dirty air / a fight
PRESSURE_GAP_S: Final = 1.0  # car behind at the line closer than this = under pressure
MIN_TRAFFIC_FRACTION: Final = 0.01  # ignore traffic shorter than ~50 m
FLAG_NAMES: Final = {
    "2": "yellow flag",
    "4": "safety car",
    "5": "red flag",
    "6": "virtual safety car",
    "7": "virtual safety car (ending)",
}
DRS_OPEN: Final = 10  # FastF1 DRS channel: 10, 12, 14 = flap open


@dataclass(frozen=True, slots=True)
class Span:
    """A stretch of the lap, as fractions of the lap length, with what happened there."""

    start: float
    end: float
    what: str  # driver code ahead, or flag name
    value: float | None = None  # closest gap in seconds, for traffic

    def overlaps(self, start: float, end: float) -> bool:
        return self.start < end and start < self.end


@dataclass(frozen=True, slots=True)
class LapContext:
    session_kind: str = ""  # "race" | "qualifying" | ""
    lap_number: int | None = None
    race_laps: int | None = None
    compound: str | None = None
    tyre_life: int | None = None
    pit_in: bool = False
    pit_out: bool = False
    deleted: bool = False
    accurate: bool = True
    positions_gained: int = 0  # >0 gained, <0 lost on this lap
    car_behind: str | None = None
    car_behind_gap_s: float | None = None
    traffic: tuple[Span, ...] = ()
    flags: tuple[Span, ...] = ()
    drs_open: tuple[Span, ...] = field(default=())

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def session_kind(name: str, year: int | None = None) -> str:
    """"race" for grands prix and sprints, "qualifying" for qualifying and shootouts.

    FastF1 names follow each season's format: 2021's "Sprint Qualifying" was the sprint race,
    2023's sprint grid session is "Sprint Shootout", and from 2024 "Sprint Qualifying" is
    qualifying again."""
    n = name.strip().lower()
    if n == "sprint qualifying":
        return "race" if year == 2021 else "qualifying"
    if n == "qualifying" or "shootout" in n:
        return "qualifying"
    if n in {"race", "sprint"}:
        return "race"
    return ""


def spans(mask: npt.NDArray[np.bool_], frac: F64, labels: npt.NDArray[Any] | None = None,
          values: F64 | None = None) -> list[Span]:
    """Contiguous runs of `mask` (split where `labels` change) as `Span`s; `value` = run min."""
    out: list[Span] = []
    n = mask.size
    i = 0
    while i < n:
        if not mask[i]:
            i += 1
            continue
        j = i
        lab = labels[i] if labels is not None else ""
        while j + 1 < n and mask[j + 1] and (labels is None or labels[j + 1] == lab):
            j += 1
        if frac[j] - frac[i] >= MIN_TRAFFIC_FRACTION:
            v = float(np.nanmin(values[i : j + 1])) if values is not None else None
            out.append(Span(float(frac[i]), float(frac[j]), str(lab), v))
        i = j + 1
    return out


def traffic_spans(frac: F64, ahead: npt.NDArray[Any], gap_m: F64, speed_kmh: F64,
                  max_gap_s: float = TRAFFIC_GAP_S) -> list[Span]:
    """Where the car ahead was within `max_gap_s` (gap = distance / own speed)."""
    with np.errstate(divide="ignore", invalid="ignore"):
        gap_s = gap_m / np.maximum(speed_kmh / 3.6, 1.0)
    close = np.isfinite(gap_s) & (gap_s < max_gap_s) & (ahead.astype(str) != "")
    return spans(close, frac, ahead.astype(str), gap_s)


def flag_spans(status: pd.DataFrame, lap_start_s: float, lap_end_s: float,
               session_s: F64, frac: F64) -> list[Span]:
    """Track-status periods (session `Time` in seconds, `Status` code) during the lap, mapped to
    lap fractions through the lap's own (session time, fraction) samples."""
    if status.empty:
        return []
    times = status["Time"].to_numpy(dtype=float)
    codes = status["Status"].astype(str).to_numpy()
    out = []
    for k in range(len(times)):
        start = times[k]
        end = times[k + 1] if k + 1 < len(times) else np.inf
        name = FLAG_NAMES.get(codes[k])
        if name is None or end <= lap_start_s or start >= lap_end_s:
            continue
        a = float(np.interp(max(start, lap_start_s), session_s, frac))
        b = float(np.interp(min(end, lap_end_s), session_s, frac))
        out.append(Span(a, b, name))
    return out


def _seconds(value: Any) -> float | None:
    if value is None or value is pd.NaT or (isinstance(value, float) and np.isnan(value)):
        return None
    with contextlib.suppress(AttributeError):
        return float(value.total_seconds())
    return None


def _flag(value: Any) -> bool:
    """FastF1 flag columns hold numpy bools (`x is True` is never true for those) or NaN."""
    try:
        return bool(value) if value is not None and not pd.isna(value) else False
    except (TypeError, ValueError):
        return False


def _int(value: Any) -> int | None:
    try:
        return None if pd.isna(value) else int(value)
    except (TypeError, ValueError):
        return None


def lap_context(ses: Any, row: Any) -> LapContext:
    """Context for one FastF1 lap row. Never raises for missing data: unknown parts stay empty."""
    laps = ses.laps
    kind = session_kind(str(ses.name), int(ses.event.year))
    driver = str(row["Driver"])
    number = _int(row["LapNumber"])

    gained = 0
    car_behind = None
    behind_gap = None
    if kind == "race" and number is not None:
        pos = _int(row.get("Position"))
        prev = laps[(laps["Driver"] == driver) & (laps["LapNumber"] == number - 1)]
        prev_pos = _int(prev["Position"].iloc[0]) if len(prev) else None
        if pos is not None and prev_pos is not None:
            gained = prev_pos - pos
        end = _seconds(row.get("Time"))
        if pos is not None and end is not None:
            same = laps[(laps["LapNumber"] == number) & (laps["Position"] == pos + 1)]
            if len(same):
                gap = _seconds(same["Time"].iloc[0])
                if gap is not None and 0 <= gap - end < PRESSURE_GAP_S:
                    car_behind, behind_gap = str(same["Driver"].iloc[0]), gap - end

    traffic: list[Span] = []
    flags: list[Span] = []
    drs: list[Span] = []
    try:
        tel = row.get_telemetry()  # includes DriverAhead (only this one lap: ~60 ms)
        start, end = _seconds(row.get("LapStartTime")), _seconds(row.get("Time"))
        if start is not None and end is not None:  # drop padding outside the lap
            t = tel["SessionTime"].dt.total_seconds()
            tel = tel[((t >= start) & (t <= end)).to_numpy()]
        dist = tel["Distance"].to_numpy(dtype=float)
        dist = dist - dist[0]
        frac = dist / max(float(dist[-1]), 1.0)
        codes = {str(n): str(ses.get_driver(str(n))["Abbreviation"])
                 for n in pd.unique(tel["DriverAhead"].dropna()) if str(n)}
        ahead = np.array([codes.get(str(n), "") for n in tel["DriverAhead"]], dtype=object)
        traffic = traffic_spans(frac, ahead, tel["DistanceToDriverAhead"].to_numpy(dtype=float),
                                tel["Speed"].to_numpy(dtype=float))
        if "DRS" in tel:
            drs = spans(tel["DRS"].to_numpy(dtype=float) >= DRS_OPEN, frac)
        session_s = tel["SessionTime"].dt.total_seconds().to_numpy()
        status = getattr(ses, "track_status", None)
        if status is not None and len(status):
            frame = pd.DataFrame({"Time": status["Time"].dt.total_seconds(),
                                  "Status": status["Status"]})
            flags = flag_spans(frame, float(session_s[0]), float(session_s[-1]), session_s, frac)
    except Exception:  # telemetry gaps must not break a rating
        pass

    race_laps = _int(laps["LapNumber"].max()) if kind == "race" else None
    return LapContext(
        session_kind=kind,
        lap_number=number,
        race_laps=race_laps,
        compound=str(row["Compound"]) if isinstance(row.get("Compound"), str) else None,
        tyre_life=_int(row.get("TyreLife")),
        pit_in=_seconds(row.get("PitInTime")) is not None,
        pit_out=_seconds(row.get("PitOutTime")) is not None,
        deleted=_flag(row.get("Deleted")),
        accurate=_flag(row.get("IsAccurate")),
        positions_gained=gained,
        car_behind=car_behind,
        car_behind_gap_s=behind_gap,
        traffic=tuple(traffic),
        flags=tuple(flags),
        drs_open=tuple(drs),
    )
