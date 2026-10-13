// URL state for /analyse (?y=&e=&s=&ref=&oth=&oy=&tab=) and its resolution against index.json.

import type { DriverEntry, EventEntry, IndexFile, Season, SessionFile, SessionRef } from "./types";

export const FASTEST = "fastest";
export type Tab = "compare" | "rating";

export interface Params {
  y?: number;
  e?: string;
  s?: string;
  ref?: string;
  oth?: string;
  oy?: number;
  tab: Tab;
}

function int(v: string | null): number | undefined {
  const n = v == null ? NaN : Number.parseInt(v, 10);
  return Number.isFinite(n) ? n : undefined;
}

export function parseParams(search: string): Params {
  const q = new URLSearchParams(search);
  return {
    y: int(q.get("y")),
    e: q.get("e") ?? undefined,
    s: q.get("s") ?? undefined,
    ref: q.get("ref") ?? undefined,
    oth: q.get("oth") ?? undefined,
    oy: int(q.get("oy")),
    tab: q.get("tab") === "rating" ? "rating" : "compare",
  };
}

export function toSearch(p: Params): string {
  const q = new URLSearchParams();
  if (p.y != null) q.set("y", String(p.y));
  if (p.e) q.set("e", p.e);
  if (p.s) q.set("s", p.s);
  if (p.ref) q.set("ref", p.ref);
  if (p.oth) q.set("oth", p.oth);
  if (p.oy != null) q.set("oy", String(p.oy));
  if (p.tab !== "compare") q.set("tab", p.tab);
  const s = q.toString();
  return s ? `?${s}` : "";
}

export function sortedSeasons(index: IndexFile): Season[] {
  return [...index.seasons].sort((a, b) => b.year - a.year);
}

/** The same Grand Prix in another season (round numbers move, names rarely do). */
export function matchEvent(season: Season, event: EventEntry): EventEntry | undefined {
  return (
    season.events.find((e) => e.name === event.name) ??
    season.events.find((e) => e.location === event.location)
  );
}

/** Other seasons that have this event with the given session. */
export function otherSeasonsFor(index: IndexFile, event: EventEntry, year: number, key: string): number[] {
  return sortedSeasons(index)
    .filter((s) => s.year !== year && matchEvent(s, event)?.sessions.some((x) => x.key === key))
    .map((s) => s.year);
}

export interface Resolved {
  season: Season;
  event: EventEntry;
  session: SessionRef;
  /** Set when comparing against the same event in another season. */
  other?: { season: Season; event: EventEntry; session: SessionRef };
}

export function resolve(index: IndexFile, p: Params): Resolved | null {
  const seasons = sortedSeasons(index).filter((s) => s.events.length);
  const season = seasons.find((s) => s.year === p.y) ?? seasons[0];
  if (!season) return null;
  const event = season.events.find((e) => e.slug === p.e) ?? season.events[season.events.length - 1];
  const session = event.sessions.find((s) => s.key === p.s) ?? event.sessions[0];
  if (!session) return null;
  let other: Resolved["other"];
  if (p.oy != null && p.oy !== season.year) {
    const os = seasons.find((s) => s.year === p.oy);
    const oe = os && matchEvent(os, event);
    const ox = oe?.sessions.find((s) => s.key === session.key);
    if (os && oe && ox) other = { season: os, event: oe, session: ox };
  }
  return { season, event, session, other };
}

function byCode(meta: SessionFile, code: string | undefined): DriverEntry | undefined {
  return code ? meta.drivers.find((d) => d.code === code) : undefined;
}

/** Reference driver: the requested code, else the session's fastest. */
export function pickReference(meta: SessionFile, code: string | undefined): DriverEntry | undefined {
  if (code && code !== FASTEST) {
    const d = byCode(meta, code);
    if (d) return d;
  }
  return byCode(meta, meta.fastest) ?? meta.drivers[0];
}

/** Compared driver: the requested code; "fastest"; or by default the best driver other than `ref`. */
export function pickOther(meta: SessionFile, code: string | undefined, ref: string | undefined): DriverEntry | undefined {
  if (code === FASTEST) return byCode(meta, meta.fastest) ?? meta.drivers[0];
  return byCode(meta, code) ?? meta.drivers.find((d) => d.code !== ref) ?? meta.drivers[0];
}

/** Home page deep link: newest Monza qualifying if exported, else the newest qualifying. */
export function featured(index: IndexFile): { year: number; event: EventEntry; session: SessionRef } | null {
  const seasons = sortedSeasons(index);
  for (const pick of [(e: EventEntry) => e.location === "Monza", () => true]) {
    for (const s of seasons) {
      for (const e of [...s.events].reverse()) {
        const q = e.sessions.find((x) => x.key === "Q");
        if (q && pick(e)) return { year: s.year, event: e, session: q };
      }
    }
  }
  return null;
}
