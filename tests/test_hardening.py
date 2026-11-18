"""Regression tests for the audit fixes (order recovery, dust, kill switches, persistence...)."""
import sqlite3
import textwrap

import ccxt
import pytest

import run
from bot.broker import BrokerError, DustError, OrderStateUnknown, PaperBroker, PositionMissingError
from bot.config import AppConfig, db_path_for, load_config
from bot.data import load_csv
from bot.engine import RESUME_KEY, Engine
from bot.notify import Notifier, NullNotifier
from bot.risk import Position, RiskConfig, RiskManager, RiskState
from bot.runner import Runner
from bot.store import Store
from bot.strategies import BUY, build_strategy
from tests.test_bot import synthetic
from tests.test_runner import FakeExchange, fast_broker


class RecordingNotifier(NullNotifier):
    def __init__(self):
        super().__init__()
        self.msgs = []

    def send(self, text):
        self.msgs.append(text)


def live_engine(ex, **risk):
    risk.setdefault("cooldown_bars", 0)
    return Engine("BTC/USDT", fast_broker(ex), RiskManager(RiskConfig(**risk)), Store(),
                  RecordingNotifier(), mode="live-test")


# ---- order recovery (P1) -----------------------------------------------------

def test_buy_timeout_after_fill_is_recovered_by_client_id():
    ex = FakeExchange(synthetic(600))
    ex.fail_submit_after_fill = True
    e = live_engine(ex)
    e.on_signal("2025-01-01 00:00", BUY, ex.fetch_ticker("BTC/USDT")["last"])
    assert e.position is not None, "filled order must not be lost on a submission timeout"
    assert e.position.qty == pytest.approx(ex.base)
    assert e.store.trades()[-1]["side"] == "buy"


def test_buy_timeout_before_send_is_a_clean_failure():
    ex = FakeExchange(synthetic(600))
    ex.fail_submit_before_fill = True
    e = live_engine(ex)
    e.on_signal("2025-01-01 00:00", BUY, 100.0)
    assert e.position is None and ex.base == 0
    assert e.risk.state.halted_reason is None  # known not placed -> no halt


def test_buy_unknown_state_halts_entries():
    ex = FakeExchange(synthetic(600))
    ex.fail_submit_after_fill = True
    ex.fail_lookup = True
    e = live_engine(ex)
    e.on_signal("2025-01-01 00:00", BUY, 100.0)
    assert e.position is None
    assert "unknown" in e.risk.state.halted_reason
    assert any("HALTED" in m for m in e.notifier.msgs)
    assert e.store.get("risk")["halted_reason"]  # persisted


def test_buy_fill_from_order_when_balances_unreadable():
    ex = FakeExchange(synthetic(600))
    ex.fail_balance_after_order = True
    b = fast_broker(ex)
    fill = b.buy_quote(100, 0)
    # qty = filled - base fee, i.e. what actually landed in the wallet
    assert fill.qty == pytest.approx(ex.base)
    assert fill.quote == pytest.approx(100)


# ---- sells (P1) -----------------------------------------------------------------

def test_dust_position_is_dropped_not_retried_forever():
    ex = FakeExchange(synthetic(600))
    b = fast_broker(ex)
    ex.base = 0.00001
    with pytest.raises(DustError):
        b.sell_qty(0.00001, 100.0)  # 0.001 USDT < 5 USDT minimum
    e = live_engine(ex)
    e.position = Position(qty=0.00001, entry_price=100, cost_quote=1, stop=98, take=None, peak=100,
                          opened_at="x")
    e.on_price("t", low=50, high=50)
    assert e.position is None
    assert e.store.trades()[-1]["side"] == "abandon"


def test_sell_when_wallet_empty_raises_position_missing():
    ex = FakeExchange(synthetic(600))
    with pytest.raises(PositionMissingError):
        fast_broker(ex).sell_qty(1.0, 100.0)
    with pytest.raises(PositionMissingError):
        PaperBroker().sell_qty(1.0, 100.0)


def test_order_not_found_after_timeout_is_broker_error():
    ex = FakeExchange(synthetic(600))
    ex.fail_submit_before_fill = True
    with pytest.raises(BrokerError) as e:
        fast_broker(ex).buy_quote(100, 0)
    assert not isinstance(e.value, OrderStateUnknown)


# ---- persistence (P1) -----------------------------------------------------------

def test_position_and_paper_balances_saved_atomically(tmp_path):
    db = tmp_path / "s.db"
    e = Engine("BTC/USDT", PaperBroker(1000, 0, 0), RiskManager(RiskConfig()), Store(db), mode="t")
    e.on_signal("2025-01-01 00:00", BUY, 100)
    # crash here (no runner.persist) -> restart must see coins AND the position
    e2 = Engine("BTC/USDT", PaperBroker(1000, 0, 0), RiskManager(RiskConfig()), Store(db), mode="t")
    e2.load()
    assert e2.position is not None
    assert e2.broker.base == pytest.approx(e2.position.qty)
    assert e2.broker.quote < 1000


def test_trailing_stop_persisted(tmp_path):
    db = tmp_path / "s.db"
    e = Engine("BTC/USDT", PaperBroker(1000, 0, 0),
               RiskManager(RiskConfig(take_profit_pct=None, trailing_stop_pct=1)), Store(db), mode="t")
    e.on_signal("2025-01-01 00:00", BUY, 100)
    e.on_price("t", low=119, high=120)  # low above the raised stop, so the position survives
    assert Store(db).get("position")["stop"] == pytest.approx(118.8)


def test_old_risk_state_loads():
    st = RiskState.from_dict({"day": "2025-01-01", "trades_today": 2, "obsolete": 1})
    assert st.trades_today == 2 and st.peak_equity == 0


# ---- kill switch + resume (missing feature) ---------------------------------------

def test_max_drawdown_halt_and_resume(tmp_path):
    db = tmp_path / "s.db"
    rm = RiskManager(RiskConfig(max_drawdown_halt_pct=10, max_daily_loss_pct=50))
    rm.observe_equity(1000)
    rm.observe_equity(950)
    assert rm.can_enter(950, 99)[0]
    rm.observe_equity(890)
    ok, why = rm.can_enter(890, 99)
    assert not ok and "max drawdown" in why
    rm.roll_day("2099-01-01", 890)  # a new day must NOT clear it
    assert rm.state.halted_reason

    e = Engine("BTC/USDT", PaperBroker(1000, 0, 0), rm, Store(db), RecordingNotifier(), mode="t")
    e.save()
    cfg = AppConfig(db_path=str(tmp_path / "bot.db"))
    Store(db_path_for(cfg, "paper")).put("risk", rm.state_dict())
    assert run.main(["-c", str(write_cfg(tmp_path, cfg)), "resume", "--mode", "paper"]) == 0
    s = Store(db_path_for(cfg, "paper"))
    assert s.get(RESUME_KEY) is not None
    e2 = Engine("BTC/USDT", PaperBroker(1000, 0, 0), RiskManager(rm.cfg), s, RecordingNotifier(), mode="t")
    e2.load()
    e2.apply_resume_request(100.0)
    assert e2.risk.state.halted_reason is None
    assert s.get(RESUME_KEY) is None
    assert e2.risk.state.peak_equity == pytest.approx(1000)  # re-based to current equity


# ---- runner resilience (P1) ------------------------------------------------------

def test_runner_survives_unexpected_error_and_stops_on_auth_error():
    ex = FakeExchange(synthetic(600))
    note = RecordingNotifier()
    r = Runner(AppConfig(), "paper", exchange=ex, store=Store(), notifier=note)

    def boom():
        raise KeyError("weird")
    r.step = boom
    assert r.tick(30) == 60 and not r._stop
    assert any("unexpected error" in m for m in note.msgs)

    def auth():
        raise ccxt.AuthenticationError("invalid api key")
    r.step = auth
    r.tick(30)
    assert r._stop and r.exit_code == 3


def test_runner_run_enforces_live_gates(monkeypatch):
    for k in ("BINANCE_API_KEY", "BINANCE_API_SECRET"):
        monkeypatch.delenv(k, raising=False)
    ex = FakeExchange(synthetic(600))
    r = Runner(AppConfig(testnet=False), "live", exchange=ex, broker=fast_broker(ex), store=Store(),
               notifier=NullNotifier())
    with pytest.raises(PermissionError):
        r.run()


# ---- notifier throttle (P2) ---------------------------------------------------------

def test_notifier_dedupes_repeated_messages():
    n = Notifier(token="t", chat_id="c", dedupe_seconds=60)
    assert not n._suppressed("exchange error")
    assert n._suppressed("exchange error")
    assert not n._suppressed("other")


# ---- dashboard store is read-only (P2) ---------------------------------------------

def test_read_only_store_cannot_write(tmp_path):
    db = tmp_path / "x.db"
    Store(db).put("a", 1)
    ro = Store(db, read_only=True)
    assert ro.get("a") == 1
    with pytest.raises(sqlite3.OperationalError):
        ro.put("a", 2)
    with pytest.raises(FileNotFoundError):
        Store(tmp_path / "missing.db", read_only=True)


def test_trade_columns_whitelisted():
    with pytest.raises(ValueError):
        Store().log_trade(ts="x", evil="1")


# ---- config / input validation (P3) -------------------------------------------------

def write_cfg(tmp_path, cfg=None, body=None):
    p = tmp_path / "config.yaml"
    p.write_text(body if body is not None else f"db_path: {cfg.db_path}\n", encoding="utf-8")
    return p


def test_config_empty_sections_ok(tmp_path):
    p = write_cfg(tmp_path, body="exchange:\nrisk:\nstrategy:\npaper:\nloop:\n")
    cfg = load_config(p)
    assert cfg.testnet is True and cfg.risk.stop_loss_pct == 2.0


@pytest.mark.parametrize("body,msg", [
    ("timeframe: 15x\n", "timeframe"),
    ("symbol: BTCUSDT\n", "symbol"),
    ("risk:\n  stop_los_pct: 2\n", "unknown risk"),
    ("risk:\n  max_trades_per_day: 0\n", "max_trades_per_day"),
    ("paper:\n  fee_pct: -1\n", "fee_pct"),
])
def test_config_rejects_bad_values(tmp_path, body, msg):
    with pytest.raises(ValueError, match=msg):
        load_config(write_cfg(tmp_path, body=body))


def test_cli_reports_config_errors(tmp_path, capsys):
    assert run.main(["-c", str(tmp_path / "nope.yaml"), "status"]) == 2
    assert "config error" in capsys.readouterr().err


def test_strategy_bad_params_are_value_errors():
    with pytest.raises(ValueError, match="invalid params"):
        build_strategy("ema_cross", {"fsat": 9})


def test_load_csv_dedupes_and_drops_nan(tmp_path):
    p = tmp_path / "d.csv"
    p.write_text(textwrap.dedent("""\
        timestamp,open,high,low,close,volume
        1700000000000,1,2,0.5,1.5,10
        1700000000000,1,2,0.5,1.6,10
        1700000900000,1,2,0.5,,10
        1700001800000,1,2,0.5,1.7,10
        """))
    df = load_csv(str(p))
    assert len(df) == 2 and df["close"].iloc[0] == pytest.approx(1.6)


# ---- health command (missing feature) -------------------------------------------------

def test_health_command(tmp_path):
    cfg = AppConfig(db_path=str(tmp_path / "bot.db"))
    cpath = write_cfg(tmp_path, cfg)
    assert run.main(["-c", str(cpath), "health"]) == 1  # no db yet
    ex = FakeExchange(synthetic(600))
    r = Runner(cfg, "paper", exchange=ex, notifier=NullNotifier())
    r.restore()
    r.step()
    assert run.main(["-c", str(cpath), "health"]) == 0
    hb = r.store.get("heartbeat")
    hb["ts"] = "2000-01-01T00:00:00+00:00"
    r.store.put("heartbeat", hb)
    assert run.main(["-c", str(cpath), "health"]) == 1


# ---- backup command ---------------------------------------------------------------------

def test_backup_command(tmp_path):
    cfg = AppConfig(db_path=str(tmp_path / "data" / "bot.db"))
    cpath = write_cfg(tmp_path, cfg)
    out = tmp_path / "bk"
    assert run.main(["-c", str(cpath), "backup", "--dir", str(out)]) == 1  # nothing to back up
    live = Store(db_path_for(cfg, "paper"))
    live.put("position", {"qty": 1})
    live.log_trade(ts="t", side="buy", qty=1.0)
    assert run.main(["-c", str(cpath), "backup", "--dir", str(out)]) == 0
    files = list(out.glob("bot.paper.*.db"))
    assert len(files) == 1
    copy = Store(files[0], read_only=True)
    assert copy.get("position") == {"qty": 1} and len(copy.trades()) == 1
