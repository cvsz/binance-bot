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
# keep a little quote back so a market buy plus its fee never exceeds the free balance
LIVE_FEE_HEADROOM = 0.01


class Engine:
    def __init__(self, symbol: str, broker, risk: RiskManager, store: Store | None = None,
                 notifier=None, mode: str = "paper", batch_mode: bool = False):
        self.symbol = symbol
        self.broker = broker
        self.risk = risk
        self.store = store or Store()
        self.notifier = notifier or NullNotifier()
        self.mode = mode
        self.position: Position | None = None
        self.bar_index = 0
        self._dirty: bool = False
        self._batch_mode: bool = batch_mode

    def _mark_dirty(self) -> None:
        self._dirty = True

    # ---- persistence -----------------------------------------------------
    def save(self, force: bool = False) -> None:
        """Persist position, risk state and (paper) balances in ONE transaction, so a
        crash can never leave a recorded position without the matching balances.

        When force=False (default), the write is skipped unless state has changed
        since the last successful save, avoiding redundant SQLite writes.

        In batch_mode (backtest), per-bar saves are skipped entirely; call save(force=True)
        once at the end to persist the final state.
        """
        if self._batch_mode and not force:
            return
        if not self._dirty and not force:
            return
        items = {
            "position": asdict(self.position) if self.position else None,
            "risk": self.risk.state_dict(),
            "bar_index": self.bar_index,
        }
        if hasattr(self.broker, "snapshot"):
            items["paper_balances"] = self.broker.snapshot()
        self.store.put_many(items)
        self._dirty = False

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
        prev = self.risk.resume(self.equity(price) if price else None)
        self._mark_dirty()
        self.save()
        # delete only AFTER the new state is durable: a crash in between must not
        # silently lose the operator's resume request
        self.store.delete(RESUME_KEY)
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
        available = quote * (1 - LIVE_FEE_HEADROOM) if self.broker.live else quote
        size = self.risk.position_size_quote(equity, available)
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
                                 stop=stop, take=take, peak=fill.price, opened_at=ts,
                                 pending_order_id=None)
        self.risk.record_entry()
        self._mark_dirty()
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
        self._mark_dirty()
        self.save()
        self.store.log_trade(ts=ts, mode=self.mode, symbol=self.symbol, side="abandon", qty=pos.qty,
                             price=None, quote=None, reason=reason, pnl_quote=None, order_id="")
        log.error("%s position dropped (%s): %s", ts, reason, detail)
        self.notifier.send(f"[{self.mode}] ⚠️ position {self.symbol} dropped ({reason}): {detail}")

    def _record_exit(self, ts: str, fill, pos: Position, reason: str) -> None:
        """Book a completed sell exactly once (called from the normal and recovered paths)."""
        pnl = fill.quote - pos.cost_quote * (fill.qty / pos.qty if pos.qty else 1)
        self.position = None
        self.risk.record_exit(self.bar_index)
        self._mark_dirty()
        self.save()
        self.store.log_trade(ts=ts, mode=self.mode, symbol=self.symbol, side="sell", qty=fill.qty,
                             price=fill.price, quote=fill.quote, reason=reason, pnl_quote=pnl,
                             order_id=fill.order_id)
        self.notifier.send(f"[{self.mode}] SELL {self.symbol} ({reason}) @ {fill.price:.4f} PnL={pnl:+.2f}")

    def _exit(self, ts: str, price: float, reason: str) -> None:
        pos = self.position
        # A previous sell may have filled while its result was lost. Reconcile by
        # client order id BEFORE retrying, so the wallet looks empty but the PnL is
        # still recorded instead of the position being dropped as "missing".
        if pos.pending_order_id and hasattr(self.broker, "fill_from_order"):
            recovered = self.broker.fill_from_order(pos.pending_order_id, "sell")
            if recovered is not None:
                log.warning("%s recovered sell %s by client order id", ts, pos.pending_order_id)
                return self._record_exit(ts, recovered, pos, reason)
        try:
            fill = self.broker.sell_qty(pos.qty, price)
        except DustError as exc:
            return self._drop_position(ts, "dust", f"{exc}; left in wallet")
        except PositionMissingError as exc:
            return self._drop_position(ts, "missing", str(exc))
        except OrderStateUnknown as exc:
            # keep the position: the next tick retries; if it did sell, the retry
            # reconciles via the client id and books the real fill. Block entries
            # until a human checks.
            pos.pending_order_id = exc.client_order_id
            self._mark_dirty()
            self.save()
            return self._halt(f"sell order state unknown ({reason}): {exc}")
        except BrokerError as exc:
            log.error("%s sell failed (%s): %s", ts, reason, exc)
            self.notifier.send(f"[{self.mode}] ⚠️ SELL FAILED {self.symbol}: {exc}")
            return
        self._record_exit(ts, fill, pos, reason)

    # ---- event handlers --------------------------------------------------
    def on_price(self, ts: str, low: float, high: float, open_: float | None = None) -> None:
        """Manage stop / take-profit / trailing for an open position.

        Backtest passes bar open/low/high; live passes the last price for low/high
        and NO open (otherwise every live stop would be mislabeled as a gap).
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
            self._mark_dirty()
            self.save()  # a raised trailing stop must survive a restart
            # the new stop may already have been breached by this very bar's low
            if low <= pos.stop:
                return self._exit(ts, pos.stop, "trailing_stop")

    def on_signal(self, ts: str, signal: int, price: float, mark_price: float | None = None) -> None:
        """Called once per closed bar with that bar's strategy signal.

        `price` is the execution price; `mark_price` (when given) is used only for
        risk/equity checks so the backtest's kill switches and equity curve agree.
        """
        self.bar_index += 1
        self._mark_dirty()
        equity = self.equity(mark_price if mark_price is not None else price)
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
