const ok = (v: number | null | undefined): v is number => v != null && Number.isFinite(v);

/** 79.327 -> "1:19.327" */
export function lapTime(s: number | null | undefined): string {
  if (!ok(s)) return "-";
  const m = Math.floor(s / 60);
  const rest = s - m * 60;
  return m > 0 ? `${m}:${rest.toFixed(3).padStart(6, "0")}` : rest.toFixed(3);
}

/** Signed seconds, "+0.134" / "-0.052". */
export function delta(s: number | null | undefined, digits = 3): string {
  if (!ok(s)) return "-";
  const v = Number(s.toFixed(digits));
  return `${v > 0 ? "+" : v < 0 ? "-" : "±"}${Math.abs(v).toFixed(digits)}`;
}

export function fixed(v: number | null | undefined, digits = 0): string {
  return ok(v) ? v.toFixed(digits) : "-";
}

export function metres(v: number | null | undefined): string {
  return ok(v) ? `${Math.round(v)} m` : "-";
}
