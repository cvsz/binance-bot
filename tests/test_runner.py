import ccxt
import pytest

from bot.broker import LiveBroker
from bot.config import AppConfig
from bot.notify import NullNotifier
from bot.runner import Runner
from bot.store import Store
from tests.test_bot import synthetic


class FakeExchange:
    """Minimal ccxt-like exchange replaying synthetic candles (same call signatures as ccxt)."""
    id = "fake"
    rateLimit = 0

    def __init__(self, df):
        self.df, self.i = df, 300
        self.base, self.quote = 0.0, 1000.0
        self.markets = {"BTC/USDT": {"spot": True, "base": "BTC", "quote": "USDT",
                                     "limits": {"cost": {"min": 5}, "amount": {"min": 1e-5}}}}
        self.orders: dict[str, dict] = {}
        self.fail_submit_after_fill = False   # simulate timeout AFTER the exchange accepted the order
        self.fail_submit_before_fill = False  # simulate timeout BEFORE the order reached the exchange
        self.fail_lookup = False
        self.fail_balance_after_order = False
        self._balance_broken = False

    def parse_timeframe(self, tf):
        return 900

    def milliseconds(self):
        return self.df.index[self.i].value // 1_000_000 + 1000  # bar i still open

    def load_markets(self):
        return self.markets

    def fetch_ohlcv(self, symbol, tf, since=None, limit=500):
        d = self.df.iloc[max(0, self.i + 1 - limit): self.i + 1]
        cols = d[["open", "high", "low", "close", "volume"]].values.tolist()
        return [[ts.value // 1_000_000, *row] for ts, row in zip(d.index, cols, strict=True)]

    def fetch_ticker(self, symbol):
        return {"last": float(self.df["open"].iloc[self.i])}

    # ---- live-broker surface ----
    def fetch_balance(self):
        if self._balance_broken:
            raise ccxt.NetworkError("balance timeout")
        return {"free": {"BTC": self.base, "USDT": self.quote}}

    def cost_to_precision(self, s, c):
        return f"{c:.2f}"

    def amount_to_precision(self, s, a):
        r = int(a * 1e5) / 1e5
        if r <= 0:
            raise ccxt.InvalidOrder("amount must be greater than minimum amount precision")
        return f"{r:.5f}"

    def _place(self, side, params, fill):
        if self.fail_submit_before_fill:
            raise ccxt.RequestTimeout("timeout before send")
        order = fill()
        order["clientOrderId"] = params.get("newClientOrderId")
        self.orders[order["clientOrderId"]] = order
        if self.fail_balance_after_order:
            self._balance_broken = True
        if self.fail_submit_after_fill:
            raise ccxt.RequestTimeout("timeout after send")
        return order

    def create_market_buy_order_with_cost(self, s, cost, params=None):
        def fill():
            px = self.fetch_ticker(s)["last"]
            qty = cost * 0.999 / px
            self.quote -= cost
            self.base += qty
            return {"id": f"b{len(self.orders)}", "average": px, "filled": cost / px, "cost": cost,
                    "status": "closed", "fee": {"currency": "BTC", "cost": cost / px - qty}}
        return self._place("buy", params or {}, fill)

    def create_market_sell_order(self, s, amt, params=None):
        def fill():
            px = self.fetch_ticker(s)["last"]
            self.base -= amt
            self.quote += amt * px * 0.999
            return {"id": f"s{len(self.orders)}", "average": px, "filled": amt, "cost": amt * px,
                    "status": "closed", "fee": {"currency": "USDT", "cost": amt * px * 0.001}}
        return self._place("sell", params or {}, fill)

    def fetch_order(self, id, symbol=None, params=None):
        if self.fail_lookup:
            raise ccxt.NetworkError("lookup timeout")
        cid = (params or {}).get("clientOrderId")
        if cid not in self.orders:
            raise ccxt.OrderNotFound("Order does not exist.")
        return self.orders[cid]


def fast_broker(ex):
    return LiveBroker(ex, "BTC/USDT", settle_attempts=1, settle_delay=0, lookup_attempts=2, lookup_delay=0)


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
    r.restore()
    r.step()
    assert store.get("last_bar") is not None and store.trades() == []


def test_live_runner_with_fake_exchange(tmp_path):
    ex = FakeExchange(synthetic(1500))
    store = Store()
    r = Runner(AppConfig(), "live", exchange=ex, broker=fast_broker(ex), store=store, notifier=NullNotifier())
    run_steps(r, ex, 1100)
    sells = [t for t in store.trades() if t["side"] == "sell"]
    assert sells and all(t["pnl_quote"] is not None for t in sells)
    assert ex.base >= 0 and ex.quote > 0


def test_live_restore_clears_missing_position(tmp_path):
    ex = FakeExchange(synthetic(600))
    store = Store()
    store.put("position", {"qty": 1.0, "entry_price": 100, "cost_quote": 100, "stop": 98,
                           "take": None, "peak": 100, "opened_at": "x"})
    r = Runner(AppConfig(), "live", exchange=ex, broker=fast_broker(ex), store=store,
               notifier=NullNotifier())
    r.restore()
    assert r.engine.position is None
