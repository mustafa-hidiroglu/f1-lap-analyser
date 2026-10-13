const FALLBACK = ["#E8E8EA", "#F2B33D"];

function hexToRgb(hex: string): [number, number, number] | null {
  const m = /^#?([0-9a-f]{6})$/i.exec(hex.trim());
  if (!m) return null;
  const n = parseInt(m[1], 16);
  return [(n >> 16) & 255, (n >> 8) & 255, n & 255];
}

function close(a: string, b: string): boolean {
  const x = hexToRgb(a), y = hexToRgb(b);
  if (!x || !y) return a.toLowerCase() === b.toLowerCase();
  return Math.hypot(x[0] - y[0], x[1] - y[1], x[2] - y[2]) < 60;
}

/** Mix `hex` towards white by `t` (0..1). */
export function lighten(hex: string, t: number): string {
  const c = hexToRgb(hex);
  if (!c) return hex;
  const mix = c.map((v) => Math.round(v + (255 - v) * t));
  return `#${mix.map((v) => v.toString(16).padStart(2, "0")).join("")}`;
}

export interface Pair {
  ref: string;
  oth: string;
  /** Teammates (or near-identical team colours): the compared driver is drawn dashed. */
  dashed: boolean;
}

/** Colours for a reference/compared pair, from the data's team colours. */
export function pairColors(ref: string | null | undefined, oth: string | null | undefined): Pair {
  const r = ref ?? FALLBACK[0];
  let o = oth ?? FALLBACK[1];
  const dashed = close(r, o);
  // Same colour: lighten the second so fills (track map, table tints) stay distinguishable.
  if (dashed) o = lighten(o, 0.55);
  return { ref: r, oth: o, dashed };
}
