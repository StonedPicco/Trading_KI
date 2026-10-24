"use client";

import type { Analysis, Factor } from "@/lib/api";
import { OUTCOME_TONE, PHASE_LABEL, ago, dataKindLabel, fmtPrice, fmtTime } from "@/lib/format";

function FactorRow({ f }: { f: Factor }) {
  return (
    <div className="factor">
      <span className={f.direction > 0 ? "up" : "down"}>{f.direction > 0 ? "▲" : "▼"}</span>
      <div>
        <div>{f.observation}</div>
        <div className="muted">{f.interpretation}</div>
      </div>
      <span className="w">{f.weight.toFixed(1)}</span>
    </div>
  );
}

export function AnalystPanel({ analysis, loading, error, onAnalyze }: {
  analysis: Analysis | null;
  loading: boolean;
  error: string | null;
  onAnalyze: () => void;
}) {
  const sc = analysis?.scenario;
  const n = analysis?.narrative;
  const tone = sc ? OUTCOME_TONE[sc.outcome] ?? "muted" : "muted";
  const dq = analysis?.facts?.data_quality;

  return (
    <div className="panel" style={{ flex: 1 }}>
      <div className="panel-head">
        AI Analyst
        <span className="spacer" />
        <button className="btn primary" onClick={onAnalyze} disabled={loading}>
          {loading ? "Analysiere …" : "Neu analysieren"}
        </button>
      </div>
      <div className="panel-body">
        {error && <div className="note warn">{error}</div>}
        {!analysis && !loading && <div className="empty">Noch keine Analyse für dieses Symbol.</div>}
        {analysis && sc && n && (
          <>
            <div className="headline">
              <span className={`badge tone-${tone}`}>{sc.label}</span>
              <span className="big num">{fmtPrice(sc.reference_price)}</span>
              <span className={`chip ${analysis.data_kind === "demo" ? "demo" : analysis.data_kind === "delayed" ? "delayed" : "live"}`}>
                <span className="dot" />
                {dataKindLabel(analysis.data_kind, analysis.provenance.delay_minutes)}
              </span>
            </div>
            <div className="muted" style={{ fontSize: 11 }}>
              Datenstand {fmtTime(analysis.data_as_of, true)} · erstellt {ago(analysis.created_at)} ·{" "}
              {PHASE_LABEL[analysis.market_phase] ?? analysis.market_phase} · Trigger: {analysis.trigger} ·{" "}
              Quelle: {analysis.provenance.provider}/{analysis.provenance.feed}
            </div>

            {sc.entry_zone && (
              <div className="levels">
                <div className="level"><div className="k">Entry-Zone</div>
                  <div className="v">{fmtPrice(sc.entry_zone[0])} – {fmtPrice(sc.entry_zone[1])}</div></div>
                <div className="level"><div className="k">Stop / Invalidierung</div>
                  <div className="v down">{fmtPrice(sc.stop)}</div></div>
                <div className="level"><div className="k">Ziele</div>
                  <div className="v up">{sc.targets.map((t) => fmtPrice(t)).join(" · ")}</div></div>
                <div className="level"><div className="k">Chance/Risiko</div>
                  <div className="v">{sc.reward_risk?.toFixed(2) ?? "–"} R</div></div>
              </div>
            )}

            <div className="section"><h4>Einschätzung</h4><div>{n.summary}</div></div>

            {sc.confirmation.length > 0 && (
              <div className="section"><h4>Bestätigung abwarten</h4>
                <ul>{sc.confirmation.map((c) => <li key={c}>{c}</li>)}</ul></div>
            )}
            {sc.invalidation && (
              <div className="section"><h4>Ungültig wenn</h4><div>{sc.invalidation}</div></div>
            )}

            <div className="section">
              <h4>Evidenz · Bilanz {sc.evidence_score > 0 ? "+" : ""}{sc.evidence_score.toFixed(1)}</h4>
              <div className="faint" style={{ fontSize: 11, marginBottom: 6 }}>{sc.evidence_note}</div>
              {sc.factors_for.map((f) => <FactorRow key={f.key} f={f} />)}
              {sc.factors_against.map((f) => <FactorRow key={f.key} f={f} />)}
              {sc.factors_for.length + sc.factors_against.length === 0 && <div className="faint">Keine gerichteten Faktoren.</div>}
            </div>

            <div className="section"><h4>Bullisches Szenario</h4>
              <ul>{n.bull_case.length ? n.bull_case.map((x) => <li key={x}>{x}</li>) : <li className="faint">–</li>}</ul></div>
            <div className="section"><h4>Bärisches Szenario</h4>
              <ul>{n.bear_case.length ? n.bear_case.map((x) => <li key={x}>{x}</li>) : <li className="faint">–</li>}</ul></div>
            <div className="section"><h4>Risiken</h4>
              <ul>{[...sc.risks, ...n.key_risks.filter((r) => !sc.risks.includes(r))].map((r) => <li key={r}>{r}</li>)}</ul></div>
            <div className="section"><h4>Markt & Sektor</h4><div>{n.market_context}</div></div>
            {n.engine_agreement !== "agree" && (
              <div className="note warn">KI widerspricht der Engine ({n.engine_agreement}): {n.disagreement_reason}</div>
            )}
            <div className="section"><h4>Unsicherheiten</h4>
              <ul>{n.uncertainty.map((u) => <li key={u}>{u}</li>)}</ul></div>
            {dq && !dq.ok && <div className="note warn">Datenqualität: {dq.issues.join("; ")}</div>}

            <div className="section"><h4>Quellen</h4>
              <ul>
                {analysis.sources.map((src, i) => (
                  <li key={i}>
                    {src.type === "market_data"
                      ? `Marktdaten: ${src.provider} (${src.data_kind}) · Stand ${fmtTime(src.as_of, true)}`
                      : src.url ? <a href={src.url} target="_blank" rel="noreferrer">{src.title}</a> : src.title}
                  </li>
                ))}
              </ul>
            </div>
            <div className="note">
              Begründung: {n.meta.generated_by}{n.meta.model ? ` (${n.meta.model})` : ""} · Engine {analysis.engine_version} ·
              Hash <span className="num">{analysis.input_hash.slice(0, 12)}</span>
              {n.meta.validation && !n.meta.validation.ok && <> · LLM-Ausgabe verworfen: {n.meta.validation.errors.join("; ")}</>}
              {n.meta.llm_error && <> · LLM nicht verfügbar: {n.meta.llm_error}</>}
            </div>
          </>
        )}
      </div>
      <div className="footer-disclaimer">
        Analyse und Szenarien – keine Anlageberatung. Es werden keine Orders ausgeführt.
      </div>
    </div>
  );
}
