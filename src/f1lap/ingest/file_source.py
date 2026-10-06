"""CSV / Parquet telemetry exports (FastF1 or canonical column names)."""

from __future__ import annotations

from pathlib import Path

import polars as pl

from f1lap.ingest import trace_from_columns
from f1lap.trace import LapMeta, LapTrace


def read_trace(path: Path, driver: str = "", lap_number: int | None = None) -> LapTrace:
    suffix = path.suffix.lower()
    if suffix == ".parquet":
        frame = pl.read_parquet(path)
    elif suffix == ".csv":
        frame = pl.read_csv(path)
    else:
        raise ValueError(f"unsupported telemetry file type {suffix!r} (expected .csv or .parquet)")
    columns = {name: frame.get_column(name).to_numpy() for name in frame.columns}
    return trace_from_columns(
        columns, LapMeta(driver=driver, lap_number=lap_number, source=str(path))
    )
