"use client";

import { ArrowBendDownRight, FlagCheckered } from "@phosphor-icons/react";
import { useMemo, useState } from "react";
import { LineChart, type Series } from "@/components/charts/LineChart";
import { deltaToPerfect } from "@/lib/analysis";
import { delta, fixed, lapTime } from "@/lib/format";
import type { PerfectReport, Rating } from "@/lib/types";
import type { Side } from "./Analyser";
import { Notice, SectionTitle, Stat } from "./ui";

export function RatingTab({ sides }: { sides: [Side, Side] }) {
  const [which, setWhich] = useState(0);
  const same = sides[0].driver.code === sides[1].driver.code && sides[0].session === sides[1].session;
  const side = sides[same ? 0 : which];
  const lap = side.session.meta.laps[side.driver.code];
  const rating = lap?.rating && "score" in lap.rating ? (lap.rating as Rating) : null;
  const ratingError = lap?.rating && "error" in lap.rating ? lap.rating.error : null;

  return (
    <div className="grid grid-cols-[minmax(0,1fr)] gap-10">
      {!same && (
        <fieldset className="flex flex-wrap items-center gap-3">
          <legend className="sr-only">Lap to rate</legend>
          <span className="text-sm text-muted" aria-hidden>Rate</span>
          <div className="inline-flex rounded-full border border-line p-1">
            {sides.map((s, i) => (
              <label key={i} className={`cursor-pointer rounded-full px-4 py-1.5 text-sm has-[:focus-visible]:outline-2 has-[:focus-visible]:outline-accent ${which === i ? "bg-raised text-fg" : "text-muted hover:text-fg"}`}>
                <input type="radio" name="rated" className="sr-only" checked={which === i} onChange={() => setWhich(i)} />
                {i === 0 ? "Reference" : "Compared"} <span className="font-mono" style={{ color: s.color }}>{s.label}</span>
              </label>
            ))}
          </div>
        </fieldset>
      )}

      <PerfectSection side={side} report={lap?.perfect} />
      {rating ? (
        <RatingReport side={side} r={rating} />
      ) : (
        <Notice>No rating for this lap{ratingError ? `: ${ratingError}` : "."}</Notice>
      )}
    </div>
  );
}

function RatingReport({ side, r }: { side: Side; r: Rating }) {
  const ref = side.session.meta.reference;
  const th = "px-3 py-2 text-right font-normal";
  const td = "px-3 py-2 text-right font-mono tabular";
  const loss = (v: number) => (v > 0.0005 ? "text-danger" : "text-muted");
  return (
    <section aria-labelledby="rating-title" className="grid grid-cols-[minmax(0,1fr)] gap-6">
      <SectionTitle><span id="rating-title">Lap rating</span></SectionTitle>
      <dl className="grid grid-cols-2 gap-x-6 gap-y-5 sm:grid-cols-3 lg:grid-cols-6">
        <Stat label="Score" value={fixed(r.score)} sub="out of 100" accent />
        <Stat label={`${side.label}${r.lap_number ? ` L${r.lap_number}` : ""}`} value={lapTime(r.lap_time_s)} />
        <Stat label="Theoretical best" value={lapTime(r.theoretical_best_s)} sub="own best segments" />
        <Stat label="Left on the table" value={delta(r.time_left_s)} />
        <Stat label="Session ultimate" value={lapTime(r.ultimate_s)} sub="best segments of the field" />
        <Stat label="Gap to ultimate" value={delta(r.gap_to_ultimate_s)} />
      </dl>
      <p className="max-w-[80ch] text-xs leading-relaxed text-muted">
        Against {r.laps} valid laps from {r.drivers} drivers; segments cut on {ref.driver} L{ref.lap_number}. Score is
        the mean segment percentile against the other drivers&apos; bests.
      </p>
      <div className="overflow-x-auto rounded-xl border border-line">
        <table className="w-full min-w-[760px] text-sm">
          <caption className="sr-only">Segment times for {side.label} against the driver&apos;s own best and the field&apos;s best</caption>
          <thead className="bg-panel text-xs text-muted">
            <tr>
              <th scope="col" className="px-3 py-2 text-left font-normal">Segment</th>
              <th scope="col" className={th}>Time</th>
              <th scope="col" className={th}>Own best</th>
              <th scope="col" className={th}>Lost</th>
              <th scope="col" className={th}>Field best</th>
              <th scope="col" className="px-3 py-2 text-left font-normal">By</th>
              <th scope="col" className={th}>Lost to field</th>
              <th scope="col" className={th}>Rank</th>
              <th scope="col" className={th}>Percentile</th>
            </tr>
          </thead>
          <tbody>
            {r.segments.map((s) => (
              <tr key={s.name} className="border-t border-line/60">
                <th scope="row" className="px-3 py-2 text-left font-medium">{s.name}</th>
                <td className={td}>{fixed(s.time_s, 3)}</td>
                <td className={td}>{fixed(s.own_best_s, 3)}{s.own_best_lap != null && <span className="text-muted"> L{s.own_best_lap}</span>}</td>
                <td className={`${td} ${loss(s.lost_to_own_best_s)}`}>{delta(s.lost_to_own_best_s)}</td>
                <td className={td}>{fixed(s.field_best_s, 3)}</td>
                <td className="px-3 py-2 text-left font-mono text-muted">{s.field_best_by}</td>
                <td className={`${td} ${loss(s.lost_to_field_s)}`}>{delta(s.lost_to_field_s)}</td>
                <td className={td}>{s.rank}/{r.drivers}</td>
                <td className={td}>{fixed(s.percentile)}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </section>
  );
}

function PerfectSection({ side, report }: { side: Side; report?: PerfectReport }) {
  const [cursor, setCursor] = useState<number | null>(null);
  const meta = side.session.meta;
  const series = useMemo<Series[] | null>(() => {
    const d = deltaToPerfect(side.session, side.driver.code);
    return d && [{ name: side.label, values: d, color: side.color }];
  }, [side]);

  if (!report || report.error || !meta.perfect.available) {
    const why = report?.error ?? meta.perfect.error;
    return (
      <section aria-labelledby="perfect-title">
        <SectionTitle><span id="perfect-title">Against the perfect lap</span></SectionTitle>
        <Notice>No perfect lap for this session{why ? `: ${why}` : "."}</Notice>
      </section>
    );
  }
  const left = Math.max((report.gap_s ?? 0) - (report.typical_gap_s ?? 0), 0);
  const corners = report.corners ?? [];
  return (
    <section aria-labelledby="perfect-title" className="grid grid-cols-[minmax(0,1fr)] gap-6">
      <SectionTitle><span id="perfect-title">Against the perfect lap</span></SectionTitle>
      <dl className="grid grid-cols-2 gap-x-6 gap-y-5 md:grid-cols-4">
        <Stat label="Perfect lap" value={lapTime(report.sim_lap_time_s)} sub="simulated from the session's best" />
        <Stat label="Gap" value={delta(report.gap_s)} />
        <Stat label="Best laps' typical gap" value={delta(report.typical_gap_s)} />
        <Stat label="Left on the table" value={delta(left)} accent />
      </dl>

      {!!report.summary?.length && (
        <ul className="grid max-w-[90ch] gap-2 text-sm leading-relaxed">
          {report.summary.map((line, i) => (
            <li key={i} className="flex gap-2.5">
              {i === 0
                ? <FlagCheckered size={16} className="mt-0.5 shrink-0 text-fg" aria-hidden />
                : <ArrowBendDownRight size={16} className="mt-0.5 shrink-0 text-muted" aria-hidden />}
              <span className={i === 0 ? "" : "text-muted"}>{line}</span>
            </li>
          ))}
        </ul>
      )}

      {series && (
        <LineChart
          title={`Delta to the perfect lap, s (${side.label} minus perfect)`}
          series={series}
          step={meta.step_m}
          xDomain={[0, (meta.samples - 1) * meta.step_m]}
          height={160}
          cursor={cursor}
          onCursor={setCursor}
          format={(v) => delta(v, 2)}
          zero
          xAxis
        />
      )}

      {corners.length > 0 && (
        <div className="overflow-x-auto rounded-xl border border-line">
          <table className="w-full min-w-[680px] text-sm">
            <caption className="sr-only">Time lost to the perfect lap per corner, with findings</caption>
            <thead className="bg-panel text-xs text-muted">
              <tr>
                <th scope="col" className="px-3 py-2 text-left font-normal">Corner</th>
                <th scope="col" className="px-3 py-2 text-right font-normal">Lost</th>
                <th scope="col" className="px-3 py-2 text-right font-normal">Typical</th>
                <th scope="col" className="px-3 py-2 text-right font-normal">Excess</th>
                <th scope="col" className="px-3 py-2 text-left font-normal">Findings</th>
              </tr>
            </thead>
            <tbody>
              {corners.map((c) => (
                <tr key={c.name} className="border-t border-line/60 align-top">
                  <th scope="row" className="px-3 py-2 text-left font-medium">{c.name}</th>
                  <td className="px-3 py-2 text-right font-mono tabular">{delta(c.lost_s)}</td>
                  <td className="px-3 py-2 text-right font-mono text-muted tabular">{delta(c.typical_lost_s)}</td>
                  <td className={`px-3 py-2 text-right font-mono tabular ${c.excess_s > 0.0005 ? "text-danger" : "text-muted"}`}>{delta(c.excess_s)}</td>
                  <td className="px-3 py-2 text-muted">
                    {c.findings.length ? c.findings.map((f, i) => <p key={i}>{f.text}</p>) : "-"}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}

      {(() => {
        // Lap-level findings usually already appear in the summary; show only the rest.
        const extra = report.lap_findings?.filter((f) => !report.summary?.includes(f.text)) ?? [];
        return extra.length > 0 && <p className="text-xs text-muted">{extra.map((f) => f.text).join(" ")}</p>;
      })()}
    </section>
  );
}
