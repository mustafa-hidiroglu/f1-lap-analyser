// Build-time data for the home page (server only): the featured session, read from public/data
// while `next build` prerenders the page, so the hero visual ships as static SVG.

import { existsSync, readFileSync } from "node:fs";
import path from "node:path";
import {
  compare,
  compareCorners,
  gainPer100m,
  sessionLap,
  summarise,
  type CornerRow,
} from "./analysis";
import { pairColors, type Pair } from "./colors";
import { decodeBinary, sessionDir } from "./data";
import { featured, toSearch } from "./selection";
import type { Circuit, DriverEntry, IndexFile, PerfectReport, Rating, SessionFile } from "./types";

const DATA = path.join(process.cwd(), "public", "data");

export interface HomePreview {
  year: number;
  event: string;
  session: string;
  ref: DriverEntry;
  oth: DriverEntry;
  colors: Pair;
  circuit: Circuit;
  step: number;
  gain: Float64Array;
  delta: Float64Array;
  refSpeed: Float64Array;
  othSpeed: Float64Array;
  finalDelta: number;
  corners: CornerRow[];
  rating: Rating | null;
  perfect: PerfectReport | null;
  href: string;
  seasons: number;
  sessions: number;
}

function readJson<T>(file: string): T {
  return JSON.parse(readFileSync(path.join(DATA, file), "utf8")) as T;
}

export function loadHomePreview(): HomePreview | null {
  try {
    if (!existsSync(path.join(DATA, "index.json"))) return null;
    const index = readJson<IndexFile>("index.json");
    const pick = featured(index);
    if (!pick) return null;
    const meta = readJson<SessionFile>(pick.session.path);
    const buf = readFileSync(path.join(DATA, sessionDir(pick.session.path), meta.binary.file));
    const ab = buf.buffer.slice(buf.byteOffset, buf.byteOffset + buf.byteLength) as ArrayBuffer;
    const session = { meta, columns: decodeBinary(ab, meta.binary.columns) };
    const [ref, oth] = meta.drivers;
    if (!ref || !oth) return null;
    const cmp = compare(sessionLap(session, ref.code), sessionLap(session, oth.code));
    const rating = meta.laps[ref.code]?.rating;
    return {
      year: pick.year,
      event: pick.event.name,
      session: meta.session,
      ref,
      oth,
      colors: pairColors(ref.color, oth.color),
      circuit: meta.circuit,
      step: meta.step_m,
      gain: gainPer100m(cmp.delta, meta.step_m),
      delta: cmp.delta,
      refSpeed: cmp.reference.channels.speed,
      othSpeed: cmp.other.channels.speed,
      finalDelta: summarise(cmp).final_delta_s,
      corners: compareCorners(cmp, meta.circuit.segments, meta.laps[ref.code]?.corners),
      rating: rating && "score" in rating ? rating : null,
      perfect: meta.laps[ref.code]?.perfect ?? null,
      href: `/analyse${toSearch({ y: pick.year, e: pick.event.slug, s: "Q", ref: ref.code, oth: oth.code, tab: "compare" })}`,
      seasons: index.seasons.length,
      sessions: index.seasons.reduce((n, s) => n + s.events.reduce((m, e) => m + e.sessions.length, 0), 0),
    };
  } catch (err) {
    console.warn("home preview unavailable:", err);
    return null;
  }
}
