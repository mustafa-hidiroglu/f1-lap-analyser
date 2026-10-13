// Client-side lap analysis. Mirrors f1lap.delta (compare, corner_table), f1lap.resample.rescale
// and f1lap.phases.compare_corners so results match the desktop app within grid tolerance.
//
// Sign convention: deltas are `other - reference`; positive means the compared lap is slower.

import type { CornerPoints, LoadedSession, Segment } from "./types";

export const CHANNELS = ["time", "speed", "throttle", "brake", "gear", "rpm"] as const;
export type Channel = (typeof CHANNELS)[number];
const DISCRETE: ReadonlySet<Channel> = new Set(["gear"]);

export const PHASES = ["approach", "braking", "mid", "exit", "straight"] as const;
export type Phase = (typeof PHASES)[number];

/** One lap on a uniform distance grid `distance[i] = i * step_m`. */
export interface Lap {
  driver: string;
  step_m: number;
  /** Nominal length the grid represents (the session reference lap's length). */
  length_m: number;
  samples: number;
  channels: Record<Channel, Float64Array>;
}

/** numpy.round: round half to even. */
export function roundHalfEven(x: number): number {
  const r = Math.round(x);
  return Math.abs(x % 1) === 0.5 && r % 2 !== 0 ? r - 1 : r;
}

export function distanceGrid(samples: number, step: number): Float64Array {
  const g = new Float64Array(samples);
  for (let i = 0; i < samples; i++) g[i] = i * step;
  return g;
}

function nanColumn(n: number): Float64Array {
  return new Float64Array(n).fill(NaN);
}

/** A driver's lap from a session's binary columns (session grid, unaltered). */
export function sessionLap(session: LoadedSession, code: string): Lap {
  const { meta, columns } = session;
  if (!columns.has(`${code}.time`)) throw new Error(`no telemetry for ${code}`);
  const channels = {} as Record<Channel, Float64Array>;
  for (const ch of CHANNELS) channels[ch] = columns.get(`${code}.${ch}`) ?? nanColumn(meta.samples);
  return { driver: code, step_m: meta.step_m, length_m: meta.length_m, samples: meta.samples, channels };
}

/** The session's simulated perfect lap, or null if it has none. */
export function simLap(session: LoadedSession): Lap | null {
  return session.columns.has("sim.time") ? sessionLap(session, "sim") : null;
}

/** np.interp for continuous channels, NaNs dropped, linear extension past the last sample. */
function interpContinuous(grid: Float64Array, d: Float64Array, values: Float64Array): Float64Array {
  const xs: number[] = [];
  const ys: number[] = [];
  for (let i = 0; i < d.length; i++) {
    if (Number.isFinite(values[i])) {
      xs.push(d[i]);
      ys.push(values[i]);
    }
  }
  const out = new Float64Array(grid.length);
  if (xs.length < 2) return out.fill(NaN);
  const last = xs.length - 1;
  const slope = (ys[last] - ys[last - 1]) / (xs[last] - xs[last - 1]);
  let j = 0;
  for (let i = 0; i < grid.length; i++) {
    const g = grid[i];
    if (g <= xs[0]) out[i] = ys[0];
    else if (g > xs[last]) out[i] = ys[last] + slope * (g - xs[last]);
    else {
      while (j < last && xs[j + 1] < g) j++;
      const x0 = xs[j], x1 = xs[j + 1];
      out[i] = x1 === x0 ? ys[j + 1] : ys[j] + ((ys[j + 1] - ys[j]) * (g - x0)) / (x1 - x0);
    }
  }
  return out;
}

/** Zero-order hold: the last sample at or before each grid point. */
function holdDiscrete(grid: Float64Array, d: Float64Array, values: Float64Array): Float64Array {
  const out = new Float64Array(grid.length);
  let j = 0;
  for (let i = 0; i < grid.length; i++) {
    while (j + 1 < d.length && d[j + 1] <= grid[i]) j++;
    out[i] = values[j];
  }
  return out;
}

export interface Grid {
  step_m: number;
  length_m: number;
  samples: number;
}

function sameGrid(a: Grid, b: Grid): boolean {
  return a.step_m === b.step_m && a.samples === b.samples && a.length_m === b.length_m;
}

/** `lap` on `grid` (distance rescaled by grid.length / lap.length), like `delta.align`. */
export function align(grid: Grid, lap: Lap): Lap {
  if (sameGrid(grid, lap)) return lap;
  const k = grid.length_m / lap.length_m;
  const d = new Float64Array(lap.samples);
  for (let i = 0; i < lap.samples; i++) d[i] = i * lap.step_m * k;
  const g = distanceGrid(grid.samples, grid.step_m);
  const channels = {} as Record<Channel, Float64Array>;
  for (const ch of CHANNELS) {
    channels[ch] = DISCRETE.has(ch)
      ? holdDiscrete(g, d, lap.channels[ch])
      : interpContinuous(g, d, lap.channels[ch]);
  }
  return { ...lap, ...grid, channels };
}

export interface Comparison {
  reference: Lap;
  other: Lap;
  distance: Float64Array;
  delta: Float64Array;
}

export function compare(reference: Lap, other: Lap): Comparison {
  const oth = align(reference, other);
  const n = reference.samples;
  const delta = new Float64Array(n);
  for (let i = 0; i < n; i++) delta[i] = oth.channels.time[i] - reference.channels.time[i];
  return { reference, other: oth, distance: distanceGrid(n, reference.step_m), delta };
}

export interface ComparisonSummary {
  final_delta_s: number;
  max_gain_s: number;
  max_gain_at_m: number;
  max_loss_s: number;
  max_loss_at_m: number;
}

export function summarise(cmp: Comparison): ComparisonSummary {
  let lo = Infinity, hi = -Infinity, loAt = 0, hiAt = 0;
  cmp.delta.forEach((v, i) => {
    if (v < lo) { lo = v; loAt = i; }
    if (v > hi) { hi = v; hiAt = i; }
  });
  return {
    final_delta_s: cmp.delta[cmp.delta.length - 1],
    max_gain_s: lo,
    max_gain_at_m: cmp.distance[loAt],
    max_loss_s: hi,
    max_loss_at_m: cmp.distance[hiAt],
  };
}

function gridIndex(m: number, step: number, n: number): number {
  return Math.min(n - 1, Math.max(0, roundHalfEven(m / step)));
}

function minIgnoringNaN(a: Float64Array, from: number, to: number): number {
  let m = Infinity;
  for (let i = from; i < to; i++) if (a[i] < m) m = a[i];
  return m === Infinity ? NaN : m;
}

export interface SectorRow {
  name: string;
  start_m: number;
  end_m: number;
  ref_time_s: number;
  other_time_s: number;
  delta_s: number;
  ref_min_speed: number;
  other_min_speed: number;
}

/** Per-segment comparison, like `delta.corner_table`. */
export function cornerTable(cmp: Comparison, segments: Segment[]): SectorRow[] {
  if (!segments.length) throw new Error("no segments");
  const n = cmp.reference.samples, step = cmp.reference.step_m;
  const edges = [segments[0].start_m, ...segments.map((s) => s.end_m)];
  const b = edges.map((e) => gridIndex(e, step, n));
  for (let i = 1; i < b.length; i++) {
    if (b[i] <= b[i - 1]) throw new Error("segments must be at least one grid step long and in order");
  }
  const rt = cmp.reference.channels.time, ot = cmp.other.channels.time;
  const rs = cmp.reference.channels.speed, os = cmp.other.channels.speed;
  return segments.map((s, i) => {
    const a = b[i], z = b[i + 1];
    const until = i === segments.length - 1 ? n : z; // numpy reduceat: last slice runs to the end
    return {
      name: s.name,
      start_m: cmp.distance[a],
      end_m: cmp.distance[z],
      ref_time_s: rt[z] - rt[a],
      other_time_s: ot[z] - ot[a],
      delta_s: cmp.delta[z] - cmp.delta[a],
      ref_min_speed: minIgnoringNaN(rs, a, until),
      other_min_speed: minIgnoringNaN(os, a, until),
    };
  });
}

export interface CornerRow {
  name: string;
  start_m: number;
  end_m: number;
  delta_s: number;
  /** Per phase, cut at the reference lap's corner points; null without corner points. */
  phase_delta_s: Record<Phase, number> | null;
}

/** Phase-by-phase deltas per segment, like `phases.compare_corners`. */
export function compareCorners(
  cmp: Comparison,
  segments: Segment[],
  refCorners: CornerPoints[] | undefined,
): CornerRow[] {
  const n = cmp.reference.samples, step = cmp.reference.step_m;
  return segments.map((seg, i) => {
    const pts = refCorners?.find((c) => c.name === seg.name) ?? refCorners?.[i];
    const segDelta = cmp.delta[gridIndex(seg.end_m, step, n)] - cmp.delta[gridIndex(seg.start_m, step, n)];
    if (!pts?.bounds_m || pts.bounds_m.length !== 4) {
      return { name: seg.name, start_m: seg.start_m, end_m: seg.end_m, delta_s: segDelta, phase_delta_s: null };
    }
    const edges = [seg.start_m, ...pts.bounds_m, seg.end_m];
    const idx = edges.map((e) => gridIndex(e, step, n));
    for (let k = 1; k < idx.length; k++) idx[k] = Math.max(idx[k], idx[k - 1]);
    const phase = {} as Record<Phase, number>;
    let total = 0;
    PHASES.forEach((p, k) => {
      phase[p] = cmp.delta[idx[k + 1]] - cmp.delta[idx[k]];
      total += phase[p];
    });
    return { name: seg.name, start_m: seg.start_m, end_m: seg.end_m, delta_s: total, phase_delta_s: phase };
  });
}

/** Delta time gained (<0) or lost (>0) per 100 m, over a centred window, for track colouring. */
export function gainPer100m(delta: Float64Array, step: number, windowM = 100): Float64Array {
  const n = delta.length;
  const h = Math.max(1, Math.round(windowM / step / 2));
  const out = new Float64Array(n);
  for (let i = 0; i < n; i++) {
    const a = Math.max(0, i - h), b = Math.min(n - 1, i + h);
    out[i] = b > a ? ((delta[b] - delta[a]) * 100) / ((b - a) * step) : 0;
  }
  return out;
}

/** `lap.time - sim.time` on the session grid (positive: slower than the perfect lap). */
export function deltaToPerfect(session: LoadedSession, code: string): Float64Array | null {
  const sim = session.columns.get("sim.time");
  const lap = session.columns.get(`${code}.time`);
  if (!sim || !lap) return null;
  return lap.map((t, i) => t - sim[i]);
}
