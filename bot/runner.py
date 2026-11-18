"""Long-running loop for paper and live trading."""
from __future__ import annotations

import logging
import signal
import time

import ccxt
import pandas as pd

from .broker import LiveBroker, PaperBroker
from .config import AppConfig, api_keys, check_live_allowed, db_path_for
from .data import fetch_recent
from .engine import Engine
from .notify import Notifier
from .risk import RiskManager
from .store import Store
from .strategies import build_strategy

log = logging.getLogger(__name__)

MAX_BACKOFF = 600
# errors that retrying cannot fix: stop instead of hammering the API
FATAL_ERRORS = (ccxt.AuthenticationError, ccxt.AccountSuspended, ccxt.BadSymbol)


def make_exchange(cfg: AppConfig, authenticated: bool):
    params = {"enableRateLimit": True, "options": {"defaultType": "spot", "adjustForTimeDifference": True}}
    if authenticated:
        key, secret = api_keys(cfg.testnet)
        params.update(apiKey=key, secret=secret)
    ex = ccxt.binance(params)
    if authenticated and cfg.testnet:
        ex.set_sandbox_mode(True)
    return ex


class Runner:
    def __init__(self, cfg: AppConfig, mode: str, exchange=None, broker=None, store: Store | None = None,
                 notifier=None, real_money: bool = False):
        if mode not in ("paper", "live"):
            raise ValueError(f"mode must be 'paper' or 'live', got {mode!r}")
        self.cfg, self.mode, self.real_money = cfg, mode, real_money
        self.ex = exchange or make_exchange(cfg, authenticated=(mode == "live"))
        self.strategy = build_strategy(cfg.strategy, cfg.strategy_params)
        self.store = store or Store(db_path_for(cfg, mode))
        if broker is None:
            broker = LiveBroker(self.ex, cfg.symbol) if mode == "live" else PaperBroker(
                cfg.paper_starting_quote, cfg.fee_pct, cfg.slippage_pct)
        self.broker = broker
        self.engine = Engine(cfg.symbol, broker, RiskManager(cfg.risk), self.store,
                             notifier or Notifier(), mode=mode + ("-testnet" if mode == "live" and cfg.testnet else ""))
        self._stop = False
        self.exit_code = 0

    # ---- startup ---------------------------------------------------------
    def restore(self) -> None:
        self.engine.load()  # also restores paper balances
        if not self.broker.live:
            return
        base, _ = self.broker.balances()
        if self.engine.position:
            if base < self.engine.position.qty * 0.5:
                log.warning("stored position not found in wallet (sold manually?) - clearing it")
                self.engine.notifier.send(f"[{self.mode}] position {self.cfg.symbol} missing from wallet; cleared")
                self.engine.position = None
                self.engine.save()
        elif base > 0:
            # A buy may have filled without being persisted (crash or unconfirmed
            # order). Coins with no tracked stop are unacceptable: block new
            # entries until a human reconciles the wallet.
            try:
                price = float(self.ex.fetch_ticker(self.cfg.symbol)["last"])
                worth = base * price
            except ccxt.NetworkError:
                worth = 0.0  # cannot price it; be conservative and halt anyway
            if worth >= self.broker.min_order_quote() or worth == 0.0:
                log.error("untracked %s in wallet with no position - halting entries", self.cfg.symbol)
                self.engine._halt(
                    f"untracked {base:.8f} {self.cfg.symbol} in wallet (no position/stop); "
                    f"check Binance, fix, then resume")

    # ---- loop ------------------------------------------------------------
    def step(self) -> None:
        df = fetch_recent(self.ex, self.cfg.symbol, self.cfg.timeframe, limit=self.strategy.warmup + 100)
        if len(df) <= self.strategy.warmup:
            log.warning("not enough candles yet (%d)", len(df))
            return
        price = float(self.ex.fetch_ticker(self.cfg.symbol)["last"])
        now = pd.Timestamp.now(tz="UTC").strftime("%Y-%m-%d %H:%M")
        self.engine.apply_resume_request(price)
        bar_key = df.index[-1].isoformat()
        last = self.store.get("last_bar")
        if last is None:
            log.info("first run: syncing to bar %s without trading on it", bar_key)
            self.store.put("last_bar", bar_key)
            new_bar = True  # record a starting equity point
        elif bar_key != last:
            sig = int(self.strategy.signals(df).iloc[-1])
            log.info("bar %s closed  close=%.4f  signal=%s", bar_key, df["close"].iloc[-1], sig)
            self.engine.on_signal(now, sig, price)
            self.store.put("last_bar", bar_key)
            new_bar = True
        else:
            new_bar = False
        # live has a single last price: no bar open, so stops keep their real reason
        self.engine.on_price(now, price, price, open_=None)
        self.engine.save()
        base, quote = self.broker.balances()
        equity = base * price + quote
        if new_bar:
            self.store.log_equity(bar_key, equity, price)
        start_equity = self.store.get("start_equity")
        if start_equity is None:
            start_equity = equity
            self.store.put("start_equity", equity)
        self.store.put("heartbeat", {
            "ts": pd.Timestamp.now(tz="UTC").isoformat(), "price": price, "equity": equity,
            "base": base, "quote": quote, "symbol": self.cfg.symbol, "timeframe": self.cfg.timeframe,
            "strategy": self.cfg.strategy, "mode": self.engine.mode, "poll_seconds": self.cfg.poll_seconds,
            "start_equity": start_equity, "halted": self.engine.risk.state.halted_reason,
        })

    def run(self) -> int:
        if self.mode == "live":
            check_live_allowed(self.cfg, self.real_money)  # defense in depth: CLI checks too
        signal.signal(signal.SIGINT, self._handle_stop)
        signal.signal(signal.SIGTERM, self._handle_stop)
        self.restore()
        self.engine.notifier.send(f"[{self.engine.mode}] bot started {self.cfg.symbol} {self.cfg.timeframe} "
                                  f"strategy={self.cfg.strategy}")
        backoff = self.cfg.poll_seconds
        while not self._stop:
            backoff = self.tick(backoff)
            if self._stop:
                break
            self._sleep(backoff)
        self.engine.save()
        self.engine.notifier.send(f"[{self.engine.mode}] bot stopped" +
                                  (f" (exit code {self.exit_code})" if self.exit_code else ""))
        return self.exit_code

    def tick(self, backoff: float) -> float:
        """One guarded step. Returns the delay before the next one."""
        try:
            self.step()
            return self.cfg.poll_seconds
        except FATAL_ERRORS as exc:
            log.critical("fatal exchange error, stopping: %s", exc)
            self.engine.notifier.send(f"[{self.engine.mode}] ⛔ STOPPED - fatal error: {exc}"
                                      + (" (open position is NOT protected!)" if self.engine.position else ""))
            self.exit_code = 3
            self._stop = True
        except ccxt.NetworkError as exc:
            log.warning("network error, retry in %ss: %s", min(backoff * 2, MAX_BACKOFF), exc)
        except ccxt.ExchangeError as exc:
            log.error("exchange error: %s", exc)
            self.engine.notifier.send(f"[{self.engine.mode}] ⚠️ exchange error: {exc}")
        except Exception as exc:  # keep managing stops even if something unexpected breaks
            log.exception("unexpected error in trading loop")
            self.engine.notifier.send(f"[{self.engine.mode}] ⚠️ unexpected error: {type(exc).__name__}: {exc}")
        return min(backoff * 2, MAX_BACKOFF)

    def _sleep(self, seconds: float) -> None:
        end = time.time() + seconds
        while not self._stop and time.time() < end:
            time.sleep(0.5)

    def _handle_stop(self, *_):
        log.info("stop requested")
        self._stop = True
