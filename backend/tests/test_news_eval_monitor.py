from __future__ import annotations

import uuid
from datetime import UTC, datetime

import numpy as np
import pandas as pd
import pytest

from app.backtest.runner import CostModel, _r, simulate
from app.db.models import AnalysisRow
from app.domain.models import NewsItem
from app.news.service import content_hash, jaccard, price_reaction
from app.services.evaluation import evaluate_one, simulate_trade
from app.services.monitor import detect_triggers
from tests.conftest import make_minute_bars, regular_session_frame

T0 = datetime(2026, 10, 22, 14, 0, tzinfo=UTC)


def test_headline_hash_and_similarity() -> None:
    a = NewsItem(id="1", provider="x", published_at=T0, headline="Acme Raises Guidance!")
    b = NewsItem(id="2", provider="y", published_at=T0, headline="acme raises the guidance")
    assert content_hash(a) == content_hash(b)
    assert jaccard("Acme beats Q3 estimates", "Acme beats Q3 estimates, shares jump") >= 0.6


def test_price_reaction_measures_excess_return_and_volume() -> None:
    before = make_minute_bars(np.full(400, 100.0), T0 - pd.Timedelta(minutes=400), volume=1000)
    after = make_minute_bars(np.linspace(100.2, 102, 30), T0, volume=4000)
    stock = pd.concat([before, after])
    bench = make_minute_bars(np.full(430, 50.0), T0 - pd.Timedelta(minutes=400))
    r = price_reaction(stock, bench, T0)
    assert r is not None and r["status"] == "ok"
    assert r["excess_15m_pct"] > 0.5
    assert r["rvol_15m"] == pytest.approx(4.0)
    assert r["significant"] and r["direction"] == "up"


def test_price_reaction_pending_without_later_bars() -> None:
    before = make_minute_bars(np.full(10, 100.0), T0 - pd.Timedelta(minutes=10))
    assert price_reaction(before, None, T0) == {
        "status": "pending",
        "note": "noch keine Kursdaten nach Veröffentlichung",
    }


def test_trade_simulation_is_conservative_when_stop_and_target_in_same_bar() -> None:
    bars = make_minute_bars([100, 100], T0)
    bars.iloc[1, bars.columns.get_loc("high")] = 103
    bars.iloc[1, bars.columns.get_loc("low")] = 97
    out = simulate_trade(bars, "long", (99.5, 100.5), stop=98, target=102)
    assert out["result"] == "stop"
    res, _, _ = simulate(bars, 1, (99.5, 100.5), 98, 102)
    assert res == "stop"


def test_trade_not_triggered_when_entry_zone_never_touched() -> None:
    bars = make_minute_bars(np.linspace(105, 106, 20), T0)
    assert simulate_trade(bars, "long", (100, 101), 99, 104)["result"] == "not_triggered"


def test_simulator_has_no_systematic_bias_on_random_walk() -> None:
    """On a driftless random walk without costs, the mean gross R must be ~0."""
    rng = np.random.default_rng(42)
    rs = []
    for _ in range(600):
        closes = 100 * np.exp(np.cumsum(rng.normal(0, 0.001, 240)))
        bars = make_minute_bars(closes, T0)
        price = float(closes[0])
        sign = int(rng.choice([-1, 1]))
        stop, target = price - sign * 0.5, price + sign * 1.0
        _res, entry, exit_ = simulate(bars.iloc[1:], sign, (price, price), stop, target)
        if entry is not None and exit_ is not None:
            g, _ = _r(sign, entry, exit_, stop, CostModel(0, 0))
            rs.append(g)
    mean, se = float(np.mean(rs)), float(np.std(rs) / np.sqrt(len(rs)))
    assert abs(mean) < 3 * se + 0.05


def test_costs_reduce_r() -> None:
    gross, net = _r(1, 100.0, 102.0, 99.0, CostModel(spread_bps=10, slippage_bps=5))
    assert gross == pytest.approx(2.0)
    assert net < gross


def _analysis(**kw: object) -> AnalysisRow:
    base: dict[str, object] = dict(
        id=uuid.uuid4(),
        symbol="TEST",
        created_at=T0,
        data_as_of=T0,
        trigger="t",
        outcome="long_entry",
        bias="long",
        reference_price=100.0,
        market_phase="regular",
        data_kind="historical",
        scenario={"entry_zone": [99.8, 100.2], "stop": 99.0, "targets": [102.0]},
        facts={},
        narrative={},
        provenance={},
        sources=[],
        input_hash="x",
        engine_version="0",
    )
    base.update(kw)
    return AnalysisRow(**base)


def test_evaluate_one_hits_target() -> None:
    bars = make_minute_bars(np.linspace(100, 103, 61), T0)
    out = evaluate_one(_analysis(), bars, 60)
    assert out is not None
    assert out.result == "target" and out.r_multiple is not None and out.r_multiple > 1.5
    assert out.ret_pct is not None and out.ret_pct > 0


def test_evaluate_one_waits_for_enough_data() -> None:
    bars = make_minute_bars(np.linspace(100, 101, 10), T0)
    assert evaluate_one(_analysis(), bars, 60) is None


def test_monitor_detects_breakout_and_invalidation() -> None:
    minute = regular_session_frame(3, datetime(2026, 10, 22, 20, 0, tzinfo=UTC))
    close = float(minute["close"].iloc[-1])
    last = {
        "id": "a1",
        "reference_price": close - 1.0,
        "facts": {"zones": [{"low": close - 0.8, "high": close - 0.5, "strength": 3}]},
        "scenario": {"bias": "short", "invalidation_price": close - 0.2},
    }
    kinds = {t.kind for t in detect_triggers("TEST", minute, None, last, minute.index[-1])}
    assert {"level_break", "invalidation"} <= kinds
