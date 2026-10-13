"use client";

import { useRef, type KeyboardEvent } from "react";
import { pairColors } from "@/lib/colors";
import { lapTime } from "@/lib/format";
import {
  FASTEST,
  matchEvent,
  otherSeasonsFor,
  pickOther,
  pickReference,
  resolve,
  sortedSeasons,
  type Params,
  type Tab,
} from "@/lib/selection";
import type { DriverEntry, IndexFile, LoadedSession } from "@/lib/types";
import { CompareTab } from "./CompareTab";
import { useIndex, useSession, useUrlParams } from "./hooks";
import { RatingTab } from "./RatingTab";
import { Notice, Skeleton } from "./ui";

export interface Side {
  session: LoadedSession;
  driver: DriverEntry;
  color: string;
  dashed: boolean;
  /** "NOR" or "NOR 2025" when the sides come from different seasons. */
  label: string;
}

export function Analyser() {
  const [params, setParams] = useUrlParams();
  const { index, error, retry } = useIndex();

  if (error) {
    return (
      <Shell>
        <Notice tone="error" action={<button type="button" onClick={retry} className="rounded-full border border-line px-3 py-1 hover:border-muted">Retry</button>}>
          Could not load the session list ({error}).
        </Notice>
      </Shell>
    );
  }
  if (!index || !params) return <Shell><LoadingLayout /></Shell>;
  if (!index.seasons.some((s) => s.events.length)) {
    return <Shell><Notice>No sessions have been exported yet.</Notice></Shell>;
  }
  return <Loaded index={index} params={params} setParams={setParams} />;
}

function Shell({ children }: { children: React.ReactNode }) {
  return <div className="mx-auto max-w-[1400px] px-4 py-8 md:px-8">{children}</div>;
}

function Loaded({ index, params, setParams }: { index: IndexFile; params: Params; setParams: (p: Params, push?: boolean) => void }) {
  const r = resolve(index, params)!;
  const refQ = useSession(r.session.path);
  const othQ = useSession((r.other?.session ?? r.session).path);
  const crossSeason = !!r.other;
  const update = (patch: Partial<Params>) => setParams({ ...params, ...patch });

  const refMeta = refQ.session?.meta;
  const othMeta = othQ.session?.meta;
  const refDriver = refMeta && pickReference(refMeta, params.ref);
  const othDriver = othMeta && pickOther(othMeta, params.oth, crossSeason ? undefined : refDriver?.code);

  let sides: [Side, Side] | null = null;
  if (refQ.session && othQ.session && refDriver && othDriver) {
    const c = pairColors(refDriver.color, othDriver.color);
    const tag = (d: DriverEntry, y: number) => (crossSeason ? `${d.code} ${y}` : d.code);
    sides = [
      { session: refQ.session, driver: refDriver, color: c.ref, dashed: false, label: tag(refDriver, r.season.year) },
      { session: othQ.session, driver: othDriver, color: c.oth, dashed: c.dashed, label: tag(othDriver, r.other?.season.year ?? r.season.year) },
    ];
  }
  const loadError = refQ.error ?? othQ.error;
  const otherYears = otherSeasonsFor(index, r.event, r.season.year, r.session.key);

  return (
    <div className="mx-auto grid max-w-[1400px] grid-cols-[minmax(0,1fr)] gap-8 px-4 py-8 md:px-8 lg:grid-cols-[260px_minmax(0,1fr)]">
      <aside aria-label="Lap selection" className="lg:sticky lg:top-6 lg:self-start">
        <h1 className="sr-only">Lap analyser</h1>
        <form className="grid gap-4 sm:grid-cols-2 lg:grid-cols-1" onSubmit={(e) => e.preventDefault()}>
          <Select
            label="Season"
            value={String(r.season.year)}
            onChange={(v) => {
              const season = index.seasons.find((s) => s.year === Number(v))!;
              const ev = matchEvent(season, r.event);
              update({ y: season.year, e: ev?.slug, oy: params.oy === season.year ? undefined : params.oy });
            }}
            options={sortedSeasons(index).filter((s) => s.events.length).map((s) => ({ value: String(s.year), label: String(s.year) }))}
          />
          <Select
            label="Grand Prix"
            value={r.event.slug}
            onChange={(v) => update({ e: v })}
            options={r.season.events.map((e) => ({ value: e.slug, label: `R${e.round} ${e.name}` }))}
          />
          <Select
            label="Session"
            value={r.session.key}
            onChange={(v) => update({ s: v })}
            options={r.event.sessions.map((s) => ({ value: s.key, label: s.name }))}
          />
          <DriverSelect
            label="Reference lap"
            drivers={refMeta?.drivers}
            fastest={refMeta?.fastest}
            value={params.ref === FASTEST ? FASTEST : refDriver?.code}
            onChange={(v) => update({ ref: v })}
          />
          <Select
            label="Compare with season"
            value={r.other ? String(r.other.season.year) : ""}
            onChange={(v) => update({ oy: v ? Number(v) : undefined, oth: undefined })}
            options={[
              { value: "", label: `Same season (${r.season.year})` },
              ...otherYears.map((y) => ({ value: String(y), label: `${y} ${r.event.name}` })),
            ]}
            help={otherYears.length ? undefined : "No other season of this event is available."}
          />
          <DriverSelect
            label={crossSeason ? `Compared lap (${r.other!.season.year})` : "Compared lap"}
            drivers={othMeta?.drivers}
            fastest={othMeta?.fastest}
            value={params.oth === FASTEST ? FASTEST : othDriver?.code}
            onChange={(v) => update({ oth: v })}
          />
        </form>
        <p className="mt-5 text-xs leading-relaxed text-muted">
          Each driver&apos;s fastest lap in the session. Delta = compared minus reference: negative means the compared
          lap is ahead.
        </p>
      </aside>

      <section aria-label="Results" className="min-w-0">
        <header className="mb-6">
          <p className="text-sm text-muted">
            {r.season.year} {r.event.name}, {r.session.name}
            {r.other && ` vs ${r.other.season.year}`}
          </p>
          <h2 className="mt-1 text-2xl font-semibold tracking-tight md:text-3xl">
            {sides ? (
              <>
                <span style={{ color: sides[0].color }}>{sides[0].label}</span>
                <span className="text-muted"> vs </span>
                <span style={{ color: sides[1].color }}>{sides[1].label}</span>
              </>
            ) : (
              <Skeleton className="h-8 w-56" />
            )}
          </h2>
          {sides && (
            <p className="mt-1 font-mono text-sm text-muted tabular">
              {lapTime(sides[0].driver.lap_time_s)} (L{sides[0].driver.lap_number}) / {lapTime(sides[1].driver.lap_time_s)} (L{sides[1].driver.lap_number})
            </p>
          )}
        </header>

        <Tabs value={params.tab} onChange={(tab) => setParams({ ...params, tab }, false)} />

        <div id={`panel-${params.tab}`} role="tabpanel" aria-labelledby={`tab-${params.tab}`} className="pt-6">
          {loadError ? (
            <Notice tone="error">Could not load this session ({loadError}). Try another session or reload the page.</Notice>
          ) : !sides ? (
            <LoadingPanel />
          ) : params.tab === "compare" ? (
            <CompareTab key={`${r.session.path}|${r.other?.session.path}|${sides[0].driver.code}|${sides[1].driver.code}`} reference={sides[0]} compared={sides[1]} crossSeason={crossSeason} />
          ) : (
            <RatingTab sides={sides} />
          )}
        </div>
      </section>
    </div>
  );
}

interface Option { value: string; label: string }

function Select({ label, value, options, onChange, help, disabled }: {
  label: string; value: string; options: Option[]; onChange: (v: string) => void; help?: string; disabled?: boolean;
}) {
  const id = `sel-${label.toLowerCase().replace(/\W+/g, "-")}`;
  return (
    <div className="grid gap-1.5">
      <label htmlFor={id} className="text-xs text-muted">{label}</label>
      <select
        id={id}
        value={value}
        disabled={disabled}
        onChange={(e) => onChange(e.target.value)}
        aria-describedby={help ? `${id}-help` : undefined}
        className="h-10 w-full rounded-lg border border-line bg-panel px-3 text-sm text-fg hover:border-muted disabled:opacity-60"
      >
        {options.map((o) => <option key={o.value} value={o.value}>{o.label}</option>)}
      </select>
      {help && <p id={`${id}-help`} className="text-xs text-muted">{help}</p>}
    </div>
  );
}

function DriverSelect({ label, drivers, fastest, value, onChange }: {
  label: string; drivers?: DriverEntry[]; fastest?: string; value?: string; onChange: (v: string) => void;
}) {
  if (!drivers) return <Select label={label} value="" options={[{ value: "", label: "Loading drivers..." }]} onChange={() => {}} disabled />;
  const options = [
    { value: FASTEST, label: `★ Fastest (${fastest ?? "?"})` },
    ...drivers.map((d, i) => ({
      value: d.code,
      label: `P${d.position ?? i + 1}  ${d.code}  ${lapTime(d.lap_time_s)}${d.team ? `  ${d.team}` : ""}`,
    })),
  ];
  return <Select label={label} value={value ?? ""} options={options} onChange={onChange} />;
}

const TABS: { id: Tab; label: string }[] = [
  { id: "compare", label: "Compare" },
  { id: "rating", label: "Rating" },
];

function Tabs({ value, onChange }: { value: Tab; onChange: (t: Tab) => void }) {
  const refs = useRef<(HTMLButtonElement | null)[]>([]);
  function key(e: KeyboardEvent, i: number) {
    if (e.key !== "ArrowRight" && e.key !== "ArrowLeft") return;
    e.preventDefault();
    const j = (i + (e.key === "ArrowRight" ? 1 : TABS.length - 1)) % TABS.length;
    onChange(TABS[j].id);
    refs.current[j]?.focus();
  }
  return (
    <div role="tablist" aria-label="View" className="flex gap-1 border-b border-line">
      {TABS.map((t, i) => {
        const on = t.id === value;
        return (
          <button
            key={t.id}
            ref={(el) => { refs.current[i] = el; }}
            id={`tab-${t.id}`}
            type="button"
            role="tab"
            aria-selected={on}
            aria-controls={`panel-${t.id}`}
            tabIndex={on ? 0 : -1}
            onClick={() => onChange(t.id)}
            onKeyDown={(e) => key(e, i)}
            className={`-mb-px border-b-2 px-4 py-2.5 text-sm font-medium transition-colors ${
              on ? "border-accent text-fg" : "border-transparent text-muted hover:text-fg"
            }`}
          >
            {t.label}
          </button>
        );
      })}
    </div>
  );
}

function LoadingPanel() {
  return (
    <div className="grid gap-4" aria-busy="true" aria-label="Loading lap data">
      <div className="grid grid-cols-2 gap-4 md:grid-cols-4">
        {[0, 1, 2, 3].map((i) => <Skeleton key={i} className="h-14" />)}
      </div>
      <Skeleton className="h-40" />
      <div className="grid gap-4 xl:grid-cols-[minmax(0,1fr)_340px]">
        <Skeleton className="h-80" />
        <Skeleton className="h-80" />
      </div>
    </div>
  );
}

function LoadingLayout() {
  return (
    <div className="grid gap-8 lg:grid-cols-[260px_minmax(0,1fr)]">
      <div className="grid gap-4">
        {[0, 1, 2, 3, 4, 5].map((i) => <Skeleton key={i} className="h-14" />)}
      </div>
      <div className="grid content-start gap-4">
        <Skeleton className="h-10 w-72" />
        <LoadingPanel />
      </div>
    </div>
  );
}
