"""Walk-forward replay of the analysis engine with realistic costs and simple baselines.

Every decision uses ``compute_facts`` with ``as_of`` = decision time, so the engine only sees
data available at that moment (the pipeline truncates inputs). The engine has no fitted
parameters; thresholds are fixed a priori, so every decision is out-of-sample by construction.
Results are reported overall, per period half and per volatility regime, next to baselines
that trade the *same* decision times with the same risk/target geometry.

Paper evaluation only – nothing here can place orders.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import logging
from dataclasses import asdict, dataclass, field
from datetime import UTC, date, datetime, time, timedelta
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd

from app.analysis.context import DEFAULT_SECTOR
from app.analysis.indicators import atr
from app.analysis.multitimeframe import resample_intraday
from app.analysis.pipeline import FactInputs, SymbolData, compute_facts
from app.analysis.similarity import build_feature_table
from app.core.jsonsafe import to_jsonable
from app.core.market_time import NY, session_times, trading_days
from app.domain.models import Provenance, Timeframe
from app.providers.base import MarketDataProvider
from app.signals.engine import ENGINE_VERSION, Outcome, build_scenario

log = logging.getLogger(__name__)


@dataclass
class CostModel:
    spread_bps: float = 2.0  # full quoted spread; half is paid on entry and on exit
    slippage_bps: float = 1.0  # per side, adverse
    commission_per_share: float = 0.0
    shares: int = 100

    def adverse(self, price: float, sign: int, entering: bool) -> float:
        bps = self.spread_bps / 2 + self.slippage_bps
        direction = sign if entering else -sign
        return price * (1 + direction * bps / 10_000)


@dataclass
class Trade:
    strategy: str
    decision_ts: str
    session: str
    bias: str
    entry: float
    stop: float
    target: float
    exit: float
    result: str
    r_gross: float
    r_net: float
    regime: str


@dataclass
class BacktestConfig:
    symbol: str
    start: date
    end: date
    step_minutes: int = 30
    first_decision: time = time(10, 0)
    last_decision: time = time(15, 0)
    costs: CostModel = field(default_factory=CostModel)
    seed: int = 7
    min_reward_risk: float = 1.5
    run_similarity: bool = True


def simulate(
    bars: pd.DataFrame, sign: int, entry_zone: tuple[float, float], stop: float, target: float
) -> tuple[str, float | None, float | None]:
    """Conservative bar replay until session end: (result, raw entry, raw exit) before costs."""
    lo, hi = entry_zone
    entry = None
    for _, b in bars.iterrows():
        if entry is None:
            if (sign > 0 and b["low"] <= hi) or (sign < 0 and b["high"] >= lo):
                entry = min(hi, b["open"]) if sign > 0 else max(lo, b["open"])
            else:
                continue
        if (sign > 0 and b["low"] <= stop) or (sign < 0 and b["high"] >= stop):
            return "stop", entry, stop
        if (sign > 0 and b["high"] >= target) or (sign < 0 and b["low"] <= target):
            return "target", entry, target
    if entry is None:
        return "not_triggered", None, None
    return "time_exit", entry, float(bars["close"].iloc[-1])


def _r(sign: int, entry: float, exit_: float, stop: float, costs: CostModel) -> tuple[float, float]:
    """R multiple before and after costs (risk measured on the planned, cost-free distance)."""
    risk = abs(entry - stop)
    if risk <= 0:
        return 0.0, 0.0
    gross = sign * (exit_ - entry) / risk
    entry_net = costs.adverse(entry, sign, entering=True)
    exit_net = costs.adverse(exit_, sign, entering=False)
    net = (sign * (exit_net - entry_net) - 2 * costs.commission_per_share) / risk
    return gross, net


def summarize(trades: list[Trade]) -> dict[str, Any]:
    if not trades:
        return {"trades": 0}
    r = np.array([t.r_net for t in trades])
    equity = np.cumsum(r)
    drawdown = float((np.maximum.accumulate(equity) - equity).max()) if len(equity) else 0.0
    wins = r[r > 0]
    losses = r[r <= 0]
    return {
        "trades": len(trades),
        "hit_rate": round(float((r > 0).mean()), 4),
        "mean_r_net": round(float(r.mean()), 4),
        "median_r_net": round(float(np.median(r)), 4),
        "total_r_net": round(float(r.sum()), 3),
        "profit_factor": round(float(wins.sum() / -losses.sum()), 3) if losses.sum() < 0 else None,
        "max_drawdown_r": round(drawdown, 3),
        "mean_r_gross": round(float(np.mean([t.r_gross for t in trades])), 4),
        "t_stat": round(float(r.mean() / (r.std(ddof=1) / np.sqrt(len(r)))), 3)
        if len(r) > 2 and r.std(ddof=1) > 0
        else None,
    }


async def load_inputs(
    provider: MarketDataProvider, symbol: str, start: date, end: date, history_days: int = 250
) -> tuple[SymbolData, SymbolData, SymbolData | None]:
    t0 = datetime.combine(start - timedelta(days=int(history_days * 1.5)), time(0), tzinfo=UTC)
    t1 = datetime.combine(end + timedelta(days=1), time(0), tzinfo=UTC)
    d0 = datetime.combine(start - timedelta(days=760), time(0), tzinfo=UTC)

    async def one(sym: str, minute_from: datetime) -> SymbolData:
        m = await provider.get_bars(sym, Timeframe.M1, minute_from, t1)
        d = await provider.get_bars(sym, Timeframe.D1, d0, t1)
        return SymbolData(sym, m, d)

    target = await one(symbol, t0)
    spy = await one("SPY", datetime.combine(start - timedelta(days=15), time(0), tzinfo=UTC))
    sector_sym = DEFAULT_SECTOR.get(symbol)
    sector = (
        (await one(sector_sym, datetime.combine(start - timedelta(days=15), time(0), tzinfo=UTC)))
        if sector_sym
        else None
    )
    return target, spy, sector


def run_backtest(
    cfg: BacktestConfig,
    target: SymbolData,
    spy: SymbolData | None,
    sector: SymbolData | None,
    provenance: Provenance,
) -> dict[str, Any]:
    rng = np.random.default_rng(cfg.seed)
    table = build_feature_table(target.minute, target.daily) if cfg.run_similarity else None
    m5_all = resample_intraday(target.minute, Timeframe.M5)
    trades: list[Trade] = []
    outcome_counts: dict[str, int] = {}
    decisions = 0
    for day in trading_days(cfg.start, cfg.end):
        st = session_times(day)
        if st is None:
            continue
        t = datetime.combine(day, cfg.first_decision, tzinfo=NY).astimezone(UTC)
        t_last = min(
            datetime.combine(day, cfg.last_decision, tzinfo=NY).astimezone(UTC),
            st.close - timedelta(minutes=30),
        )
        session_bars = target.minute[
            (target.minute.index >= st.open) & (target.minute.index < st.close)
        ]
        if session_bars.empty:
            continue
        while t <= t_last:
            decisions += 1
            facts = to_jsonable(
                compute_facts(
                    FactInputs(
                        target=target,
                        market=spy,
                        sector=sector,
                        as_of=t,
                        provenance=provenance,
                        run_similarity=cfg.run_similarity,
                        feature_table=table,
                    )
                )
            )
            sc = build_scenario(facts, cfg.min_reward_risk)
            outcome_counts[sc.outcome.value] = outcome_counts.get(sc.outcome.value, 0) + 1
            future = session_bars[session_bars.index >= t]
            regime = (facts.get("volatility") or {}).get("regime", "unknown")
            stop_dist = None
            if (
                sc.outcome in (Outcome.LONG_ENTRY, Outcome.SHORT_ENTRY)
                and sc.entry_zone
                and sc.stop is not None
            ):
                sign = 1 if sc.bias == "long" else -1
                target_px = sc.targets[0]
                res, fill, exit_ = simulate(future, sign, sc.entry_zone, sc.stop, target_px)
                if fill is not None and exit_ is not None and sc.stop is not None:
                    g, n = _r(sign, fill, exit_, sc.stop, cfg.costs)
                    trades.append(
                        Trade(
                            "engine",
                            t.isoformat(),
                            day.isoformat(),
                            sc.bias,
                            fill,
                            sc.stop,
                            target_px,
                            exit_,
                            res,
                            g,
                            n,
                            regime,
                        )
                    )
                stop_dist = abs((sc.entry_zone[0] + sc.entry_zone[1]) / 2 - sc.stop)
            # Baselines at the same decision time. Geometry: 1.5×ATR(5m) stop, 2R target, unless
            # the engine traded (then reuse its stop distance for a like-for-like comparison).
            m5 = m5_all[m5_all.index + timedelta(minutes=5) <= t]
            a5 = float(atr(m5).iloc[-1]) if len(m5) > 20 else None
            price = facts["price"]
            if a5 and price == price:
                dist = stop_dist or 1.5 * a5
                ref30 = m5["close"].iloc[-7] if len(m5) > 7 else price
                for name, sign in (
                    ("baseline_random", int(rng.choice([-1, 1]))),
                    ("baseline_momentum_30m", 1 if price > ref30 else -1),
                    ("baseline_always_long", 1),
                ):
                    stop = price - sign * dist
                    tgt = price + sign * 2 * dist
                    res, fill, exit_ = simulate(future, sign, (price, price), stop, tgt)
                    if fill is not None and exit_ is not None:
                        g, n = _r(sign, fill, exit_, stop, cfg.costs)
                        trades.append(
                            Trade(
                                name,
                                t.isoformat(),
                                day.isoformat(),
                                "long" if sign > 0 else "short",
                                fill,
                                stop,
                                tgt,
                                exit_,
                                res,
                                g,
                                n,
                                regime,
                            )
                        )
            t += timedelta(minutes=cfg.step_minutes)

    strategies = sorted({tr.strategy for tr in trades})
    sessions = sorted({tr.session for tr in trades})
    mid = sessions[len(sessions) // 2] if sessions else None
    report: dict[str, Any] = {
        "symbol": cfg.symbol,
        "start": cfg.start.isoformat(),
        "end": cfg.end.isoformat(),
        "engine_version": ENGINE_VERSION,
        "data_kind": provenance.data_kind.value,
        "provider": provenance.provider,
        "feed": provenance.feed,
        "decisions": decisions,
        "engine_outcomes": outcome_counts,
        "costs": asdict(cfg.costs),
        "results": {s: summarize([t for t in trades if t.strategy == s]) for s in strategies},
        "by_half": {
            s: {
                "first_half": summarize(
                    [t for t in trades if t.strategy == s and mid and t.session < mid]
                ),
                "second_half": summarize(
                    [t for t in trades if t.strategy == s and mid and t.session >= mid]
                ),
            }
            for s in strategies
        },
        "by_regime": {
            s: {
                r: summarize([t for t in trades if t.strategy == s and t.regime == r])
                for r in sorted({t.regime for t in trades})
            }
            for s in strategies
        },
        "trades": [asdict(t) for t in trades if t.strategy == "engine"],
        "caveats": [
            "Bar-basierte Simulation: Reihenfolge innerhalb eines Bars unbekannt; Stop wird "
            "bei Konflikt zuerst angenommen (konservativ).",
            "Spread/Slippage sind Annahmen (bps), keine gemessenen Quotes.",
            "Einzelsymbol-Test: kein Survivorship-Schutz für Universen; Ergebnisse nicht "
            "auf andere Titel übertragbar.",
            "Mehrere Strategien/Perioden werden verglichen – Mehrfachtest-Problematik beachten.",
        ],
    }
    if provenance.is_demo:
        report["caveats"].insert(
            0, "DEMO-DATEN (simuliert): Ergebnisse haben KEINE Aussagekraft für reale Märkte."
        )
    return to_jsonable(report)


async def _main() -> None:
    from app.core.config import get_settings
    from app.providers.demo import DemoMarketData

    parser = argparse.ArgumentParser(description="Walk-forward backtest (paper evaluation only)")
    parser.add_argument("--symbol", required=True)
    parser.add_argument("--start", required=True, type=date.fromisoformat)
    parser.add_argument("--end", required=True, type=date.fromisoformat)
    parser.add_argument("--step", type=int, default=30)
    parser.add_argument("--provider", choices=["auto", "demo", "alpaca"], default="auto")
    parser.add_argument("--spread-bps", type=float, default=2.0)
    parser.add_argument("--slippage-bps", type=float, default=1.0)
    parser.add_argument("--no-similarity", action="store_true")
    parser.add_argument("--out", default=None)
    args = parser.parse_args()

    settings = get_settings()
    kind = settings.resolved_data_provider() if args.provider == "auto" else args.provider
    provider: MarketDataProvider
    if kind == "alpaca":
        from app.providers.alpaca import AlpacaClient, AlpacaMarketData

        provider = AlpacaMarketData(AlpacaClient(settings))
    else:
        provider = DemoMarketData()
    target, spy, sector = await load_inputs(provider, args.symbol.upper(), args.start, args.end)
    cfg = BacktestConfig(
        symbol=args.symbol.upper(),
        start=args.start,
        end=args.end,
        step_minutes=args.step,
        costs=CostModel(spread_bps=args.spread_bps, slippage_bps=args.slippage_bps),
        run_similarity=not args.no_similarity,
    )
    prov = provider.provenance(Timeframe.M1)
    report = await asyncio.to_thread(run_backtest, cfg, target, spy, sector, prov)
    await provider.aclose()
    text = json.dumps(
        {k: v for k, v in report.items() if k != "trades"}, indent=2, ensure_ascii=False
    )
    print(text)
    if args.out:
        payload = json.dumps(report, indent=2, ensure_ascii=False)
        await asyncio.to_thread(Path(args.out).write_text, payload, encoding="utf-8")


if __name__ == "__main__":
    asyncio.run(_main())
