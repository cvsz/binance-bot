"""Production-hardening regression tests: fill confirmation, stop reasons, reconciliation."""
import sqlite3
import time
from pathlib import Path

import ccxt
import pytest
from dotenv import dotenv_values

import run
from bot.broker import LiveBroker, PaperBroker
from bot.config import AppConfig, api_keys, check_live_allowed, db_path_for, load_config
from bot.engine import RESUME_KEY, Engine
from bot.errors import ErrorCategory, classify_error
from bot.notify import Notifier, NullNotifier
from bot.risk import Position, RiskConfig, RiskManager
from bot.runner import Runner, make_exchange
from bot.store import Store
from bot.strategies import BUY
from bot.venues import get_venue
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


@pytest.mark.parametrize("exc,category", [
    (ccxt.NetworkError("network down"), ErrorCategory.TRANSIENT),
    (ccxt.RateLimitExceeded("rate limit"), ErrorCategory.RATE_LIMITED),
    (ccxt.InsufficientFunds("not enough balance"), ErrorCategory.REJECTED),
    (ccxt.AuthenticationError("bad key"), ErrorCategory.AUTH_FAILED),
    (RuntimeError("something odd"), ErrorCategory.UNKNOWN),
])
def test_error_classification(exc, category):
    assert classify_error(exc) is category


def test_ambiguous_exchange_error_is_recovered_by_client_id():
    ex = FakeExchange(synthetic(600))
    ex.submit_error = ccxt.ExchangeError("broker returned something odd")
    e = live_engine(ex)
    e.on_signal("2025-01-01 00:00", BUY, ex.fetch_ticker("BTC/USDT")["last"])
    assert e.position is not None, "an ambiguous outcome must be looked up, never blindly retried"
    assert e.risk.state.halted_reason is None


def test_ambiguous_exchange_error_halts_when_lookup_fails():
    ex = FakeExchange(synthetic(600))
    ex.submit_error = ccxt.ExchangeError("broker returned something odd")
    ex.fail_lookup = True
    e = live_engine(ex)
    e.on_signal("2025-01-01 00:00", BUY, 100.0)
    assert e.position is None and "unknown" in e.risk.state.halted_reason
    assert e.store.get("risk")["halted_reason"]


def test_known_rejection_is_not_treated_as_ambiguous():
    ex = FakeExchange(synthetic(600))
    ex.pre_submit_error = ccxt.InsufficientFunds("no balance")
    e = live_engine(ex)
    e.on_signal("2025-01-01 00:00", BUY, 100.0)
    assert e.position is None and e.risk.state.halted_reason is None


def test_rejected_order_does_not_escalate_backoff():
    r = Runner(AppConfig(), "paper", exchange=FakeExchange(synthetic(600)),
               store=Store(), notifier=NullNotifier())

    def reject():
        raise ccxt.InsufficientFunds("no balance")

    r.step = reject
    assert r.tick(120) == r.cfg.poll_seconds == 30


def test_rate_limit_honours_retry_after():
    r = Runner(AppConfig(), "paper", exchange=FakeExchange(synthetic(600)),
               store=Store(), notifier=NullNotifier())

    def limited():
        raise ccxt.RateLimitExceeded("retry-after: 120")

    r.step = limited
    assert r.tick(30) == 120


def test_cli_live_gate_refuses_without_keys(tmp_path, monkeypatch):
    for k in ("BINANCE_API_KEY", "BINANCE_API_SECRET"):
        monkeypatch.delenv(k, raising=False)
    cfg = write_cfg(tmp_path, body="exchange:\n  testnet: false\n")
    assert run.main(["-c", str(cfg), "live"]) == 2


@pytest.mark.parametrize("error", [
    ccxt.AuthenticationError("bad key"),
    ccxt.AccountSuspended("suspended"),
    ccxt.BadSymbol("bad symbol"),
])
def test_all_fatal_exchange_errors_stop_with_exit_3(error):
    r = Runner(AppConfig(), "paper", exchange=FakeExchange(synthetic(600)),
               store=Store(), notifier=NullNotifier())

    def fatal():
        raise error

    r.step = fatal
    r.tick(30)
    assert r._stop and r.exit_code == 3


@pytest.mark.parametrize("field,value", [
    ("stop_loss_pct", 0), ("stop_loss_pct", 100),
    ("risk_per_trade_pct", 0), ("risk_per_trade_pct", 6),
    ("max_position_pct", 0), ("max_position_pct", 101),
    ("take_profit_pct", -1),
    ("trailing_stop_pct", 0), ("trailing_stop_pct", 100),
    ("max_daily_loss_pct", 0), ("max_daily_loss_pct", 101),
    ("max_drawdown_halt_pct", 0), ("max_drawdown_halt_pct", 101),
    ("max_trades_per_day", 0), ("cooldown_bars", -1),
])
def test_risk_config_rejects_invalid_values(field, value):
    with pytest.raises(ValueError):
        RiskConfig(**{field: value})


def test_put_many_rolls_back_on_error(tmp_path):
    s = Store(tmp_path / "x.db")
    s.put("keep", 1)
    s.db.execute("CREATE TRIGGER fail_b BEFORE INSERT ON state WHEN NEW.k='b' "
                 "BEGIN SELECT RAISE(ABORT, 'boom'); END;")
    with pytest.raises(sqlite3.IntegrityError):
        s.put_many({"a": 1, "b": 2})
    assert s.get("a") is None and s.get("keep") == 1


def test_backoff_caps_at_600():
    r = Runner(AppConfig(), "paper", exchange=FakeExchange(synthetic(600)),
               store=Store(), notifier=NullNotifier())

    def outage():
        raise ccxt.NetworkError("network down")

    r.step = outage
    assert r.tick(400) == 600
    assert r.tick(700) == 600
    assert r.exit_code == 0 and not r._stop


class StaleTickerExchange(FakeExchange):
    def __init__(self, df, age_seconds):
        super().__init__(df)
        self.age_seconds = age_seconds

    def fetch_ticker(self, symbol):
        return {"last": 100.0, "timestamp": (time.time() - self.age_seconds) * 1000}


def test_stale_price_skips_entries_and_keeps_bar_unconsumed(tmp_path):
    ex = StaleTickerExchange(synthetic(600), age_seconds=1000)
    store = Store(tmp_path / "p.db")
    note = RecordingNotifier()
    r = Runner(AppConfig(), "paper", exchange=ex, store=store, notifier=note)
    r.restore()
    r.step()
    first_bar = store.get("last_bar")
    ex.i += 1
    r.step()
    assert store.trades() == []
    assert store.get("last_bar") == first_bar  # signal will be retried when price is fresh
    assert store.get("heartbeat")["price_stale"] is True
    assert any("stale price" in m for m in note.msgs)


def test_fresh_price_allows_entries(tmp_path):
    ex = StaleTickerExchange(synthetic(600), age_seconds=1)
    store = Store(tmp_path / "p.db")
    r = Runner(AppConfig(), "paper", exchange=ex, store=store, notifier=NullNotifier())
    signals = []
    original = r.engine.on_signal

    def spy(*args, **kwargs):
        signals.append(args)
        return original(*args, **kwargs)

    r.engine.on_signal = spy
    r.restore()
    r.step()
    ex.i += 1
    r.step()
    assert store.get("heartbeat")["price_stale"] is False
    assert len(signals) == 1  # the new bar was processed once the price was fresh


def test_position_quantity_mismatch_halts(tmp_path):
    ex = FakeExchange(synthetic(600))
    ex.base = 0.7
    store = Store(tmp_path / "s.db")
    store.put("position", {"qty": 1.0, "entry_price": 100, "cost_quote": 100, "stop": 98,
                           "take": None, "peak": 100, "opened_at": "x"})
    r = Runner(AppConfig(), "live", exchange=ex, broker=fast_broker(ex), store=store,
               notifier=RecordingNotifier())
    r.restore()
    assert "mismatch" in r.engine.risk.state.halted_reason


def test_small_quantity_difference_is_tolerated(tmp_path):
    ex = FakeExchange(synthetic(600))
    ex.base = 0.999
    store = Store(tmp_path / "s.db")
    store.put("position", {"qty": 1.0, "entry_price": 100, "cost_quote": 100, "stop": 98,
                           "take": None, "peak": 100, "opened_at": "x"})
    r = Runner(AppConfig(), "live", exchange=ex, broker=fast_broker(ex), store=store,
               notifier=NullNotifier())
    r.restore()
    assert r.engine.risk.state.halted_reason is None
    assert r.engine.position is not None


def test_untracked_wallet_balance_halts_entries():
    ex = FakeExchange(synthetic(600))
    ex.base = 1.0  # coins in wallet but no stored position
    r = Runner(AppConfig(), "live", exchange=ex, broker=fast_broker(ex),
               store=Store(), notifier=RecordingNotifier())
    r.restore()
    assert r.engine.position is None
    assert "untracked" in r.engine.risk.state.halted_reason
    assert any("HALTED" in m for m in r.engine.notifier.msgs)


FAKE_ED25519_PEM = (
    "-----BEGIN PRIVATE KEY-----\nMC4CAQAwBQYDK2VwBCIEIFakeFake\n-----END PRIVATE KEY-----"
)


def test_ccxt_signing_uses_eddsa_for_pem_secret():
    ex = ccxt.binance({"apiKey": "k", "secret": FAKE_ED25519_PEM})
    ex.eddsa = lambda *a, **k: b"sig-ed"
    ex.hmac = lambda *a, **k: pytest.fail("HMAC must not be used when secret is a PEM key")

    signed = ex.sign("order", ["private"], "POST", {"timestamp": 1})
    assert "signature=sig-ed" in signed["body"]


def test_ccxt_signing_uses_hmac_for_plain_secret():
    ex = ccxt.binance({"apiKey": "k", "secret": "plain-secret"})
    ex.hmac = lambda *a, **k: "sig-hmac"  # ccxt concatenates the HMAC result as str
    ex.eddsa = lambda *a, **k: pytest.fail("EdDSA must not be used for a normal HMAC secret")

    signed = ex.sign("order", ["private"], "POST", {"timestamp": 1})
    assert "signature=sig-hmac" in signed["body"]


def test_dotenv_reads_multiline_pem(tmp_path):
    env = tmp_path / "env.test"
    env.write_text(
        'BINANCE_API_KEY=k\n'
        'BINANCE_API_SECRET="-----BEGIN PRIVATE KEY-----\n'
        'ABC\n'
        '-----END PRIVATE KEY-----"\n'
    )
    value = dotenv_values(env)["BINANCE_API_SECRET"]
    assert "PRIVATE KEY" in value and value.count("\n") == 2


def test_venue_registry():
    assert get_venue("binance").key_prefix == "BINANCE"
    assert get_venue("BINANCEUS").ccxt_id == "binanceus"
    assert get_venue("binanceth").custom == "THExchange"  # now served by the TH adapter
    with pytest.raises(ValueError, match="unknown exchange"):
        get_venue("somethingelse")


def test_config_rejects_testnet_for_real_money_only_venue(tmp_path):
    with pytest.raises(ValueError, match="no testnet"):
        load_config(write_cfg(tmp_path, body="exchange:\n  name: binanceth\n  testnet: true\n"))
    cfg = load_config(write_cfg(tmp_path, body="exchange:\n  name: binanceth\n  testnet: false\n"))
    assert cfg.exchange_name == "binanceth" and cfg.testnet is False


def test_make_exchange_returns_th_adapter():
    ex = make_exchange(AppConfig(exchange_name="binanceth", testnet=False), authenticated=False)
    assert ex.id == "binanceth"
    with pytest.raises(PermissionError, match="REAL MONEY"):
        ex.set_sandbox_mode(True)


def test_config_selects_exchange_and_rejects_unsupported(tmp_path):
    cfg = load_config(write_cfg(tmp_path, body="exchange:\n  name: binanceus\n  testnet: true\n"))
    assert cfg.exchange_name == "binanceus"
    with pytest.raises(ValueError, match="unknown exchange"):
        load_config(write_cfg(tmp_path, body="exchange:\n  name: kraken\n"))


def test_api_keys_accept_user_naming_aliases(monkeypatch):
    for k in ("BINANCE_TESTNET_API_KEY", "BINANCE_TESTNET_API_SECRET"):
        monkeypatch.delenv(k, raising=False)
    monkeypatch.setenv("BINANCE_TH_TESTNET_API_KEY", "th-key")
    monkeypatch.setenv("BINANCE_TH_TESTNET_API_SECRET", "th-secret")
    assert api_keys(True, "binance") == ("th-key", "th-secret")

    for k in ("BINANCEUS_API_KEY", "BINANCEUS_API_SECRET"):
        monkeypatch.delenv(k, raising=False)
    monkeypatch.setenv("BINANCE_US_API_KEY", "us-key")
    monkeypatch.setenv("BINANCE_US_API_SECRET", "us-secret")
    assert api_keys(False, "binanceus") == ("us-key", "us-secret")


def test_api_keys_primary_prefix_wins(monkeypatch):
    monkeypatch.setenv("BINANCE_TESTNET_API_KEY", "primary-key")
    monkeypatch.setenv("BINANCE_TESTNET_API_SECRET", "primary-secret")
    monkeypatch.setenv("BINANCE_TH_TESTNET_API_KEY", "alias-key")
    monkeypatch.setenv("BINANCE_TH_TESTNET_API_SECRET", "alias-secret")
    assert api_keys(True, "binance") == ("primary-key", "primary-secret")


def test_api_keys_use_venue_prefix(monkeypatch):
    monkeypatch.setenv("BINANCEUS_API_KEY", "us-key")
    monkeypatch.setenv("BINANCEUS_API_SECRET", "us-secret")
    assert api_keys(False, "binanceus") == ("us-key", "us-secret")
    monkeypatch.setenv("BINANCEUS_TESTNET_API_KEY", "us-test-key")
    monkeypatch.setenv("BINANCEUS_TESTNET_API_SECRET", "us-test-secret")
    assert api_keys(True, "binanceus") == ("us-test-key", "us-test-secret")


def test_db_path_includes_venue_when_not_default():
    cfg = AppConfig(exchange_name="binanceus", db_path="data/bot.db")
    assert str(db_path_for(cfg, "paper")).endswith("bot.paper.binanceus.db")
    assert str(db_path_for(cfg, "live")).endswith("bot.live.testnet.binanceus.db")


def test_make_exchange_uses_venue_class():
    ex = make_exchange(AppConfig(exchange_name="binanceus"), authenticated=False)
    assert ex.id == "binanceus"


def test_live_gate_uses_venue_keys(monkeypatch):
    for k in ("BINANCE_TESTNET_API_KEY", "BINANCE_TESTNET_API_SECRET"):
        monkeypatch.delenv(k, raising=False)
    monkeypatch.setenv("BINANCEUS_TESTNET_API_KEY", "us-key")
    monkeypatch.setenv("BINANCEUS_TESTNET_API_SECRET", "us-secret")
    check_live_allowed(AppConfig(exchange_name="binanceus", testnet=True), False)


def test_example_config_loads_with_all_risk_keys():
    """Every key shipped in config.example.yaml must be accepted."""
    example = Path(__file__).resolve().parents[1] / "config.example.yaml"
    cfg = load_config(example)
    assert cfg.risk.stop_loss_pct == 2.0
    assert cfg.risk.risk_per_trade_pct == 1.0
    assert cfg.testnet is True


@pytest.mark.parametrize("body", [
    "testnetz: true\n",
    "exchange:\n  testnet: true\n  tyop: 1\n",
    "loop:\n  poll_second: 30\n",
])
def test_config_rejects_unknown_keys(tmp_path, body):
    with pytest.raises(ValueError, match="unknown"):
        load_config(write_cfg(tmp_path, body=body))


@pytest.mark.parametrize("value,expected", [("true", True), ("false", False), ("FALSE", False)])
def test_config_parses_booleans_strictly(tmp_path, value, expected):
    cfg = load_config(write_cfg(tmp_path, body=f"exchange:\n  testnet: {value}\n"))
    assert cfg.testnet is expected


def test_config_rejects_loose_boolean(tmp_path):
    with pytest.raises(ValueError, match="true or false"):
        load_config(write_cfg(tmp_path, body="exchange:\n  testnet: 'yes'\n"))


def test_config_rejects_parent_path(tmp_path):
    with pytest.raises(ValueError, match="db_path"):
        load_config(write_cfg(tmp_path, body="db_path: ../outside/bot.db\n"))


def test_cli_reports_type_error_as_config_error(tmp_path, capsys):
    cfg = write_cfg(tmp_path, body="risk:\n  stop_loss_pct: abc\n")
    assert run.main(["-c", str(cfg), "status"]) == 2
    assert "config error" in capsys.readouterr().err


def test_notifier_send_suppresses_duplicate_http(monkeypatch):
    calls = []

    class Response:
        def read(self):
            return b"{}"

    def fake_urlopen(req, timeout=None):
        calls.append(req)
        return Response()

    monkeypatch.setattr("urllib.request.urlopen", fake_urlopen)
    n = Notifier(token="t", chat_id="c")
    n.send("same message")
    n.send("same message")
    assert len(calls) == 1


def test_notifier_tracking_is_bounded():
    n = Notifier(token="t", chat_id="c")
    for i in range(600):
        n._suppressed(f"unique message {i}")
    assert len(n._last_sent) <= 500


def test_live_sizing_keeps_fee_headroom():
    ex = FakeExchange(synthetic(600))
    ex.base, ex.quote = 0.0, 1000.0
    cfg = RiskConfig(risk_per_trade_pct=5, stop_loss_pct=2, max_position_pct=100)
    e = Engine("BTC/USDT", fast_broker(ex), RiskManager(cfg), Store(), mode="live-test")
    e.on_signal("2025-01-01 00:00", BUY, 100)
    assert e.position is not None
    assert e.position.cost_quote == pytest.approx(990)  # 1000 minus 1% headroom
    assert ex.quote == pytest.approx(10)
