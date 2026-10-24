"""Historical analog search ("which past situations looked like now, and what happened next?").

Method (see docs/architecture.md §7):
1. Feature vector per completed 5-minute regular-session bar, computed causally.
2. Candidates: earlier sessions only (strict embargo of the query session), same time-of-day
   window, optionally the same volatility regime.
3. Robust scaling fitted on the candidate set only, Euclidean kNN, optional DTW re-ranking on the
   normalised 60-minute price path, at most one analog per session (independence).
4. Forward outcomes (5/15/30/60 min, MFE/MAE) of the analogs vs. the unconditional base rate of
   the same candidate window; Wilson intervals; a probability is only reported as
   "statistically distinguishable" when n is large enough and the interval excludes the base rate.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from datetime import date
from math import sqrt
from typing import Any

import numpy as np
import pandas as pd

from app.analysis.context import regime_series
from app.analysis.indicators import atr, ema, regular_session_mask, relative_volume, rsi
from app.analysis.multitimeframe import resample_intraday
from app.domain.models import Timeframe

FEATURES = [
    "r5",
    "r15",
    "r30",
    "r60",
    "vwap_dist",
    "range_pos",
    "rvol_cum",
    "gap_atr",
    "trend",
    "rsi_c",
]
FEATURE_WEIGHTS = np.array([1.0, 1.2, 1.2, 1.0, 1.2, 0.8, 0.8, 0.6, 1.0, 0.6])
HORIZONS = {5: 1, 15: 3, 30: 6, 60: 12}  # minutes -> 5-min bars
PATH_BARS = 12


def build_feature_table(minute: pd.DataFrame, daily: pd.DataFrame) -> pd.DataFrame:
    """One row per completed 5-min regular-session bar with features and forward outcomes.

    Feature columns use only information available at the bar's close. Outcome columns
    (``fwd_*``, ``mfe``, ``mae``) look forward and must only be read for *candidate* rows.
    """
    m5 = resample_intraday(minute, Timeframe.M5)
    m5 = m5[regular_session_mask(m5.index)].copy()
    if len(m5) < 50:
        return pd.DataFrame()
    session = pd.Series(m5.index.tz_convert("America/New_York").date, index=m5.index)
    m5["session"] = session
    g = m5.groupby("session", sort=False)

    a5 = atr(m5[["open", "high", "low", "close"]])
    close = m5["close"]
    atr_pct = (a5 / close).replace(0, np.nan)
    sess_open = g["open"].transform("first")
    for name, k in (("r5", 1), ("r15", 3), ("r30", 6), ("r60", 12)):
        ref = g["close"].shift(k).fillna(sess_open)
        m5[name] = np.log(close / ref) / atr_pct

    pv = m5["vwap"].fillna(close) * m5["volume"]
    vwap = pv.groupby(session).cumsum() / m5["volume"].groupby(session).cumsum().replace(0, np.nan)
    m5["vwap_dist"] = (close - vwap) / a5
    hod, lod = g["high"].cummax(), g["low"].cummin()
    rng = (hod - lod).replace(0, np.nan)
    m5["range_pos"] = ((close - lod) / rng).fillna(0.5)
    m5["rvol_cum"] = np.log(relative_volume(m5)["rvol_cum"].clip(lower=0.05)).fillna(0.0)

    # Previous *completed* session's close and daily ATR, looked up strictly before each
    # session (works whether or not a bar for the current session exists in ``daily``).
    daily_dates = np.array(daily.index.date)
    d_atr = atr(daily).to_numpy()
    d_close = daily["close"].to_numpy()
    uniq = pd.Index(session.unique())
    pos = np.searchsorted(daily_dates, np.array(uniq), side="left") - 1
    valid = pos >= 0
    prev_close_map = pd.Series(np.where(valid, d_close[np.clip(pos, 0, None)], np.nan), index=uniq)
    prev_atr_map = pd.Series(np.where(valid, d_atr[np.clip(pos, 0, None)], np.nan), index=uniq)
    m5["gap_atr"] = (
        ((sess_open - session.map(prev_close_map)) / session.map(prev_atr_map))
        .fillna(0.0)
        .clip(-5, 5)
    )

    e20 = ema(close, 20)
    m5["trend"] = ((e20 - e20.shift(6)) / a5).clip(-5, 5)
    m5["rsi_c"] = rsi(close) / 100 - 0.5
    local = m5.index.tz_convert("America/New_York")
    m5["mos"] = local.hour * 60 + local.minute - 570 + 5  # minutes since open at bar close
    regimes = regime_series(daily) if len(daily) > 30 else pd.Series(dtype="object")
    m5["regime"] = session.map(regimes).fillna("unknown") if len(regimes) else "unknown"

    # Forward outcomes within the same session.
    for minutes, k in HORIZONS.items():
        m5[f"fwd_{minutes}"] = g["close"].shift(-k) / close - 1
    mfe = np.full(len(m5), np.nan)
    mae = np.full(len(m5), np.nan)
    highs, lows, closes = m5["high"].to_numpy(), m5["low"].to_numpy(), close.to_numpy()
    sess_arr = session.to_numpy()
    for i in range(len(m5)):
        j = i + PATH_BARS
        if j < len(m5) and sess_arr[j] == sess_arr[i]:
            mfe[i] = highs[i + 1 : j + 1].max() / closes[i] - 1
            mae[i] = lows[i + 1 : j + 1].min() / closes[i] - 1
    m5["mfe"], m5["mae"] = mfe, mae
    m5["log_close"] = np.log(close)
    return m5.replace([np.inf, -np.inf], np.nan)


def dtw_distance(a: np.ndarray, b: np.ndarray, band: int = 3) -> float:
    n, m = len(a), len(b)
    cost = np.full((n + 1, m + 1), np.inf)
    cost[0, 0] = 0.0
    for i in range(1, n + 1):
        for j in range(max(1, i - band), min(m, i + band) + 1):
            d = abs(a[i - 1] - b[j - 1])
            cost[i, j] = d + min(cost[i - 1, j], cost[i, j - 1], cost[i - 1, j - 1])
    return float(cost[n, m])


def _norm_path(x: np.ndarray) -> np.ndarray:
    sd = x.std()
    return (x - x.mean()) / sd if sd > 0 else x - x.mean()


def wilson_interval(successes: int, n: int, z: float = 1.96) -> tuple[float, float]:
    if n == 0:
        return (0.0, 1.0)
    p = successes / n
    denom = 1 + z**2 / n
    centre = (p + z**2 / (2 * n)) / denom
    half = z * sqrt(p * (1 - p) / n + z**2 / (4 * n**2)) / denom
    return (max(0.0, centre - half), min(1.0, centre + half))


@dataclass
class HorizonStats:
    horizon_min: int
    n: int
    mean_pct: float | None
    median_pct: float | None
    q25_pct: float | None
    q75_pct: float | None
    hit_rate: float | None
    ci_low: float | None
    ci_high: float | None
    base_hit_rate: float | None
    base_mean_pct: float | None
    distinguishable: bool


@dataclass
class SimilarityResult:
    status: str  # ok | insufficient_history | not_regular_session
    query_ts: str | None = None
    query_session: str | None = None
    candidates: int = 0
    n_analogs: int = 0
    regime_filter: str | None = None
    match_quality: float | None = None  # mean analog distance / median candidate distance
    horizons: list[HorizonStats] = field(default_factory=list)
    mfe_mean_pct: float | None = None
    mae_mean_pct: float | None = None
    analogs: list[dict[str, Any]] = field(default_factory=list)
    query_features: dict[str, float] = field(default_factory=dict)
    statistically_usable: bool = False
    limitations: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def _pct(x: float | None) -> float | None:
    return None if x is None or not np.isfinite(x) else round(float(x) * 100, 3)


def find_analogs(
    table: pd.DataFrame,
    query_ts: pd.Timestamp | None = None,
    k: int = 40,
    tod_window: int = 30,
    use_regime: bool = True,
    use_dtw: bool = True,
    min_samples: int = 30,
) -> SimilarityResult:
    if table.empty:
        return SimilarityResult(
            status="insufficient_history", limitations=["keine Intraday-Historie"]
        )
    if query_ts is None:
        query_ts = table.index[-1]
    if query_ts not in table.index:
        prior = table.index[table.index <= query_ts]
        if prior.empty:
            return SimilarityResult(status="insufficient_history")
        query_ts = prior[-1]
    q = table.loc[query_ts]
    q_session: date = q["session"]
    if q[FEATURES].isna().any():
        return SimilarityResult(
            status="insufficient_history",
            query_ts=query_ts.isoformat(),
            limitations=["Merkmale am Abfragezeitpunkt unvollständig"],
        )

    # Strict embargo: only sessions strictly before the query session.
    cand = table[(table["session"] < q_session)]
    cand = cand[(cand["mos"] - q["mos"]).abs() <= tod_window]
    cand = cand.dropna(subset=[*FEATURES, "fwd_30"])
    limitations: list[str] = []
    regime_filter = None
    if use_regime and q["regime"] != "unknown":
        same = cand[cand["regime"] == q["regime"]]
        if same["session"].nunique() >= 2 * min_samples:
            cand, regime_filter = same, str(q["regime"])
        else:
            limitations.append("Regime-Filter gelockert (zu wenige Sessions im selben Regime)")
    n_sessions = int(cand["session"].nunique())
    if n_sessions < 10:
        return SimilarityResult(
            status="insufficient_history",
            query_ts=query_ts.isoformat(),
            query_session=str(q_session),
            candidates=len(cand),
            limitations=[f"nur {n_sessions} vergleichbare Sessions in der Historie"],
        )

    x = cand[FEATURES].to_numpy(dtype=float)
    med = np.median(x, axis=0)
    iqr = np.subtract(*np.percentile(x, [75, 25], axis=0))
    iqr[iqr == 0] = 1.0
    xs = (x - med) / iqr * FEATURE_WEIGHTS
    qs = (q[FEATURES].to_numpy(dtype=float) - med) / iqr * FEATURE_WEIGHTS
    dist = np.sqrt(((xs - qs) ** 2).sum(axis=1))
    cand = cand.assign(distance=dist)

    # Best match per session (independence), then top-k.
    best = cand.sort_values("distance").groupby("session", sort=False).head(1)
    pool = best.nsmallest(min(len(best), k * 3), "distance")
    if use_dtw:
        q_path = _query_path(table, query_ts)
        if q_path is not None:
            dtw = []
            for ts in pool.index:
                p = _query_path(table, ts)
                dtw.append(
                    dtw_distance(_norm_path(q_path), _norm_path(p)) if p is not None else np.nan
                )
            pool = pool.assign(dtw=dtw)
            f_rank = pool["distance"].rank(pct=True)
            d_rank = pool["dtw"].rank(pct=True).fillna(1.0)
            pool = pool.assign(score=0.7 * f_rank + 0.3 * d_rank).sort_values("score")
    analogs = pool.head(k)
    median_cand = float(np.median(dist)) if len(dist) else np.nan
    quality = float(analogs["distance"].mean() / median_cand) if median_cand > 0 else None

    base = cand  # unconditional base rate: the whole candidate window
    horizons: list[HorizonStats] = []
    for minutes in HORIZONS:
        col = f"fwd_{minutes}"
        vals = analogs[col].dropna().to_numpy()
        bvals = base[col].dropna().to_numpy()
        n = len(vals)
        hits = int((vals > 0).sum())
        lo, hi = wilson_interval(hits, n) if n else (None, None)
        base_hit = float((bvals > 0).mean()) if len(bvals) else None
        disting = bool(
            n >= min_samples
            and base_hit is not None
            and lo is not None
            and hi is not None
            and (lo > base_hit or hi < base_hit)
        )
        horizons.append(
            HorizonStats(
                horizon_min=minutes,
                n=n,
                mean_pct=_pct(vals.mean()) if n else None,
                median_pct=_pct(np.median(vals)) if n else None,
                q25_pct=_pct(np.percentile(vals, 25)) if n else None,
                q75_pct=_pct(np.percentile(vals, 75)) if n else None,
                hit_rate=round(hits / n, 4) if n else None,
                ci_low=round(lo, 4) if lo is not None else None,
                ci_high=round(hi, 4) if hi is not None else None,
                base_hit_rate=round(base_hit, 4) if base_hit is not None else None,
                base_mean_pct=_pct(bvals.mean()) if len(bvals) else None,
                distinguishable=disting,
            )
        )
    n_analogs = len(analogs)
    if n_analogs < min_samples:
        limitations.append(f"Stichprobe klein (n={n_analogs} < {min_samples}): nur deskriptiv")
    limitations.append(
        "Vier Horizonte werden gleichzeitig geprüft (Mehrfachtests); "
        "Einzelsignifikanz vorsichtig lesen"
    )
    limitations.append("Analogien stammen nur aus der Historie desselben Symbols")
    usable = any(h.distinguishable for h in horizons) and (quality is not None and quality < 0.6)

    return SimilarityResult(
        status="ok",
        query_ts=query_ts.isoformat(),
        query_session=str(q_session),
        candidates=len(cand),
        n_analogs=n_analogs,
        regime_filter=regime_filter,
        match_quality=round(quality, 3) if quality is not None else None,
        horizons=horizons,
        mfe_mean_pct=_pct(analogs["mfe"].mean()),
        mae_mean_pct=_pct(analogs["mae"].mean()),
        analogs=[
            {
                "ts": ts.isoformat(),
                "session": str(row["session"]),
                "distance": round(float(row["distance"]), 3),
                "regime": row["regime"],
                **{f"fwd_{m}_pct": _pct(row[f"fwd_{m}"]) for m in HORIZONS},
                "mfe_pct": _pct(row["mfe"]),
                "mae_pct": _pct(row["mae"]),
            }
            for ts, row in analogs.head(15).iterrows()
        ],
        query_features={f: round(float(q[f]), 4) for f in FEATURES},
        statistically_usable=usable,
        limitations=limitations,
    )


def _query_path(table: pd.DataFrame, ts: pd.Timestamp) -> np.ndarray | None:
    pos = table.index.get_loc(ts)
    if not isinstance(pos, int) or pos < PATH_BARS - 1:
        return None
    window = table.iloc[pos - PATH_BARS + 1 : pos + 1]
    if window["session"].nunique() != 1:
        return None
    return window["log_close"].to_numpy()
