from __future__ import annotations

from pathlib import Path

import numpy as np
import pandas as pd
import polars as pl
import pytest
from conftest import MakeLap

from f1lap.cli import main
from f1lap.ingest.fastf1_source import trace_from_frame
from f1lap.ingest.file_source import read_trace
from f1lap.resample import resample_to_distance
from f1lap.store import lap_filename, read_lap, write_lap
from f1lap.trace import LapMeta


def test_parquet_roundtrip_is_lossless(make_lap: MakeLap, tmp_path: Path) -> None:
    lap = resample_to_distance(make_lap(), 1.0)
    back = read_lap(write_lap(lap, tmp_path / "lap.parquet"))
    assert back.meta == lap.meta
    assert back.step_m == lap.step_m
    assert back.channels.keys() == lap.channels.keys()
    for name, arr in lap.channels.items():
        assert back[name].dtype == arr.dtype
        np.testing.assert_array_equal(back[name], arr)


def test_read_rejects_foreign_parquet(tmp_path: Path) -> None:
    path = tmp_path / "x.parquet"
    pl.DataFrame({"distance": [0.0]}).write_parquet(path)
    with pytest.raises(ValueError, match="not an f1lap"):
        read_lap(path)


def test_lap_filename_is_safe(make_lap: MakeLap) -> None:
    lap = resample_to_distance(make_lap(n=100), 1.0)
    assert lap_filename(lap) == "tst_l7.parquet"


def _fastf1_style_frame(make_lap: MakeLap) -> pd.DataFrame:
    t = make_lap(n=300)
    return pd.DataFrame(
        {
            "Date": pd.date_range("2024-09-01", periods=len(t), freq="100ms"),
            "Time": pd.to_timedelta(t["time"], unit="s"),
            "Distance": t["distance"],
            "Speed": t["speed"],
            "Throttle": t["throttle"],
            "Brake": t["brake"] > 0,
            "nGear": t["gear"],
            "RPM": t["rpm"],
            "DRS": t["drs"],
            "X": t["x"],
            "Y": t["y"],
            "Z": np.zeros(len(t)),
            "Source": "car",
        }
    )


def test_fastf1_frame_conversion(make_lap: MakeLap) -> None:
    frame = _fastf1_style_frame(make_lap)
    trace = trace_from_frame(frame, LapMeta(driver="TST"))
    assert set(trace.channels) == {
        "distance", "time", "speed", "throttle", "brake", "gear", "rpm", "drs", "x", "y", "z",
    }
    np.testing.assert_allclose(trace["time"], make_lap(n=300)["time"], atol=1e-6)
    assert set(np.unique(trace["brake"])) <= {0.0, 1.0}
    assert trace["gear"].dtype == np.int16


@pytest.mark.parametrize("suffix", [".csv", ".parquet"])
def test_file_source(make_lap: MakeLap, tmp_path: Path, suffix: str) -> None:
    t = make_lap(n=200)
    frame = pl.DataFrame({"Distance": t["distance"], "Time": t["time"], "Speed": t["speed"],
                          "nGear": t["gear"], "unrelated": np.zeros(len(t))})
    path = tmp_path / f"lap{suffix}"
    frame.write_csv(path) if suffix == ".csv" else frame.write_parquet(path)
    trace = read_trace(path, driver="TST")
    assert set(trace.channels) == {"distance", "time", "speed", "gear"}
    np.testing.assert_allclose(trace["speed"], t["speed"])


def test_file_source_rejects_unknown_type(tmp_path: Path) -> None:
    with pytest.raises(ValueError, match="unsupported"):
        read_trace(tmp_path / "lap.json")


def test_cli_import_then_info(
    make_lap: MakeLap, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    t = make_lap(n=500)
    csv = tmp_path / "lap.csv"
    pl.DataFrame({k: v for k, v in t.channels.items()}).write_csv(csv)
    out = tmp_path / "out.parquet"
    cfg = tmp_path / "missing.toml"

    assert main(["--config", str(cfg), "--step", "2", "-o", str(out), "import", str(csv)]) == 0
    assert read_lap(out).step_m == 2.0
    assert main(["--config", str(cfg), "info", str(out)]) == 0
    assert "2501 x 2.0 m" in capsys.readouterr().out


def test_cli_reports_errors(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    assert main(["info", str(tmp_path / "missing.parquet")]) == 1
    assert "f1lap: error" in capsys.readouterr().err
