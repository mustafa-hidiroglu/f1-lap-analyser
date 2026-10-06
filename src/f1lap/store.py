"""Columnar persistence for resampled laps (Parquet, zstd, metadata in the schema)."""

from __future__ import annotations

import json
from dataclasses import asdict, fields
from pathlib import Path
from typing import Any

import pyarrow as pa
import pyarrow.parquet as pq

from f1lap import schema
from f1lap.trace import Array, LapMeta, ResampledLap

_META_KEY = b"f1lap"
_FORMAT_VERSION = 1
_KNOWN_COLUMNS = schema.CHANNELS.keys() | {schema.DISTANCE}
_META_TYPES: dict[str, tuple[type, ...]] = {
    "driver": (str,),
    "source": (str,),
    "event": (str,),
    "session": (str,),
    "lap_number": (int, type(None)),
    "year": (int, type(None)),
    "lap_time_s": (int, float, type(None)),
    "raw_length_m": (int, float, type(None)),
    "normalised_to_m": (int, float, type(None)),
}


def _printable(text: str) -> str:
    """Strip control characters (e.g. ANSI escapes) from untrusted metadata."""
    return "".join(c for c in text if c.isprintable())


def write_lap(lap: ResampledLap, path: Path) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    meta = {"version": _FORMAT_VERSION, "step_m": lap.step_m, **asdict(lap.meta)}
    table = pa.table(dict(lap.channels)).replace_schema_metadata(
        {_META_KEY: json.dumps(meta).encode()}
    )
    pq.write_table(table, path, compression="zstd")
    return path


def _parse_meta(path: Path, raw: bytes | None) -> tuple[float, LapMeta]:
    if raw is None:
        raise ValueError(f"{path} is not an f1lap lap file (missing metadata)")
    meta: Any = json.loads(raw)
    if not isinstance(meta, dict):
        raise ValueError(f"{path}: malformed f1lap metadata")
    if meta.get("version") != _FORMAT_VERSION:
        raise ValueError(f"{path}: unsupported f1lap format version {meta.get('version')!r}")
    step = meta.get("step_m")
    if not isinstance(step, int | float) or isinstance(step, bool):
        raise ValueError(f"{path}: invalid step_m {step!r}")

    values: dict[str, Any] = {}
    for f in fields(LapMeta):
        value = meta.get(f.name, f.default)
        if not isinstance(value, _META_TYPES[f.name]) or isinstance(value, bool):
            raise ValueError(f"{path}: invalid metadata field {f.name}={value!r}")
        values[f.name] = _printable(value) if isinstance(value, str) else value
    return float(step), LapMeta(**values)


def read_lap(path: Path) -> ResampledLap:
    table = pq.read_table(path)
    step_m, meta = _parse_meta(path, (table.schema.metadata or {}).get(_META_KEY))
    unknown = set(table.column_names) - _KNOWN_COLUMNS
    if unknown:
        raise ValueError(f"{path}: unknown columns {sorted(unknown)}")
    nulls = [c for c in table.column_names if table.column(c).null_count]
    if nulls:
        raise ValueError(f"{path}: null values in {nulls}")
    channels: dict[str, Array] = {
        name: table.column(name).to_numpy() for name in table.column_names
    }
    return ResampledLap(channels, step_m=step_m, meta=meta)


def lap_filename(lap: ResampledLap) -> str:
    """Filesystem-safe default name, e.g. `2024_italian_grand_prix_q_lec_l20.parquet`."""
    m = lap.meta
    parts = [str(m.year or ""), m.event, m.session, m.driver, f"l{m.lap_number or ''}"]
    name = "_".join(p for p in parts if p and p != "l").lower() or "lap"
    safe = "".join(c if c.isalnum() or c in "-_" else "_" for c in name)
    return f"{safe}.parquet"
