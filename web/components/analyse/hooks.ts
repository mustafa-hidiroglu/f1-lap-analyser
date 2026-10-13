"use client";

import { useCallback, useEffect, useState, useSyncExternalStore } from "react";
import { loadIndex, loadSession } from "@/lib/data";
import { parseParams, toSearch, type Params } from "@/lib/selection";
import type { IndexFile, LoadedSession } from "@/lib/types";

// The URL is the single source of truth for the selection, so links and back/forward just work.
const listeners = new Set<() => void>();
function subscribe(cb: () => void) {
  listeners.add(cb);
  window.addEventListener("popstate", cb);
  return () => {
    listeners.delete(cb);
    window.removeEventListener("popstate", cb);
  };
}

export function useUrlParams(): [Params | null, (next: Params, push?: boolean) => void] {
  const search = useSyncExternalStore(subscribe, () => window.location.search, () => null);
  const params = search == null ? null : parseParams(search);
  const set = useCallback((next: Params, push = true) => {
    const url = `${window.location.pathname}${toSearch(next)}`;
    if (push) window.history.pushState(null, "", url);
    else window.history.replaceState(null, "", url);
    listeners.forEach((l) => l());
  }, []);
  return [params, set];
}

interface Async<T> {
  key: string;
  data?: T;
  error?: string;
}

function message(e: unknown): string {
  return e instanceof Error ? e.message : String(e);
}

export function useIndex(): { index?: IndexFile; error?: string; retry: () => void } {
  const [attempt, setAttempt] = useState(0);
  const [st, setSt] = useState<Async<IndexFile>>({ key: "" });
  useEffect(() => {
    let live = true;
    loadIndex().then(
      (data) => live && setSt({ key: String(attempt), data }),
      (e) => live && setSt({ key: String(attempt), error: message(e) }),
    );
    return () => { live = false; };
  }, [attempt]);
  return { index: st.data, error: st.error, retry: () => setAttempt((a) => a + 1) };
}

/** A session (JSON + binary), loaded lazily; `loading` while the path's data is in flight. */
export function useSession(path: string | undefined): { session?: LoadedSession; error?: string; loading: boolean } {
  const [st, setSt] = useState<Async<LoadedSession>>({ key: "" });
  useEffect(() => {
    if (!path) return;
    let live = true;
    loadSession(path).then(
      (data) => live && setSt({ key: path, data }),
      (e) => live && setSt({ key: path, error: message(e) }),
    );
    return () => { live = false; };
  }, [path]);
  const current = st.key === path;
  return {
    session: current ? st.data : undefined,
    error: current ? st.error : undefined,
    loading: !!path && !current,
  };
}
