from __future__ import annotations

from pathlib import Path

import numpy as np
import pytest

from f1lap.config import ConfigError, load_settings
from f1lap.trace import LapTrace, TraceError


def test_trace_rejects_mismatched_lengths() -> None:
    with pytest.raises(TraceError, match="samples"):
        LapTrace({"distance": np.arange(3.0), "time": np.arange(3.0), "speed": np.arange(4.0)})


def test_trace_requires_core_channels() -> None:
    with pytest.raises(TraceError, match="missing"):
        LapTrace({"distance": np.arange(3.0), "speed": np.arange(3.0)})


def test_trace_rejects_unknown_channel() -> None:
    with pytest.raises(TraceError, match="unknown"):
        z = np.zeros(2)
        LapTrace({"distance": z, "time": z, "speed": z, "tyre_temp": z})


def _write_toml(tmp_path: Path) -> Path:
    cfg = tmp_path / "f1lap.toml"
    cfg.write_text('[paths]\ncache_dir = "c"\ndata_dir = "/abs/data"\n[resample]\nstep_m = 2.5\n')
    return cfg


def test_settings_from_toml(tmp_path: Path) -> None:
    s = load_settings(_write_toml(tmp_path), env={})
    assert s.cache_dir == tmp_path / "c"
    assert s.data_dir == Path("/abs/data")
    assert s.step_m == 2.5


def test_env_overrides_toml(tmp_path: Path) -> None:
    env = {"F1LAP_STEP_M": "0.5", "F1LAP_DATA_DIR": "out", "F1LAP_CACHE_DIR": "/tmp/x"}
    s = load_settings(_write_toml(tmp_path), env=env)
    assert (s.step_m, s.data_dir, s.cache_dir) == (0.5, tmp_path / "out", Path("/tmp/x"))


def test_missing_toml_uses_defaults(tmp_path: Path) -> None:
    s = load_settings(tmp_path / "nope.toml", env={})
    assert (s.cache_dir, s.data_dir, s.step_m) == (tmp_path / "cache", tmp_path / "data", 1.0)


@pytest.mark.parametrize("bad", ["0", "-1", "abc", "nan", "inf"])
def test_invalid_step_rejected(tmp_path: Path, bad: str) -> None:
    with pytest.raises(ConfigError):
        load_settings(tmp_path / "nope.toml", env={"F1LAP_STEP_M": bad})


def test_repo_config_loads() -> None:
    s = load_settings(Path(__file__).parents[1] / "f1lap.toml", env={})
    assert s.step_m == 1.0
