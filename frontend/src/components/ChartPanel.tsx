"use client";

import {
  CandlestickSeries,
  ColorType,
  CrosshairMode,
  HistogramSeries,
  LineSeries,
  LineStyle,
  createChart,
  createSeriesMarkers,
  type IChartApi,
  type IPriceLine,
  type ISeriesApi,
  type ISeriesMarkersPluginApi,
  type SeriesMarker,
  type Time,
  type UTCTimestamp,
} from "lightweight-charts";
import { useCallback, useEffect, useRef, useState } from "react";
import { api, type Analysis, type Bar, type Point, type Timeframe } from "@/lib/api";
import { toChartTime } from "@/lib/format";

const TIMEFRAMES: Array<{ tf: Timeframe; label: string; days: number }> = [
  { tf: "1Min", label: "1m", days: 2 },
  { tf: "5Min", label: "5m", days: 5 },
  { tf: "15Min", label: "15m", days: 15 },
  { tf: "1Hour", label: "1h", days: 40 },
  { tf: "1Day", label: "1D", days: 250 },
  { tf: "1Week", label: "1W", days: 250 },
];

const C = {
  up: "#3ddc97",
  down: "#ff5d73",
  grid: "#151c26",
  text: "#7d8899",
  ema20: "#f5b942",
  ema50: "#b48cff",
  vwap: "#5b9cff",
  bb: "rgba(125,136,153,.55)",
  entry: "#5b9cff",
  stop: "#ff5d73",
  target: "#3ddc97",
  support: "rgba(61,220,151,.45)",
  resistance: "rgba(255,93,115,.45)",
};

type Overlay = "ema" | "vwap" | "bb" | "levels" | "signals";

const ts = (t: number) => toChartTime(t) as UTCTimestamp;
// Gaps (value null) become whitespace. Lightweight Charts still connects across whitespace and
// colours a segment by its *starting* point, so the last point before a gap is made transparent.
// Every point gets an explicit colour (points without one may inherit a previous override).
const line = (pts: Point[] | undefined, color: string) => {
  const arr = pts ?? [];
  return arr.map((p, i) => {
    if (p.value === null) return { time: ts(p.time) };
    const beforeGap = arr[i + 1]?.value === null;
    return { time: ts(p.time), value: p.value, color: beforeGap ? "rgba(0,0,0,0)" : color };
  });
};

export function ChartPanel({ symbol, analysis, history, refreshKey }: {
  symbol: string;
  analysis: Analysis | null;
  history: Analysis[];
  refreshKey: number;
}) {
  const el = useRef<HTMLDivElement>(null);
  const chart = useRef<IChartApi | null>(null);
  const s = useRef<Record<string, ISeriesApi<"Candlestick" | "Line" | "Histogram">>>({});
  const markers = useRef<ISeriesMarkersPluginApi<Time> | null>(null);
  const lines = useRef<IPriceLine[]>([]);
  const barsRef = useRef<Bar[]>([]);
  const [tf, setTf] = useState<Timeframe>("5Min");
  const [overlays, setOverlays] = useState<Record<Overlay, boolean>>({
    ema: true, vwap: true, bb: false, levels: true, signals: true,
  });
  const [error, setError] = useState<string | null>(null);
  const [last, setLast] = useState<Bar | null>(null);

  // create chart once
  useEffect(() => {
    if (!el.current) return;
    const c = createChart(el.current, {
      autoSize: true,
      layout: {
        background: { type: ColorType.Solid, color: "#0b0f15" },
        textColor: C.text,
        fontSize: 11,
        attributionLogo: true, // required by the Lightweight Charts licence (TradingView attribution)
        panes: { separatorColor: "#1d2633", enableResize: true },
      },
      grid: { vertLines: { color: C.grid }, horzLines: { color: C.grid } },
      crosshair: { mode: CrosshairMode.Normal },
      rightPriceScale: { borderColor: "#1d2633" },
      timeScale: { borderColor: "#1d2633", timeVisible: true, secondsVisible: false },
    });
    chart.current = c;
    const candles = c.addSeries(CandlestickSeries, {
      upColor: C.up, downColor: C.down, borderVisible: false, wickUpColor: C.up, wickDownColor: C.down,
    });
    const volume = c.addSeries(HistogramSeries, { priceFormat: { type: "volume" }, priceScaleId: "vol" });
    volume.priceScale().applyOptions({ scaleMargins: { top: 0.82, bottom: 0 } });
    const mk = (color: string, width: 1 | 2 = 1, pane = 0, style: LineStyle = LineStyle.Solid) =>
      c.addSeries(LineSeries, {
        color, lineWidth: width, lineStyle: style, priceLineVisible: false, lastValueVisible: false,
        crosshairMarkerVisible: false,
      }, pane);
    s.current = {
      candles, volume,
      ema20: mk(C.ema20), ema50: mk(C.ema50), vwap: mk(C.vwap, 2),
      bbU: mk(C.bb, 1, 0, LineStyle.Dotted), bbL: mk(C.bb, 1, 0, LineStyle.Dotted),
      rsi: mk("#c9a8ff", 1, 1),
      macd: mk(C.vwap, 1, 2), macdSig: mk(C.ema20, 1, 2),
      macdHist: c.addSeries(HistogramSeries, { priceLineVisible: false, lastValueVisible: false }, 2),
    };
    s.current.rsi!.createPriceLine({ price: 70, color: "#3a4556", lineStyle: LineStyle.Dashed, lineWidth: 1, axisLabelVisible: false, title: "" });
    s.current.rsi!.createPriceLine({ price: 30, color: "#3a4556", lineStyle: LineStyle.Dashed, lineWidth: 1, axisLabelVisible: false, title: "" });
    markers.current = createSeriesMarkers(candles, []);
    const panes = c.panes();
    panes[1]?.setHeight(80);
    panes[2]?.setHeight(80);
    c.subscribeCrosshairMove((p) => {
      const d = p.seriesData.get(candles) as Bar | undefined;
      setLast(d ?? barsRef.current.at(-1) ?? null);
    });
    return () => {
      c.remove();
      chart.current = null;
    };
  }, []);

  const load = useCallback(async () => {
    const conf = TIMEFRAMES.find((t) => t.tf === tf)!;
    try {
      const [b, ind] = await Promise.all([api.bars(symbol, tf, conf.days), api.indicators(symbol, tf, conf.days)]);
      setError(null);
      barsRef.current = b.bars;
      setLast(b.bars.at(-1) ?? null);
      const sr = s.current;
      sr.candles!.setData(b.bars.map((x) => ({ time: ts(x.time), open: x.open, high: x.high, low: x.low, close: x.close })));
      sr.volume!.setData(b.bars.map((x) => ({
        time: ts(x.time), value: x.volume,
        color: x.close >= x.open ? "rgba(61,220,151,.28)" : "rgba(255,93,115,.28)",
      })));
      sr.ema20!.setData(line(ind.series.ema20, C.ema20));
      sr.ema50!.setData(line(ind.series.ema50, C.ema50));
      sr.vwap!.setData(line(ind.series.vwap, C.vwap));
      sr.bbU!.setData(line(ind.series.bb_upper, C.bb));
      sr.bbL!.setData(line(ind.series.bb_lower, C.bb));
      sr.rsi!.setData(line(ind.series.rsi14, "#c9a8ff"));
      sr.macd!.setData(line(ind.series.macd, C.vwap));
      sr.macdSig!.setData(line(ind.series.macd_signal, C.ema20));
      sr.macdHist!.setData((ind.series.macd_hist ?? []).map((p) => ({
        time: ts(p.time), value: p.value ?? 0, color: (p.value ?? 0) >= 0 ? "rgba(61,220,151,.5)" : "rgba(255,93,115,.5)",
      })));
    } catch (e) {
      setError((e as Error).message);
    }
  }, [symbol, tf]);

  useEffect(() => {
    void load();
  }, [load, refreshKey]);

  useEffect(() => {
    chart.current?.timeScale().fitContent();
  }, [symbol, tf]);

  // overlay visibility
  useEffect(() => {
    const sr = s.current;
    sr.ema20?.applyOptions({ visible: overlays.ema });
    sr.ema50?.applyOptions({ visible: overlays.ema });
    sr.vwap?.applyOptions({ visible: overlays.vwap });
    sr.bbU?.applyOptions({ visible: overlays.bb });
    sr.bbL?.applyOptions({ visible: overlays.bb });
  }, [overlays]);

  // levels from the latest analysis: zones, entry/stop/targets
  useEffect(() => {
    const candles = s.current.candles;
    if (!candles) return;
    lines.current.forEach((l) => candles.removePriceLine(l));
    lines.current = [];
    if (!overlays.levels || !analysis) return;
    const add = (price: number, color: string, title: string, style: LineStyle = LineStyle.Dashed, width: 1 | 2 = 1) =>
      lines.current.push(candles.createPriceLine({ price, color, title, lineStyle: style, lineWidth: width, axisLabelVisible: true }));
    for (const z of analysis.facts?.zones ?? []) {
      add(z.mid, z.kind === "support" ? C.support : C.resistance, `${z.kind === "support" ? "S" : "R"}${z.strength}`, LineStyle.Dotted);
    }
    const sc = analysis.scenario;
    if (sc.entry_zone) {
      add(sc.entry_zone[0], C.entry, "Entry", LineStyle.Solid);
      add(sc.entry_zone[1], C.entry, "", LineStyle.Solid);
    }
    if (sc.stop) add(sc.stop, C.stop, "Stop", LineStyle.Solid, 2);
    sc.targets.forEach((t, i) => add(t, C.target, `T${i + 1}`, LineStyle.Solid));
  }, [analysis, overlays.levels]);

  // historical + current signal markers
  useEffect(() => {
    if (!markers.current) return;
    const bars = barsRef.current;
    if (!overlays.signals || bars.length === 0) {
      markers.current.setMarkers([]);
      return;
    }
    const first = bars[0]!.time;
    const snap = (unix: number) => {
      let lo = 0, hi = bars.length - 1;
      while (lo < hi) {
        const mid = Math.ceil((lo + hi) / 2);
        if (bars[mid]!.time <= unix) lo = mid; else hi = mid - 1;
      }
      return bars[lo]!.time;
    };
    const ms: SeriesMarker<Time>[] = history
      .filter((a) => ["long_entry", "short_entry", "bullish_setup", "bearish_setup", "invalidated"].includes(a.outcome))
      .map((a) => ({ a, t: Math.floor(new Date(a.data_as_of).getTime() / 1000) }))
      .filter(({ t }) => t >= first)
      .sort((x, y) => x.t - y.t)
      .map(({ a, t }) => {
        const long = a.bias === "long";
        const inval = a.outcome === "invalidated";
        return {
          time: ts(snap(t)),
          position: inval ? "aboveBar" : long ? "belowBar" : "aboveBar",
          color: inval ? "#f5b942" : long ? C.up : C.down,
          shape: inval ? "circle" : long ? "arrowUp" : "arrowDown",
          text: inval ? "×" : a.outcome.endsWith("entry") ? (long ? "L" : "S") : (long ? "l" : "s"),
        } as SeriesMarker<Time>;
      });
    markers.current.setMarkers(ms);
  }, [history, overlays.signals, refreshKey, tf, symbol]);

  const toggle = (o: Overlay) => setOverlays((v) => ({ ...v, [o]: !v[o] }));

  return (
    <div className="panel" style={{ flex: 1 }}>
      <div className="panel-head">
        <span style={{ color: "var(--text)", fontSize: 13, letterSpacing: ".04em" }}>{symbol}</span>
        <div className="seg">
          {TIMEFRAMES.map((t) => (
            <button key={t.tf} className={t.tf === tf ? "on" : ""} onClick={() => setTf(t.tf)}>{t.label}</button>
          ))}
        </div>
        <div className="seg">
          {(["ema", "vwap", "bb", "levels", "signals"] as Overlay[]).map((o) => (
            <button key={o} className={overlays[o] ? "on" : ""} onClick={() => toggle(o)}>
              {{ ema: "EMA 20/50", vwap: "VWAP", bb: "Bollinger", levels: "Levels", signals: "Signale" }[o]}
            </button>
          ))}
        </div>
        <span className="spacer" />
        {error && <span className="down" style={{ textTransform: "none" }}>{error}</span>}
      </div>
      <div className="chart-wrap">
        {last && (
          <div className="chart-legend num">
            <span>O {last.open?.toFixed(2)}</span><span>H {last.high?.toFixed(2)}</span>
            <span>L {last.low?.toFixed(2)}</span><span>C {last.close?.toFixed(2)}</span>
            <span className="faint">Zeiten in ET · RSI(14) · MACD(12,26,9)</span>
          </div>
        )}
        <div ref={el} style={{ position: "absolute", inset: 0 }} />
      </div>
    </div>
  );
}
