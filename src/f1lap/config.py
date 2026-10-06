"""Project settings from `f1lap.toml`, with `F1LAP_*` environment overrides."""

from __future__ import annotations

import math
import os
import tomllib
from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path

DEFAULT_CONFIG = Path("f1lap.toml")


class ConfigError(ValueError):
    pass


@dataclass(frozen=True, slots=True)
class Settings:
    cache_dir: Path
    data_dir: Path
    step_m: float


def load_settings(
    path: Path | None = None, env: Mapping[str, str] | None = None
) -> Settings:
    """Load settings; relative paths resolve against the toml's directory.

    A missing toml is allowed (defaults apply, relative to the current directory).
    """
    path = path or DEFAULT_CONFIG
    env = os.environ if env is None else env

    raw: dict[str, dict[str, object]] = {}
    if path.is_file():
        with path.open("rb") as fh:
            raw = tomllib.load(fh)
    base = path.resolve().parent

    paths = raw.get("paths", {})
    resample = raw.get("resample", {})

    def _path(key: str, env_key: str, default: str) -> Path:
        value = Path(env.get(env_key) or str(paths.get(key, default))).expanduser()
        return value if value.is_absolute() else base / value

    step_raw = env.get("F1LAP_STEP_M") or resample.get("step_m", 1.0)
    try:
        step_m = float(step_raw)  # type: ignore[arg-type]
    except (TypeError, ValueError) as exc:
        raise ConfigError(f"step_m must be a number, got {step_raw!r}") from exc
    if not (math.isfinite(step_m) and step_m > 0):
        raise ConfigError(f"step_m must be finite and > 0, got {step_m}")

    return Settings(
        cache_dir=_path("cache_dir", "F1LAP_CACHE_DIR", "cache"),
        data_dir=_path("data_dir", "F1LAP_DATA_DIR", "data"),
        step_m=step_m,
    )
