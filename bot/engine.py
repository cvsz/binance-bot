"""Trading engine shared by backtest, paper and live modes (long-only spot)."""
from __future__ import annotations

import logging
from dataclasses import asdict
from typing import Optional

from .broker import BrokerError
from .notify import NullNotifier
from .risk import Position, RiskManager, RiskState
from .store import Store
from .strategies import BUY, SELL

log = logging.getLogger(__name__)


class Engine:
    def __init__(self, symbol: str, broker, risk: RiskManager, store: Store | None = None,
                 notifier=None, mode: str = "paper"):
        self.symbol = symbol
        self.broker = broker
        self.risk = risk
        self.store = store or Store()
        self.notifier = notifier or NullNotifier()
        self.mode = mode
        self.position: Optional[Position] = None
        self.bar_index = 0

    # ---- persistence -----------------------------------------------------
    def save(self) -> None:
        self.store.put("position", asdict(self.position) if self.position else None)
        self.store.put("risk", self.risk.state_dict())
        self.store.put("bar_index", self.bar_index)

    def load(self) -> None:
        pos = self.store.get("position")
        self.position = Position(**pos) if pos else None
        self.risk.state = RiskState(**self.store.get("risk", {}))
        self.bar_index = self.store.get("bar_index", 0)

    # ---- helpers ---------------------------------------------------------
    def equity(self, price: float) -> float:
        base, quote = self.broker.balances()
        return base * price + quote

    def _enter(self, ts: str, price: float) -> None:
        base, quote = self.broker.balances()
        equity = base * price + quote
        ok, reason = self.risk.can_enter(equity, self.bar_index)
        if not ok:
            log.info("%s entry skipped: %s", ts, reason)
            return
        size = self.risk.position_size_quote(equity, quote)
        if size < self.broker.min_order_quote():
            log.info("%s entry skipped: size %.2f below minimum order", ts, size)
            return
        try:
            fill = self.broker.buy_quote(size, price)
        except BrokerError as exc:
            log.warning("%s buy failed: %s", ts, exc)
            return
        stop, take = self.risk.levels(fill.price)
        self.position = Position(qty=fill.qty, entry_price=fill.price, cost_quote=fill.quote,
                                 stop=stop, take=take, peak=fill.price, opened_at=ts)
        self.risk.record_entry()
        self.store.log_trade(ts=ts, mode=self.mode, symbol=self.symbol, side="buy", qty=fill.qty,
                             price=fill.price, quote=fill.quote, reason="signal", pnl_quote=None,
                             order_id=fill.order_id)
        self.notifier.send(f"[{self.mode}] BUY {self.symbol} qty={fill.qty:.6f} @ {fill.price:.4f} "
                           f"SL={stop:.4f} TP={take if take is None else round(take, 4)}")
        self.save()

    def _exit(self, ts: str, price: float, reason: str) -> None:
        pos = self.position
        try:
            fill = self.broker.sell_qty(pos.qty, price)
        except BrokerError as exc:
            log.error("%s sell failed (%s): %s", ts, reason, exc)
            self.notifier.send(f"[{self.mode}] ⚠️ SELL FAILED {self.symbol}: {exc}")
            return
        pnl = fill.quote - pos.cost_quote * (fill.qty / pos.qty if pos.qty else 1)
        self.position = None
        self.risk.record_exit(self.bar_index)
        self.store.log_trade(ts=ts, mode=self.mode, symbol=self.symbol, side="sell", qty=fill.qty,
                             price=fill.price, quote=fill.quote, reason=reason, pnl_quote=pnl,
                             order_id=fill.order_id)
        self.notifier.send(f"[{self.mode}] SELL {self.symbol} ({reason}) @ {fill.price:.4f} PnL={pnl:+.2f}")
        self.save()

    # ---- event handlers --------------------------------------------------
    def on_price(self, ts: str, low: float, high: float, open_: float | None = None) -> None:
        """Manage stop / take-profit / trailing for an open position.

        Backtest passes bar open/low/high; live passes the last price for all three.
        If a bar touches both stop and target, the stop is assumed first (conservative).
        """
        pos = self.position
        if not pos:
            return
        if open_ is not None and open_ <= pos.stop:
            return self._exit(ts, open_, "stop_gap")
        if low <= pos.stop:
            return self._exit(ts, pos.stop, "trailing_stop" if pos.stop > pos.entry_price else "stop_loss")
        if pos.take is not None:
            if open_ is not None and open_ >= pos.take:
                return self._exit(ts, open_, "take_profit")
            if high >= pos.take:
                return self._exit(ts, pos.take, "take_profit")
        self.risk.update_trailing(pos, high)

    def on_signal(self, ts: str, signal: int, price: float) -> None:
        """Called once per closed bar with that bar's strategy signal."""
        self.bar_index += 1
        day = ts[:10]
        self.risk.roll_day(day, self.equity(price))
        if signal == SELL and self.position:
            self._exit(ts, price, "signal")
        elif signal == BUY and not self.position:
            self._enter(ts, price)
        self.save()
