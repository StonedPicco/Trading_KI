"use client";

import { useEffect, useState } from "react";
import type { Health, NotificationItem } from "@/lib/api";
import { PHASE_LABEL, ago, dataKindLabel } from "@/lib/format";

export function TopBar({ health, notifications, wsState, onRead, onSelectSymbol }: {
  health: Health | null;
  notifications: NotificationItem[];
  wsState: string;
  onRead: (id: number) => void;
  onSelectSymbol: (s: string) => void;
}) {
  const [open, setOpen] = useState(false);
  const [clock, setClock] = useState("");
  useEffect(() => {
    const tick = () => setClock(new Date().toLocaleTimeString("de-AT", { timeZone: "America/New_York", hour: "2-digit", minute: "2-digit", second: "2-digit" }));
    tick();
    const t = setInterval(tick, 1000);
    return () => clearInterval(t);
  }, []);
  const unread = notifications.filter((n) => !n.read).length;
  const prov = health?.provenance;
  const kindClass = prov?.data_kind === "demo" ? "demo" : prov?.data_kind === "delayed" ? "delayed" : "live";

  return (
    <div className="topbar">
      <div className="brand"><span className="brand-mark" />ATI TERMINAL <small>Market Intelligence</small></div>
      {prov && (
        <span className={`chip ${kindClass}`} title={prov.notes.join(" ")}>
          <span className="dot" />{dataKindLabel(prov.data_kind, prov.delay_minutes)} · {prov.provider}/{prov.feed}
        </span>
      )}
      {health && <span className="chip">{PHASE_LABEL[health.market_phase] ?? health.market_phase}</span>}
      <span className="chip num">NY {clock}</span>
      {health && <span className="chip">LLM: {health.llm.enabled ? health.llm.model : "aus (deterministisch)"}</span>}
      <span className={`chip ${wsState === "open" ? "live" : "delayed"}`}><span className="dot" />Push {wsState === "open" ? "verbunden" : "getrennt"}</span>
      <span className="spacer" />
      <div className="bell">
        <button className="btn" onClick={() => setOpen((o) => !o)}>Benachrichtigungen</button>
        {unread > 0 && <span className="count">{unread}</span>}
      </div>
      {open && (
        <div className="drawer">
          {notifications.length === 0 && <div className="empty">Keine Benachrichtigungen.</div>}
          {notifications.map((n) => (
            <div key={n.id} className={`notif ${n.read ? "" : "unread"}`}
              onClick={() => { if (!n.read) onRead(n.id); if (n.symbol) onSelectSymbol(n.symbol); }}
              style={{ cursor: "pointer" }}>
              <div style={{ display: "flex", gap: 6, alignItems: "center" }}>
                <span className={`badge tone-${n.severity === "alert" ? "bull" : n.severity === "warn" ? "warn" : "neutral"}`}>{n.kind}</span>
                <b>{n.title}</b>
              </div>
              <div className="muted">{n.body}</div>
              <div className="faint" style={{ fontSize: 11 }}>{ago(n.created_at)}</div>
            </div>
          ))}
        </div>
      )}
    </div>
  );
}
