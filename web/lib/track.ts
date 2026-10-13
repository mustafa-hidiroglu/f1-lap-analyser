// Track outline projection (rotation as in the desktop app's TrackProjection), in SVG units.

import type { Circuit } from "./types";

export interface TrackShape {
  /** Projected points (y down), one per track sample. */
  px: Float64Array;
  py: Float64Array;
  distance: number[];
  width: number;
  height: number;
  /** Stroke width that reads as ~1 % of the larger side. */
  unit: number;
}

export function projectTrack(circuit: Circuit, pad = 0.06): TrackShape | null {
  const t = circuit.track;
  if (!t || t.x.length < 2) return null;
  const r = ((circuit.rotation_deg ?? 0) * Math.PI) / 180;
  const c = Math.cos(r), s = Math.sin(r);
  const n = t.x.length;
  const rx = new Float64Array(n), ry = new Float64Array(n);
  let minX = Infinity, maxX = -Infinity, minY = Infinity, maxY = -Infinity;
  for (let i = 0; i < n; i++) {
    const x = t.x[i], y = t.y[i];
    rx[i] = x * c - y * s;
    ry[i] = x * s + y * c;
    if (!Number.isFinite(rx[i]) || !Number.isFinite(ry[i])) continue;
    minX = Math.min(minX, rx[i]); maxX = Math.max(maxX, rx[i]);
    minY = Math.min(minY, ry[i]); maxY = Math.max(maxY, ry[i]);
  }
  if (!Number.isFinite(minX)) return null;
  const span = Math.max(maxX - minX, maxY - minY, 1);
  const p = span * pad;
  const width = maxX - minX + 2 * p, height = maxY - minY + 2 * p;
  const px = rx.map((v) => v - minX + p);
  const py = ry.map((v) => maxY - v + p);
  return { px, py, distance: t.distance, width, height, unit: span / 100 };
}

/** Index of the track sample nearest to distance `d` (binary search; distances ascend). */
export function nearestSample(distance: number[], d: number): number {
  let lo = 0, hi = distance.length - 1;
  while (lo < hi) {
    const mid = (lo + hi) >> 1;
    if (distance[mid] < d) lo = mid + 1;
    else hi = mid;
  }
  return lo;
}
