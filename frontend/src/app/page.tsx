"use client";

import { useCallback, useEffect, useState } from "react";
import { AnalystPanel } from "@/components/AnalystPanel";
import { BottomTabs } from "@/components/BottomTabs";
import { ChartPanel } from "@/components/ChartPanel";
import { TopBar } from "@/components/TopBar";
import { Watchlist } from "@/components/Watchlist";
import { api, type Analysis, type Health, type NotificationItem, type OverviewItem } from "@/lib/api";
import { useServerEvents } from "@/lib/useEvents";

const POLL_MS = 60_000; // fallback refresh in addition to WebSocket push

export default function Dashboard() {
  const [health, setHealth] = useState<Health | null>(null);
  const [items, setItems] = useState<OverviewItem[]>([]);
  const [symbol, setSymbol] = useState<string>("");
  const [analysis, setAnalysis] = useState<Analysis | null>(null);
  const [history, setHistory] = useState<Analysis[]>([]);
  const [notifications, setNotifications] = useState<NotificationItem[]>([]);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [refreshKey, setRefreshKey] = useState(0);

  const loadOverview = useCallback(async () => {
    try {
      const ov = await api.overview();
      setItems(ov);
      setSymbol((s) => s || ov[0]?.symbol || "");
    } catch (e) {
      setError(`Backend nicht erreichbar: ${(e as Error).message}`);
    }
  }, []);

  const loadSymbol = useCallback(async (sym: string) => {
    if (!sym) return;
    const [latest, hist] = await Promise.allSettled([api.latest(sym), api.history(sym, 200)]);
    setAnalysis(latest.status === "fulfilled" ? latest.value : null);
    setHistory(hist.status === "fulfilled" ? hist.value : []);
  }, []);

  const loadNotifications = useCallback(() => {
    api.notifications().then(setNotifications).catch(() => undefined);
  }, []);

  useEffect(() => {
    api.health().then(setHealth).catch((e: Error) => setError(`Backend nicht erreichbar: ${e.message}`));
    void loadOverview();
    loadNotifications();
    const t = setInterval(() => {
      void loadOverview();
      setRefreshKey((k) => k + 1);
    }, POLL_MS);
    return () => clearInterval(t);
  }, [loadOverview, loadNotifications]);

  useEffect(() => {
    void loadSymbol(symbol);
  }, [symbol, loadSymbol, refreshKey]);

  const wsState = useServerEvents((e) => {
    if (e.type === "notification") loadNotifications();
    if (e.type === "analysis.created") {
      void loadOverview();
      if (e.symbol === symbol) setRefreshKey((k) => k + 1);
    }
    if (e.type === "bars.updated") setRefreshKey((k) => k + 1);
  });

  const analyze = async () => {
    if (!symbol) return;
    setBusy(true);
    setError(null);
    try {
      const a = await api.analyze(symbol);
      setAnalysis(a);
      await loadOverview();
      setRefreshKey((k) => k + 1);
    } catch (e) {
      setError((e as Error).message);
    } finally {
      setBusy(false);
    }
  };

  return (
    <div className="app">
      {health?.demo_mode ? (
        <div className="demo-banner">
          DEMO-MODUS: Alle Kurse, Charts und Analysen basieren auf SIMULIERTEN Daten – keine echten Marktdaten.
        </div>
      ) : <div />}
      <TopBar health={health} notifications={notifications} wsState={wsState}
        onRead={(id) => { void api.markRead(id).then(loadNotifications); }}
        onSelectSymbol={setSymbol} />
      <div className="main">
        <div className="col">
          <Watchlist items={items} selected={symbol} onSelect={setSymbol}
            onAdd={async (s) => { await api.addSymbol(s); await loadOverview(); setSymbol(s); }}
            onRemove={(s) => { void api.removeSymbol(s).then(loadOverview); }} />
        </div>
        <div className="col center">
          {symbol ? (
            <>
              <ChartPanel symbol={symbol} analysis={analysis} history={history} refreshKey={refreshKey} />
              <BottomTabs symbol={symbol} analysis={analysis} history={history} refreshKey={refreshKey} />
            </>
          ) : <div className="empty">{error ?? "Lade …"}</div>}
        </div>
        <div className="col right">
          <AnalystPanel analysis={analysis} loading={busy} error={error} onAnalyze={() => void analyze()} />
        </div>
      </div>
    </div>
  );
}
