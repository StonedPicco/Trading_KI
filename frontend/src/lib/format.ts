// Formatting helpers (pure, unit tested).

const NY = "America/New_York";

/** Offset of America/New_York from UTC in seconds at the given instant (negative in the US). */
export function nyOffsetSeconds(unixSeconds: number): number {
  const d = new Date(unixSeconds * 1000);
  const parts = new Intl.DateTimeFormat("en-US", {
    timeZone: NY,
    hourCycle: "h23",
    year: "numeric",
    month: "2-digit",
    day: "2-digit",
    hour: "2-digit",
    minute: "2-digit",
    second: "2-digit",
  }).formatToParts(d);
  const get = (t: string) => Number(parts.find((p) => p.type === t)?.value ?? 0);
  const asUtc = Date.UTC(get("year"), get("month") - 1, get("day"), get("hour"), get("minute"), get("second"));
  return Math.round((asUtc - d.getTime()) / 1000);
}

/** Lightweight Charts renders timestamps as UTC; shift so the axis shows New York time. */
export function toChartTime(unixSeconds: number): number {
  return unixSeconds + nyOffsetSeconds(unixSeconds);
}

export function fmtPrice(v: number | null | undefined, digits = 2): string {
  if (v === null || v === undefined || !Number.isFinite(v)) return "–";
  return v.toLocaleString("de-AT", { minimumFractionDigits: digits, maximumFractionDigits: digits });
}

export function fmtPct(v: number | null | undefined, digits = 2, signed = true): string {
  if (v === null || v === undefined || !Number.isFinite(v)) return "–";
  const s = v.toLocaleString("de-AT", { minimumFractionDigits: digits, maximumFractionDigits: digits });
  return `${signed && v > 0 ? "+" : ""}${s} %`;
}

export function fmtCompact(v: number | null | undefined): string {
  if (v === null || v === undefined || !Number.isFinite(v)) return "–";
  return new Intl.NumberFormat("de-AT", { notation: "compact", maximumFractionDigits: 1 }).format(v);
}

export function fmtTime(iso: string | null | undefined, withDate = false): string {
  if (!iso) return "–";
  const d = new Date(iso);
  return d.toLocaleString("de-AT", {
    timeZone: NY,
    hour: "2-digit",
    minute: "2-digit",
    ...(withDate ? { day: "2-digit", month: "2-digit" } : {}),
  }) + " ET";
}

export function ago(iso: string, now: number = Date.now()): string {
  const s = Math.max(0, Math.round((now - new Date(iso).getTime()) / 1000));
  if (s < 60) return `vor ${s}s`;
  if (s < 3600) return `vor ${Math.floor(s / 60)} Min.`;
  if (s < 86400) return `vor ${Math.floor(s / 3600)} Std.`;
  return `vor ${Math.floor(s / 86400)} T.`;
}

export const OUTCOME_TONE: Record<string, "bull" | "bear" | "neutral" | "warn" | "muted"> = {
  long_entry: "bull",
  bullish_setup: "bull",
  short_entry: "bear",
  bearish_setup: "bear",
  watch: "neutral",
  no_trade: "muted",
  invalidated: "warn",
  insufficient_data: "warn",
};

export const PHASE_LABEL: Record<string, string> = {
  pre_market: "Pre-Market",
  regular: "Regular Session",
  after_hours: "After-Hours",
  closed: "Markt geschlossen",
};

export function dataKindLabel(kind: string, delay = 0): string {
  switch (kind) {
    case "live":
      return "LIVE";
    case "delayed":
      return `VERZÖGERT ${delay} Min.`;
    case "historical":
      return "HISTORISCH";
    case "demo":
      return "DEMO – SIMULIERT";
    default:
      return kind.toUpperCase();
  }
}
