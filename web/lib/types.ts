// Data contract written by tools/web_export.py (see web/public/data/).

export interface SessionRef {
  key: string; // "Q" | "R"
  name: string;
  path: string; // relative to /data/
  drivers: number;
}

export interface EventEntry {
  round: number;
  name: string;
  country: string;
  location: string;
  date: string;
  slug: string;
  sessions: SessionRef[];
}

export interface Season {
  year: number;
  events: EventEntry[];
}

export interface IndexFile {
  generated_at: string;
  step_m: number;
  seasons: Season[];
  failures?: { year: number; round: number; session: string; error: string }[];
}

export interface Segment {
  name: string;
  start_m: number;
  end_m: number;
}

export interface Circuit {
  name: string;
  source: string;
  rotation_deg: number;
  corners: { label: string; distance_m: number }[];
  segments: Segment[];
  track?: { distance: number[]; x: number[]; y: number[] };
}

export interface DriverEntry {
  code: string;
  team: string;
  color: string | null;
  position: number | null;
  lap_number: number;
  lap_time_s: number | null;
  compound?: string | null;
}

export interface CornerPoints {
  name: string;
  entry_m: number;
  brake_on_m: number | null;
  brake_off_m: number | null;
  brake_applications: number;
  apex_m: number;
  mid_start_m: number;
  mid_end_m: number;
  pickup_m: number | null;
  full_throttle_m: number;
  entry_speed: number;
  apex_speed: number;
  exit_speed: number;
  flat: boolean;
  bounds_m: number[]; // entry, mid_start, mid_end, full_throttle
}

export interface LapMetrics {
  driver: string;
  lap_number: number;
  lap_time_s: number;
  full_throttle_s: number;
  full_throttle_pct: number;
  braking_s: number;
  braking_pct: number;
  coasting_s: number;
  coasting_pct: number;
  throttle_smoothness: number | null;
  brake_source: string;
}

export interface RatingSegment {
  name: string;
  time_s: number;
  own_best_s: number;
  own_best_lap: number | null;
  lost_to_own_best_s: number;
  field_best_s: number;
  field_best_by: string;
  lost_to_field_s: number;
  rank: number;
  percentile: number;
}

export interface Rating {
  driver: string;
  lap_number: number | null;
  lap_time_s: number;
  official_lap_time_s: number | null;
  theoretical_best_s: number;
  time_left_s: number;
  ultimate_s: number;
  gap_to_ultimate_s: number;
  score: number;
  drivers: number;
  laps: number;
  segments: RatingSegment[];
}

export interface Finding {
  kind: string;
  text: string;
  corner: string | null;
  cost_s: number | null;
}

export interface PerfectCorner {
  name: string;
  start_m: number;
  end_m: number;
  lost_s: number;
  typical_lost_s: number;
  excess_s: number;
  phase_lost_s: Record<string, number>;
  findings: Finding[];
}

export interface PerfectReport {
  error?: string;
  driver?: string;
  lap_number?: number;
  lap_time_s?: number;
  sim_lap_time_s?: number;
  gap_s?: number;
  typical_gap_s?: number;
  corners?: PerfectCorner[];
  lap_findings?: Finding[];
  summary?: string[];
}

export interface LapEntry {
  metrics?: LapMetrics;
  corners?: CornerPoints[];
  rating?: Rating | { error: string };
  perfect?: PerfectReport;
}

export type Dtype = "f32" | "f64" | "u8" | "u16" | "i16" | "i32";

export interface BinColumn {
  name: string;
  dtype: Dtype;
  offset: number;
  count: number;
  scale?: number;
}

export interface SessionFile {
  year: number;
  round: number;
  event: string;
  location: string;
  country?: string;
  date?: string;
  session: string;
  key: string;
  step_m: number;
  samples: number;
  length_m: number;
  fastest: string;
  reference: { driver: string; lap_number: number; lap_time_s: number };
  circuit: Circuit;
  drivers: DriverEntry[];
  laps: Record<string, LapEntry>;
  perfect: { available: boolean; sim_lap_time_s?: number; error?: string };
  binary: { file: string; columns: BinColumn[] };
}

/** A session JSON plus its decoded binary columns. */
export interface LoadedSession {
  meta: SessionFile;
  columns: Map<string, Float64Array>;
}
