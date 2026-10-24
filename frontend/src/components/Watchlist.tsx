"use client";

import { useState } from "react";
import type { OverviewItem } from "@/lib/api";
import { OUTCOME_TONE, fmtCompact, fmtPct, fmtPrice } from "@/lib/format";

export function Watchlist({ items, selected, onSelect, onAdd, onRemove }: {
  items: OverviewItem[];
  selected: string;
  onSelect: (s: string) => void;
  onAdd: (s: string) => Promise<void>;
  onRemove: (s: string) => void;
}) {
  const [value, setValue] = useState("");
  const [err, setErr] = useState<string | null>(null);

  const submit = async () => {
    const sym = value.trim().toUpperCase();
    if (!sym) return;
    try {
      await onAdd(sym);
      setValue("");
      setErr(null);
    } catch (e) {
      setErr((e as Error).message);
    }
  };

  return (
    <div className="panel" style={{ flex: 1 }}>
      <div className="panel-head">Watchlist<span className="spacer" />{items.length}</div>
      <div className="wl-add">
        <input
          value={value}
          placeholder="Ticker, z. B. MSFT"
          maxLength={10}
          onChange={(e) => setValue(e.target.value)}
          onKeyDown={(e) => e.key === "Enter" && void submit()}
        />
        <button className="btn" onClick={() => void submit()}>+</button>
      </div>
      {err && <div className="note warn" style={{ margin: 8 }}>{err}</div>}
      <div className="panel-body" style={{ padding: 0 }}>
        {items.map((it) => {
          const tone = it.signal ? OUTCOME_TONE[it.signal.outcome] ?? "muted" : "muted";
          return (
            <div key={it.symbol} className={`wl-row ${it.symbol === selected ? "active" : ""}`} onClick={() => onSelect(it.symbol)}>
              <span className="wl-sym">{it.symbol}</span>
              <span className="num">{fmtPrice(it.price)}</span>
              <span className="wl-meta">
                <span>RVOL <span className="num">{it.rvol?.toFixed(2) ?? "–"}</span></span>
                <span>Vol <span className="num">{fmtCompact(it.volume_today)}</span></span>
                {it.news_24h ? <span title="Nachrichten (24h)">📰 {it.news_24h}</span> : null}
              </span>
              <span className={`num ${(it.change_pct ?? 0) >= 0 ? "up" : "down"}`}>{fmtPct(it.change_pct)}</span>
              <span style={{ gridColumn: "1 / -1" }}>
                {it.signal ? <span className={`badge tone-${tone}`}>{it.signal.label}</span>
                  : <span className="faint" style={{ fontSize: 11 }}>{it.error ?? "noch keine Analyse"}</span>}
              </span>
              <button className="wl-remove" title="Entfernen" onClick={(e) => { e.stopPropagation(); onRemove(it.symbol); }}>×</button>
            </div>
          );
        })}
        {items.length === 0 && <div className="empty">Watchlist ist leer.</div>}
      </div>
    </div>
  );
}
