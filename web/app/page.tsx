import Link from "next/link";
import { AppleLogo, ArrowRight, DownloadSimple, Info, WindowsLogo } from "@phosphor-icons/react/dist/ssr";
import { MiniLines } from "@/components/MiniLines";
import { TrackMap } from "@/components/TrackMap";
import { PHASES } from "@/lib/analysis";
import { delta, lapTime } from "@/lib/format";
import { loadHomePreview, type HomePreview } from "@/lib/home-preview";
import { MAC_DMG_URL, RELEASES_URL, WIN_EXE_URL } from "@/lib/links";

export default function Home() {
  const p = loadHomePreview();
  const analyseHref = p?.href ?? "/analyse";
  return (
    <>
      <Hero p={p} href={analyseHref} />
      <Downloads />
      <Features p={p} />
    </>
  );
}

function Hero({ p, href }: { p: HomePreview | null; href: string }) {
  return (
    <section className="mx-auto grid max-w-[1400px] items-center gap-12 px-4 pb-16 pt-12 md:px-8 lg:grid-cols-[5fr_6fr] lg:pb-24 lg:pt-20">
      <div className="max-w-xl">
        <h1 className="rise text-4xl font-semibold leading-[1.05] tracking-tighter md:text-5xl lg:text-6xl">
          See exactly where a lap was won.
        </h1>
        <p className="rise mt-6 max-w-[48ch] text-lg leading-relaxed text-muted" style={{ "--i": 1 } as React.CSSProperties}>
          Compare any two drivers&apos; fastest qualifying or race laps from 2024 to 2026, corner by corner, in
          your browser.
        </p>
        <div className="rise mt-9 flex flex-wrap gap-3" style={{ "--i": 2 } as React.CSSProperties}>
          <Link
            href={href}
            className="inline-flex items-center gap-2 whitespace-nowrap rounded-full bg-accent px-6 py-3 font-medium text-accent-ink transition-transform duration-200 hover:-translate-y-px active:translate-y-px"
          >
            Open the analyser <ArrowRight size={18} weight="bold" aria-hidden />
          </Link>
          <a
            href="#download"
            className="inline-flex items-center gap-2 whitespace-nowrap rounded-full border border-line px-6 py-3 font-medium text-fg transition-colors hover:border-muted"
          >
            Get the desktop app
          </a>
        </div>
      </div>

      <figure className="rise" style={{ "--i": 1 } as React.CSSProperties}>
        {p ? (
          <>
            <div className="rounded-2xl border border-line bg-panel p-4 md:p-6">
              <TrackMap
                id="hero-track"
                circuit={p.circuit}
                gain={p.gain}
                step={p.step}
                refColor={p.colors.ref}
                othColor={p.colors.oth}
                reveal
                title={`${p.event} ${p.year} ${p.session}: track coloured by whether ${p.ref.code} or ${p.oth.code} was faster`}
                className="mx-auto aspect-[4/3] max-h-[440px] w-full"
              />
            </div>
            <figcaption className="mt-4 flex flex-wrap items-baseline justify-between gap-x-6 gap-y-2 text-sm text-muted">
              <span>
                {p.event} {p.year}, {p.session.toLowerCase()}. Coloured by who was faster through each stretch.
              </span>
              <span className="flex items-center gap-4 font-mono tabular">
                <Swatch color={p.colors.ref} label={`${p.ref.code} ${lapTime(p.ref.lap_time_s)}`} />
                <Swatch color={p.colors.oth} label={`${p.oth.code} ${delta(p.finalDelta)}`} />
              </span>
            </figcaption>
          </>
        ) : (
          <div className="flex aspect-[4/3] items-center justify-center rounded-2xl border border-dashed border-line text-sm text-muted">
            Track preview appears once session data is exported.
          </div>
        )}
      </figure>
    </section>
  );
}

function Swatch({ color, label }: { color: string; label: string }) {
  return (
    <span className="inline-flex items-center gap-2 text-fg">
      <span aria-hidden className="h-[3px] w-4 rounded-full" style={{ background: color }} />
      {label}
    </span>
  );
}

function Downloads() {
  return (
    <section id="download" className="scroll-mt-8 border-y border-line/70 bg-panel/60">
      <div className="mx-auto grid max-w-[1400px] gap-10 px-4 py-16 md:px-8 lg:grid-cols-[6fr_5fr] lg:py-20">
        <div>
          <h2 className="text-3xl font-semibold tracking-tight md:text-4xl">Web or desktop</h2>
          <aside
            aria-label="What the web version covers"
            className="mt-8 rounded-2xl border border-accent/40 bg-bg p-6 md:p-8"
          >
            <p className="flex items-center gap-2 font-medium">
              <Info size={20} weight="bold" className="text-accent" aria-hidden />
              What&apos;s in each version
            </p>
            <dl className="mt-5 grid gap-6 sm:grid-cols-2">
              <div>
                <dt className="text-sm text-muted">In the browser</dt>
                <dd className="mt-2 leading-relaxed">
                  2024 to 2026 qualifying and races, using each driver&apos;s fastest lap.
                </dd>
              </div>
              <div>
                <dt className="text-sm text-muted">The desktop app adds</dt>
                <dd className="mt-2 leading-relaxed">
                  Every season FastF1 covers, every lap (not just the fastest), practice and sprint sessions,
                  and a ghost replay against the perfect lap.
                </dd>
              </div>
            </dl>
          </aside>
        </div>

        <div className="flex flex-col justify-end gap-3">
          <DownloadLink href={MAC_DMG_URL} icon={<AppleLogo size={22} weight="fill" aria-hidden />} title="macOS" detail="Apple silicon, .dmg" />
          <DownloadLink href={WIN_EXE_URL} icon={<WindowsLogo size={22} weight="fill" aria-hidden />} title="Windows" detail="64-bit installer, .exe" />
          <a href={RELEASES_URL} className="mt-1 inline-flex items-center gap-2 self-start text-sm text-muted underline decoration-line underline-offset-4 hover:text-fg">
            All releases <ArrowRight size={14} aria-hidden />
          </a>
          <p className="mt-2 max-w-[60ch] text-sm leading-relaxed text-muted">
            The builds are not code-signed. On first launch, macOS needs System Settings, Privacy &amp;
            Security, Open Anyway; Windows SmartScreen needs More info, then Run anyway.
          </p>
        </div>
      </div>
    </section>
  );
}

function DownloadLink({ href, icon, title, detail }: { href: string; icon: React.ReactNode; title: string; detail: string }) {
  return (
    <a
      href={href}
      className="group flex items-center gap-4 rounded-2xl border border-line bg-bg px-5 py-4 transition-colors hover:border-muted active:translate-y-px"
    >
      {icon}
      <span className="flex-1">
        <span className="block font-medium">Download for {title}</span>
        <span className="block text-sm text-muted">{detail}</span>
      </span>
      <DownloadSimple size={20} className="text-muted transition-colors group-hover:text-fg" aria-hidden />
    </a>
  );
}

function Features({ p }: { p: HomePreview | null }) {
  const corner = p?.corners.filter((c) => c.phase_delta_s).sort((a, b) => Math.abs(b.delta_s) - Math.abs(a.delta_s))[0];
  const summary = p?.perfect?.summary?.[0];
  return (
    <section className="mx-auto max-w-[1400px] px-4 py-16 md:px-8 lg:py-24">
      <h2 className="max-w-[24ch] text-3xl font-semibold tracking-tight md:text-4xl">What a lap comparison shows you</h2>
      <div className="mt-10 grid gap-4 md:grid-cols-3">
        <Cell className="md:col-span-2" title="Delta, metre by metre" body="Where the gap opens and closes, on a shared distance grid. Same session or the same track a season apart.">
          {p && (
            <MiniLines
              label={`Delta of ${p.oth.code} to ${p.ref.code} over the lap`}
              series={[{ values: p.delta, color: "var(--color-fg)" }]}
              zero
              height={110}
              className="mt-6 h-28 w-full"
            />
          )}
        </Cell>

        <Cell title="Corner phases" body="Each corner split into approach, braking, mid, exit and straight, so a loss has an address.">
          {p && corner?.phase_delta_s && (
            <PhaseBars p={p} name={corner.name} phases={corner.phase_delta_s} />
          )}
        </Cell>

        <Cell title="Synced traces" body="Speed, throttle, brake and gear under one crosshair, with the track map following along.">
          {p && (
            <MiniLines
              label={`Speed traces of ${p.ref.code} and ${p.oth.code}`}
              series={[
                { values: p.refSpeed, color: p.colors.ref },
                { values: p.othSpeed, color: p.colors.oth, dashed: p.colors.dashed },
              ]}
              height={110}
              className="mt-6 h-28 w-full"
            />
          )}
        </Cell>

        <Cell
          className="md:col-span-2 bg-gradient-to-br from-accent/[0.08] to-transparent"
          title="Rated against the perfect lap"
          body="A score against the field, time left against the driver's own best segments, and plain findings on where the perfect lap gains."
        >
          {p?.rating && (
            <div className="mt-6 grid items-end gap-6 sm:grid-cols-[auto_1fr]">
              <p className="font-mono tabular">
                <span className="block text-5xl font-semibold tracking-tight text-accent">{p.rating.score.toFixed(0)}</span>
                <span className="text-sm text-muted">{p.ref.code} score / 100</span>
              </p>
              {summary && <p className="max-w-[60ch] text-sm leading-relaxed text-muted">{summary}</p>}
            </div>
          )}
        </Cell>
      </div>
    </section>
  );
}

function Cell({ title, body, className = "", children }: { title: string; body: string; className?: string; children?: React.ReactNode }) {
  return (
    <article className={`flex flex-col justify-between rounded-2xl border border-line bg-panel p-6 md:p-8 ${className}`}>
      <div>
        <h3 className="text-lg font-medium">{title}</h3>
        <p className="mt-2 max-w-[52ch] text-sm leading-relaxed text-muted">{body}</p>
      </div>
      {children}
    </article>
  );
}

function PhaseBars({ p, name, phases }: { p: HomePreview; name: string; phases: Record<string, number> }) {
  const max = Math.max(0.01, ...PHASES.map((k) => Math.abs(phases[k])));
  return (
    <figure className="mt-6">
      <figcaption className="mb-3 text-xs text-muted">
        {name}, {p.oth.code} vs {p.ref.code}
      </figcaption>
      <ul className="grid gap-1.5 font-mono text-xs tabular">
        {PHASES.map((k) => {
          const v = phases[k];
          const w = (Math.abs(v) / max) * 50;
          return (
            <li key={k} className="grid grid-cols-[4.5rem_1fr_3.5rem] items-center gap-2">
              <span className="text-muted">{k}</span>
              <span className="relative h-2">
                <span aria-hidden className="absolute inset-y-0 left-1/2 w-px bg-line" />
                <span
                  aria-hidden
                  className="absolute inset-y-0 rounded-sm"
                  style={{
                    background: v < 0 ? p.colors.oth : p.colors.ref,
                    left: v < 0 ? `${50 - w}%` : "50%",
                    width: `${w}%`,
                  }}
                />
              </span>
              <span className="text-right">{delta(v)}</span>
            </li>
          );
        })}
      </ul>
    </figure>
  );
}
