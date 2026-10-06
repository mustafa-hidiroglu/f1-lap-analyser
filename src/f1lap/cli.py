"""`f1lap` command line: fetch / import laps onto the distance grid, inspect stored laps."""

from __future__ import annotations

import argparse
import sys
from collections.abc import Sequence
from pathlib import Path

import polars as pl
import pyarrow as pa

from f1lap import schema
from f1lap.config import ConfigError, Settings, load_settings
from f1lap.resample import resample_to_distance
from f1lap.store import lap_filename, read_lap, write_lap
from f1lap.trace import LapTrace, TraceError


def _lap_selector(value: str) -> int | str:
    return "fastest" if value == "fastest" else int(value)


def _event(value: str) -> str | int:
    return int(value) if value.isdigit() else value


def _parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(prog="f1lap", description=__doc__)
    p.add_argument("--config", type=Path, default=None, help="path to f1lap.toml")
    p.add_argument("--step", type=float, default=None, help="grid spacing in metres")
    p.add_argument("--length", type=float, default=None, help="normalise lap to this length (m)")
    p.add_argument("-o", "--out", type=Path, default=None, help="output .parquet path")
    sub = p.add_subparsers(dest="command", required=True)

    f = sub.add_parser("fetch", help="download a lap via FastF1 and store it resampled")
    f.add_argument("year", type=int)
    f.add_argument("event", type=_event, help="event name or round number, e.g. Monza or 16")
    f.add_argument("session", help="FP1, FP2, FP3, Q, SQ, S, R")
    f.add_argument("driver", help="driver code or number, e.g. LEC or 16")
    f.add_argument("--lap", type=_lap_selector, default="fastest", help="lap number or 'fastest'")

    i = sub.add_parser("import", help="resample a CSV/Parquet telemetry export")
    i.add_argument("path", type=Path)
    i.add_argument("--driver", default="")
    i.add_argument("--lap-number", type=int, default=None)

    n = sub.add_parser("info", help="summarise a stored lap file")
    n.add_argument("path", type=Path)
    return p


def _store(trace: LapTrace, args: argparse.Namespace, settings: Settings) -> Path:
    step = settings.step_m if args.step is None else args.step
    lap = resample_to_distance(trace, step, args.length)
    out = args.out or settings.data_dir / lap_filename(lap)
    write_lap(lap, out)
    print(f"wrote {out} ({len(lap)} samples @ {lap.step_m} m, lap {lap.meta.raw_length_m:.1f} m)")
    return out


def _info(path: Path) -> None:
    lap = read_lap(path)
    m = lap.meta
    lap_time = f"{m.lap_time_s:.3f} s" if m.lap_time_s is not None else "n/a"
    session = " ".join(str(p) for p in (m.year, m.event, m.session) if p) or "n/a"
    print(f"source   {m.source}  {session}")
    print(f"driver   {m.driver or 'n/a'}  lap {m.lap_number or 'n/a'}  time {lap_time}")
    length = f"{m.raw_length_m:.1f} m" if m.raw_length_m is not None else "n/a"
    norm = f" (normalised to {m.normalised_to_m:.1f} m)" if m.normalised_to_m else ""
    print(f"length   {length}{norm}\ngrid     {len(lap)} x {lap.step_m} m")
    speed = lap["speed"]
    print(f"speed    min {speed.min():.1f}  max {speed.max():.1f} km/h")
    print("channels " + ", ".join(c for c in lap.channels if c != schema.DISTANCE))


def main(argv: Sequence[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    try:
        settings = load_settings(args.config)
        if args.command == "fetch":
            from f1lap.ingest.fastf1_source import fetch_lap

            trace = fetch_lap(
                args.year, args.event, args.session, args.driver, args.lap,
                cache_dir=settings.cache_dir,
            )
            _store(trace, args, settings)
        elif args.command == "import":
            from f1lap.ingest.file_source import read_trace

            _store(read_trace(args.path, args.driver, args.lap_number), args, settings)
        else:
            _info(args.path)
    except (
        ConfigError, TraceError, LookupError, ValueError, OSError,
        pl.exceptions.PolarsError, pa.ArrowException,
    ) as exc:
        print(f"f1lap: error: {exc}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
