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
          {/* Pulse mark (assets/brand/f1lap-icon.svg): one speed trace bending around the apex. */}
          <svg aria-hidden viewBox="20 72 222 108" className="h-4 w-auto">
            <path
              d="M28 86H64C90 86 96 166 120 166C148 166 166 86 198 86H228"
              fill="none"
              stroke="currentColor"
              strokeWidth="20"
              strokeLinecap="round"
              strokeLinejoin="round"
            />
            <circle cx="122" cy="126" r="14" fill="#E8352B" />
          </svg>
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
