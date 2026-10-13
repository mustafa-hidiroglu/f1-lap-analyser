import { Info, Warning } from "@phosphor-icons/react";
import type { ReactNode } from "react";

export function Stat({ label, value, sub, accent }: { label: string; value: ReactNode; sub?: ReactNode; accent?: boolean }) {
  return (
    <div className="min-w-0">
      <dt className="text-xs text-muted">{label}</dt>
      <dd className={`mt-1 font-mono text-xl font-semibold tracking-tight tabular ${accent ? "text-accent" : ""}`}>{value}</dd>
      {sub && <dd className="mt-0.5 text-xs text-muted">{sub}</dd>}
    </div>
  );
}

export function SectionTitle({ children, aside }: { children: ReactNode; aside?: ReactNode }) {
  return (
    <div className="mb-3 flex flex-wrap items-baseline justify-between gap-2">
      <h3 className="text-base font-medium">{children}</h3>
      {aside}
    </div>
  );
}

export function Notice({ tone = "info", children, action }: { tone?: "info" | "error"; children: ReactNode; action?: ReactNode }) {
  const Icon = tone === "error" ? Warning : Info;
  return (
    <div
      role={tone === "error" ? "alert" : "status"}
      className={`flex items-start gap-3 rounded-xl border p-4 text-sm leading-relaxed ${
        tone === "error" ? "border-danger/50 text-fg" : "border-line text-muted"
      }`}
    >
      <Icon size={18} weight="bold" className={`mt-0.5 shrink-0 ${tone === "error" ? "text-danger" : "text-accent"}`} aria-hidden />
      <div className="flex-1">{children}</div>
      {action}
    </div>
  );
}

export function Skeleton({ className = "" }: { className?: string }) {
  return <div aria-hidden className={`skeleton rounded-md bg-raised ${className}`} />;
}

export function DriverDot({ color, dashed }: { color: string; dashed?: boolean }) {
  return (
    <svg width="14" height="4" aria-hidden className="inline-block shrink-0 overflow-visible">
      <line x1="0" x2="14" y1="2" y2="2" stroke={color} strokeWidth="3" strokeLinecap="round" strokeDasharray={dashed ? "4 3" : undefined} />
    </svg>
  );
}
