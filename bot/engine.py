"""Trading engine shared by backtest, paper and live modes (long-only spot)."""
from __future__ import annotations

import logging
from dataclasses import asdict

from .broker import BrokerError, DustError, OrderStateUnknown, PositionMissingError
from .notify import NullNotifier
from .risk import Position, RiskManager, RiskState
from .store import Store
from .strategies import BUY, SELL

log = logging.getLogger(__name__)

RESUME_KEY = "resume_requested"


class Engine:
    def __init__(self, symbol: str, broker, risk: RiskManager, store: Store | None = None,
                 notifier=None, mode: str = "paper"):
        self.symbol = symbol
        self.broker = broker
        self.risk = risk
        self.store = store or Store()
        self.notifier = notifier or NullNotifier()
        self.mode = mode
        self.position: Position | None = None
        self.bar_index = 0

    # ---- persistence -----------------------------------------------------
    def save(self) -> None:
        """Persist position, risk state and (paper) balances in ONE transaction, so a
        crash can never leave a recorded position without the matching balances."""
        items = {
            "position": asdict(self.position) if self.position else None,
            "risk": self.risk.state_dict(),
            "bar_index": self.bar_index,
        }
        if hasattr(self.broker, "snapshot"):
            items["paper_balances"] = self.broker.snapshot()
        self.store.put_many(items)

    def load(self) -> None:
        pos = self.store.get("position")
        self.position = Position(**pos) if pos else None
        self.risk.state = RiskState.from_dict(self.store.get("risk"))
        self.bar_index = self.store.get("bar_index", 0)
        snap = self.store.get("paper_balances")
        if snap and hasattr(self.broker, "restore"):
            self.broker.restore(snap)

    def apply_resume_request(self, price: float | None = None) -> None:
        """Clear a halt if `run.py resume` asked for it (works while the bot is running)."""
        if self.store.get(RESUME_KEY) is None:
            return
        self.store.delete(RESUME_KEY)
        prev = self.risk.resume(self.equity(price) if price else None)
        self.save()
        log.warning("trading resumed by operator (was: %s)", prev)
        self.notifier.send(f"[{self.mode}] ▶️ resumed by operator (was halted: {prev})")

    # ---- helpers ---------------------------------------------------------
    def equity(self, price: float) -> float:
        base, quote = self.broker.balances()
        return base * price + quote

    def _halt(self, reason: str) -> None:
        self.risk.halt(reason)
        log.error("HALTED: %s", reason)
        self.notifier.send(f"[{self.mode}] ⛔ HALTED {self.symbol}: {reason}\n"
                           f"Fix the account, then run: python run.py resume --mode <mode>")
        self.save()

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
        except OrderStateUnknown as exc:
            # coins may be in the wallet without a stop: block new entries until a human checks
            return self._halt(f"buy order state unknown: {exc}")
        except BrokerError as exc:
            log.warning("%s buy failed: %s", ts, exc)
            return
        stop, take = self.risk.levels(fill.price)
        self.position = Position(qty=fill.qty, entry_price=fill.price, cost_quote=fill.quote,
                                 stop=stop, take=take, peak=fill.price, opened_at=ts)
        self.risk.record_entry()
        self.save()  # persist the position before anything else can fail
        self.store.log_trade(ts=ts, mode=self.mode, symbol=self.symbol, side="buy", qty=fill.qty,
                             price=fill.price, quote=fill.quote, reason="signal", pnl_quote=None,
                             order_id=fill.order_id)
        self.notifier.send(f"[{self.mode}] BUY {self.symbol} qty={fill.qty:.6f} @ {fill.price:.4f} "
                           f"SL={stop:.4f} TP={take if take is None else round(take, 4)}")

    def _drop_position(self, ts: str, reason: str, detail: str) -> None:
        pos = self.position
        self.position = None
        self.risk.record_exit(self.bar_index)
        self.save()
        self.store.log_trade(ts=ts, mode=self.mode, symbol=self.symbol, side="abandon", qty=pos.qty,
                             price=None, quote=None, reason=reason, pnl_quote=None, order_id="")
        log.error("%s position dropped (%s): %s", ts, reason, detail)
        self.notifier.send(f"[{self.mode}] ⚠️ position {self.symbol} dropped ({reason}): {detail}")

    def _exit(self, ts: str, price: float, reason: str) -> None:
        pos = self.position
        try:
            fill = self.broker.sell_qty(pos.qty, price)
        except DustError as exc:
            return self._drop_position(ts, "dust", f"{exc}; left in wallet")
        except PositionMissingError as exc:
            return self._drop_position(ts, "missing", str(exc))
        except OrderStateUnknown as exc:
            # keep the position: the next tick retries; if it did sell, the retry sees an
            # empty wallet and drops it. Block entries until checked.
            return self._halt(f"sell order state unknown ({reason}): {exc}")
        except BrokerError as exc:
            log.error("%s sell failed (%s): %s", ts, reason, exc)
            self.notifier.send(f"[{self.mode}] ⚠️ SELL FAILED {self.symbol}: {exc}")
            return
        pnl = fill.quote - pos.cost_quote * (fill.qty / pos.qty if pos.qty else 1)
        self.position = None
        self.risk.record_exit(self.bar_index)
        self.save()
        self.store.log_trade(ts=ts, mode=self.mode, symbol=self.symbol, side="sell", qty=fill.qty,
                             price=fill.price, quote=fill.quote, reason=reason, pnl_quote=pnl,
                             order_id=fill.order_id)
        self.notifier.send(f"[{self.mode}] SELL {self.symbol} ({reason}) @ {fill.price:.4f} PnL={pnl:+.2f}")

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
        old_stop = pos.stop
        self.risk.update_trailing(pos, high)
        if pos.stop != old_stop:
            self.save()  # a raised trailing stop must survive a restart

    def on_signal(self, ts: str, signal: int, price: float) -> None:
        """Called once per closed bar with that bar's strategy signal."""
        self.bar_index += 1
        equity = self.equity(price)
        self.risk.roll_day(ts[:10], equity)
        was_halted = self.risk.state.halted_reason
        self.risk.observe_equity(equity)
        if not was_halted and self.risk.state.halted_reason:
            self.notifier.send(f"[{self.mode}] ⛔ {self.risk.state.halted_reason} - no new entries "
                               f"until `python run.py resume`")
        if signal == SELL and self.position:
            self._exit(ts, price, "signal")
        elif signal == BUY and not self.position:
            self._enter(ts, price)
        self.save()
