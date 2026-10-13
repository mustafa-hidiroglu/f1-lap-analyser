"use client";

import { memo, useMemo, type KeyboardEvent, type PointerEvent } from "react";

export interface Series {
  name: string;
  values: Float64Array;
  color: string;
  dashed?: boolean;
}

interface Props {
  title: string;
  series: Series[];
  /** Grid step (m): sample i sits at i * step. */
  step: number;
  xDomain: [number, number];
  height: number;
  /** Shared hover cursor (sample index). */
  cursor: number | null;
  onCursor: (i: number | null) => void;
  format: (v: number) => string;
  yDomain?: [number, number];
  zero?: boolean;
  stepped?: boolean;
  xAxis?: boolean;
}

const W = 1000;
const MAX_POINTS = 1600;

function niceTicks(lo: number, hi: number, count = 3): number[] {
  const span = hi - lo;
  if (!(span > 0)) return [lo];
  const raw = span / count;
  const mag = 10 ** Math.floor(Math.log10(raw));
  const step = [1, 2, 2.5, 5, 10].map((m) => m * mag).find((s) => s >= raw) ?? raw;
  const out: number[] = [];
  for (let v = Math.ceil(lo / step) * step; v <= hi + 1e-9; v += step) out.push(Number(v.toFixed(10)));
  return out;
}

function buildPath(values: Float64Array, i0: number, i1: number, x: (i: number) => number, y: (v: number) => number, stepped: boolean): string {
  const stride = Math.max(1, Math.floor((i1 - i0) / MAX_POINTS));
  let d = "";
  let pen = false;
  for (let i = i0; i <= i1; i += stride) {
    const v = values[i];
    if (!Number.isFinite(v)) { pen = false; continue; }
    const px = x(i).toFixed(1), py = y(v).toFixed(1);
    if (!pen) d += `M${px} ${py}`;
    else if (stepped) d += `H${px}V${py}`;
    else d += `L${px} ${py}`;
    pen = true;
  }
  return d;
}

/** Distance-domain line chart (SVG). Stretches to its container's width. */
export const LineChart = memo(function LineChart({
  title, series, step, xDomain, height, cursor, onCursor, format, yDomain, zero, stepped = false, xAxis = false,
}: Props) {
  const [x0, x1] = xDomain;
  const n = series[0]?.values.length ?? 0;
  const i0 = Math.max(0, Math.floor(x0 / step));
  const i1 = Math.min(n - 1, Math.ceil(x1 / step));

  const geom = useMemo(() => {
    let lo = Infinity, hi = -Infinity;
    if (yDomain) [lo, hi] = yDomain;
    else {
      for (const s of series) {
        for (let i = i0; i <= i1; i++) {
          const v = s.values[i];
          if (v < lo) lo = v;
          if (v > hi) hi = v;
        }
      }
      if (!Number.isFinite(lo)) { lo = 0; hi = 1; }
      if (zero) { lo = Math.min(lo, 0); hi = Math.max(hi, 0); }
      const pad = (hi - lo) * 0.08 || 0.5;
      lo -= pad; hi += pad;
    }
    const x = (i: number) => ((i * step - x0) / (x1 - x0)) * W;
    const y = (v: number) => height - ((v - lo) / (hi - lo)) * height;
    return {
      lo, hi, y,
      paths: series.map((s) => buildPath(s.values, i0, i1, x, y, stepped)),
      ticks: niceTicks(lo, hi),
    };
  }, [series, i0, i1, x0, x1, step, height, yDomain, zero, stepped]);

  const xFrac = (i: number) => (i * step - x0) / (x1 - x0);
  const inView = cursor != null && cursor >= i0 && cursor <= i1;

  function move(e: PointerEvent<HTMLDivElement>) {
    const r = e.currentTarget.getBoundingClientRect();
    const frac = Math.min(1, Math.max(0, (e.clientX - r.left) / r.width));
    onCursor(Math.round((x0 + frac * (x1 - x0)) / step));
  }

  function key(e: KeyboardEvent<HTMLDivElement>) {
    const by = e.shiftKey ? 20 : 2;
    if (e.key === "ArrowRight" || e.key === "ArrowLeft") {
      e.preventDefault();
      const from = cursor ?? i0;
      onCursor(Math.min(i1, Math.max(i0, from + (e.key === "ArrowRight" ? by : -by))));
    } else if (e.key === "Escape") onCursor(null);
  }

  const xTicks = xAxis ? niceTicks(x0, x1, 6) : [];

  return (
    <figure className="min-w-0">
      <figcaption className="mb-1.5 flex flex-wrap items-baseline gap-x-4 gap-y-1 text-xs">
        <span className="text-muted">{title}</span>
        {series.map((s) => (
          <span key={s.name} className="inline-flex items-center gap-1.5 font-mono tabular">
            <svg width="16" height="4" aria-hidden className="overflow-visible">
              <line x1="0" x2="16" y1="2" y2="2" stroke={s.color} strokeWidth="2" strokeDasharray={s.dashed ? "4 3" : undefined} />
            </svg>
            <span className="text-muted">{s.name}</span>
            {inView && <span className="text-fg">{format(s.values[cursor])}</span>}
          </span>
        ))}
        {inView && <span className="ml-auto font-mono text-muted tabular">{Math.round(cursor * step)} m</span>}
      </figcaption>
      <div
        className="relative cursor-crosshair touch-pan-y rounded-md border border-line/60 bg-panel"
        style={{ height }}
        tabIndex={0}
        role="img"
        aria-label={`${title}. Use left and right arrow keys to move the cursor along the lap.`}
        onPointerMove={move}
        onPointerDown={move}
        onPointerLeave={(e) => e.pointerType === "mouse" && onCursor(null)}
        onKeyDown={key}
      >
        <svg viewBox={`0 0 ${W} ${height}`} preserveAspectRatio="none" className="absolute inset-0 h-full w-full overflow-visible" aria-hidden>
          {geom.ticks.map((t) => (
            <line key={t} x1={0} x2={W} y1={geom.y(t)} y2={geom.y(t)} stroke="var(--color-line)" strokeOpacity={t === 0 && zero ? 1 : 0.5} vectorEffect="non-scaling-stroke" />
          ))}
          {geom.paths.map((d, k) => (
            <path
              key={series[k].name}
              d={d}
              fill="none"
              stroke={series[k].color}
              strokeWidth={1.5}
              strokeDasharray={series[k].dashed ? "6 4" : undefined}
              strokeLinejoin="round"
              vectorEffect="non-scaling-stroke"
            />
          ))}
          {inView && (
            <line x1={xFrac(cursor) * W} x2={xFrac(cursor) * W} y1={0} y2={height} stroke="var(--color-fg)" strokeOpacity={0.6} vectorEffect="non-scaling-stroke" />
          )}
        </svg>
        {geom.ticks.map((t) => {
          const top = geom.y(t);
          if (top < 6 || top > height - 6) return null;
          return (
            <span key={t} className="pointer-events-none absolute left-1.5 -translate-y-1/2 font-mono text-[10px] text-muted tabular" style={{ top }}>
              {format(t)}
            </span>
          );
        })}
      </div>
      {xAxis && (
        <div className="relative mt-1 h-4 font-mono text-[10px] text-muted tabular" aria-hidden>
          {xTicks.map((t) => {
            const f = (t - x0) / (x1 - x0);
            if (f < 0.02 || f > 0.98) return null;
            return (
              <span key={t} className="absolute -translate-x-1/2" style={{ left: `${f * 100}%` }}>
                {t >= 1000 ? `${(t / 1000).toFixed(t % 1000 ? 1 : 0)} km` : `${t} m`}
              </span>
            );
          })}
        </div>
      )}
    </figure>
  );
});
