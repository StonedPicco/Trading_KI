"""Out-of-sample evaluation of stored live analyses against later market data.

Analyses are never modified; results are appended to ``signal_outcomes``. Trade simulation is
conservative: entry only if the entry zone is touched, and if stop and target fall inside the
same bar the stop is assumed to be hit first.
"""

from __future__ import annotations

import logging
from collections import defaultdict
from datetime import timedelta
from typing import Any

import numpy as np
import pandas as pd

from app.core.market_time import utcnow
from app.db import repositories as repo
from app.db.models import AnalysisRow, SignalOutcomeRow
from app.db.session import Database
from app.domain.models import Timeframe
from app.services.market_data import MarketDataService
from app.signals.engine import Outcome

log = logging.getLogger(__name__)

HORIZONS_MIN = (15, 60, 240)
DIRECTIONAL = {
    Outcome.LONG_ENTRY.value,
    Outcome.SHORT_ENTRY.value,
    Outcome.BULLISH_SETUP.value,
    Outcome.BEARISH_SETUP.value,
}


def simulate_trade(
    bars: pd.DataFrame, bias: str, entry: tuple[float, float], stop: float, target: float
) -> dict[str, Any]:
    sign = 1 if bias == "long" else -1
    lo, hi = entry
    entered_at = None
    entry_price = None
    for ts, b in bars.iterrows():
        if entered_at is None:
            touched = b["low"] <= hi if sign > 0 else b["high"] >= lo
            if not touched:
                continue
            entered_at = ts
            entry_price = min(hi, b["open"]) if sign > 0 else max(lo, b["open"])
        stop_hit = b["low"] <= stop if sign > 0 else b["high"] >= stop
        tgt_hit = b["high"] >= target if sign > 0 else b["low"] <= target
        if stop_hit:
            return {
                "result": "stop",
                "entry_price": entry_price,
                "exit_price": stop,
                "exit_ts": ts.isoformat(),
                "entered_at": entered_at.isoformat(),
            }
        if tgt_hit:
            return {
                "result": "target",
                "entry_price": entry_price,
                "exit_price": target,
                "exit_ts": ts.isoformat(),
                "entered_at": entered_at.isoformat(),
            }
    if entered_at is None:
        return {"result": "not_triggered"}
    return {
        "result": "open",
        "entry_price": entry_price,
        "exit_price": float(bars["close"].iloc[-1]),
        "entered_at": entered_at.isoformat(),
    }


def evaluate_one(
    row: AnalysisRow, minute: pd.DataFrame, horizon_min: int
) -> SignalOutcomeRow | None:
    start = pd.Timestamp(row.data_as_of)
    end = start + pd.Timedelta(minutes=horizon_min)
    if minute.empty or minute.index[-1] < end - pd.Timedelta(minutes=1):
        return None  # not enough subsequent data yet
    window = minute[(minute.index >= start) & (minute.index < end)]
    ref = row.reference_price
    details: dict[str, Any] = {"bars": len(window)}
    if window.empty or not ref:
        return SignalOutcomeRow(
            analysis_id=row.id,
            horizon_min=horizon_min,
            evaluated_at=utcnow(),
            result="n_a",
            details={"note": "keine Bars"},
        )
    ret = float(window["close"].iloc[-1] / ref - 1) * 100
    mfe = float(window["high"].max() / ref - 1) * 100
    mae = float(window["low"].min() / ref - 1) * 100
    result, r_mult = "n_a", None
    sc = row.scenario
    if row.outcome in DIRECTIONAL and sc.get("entry_zone") and sc.get("stop") and sc.get("targets"):
        trade = simulate_trade(
            window, row.bias, tuple(sc["entry_zone"]), sc["stop"], sc["targets"][0]
        )
        result = trade["result"]
        details["trade"] = trade
        if trade.get("entry_price") is not None:
            risk = abs(trade["entry_price"] - sc["stop"])
            sign = 1 if row.bias == "long" else -1
            if risk > 0:
                r_mult = round(sign * (trade["exit_price"] - trade["entry_price"]) / risk, 3)
    return SignalOutcomeRow(
        analysis_id=row.id,
        horizon_min=horizon_min,
        evaluated_at=utcnow(),
        ret_pct=round(ret, 4),
        mfe_pct=round(mfe, 4),
        mae_pct=round(mae, 4),
        result=result,
        r_multiple=r_mult,
        details=details,
    )


class EvaluationService:
    def __init__(self, db: Database, market: MarketDataService) -> None:
        self.db = db
        self.market = market

    async def run(self) -> int:
        done = 0
        now = utcnow()
        for h in HORIZONS_MIN:
            async with self.db.session() as s:
                pending = await repo.analyses_pending_evaluation(s, h, now - timedelta(minutes=h))
            by_symbol: dict[str, list[AnalysisRow]] = defaultdict(list)
            for row in pending:
                if row.data_kind == self.market.provenance().data_kind.value:
                    by_symbol[row.symbol].append(row)
            for symbol, rows in by_symbol.items():
                minute = await self.market.get(symbol, Timeframe.M1, now)
                async with self.db.session() as s:
                    for row in rows:
                        out = evaluate_one(row, minute, h)
                        if out is not None:
                            await repo.insert_outcome(s, out)
                            done += 1
        if done:
            log.info("signal outcomes evaluated", extra={"count": done})
        return done


def performance_summary(
    analyses: list[AnalysisRow],
    outcomes: dict[Any, list[SignalOutcomeRow]],
    horizon_min: int = 60,
    calibration_min_samples: int = 50,
) -> dict[str, Any]:
    """Engine vs. simple baselines on the same set of evaluated analyses."""
    rows = []
    for a in analyses:
        o = next((x for x in outcomes.get(a.id, []) if x.horizon_min == horizon_min), None)
        if o is None or o.ret_pct is None:
            continue
        trend5 = (a.facts.get("trends") or {}).get("5Min", {}).get("direction")
        rows.append(
            {
                "outcome": a.outcome,
                "bias": a.bias,
                "ret": o.ret_pct,
                "result": o.result,
                "r": o.r_multiple,
                "score": (a.scenario or {}).get("evidence_score", 0.0),
                "momentum_sign": {"up": 1, "down": -1}.get(trend5 or "", 0),
                "data_kind": a.data_kind,
            }
        )
    if not rows:
        return {"horizon_min": horizon_min, "n": 0, "note": "noch keine ausgewerteten Analysen"}
    df = pd.DataFrame(rows)
    sign = df["bias"].map({"long": 1, "short": -1}).fillna(0)
    directional = df[sign != 0]
    engine_ret = directional["ret"] * sign[sign != 0]
    by_outcome = (
        df.groupby("outcome")
        .agg(
            n=("ret", "size"),
            mean_ret_pct=("ret", "mean"),
            hit_target=("result", lambda r: float((r == "target").mean())),
            mean_r=("r", "mean"),
        )
        .reset_index()
        .replace({np.nan: None})
        .to_dict("records")
    )
    momentum = df[df["momentum_sign"] != 0]
    calibration = []
    if len(directional) >= calibration_min_samples:
        bins = pd.cut(directional["score"].abs(), bins=[3, 4, 5, 7, 100], right=False)
        for b, grp in directional.assign(signed=engine_ret).groupby(bins, observed=True):
            if len(grp) >= max(10, calibration_min_samples // 5):
                calibration.append(
                    {
                        "score_bucket": str(b),
                        "n": len(grp),
                        "hit_rate": float((grp["signed"] > 0).mean()),
                    }
                )
    return {
        "horizon_min": horizon_min,
        "n": len(df),
        "data_kinds": sorted(df["data_kind"].unique().tolist()),
        "engine_directional": {
            "n": len(directional),
            "mean_signed_ret_pct": float(engine_ret.mean()) if len(directional) else None,
            "hit_rate": float((engine_ret > 0).mean()) if len(directional) else None,
        },
        "baseline_always_long": {
            "n": len(df),
            "mean_ret_pct": float(df["ret"].mean()),
            "hit_rate": float((df["ret"] > 0).mean()),
        },
        "baseline_momentum_5m": {
            "n": len(momentum),
            "mean_signed_ret_pct": float((momentum["ret"] * momentum["momentum_sign"]).mean())
            if len(momentum)
            else None,
        },
        "baseline_random": {"mean_signed_ret_pct": 0.0, "note": "Erwartungswert ohne Kosten"},
        "by_outcome": by_outcome,
        "calibration": calibration,
        "calibrated": bool(calibration),
        "note": (
            f"Kalibrierung erst ab {calibration_min_samples} ausgewerteten gerichteten Analysen"
            if not calibration
            else "Kalibrierung auf live gespeicherten, nachträglich ausgewerteten Analysen"
        ),
    }
