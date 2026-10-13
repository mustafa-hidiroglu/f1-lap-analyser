// Parity with the Python pipeline: LEC (reference) vs NOR, 2024 Italian GP qualifying.
// The fixture is `f1lap` compare output on a 1 m grid; the web data is a 5 m grid, hence the
// tolerances. Needs the exported session in public/data (produced by tools/web_export.py).

import { existsSync, readFileSync } from "node:fs";
import { fileURLToPath } from "node:url";
import { describe, expect, it } from "vitest";
import { compare, compareCorners, cornerTable, PHASES, sessionLap, summarise } from "@/lib/analysis";
import { decodeBinary } from "@/lib/data";
import type { LoadedSession, SessionFile } from "@/lib/types";
import fixture from "./fixtures/compare-fixture-monza2024q-lec-nor.json";

const dir = fileURLToPath(new URL("../public/data/2024/16-italian-grand-prix/", import.meta.url));
const hasData = existsSync(`${dir}Q.json`) && existsSync(`${dir}Q.bin`);

function load(): LoadedSession {
  const meta = JSON.parse(readFileSync(`${dir}Q.json`, "utf8")) as SessionFile;
  const buf = readFileSync(`${dir}${meta.binary.file}`);
  const ab = buf.buffer.slice(buf.byteOffset, buf.byteOffset + buf.byteLength);
  return { meta, columns: decodeBinary(ab, meta.binary.columns) };
}

if (!hasData) {
  console.warn(
    "parity test skipped: web/public/data/2024/16-italian-grand-prix/Q.{json,bin} not found. " +
      "Run `uv run python tools/web_export.py` first.",
  );
}

describe.skipIf(!hasData)("parity with Python compare (Monza 2024 Q, LEC vs NOR)", () => {
  const session = hasData ? load() : (null as unknown as LoadedSession);
  const cmp = hasData ? compare(sessionLap(session, "LEC"), sessionLap(session, "NOR")) : null!;

  it("final delta", () => {
    expect(summarise(cmp).final_delta_s).toBeCloseTo(fixture.final_delta_s, 1);
    expect(Math.abs(summarise(cmp).final_delta_s - fixture.final_delta_s)).toBeLessThan(0.02);
  });

  it("sector deltas within 0.02 s", () => {
    const rows = cornerTable(cmp, session.meta.circuit.segments);
    expect(rows.map((r) => r.name)).toEqual(fixture.sectors.map((s) => s.name));
    const errs = rows.map((r, i) => Math.abs(r.delta_s - fixture.sectors[i].delta_s));
    console.info(`max sector delta error: ${Math.max(...errs).toFixed(4)} s`);
    errs.forEach((e, i) => expect(e, rows[i].name).toBeLessThan(0.02));
  });

  it("phase deltas within 0.03 s", () => {
    const rows = compareCorners(cmp, session.meta.circuit.segments, session.meta.laps.LEC.corners);
    expect(rows.map((r) => r.name)).toEqual(fixture.corners.map((c) => c.name));
    let worst = 0;
    rows.forEach((r, i) => {
      const want = fixture.corners[i].phase_delta_s as Record<string, number>;
      expect(r.phase_delta_s, r.name).not.toBeNull();
      for (const p of PHASES) {
        const err = Math.abs(r.phase_delta_s![p] - want[p]);
        worst = Math.max(worst, err);
        expect(err, `${r.name} ${p}`).toBeLessThan(0.03);
      }
    });
    console.info(`max phase delta error: ${worst.toFixed(4)} s`);
  });
});
