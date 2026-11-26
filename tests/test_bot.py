import numpy as np
import pandas as pd
import pytest

from bot.backtest import run_backtest
from bot.broker import PaperBroker
from bot.config import AppConfig, REAL_MONEY_ENV, REAL_MONEY_VALUE, check_live_allowed
from bot.data import drop_open_candle
from bot.engine import Engine
from bot.indicators import (
    atr,
    bollinger_bands,
    macd,
    rate_of_change,
    rsi,
    sma,
    stochastic,
    vwap,
    williams_r,
)
from bot.money import Money, thb, usdt
from bot.risk import RiskConfig, RiskManager
from bot.store import Store
from bot.strategies import BUY, HOLD, SELL, EmaCross, RsiReversion, build_strategy
from bot.types import SignalAction, Side, TradingMode


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
    b.sell_qty(f.qty, 100)
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
    # a bar whose low is ABOVE the raised stop must keep the position
    e.on_price("t", low=109.5, high=110)
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
    for k in (
        "BINANCE_API_KEY",
        "BINANCE_API_SECRET",
        "BINANCE_TESTNET_API_KEY",
        "BINANCE_TESTNET_API_SECRET",
        REAL_MONEY_ENV,
    ):
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
        check_live_allowed(real, False)  # missing --real-money
    with pytest.raises(PermissionError):
        check_live_allowed(real, True)  # missing env confirmation
    monkeypatch.setenv(REAL_MONEY_ENV, REAL_MONEY_VALUE)
    check_live_allowed(real, True)


# ---- money ----------------------------------------------------------------


def test_money_add_subtract_same_currency():
    a = usdt(100.50)
    b = usdt(25.25)
    assert (a + b).to_float() == pytest.approx(125.75)
    assert (a - b).to_float() == pytest.approx(75.25)


def test_money_currency_mismatch_raises():
    with pytest.raises(ValueError, match="currency mismatch"):
        usdt(100) + thb(100)


def test_money_multiply_divide():
    assert usdt(100) * 2 == usdt(200)
    assert 2 * usdt(100) == usdt(200)
    assert usdt(100) / 4 == usdt(25)


def test_money_zero_and_from_float():
    assert usdt(0).to_float() == 0.0
    assert Money.from_float(0.1 + 0.2).to_float() == pytest.approx(0.3)


def test_money_comparison():
    assert usdt(10) < usdt(20)
    assert usdt(20) > usdt(10)
    assert usdt(10) <= usdt(10)
    assert usdt(10) >= usdt(10)
    assert usdt(10) == usdt(10)


# ---- types ----------------------------------------------------------------


def test_side_enum():
    assert Side.BUY == "buy"
    assert Side.SELL == "sell"
    assert {Side.BUY, Side.SELL} == {Side.BUY, Side.SELL}


def test_trading_mode_enum():
    assert TradingMode.PAPER == "paper"
    assert TradingMode.SANDBOX == "sandbox"
    assert TradingMode.LIVE == "live"


def test_signal_action_enum():
    assert SignalAction.BUY == "buy"
    assert SignalAction.SELL == "sell"
    assert SignalAction.HOLD == "hold"


# ---- new indicators -------------------------------------------------------


def test_sma_indicator():
    s = pd.Series([1.0, 2.0, 3.0, 4.0, 5.0])
    result = sma(s, 3)
    assert result.iloc[2] == pytest.approx(2.0)
    assert result.iloc[4] == pytest.approx(4.0)
    assert result.iloc[0] is pd.NA or pd.isna(result.iloc[0])


def test_macd_indicator():
    s = pd.Series([1.0, 2.0, 3.0, 4.0, 5.0, 6.0, 7.0, 8.0, 9.0, 10.0])
    macd_line, signal_line, hist = macd(s, fast=3, slow=5, signal=2)
    assert len(macd_line) == len(s)
    assert len(signal_line) == len(s)
    assert len(hist) == len(s)


def test_bollinger_bands_indicator():
    s = pd.Series([1.0, 2.0, 3.0, 4.0, 5.0, 6.0, 7.0, 8.0, 9.0, 10.0])
    upper, middle, lower = bollinger_bands(s, period=3)
    assert len(upper) == len(s)
    assert len(middle) == len(s)
    assert len(lower) == len(s)
    assert (upper.dropna() >= middle.dropna()).all()
    assert (lower.dropna() <= middle.dropna()).all()


def test_atr_indicator():
    high = pd.Series([10.0, 11.0, 12.0, 13.0, 14.0])
    low = pd.Series([9.0, 10.0, 11.0, 12.0, 13.0])
    close = pd.Series([9.5, 10.5, 11.5, 12.5, 13.5])
    result = atr(high, low, close, period=2)
    assert len(result) == len(high)
    assert (result.dropna() >= 0).all()


def test_stochastic_indicator():
    high = pd.Series([10.0, 11.0, 12.0, 13.0, 14.0])
    low = pd.Series([9.0, 10.0, 11.0, 12.0, 13.0])
    close = pd.Series([9.5, 10.5, 11.5, 12.5, 13.5])
    k, d = stochastic(high, low, close, k_period=3, d_period=2)
    assert len(k) == len(high)
    assert len(d) == len(high)


def test_williams_r_indicator():
    high = pd.Series([10.0, 11.0, 12.0, 13.0, 14.0])
    low = pd.Series([9.0, 10.0, 11.0, 12.0, 13.0])
    close = pd.Series([9.5, 10.5, 11.5, 12.5, 13.5])
    result = williams_r(high, low, close, period=3)
    assert len(result) == len(high)
    assert (result.dropna() <= 0).all()
    assert (result.dropna() >= -100).all()


def test_vwap_indicator():
    high = pd.Series([10.0, 11.0, 12.0])
    low = pd.Series([9.0, 10.0, 11.0])
    close = pd.Series([9.5, 10.5, 11.5])
    volume = pd.Series([100.0, 200.0, 300.0])
    result = vwap(high, low, close, volume)
    assert len(result) == len(high)
    assert (result > 0).all()


def test_rate_of_change_indicator():
    s = pd.Series([100.0, 110.0, 121.0, 133.1])
    result = rate_of_change(s, period=1)
    assert len(result) == len(s)
    assert result.iloc[1] == pytest.approx(0.10)  # 10% change


# ---- new indicators are causal (no lookahead) ------------------------------


def test_single_series_indicators_no_lookahead():
    df = synthetic(300)
    single_series = [
        (sma, (3,)),
        (rsi, (14,)),
        (rate_of_change, (2,)),
    ]
    for fn, args in single_series:
        full = fn(df["close"], *args)
        for i in range(50, len(df), 37):
            partial = fn(df["close"].iloc[: i + 1], *args)
            assert partial.iloc[-1] == full.iloc[i], f"{fn.__name__} has lookahead at {i}"


def test_multi_series_indicators_no_lookahead():
    df = synthetic(300)
    # stochastic returns (k, d) tuple
    full_k, _ = stochastic(df["high"], df["low"], df["close"], 3, 2)
    for i in range(50, len(df), 37):
        partial_k, _ = stochastic(
            df["high"].iloc[: i + 1],
            df["low"].iloc[: i + 1],
            df["close"].iloc[: i + 1],
            3,
            2,
        )
        assert partial_k.iloc[-1] == full_k.iloc[i], "stochastic has lookahead at {i}"
    # williams_r returns a single Series
    full_wr = williams_r(df["high"], df["low"], df["close"], 3)
    for i in range(50, len(df), 37):
        partial_wr = williams_r(
            df["high"].iloc[: i + 1],
            df["low"].iloc[: i + 1],
            df["close"].iloc[: i + 1],
            3,
        )
        assert partial_wr.iloc[-1] == full_wr.iloc[i], "williams_r has lookahead at {i}"


def test_atr_indicator_no_lookahead():
    df = synthetic(300)
    full = atr(df["high"], df["low"], df["close"], 14)
    for i in range(50, len(df), 37):
        partial = atr(
            df["high"].iloc[: i + 1],
            df["low"].iloc[: i + 1],
            df["close"].iloc[: i + 1],
            14,
        )
        assert partial.iloc[-1] == full.iloc[i], "atr has lookahead at {i}"
