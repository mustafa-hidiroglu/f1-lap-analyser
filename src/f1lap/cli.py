"""`f1lap` command line: fetch / import laps onto the distance grid, inspect and compare them."""

from __future__ import annotations

import argparse
import json
import sys
from collections.abc import Sequence
from pathlib import Path

import polars as pl
import pyarrow as pa

from f1lap import schema
from f1lap.circuit import Circuit, circuit_filename, corner_segments, detect_corners
from f1lap.config import ConfigError, Settings, load_settings
from f1lap.delta import compare, corner_table, micro_sectors, summary
from f1lap.phases import CornerComparison, compare_corners
from f1lap.rating import LapEntry, LapRating
from f1lap.resample import resample_to_distance
from f1lap.store import lap_filename, read_lap, write_lap
from f1lap.trace import LapMeta, LapTrace, ResampledLap, TraceError


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

    c = sub.add_parser("corners", help="show the circuit's corners located on a stored lap")
    c.add_argument("path", type=Path)
    _circuit_args(c)
    c.add_argument("--json", type=Path, default=None, help="write the circuit as JSON")

    d = sub.add_parser("delta", help="delta-time of a lap vs a reference lap, per corner")
    d.add_argument("reference", type=Path, help="reference lap .parquet")
    d.add_argument("other", type=Path, help="compared lap .parquet")
    d.add_argument("--sectors", type=int, default=None,
                   help="use N equal micro-sectors instead of corners")
    _circuit_args(d)
    d.add_argument("--json", type=Path, default=None, help="write the report as JSON")

    m = sub.add_parser("metrics", help="driver-input metrics of one or more stored laps")
    m.add_argument("paths", type=Path, nargs="+", help="lap .parquet files")
    _circuit_args(m)
    m.add_argument("--json", type=Path, default=None, help="write the metrics as JSON")

    r = sub.add_parser("rate", help="rate a lap vs the driver's theoretical best and the field")
    r.add_argument("year", type=int)
    r.add_argument("event", type=_event)
    r.add_argument("session")
    r.add_argument("driver")
    r.add_argument("--lap", type=_lap_selector, default="fastest", help="lap number or 'fastest'")
    r.add_argument("--json", type=Path, default=None, help="write the rating as JSON")

    b = sub.add_parser("simbase", help="the perfect-lap base: build or list simulated laps")
    bsub = b.add_subparsers(dest="simbase_command", required=True)
    bb = bsub.add_parser("build", help="simulate every competitive session of whole seasons")
    bb.add_argument("--years", type=_years, default=range(2018, 2027),
                    help="season or range, e.g. 2024 or 2018-2026")
    bb.add_argument("--session", action="append", default=None,
                    help="only these session names (repeatable), e.g. Qualifying")
    bb.add_argument("--base", type=Path, default=None, help="output base (default: shipped)")
    bb.add_argument("--build-cache", type=Path, default=None,
                    help="FastF1 cache for the build (default: <cache_dir>/simbase-build)")
    bb.add_argument("--retry-failed", action="store_true", help="retry recorded failures")
    bl = bsub.add_parser("list", help="list the base's entries and failures")
    bl.add_argument("--base", type=Path, default=None)
    return p


def _years(value: str) -> range:
    a, _, b = value.partition("-")
    return range(int(a), int(b or a) + 1)


def _circuit_args(p: argparse.ArgumentParser) -> None:
    g = p.add_mutually_exclusive_group()
    g.add_argument("--circuit", type=Path, default=None, help="circuit JSON to use")
    g.add_argument("--detect", action="store_true",
                   help="detect corners from telemetry, ignoring any saved circuit")


def _circuit_for(lap: ResampledLap, args: argparse.Namespace, settings: Settings) -> Circuit:
    """Explicit --circuit, else the circuit saved by `fetch`, else detected from `lap`."""
    if args.circuit:
        return Circuit.load(args.circuit)
    saved = settings.data_dir / "circuits" / circuit_filename(lap.meta.year, lap.meta.event)
    if not args.detect and lap.meta.event and saved.is_file():
        return Circuit.load(saved)
    return detect_corners(lap)


def _store(trace: LapTrace, args: argparse.Namespace, settings: Settings) -> Path:
    step = settings.step_m if args.step is None else args.step
    lap = resample_to_distance(trace, step, args.length)
    out = args.out or settings.data_dir / lap_filename(lap)
    write_lap(lap, out)
    print(f"wrote {out} ({len(lap)} samples @ {lap.step_m} m, lap {lap.meta.raw_length_m:.1f} m)")
    return out


def _fetch(args: argparse.Namespace, settings: Settings) -> None:
    from f1lap.ingest.fastf1_source import circuit_from_session, lap_from_session, load_session

    ses = load_session(args.year, args.event, args.session, cache_dir=settings.cache_dir)
    trace = lap_from_session(ses, args.driver, args.lap)
    _store(trace, args, settings)
    path = settings.data_dir / "circuits" / circuit_filename(trace.meta.year, trace.meta.event)
    if not path.is_file():
        try:
            print(f"wrote {circuit_from_session(ses).save(path)}")
        except (LookupError, ValueError) as exc:
            print(f"f1lap: note: no circuit saved ({exc}); corners will be detected",
                  file=sys.stderr)


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


def _who(meta: LapMeta) -> str:
    lap = f" L{meta.lap_number}" if meta.lap_number else ""
    time = f" {meta.lap_time_s:.3f}s" if meta.lap_time_s is not None else ""
    return f"{meta.driver or '?'}{lap}{time}"


def _corners(args: argparse.Namespace, settings: Settings) -> None:
    lap = read_lap(args.path)
    circuit = _circuit_for(lap, args, settings)
    pos = circuit.positions_on(lap)
    print(f"{circuit.name}: {len(circuit.corners)} corners ({circuit.source}), "
          f"reference length {circuit.length_m:.1f} m")
    print(f"{'corner':>6} {'at m':>7} {'speed':>6} {'gear':>4}")
    idx = (pos / lap.step_m).round().astype(int).clip(0, len(lap) - 1)
    for corner, d, i in zip(circuit.corners, pos, idx, strict=True):
        gear = int(lap["gear"][i]) if "gear" in lap.channels else 0
        print(f"{'T' + corner.label:>6} {d:>7.0f} {lap['speed'][i]:>6.0f} {gear or '-':>4}")
    print("segments " + "  ".join(
        f"{s.name}[{s.start_m:.0f}-{s.end_m:.0f}]" for s in corner_segments(circuit, lap)
    ))
    if args.json:
        print(f"wrote {circuit.save(args.json)}")


def _print_phases(corners: list[CornerComparison]) -> None:
    print("\nphases (s, other - reference)       |  other vs reference")
    print(f"{'corner':>8} {'braking':>8} {'mid':>7} {'exit':>7} | {'brake pt':>9} {'min v':>6} "
          f"{'pickup':>7} {'full thr':>8} {'brakes':>6}")
    for c in corners:
        r, o = c.reference, c.other
        if r.flat:
            print(f"{c.segment.name:>8} {'flat':>8}")
            continue
        _, braking, mid, exit_, _ = c.phase_delta_s
        brake = ("-" if r.brake_on_m is None or o.brake_on_m is None
                 else f"{o.brake_on_m - r.brake_on_m:+.0f} m")
        print(f"{c.segment.name:>8} {braking:>+8.3f} {mid:>+7.3f} {exit_:>+7.3f} | {brake:>9} "
              f"{o.apex_speed - r.apex_speed:>+6.1f} {o.pickup_m - r.pickup_m:>+5.0f} m "
              f"{o.full_throttle_m - r.full_throttle_m:>+6.0f} m "
              f"{r.brake_applications:>3}/{o.brake_applications}")
    print("(brake pt / pickup / full thr: + = later; min v: + = faster; brakes: ref/other count)")


def _metrics(args: argparse.Namespace, settings: Settings) -> None:
    from f1lap.metrics import lap_metrics

    laps = [read_lap(p) for p in args.paths]
    circuit = _circuit_for(laps[0], args, settings)
    results = [lap_metrics(lap, corner_segments(circuit, lap)) for lap in laps]
    names = [LapEntry.of(lap).label for lap in laps]
    print(f"{'':16}" + "".join(f"{n:>11}" for n in names))
    for label, attr in (("full throttle", "full_throttle_s"), ("braking", "braking_s"),
                        ("coasting", "coasting_s")):
        print(f"{label:16}" + "".join(f"{m.pct(getattr(m, attr)):>9.1f} %" for m in results))
    print(f"{'thr smoothness':16}" + "".join(
        f"{m.throttle_smoothness:>11.3f}" if m.throttle_smoothness is not None else f"{'-':>11}"
        for m in results))
    print(f"\n{'corner':>8} {'lap':>9} {'smooth':>7} {'ramp s':>7} {'lifts':>5} "
          f"{'decel g':>7} {'rise s':>6}")

    def f(x: float | None, spec: str) -> str:
        return "-" if x is None else format(x, spec)

    for k in range(len(results[0].corners)):
        for j, m in enumerate(results):
            cm = m.corners[k]
            name = cm.name if j == 0 else ""
            if cm.flat:
                print(f"{name:>8} {names[j]:>9} {'flat':>7}")
                continue
            print(f"{name:>8} {names[j]:>9} {f(cm.throttle_smoothness, '.2f'):>7} "
                  f"{f(cm.throttle_ramp_s, '.2f'):>7} {cm.throttle_lifts:>5} "
                  f"{f(cm.peak_decel_g, '.2f'):>7} {f(cm.decel_rise_s, '.2f'):>6}")
    print(f"(brake data: {results[0].brake_source}; decel rise = 10-90 % of peak, "
          "comparable between laps, not absolute)")
    if args.json:
        args.json.parent.mkdir(parents=True, exist_ok=True)
        args.json.write_text(json.dumps([m.to_dict() for m in results], indent=2))
        print(f"wrote {args.json}")


def _rate(args: argparse.Namespace, settings: Settings) -> None:
    from f1lap.rating import rate_fastf1_lap

    step = settings.step_m if args.step is None else args.step
    rating = rate_fastf1_lap(
        args.year, args.event, args.session, args.driver, args.lap,
        cache_dir=settings.cache_dir, step_m=step,
    )
    print_rating(rating)
    report = None
    try:
        from f1lap import explain

        report = explain.explain_fastf1_lap(
            args.year, args.event, args.session, args.driver, args.lap,
            cache_dir=settings.cache_dir, step_m=step,
        )
    except (ValueError, LookupError) as exc:  # SimError: no perfect lap for this session
        print(f"\nno perfect lap: {exc}")
    if report is not None:
        print(f"\nperfect lap {report.sim_lap_time_s:.3f} s  (gap {report.gap_s:.3f} s; best laps "
              f"typically {report.typical_gap_s:.3f} s)")
        for line in report.summary:
            print(f"  - {line}")
    if args.json:
        args.json.parent.mkdir(parents=True, exist_ok=True)
        data = rating.to_dict() | ({"perfect": report.to_dict()} if report else {})
        args.json.write_text(json.dumps(data, indent=2))
        print(f"wrote {args.json}")


def _simbase(args: argparse.Namespace, settings: Settings) -> None:
    from f1lap import simbase

    base = args.base or simbase.PACKAGE_BASE
    if args.simbase_command == "list":
        files = sorted(base.glob("*/*.parquet"))
        for f in files:
            print(f.relative_to(base))
        fails = simbase.failures(base)
        print(f"{len(files)} perfect laps, {len(fails)} sessions without one")
        for key, reason in fails.items():
            print(f"  ✕ {key}: {reason}")
        return

    import asyncio
    import logging

    from f1lap.simbase_build import build

    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(message)s", stream=sys.stdout)
    names = {n.lower() for n in args.session} if args.session else None
    tally = asyncio.run(build(
        args.years, base, args.build_cache or settings.cache_dir / "simbase-build",
        retry_failed=args.retry_failed,
        only=(lambda p: p.session.lower() in names) if names else None,
    ))
    print(tally)


def print_rating(rating: LapRating) -> None:
    r = rating
    print(f"{r.lap.label}  {r.lap_time_s:.3f} s   vs {r.laps} laps from {r.drivers} drivers")
    print(f"theoretical best {r.theoretical_best_s:.3f} s  "
          f"({r.lap_time_s - r.theoretical_best_s:.3f} s left on the table)")
    print(f"session ultimate {r.ultimate_s:.3f} s  ({r.lap_time_s - r.ultimate_s:.3f} s off)"
          f"   score {r.score:.0f}/100")
    print(f"{'corner':>8} {'time':>7} {'own best':>12} {'lost':>7} {'session best':>20} "
          f"{'lost':>7} {'rank':>6}")
    for i, name in enumerate(r.names):
        own = f"{r.own_best[i]:.3f} L{r.own_best_lap[i]}"
        best = f"{r.field_best[i]:.3f} {r.field_best_by[i]}"
        print(f"{name:>8} {r.lap_times[i]:>7.3f} {own:>12} {r.lap_times[i] - r.own_best[i]:>+7.3f} "
              f"{best:>20} {r.lap_times[i] - r.field_best[i]:>+7.3f} "
              f"{r.rank[i]:>3}/{r.drivers}")


def _delta(args: argparse.Namespace, settings: Settings) -> None:
    cmp = compare(read_lap(args.reference), read_lap(args.other))
    corners: list[CornerComparison] = []
    if args.sectors is not None:
        sectors = micro_sectors(cmp, args.sectors)
    else:
        circuit = _circuit_for(cmp.reference, args, settings)
        segments = corner_segments(circuit, cmp.reference)
        sectors = corner_table(cmp, segments)
        corners = compare_corners(cmp, segments)
    report = summary(cmp, sectors)
    if corners:
        report["corners"] = [c.to_dict() for c in corners]

    print(f"reference {_who(cmp.reference.meta)}   vs   {_who(cmp.other.meta)}")
    official = report["lap_time_delta_s"]
    official_s = f"  (official {official:+.3f} s)" if official is not None else ""
    print(f"delta at line {cmp.final_delta_s:+.3f} s{official_s}   (+ = slower than reference)")
    print(f"{'sector':>8} {'from-to m':>13} {'ref s':>7} {'oth s':>7} {'delta':>7} "
          f"{'vmin ref':>8} {'vmin oth':>8}")
    for row in report["sectors"]:
        print(f"{row['name']:>8} {row['start_m']:>6.0f}-{row['end_m']:<6.0f} "
              f"{row['ref_time_s']:>7.3f} "
              f"{row['other_time_s']:>7.3f} {row['delta_s']:>+7.3f} "
              f"{row['ref_min_speed']:>8.1f} {row['other_min_speed']:>8.1f}")
    if corners:
        _print_phases(corners)
    if args.json:
        args.json.parent.mkdir(parents=True, exist_ok=True)
        args.json.write_text(json.dumps(report, indent=2))
        print(f"wrote {args.json}")


def main(argv: Sequence[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    try:
        settings = load_settings(args.config)
        if args.command == "fetch":
            _fetch(args, settings)
        elif args.command == "import":
            from f1lap.ingest.file_source import read_trace

            _store(read_trace(args.path, args.driver, args.lap_number), args, settings)
        elif args.command == "delta":
            _delta(args, settings)
        elif args.command == "corners":
            _corners(args, settings)
        elif args.command == "metrics":
            _metrics(args, settings)
        elif args.command == "rate":
            _rate(args, settings)
        elif args.command == "simbase":
            _simbase(args, settings)
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
