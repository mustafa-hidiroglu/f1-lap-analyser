"use client";

import { ArrowCounterClockwise } from "@phosphor-icons/react";
import { useMemo, useState } from "react";
import { LineChart, type Series } from "@/components/charts/LineChart";
import { TrackMap } from "@/components/TrackMap";
import {
  compare,
  compareCorners,
  cornerTable,
  gainPer100m,
  PHASES,
  sessionLap,
  summarise,
  type CornerRow,
  type SectorRow,
} from "@/lib/analysis";
import { delta, fixed, lapTime } from "@/lib/format";
import type { Side } from "./Analyser";
import { DriverDot, Notice, SectionTitle, Stat } from "./ui";

type TraceKey = "speed" | "throttle" | "brake" | "gear";

interface Props {
  reference: Side;
  compared: Side;
  crossSeason: boolean;
}

/** Background tint for a delta cell: the faster driver's colour, stronger for bigger gaps. */
function tint(v: number, ref: string, oth: string): string | undefined {
  if (!Number.isFinite(v) || Math.abs(v) < 0.005) return undefined;
  const a = Math.min(0.45, 0.1 + Math.abs(v) * 2);
  const hex = Math.round(a * 255).toString(16).padStart(2, "0");
  return `${v < 0 ? oth : ref}${hex}`;
}

export function CompareTab({ reference, compared, crossSeason }: Props) {
  const [cursor, setCursor] = useState<number | null>(null);
  const [zoom, setZoom] = useState<string | null>(null);

  const result = useMemo(() => {
    try {
      const meta = reference.session.meta;
      const cmp = compare(sessionLap(reference.session, reference.driver.code), sessionLap(compared.session, compared.driver.code));
      const segments = meta.circuit.segments;
      let sectors: SectorRow[] = [];
      let corners: CornerRow[] = [];
      if (segments.length) {
        sectors = cornerTable(cmp, segments);
        corners = compareCorners(cmp, segments, meta.laps[reference.driver.code]?.corners);
      }
      const pair = (k: TraceKey): Series[] => [
        { name: reference.label, values: cmp.reference.channels[k], color: reference.color },
        { name: compared.label, values: cmp.other.channels[k], color: compared.color, dashed: compared.dashed },
      ];
      // Built once per comparison so hovering doesn't rebuild every chart's paths.
      const series = {
        delta: [{ name: "delta", values: cmp.delta, color: "var(--color-fg)" }] as Series[],
        speed: pair("speed"), throttle: pair("throttle"), brake: pair("brake"), gear: pair("gear"),
      };
      return { cmp, sectors, corners, series, summary: summarise(cmp), gain: gainPer100m(cmp.delta, meta.step_m) };
    } catch (e) {
      return { error: e instanceof Error ? e.message : String(e) };
    }
  }, [reference, compared]);

  if ("error" in result) return <Notice tone="error">Could not compare these laps ({result.error}).</Notice>;

  const { cmp, sectors, corners, series, summary, gain } = result;
  const meta = reference.session.meta;
  const step = meta.step_m;
  const end = (cmp.reference.samples - 1) * step;
  const zoomed = corners.find((c) => c.name === zoom);
  const xDomain: [number, number] = zoomed
    ? [Math.max(0, zoomed.start_m - 60), Math.min(end, zoomed.end_m + 60)]
    : [0, end];
  const R = reference, O = compared;
  const lead = summary.final_delta_s < 0 ? O : R;

  const traces: { title: string; key: TraceKey; h: number; fmt: (v: number) => string; y?: [number, number]; stepped?: boolean }[] = [
    { title: "Speed (km/h)", key: "speed", h: 150, fmt: (v) => fixed(v) },
    { title: "Throttle (%)", key: "throttle", h: 70, fmt: (v) => fixed(v), y: [-8, 108] },
    { title: "Brake (%)", key: "brake", h: 54, fmt: (v) => fixed(v), y: [-8, 108] },
    { title: "Gear", key: "gear", h: 70, fmt: (v) => fixed(v), y: [0.5, 8.5], stepped: true },
  ];
  return (
    <div className="grid grid-cols-[minmax(0,1fr)] gap-8">
      <dl className="grid grid-cols-2 gap-x-6 gap-y-5 md:grid-cols-4">
        <Stat label={`${R.label} lap`} value={lapTime(R.driver.lap_time_s)} sub={`Lap ${R.driver.lap_number}${R.driver.compound ? `, ${R.driver.compound.toLowerCase()}` : ""}`} />
        <Stat label={`${O.label} lap`} value={lapTime(O.driver.lap_time_s)} sub={`Lap ${O.driver.lap_number}${O.driver.compound ? `, ${O.driver.compound.toLowerCase()}` : ""}`} />
        <Stat
          label="Final delta"
          value={delta(summary.final_delta_s)}
          accent
          sub={Math.abs(summary.final_delta_s) < 0.0005 ? "Dead level" : `${lead.label} ahead at the line`}
        />
        <Stat
          label="Largest swing"
          value={`${delta(summary.max_gain_s)} / ${delta(summary.max_loss_s)}`}
          sub={`at ${Math.round(summary.max_gain_at_m)} m / ${Math.round(summary.max_loss_at_m)} m`}
        />
      </dl>
      {crossSeason && (
        <Notice>
          Different seasons: the {O.label} lap&apos;s distance is rescaled to the {R.label} lap&apos;s length ({fixed(meta.length_m)} m)
          before comparing, as in the desktop app. Corner segments and phases come from the reference session.
        </Notice>
      )}

      <div className="grid grid-cols-[minmax(0,1fr)] gap-8 xl:grid-cols-[minmax(0,1fr)_340px]">
        <div className="grid min-w-0 gap-4">
          <div className="flex flex-wrap items-center justify-between gap-2">
            <SectionTitle>Delta and traces</SectionTitle>
            {zoomed && (
              <button type="button" onClick={() => setZoom(null)} className="inline-flex items-center gap-1.5 rounded-full border border-line px-3 py-1 text-xs text-muted hover:text-fg">
                <ArrowCounterClockwise size={14} aria-hidden /> Full lap (zoomed to {zoomed.name})
              </button>
            )}
          </div>
          <LineChart
            title={`Delta, s (${O.label} minus ${R.label})`}
            series={series.delta}
            step={step}
            xDomain={xDomain}
            height={140}
            cursor={cursor}
            onCursor={setCursor}
            format={(v) => delta(v, 2)}
            zero
          />
          {traces.map((t, i) => (
            <LineChart
              key={t.key}
              title={t.title}
              series={series[t.key]}
              step={step}
              xDomain={xDomain}
              height={t.h}
              cursor={cursor}
              onCursor={setCursor}
              format={t.fmt}
              yDomain={t.y}
              stepped={t.stepped}
              xAxis={i === traces.length - 1}
            />
          ))}
        </div>

        <aside aria-label="Track map" className="xl:sticky xl:top-6 xl:self-start">
          <SectionTitle>Track</SectionTitle>
          <div className="rounded-xl border border-line bg-panel p-3">
            <TrackMap
              id="analyse-track"
              circuit={meta.circuit}
              gain={gain}
              step={step}
              refColor={R.color}
              othColor={O.color}
              cursorM={cursor != null ? cursor * step : null}
              window={zoomed ? [zoomed.start_m, zoomed.end_m] : null}
              title={`Track map coloured by whether ${R.label} or ${O.label} was faster`}
              className="aspect-square w-full"
            />
          </div>
          <p className="mt-3 flex flex-wrap gap-x-4 gap-y-1 text-xs text-muted">
            <span className="inline-flex items-center gap-1.5"><DriverDot color={R.color} /> {R.label} faster</span>
            <span className="inline-flex items-center gap-1.5"><DriverDot color={O.color} dashed={O.dashed} /> {O.label} faster</span>
            <span>Stronger colour, bigger gain per 100 m.</span>
          </p>
        </aside>
      </div>

      {corners.length > 0 && (
        <CornerTable corners={corners} sectors={sectors} R={R} O={O} zoom={zoom} onZoom={(n) => setZoom(zoom === n ? null : n)} />
      )}
    </div>
  );
}

function CornerTable({ corners, sectors, R, O, zoom, onZoom }: {
  corners: CornerRow[]; sectors: SectorRow[]; R: Side; O: Side; zoom: string | null; onZoom: (name: string) => void;
}) {
  const td = "px-3 py-2 text-right font-mono tabular";
  return (
    <section aria-labelledby="corner-table">
      <SectionTitle aside={<span className="text-xs text-muted">Select a corner to zoom the traces.</span>}>
        <span id="corner-table">Corners</span>
      </SectionTitle>
      <div className="overflow-x-auto rounded-xl border border-line">
        <table className="w-full min-w-[760px] text-sm">
          <caption className="sr-only">
            Time delta per corner and per phase, {O.label} minus {R.label}; negative means {O.label} gained.
          </caption>
          <thead className="bg-panel text-xs text-muted">
            <tr>
              <th scope="col" className="px-3 py-2 text-left font-normal">Corner</th>
              <th scope="col" className="px-3 py-2 text-right font-normal">Delta</th>
              {PHASES.map((p) => (
                <th key={p} scope="col" className="px-3 py-2 text-right font-normal capitalize">{p}</th>
              ))}
              <th scope="col" className="px-3 py-2 text-right font-normal">Min km/h</th>
            </tr>
          </thead>
          <tbody>
            {corners.map((c, i) => {
              const s = sectors[i];
              const on = zoom === c.name;
              return (
                <tr key={c.name} className={`border-t border-line/60 ${on ? "bg-raised" : ""}`}>
                  <th scope="row" className="px-3 py-1 text-left font-medium">
                    <button
                      type="button"
                      aria-pressed={on}
                      onClick={() => onZoom(c.name)}
                      className="rounded px-1 py-1 underline decoration-line underline-offset-4 hover:decoration-fg"
                    >
                      {c.name}
                    </button>
                  </th>
                  <td className={`${td} font-semibold`} style={{ background: tint(c.delta_s, R.color, O.color) }}>{delta(c.delta_s)}</td>
                  {PHASES.map((p) => {
                    const v = c.phase_delta_s?.[p];
                    return (
                      <td key={p} className={td} style={{ background: v == null ? undefined : tint(v, R.color, O.color) }}>
                        {v == null ? "-" : delta(v)}
                      </td>
                    );
                  })}
                  <td className={`${td} text-muted`}>
                    {s ? `${fixed(s.ref_min_speed)} / ${fixed(s.other_min_speed)}` : "-"}
                  </td>
                </tr>
              );
            })}
          </tbody>
        </table>
      </div>
    </section>
  );
}
