import { describe, expect, it } from "vitest";
import {
  align,
  compare,
  compareCorners,
  cornerTable,
  gainPer100m,
  roundHalfEven,
  summarise,
  type Lap,
} from "@/lib/analysis";
import { decodeBinary } from "@/lib/data";
import type { CornerPoints } from "@/lib/types";

function lap(driver: string, samples: number, step: number, length: number, speedKmh: number): Lap {
  const time = new Float64Array(samples);
  const speed = new Float64Array(samples).fill(speedKmh);
  const gear = new Float64Array(samples);
  for (let i = 0; i < samples; i++) {
    time[i] = (i * step) / (speedKmh / 3.6);
    gear[i] = 1 + Math.floor((i / samples) * 8);
  }
  const flat = new Float64Array(samples).fill(100);
  return {
    driver,
    step_m: step,
    length_m: length,
    samples,
    channels: { time, speed, throttle: flat, brake: new Float64Array(samples), gear, rpm: flat },
  };
}

describe("roundHalfEven", () => {
  it("rounds like numpy", () => {
    expect([0.5, 1.5, 2.5, -0.5, -1.5, 2.4, 2.6].map(roundHalfEven)).toEqual([0, 2, 2, -0, -2, 2, 3]);
  });
});

describe("decodeBinary", () => {
  it("reads little-endian columns, scales and maps sentinels to NaN", () => {
    const buf = new ArrayBuffer(16);
    const v = new DataView(buf);
    v.setFloat32(0, 1.5, true);
    v.setFloat32(4, NaN, true);
    v.setUint16(8, 3105, true);
    v.setUint16(10, 0xffff, true);
    v.setUint8(12, 7);
    v.setUint8(13, 255);
    const cols = decodeBinary(buf, [
      { name: "a.time", dtype: "f32", offset: 0, count: 2, scale: 1 },
      { name: "a.speed", dtype: "u16", offset: 8, count: 2, scale: 0.1 },
      { name: "a.gear", dtype: "u8", offset: 12, count: 2 },
    ]);
    expect(Array.from(cols.get("a.time")!)).toEqual([1.5, NaN]);
    expect(cols.get("a.speed")![0]).toBeCloseTo(310.5, 6);
    expect(cols.get("a.speed")![1]).toBeNaN();
    expect(Array.from(cols.get("a.gear")!)).toEqual([7, NaN]);
  });

  it("rejects columns past the end of the buffer", () => {
    expect(() => decodeBinary(new ArrayBuffer(4), [{ name: "x", dtype: "f32", offset: 0, count: 2 }])).toThrow();
  });
});

describe("compare", () => {
  it("diffs laps on the same grid without resampling", () => {
    const ref = lap("A", 201, 5, 1000, 200);
    const oth = lap("B", 201, 5, 1000, 180);
    const cmp = compare(ref, oth);
    expect(cmp.other).toBe(oth);
    expect(cmp.delta[0]).toBe(0);
    expect(summarise(cmp).final_delta_s).toBeCloseTo(1000 / 50 - 1000 / (200 / 3.6), 9);
  });

  it("rescales a lap of a different length onto the reference grid", () => {
    const ref = lap("A", 201, 5, 1000, 200);
    // Same pace over a track 10 % longer: after rescaling, its time trace is 1.1x the reference.
    const oth = lap("B", 221, 5, 1100, 200);
    const aligned = align(ref, oth);
    expect(aligned.samples).toBe(201);
    expect(aligned.length_m).toBe(1000);
    expect(aligned.channels.time[200]).toBeCloseTo(ref.channels.time[200] * 1.1, 9);
    expect(aligned.channels.gear[200]).toBe(8);
  });

  it("extends time linearly past the last sample of a stretched lap", () => {
    const ref = lap("A", 201, 5, 1000, 200);
    const oth = lap("B", 200, 5, 997, 200); // grid ends at 995 m, short of the reference's 1000 m
    const aligned = align(ref, oth);
    const t = aligned.channels.time;
    expect(t[200] - t[199]).toBeCloseTo(t[199] - t[198], 9);
  });
});

describe("cornerTable / compareCorners", () => {
  const ref = lap("A", 201, 5, 1000, 200);
  const oth = lap("B", 201, 5, 1000, 190);
  const cmp = compare(ref, oth);
  const segs = [
    { name: "T1", start_m: 0, end_m: 402.5 },
    { name: "T2", start_m: 402.5, end_m: 1000 },
  ];

  it("sector deltas sum to the final delta", () => {
    const rows = cornerTable(cmp, segs);
    expect(rows.map((r) => r.end_m)).toEqual([400, 1000]); // 80.5 rounds half to even
    expect(rows[0].delta_s + rows[1].delta_s).toBeCloseTo(summarise(cmp).final_delta_s, 12);
    expect(rows[0].ref_min_speed).toBe(200);
  });

  it("phase deltas sum to the segment delta and clamp reversed bounds", () => {
    const pts = { name: "T1", bounds_m: [100, 90, 200, 300] } as CornerPoints;
    const [row] = compareCorners(cmp, segs, [pts]);
    const p = row.phase_delta_s!;
    expect(p.braking).toBe(0); // 90 m is before entry at 100 m
    const sum = p.approach + p.braking + p.mid + p.exit + p.straight;
    expect(sum).toBeCloseTo(cornerTable(cmp, segs)[0].delta_s, 12);
  });

  it("track gain is negative where the compared lap is faster", () => {
    const g = gainPer100m(compare(oth, ref).delta, 5);
    expect(g[100]).toBeLessThan(0);
  });
});
