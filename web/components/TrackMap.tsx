// Track outline coloured by who is faster where. Pure (no hooks): renders on the server for the
// home page and inside the client analyser.

import type { Circuit } from "@/lib/types";
import { nearestSample, projectTrack } from "@/lib/track";

interface Props {
  circuit: Circuit;
  /** Delta gained (<0, compared faster) or lost (>0) per 100 m, on the session grid. */
  gain: Float64Array;
  step: number;
  refColor: string;
  othColor: string;
  /** Distance of the hover cursor, metres. */
  cursorM?: number | null;
  /** Highlighted distance window (zoomed corner), metres. */
  window?: [number, number] | null;
  labels?: boolean;
  /** Draw the coloured layer in on first paint (home page). */
  reveal?: boolean;
  id: string;
  title: string;
  className?: string;
}

const LEVELS = 4; // opacity steps; saturates at 0.02 s per 100 m

export function TrackMap({
  circuit, gain, step, refColor, othColor, cursorM, window, labels = true, reveal, id, title, className,
}: Props) {
  const shape = projectTrack(circuit);
  if (!shape) {
    return <p className="text-sm text-muted">No position data for this circuit.</p>;
  }
  const { px, py, distance, unit } = shape;
  const n = px.length;
  // Sub-unit precision is invisible at this scale (a unit is ~1 % of the track's extent).
  const digits = unit >= 1 ? 0 : 1;
  const pt = (i: number) => `${px[i].toFixed(digits)},${py[i].toFixed(digits)}`;

  // Runs of consecutive samples with the same leader and strength -> one polyline each.
  const runs: { from: number; to: number; color: string; opacity: number; dim: boolean }[] = [];
  for (let i = 1; i < n; i++) {
    const g = gain[Math.min(gain.length - 1, Math.round(distance[i] / step))] ?? 0;
    const level = Number.isFinite(g) ? Math.min(LEVELS, Math.ceil((Math.abs(g) / 0.02) * LEVELS)) : 0;
    const color = g < 0 ? othColor : refColor;
    const opacity = level === 0 ? 0.18 : 0.25 + (0.75 * level) / LEVELS;
    const dim = !!window && (distance[i] < window[0] || distance[i] > window[1]);
    const last = runs[runs.length - 1];
    if (last && last.color === color && last.opacity === opacity && last.dim === dim) last.to = i;
    else runs.push({ from: i - 1, to: i, color, opacity, dim });
  }

  const all = Array.from({ length: n }, (_, i) => pt(i)).join(" ");
  const cursor = cursorM != null ? nearestSample(distance, cursorM) : null;
  const sw = unit * 1.3;

  // Start/finish: a short bar across the track at sample 0.
  const dx = px[1] - px[0], dy = py[1] - py[0];
  const len = Math.hypot(dx, dy) || 1;
  const nx = (-dy / len) * unit * 2.2, ny = (dx / len) * unit * 2.2;

  return (
    <svg
      viewBox={`0 0 ${shape.width.toFixed(1)} ${shape.height.toFixed(1)}`}
      className={className}
      role="img"
      aria-label={title}
      preserveAspectRatio="xMidYMid meet"
    >
      <title>{title}</title>
      {reveal && (
        <mask id={`${id}-mask`} maskUnits="userSpaceOnUse">
          <polyline
            points={all}
            fill="none"
            stroke="#fff"
            strokeWidth={sw * 3}
            strokeLinecap="round"
            strokeLinejoin="round"
            pathLength={1}
            className="track-reveal"
          />
        </mask>
      )}
      <polyline
        points={all}
        fill="none"
        stroke="var(--color-line)"
        strokeWidth={sw * 2.2}
        strokeLinecap="round"
        strokeLinejoin="round"
      />
      <g mask={reveal ? `url(#${id}-mask)` : undefined}>
        {runs.map((r) => (
          <polyline
            key={r.from}
            points={Array.from({ length: r.to - r.from + 1 }, (_, k) => pt(r.from + k)).join(" ")}
            fill="none"
            stroke={r.color}
            strokeOpacity={r.dim ? r.opacity * 0.3 : r.opacity}
            strokeWidth={r.dim ? sw * 0.8 : sw}
            strokeLinecap="round"
            strokeLinejoin="round"
          />
        ))}
      </g>
      <line
        x1={px[0] - nx} y1={py[0] - ny} x2={px[0] + nx} y2={py[0] + ny}
        stroke="var(--color-fg)" strokeWidth={unit * 0.6} strokeLinecap="round"
      />
      {labels &&
        circuit.corners.map((c) => {
          const i = nearestSample(distance, c.distance_m);
          return (
            <text
              key={`${c.label}-${c.distance_m}`}
              x={px[i] + unit * 2.4}
              y={py[i] - unit * 2.4}
              fontSize={unit * 3.2}
              className="fill-muted font-mono"
              paintOrder="stroke"
              stroke="var(--color-bg)"
              strokeWidth={unit * 0.8}
            >
              {c.label}
            </text>
          );
        })}
      {cursor != null && (
        <circle
          cx={px[cursor]} cy={py[cursor]} r={unit * 1.8}
          fill="var(--color-fg)" stroke="var(--color-bg)" strokeWidth={unit * 0.6}
        />
      )}
    </svg>
  );
}
