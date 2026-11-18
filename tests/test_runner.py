import pandas as pd
import pytest

from bot.broker import LiveBroker, PaperBroker
from bot.config import AppConfig
from bot.notify import NullNotifier
from bot.runner import Runner
from bot.store import Store
from tests.test_bot import synthetic


class FakeExchange:
    """Minimal ccxt-like exchange replaying synthetic candles."""
    id = "fake"
    rateLimit = 0

    def __init__(self, df):
        self.df, self.i = df, 300
        self.base, self.quote = 0.0, 1000.0
        self.markets = {"BTC/USDT": {"spot": True, "base": "BTC", "quote": "USDT",
                                     "limits": {"cost": {"min": 5}}}}

    def parse_timeframe(self, tf): return 900
    def milliseconds(self): return self.df.index[self.i].value // 1_000_000 + 1000  # bar i still open
    def load_markets(self): return self.markets
    def fetch_ohlcv(self, symbol, tf, since=None, limit=500):
        d = self.df.iloc[max(0, self.i + 1 - limit): self.i + 1]
        return [[ts.value // 1_000_000, *row] for ts, row in zip(d.index, d[["open","high","low","close","volume"]].values.tolist())]
    def fetch_ticker(self, symbol): return {"last": float(self.df["open"].iloc[self.i])}
    # live-broker surface
    def fetch_balance(self): return {"free": {"BTC": self.base, "USDT": self.quote}}
    def cost_to_precision(self, s, c): return f"{c:.2f}"
    def amount_to_precision(self, s, a): return f"{int(a * 1e5) / 1e5:.5f}"
    def create_market_buy_order_with_cost(self, s, cost):
        px = self.fetch_ticker(s)["last"]; self.quote -= cost; self.base += cost * 0.999 / px
        return {"id": "b1", "average": px}
    def create_market_sell_order(self, s, amt):
        px = self.fetch_ticker(s)["last"]; self.base -= amt; self.quote += amt * px * 0.999
        return {"id": "s1", "average": px}


def run_steps(runner, ex, n):
    runner.restore()
    for _ in range(n):
        runner.step()
        ex.i += 1


def test_paper_runner_trades_and_persists(tmp_path):
    ex = FakeExchange(synthetic(1500))
    cfg = AppConfig(db_path=str(tmp_path / "bot.db"))
    store = Store(tmp_path / "p.db")
    r = Runner(cfg, "paper", exchange=ex, store=store, notifier=NullNotifier())
    run_steps(r, ex, 1100)
    trades = store.trades()
    assert len(trades) > 2
    assert store.get("paper_balances") is not None
    # restart resumes balances
    r2 = Runner(cfg, "paper", exchange=ex, store=store, notifier=NullNotifier())
    r2.restore()
    assert [r2.broker.base, r2.broker.quote] == pytest.approx(store.get("paper_balances"))


def test_first_bar_not_traded(tmp_path):
    ex = FakeExchange(synthetic(600))
    store = Store()
    r = Runner(AppConfig(), "paper", exchange=ex, store=store, notifier=NullNotifier())
    r.restore(); r.step()
    assert store.get("last_bar") is not None and store.trades() == []


def test_live_runner_with_fake_exchange(tmp_path):
    ex = FakeExchange(synthetic(1500))
    store = Store()
    broker = LiveBroker(ex, "BTC/USDT")
    broker._settle = lambda before: broker.balances()
    r = Runner(AppConfig(), "live", exchange=ex, broker=broker, store=store, notifier=NullNotifier())
    run_steps(r, ex, 1100)
    sells = [t for t in store.trades() if t["side"] == "sell"]
    assert sells and all(t["pnl_quote"] is not None for t in sells)
    assert ex.base >= 0 and ex.quote > 0


def test_live_restore_clears_missing_position(tmp_path):
    ex = FakeExchange(synthetic(600))
    store = Store()
    store.put("position", {"qty": 1.0, "entry_price": 100, "cost_quote": 100, "stop": 98,
                           "take": None, "peak": 100, "opened_at": "x"})
    r = Runner(AppConfig(), "live", exchange=ex, broker=LiveBroker(ex, "BTC/USDT"), store=store,
               notifier=NullNotifier())
    r.restore()
    assert r.engine.position is None
