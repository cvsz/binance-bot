import os

import numpy as np
import pandas as pd
import pytest

from bot.backtest import run_backtest
from bot.broker import PaperBroker
from bot.config import AppConfig, REAL_MONEY_ENV, REAL_MONEY_VALUE, check_live_allowed
from bot.data import drop_open_candle
from bot.engine import Engine
from bot.indicators import rsi
from bot.risk import RiskConfig, RiskManager
from bot.store import Store
from bot.strategies import BUY, HOLD, SELL, EmaCross, RsiReversion, build_strategy


def synthetic(n=3000, seed=7, start=30000.0):
    rng = np.random.default_rng(seed)
    # regime-switching drift so both trends and chop appear
    drift = np.repeat(rng.choice([-0.0015, 0.0, 0.0015], size=n // 200 + 1), 200)[:n]
    rets = drift + rng.normal(0, 0.006, n)
    close = start * np.exp(np.cumsum(rets))
    open_ = np.r_[start, close[:-1]]
    spread = np.abs(rng.normal(0, 0.003, n)) * close
    high = np.maximum(open_, close) + spread
    low = np.minimum(open_, close) - spread
    idx = pd.date_range("2025-01-01", periods=n, freq="15min", tz="UTC")
    return pd.DataFrame({"open": open_, "high": high, "low": low, "close": close, "volume": 1.0}, index=idx)


# ---- indicators / strategies ---------------------------------------------

def test_rsi_bounds_and_flat():
    s = synthetic()["close"]
    r = rsi(s).dropna()
    assert ((r >= 0) & (r <= 100)).all()
    assert rsi(pd.Series([5.0] * 50)).iloc[-1] == 50.0


@pytest.mark.parametrize("strategy", [EmaCross(), RsiReversion()])
def test_no_lookahead(strategy):
    df = synthetic(1200)
    full = strategy.signals(df)
    for i in range(strategy.warmup + 5, len(df), 97):
        partial = strategy.signals(df.iloc[: i + 1])
        assert partial.iloc[-1] == full.iloc[i], f"signal at {i} depends on future bars"


def test_signals_values_and_warmup():
    s = EmaCross().signals(synthetic())
    assert set(s.unique()) <= {BUY, SELL, HOLD}
    assert (s.iloc[: EmaCross().warmup] == HOLD).all()
    assert (s == BUY).sum() > 0 and (s == SELL).sum() > 0


def test_build_strategy_validation():
    with pytest.raises(ValueError):
        build_strategy("nope")
    with pytest.raises(ValueError):
        build_strategy("ema_cross", {"fast": 30, "slow": 10})


# ---- risk ------------------------------------------------------------------

def test_position_sizing_capped():
    rm = RiskManager(RiskConfig(risk_per_trade_pct=1, stop_loss_pct=2, max_position_pct=25))
    # 1% risk / 2% stop = 50% of equity, capped at 25%
    assert rm.position_size_quote(1000, 1000) == pytest.approx(250)
    assert rm.position_size_quote(1000, 100) == pytest.approx(100)  # limited by free balance


def test_risk_config_requires_stop():
    with pytest.raises(ValueError):
        RiskConfig(stop_loss_pct=0)


def test_daily_loss_halt_and_reset():
    rm = RiskManager(RiskConfig(max_daily_loss_pct=3))
    rm.roll_day("2025-01-01", 1000)
    assert rm.can_enter(990, 10)[0]
    ok, reason = rm.can_enter(960, 10)
    assert not ok and "daily loss" in reason
    rm.roll_day("2025-01-02", 960)
    assert rm.can_enter(960, 10)[0]


# ---- broker / engine -------------------------------------------------------

def test_paper_broker_round_trip_costs():
    b = PaperBroker(1000, fee_pct=0.1, slippage_pct=0.05)
    f = b.buy_quote(500, 100)
    s = b.sell_qty(f.qty, 100)
    assert b.base == 0
    assert 998 < b.quote < 1000  # paid fees+slippage both ways


def make_engine(**risk):
    return Engine("BTC/USDT", PaperBroker(1000, 0, 0), RiskManager(RiskConfig(**risk)), Store(), mode="test")


def test_stop_loss_triggers():
    e = make_engine(stop_loss_pct=2, take_profit_pct=None, cooldown_bars=0)
    e.on_signal("2025-01-01 00:00", BUY, 100)
    assert e.position and e.position.stop == pytest.approx(98)
    e.on_price("2025-01-01 00:15", low=97.5, high=101)
    assert e.position is None
    sell = e.store.trades()[-1]
    assert sell["reason"] == "stop_loss" and sell["pnl_quote"] < 0


def test_gap_below_stop_fills_at_open():
    e = make_engine(stop_loss_pct=2, take_profit_pct=None)
    e.on_signal("2025-01-01 00:00", BUY, 100)
    e.on_price("2025-01-01 00:15", low=90, high=96, open_=95)
    assert e.store.trades()[-1]["price"] == pytest.approx(95)


def test_take_profit_and_trailing():
    e = make_engine(stop_loss_pct=2, take_profit_pct=None, trailing_stop_pct=1)
    e.on_signal("2025-01-01 00:00", BUY, 100)
    e.on_price("t", low=100, high=110)
    assert e.position.stop == pytest.approx(108.9)
    e.on_price("t", low=108.5, high=109)
    assert e.position is None and e.store.trades()[-1]["reason"] == "trailing_stop"

    e2 = make_engine(stop_loss_pct=2, take_profit_pct=3)
    e2.on_signal("2025-01-01 00:00", BUY, 100)
    e2.on_price("t", low=99, high=104)
    assert e2.position is None and e2.store.trades()[-1]["reason"] == "take_profit"


def test_state_persists_across_restart(tmp_path):
    db = tmp_path / "s.db"
    e = Engine("BTC/USDT", PaperBroker(1000, 0, 0), RiskManager(RiskConfig()), Store(db), mode="test")
    e.on_signal("2025-01-01 00:00", BUY, 100)
    e2 = Engine("BTC/USDT", PaperBroker(1000, 0, 0), RiskManager(RiskConfig()), Store(db), mode="test")
    e2.load()
    assert e2.position and e2.position.entry_price == pytest.approx(100)
    assert e2.risk.state.trades_today == 1


# ---- backtest --------------------------------------------------------------

def test_backtest_end_to_end():
    df = synthetic()
    res = run_backtest(df, EmaCross(), RiskConfig())
    st = res.stats
    assert len(res.equity) == len(df)
    assert st["closed_trades"] > 5
    assert st["max_drawdown_pct"] <= 0
    assert (res.equity > 0).all()
    # long-only with position cap: never more than 25% of equity at risk of a 100% wipe
    assert st["max_drawdown_pct"] > -50


def test_backtest_too_short():
    with pytest.raises(ValueError):
        run_backtest(synthetic(30), EmaCross(), RiskConfig())


def test_drop_open_candle():
    df = synthetic(5)
    last_ms = df.index[-1].value // 1_000_000
    assert len(drop_open_candle(df, 900_000, last_ms + 1000)) == 4
    assert len(drop_open_candle(df, 900_000, last_ms + 900_000)) == 5


# ---- safety gates ------------------------------------------------------------

def test_live_gates(monkeypatch):
    for k in ("BINANCE_API_KEY", "BINANCE_API_SECRET", "BINANCE_TESTNET_API_KEY",
              "BINANCE_TESTNET_API_SECRET", REAL_MONEY_ENV):
        monkeypatch.delenv(k, raising=False)
    with pytest.raises(PermissionError):
        check_live_allowed(AppConfig(testnet=True), False)
    monkeypatch.setenv("BINANCE_TESTNET_API_KEY", "k")
    monkeypatch.setenv("BINANCE_TESTNET_API_SECRET", "s")
    check_live_allowed(AppConfig(testnet=True), False)  # testnet ok

    real = AppConfig(testnet=False)
    monkeypatch.setenv("BINANCE_API_KEY", "k")
    monkeypatch.setenv("BINANCE_API_SECRET", "s")
    with pytest.raises(PermissionError):
        check_live_allowed(real, False)          # missing --real-money
    with pytest.raises(PermissionError):
        check_live_allowed(real, True)           # missing env confirmation
    monkeypatch.setenv(REAL_MONEY_ENV, REAL_MONEY_VALUE)
    check_live_allowed(real, True)
