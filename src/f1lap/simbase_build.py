"""Prebuild the perfect-lap base for whole seasons: `f1lap simbase build --years 2018-2026`.

Every non-practice session of every championship event that has already taken place gets one
simulated lap, saved under `out` (default: the shipped base). The run is resumable and safe to
interrupt: existing entries and recorded failures are skipped (`--retry-failed` retries the
latter); a rate-limited request waits and retries the same session instead of failing it;
network errors leave the session for the next run.

Disk and memory: FastF1 data goes to a separate build cache; each session's parsed data is
deleted after its lap is built, and the HTTP cache is reset when it passes `HTTP_CACHE_MAX`.
Only one session is loaded at a time.
"""

from __future__ import annotations

import asyncio
import gc
import logging
import shutil
from collections.abc import Callable, Iterator
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Final

import pandas as pd

from f1lap import simbase
from f1lap.session import LoadedSession
from f1lap.sim import SimError, simulate

log = logging.getLogger("f1lap.simbase")

HTTP_CACHE_MAX: Final = 1 << 30  # bytes
RATE_LIMIT_WAIT_S: Final = (60.0, 300.0, 900.0, 1800.0)
NETWORK_RETRIES: Final = 2


@dataclass(frozen=True, slots=True)
class Planned:
    year: int
    round: int
    event: str
    session: str


@dataclass
class Tally:
    built: int = 0
    skipped: int = 0
    failed: int = 0
    deferred: int = 0  # network trouble: left for the next run

    def __str__(self) -> str:
        return (f"built {self.built}, already present {self.skipped}, failed {self.failed}, "
                f"deferred {self.deferred}")


def competitive(name: str) -> bool:
    return bool(name) and not name.lower().startswith("practice")


def plan_year(schedule: pd.DataFrame, year: int, now: datetime) -> Iterator[Planned]:
    """Sessions of `schedule` (FastF1 event schedule) that are competitive and over."""
    for row in schedule.itertuples(index=False):
        for i in range(1, 6):
            name = getattr(row, f"Session{i}", None)
            date = getattr(row, f"Session{i}DateUtc", None)
            if not isinstance(name, str) or not competitive(name):
                continue
            if date is None or pd.isna(date) or pd.Timestamp(date).tz_localize(None) > (
                    pd.Timestamp(now).tz_localize(None)):
                continue
            yield Planned(year, int(row.RoundNumber), str(row.EventName), name)


def _session_dir(cache: Path, ses: Any) -> Path | None:
    api = str(getattr(ses, "api_path", "") or "")
    rel = api.removeprefix("/static/").strip("/")
    return cache / rel if rel else None


def _trim_cache(cache: Path, ses: Any, existed: bool) -> None:
    """Free the session's parsed data — only if this build downloaded it (never delete a cache
    the app or the user filled)."""
    d = _session_dir(cache, ses)
    if not existed and d is not None and d.is_dir():
        shutil.rmtree(d, ignore_errors=True)
    http = cache / "fastf1_http_cache.sqlite"
    if http.exists() and http.stat().st_size > HTTP_CACHE_MAX:
        http.unlink(missing_ok=True)


def build_one(p: Planned, out: Path, cache: Path, step_m: float = 1.0) -> Path:
    """Load one session, simulate its perfect lap, save it. Blocking: run in a worker thread."""
    import fastf1

    fastf1.Cache.enable_cache(str(cache))
    fastf1.set_log_level("ERROR")
    ses = fastf1.get_session(p.year, p.round, p.session)
    d = _session_dir(cache, ses)
    existed = d is not None and d.is_dir()
    try:
        ses.load(laps=True, telemetry=True, weather=False, messages=False)
        sd = LoadedSession(ses, step_m)
        calib = sd.calibration_laps()
        if not calib:
            raise SimError("no valid timed laps", permanent=len(ses.laps) > 0)
        sim = simulate(calib[0], calib)
        key = simbase.SimKey.of_session(ses)
        return simbase.save(sim, key, out)
    finally:
        _trim_cache(cache, ses, existed)
        del ses
        gc.collect()


def _is_rate_limit(exc: BaseException) -> bool:
    return type(exc).__name__ == "RateLimitExceededError"


def _is_network(exc: BaseException) -> bool:
    import requests

    return isinstance(exc, requests.RequestException | ConnectionError | TimeoutError)


async def build(
    years: range, out: Path, cache: Path, *, retry_failed: bool = False,
    only: Callable[[Planned], bool] | None = None, now: datetime | None = None,
) -> Tally:
    import fastf1

    now = now or datetime.now(UTC)
    cache.mkdir(parents=True, exist_ok=True)
    fastf1.Cache.enable_cache(str(cache))
    fastf1.set_log_level("ERROR")
    tally = Tally()
    for year in years:
        try:
            schedule = await asyncio.to_thread(
                fastf1.get_event_schedule, year, include_testing=False)
        except Exception as exc:
            log.warning("%d: no schedule (%s); skipped", year, exc)
            tally.deferred += 1
            continue
        for p in plan_year(schedule, year, now):
            if only is not None and not only(p):
                continue
            await _build_planned(p, out, cache, retry_failed, tally)
    log.info("done: %s", tally)
    return tally


async def _build_planned(p: Planned, out: Path, cache: Path, retry_failed: bool,
                         tally: Tally) -> None:
    label = f"{p.year} R{p.round} {p.event} {p.session}"
    # Keys come from the loaded session; the schedule's names match FastF1's for that year.
    key = simbase.SimKey(p.year, p.event, p.session)
    if (out / key.relpath).exists():
        tally.skipped += 1
        return
    if key.label in simbase.failures(out) and not retry_failed:
        tally.skipped += 1
        return
    waits = iter(RATE_LIMIT_WAIT_S)
    network = 0
    while True:
        try:
            path = await asyncio.to_thread(build_one, p, out, cache)
        except Exception as exc:
            if _is_rate_limit(exc):
                wait = next(waits, None)
                if wait is None:
                    log.warning("%s: still rate limited; deferred", label)
                    tally.deferred += 1
                    return
                log.info("%s: rate limited, waiting %.0f s", label, wait)
                await asyncio.sleep(wait)
                continue
            if _is_network(exc) and network < NETWORK_RETRIES:
                network += 1
                await asyncio.sleep(30.0 * network)
                continue
            if not isinstance(exc, SimError) or not exc.permanent:
                # Load/network/library errors may be transient: retry on the next run.
                log.warning("%s: %s: %s; deferred", label, type(exc).__name__, exc)
                tally.deferred += 1
                return
            reason = str(exc)[:300]
            log.warning("%s: no perfect lap — %s", label, reason)
            simbase.record_failure(out, key, reason)
            tally.failed += 1
            return
        simbase.record_failure(out, key, None)
        tally.built += 1
        log.info("%s: saved %s", label, path.relative_to(out))
        return
