"""Production-hardening regression tests: fill confirmation, stop reasons, reconciliation."""
import ccxt
import pytest

import run
from bot.broker import LiveBroker, PaperBroker
from bot.config import AppConfig
from bot.engine import RESUME_KEY, Engine
from bot.notify import NullNotifier
from bot.risk import Position, RiskConfig, RiskManager
from bot.runner import Runner
from bot.store import Store
from bot.strategies import BUY
from tests.test_bot import make_engine, synthetic
from tests.test_hardening import RecordingNotifier, live_engine, write_cfg
from tests.test_runner import FakeExchange, fast_broker


def test_runner_price_check_has_no_gap_open(tmp_path):
    """Live checks a single last price, never a bar open (which would fake a gap)."""
    ex = FakeExchange(synthetic(600))
    r = Runner(AppConfig(), "paper", exchange=ex, store=Store(tmp_path / "p.db"), notifier=NullNotifier())
    seen = {}
    original = r.engine.on_price

    def spy(ts, low, high, open_=None):
        seen["open_"] = open_
        return original(ts, low, high, open_)

    r.engine.on_price = spy
    r.restore()
    r.step()
    assert "open_" in seen and seen["open_"] is None


class PartialExchange(FakeExchange):
    """Returns a partial balance delta before the full one."""

    def __init__(self, df):
        super().__init__(df)
        self.reads = 0

    def fetch_ticker(self, symbol):
        return {"last": 100.0}

    def fetch_balance(self):
        self.reads += 1
        if self.reads == 1:
            return {"free": {"BTC": 0.0, "USDT": 1000.0}}
        if self.reads == 2:
            return {"free": {"BTC": 0.4, "USDT": 960.0}}  # partial fill
        return {"free": {"BTC": 0.999, "USDT": 900.0}}     # full fill


def test_settle_waits_for_full_fill_not_first_delta():
    ex = PartialExchange(synthetic(600))
    broker = LiveBroker(ex, "BTC/USDT", settle_attempts=3, settle_delay=0,
                        lookup_attempts=2, lookup_delay=0)
    fill = broker.buy_quote(100, 100)
    assert fill.qty == pytest.approx(0.999)   # not the partial 0.4
    assert ex.reads >= 3


def test_trailing_stop_breached_in_same_bar_exits():
    e = make_engine(take_profit_pct=None, trailing_stop_pct=1)
    e.on_signal("2025-01-01 00:00", BUY, 100)  # initial stop 98
    # high 110 raises the stop to 108.9, but low 105 is already below it
    e.on_price("2025-01-01 00:15", low=105, high=110, open_=100)
    assert e.position is None
    trade = e.store.trades()[-1]
    assert trade["reason"] == "trailing_stop"
    assert trade["price"] == pytest.approx(108.9)


def test_resume_request_deleted_only_after_save(tmp_path):
    db = tmp_path / "s.db"
    store = Store(db)
    store.put(RESUME_KEY, "x")
    e = Engine("BTC/USDT", PaperBroker(1000, 0, 0), RiskManager(RiskConfig()), store, mode="t")
    e.risk.halt("manual")
    calls = []
    original_save, original_delete = e.save, store.delete
    e.save = lambda: (calls.append("save"), original_save())[1]
    store.delete = lambda key: (calls.append("delete"), original_delete(key))[1]
    e.apply_resume_request(100.0)
    assert calls == ["save", "delete"]
    assert e.risk.state.halted_reason is None and store.get(RESUME_KEY) is None


def test_sell_unknown_state_halts_then_recovers_pnl():
    ex = FakeExchange(synthetic(600))
    ex.fail_submit_after_fill = True
    ex.fail_lookup = True
    e = live_engine(ex)
    ex.base = 1.0
    e.position = Position(qty=1.0, entry_price=100, cost_quote=100, stop=98, take=None,
                          peak=100, opened_at="x")
    e.on_price("t", low=97, high=97)  # stop hit -> sell with unknown result
    assert e.position is not None
    assert e.position.pending_order_id
    assert "unknown" in e.risk.state.halted_reason
    assert any("HALTED" in m for m in e.notifier.msgs)

    ex.fail_lookup = False
    e.on_price("t2", low=97, high=97)  # retry reconciles the lost fill
    assert e.position is None
    sell = e.store.trades()[-1]
    assert sell["side"] == "sell" and sell["pnl_quote"] is not None


def test_cli_live_gate_refuses_without_keys(tmp_path, monkeypatch):
    for k in ("BINANCE_API_KEY", "BINANCE_API_SECRET"):
        monkeypatch.delenv(k, raising=False)
    cfg = write_cfg(tmp_path, body="exchange:\n  testnet: false\n")
    assert run.main(["-c", str(cfg), "live"]) == 2


def test_backoff_caps_at_600():
    r = Runner(AppConfig(), "paper", exchange=FakeExchange(synthetic(600)),
               store=Store(), notifier=NullNotifier())

    def outage():
        raise ccxt.NetworkError("network down")

    r.step = outage
    assert r.tick(400) == 600
    assert r.tick(700) == 600
    assert r.exit_code == 0 and not r._stop


def test_untracked_wallet_balance_halts_entries():
    ex = FakeExchange(synthetic(600))
    ex.base = 1.0  # coins in wallet but no stored position
    r = Runner(AppConfig(), "live", exchange=ex, broker=fast_broker(ex),
               store=Store(), notifier=RecordingNotifier())
    r.restore()
    assert r.engine.position is None
    assert "untracked" in r.engine.risk.state.halted_reason
    assert any("HALTED" in m for m in r.engine.notifier.msgs)


def test_live_sizing_keeps_fee_headroom():
    ex = FakeExchange(synthetic(600))
    ex.base, ex.quote = 0.0, 1000.0
    cfg = RiskConfig(risk_per_trade_pct=5, stop_loss_pct=2, max_position_pct=100)
    e = Engine("BTC/USDT", fast_broker(ex), RiskManager(cfg), Store(), mode="live-test")
    e.on_signal("2025-01-01 00:00", BUY, 100)
    assert e.position is not None
    assert e.position.cost_quote == pytest.approx(990)  # 1000 minus 1% headroom
    assert ex.quote == pytest.approx(10)
