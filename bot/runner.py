"""Long-running loop for paper and live trading."""
from __future__ import annotations

import logging
import signal
import time

import pandas as pd

from .broker import LiveBroker, PaperBroker
from .config import AppConfig, api_keys, db_path_for
from .data import fetch_recent
from .engine import Engine
from .notify import Notifier
from .risk import RiskManager
from .store import Store
from .strategies import build_strategy

log = logging.getLogger(__name__)


def make_exchange(cfg: AppConfig, authenticated: bool):
    import ccxt

    params = {"enableRateLimit": True, "options": {"defaultType": "spot"}}
    if authenticated:
        key, secret = api_keys(cfg.testnet)
        params.update(apiKey=key, secret=secret)
    ex = ccxt.binance(params)
    if authenticated and cfg.testnet:
        ex.set_sandbox_mode(True)
    return ex


class Runner:
    def __init__(self, cfg: AppConfig, mode: str, exchange=None, broker=None, store: Store | None = None,
                 notifier=None):
        assert mode in ("paper", "live")
        self.cfg, self.mode = cfg, mode
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

    # ---- startup ---------------------------------------------------------
    def restore(self) -> None:
        self.engine.load()
        if isinstance(self.broker, PaperBroker):
            bal = self.store.get("paper_balances")
            if bal:
                self.broker.base, self.broker.quote = bal
        elif self.engine.position:
            base, _ = self.broker.balances()
            if base < self.engine.position.qty * 0.5:
                log.warning("stored position not found in wallet (sold manually?) - clearing it")
                self.engine.notifier.send(f"[{self.mode}] position {self.cfg.symbol} missing from wallet; cleared")
                self.engine.position = None
                self.engine.save()

    def persist(self) -> None:
        if isinstance(self.broker, PaperBroker):
            self.store.put("paper_balances", [self.broker.base, self.broker.quote])

    # ---- loop ------------------------------------------------------------
    def step(self) -> None:
        df = fetch_recent(self.ex, self.cfg.symbol, self.cfg.timeframe, limit=self.strategy.warmup + 100)
        if len(df) <= self.strategy.warmup:
            log.warning("not enough candles yet (%d)", len(df))
            return
        price = float(self.ex.fetch_ticker(self.cfg.symbol)["last"])
        now = pd.Timestamp.now(tz="UTC").strftime("%Y-%m-%d %H:%M")
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
        self.engine.on_price(now, price, price)
        self.persist()
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
            "start_equity": start_equity,
        })

    def run(self) -> None:
        import ccxt

        signal.signal(signal.SIGINT, self._handle_stop)
        signal.signal(signal.SIGTERM, self._handle_stop)
        self.restore()
        self.engine.notifier.send(f"[{self.engine.mode}] bot started {self.cfg.symbol} {self.cfg.timeframe} "
                                  f"strategy={self.cfg.strategy}")
        backoff = self.cfg.poll_seconds
        while not self._stop:
            try:
                self.step()
                backoff = self.cfg.poll_seconds
            except ccxt.NetworkError as exc:
                backoff = min(backoff * 2, 600)
                log.warning("network error, retry in %ss: %s", backoff, exc)
            except ccxt.ExchangeError as exc:
                log.error("exchange error: %s", exc)
                self.engine.notifier.send(f"[{self.engine.mode}] ⚠️ exchange error: {exc}")
            self._sleep(backoff)
        self.persist()
        self.engine.save()
        self.engine.notifier.send(f"[{self.engine.mode}] bot stopped")

    def _sleep(self, seconds: float) -> None:
        end = time.time() + seconds
        while not self._stop and time.time() < end:
            time.sleep(0.5)

    def _handle_stop(self, *_):
        log.info("stop requested")
        self._stop = True
