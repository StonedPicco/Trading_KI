// Typed client for the backend REST API. All market data carries provenance (live/delayed/demo).

// Empty = same origin (the one-click start serves the dashboard from the API server).
// `npm run dev` sets NEXT_PUBLIC_API_URL via .env.development.
export const API_URL = process.env.NEXT_PUBLIC_API_URL ?? "";
const API_TOKEN = process.env.NEXT_PUBLIC_API_TOKEN;

export type DataKind = "live" | "delayed" | "historical" | "demo";
export type Timeframe = "1Min" | "5Min" | "15Min" | "1Hour" | "1Day" | "1Week";

export interface Provenance {
  provider: string;
  feed: string;
  data_kind: DataKind;
  is_realtime: boolean;
  delay_minutes: number;
  as_of: string | null;
  notes: string[];
}

export interface Health {
  status: string;
  env: string;
  market_phase: string;
  provenance: Provenance;
  demo_mode: boolean;
  llm: { enabled: boolean; model: string | null };
  news_providers: string[];
  order_execution: string;
}

export interface Bar {
  time: number;
  open: number;
  high: number;
  low: number;
  close: number;
  volume: number;
}

export interface Point {
  time: number;
  value: number | null; // null = gap (renders as whitespace)
}

export interface OverviewItem {
  symbol: string;
  sector_etf: string | null;
  price?: number;
  prev_close?: number | null;
  change_pct?: number | null;
  volume_today?: number;
  rvol?: number | null;
  last_bar?: string;
  news_24h?: number;
  error?: string;
  signal?: { id: string; outcome: string; label: string; created_at: string; data_kind: DataKind };
}

export interface Factor {
  key: string;
  direction: number;
  weight: number;
  observation: string;
  interpretation: string;
}

export interface Scenario {
  outcome: string;
  label: string;
  bias: "long" | "short" | "neutral";
  reference_price: number;
  entry_zone: [number, number] | null;
  stop: number | null;
  targets: number[];
  reward_risk: number | null;
  confirmation: string[];
  invalidation: string | null;
  invalidation_price: number | null;
  evidence_score: number;
  evidence_note: string;
  factors_for: Factor[];
  factors_against: Factor[];
  risks: string[];
  reasons: string[];
  mtf_conflict: boolean;
  engine_version: string;
}

export interface NewsAssessment {
  news_id: string;
  category: string;
  relevance: string;
  direction: string;
  is_new_information: boolean;
  verifiable_facts: string[];
  reasoning: string;
}

export interface Narrative {
  summary: string;
  bull_case: string[];
  bear_case: string[];
  key_risks: string[];
  market_context: string;
  news_assessments: NewsAssessment[];
  engine_agreement: string;
  disagreement_reason: string;
  uncertainty: string[];
  meta: {
    generated_by: string;
    model: string | null;
    validation?: { ok: boolean; errors: string[]; warnings: string[] };
    llm_error?: string;
  };
}

export interface HorizonStats {
  horizon_min: number;
  n: number;
  mean_pct: number | null;
  median_pct: number | null;
  q25_pct: number | null;
  q75_pct: number | null;
  hit_rate: number | null;
  ci_low: number | null;
  ci_high: number | null;
  base_hit_rate: number | null;
  base_mean_pct: number | null;
  distinguishable: boolean;
}

export interface Similarity {
  status: string;
  query_ts?: string | null;
  query_session?: string | null;
  candidates?: number;
  n_analogs?: number;
  regime_filter?: string | null;
  match_quality?: number | null;
  horizons?: HorizonStats[];
  mfe_mean_pct?: number | null;
  mae_mean_pct?: number | null;
  analogs?: Array<Record<string, number | string | null>>;
  statistically_usable?: boolean;
  limitations?: string[];
}

export interface Zone {
  low: number;
  high: number;
  mid: number;
  touches: number;
  strength: number;
  kind: "support" | "resistance";
  sources: string[];
}

export interface Facts {
  symbol: string;
  as_of: string;
  market_phase: string;
  price: number;
  data_quality: { ok: boolean; issues: string[]; info: string[]; last_bar_ts?: string };
  trends?: Record<string, { direction: string; structure: string; rsi14: number | null }>;
  intraday?: Record<string, unknown>;
  key_levels?: Record<string, number | null>;
  zones?: Zone[];
  relative_strength?: Record<string, { benchmark: string; rs_intraday: number | null; rs_5d: number | null }>;
  volatility?: { regime: string; atr_pct: number | null };
  liquidity?: { level: string; note: string | null };
  similarity?: Similarity;
}

export interface Outcome {
  horizon_min: number;
  ret_pct: number | null;
  mfe_pct: number | null;
  mae_pct: number | null;
  result: string;
  r_multiple: number | null;
}

export interface Analysis {
  id: string;
  symbol: string;
  created_at: string;
  data_as_of: string;
  trigger: string;
  outcome: string;
  bias: string;
  reference_price: number;
  market_phase: string;
  data_kind: DataKind;
  scenario: Scenario;
  narrative: Narrative;
  provenance: Provenance;
  sources: Array<{ type: string; title?: string; url?: string | null; provider?: string; published_at?: string; source?: string | null; data_kind?: string; as_of?: string }>;
  input_hash: string;
  engine_version: string;
  llm_model: string | null;
  facts?: Facts;
  outcomes?: Outcome[];
}

export interface NewsItem {
  id: string;
  headline: string;
  summary: string | null;
  source: string | null;
  published_at: string;
  first_seen_at: string;
  url: string | null;
  kind: string;
  symbols: string[];
  is_duplicate: boolean;
  reaction: Record<string, number | string | boolean | null> | null;
  direction: string;
  confirmed_by_price: boolean;
  assessment: NewsAssessment | null;
}

export interface NotificationItem {
  id: number;
  symbol: string | null;
  kind: string;
  severity: "info" | "warn" | "alert";
  title: string;
  body: string;
  created_at: string;
  read: boolean;
}

export interface Performance {
  horizon_min: number;
  n: number;
  note?: string;
  data_kinds?: string[];
  engine_directional?: { n: number; mean_signed_ret_pct: number | null; hit_rate: number | null };
  baseline_always_long?: { n: number; mean_ret_pct: number; hit_rate: number };
  baseline_momentum_5m?: { n: number; mean_signed_ret_pct: number | null };
  by_outcome?: Array<{ outcome: string; n: number; mean_ret_pct: number | null; hit_target: number | null; mean_r: number | null }>;
  calibration?: Array<{ score_bucket: string; n: number; hit_rate: number }>;
  calibrated?: boolean;
}

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  const headers: Record<string, string> = { "Content-Type": "application/json" };
  if (API_TOKEN) headers.Authorization = `Bearer ${API_TOKEN}`;
  const res = await fetch(`${API_URL}${path}`, { ...init, headers, cache: "no-store" });
  if (!res.ok) {
    let detail = res.statusText;
    try {
      detail = ((await res.json()) as { detail?: string }).detail ?? detail;
    } catch {
      /* non-JSON error body */
    }
    throw new Error(`${res.status}: ${detail}`);
  }
  return (res.status === 204 ? undefined : await res.json()) as T;
}

export const api = {
  health: () => request<Health>("/api/health"),
  overview: () => request<OverviewItem[]>("/api/watchlist/overview"),
  addSymbol: (symbol: string) =>
    request<{ symbol: string }>("/api/watchlist", { method: "POST", body: JSON.stringify({ symbol }) }),
  removeSymbol: (symbol: string) => request<void>(`/api/watchlist/${symbol}`, { method: "DELETE" }),
  bars: (symbol: string, tf: Timeframe, days: number) =>
    request<{ bars: Bar[]; provenance: Provenance }>(`/api/symbols/${symbol}/bars?tf=${tf}&days=${days}`),
  indicators: (symbol: string, tf: Timeframe, days: number) =>
    request<{ series: Record<string, Point[]> }>(`/api/symbols/${symbol}/indicators?tf=${tf}&days=${days}`),
  latest: (symbol: string) => request<Analysis>(`/api/symbols/${symbol}/analyses/latest`),
  analyze: (symbol: string) => request<Analysis>(`/api/symbols/${symbol}/analyze`, { method: "POST" }),
  history: (symbol?: string, limit = 100) =>
    request<Analysis[]>(`/api/analyses?limit=${limit}${symbol ? `&symbol=${symbol}` : ""}`),
  news: (symbol: string) => request<{ enabled: boolean; providers: string[]; items: NewsItem[] }>(`/api/symbols/${symbol}/news`),
  performance: (horizon = 60) => request<Performance>(`/api/performance?horizon=${horizon}`),
  notifications: () => request<NotificationItem[]>("/api/notifications?limit=50"),
  markRead: (id: number) => request<void>(`/api/notifications/${id}/read`, { method: "POST" }),
};

export function wsUrl(): string {
  const base = API_URL
    ? API_URL.replace(/^http/, "ws")
    : `${window.location.protocol === "https:" ? "wss" : "ws"}://${window.location.host}`;
  return `${base}/ws${API_TOKEN ? `?token=${encodeURIComponent(API_TOKEN)}` : ""}`;
}
