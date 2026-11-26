"""Bar-by-bar backtester using the same Engine as live trading.

Execution model: a signal produced at the close of bar i is executed at the OPEN
of bar i+1 (what a live bot can actually achieve). Stops/targets are checked
intrabar against high/low, assuming the stop is hit first when both are touched.
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from typing import cast

import pandas as pd

from .broker import PaperBroker
from .engine import Engine
from .risk import RiskConfig, RiskManager
from .store import Store
from .strategies import HOLD, Strategy


@dataclass
class BacktestResult:
    equity: pd.Series
    trades: list[dict]
    stats: dict


def _ts(idx) -> str:
    return pd.Timestamp(idx).strftime("%Y-%m-%d %H:%M")


def run_backtest(
    df: pd.DataFrame,
    strategy: Strategy,
    risk_cfg: RiskConfig,
    symbol: str = "BTC/USDT",
    starting_quote: float = 1000.0,
    fee_pct: float = 0.1,
    slippage_pct: float = 0.05,
) -> BacktestResult:
    if len(df) <= strategy.warmup + 2:
        raise ValueError(f"need more than {strategy.warmup + 2} candles for this strategy, got {len(df)}")
    signals = strategy.signals(df)
    broker = PaperBroker(starting_quote, fee_pct, slippage_pct)
    engine = Engine(symbol, broker, RiskManager(risk_cfg), Store(), mode="backtest", batch_mode=True)

    equity = []
    pending = HOLD
    for idx, bar in zip(df.index, df.itertuples(index=False), strict=True):
        ts = _ts(idx)
        open_price = cast(float, bar.open)
        high_price = cast(float, bar.high)
        low_price = cast(float, bar.low)
        close_price = cast(float, bar.close)
        engine.on_signal(ts, pending, open_price, mark_price=close_price)
        engine.on_price(ts, low_price, high_price, open_=open_price)
        pending = int(signals.loc[idx])
        equity.append(engine.equity(close_price))
    engine.save(force=True)  # persist final state once, not every bar

    eq = pd.Series(equity, index=df.index, name="equity")
    trades = engine.store.trades()
    return BacktestResult(eq, trades, compute_stats(eq, trades, df, starting_quote))


def compute_stats(eq: pd.Series, trades: list[dict], df: pd.DataFrame, start: float) -> dict:
    sells = [t for t in trades if t["side"] == "sell"]
    pnls = [t["pnl_quote"] for t in sells]
    wins = [p for p in pnls if p > 0]
    losses = [p for p in pnls if p <= 0]
    dd = (eq / eq.cummax() - 1).min() * 100
    rets = eq.pct_change().dropna()
    bars_per_year = _bars_per_year(df.index)
    sharpe = (rets.mean() / rets.std() * math.sqrt(bars_per_year)) if rets.std() > 0 else 0.0
    return {
        "start_equity": round(start, 2),
        "end_equity": round(float(eq.iloc[-1]), 2),
        "total_return_pct": round((eq.iloc[-1] / start - 1) * 100, 2),
        "buy_and_hold_pct": round((df["close"].iloc[-1] / df["close"].iloc[0] - 1) * 100, 2),
        "max_drawdown_pct": round(float(dd), 2),
        "closed_trades": len(sells),
        "win_rate_pct": round(len(wins) / len(sells) * 100, 1) if sells else 0.0,
        "profit_factor": round(sum(wins) / abs(sum(losses)), 2) if losses and sum(losses) != 0 else None,
        "avg_trade_pnl": round(sum(pnls) / len(pnls), 2) if pnls else 0.0,
        "sharpe": round(float(sharpe), 2),
        "exit_reasons": pd.Series([t["reason"] for t in sells]).value_counts().to_dict() if sells else {},
    }


def _bars_per_year(index: pd.Index) -> float:
    if len(index) < 2:
        return 365.0
    step = pd.Series(index).diff().median()
    step_td = step if isinstance(step, pd.Timedelta) else pd.Timedelta(0)
    return pd.Timedelta(days=365) / step_td if step_td and step_td > pd.Timedelta(0) else 365.0
