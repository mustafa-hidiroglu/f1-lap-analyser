import type { BinColumn, Dtype, IndexFile, LoadedSession, SessionFile } from "./types";

export const DATA_ROOT = "/data";

const SIZE: Record<Dtype, number> = { f32: 4, f64: 8, u8: 1, u16: 2, i16: 2, i32: 4 };
// Integer columns mark missing values with the dtype's max.
const MISSING: Partial<Record<Dtype, number>> = { u8: 0xff, u16: 0xffff };

/** Decode one little-endian SoA column; missing values become NaN, then `raw * scale`. */
export function decodeColumn(view: DataView, col: BinColumn): Float64Array {
  const out = new Float64Array(col.count);
  const size = SIZE[col.dtype];
  if (size === undefined) throw new Error(`unsupported dtype ${col.dtype} for ${col.name}`);
  if (col.offset + col.count * size > view.byteLength) {
    throw new Error(`column ${col.name} runs past the end of the binary`);
  }
  const scale = col.scale ?? 1;
  const missing = MISSING[col.dtype];
  for (let i = 0; i < col.count; i++) {
    const at = col.offset + i * size;
    let raw: number;
    switch (col.dtype) {
      case "f32": raw = view.getFloat32(at, true); break;
      case "f64": raw = view.getFloat64(at, true); break;
      case "u8": raw = view.getUint8(at); break;
      case "u16": raw = view.getUint16(at, true); break;
      case "i16": raw = view.getInt16(at, true); break;
      case "i32": raw = view.getInt32(at, true); break;
    }
    out[i] = raw === missing ? NaN : raw * scale;
  }
  return out;
}

export function decodeBinary(buffer: ArrayBuffer, columns: BinColumn[]): Map<string, Float64Array> {
  const view = new DataView(buffer);
  return new Map(columns.map((c) => [c.name, decodeColumn(view, c)]));
}

/** Directory of a session JSON path, e.g. "2024/16-italian-grand-prix". */
export function sessionDir(path: string): string {
  const i = path.lastIndexOf("/");
  return i < 0 ? "" : path.slice(0, i);
}

async function fetchOk(url: string): Promise<Response> {
  const res = await fetch(url);
  if (!res.ok) throw new Error(`${url}: HTTP ${res.status}`);
  return res;
}

let indexPromise: Promise<IndexFile> | null = null;

export function loadIndex(): Promise<IndexFile> {
  indexPromise ??= fetchOk(`${DATA_ROOT}/index.json`).then((r) => r.json() as Promise<IndexFile>);
  indexPromise.catch(() => (indexPromise = null));
  return indexPromise;
}

const sessions = new Map<string, Promise<LoadedSession>>();

/** Session JSON + its .bin, fetched once per path and kept for the page's lifetime. */
export function loadSession(path: string): Promise<LoadedSession> {
  let p = sessions.get(path);
  if (!p) {
    p = (async () => {
      const meta = (await (await fetchOk(`${DATA_ROOT}/${path}`)).json()) as SessionFile;
      const dir = sessionDir(path);
      const bin = await (await fetchOk(`${DATA_ROOT}/${dir ? `${dir}/` : ""}${meta.binary.file}`)).arrayBuffer();
      return { meta, columns: decodeBinary(bin, meta.binary.columns) };
    })();
    p.catch(() => sessions.delete(path));
    sessions.set(path, p);
  }
  return p;
}
