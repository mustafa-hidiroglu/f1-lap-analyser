"""Why a lap was slower than the perfect (simulated) lap, in plain sentences.

The perfect lap combines the best of every calibration lap, so even the session's fastest laps
lose time to it in every corner. Rules therefore judge a lap against the **calibration laps'
typical loss** (median of the session's fastest laps vs the sim), not against the sim itself:
"braked 20 m earlier than the best laps", not "than an envelope nobody drove".

Time attribution: every corner's loss to the sim is split into phases cut at the sim's
boundaries (`phases.compare_corners`: approach | braking | mid | exit | straight, summing to
the corner delta). A finding's cost is its phase's *excess* loss over the calibration median,
and each phase feeds at most one finding, so costs never double count. Context (traffic,
flags, tyres) explains a corner's loss but carries no cost of its own.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass, field
from pathlib import Path
from typing import TYPE_CHECKING, Any, Final

import numpy as np

from f1lap.circuit import Segment, corner_segments
from f1lap.context import LapContext, Span
from f1lap.delta import compare
from f1lap.ingest.fastf1_source import LapSelector
from f1lap.phases import PHASES, CornerComparison, compare_corners, decel_zones
from f1lap.sim import SimLap
from f1lap.trace import ResampledLap

if TYPE_CHECKING:
    from f1lap.session import LoadedSession

BRAKE_EARLY_M: Final = 15.0  # lap distances are only aligned to ~10-30 m locally
BRAKE_LATE_M: Final = 15.0
#: Brake-point offsets beyond this compare different braking events (multi-corner complexes).
BRAKE_MAX_M: Final = 80.0
#: A corner losing this much more than the best laps always gets a sentence, even without a rule.
UNEXPLAINED_S: Final = 0.10
APEX_KMH: Final = 3.0
COAST_M: Final = 30.0  # lift-to-brake distance beyond the best laps' = lift-and-coast
THROTTLE_LATE_M: Final = 15.0
#: The sim's braking zone may start this far before its corner segment.
SIM_BRAKE_LEAD_M: Final = 50.0
STRAIGHT_KMH: Final = 5.0
MIN_COST_S: Final = 0.02  # findings below this are noise
SUMMARY_FINDINGS: Final = 4
_PHASE = {p: i for i, p in enumerate(PHASES)}
_PHASE_TEXT = {
    "approach": "on the approach",
    "braking": "under braking",
    "mid": "through the slow mid-corner",
    "exit": "on the exit",
    "straight": "on the following straight",
}


@dataclass(frozen=True, slots=True)
class Finding:
    kind: str  # braked_early | braked_late | apex_speed | late_throttle | straight_speed |
    #            traffic | flag | position | lap
    text: str
    corner: str | None = None
    cost_s: float | None = None  # time attributed (vs the calibration laps); None = context

    def to_dict(self) -> dict[str, Any]:
        return {"kind": self.kind, "text": self.text, "corner": self.corner, "cost_s": self.cost_s}


@dataclass(frozen=True, slots=True)
class CornerReason:
    name: str
    start_m: float
    end_m: float
    lost_s: float  # vs the perfect lap
    typical_lost_s: float  # sum of the calibration laps' per-phase median losses
    phase_lost_s: dict[str, float]
    findings: tuple[Finding, ...]

    @property
    def excess_s(self) -> float:
        return self.lost_s - self.typical_lost_s

    def to_dict(self) -> dict[str, Any]:
        return {
            "name": self.name, "start_m": self.start_m, "end_m": self.end_m,
            "lost_s": self.lost_s, "typical_lost_s": self.typical_lost_s,
            "excess_s": self.excess_s, "phase_lost_s": self.phase_lost_s,
            "findings": [f.to_dict() for f in self.findings],
        }


@dataclass(frozen=True, slots=True)
class PerfectReport:
    driver: str
    lap_number: int | None
    lap_time_s: float
    sim_lap_time_s: float
    typical_gap_s: float  # sum of the corners' typical losses (the best laps' usual gap)
    corners: tuple[CornerReason, ...]
    lap_findings: tuple[Finding, ...]
    summary: tuple[str, ...]
    context: LapContext | None = field(default=None)

    @property
    def gap_s(self) -> float:
        return self.lap_time_s - self.sim_lap_time_s

    def to_dict(self) -> dict[str, Any]:
        return {
            "driver": self.driver, "lap_number": self.lap_number,
            "lap_time_s": self.lap_time_s, "sim_lap_time_s": self.sim_lap_time_s,
            "gap_s": self.gap_s, "typical_gap_s": self.typical_gap_s,
            "corners": [c.to_dict() for c in self.corners],
            "lap_findings": [f.to_dict() for f in self.lap_findings],
            "summary": list(self.summary),
        }


# -- measurements -----------------------------------------------------------------------------

@dataclass(frozen=True, slots=True)
class _Marks:
    """One lap through one corner, relative to the sim (positive = worse than the sim)."""

    brake_early_m: float | None  # sim braking point (deceleration) - lap brake pedal
    coast_m: float | None  # lap: lift (end of full attack) to brake pedal
    apex_kmh: float  # speed deficit at the sim's apex
    exit_kmh: float  # ... where the sim is back on full power
    end_kmh: float  # ... at the end of the segment
    approach_kmh: float  # mean speed deficit on the way in (segment start → sim entry)
    throttle_late_m: float  # lap full throttle - sim apex
    phase_s: np.ndarray


def _sim_brake_on(zones: Sequence[tuple[float, float]], c: CornerComparison,
                  prev_apex_m: float | None = None) -> float | None:
    """The perfect lap's braking point: start of its first `decel_zones` zone from
    SIM_BRAKE_LEAD_M before the segment start (a zone may begin just before the segment) to
    its apex, but after the previous corner's apex so that corner's zone is never taken. Its
    brake channel cannot be used: that only marks where the braking model binds, which on most
    sessions is nowhere (it may brake as late as any lap showed, so the demonstrated speeds
    bind instead)."""
    lo = c.segment.start_m - SIM_BRAKE_LEAD_M
    after = -np.inf if prev_apex_m is None else prev_apex_m
    return next((a for a, _ in zones if lo <= a <= c.reference.apex_m and a > after), None)


def _marks(c: CornerComparison, sim: ResampledLap, lap: ResampledLap,
           s_on: float | None) -> _Marks:
    """The sim has no pedals (it brakes wherever its speed falls hard and is "flat" wherever its
    speed is not falling), so the lap's brake pedal and full-throttle point are measured from
    fixed per-corner anchors on the sim — its deceleration-based braking point and its apex —
    rather than from the sim's own inputs. Rules subtract the best laps' median of each mark, so
    the anchors cancel and findings compare the lap's pedal with the best laps' pedals; the sim
    braking point `s_on` (`_sim_brake_on`) also gates the braking rules to corners where the
    perfect lap really brakes."""
    s, o = c.reference, c.other
    early = s_on - o.brake_on_m if s_on is not None and o.brake_on_m is not None else None
    step, n = sim.step_m, len(sim)
    vs, vl = sim["speed"], lap["speed"]

    def at(m: float) -> int:
        return min(n - 1, max(0, round(m / step)))

    def deficit(m: float) -> float:
        return float(vs[at(m)] - vl[at(m)])

    lo, hi = at(c.segment.start_m), max(at(c.segment.start_m) + 1, at(s.entry_m) + 1)
    return _Marks(
        brake_early_m=early,
        coast_m=o.brake_on_m - o.entry_m if o.brake_on_m is not None else None,
        apex_kmh=deficit(s.apex_m),
        exit_kmh=deficit(max(s.full_throttle_m, s.apex_m + 50.0)),
        end_kmh=deficit(c.segment.end_m),
        approach_kmh=float(np.mean(vs[lo:hi] - vl[lo:hi])),
        throttle_late_m=o.full_throttle_m - s.apex_m,
        phase_s=c.phase_delta_s,
    )


def _median(values: Sequence[float | None]) -> float:
    vals = [v for v in values if v is not None and np.isfinite(v)]
    return float(np.median(vals)) if vals else 0.0


def _base(values: Sequence[float | None]) -> float | None:
    """Median of the best laps' values, or None when none of them has one (rule skipped)."""
    vals = [v for v in values if v is not None and np.isfinite(v)]
    return float(np.median(vals)) if vals else None


def _corners(sim: SimLap, lap: ResampledLap, segments: Sequence[Segment]) -> tuple[
        list[CornerComparison], ResampledLap]:
    cmp = compare(sim.lap, lap)
    return compare_corners(cmp, segments), cmp.other


# -- rules ------------------------------------------------------------------------------------

def _corner_findings(name: str, m: _Marks, base: list[_Marks], cost: np.ndarray,
                     ) -> list[Finding]:
    """`cost` = excess loss per phase over the calibration median (seconds).

    Cause before effect: a slow apex also costs the exit and the following straight (the car
    is slower from there on), so those phases go to the apex finding; a deficit that only grows
    after the apex is a slow exit; one that only appears on the run to the corner is straight-line
    speed. Each phase is claimed by at most one finding."""
    out: list[Finding] = []
    used: set[int] = set()
    ap, b, mid, ex, st = (_PHASE[p] for p in ("approach", "braking", "mid", "exit", "straight"))

    def med(attr: str) -> float:
        return _median([getattr(x, attr) for x in base])

    def claim(*phases: int) -> float:
        free = [p for p in phases if p not in used]
        used.update(free)
        return float(sum(max(cost[p], 0.0) for p in free))

    apex = m.apex_kmh - med("apex_kmh")
    exit_ = m.exit_kmh - med("exit_kmh")
    end = m.end_kmh - med("end_kmh")

    # Braking zone: lift-and-coast, early or late braking.
    coast_base = _base([x.coast_m for x in base])
    early_base = _base([x.brake_early_m for x in base])
    coast = (m.coast_m - coast_base
             if m.coast_m is not None and coast_base is not None else 0.0)
    early = (m.brake_early_m - early_base
             if m.brake_early_m is not None and early_base is not None else None)
    if coast >= COAST_M and cost[b] >= MIN_COST_S:
        c = claim(b)
        out.append(Finding("lift_and_coast", f"{name}: lifted {coast:.0f} m earlier than the best "
                           f"laps before braking — lift-and-coast to save fuel or tyres "
                           f"({c:.2f} s).", name, c))
    elif early is not None and abs(early) <= BRAKE_MAX_M:
        if early >= BRAKE_EARLY_M and cost[b] >= MIN_COST_S:
            c = claim(b)
            out.append(Finding("braked_early", f"{name}: braked {early:.0f} m earlier than the "
                               f"session's best laps ({c:.2f} s on the way in).", name, c))
        elif (-early >= BRAKE_LATE_M and apex >= APEX_KMH
              and cost[b] + cost[mid] + cost[ex] >= MIN_COST_S):
            c = claim(b, mid, ex)
            out.append(Finding("braked_late", f"{name}: braked {-early:.0f} m later than the "
                               f"best laps and overshot — apex speed {apex:.0f} km/h down "
                               f"({c:.2f} s).", name, c))

    # Apex: a slower minimum speed carries through the exit (and the straight if it persists).
    if mid not in used and apex >= APEX_KMH:
        phases = (mid, ex, st) if end >= APEX_KMH / 2 else (mid, ex)
        if sum(cost[p] for p in phases) >= MIN_COST_S:
            c = claim(*phases)
            out.append(Finding("apex_speed", f"{name}: carried {apex:.0f} km/h less through the "
                               f"apex than the best laps; the deficit carries onto the exit "
                               f"({c:.2f} s).", name, c))
    # Exit: the deficit grows after the apex — late or hesitant on the throttle.
    late_base = _base([x.throttle_late_m for x in base])
    if ex not in used and exit_ - max(apex, 0.0) >= APEX_KMH and cost[ex] + cost[st] >= MIN_COST_S:
        c = claim(ex, st)
        late = None if late_base is None else m.throttle_late_m - late_base
        detail = (f", full throttle {late:.0f} m later"
                  if late is not None and late >= THROTTLE_LATE_M else "")
        out.append(Finding("slow_exit", f"{name}: slow exit — {exit_:.0f} km/h down where the "
                           f"best laps were back on full power{detail} ({c:.2f} s).", name, c))
    # Way in: slower on average before the corner (straight, or a complex's first corners).
    approach = m.approach_kmh - med("approach_kmh")
    if ap not in used and approach >= STRAIGHT_KMH and cost[ap] >= MIN_COST_S:
        c = claim(ap)
        out.append(Finding("straight_speed", f"{name}: {approach:.0f} km/h slower on average "
                           f"than the best laps on the way in ({c:.2f} s) — less tow or DRS, "
                           "energy deployment, or a compromised previous exit.", name, c))

    rest = [i for i in range(len(PHASES)) if i not in used]
    unexplained = float(sum(cost[i] for i in rest))
    if unexplained >= UNEXPLAINED_S:
        worst = max(rest, key=lambda i: cost[i])
        out.append(Finding("phase_loss", f"{name}: {unexplained:.2f} s slower than the best laps, "
                           f"mostly {_PHASE_TEXT[PHASES[worst]]} ({cost[worst]:.2f} s) — no single "
                           "input explains it: a different line, less grip or a held-back lap.",
                           name, unexplained))
    return out


def _order(reasons: list[tuple[str, float, float]]) -> Any:
    index = {name: i for i, (name, _, _) in enumerate(reasons)}
    return lambda name: index.get(name, -1)


def _join(items: list[str]) -> str:
    return items[0] if len(items) == 1 else ", ".join(items[:-1]) + " and " + items[-1]


def _context_findings(ctx: LapContext, reasons: list[tuple[str, float, float]],
                      length: float) -> tuple[dict[str, list[Finding]], list[Finding]]:
    """Traffic/flags per corner (by overlap), and lap-level context."""
    per: dict[str, list[Finding]] = {name: [] for name, _, _ in reasons}

    def where(span: Span) -> list[str]:
        return [n for n, a, b in reasons if span.overlaps(a / length, b / length)]

    # One sentence per corner, naming every car the driver was close behind there.
    behind: dict[str, list[str]] = {}
    last: dict[str, str] = {}
    for sp in ctx.traffic:
        names = where(sp)
        if names:
            gap = f"{sp.value:.1f} s" if sp.value is not None else "close"
            cars = behind.setdefault(names[0], [])
            if not any(c.startswith(f"{sp.what} ") for c in cars):
                cars.append(f"{sp.what} ({gap})")
            last[names[0]] = max(last.get(names[0], names[0]), names[-1], key=_order(reasons))
    for corner, cars in behind.items():
        span = corner if last[corner] == corner else f"from {corner} to {last[corner]}"
        where_ = f"through {span}" if last[corner] == corner else span
        per[corner].append(Finding(
            "traffic", f"Close behind {_join(cars)} {where_} — dirty air costs front grip in "
            "the corners.", corner))
    for sp in ctx.flags:
        names = where(sp)
        if names:
            per[names[0]].append(Finding(
                "flag", f"{sp.what.capitalize()} "
                + (f"from {names[0]} to {names[-1]}" if len(names) > 1 else f"at {names[0]}")
                + ": drivers must slow down.",
                names[0]))

    lap: list[Finding] = []
    if ctx.positions_gained > 0:
        lap.append(Finding("position", f"Gained {ctx.positions_gained} position"
                           f"{'s' if ctx.positions_gained > 1 else ''} on this lap — "
                           "overtaking lines and braking cost time."))
    elif ctx.positions_gained < 0:
        lap.append(Finding("position", f"Lost {-ctx.positions_gained} position"
                           f"{'s' if ctx.positions_gained < -1 else ''} on this lap "
                           "(fight or mistake)."))
    if ctx.car_behind and ctx.car_behind_gap_s is not None:
        lap.append(Finding("position", f"Under pressure: {ctx.car_behind} was "
                           f"{ctx.car_behind_gap_s:.1f} s behind at the line, so defensive "
                           "lines are likely."))
    if ctx.pit_in:
        lap.append(Finding("lap", "In-lap: the driver slowed for the pit entry."))
    if ctx.pit_out:
        lap.append(Finding("lap", "Out-lap: cold tyres after the pit stop."))
    if ctx.deleted:
        lap.append(Finding("lap", "Lap deleted (track limits)."))
    if ctx.compound and ctx.tyre_life is not None:
        old = ctx.tyre_life >= 15
        lap.append(Finding("lap", f"{ctx.compound.title()} tyres, {ctx.tyre_life} laps old"
                           + (" — worn tyres lose grip in every corner." if old else ".")))
    if (ctx.session_kind == "race" and ctx.lap_number and ctx.race_laps
            and ctx.lap_number <= ctx.race_laps // 3):
        lap.append(Finding("lap", f"Race lap {ctx.lap_number} of {ctx.race_laps}: still a "
                           "heavy fuel load."))
    return per, lap


# -- entry point ------------------------------------------------------------------------------

def explain(
    lap: ResampledLap, sim: SimLap, segments: Sequence[Segment],
    calibration: Sequence[ResampledLap], context: LapContext | None = None,
) -> PerfectReport:
    """Compare `lap` with the perfect lap `sim`, judged against the `calibration` laps."""
    if lap.meta.lap_time_s is None:
        raise ValueError("the lap has no lap time")
    corners, on_grid = _corners(sim, lap, segments)
    base_runs = [_corners(sim, c, segments) for c in calibration]
    simlap = sim.lap
    sim_zones = decel_zones(simlap)

    reasons: list[CornerReason] = []
    for i, c in enumerate(corners):
        s_on = _sim_brake_on(sim_zones, c, corners[i - 1].reference.apex_m if i else None)
        m = _marks(c, simlap, on_grid, s_on)
        base = [_marks(run[i], simlap, other, s_on) for run, other in base_runs]
        typical = (np.median(np.vstack([x.phase_s for x in base]), axis=0)
                   if base else np.zeros(len(PHASES)))
        cost = c.phase_delta_s - typical
        reasons.append(CornerReason(
            name=c.segment.name, start_m=c.segment.start_m, end_m=c.segment.end_m,
            lost_s=c.delta_s, typical_lost_s=float(typical.sum()),
            phase_lost_s=dict(zip(PHASES, map(float, c.phase_delta_s), strict=True)),
            findings=tuple(_corner_findings(c.segment.name, m, base, cost)),
        ))

    lap_findings: list[Finding] = []
    if context is not None:
        length = simlap.grid_end_m
        per, lap_findings = _context_findings(
            context, [(r.name, r.start_m, r.end_m) for r in reasons], length)
        reasons = [
            CornerReason(r.name, r.start_m, r.end_m, r.lost_s, r.typical_lost_s, r.phase_lost_s,
                         r.findings + tuple(per.get(r.name, ())))
            for r in reasons
        ]

    # From the same per-phase medians as the corner costs, so "left on the table" equals the
    # sum of the corners' excess losses.
    typical_gap = float(sum(r.typical_lost_s for r in reasons))
    report = PerfectReport(
        driver=lap.meta.driver, lap_number=lap.meta.lap_number, lap_time_s=lap.meta.lap_time_s,
        sim_lap_time_s=sim.lap_time_s, typical_gap_s=typical_gap, corners=tuple(reasons),
        lap_findings=tuple(lap_findings), summary=(), context=context,
    )
    return PerfectReport(
        report.driver, report.lap_number, report.lap_time_s, report.sim_lap_time_s,
        report.typical_gap_s, report.corners, report.lap_findings, _summary(report), context,
    )


def _summary(r: PerfectReport) -> tuple[str, ...]:
    who = f"{r.driver} L{r.lap_number}" if r.lap_number else r.driver
    left = r.gap_s - r.typical_gap_s
    verdict = (f"so this lap left {left:.3f} s on the table." if left > 0.005
               else "so this lap is as good as the session's best.")
    lines = [
        f"{who} was {r.gap_s:.3f} s slower than the perfect lap; the session's best laps were "
        f"typically {r.typical_gap_s:.3f} s off it, {verdict}"
    ]
    costed = sorted((f for c in r.corners for f in c.findings if f.cost_s is not None),
                    key=lambda f: -(f.cost_s or 0.0))
    lines += [f.text for f in costed[:SUMMARY_FINDINGS]]
    context = [f for c in r.corners for f in c.findings if f.cost_s is None]
    lines += [f.text for f in context[:2]]
    lines += [f.text for f in r.lap_findings if f.kind in {"position", "lap"}][:3]
    if len(lines) == 1:
        lines.append("No single corner stands out: the time is spread thinly around the lap.")
    return tuple(lines)


def explain_session_lap(
    session: LoadedSession, driver: str, lap: LapSelector = "fastest"
) -> PerfectReport:
    """Explain one lap of a loaded session against its perfect lap (raises `SimError` when the
    session has none)."""
    sim = session.sim
    rated = session.lap(driver, lap)
    segments = corner_segments(session.circuit, sim.lap)
    return explain(rated, sim, segments, session.calibration_laps(),
                   session.lap_context(driver, lap))


def explain_fastf1_lap(
    year: int, event: str | int, session: str, driver: str, lap: LapSelector = "fastest",
    *, cache_dir: Path, step_m: float = 1.0,
) -> PerfectReport:
    """Load a FastF1 session and explain one lap against its perfect lap (blocking)."""
    from f1lap.session import LoadedSession

    loaded = LoadedSession.load(year, event, session, cache_dir=cache_dir, step_m=step_m)
    return explain_session_lap(loaded, driver, lap)
