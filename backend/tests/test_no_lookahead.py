"""Look-ahead / data-leakage guards: results at time t must not change when future data exists."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import numpy as np
import pandas as pd
import pytest

from app.analysis.pipeline import FactInputs, SymbolData, compute_facts, truncate
from app.analysis.similarity import FEATURES, build_feature_table, find_analogs
from app.domain.models import DataKind, Provenance
from tests.conftest import daily_from_minutes, regular_session_frame

AS_OF = datetime(2026, 10, 21, 17, 0, tzinfo=UTC)  # Wednesday 13:00 NY
PROV = Provenance(provider="test", feed="test", data_kind=DataKind.HISTORICAL, is_realtime=False)


@pytest.fixture(scope="module")
def data() -> SymbolData:
    minute = regular_session_frame(90, datetime(2026, 10, 23, 20, 0, tzinfo=UTC), seed=3)
    # daily needs >60 sessions: build from a longer synthetic history
    longer = regular_session_frame(150, datetime(2026, 10, 23, 20, 0, tzinfo=UTC), seed=3)
    return SymbolData("TEST", minute, daily_from_minutes(longer))


def test_truncate_drops_future_and_current_provider_daily_bar(data: SymbolData) -> None:
    t = truncate(data, AS_OF)
    assert t.minute.index[-1] + timedelta(minutes=1) <= AS_OF
    # last daily bar is synthesised from minutes up to as_of, not the provider's full-day bar
    full_day = data.daily.loc[pd.Timestamp("2026-10-21", tz="UTC")]
    synth = t.daily.iloc[-1]
    assert t.daily.index[-1] == pd.Timestamp("2026-10-21", tz="UTC")
    assert synth["close"] == pytest.approx(float(t.minute["close"].iloc[-1]))
    assert synth["volume"] < full_day["volume"]


def test_feature_table_is_causal(data: SymbolData) -> None:
    full = build_feature_table(data.minute, data.daily)
    cut = data.minute[data.minute.index < AS_OF]
    partial = build_feature_table(cut, data.daily[data.daily.index.date < AS_OF.date()])
    common = partial.index[partial.index + timedelta(minutes=5) <= AS_OF]
    a = full.loc[common, FEATURES]
    b = partial.loc[common, FEATURES]
    pd.testing.assert_frame_equal(a, b, check_exact=False, atol=1e-9)


def test_compute_facts_identical_with_or_without_future_data(data: SymbolData) -> None:
    truncated_input = SymbolData(
        "TEST",
        data.minute[data.minute.index < AS_OF],
        data.daily[data.daily.index.date < AS_OF.date()],
    )
    f_future = compute_facts(FactInputs(data, None, None, AS_OF, PROV))
    f_trunc = compute_facts(FactInputs(truncated_input, None, None, AS_OF, PROV))
    for key in ("price", "intraday", "trends", "key_levels", "zones", "level_events"):
        assert f_future[key] == f_trunc[key], key
    assert f_future["similarity"]["horizons"] == f_trunc["similarity"]["horizons"]


def test_precomputed_feature_table_gives_same_similarity(data: SymbolData) -> None:
    table = build_feature_table(data.minute, data.daily)
    with_table = compute_facts(FactInputs(data, None, None, AS_OF, PROV, feature_table=table))
    without = compute_facts(FactInputs(data, None, None, AS_OF, PROV))
    assert with_table["similarity"]["horizons"] == without["similarity"]["horizons"]


def test_analogs_strictly_from_earlier_sessions_one_per_session(data: SymbolData) -> None:
    table = build_feature_table(data.minute, data.daily)
    q_ts = table.index[(table.index + timedelta(minutes=5)) <= AS_OF][-1]
    res = find_analogs(table, query_ts=q_ts, k=30, min_samples=10)
    assert res.status == "ok"
    sessions = [a["session"] for a in res.analogs]
    assert all(s < res.query_session for s in sessions)  # type: ignore[operator]
    assert len(sessions) == len(set(sessions))


def test_random_walk_shows_no_significant_edge(data: SymbolData) -> None:
    table = build_feature_table(data.minute, data.daily)
    rng = np.random.default_rng(0)
    usable = 0
    for ts in rng.choice(table.index[-2000:], size=8, replace=False):
        res = find_analogs(table, query_ts=pd.Timestamp(ts), min_samples=30)
        usable += int(res.statistically_usable)
    # n is small on a pure random walk; "statistically usable" must be rare
    assert usable <= 2
