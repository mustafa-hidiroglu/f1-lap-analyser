"""The perfect-lap base: one simulated lap per (season, event, session), stored as Parquet.

- The shipped base (`f1lap/simbase/`, built by `f1lap simbase build`) is read-only package data.
- Sessions missing from it are simulated on demand and saved to the user base
  (`<cache_dir>/simbase/`), so the network and the simulation run once per session.
- Keys come from the *loaded* FastF1 session (`ses.event["EventName"]`, `ses.name`) plus the
  year, so naming changes across seasons (e.g. "Sprint Qualifying" was the sprint race in 2021,
  "Sprint Shootout" in 2023) never mix sessions.

Files hold speed (float32) and the active limit (int8: brake / grip / accelerate) on a
`STORE_STEP_M` grid, plus the track outline; time is re-integrated on load. ~25 KB per session.
Sessions that cannot be simulated are listed in `_failures.json` with the reason.
"""

from __future__ import annotations

import json
import logging
import unicodedata
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any, Final

import numpy as np
import pyarrow as pa
import pyarrow.parquet as pq

from f1lap import schema
from f1lap.resample import rescale
from f1lap.sim import GRIP_THROTTLE, MODEL_VERSION, SIM_DRIVER, SPEED, CarModel, SimLap
from f1lap.trace import LapMeta, ResampledLap

log = logging.getLogger("f1lap.simbase")

PACKAGE_BASE: Final = Path(__file__).parent / "simbase"
STORE_STEP_M: Final = 2.0
FAILURES: Final = "_failures.json"
_META_KEY: Final = b"f1lap.sim"
_FORMAT: Final = 1
_BRAKE, _GRIP, _ACCEL = 0, 1, 2


@dataclass(frozen=True, slots=True)
class SimKey:
    year: int
    event: str  # FastF1 EventName, e.g. "British Grand Prix"
    session: str  # FastF1 session name, e.g. "Qualifying"

    @property
    def relpath(self) -> Path:
        return Path(str(self.year)) / f"{slug(self.event)}__{slug(self.session)}.parquet"

    @property
    def label(self) -> str:
        return f"{self.year} {self.event} {self.session}"

    @classmethod
    def of_session(cls, ses: Any) -> SimKey:
        return cls(int(ses.event.year), str(ses.event["EventName"]), str(ses.name))


def slug(text: str) -> str:
    """ASCII, lower-case, dash-separated: "São Paulo Grand Prix" -> "sao-paulo-grand-prix"."""
    ascii_text = unicodedata.normalize("NFKD", text).encode("ascii", "ignore").decode()
    words = "".join(c if c.isalnum() else " " for c in ascii_text.lower()).split()
    return "-".join(words) or "unnamed"


def save(sim: SimLap, key: SimKey, base: Path) -> Path:
    """Write `sim` under `base` (atomically: readers never see a partial file)."""
    lap = rescale(sim.lap, sim.lap.meta.raw_length_m or sim.lap.grid_end_m, STORE_STEP_M)
    state = np.where(lap["brake"] >= 0.5, _BRAKE,
                     np.where(lap["throttle"] >= 99.0, _ACCEL, _GRIP)).astype(np.int8)
    columns: dict[str, Any] = {
        "speed": lap[SPEED].astype(np.float32),
        "state": state,
    }
    for c in ("x", "y"):
        if c in lap.channels:
            columns[c] = lap[c].astype(np.float32)
    meta = {
        "format": _FORMAT,
        "key": asdict(key),
        "step_m": STORE_STEP_M,
        "length_m": sim.lap.meta.raw_length_m or sim.lap.grid_end_m,
        **sim.to_dict(),
    }
    path = base / key.relpath
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(".tmp")
    table = pa.table(columns).replace_schema_metadata({_META_KEY: json.dumps(meta).encode()})
    pq.write_table(table, tmp, compression="zstd")
    tmp.replace(path)
    return path


def load(path: Path) -> SimLap:
    table = pq.read_table(path)
    raw = (table.schema.metadata or {}).get(_META_KEY)
    if raw is None:
        raise ValueError(f"{path} is not a perfect-lap file")
    meta: dict[str, Any] = json.loads(raw)
    if meta.get("format") != _FORMAT:
        raise ValueError(f"{path}: unsupported perfect-lap format {meta.get('format')!r}")
    step = float(meta["step_m"])
    speed = table.column("speed").to_numpy().astype(np.float64)
    state = table.column("state").to_numpy()
    d = np.arange(speed.size) * step
    v = np.maximum(speed / 3.6, 1.0)
    t = np.concatenate(([0.0], np.cumsum(2.0 * step / (v[1:] + v[:-1]))))
    # Match the stored lap time (simulated on a finer grid) at the line.
    length, lap_time = float(meta["length_m"]), float(meta["lap_time_s"])
    t *= (lap_time - max(length - d[-1], 0.0) / v[-1]) / t[-1]
    channels: dict[str, Any] = {
        schema.DISTANCE: d,
        schema.TIME: t,
        SPEED: speed,
        "throttle": np.select([state == _ACCEL, state == _GRIP], [100.0, GRIP_THROTTLE], 0.0),
        "brake": (state == _BRAKE).astype(np.float64),
    }
    for c in ("x", "y"):
        if c in table.column_names:
            channels[c] = table.column(c).to_numpy().astype(np.float64)
    key = meta["key"]
    lap = ResampledLap(channels, step_m=step, meta=LapMeta(
        driver=SIM_DRIVER, lap_time_s=float(meta["lap_time_s"]), source="sim",
        year=int(key["year"]), event=str(key["event"]), session=str(key["session"]),
        raw_length_m=float(meta["length_m"]),
    ))
    return SimLap(
        lap=lap,
        model=CarModel.from_dict(meta["model"]),
        calibration=tuple(
            (str(c["driver"]), c["lap_number"], c["lap_time_s"]) for c in meta["calibration"]
        ),
        fastest_lap_s=meta.get("fastest_lap_s"),
        version=int(meta.get("version", MODEL_VERSION)),
    )


def lookup(key: SimKey, bases: list[Path]) -> SimLap | None:
    """The first stored sim for `key` in `bases` with the current model version (no network).
    Unreadable files are skipped (logged), so the session is simulated again."""
    for base in bases:
        path = base / key.relpath
        if path.exists():
            try:
                sim = load(path)
            except (OSError, ValueError, KeyError, TypeError, pa.ArrowException) as exc:
                log.warning("ignoring unreadable perfect lap %s: %s", path, exc)
                continue
            if sim.version == MODEL_VERSION:
                return sim
    return None


def _failure_file(base: Path) -> dict[str, Any]:
    try:
        data = json.loads((base / FAILURES).read_text())
    except (OSError, json.JSONDecodeError):
        return {}
    return data if isinstance(data, dict) else {}


def failures(base: Path) -> dict[str, str]:
    """Sessions without a perfect lap under the *current* model version, with the reason.
    Failures recorded by an older model are ignored, so a better model retries them."""
    return {
        str(k): str(v["reason"]) for k, v in _failure_file(base).items()
        if isinstance(v, dict) and v.get("version") == MODEL_VERSION and "reason" in v
    }


def record_failure(base: Path, key: SimKey, reason: str | None) -> None:
    """Record (or with `reason=None` clear) why `key` has no perfect lap."""
    data = _failure_file(base)
    if reason is None:
        if data.pop(key.label, None) is None:
            return
    else:
        data[key.label] = {"reason": reason, "version": MODEL_VERSION}
    base.mkdir(parents=True, exist_ok=True)
    tmp = base / (FAILURES + ".tmp")
    tmp.write_text(json.dumps(dict(sorted(data.items())), indent=1))
    tmp.replace(base / FAILURES)
