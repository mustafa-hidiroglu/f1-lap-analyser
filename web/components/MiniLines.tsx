// Small static line plot (no axes, no interaction) for the home page.

interface Series {
  values: Float64Array;
  color: string;
  dashed?: boolean;
}

const W = 400;

function path(values: Float64Array, lo: number, hi: number, h: number): string {
  const n = values.length;
  const stride = Math.max(1, Math.floor(n / W));
  let d = "";
  let pen = false;
  for (let i = 0; i < n; i += stride) {
    const v = values[i];
    if (!Number.isFinite(v)) { pen = false; continue; }
    const x = (i / (n - 1)) * W;
    const y = h - ((v - lo) / (hi - lo || 1)) * h;
    d += `${pen ? "L" : "M"}${x.toFixed(1)} ${y.toFixed(1)}`;
    pen = true;
  }
  return d;
}

export function MiniLines({
  series, height = 120, zero = false, label, className,
}: { series: Series[]; height?: number; zero?: boolean; label: string; className?: string }) {
  let lo = Infinity, hi = -Infinity;
  for (const s of series) for (const v of s.values) if (Number.isFinite(v)) { lo = Math.min(lo, v); hi = Math.max(hi, v); }
  if (!Number.isFinite(lo)) return null;
  if (zero) { lo = Math.min(lo, 0); hi = Math.max(hi, 0); }
  const pad = (hi - lo) * 0.08 || 1;
  lo -= pad; hi += pad;
  const zy = height - ((0 - lo) / (hi - lo)) * height;
  return (
    <svg viewBox={`0 0 ${W} ${height}`} preserveAspectRatio="none" role="img" aria-label={label} className={className}>
      {zero && <line x1={0} x2={W} y1={zy} y2={zy} stroke="var(--color-line)" vectorEffect="non-scaling-stroke" />}
      {series.map((s, i) => (
        <path
          key={i}
          d={path(s.values, lo, hi, height)}
          fill="none"
          stroke={s.color}
          strokeWidth={1.75}
          strokeDasharray={s.dashed ? "5 4" : undefined}
          vectorEffect="non-scaling-stroke"
          strokeLinejoin="round"
        />
      ))}
    </svg>
  );
}
