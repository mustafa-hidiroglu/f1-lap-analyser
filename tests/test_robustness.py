"""Regression tests for review findings: input validation and corrupt-data handling."""

from __future__ import annotations

import json
from pathlib import Path

import numpy as np
import polars as pl
import pyarrow as pa
import pyarrow.parquet as pq
import pytest
from conftest import MakeLap

from f1lap.cli import main
from f1lap.ingest import trace_from_columns
from f1lap.ingest.file_source import read_trace
from f1lap.resample import MAX_GRID_SAMPLES, distance_grid, resample_to_distance
from f1lap.store import read_lap, write_lap
from f1lap.trace import LapMeta, LapTrace, TraceError


def _base(n: int) -> dict[str, np.ndarray]:
    d = np.arange(float(n))
    return {"distance": d, "time": d, "speed": d}


def test_discrete_nan_is_forward_filled() -> None:
    t = LapTrace({**_base(5), "gear": np.array([np.nan, 3.0, np.nan, 4.0, np.nan])})
    np.testing.assert_array_equal(t["gear"], [3, 3, 3, 4, 4])


@pytest.mark.parametrize("bad", [[3.0, 3.9, 4.0], [3.0, 40000.0, 4.0], [np.nan] * 3])
def test_discrete_invalid_values_rejected(bad: list[float]) -> None:
    with pytest.raises(TraceError):
        LapTrace({**_base(3), "gear": np.array(bad)})


def test_caller_arrays_untouched() -> None:
    chans = _base(4)
    t = LapTrace(chans)
    assert all(a.flags.writeable for a in chans.values())
    assert not t["distance"].flags.writeable


@pytest.mark.parametrize("n", [0, 1])
def test_degenerate_traces(n: int) -> None:
    with pytest.raises(TraceError):
        resample_to_distance(LapTrace(_base(n)), 1.0)


def test_distance_spike_rejected() -> None:
    d = np.array([0.0, 1.0, 1e6, 2.0, 3.0])
    with pytest.raises(TraceError, match="jumps"):
        resample_to_distance(LapTrace({"distance": d, "time": d, "speed": d}), 1.0)


def test_grid_size_capped() -> None:
    with pytest.raises(ValueError, match="max"):
        distance_grid(5000.0, 5000.0 / (MAX_GRID_SAMPLES + 10))


def test_raw_length_recorded(make_lap: MakeLap) -> None:
    lap = resample_to_distance(make_lap(length=5000.6), 1.0)
    assert lap.meta.raw_length_m == pytest.approx(5000.6)
    assert lap.grid_end_m == 5000.0
    assert lap.meta.normalised_to_m is None


def test_fastf1_text_time_column() -> None:
    t = trace_from_columns(
        {"Time": np.array(["0 days 00:00:00", "0 days 00:00:01.500"], dtype=object),
         "Distance": [0.0, 50.0], "Speed": [100.0, 120.0]},
        LapMeta(),
    )
    np.testing.assert_allclose(t["time"], [0.0, 1.5])


def test_csv_with_empty_cells(tmp_path: Path) -> None:
    csv = tmp_path / "lap.csv"
    csv.write_text("Distance,Time,Speed,nGear\n0,0,100,3\n10,0.1,110,\n20,0.2,,4\n30,0.3,130,4\n")
    lap = resample_to_distance(read_trace(csv), 10.0)
    np.testing.assert_array_equal(lap["gear"], [3, 3, 4, 4])
    np.testing.assert_allclose(lap["speed"], [100, 110, 120, 130])


def test_cli_malformed_csv(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    csv = tmp_path / "bad.csv"
    csv.write_text('Distance,Time,Speed\n0,0,1\n"unterminated,1,2\n')
    assert main(["import", str(csv)]) == 1
    assert "f1lap: error" in capsys.readouterr().err


def test_cli_zero_step_is_error(make_lap: MakeLap, tmp_path: Path) -> None:
    csv = tmp_path / "lap.csv"
    pl.DataFrame(dict(make_lap(n=50).channels)).write_csv(csv)
    assert main(["--step", "0", "-o", str(tmp_path / "o.parquet"), "import", str(csv)]) == 1


def _rewrite_meta(src: Path, dst: Path, **changes: object) -> None:
    table = pq.read_table(src)
    meta = json.loads(table.schema.metadata[b"f1lap"]) | changes
    pq.write_table(table.replace_schema_metadata({b"f1lap": json.dumps(meta).encode()}), dst)


def test_metadata_control_chars_stripped(make_lap: MakeLap, tmp_path: Path) -> None:
    src = write_lap(resample_to_distance(make_lap(n=100), 1.0), tmp_path / "a.parquet")
    _rewrite_meta(src, tmp_path / "b.parquet", driver="\x1b[2JEVIL\x07")
    assert read_lap(tmp_path / "b.parquet").meta.driver == "[2JEVIL"


def test_metadata_wrong_type_rejected(make_lap: MakeLap, tmp_path: Path) -> None:
    src = write_lap(resample_to_distance(make_lap(n=100), 1.0), tmp_path / "a.parquet")
    _rewrite_meta(src, tmp_path / "b.parquet", lap_number="7; rm -rf")
    with pytest.raises(ValueError, match="lap_number"):
        read_lap(tmp_path / "b.parquet")


def test_parquet_unknown_or_null_columns_rejected(make_lap: MakeLap, tmp_path: Path) -> None:
    src = write_lap(resample_to_distance(make_lap(n=100), 1.0), tmp_path / "a.parquet")
    table = pq.read_table(src)
    extra = table.append_column("tyre_temp", pa.array(np.zeros(table.num_rows)))
    pq.write_table(extra, tmp_path / "x.parquet")
    with pytest.raises(ValueError, match="unknown columns"):
        read_lap(tmp_path / "x.parquet")

    gear = pa.array([None] + [3] * (table.num_rows - 1), type=pa.int16())
    nulls = table.set_column(table.column_names.index("gear"), "gear", gear)
    pq.write_table(nulls, tmp_path / "n.parquet")
    with pytest.raises(ValueError, match="null"):
        read_lap(tmp_path / "n.parquet")


def test_time_starts_at_zero_when_first_row_dropped() -> None:
    d = np.array([np.nan, 10.0, 20.0, 30.0])
    t = np.array([0.0, 0.5, 1.0, 1.5])
    lap = resample_to_distance(LapTrace({"distance": d, "time": t, "speed": d}), 10.0)
    np.testing.assert_allclose(lap["time"], [0.0, 0.5, 1.0])


def test_numeric_text_time() -> None:
    t = trace_from_columns(
        {"Time": np.array(["0", "1.5"], dtype=object), "Distance": [0.0, 1.0], "Speed": [1, 1]},
        LapMeta(),
    )
    np.testing.assert_allclose(t["time"], [0.0, 1.5])


def test_max_gap_is_configurable() -> None:
    d = np.array([0.0, 600.0, 700.0])
    trace = LapTrace({"distance": d, "time": d, "speed": d})
    with pytest.raises(TraceError, match="max_gap_m"):
        resample_to_distance(trace, 100.0)
    assert len(resample_to_distance(trace, 100.0, max_gap_m=1000.0)) == 8


def test_cli_infinite_length(make_lap: MakeLap, tmp_path: Path) -> None:
    csv = tmp_path / "lap.csv"
    pl.DataFrame(dict(make_lap(n=50).channels)).write_csv(csv)
    assert main(["--length", "inf", "-o", str(tmp_path / "o.parquet"), "import", str(csv)]) == 1
