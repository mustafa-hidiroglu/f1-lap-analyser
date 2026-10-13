import Link from "next/link";
import { REPO_URL } from "@/lib/links";

export function SiteHeader() {
  return (
    <header className="border-b border-line/70">
      <nav
        aria-label="Main"
        className="mx-auto flex h-16 max-w-[1400px] items-center justify-between gap-6 px-4 md:px-8"
      >
        <Link href="/" className="flex items-center gap-2.5 font-semibold tracking-tight">
          <span aria-hidden className="block h-3.5 w-3.5 rounded-[3px] bg-accent" />
          F1 Lap Analyser
        </Link>
        <ul className="flex items-center gap-5 text-sm text-muted">
          <li>
            <Link href="/analyse" className="hover:text-fg">Analyser</Link>
          </li>
          <li className="hidden sm:block">
            <Link href="/#download" className="hover:text-fg">Desktop app</Link>
          </li>
          <li>
            <a href={REPO_URL} className="hover:text-fg">GitHub</a>
          </li>
        </ul>
      </nav>
    </header>
  );
}
