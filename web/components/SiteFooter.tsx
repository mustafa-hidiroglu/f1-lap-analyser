import { FASTF1_URL, REPO_URL } from "@/lib/links";

export function SiteFooter() {
  return (
    <footer className="border-t border-line/70 text-sm text-muted">
      <div className="mx-auto grid max-w-[1400px] gap-6 px-4 py-10 md:grid-cols-[2fr_1fr] md:px-8">
        <p className="max-w-[70ch] leading-relaxed">
          Unofficial; not associated with Formula 1 or any of its companies. F1, FORMULA ONE and
          related marks are trademarks of Formula One Licensing B.V. Timing data via{" "}
          <a href={FASTF1_URL} className="underline decoration-line underline-offset-4 hover:text-fg">
            FastF1
          </a>
          .
        </p>
        <p className="md:text-right">
          MIT licensed.{" "}
          <a href={REPO_URL} className="underline decoration-line underline-offset-4 hover:text-fg">
            Source on GitHub
          </a>
        </p>
      </div>
    </footer>
  );
}
