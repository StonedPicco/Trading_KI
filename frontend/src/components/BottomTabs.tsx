"use client";

import { useEffect, useState } from "react";
import { api, type Analysis, type NewsItem, type Performance, type Similarity } from "@/lib/api";
import { OUTCOME_TONE, ago, fmtPct, fmtPrice, fmtTime } from "@/lib/format";

type Tab = "news" | "history" | "signals" | "performance";

export function BottomTabs({ symbol, analysis, history, refreshKey }: {
  symbol: string;
  analysis: Analysis | null;
  history: Analysis[];
  refreshKey: number;
}) {
  const [tab, setTab] = useState<Tab>("news");
  return (
    <div className="panel" style={{ minHeight: 0 }}>
      <div className="tabs">
        {([["news", "News Intelligence"], ["history", "Historische Analyse"], ["signals", "Signal History"],
          ["performance", "Ergebnisqualität"]] as Array<[Tab, string]>).map(([k, label]) => (
          <button key={k} className={tab === k ? "on" : ""} onClick={() => setTab(k)}>{label}</button>
        ))}
      </div>
      <div className="panel-body">
        {tab === "news" && <NewsTab symbol={symbol} refreshKey={refreshKey} />}
        {tab === "history" && <SimilarityTab sim={analysis?.facts?.similarity} demo={analysis?.data_kind === "demo"} />}
        {tab === "signals" && <SignalsTab history={history} />}
        {tab === "performance" && <PerformanceTab refreshKey={refreshKey} />}
      </div>
    </div>
  );
}

function NewsTab({ symbol, refreshKey }: { symbol: string; refreshKey: number }) {
  const [data, setData] = useState<{ enabled: boolean; providers: string[]; items: NewsItem[] } | null>(null);
  const [err, setErr] = useState<string | null>(null);
  useEffect(() => {
    api.news(symbol).then((d) => { setData(d); setErr(null); }).catch((e: Error) => setErr(e.message));
  }, [symbol, refreshKey]);
  if (err) return <div className="note warn">{err}</div>;
  if (!data) return <div className="empty">Lade …</div>;
  if (!data.enabled) {
    return <div className="note">Keine Nachrichtenquelle konfiguriert (Alpaca-Keys bzw. SEC_USER_AGENT setzen). Es werden keine Nachrichten simuliert.</div>;
  }
  if (data.items.length === 0) return <div className="empty">Keine Meldungen in den letzten 72 Stunden ({data.providers.join(", ")}).</div>;
  return (
    <>
      {data.items.map((n) => {
        const r = n.reaction ?? {};
        return (
          <div key={n.id} className="news-item">
            <div>
              {n.url ? <a href={n.url} target="_blank" rel="noreferrer">{n.headline}</a> : n.headline}
              {n.is_duplicate && <span className="badge tone-muted" style={{ marginLeft: 6 }}>Duplikat</span>}
            </div>
            <div className="meta">
              <span>{n.kind === "filing" ? "SEC-Filing" : n.source ?? "News"}</span>
              <span>veröffentlicht {fmtTime(n.published_at, true)} ({ago(n.published_at)})</span>
              <span>{n.symbols.join(", ")}</span>
              {r.status === "ok" && (
                <span>Reaktion 15 Min.: <span className="num">{fmtPct(r["excess_15m_pct"] as number)}</span> vs. SPY ·
                  RVOL <span className="num">{(r["rvol_15m"] as number | null)?.toFixed(1) ?? "–"}</span>
                  {r.significant ? <b className="up"> · signifikant</b> : " · nicht signifikant"}</span>
              )}
              {r.status === "pending" && <span>Kursreaktion ausstehend</span>}
            </div>
            {n.assessment && (
              <div style={{ marginTop: 4 }}>
                <span className={`badge tone-${n.assessment.direction === "bullish" ? "bull" : n.assessment.direction === "bearish" ? "bear" : "muted"}`}>
                  {n.assessment.category} · {n.assessment.direction} · Relevanz {n.assessment.relevance}
                </span>{" "}
                {!n.assessment.is_new_information && <span className="badge tone-warn">nicht neu</span>}
                <div className="muted">{n.assessment.reasoning}</div>
                {n.assessment.verifiable_facts.length > 0 && (
                  <ul>{n.assessment.verifiable_facts.map((f) => <li key={f}>„{f}“</li>)}</ul>
                )}
              </div>
            )}
            {!n.assessment && n.summary && <div className="muted" style={{ marginTop: 4 }}>{n.summary.slice(0, 280)}</div>}
          </div>
        );
      })}
    </>
  );
}

function SimilarityTab({ sim, demo }: { sim: Similarity | undefined; demo: boolean }) {
  if (!sim) return <div className="empty">Zuerst eine Analyse erstellen.</div>;
  if (sim.status !== "ok") {
    return <div className="note">Keine belastbare Historie: {(sim.limitations ?? [sim.status]).join("; ")}</div>;
  }
  const horizons = sim.horizons ?? [];
  const maxAbs = Math.max(0.01, ...(sim.analogs ?? []).map((a) => Math.abs(Number(a["fwd_30_pct"] ?? 0))));
  return (
    <>
      {demo && <div className="note warn">Basierend auf simulierten DEMO-Daten – ohne Aussagekraft.</div>}
      <div className="stat-row">
        <Stat k="Analogien" v={`${sim.n_analogs} / ${sim.candidates} Kandidaten`} />
        <Stat k="Match-Qualität" v={sim.match_quality?.toFixed(2) ?? "–"} hint="Ø Distanz / Median (kleiner = ähnlicher)" />
        <Stat k="Ø MFE / MAE (60 Min.)" v={`${fmtPct(sim.mfe_mean_pct)} / ${fmtPct(sim.mae_mean_pct)}`} />
        <Stat k="Regime-Filter" v={sim.regime_filter ?? "aus"} />
      </div>
      <div className={`note ${sim.statistically_usable ? "" : "warn"}`} style={{ marginBottom: 8 }}>
        {sim.statistically_usable
          ? "Mindestens ein Horizont unterscheidet sich statistisch von der Basisrate (Wilson-95%-KI) bei guter Match-Qualität."
          : "Deskriptiv: kein Horizont unterscheidet sich belastbar von der Basisrate. Nicht als Wahrscheinlichkeit lesen."}
      </div>
      <table className="grid">
        <thead><tr><th>Horizont</th><th>n</th><th>Ø Rendite</th><th>Median</th><th>IQR</th><th>Trefferquote (95%-KI)</th><th>Basisrate</th><th /></tr></thead>
        <tbody>
          {horizons.map((h) => (
            <tr key={h.horizon_min}>
              <td>{h.horizon_min} Min.</td><td className="num">{h.n}</td>
              <td className="num">{fmtPct(h.mean_pct, 3)}</td><td className="num">{fmtPct(h.median_pct, 3)}</td>
              <td className="num">{fmtPct(h.q25_pct, 2)} … {fmtPct(h.q75_pct, 2)}</td>
              <td className="num">{pct(h.hit_rate)} ({pct(h.ci_low)}–{pct(h.ci_high)})</td>
              <td className="num">{pct(h.base_hit_rate)}</td>
              <td>{h.distinguishable ? <span className="badge tone-neutral">≠ Basis</span> : <span className="faint">≈ Basis</span>}</td>
            </tr>
          ))}
        </tbody>
      </table>
      <div className="section">
        <h4>Rendite nach 30 Min. der ähnlichsten Situationen</h4>
        <div className="bars-mini">
          {(sim.analogs ?? []).map((a, i) => {
            const v = Number(a["fwd_30_pct"] ?? 0);
            return <div key={i} title={`${a.session}: ${fmtPct(v)}`}
              style={{ height: `${Math.max(4, (Math.abs(v) / maxAbs) * 100)}%`, background: v >= 0 ? "var(--bull)" : "var(--bear)", opacity: 0.75 }} />;
          })}
        </div>
      </div>
      <table className="grid" style={{ marginTop: 8 }}>
        <thead><tr><th>Session</th><th>Distanz</th><th>Regime</th><th>+5</th><th>+15</th><th>+30</th><th>+60</th><th>MFE</th><th>MAE</th></tr></thead>
        <tbody>
          {(sim.analogs ?? []).map((a, i) => (
            <tr key={i}>
              <td>{fmtTime(String(a.ts), true)}</td><td className="num">{a.distance}</td><td>{a.regime}</td>
              {["fwd_5_pct", "fwd_15_pct", "fwd_30_pct", "fwd_60_pct", "mfe_pct", "mae_pct"].map((k) => (
                <td key={k} className={`num ${Number(a[k] ?? 0) >= 0 ? "up" : "down"}`}>{fmtPct(a[k] as number | null)}</td>
              ))}
            </tr>
          ))}
        </tbody>
      </table>
      <div className="section"><h4>Einschränkungen</h4><ul>{(sim.limitations ?? []).map((l) => <li key={l}>{l}</li>)}</ul></div>
    </>
  );
}

function SignalsTab({ history }: { history: Analysis[] }) {
  if (history.length === 0) return <div className="empty">Noch keine gespeicherten Analysen.</div>;
  return (
    <table className="grid">
      <thead><tr><th>Zeit</th><th>Symbol</th><th>Einschätzung</th><th>Referenz</th><th>Entry / Stop / Ziel</th><th>Trigger</th><th>+15 Min.</th><th>+60 Min.</th><th>Ergebnis</th><th>Daten</th></tr></thead>
      <tbody>
        {history.map((a) => {
          const o15 = a.outcomes?.find((o) => o.horizon_min === 15);
          const o60 = a.outcomes?.find((o) => o.horizon_min === 60);
          const sc = a.scenario;
          return (
            <tr key={a.id}>
              <td>{fmtTime(a.created_at, true)}</td><td>{a.symbol}</td>
              <td><span className={`badge tone-${OUTCOME_TONE[a.outcome] ?? "muted"}`}>{sc.label}</span></td>
              <td className="num">{fmtPrice(a.reference_price)}</td>
              <td className="num">{sc.entry_zone ? `${fmtPrice(sc.entry_zone[0])}–${fmtPrice(sc.entry_zone[1])} / ${fmtPrice(sc.stop)} / ${fmtPrice(sc.targets[0])}` : "–"}</td>
              <td className="muted">{a.trigger}</td>
              <td className={`num ${(o15?.ret_pct ?? 0) >= 0 ? "up" : "down"}`}>{o15 ? fmtPct(o15.ret_pct) : "offen"}</td>
              <td className={`num ${(o60?.ret_pct ?? 0) >= 0 ? "up" : "down"}`}>{o60 ? fmtPct(o60.ret_pct) : "offen"}</td>
              <td>{o60 ? `${o60.result}${o60.r_multiple !== null ? ` (${o60.r_multiple.toFixed(2)} R)` : ""}` : "–"}</td>
              <td>{a.data_kind === "demo" ? <span className="badge tone-bear">DEMO</span> : a.data_kind}</td>
            </tr>
          );
        })}
      </tbody>
    </table>
  );
}

function PerformanceTab({ refreshKey }: { refreshKey: number }) {
  const [h, setH] = useState(60);
  const [p, setP] = useState<Performance | null>(null);
  useEffect(() => { api.performance(h).then(setP).catch(() => setP(null)); }, [h, refreshKey]);
  return (
    <>
      <div className="toolbar" style={{ marginBottom: 8 }}>
        <span className="muted">Horizont</span>
        <div className="seg">{[15, 60, 240].map((x) => <button key={x} className={x === h ? "on" : ""} onClick={() => setH(x)}>{x} Min.</button>)}</div>
      </div>
      {!p || p.n === 0 ? (
        <div className="note">{p?.note ?? "Noch keine ausgewerteten Analysen."} Auswertungen entstehen automatisch, sobald nach einer gespeicherten Analyse genügend Marktdaten vorliegen.</div>
      ) : (
        <>
          {p.data_kinds?.includes("demo") && <div className="note warn">Enthält DEMO-Analysen – nicht aussagekräftig.</div>}
          <div className="stat-row">
            <Stat k="Engine (gerichtet)" v={`${fmtPct(p.engine_directional?.mean_signed_ret_pct, 3)} · Treffer ${pct(p.engine_directional?.hit_rate ?? null)}`} hint={`n=${p.engine_directional?.n}`} />
            <Stat k="Baseline: immer Long" v={`${fmtPct(p.baseline_always_long?.mean_ret_pct, 3)} · Treffer ${pct(p.baseline_always_long?.hit_rate ?? null)}`} hint={`n=${p.baseline_always_long?.n}`} />
            <Stat k="Baseline: 5m-Momentum" v={fmtPct(p.baseline_momentum_5m?.mean_signed_ret_pct, 3)} hint={`n=${p.baseline_momentum_5m?.n}`} />
            <Stat k="Kalibrierung" v={p.calibrated ? "verfügbar" : "noch nicht"} hint={p.note} />
          </div>
          <table className="grid">
            <thead><tr><th>Einschätzung</th><th>n</th><th>Ø Rendite</th><th>Ziel erreicht</th><th>Ø R</th></tr></thead>
            <tbody>{(p.by_outcome ?? []).map((r) => (
              <tr key={r.outcome}><td>{r.outcome}</td><td className="num">{r.n}</td><td className="num">{fmtPct(r.mean_ret_pct, 3)}</td>
                <td className="num">{pct(r.hit_target)}</td><td className="num">{r.mean_r?.toFixed(2) ?? "–"}</td></tr>
            ))}</tbody>
          </table>
        </>
      )}
    </>
  );
}

function Stat({ k, v, hint }: { k: string; v: string; hint?: string }) {
  return (
    <div className="level" title={hint}>
      <div className="k">{k}</div>
      <div className="v" style={{ fontSize: 12 }}>{v}</div>
    </div>
  );
}

const pct = (x: number | null | undefined) => (x === null || x === undefined ? "–" : `${(x * 100).toFixed(0)} %`);
