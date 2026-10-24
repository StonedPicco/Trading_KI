import { describe, expect, it } from "vitest";
import { ago, dataKindLabel, fmtPct, fmtPrice, nyOffsetSeconds, toChartTime } from "./format";

describe("time zone handling", () => {
  it("uses EDT (-4h) in October and EST (-5h) in December", () => {
    const oct = Date.UTC(2026, 9, 22, 17, 45) / 1000;
    const dec = Date.UTC(2026, 11, 1, 17, 45) / 1000;
    expect(nyOffsetSeconds(oct)).toBe(-4 * 3600);
    expect(nyOffsetSeconds(dec)).toBe(-5 * 3600);
  });

  it("shifts chart time to New York wall clock", () => {
    const open = Date.UTC(2026, 9, 22, 13, 30) / 1000; // 09:30 ET
    expect(new Date(toChartTime(open) * 1000).getUTCHours()).toBe(9);
  });
});

describe("formatters", () => {
  it("handles missing values", () => {
    expect(fmtPrice(null)).toBe("–");
    expect(fmtPct(Number.NaN)).toBe("–");
  });

  it("signs positive percentages", () => {
    expect(fmtPct(1.5)).toMatch(/^\+1,50/);
    expect(fmtPct(-1.5)).toMatch(/^-1,50/);
  });

  it("labels demo data unmistakably", () => {
    expect(dataKindLabel("demo")).toContain("SIMULIERT");
    expect(dataKindLabel("delayed", 15)).toContain("15");
  });

  it("formats relative time", () => {
    const now = Date.UTC(2026, 9, 22, 12, 0);
    expect(ago(new Date(now - 90_000).toISOString(), now)).toBe("vor 1 Min.");
  });
});
