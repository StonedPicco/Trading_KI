"""Market structure: swing points, HH/HL/LH/LL, trend state, S/R zones, key levels, events.

Swing points need ``right`` bars after the pivot to be confirmed. Each swing therefore carries
``confirmed_at`` and only swings confirmed at or before the analysis time are used.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from datetime import date
from typing import Literal

import numpy as np
import pandas as pd

from app.analysis.indicators import atr, ema, regular_session_mask, rsi

Direction = Literal["up", "down", "sideways"]


@dataclass(frozen=True)
class Swing:
    ts: pd.Timestamp
    confirmed_at: pd.Timestamp
    price: float
    kind: Literal["high", "low"]
    rsi: float | None = None


def swing_points(df: pd.DataFrame, left: int = 3, right: int = 3) -> list[Swing]:
    if len(df) < left + right + 1:
        return []
    highs, lows = df["high"].to_numpy(), df["low"].to_numpy()
    rsi_vals = rsi(df["close"]).to_numpy()
    idx = df.index
    out: list[Swing] = []
    # On ties (equal highs/lows are common with tick-size rounding) the first bar is the pivot.
    for i in range(left, len(df) - right):
        win_h = highs[i - left : i + right + 1]
        win_l = lows[i - left : i + right + 1]
        r = None if np.isnan(rsi_vals[i]) else float(rsi_vals[i])
        if int(np.argmax(win_h)) == left:
            out.append(Swing(idx[i], idx[i + right], float(highs[i]), "high", r))
        if int(np.argmin(win_l)) == left:
            out.append(Swing(idx[i], idx[i + right], float(lows[i]), "low", r))
    return out


@dataclass
class StructureState:
    label: Literal["HH_HL", "LH_LL", "HH_LL", "LH_HL", "insufficient"]
    last_highs: list[float] = field(default_factory=list)
    last_lows: list[float] = field(default_factory=list)

    @property
    def direction(self) -> Direction:
        return {"HH_HL": "up", "LH_LL": "down"}.get(self.label, "sideways")  # type: ignore[return-value]


def classify_structure(swings: list[Swing]) -> StructureState:
    highs = [s.price for s in swings if s.kind == "high"][-2:]
    lows = [s.price for s in swings if s.kind == "low"][-2:]
    if len(highs) < 2 or len(lows) < 2:
        return StructureState("insufficient", highs, lows)
    hh, hl = highs[1] > highs[0], lows[1] > lows[0]
    label = {
        (True, True): "HH_HL",
        (False, False): "LH_LL",
        (True, False): "HH_LL",
        (False, True): "LH_HL",
    }[(hh, hl)]
    return StructureState(label, highs, lows)  # type: ignore[arg-type]


@dataclass
class TrendAssessment:
    timeframe: str
    direction: Direction
    strength: float  # |EMA20 slope| in ATR units per 10 bars, capped
    structure: str
    close: float
    ema20: float | None
    ema50: float | None
    rsi14: float | None
    macd_hist: float | None
    atr14: float | None
    bars: int
    notes: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, object]:
        return asdict(self)


def assess_trend(df: pd.DataFrame, timeframe: str, swing_lr: int = 3) -> TrendAssessment:
    from app.analysis.indicators import macd

    if len(df) < 30:
        return TrendAssessment(
            timeframe,
            "sideways",
            0.0,
            "insufficient",
            float(df["close"].iloc[-1]) if len(df) else float("nan"),
            None,
            None,
            None,
            None,
            None,
            len(df),
            ["zu wenige Bars"],
        )
    # EMA50 converges well within 600 bars; structure only needs the recent swings.
    df = df.iloc[-600:]
    close = df["close"]
    e20, e50 = ema(close, 20), ema(close, 50)
    a = atr(df)
    r = rsi(close)
    hist = macd(close)["hist"]
    last_atr = float(a.iloc[-1]) if pd.notna(a.iloc[-1]) else None
    slope = None
    if last_atr and len(e20.dropna()) > 10:
        slope = float((e20.iloc[-1] - e20.iloc[-11]) / last_atr)
    structure = classify_structure(
        [s for s in swing_points(df, swing_lr, swing_lr) if s.confirmed_at <= df.index[-1]]
    )
    c = float(close.iloc[-1])
    e20v = float(e20.iloc[-1]) if pd.notna(e20.iloc[-1]) else None
    e50v = float(e50.iloc[-1]) if pd.notna(e50.iloc[-1]) else None

    votes = 0
    notes: list[str] = []
    if e20v is not None and e50v is not None:
        votes += 1 if e20v > e50v else -1
        votes += 1 if c > e20v else -1
    if slope is not None:
        if slope > 0.3:
            votes += 1
        elif slope < -0.3:
            votes -= 1
    votes += {"up": 1, "down": -1}.get(structure.direction, 0)
    direction: Direction = "up" if votes >= 3 else "down" if votes <= -3 else "sideways"
    if structure.label in ("HH_LL", "LH_HL"):
        notes.append("Struktur uneinheitlich (Expansion/Kontraktion)")
    return TrendAssessment(
        timeframe=timeframe,
        direction=direction,
        strength=min(abs(slope or 0.0), 5.0),
        structure=structure.label,
        close=c,
        ema20=e20v,
        ema50=e50v,
        rsi14=float(r.iloc[-1]) if pd.notna(r.iloc[-1]) else None,
        macd_hist=float(hist.iloc[-1]) if pd.notna(hist.iloc[-1]) else None,
        atr14=last_atr,
        bars=len(df),
        notes=notes,
    )


@dataclass
class Zone:
    low: float
    high: float
    touches: int
    last_touch: str
    sources: list[str]
    kind: Literal["support", "resistance"] = "support"

    @property
    def mid(self) -> float:
        return (self.low + self.high) / 2

    @property
    def strength(self) -> int:
        return self.touches + (1 if "1Day" in self.sources else 0)

    def to_dict(self) -> dict[str, object]:
        return {**asdict(self), "mid": self.mid, "strength": self.strength}


def cluster_zones(
    swings_by_tf: dict[str, list[Swing]], tolerance: float, price: float, max_zones: int = 8
) -> list[Zone]:
    """Cluster swing prices (all timeframes) into zones of width ~``tolerance``."""
    points = sorted(
        ((s.price, s.ts, tf) for tf, swings in swings_by_tf.items() for s in swings),
        key=lambda p: p[0],
    )
    if not points or tolerance <= 0:
        return []
    clusters: list[list[tuple[float, pd.Timestamp, str]]] = [[points[0]]]
    for p in points[1:]:
        # Complete-linkage style: a zone may not grow wider than 2x tolerance (prevents chaining).
        if p[0] - clusters[-1][0][0] <= 2 * tolerance and p[0] - clusters[-1][-1][0] <= tolerance:
            clusters[-1].append(p)
        else:
            clusters.append([p])
    zones: list[Zone] = []
    for cl in clusters:
        prices = [p[0] for p in cl]
        lo, hi = min(prices), max(prices)
        pad = tolerance * 0.15
        zone = Zone(
            low=lo - pad,
            high=hi + pad,
            touches=len(cl),
            last_touch=max(p[1] for p in cl).isoformat(),
            sources=sorted({p[2] for p in cl}),
        )
        zone.kind = "resistance" if zone.mid > price else "support"
        zones.append(zone)
    zones.sort(key=lambda z: (-z.strength, abs(z.mid - price)))
    return sorted(zones[:max_zones], key=lambda z: z.mid)


@dataclass
class KeyLevels:
    prev_day_high: float | None = None
    prev_day_low: float | None = None
    prev_day_close: float | None = None
    premarket_high: float | None = None
    premarket_low: float | None = None
    session_open: float | None = None
    session_high: float | None = None
    session_low: float | None = None

    def to_dict(self) -> dict[str, float | None]:
        return asdict(self)


def key_levels(minute: pd.DataFrame, daily: pd.DataFrame, session: date) -> KeyLevels:
    kl = KeyLevels()
    prev = daily[daily.index.date < session]
    if not prev.empty:
        kl.prev_day_high = float(prev["high"].iloc[-1])
        kl.prev_day_low = float(prev["low"].iloc[-1])
        kl.prev_day_close = float(prev["close"].iloc[-1])
    today = minute[minute.index.tz_convert("America/New_York").date == session]
    if today.empty:
        return kl
    reg_mask = regular_session_mask(today.index)
    local_minutes = today.index.tz_convert("America/New_York")
    pre = today[(local_minutes.hour * 60 + local_minutes.minute) < 570]
    if not pre.empty:
        kl.premarket_high = float(pre["high"].max())
        kl.premarket_low = float(pre["low"].min())
    reg = today[reg_mask]
    if not reg.empty:
        kl.session_open = float(reg["open"].iloc[0])
        kl.session_high = float(reg["high"].max())
        kl.session_low = float(reg["low"].min())
    return kl


@dataclass
class GapInfo:
    gap_pct: float
    gap_atr: float | None
    direction: Literal["up", "down", "none"]
    filled: bool


def gap_analysis(kl: KeyLevels, daily_atr: float | None) -> GapInfo | None:
    if kl.session_open is None or kl.prev_day_close is None:
        return None
    gap = kl.session_open - kl.prev_day_close
    pct = gap / kl.prev_day_close * 100
    direction: Literal["up", "down", "none"] = (
        "up" if pct > 0.3 else "down" if pct < -0.3 else "none"
    )
    filled = False
    if direction == "up" and kl.session_low is not None:
        filled = kl.session_low <= kl.prev_day_close
    elif direction == "down" and kl.session_high is not None:
        filled = kl.session_high >= kl.prev_day_close
    return GapInfo(
        round(pct, 3), round(gap / daily_atr, 3) if daily_atr else None, direction, filled
    )


@dataclass
class LevelEvent:
    kind: Literal["breakout", "breakdown", "false_breakout_up", "false_breakout_down"]
    level: float
    zone_low: float
    zone_high: float
    bar_ts: str
    volume_confirmed: bool
    rvol: float | None


def detect_level_events(
    bars: pd.DataFrame,
    zones: list[Zone],
    rvol: pd.Series | None,
    lookback: int = 6,
    rvol_confirm: float = 1.5,
) -> list[LevelEvent]:
    """Breakouts / breakdowns / false breakouts through zones within the last ``lookback`` bars.

    * breakout: a bar closes above ``zone.high`` after the previous bar closed at/below it
    * false breakout: a bar's high pierced ``zone.high`` but it and all later bars closed below
    """
    if len(bars) < lookback + 1 or not zones:
        return []
    recent = bars.iloc[-(lookback + 1) :]
    closes, highs, lows = (
        recent["close"].to_numpy(),
        recent["high"].to_numpy(),
        recent["low"].to_numpy(),
    )
    events: list[LevelEvent] = []
    for z in zones:
        for i in range(1, len(recent)):
            ts = recent.index[i]
            rv = (
                float(rvol.loc[ts])
                if rvol is not None and ts in rvol.index and pd.notna(rvol.loc[ts])
                else None
            )
            confirmed = rv is not None and rv >= rvol_confirm
            if closes[i] > z.high >= closes[i - 1] and closes[-1] > z.high:
                events.append(
                    LevelEvent("breakout", z.high, z.low, z.high, ts.isoformat(), confirmed, rv)
                )
            elif closes[i] < z.low <= closes[i - 1] and closes[-1] < z.low:
                events.append(
                    LevelEvent("breakdown", z.low, z.low, z.high, ts.isoformat(), confirmed, rv)
                )
            elif highs[i] > z.high and closes[i - 1] <= z.high and (closes[i:] <= z.high).all():
                events.append(
                    LevelEvent(
                        "false_breakout_up", z.high, z.low, z.high, ts.isoformat(), confirmed, rv
                    )
                )
            elif lows[i] < z.low and closes[i - 1] >= z.low and (closes[i:] >= z.low).all():
                events.append(
                    LevelEvent(
                        "false_breakout_down", z.low, z.low, z.high, ts.isoformat(), confirmed, rv
                    )
                )
    # keep the most recent event per zone
    latest: dict[tuple[float, float], LevelEvent] = {}
    for e in events:
        latest[(e.zone_low, e.zone_high)] = e
    return sorted(latest.values(), key=lambda e: e.bar_ts)


def rsi_divergence(swings: list[Swing]) -> Literal["bearish", "bullish"] | None:
    """Price higher high with lower RSI (bearish) or lower low with higher RSI (bullish)."""
    highs = [s for s in swings if s.kind == "high" and s.rsi is not None][-2:]
    lows = [s for s in swings if s.kind == "low" and s.rsi is not None][-2:]
    if len(highs) == 2 and highs[1].price > highs[0].price and highs[1].rsi < highs[0].rsi - 3:  # type: ignore[operator]
        return "bearish"
    if len(lows) == 2 and lows[1].price < lows[0].price and lows[1].rsi > lows[0].rsi + 3:  # type: ignore[operator]
        return "bullish"
    return None
