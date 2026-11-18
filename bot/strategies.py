"""Trading strategies. Each returns a signal per bar: BUY (1), SELL (-1), HOLD (0).

Signals at bar i are computed from bars <= i only, so the same code is used for
backtests and live trading without lookahead bias.
"""
from __future__ import annotations

import pandas as pd

from .indicators import ema, rsi

BUY, SELL, HOLD = 1, -1, 0


class Strategy:
    name = "base"
    warmup = 0

    def signals(self, df: pd.DataFrame) -> pd.Series:  # pragma: no cover - interface
        raise NotImplementedError


class EmaCross(Strategy):
    """Trend following: buy when fast EMA crosses above slow EMA (with RSI filter),
    sell when it crosses back below."""

    name = "ema_cross"

    def __init__(self, fast: int = 9, slow: int = 21, rsi_period: int = 14, rsi_max_entry: float = 70):
        if not 1 < fast < slow:
            raise ValueError("ema_cross requires 1 < fast < slow")
        if rsi_period < 2 or not 0 < rsi_max_entry <= 100:
            raise ValueError("ema_cross requires rsi_period >= 2 and 0 < rsi_max_entry <= 100")
        self.fast, self.slow = fast, slow
        self.rsi_period, self.rsi_max_entry = rsi_period, rsi_max_entry
        self.warmup = slow * 3

    def signals(self, df: pd.DataFrame) -> pd.Series:
        close = df["close"]
        f, s = ema(close, self.fast), ema(close, self.slow)
        r = rsi(close, self.rsi_period)
        above = (f > s) & s.notna()
        prev = above.shift(1, fill_value=False)
        sig = pd.Series(HOLD, index=df.index, dtype="int64")
        sig[above & ~prev & (r < self.rsi_max_entry)] = BUY
        sig[~above & prev] = SELL
        sig.iloc[: self.warmup] = HOLD
        return sig


class RsiReversion(Strategy):
    """Mean reversion inside an uptrend: buy when RSI recovers from oversold while
    price is above the trend EMA; sell when RSI reaches overbought."""

    name = "rsi_reversion"

    def __init__(self, rsi_period: int = 14, oversold: float = 30, overbought: float = 70, trend_ema: int = 200):
        if not 0 < oversold < overbought < 100:
            raise ValueError("rsi_reversion requires 0 < oversold < overbought < 100")
        if rsi_period < 2 or trend_ema < 2:
            raise ValueError("rsi_reversion requires rsi_period >= 2 and trend_ema >= 2")
        self.rsi_period, self.oversold, self.overbought = rsi_period, oversold, overbought
        self.trend_ema = trend_ema
        self.warmup = max(trend_ema, rsi_period * 3)

    def signals(self, df: pd.DataFrame) -> pd.Series:
        close = df["close"]
        r = rsi(close, self.rsi_period)
        trend = ema(close, self.trend_ema)
        prev_r = r.shift(1)
        sig = pd.Series(HOLD, index=df.index, dtype="int64")
        sig[(prev_r <= self.oversold) & (r > self.oversold) & (close > trend)] = BUY
        sig[r >= self.overbought] = SELL
        sig.iloc[: self.warmup] = HOLD
        return sig


STRATEGIES = {cls.name: cls for cls in (EmaCross, RsiReversion)}


def build_strategy(name: str, params: dict | None = None) -> Strategy:
    if name not in STRATEGIES:
        raise ValueError(f"unknown strategy '{name}'. available: {', '.join(STRATEGIES)}")
    try:
        return STRATEGIES[name](**(params or {}))
    except TypeError as exc:  # unknown/misspelled parameter
        raise ValueError(f"invalid params for strategy '{name}': {exc}") from exc
