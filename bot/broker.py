"""Order execution: PaperBroker (simulated) and LiveBroker (Binance via ccxt)."""

from __future__ import annotations

import logging
import secrets
import time
from dataclasses import dataclass

import ccxt

from .errors import DEFINITE_REJECTIONS, FATAL_ERRORS

log = logging.getLogger(__name__)


@dataclass
class Fill:
    side: str
    qty: float  # base units actually received (buy) or sold (sell)
    price: float  # average fill price
    quote: float  # quote spent (buy, incl. fees) or received (sell, net of fees)
    order_id: str = ""


class BrokerError(RuntimeError):
    """The order was not executed; account state is unchanged."""


class DustError(BrokerError):
    """The position is below the exchange's minimum order size and cannot be sold."""


class PositionMissingError(BrokerError):
    """The wallet no longer holds the position (sold manually or elsewhere)."""


class OrderStateUnknown(BrokerError):
    """An order may or may not have executed (e.g. timeout after submission).

    The account state must be checked manually before trading continues. The
    client order id travels with the exception so it can be reconciled later
    instead of silently dropping an already-filled position.
    """

    def __init__(self, message: str, client_order_id: str | None = None):
        super().__init__(message)
        self.client_order_id = client_order_id


class PaperBroker:
    """Simulated spot account with fees and slippage."""

    live = False

    def __init__(self, starting_quote: float = 1000.0, fee_pct: float = 0.1, slippage_pct: float = 0.05):
        self.base = 0.0
        self.quote = float(starting_quote)
        self.fee = fee_pct / 100
        self.slip = slippage_pct / 100
        self._n = 0

    def balances(self) -> tuple[float, float]:
        return self.base, self.quote

    def snapshot(self) -> list[float]:
        return [self.base, self.quote]

    def restore(self, snap: list[float]) -> None:
        self.base, self.quote = float(snap[0]), float(snap[1])

    def min_order_quote(self) -> float:
        return 5.0

    def buy_quote(self, quote_amount: float, price: float) -> Fill:
        quote_amount = min(quote_amount, self.quote)
        if quote_amount <= 0:
            raise BrokerError("insufficient quote balance")
        px = price * (1 + self.slip)
        qty = quote_amount * (1 - self.fee) / px
        self.quote -= quote_amount
        self.base += qty
        self._n += 1
        return Fill("buy", qty, px, quote_amount, f"paper-{self._n}")

    def sell_qty(self, qty: float, price: float) -> Fill:
        qty = min(qty, self.base)
        if qty <= 0:
            raise PositionMissingError("nothing to sell")
        px = price * (1 - self.slip)
        net = qty * px * (1 - self.fee)
        self.base -= qty
        self.quote += net
        self._n += 1
        return Fill("sell", qty, px, net, f"paper-{self._n}")


class LiveBroker:
    """Binance spot through ccxt. Only market orders; respects exchange limits/precision.

    Quantities are measured from balance deltas, so fees charged in the base asset
    (or in BNB) are handled correctly. Every order carries a client order id so that
    an order whose submission timed out can be looked up instead of being lost.
    """

    live = True

    def __init__(
        self,
        exchange,
        symbol: str,
        settle_attempts: int = 5,
        settle_delay: float = 1.0,
        lookup_attempts: int = 3,
        lookup_delay: float = 2.0,
        balance_cache_ttl: float = 5.0,
    ):
        self.ex = exchange
        self.symbol = symbol
        self.settle_attempts, self.settle_delay = settle_attempts, settle_delay
        self.lookup_attempts, self.lookup_delay = lookup_attempts, lookup_delay
        self.balance_cache_ttl = balance_cache_ttl
        self._balance_cache: tuple[float, float] | None = None
        self._balance_cache_time: float = 0.0
        self.ex.load_markets()
        if symbol not in self.ex.markets:
            raise BrokerError(f"symbol {symbol} not available on {self.ex.id}")
        self.market = self.ex.markets[symbol]
        if not self.market.get("spot", True):
            raise BrokerError("only spot markets are supported")
        self.base_ccy, self.quote_ccy = self.market["base"], self.market["quote"]

    # ---- account -----------------------------------------------------------
    def balances(self, use_cache: bool = True) -> tuple[float, float]:
        now = time.monotonic()
        if use_cache and self._balance_cache is not None and (now - self._balance_cache_time) < self.balance_cache_ttl:
            return self._balance_cache
        bal = self.ex.fetch_balance()
        free = bal.get("free", {})
        result = (float(free.get(self.base_ccy) or 0), float(free.get(self.quote_ccy) or 0))
        self._balance_cache = result
        self._balance_cache_time = now
        return result

    def invalidate_balance_cache(self) -> None:
        """Force the next balances() call to re-fetch from the exchange."""
        self._balance_cache = None
        self._balance_cache_time = 0.0

    def _limit(self, kind: str) -> float | None:
        v = ((self.market.get("limits") or {}).get(kind) or {}).get("min")
        return float(v) if v else None

    def min_order_quote(self) -> float:
        return self._limit("cost") or 5.0

    # ---- order plumbing ----------------------------------------------------
    @staticmethod
    def _client_id(side: str) -> str:
        # Binance: ^[.A-Z:/a-z0-9_-]{1,36}$
        return f"bb{side[0]}{int(time.time() * 1000)}{secrets.token_hex(4)}"

    def _submit(self, side: str, create) -> dict:
        """Submit an order; on a network failure, look it up by client id.

        Returns the order dict. Raises BrokerError if the order is known NOT to exist,
        OrderStateUnknown if its fate cannot be determined.
        """
        cid = self._client_id(side)
        try:
            return create({"newClientOrderId": cid})  # type: ignore[no-any-return]
        except DEFINITE_REJECTIONS as exc:
            # Authentication/symbol failures stay fatal. Other known rejections
            # mean the order was definitely NOT placed, so translate them into a
            # plain BrokerError (log and retry on the next signal, no halt).
            if isinstance(exc, FATAL_ERRORS):
                raise
            raise BrokerError(f"{side} order rejected: {exc}") from exc
        except (ccxt.NetworkError, ccxt.ExchangeError) as exc:
            # Any other failure leaves the outcome unknown — including exchange
            # errors that are not obviously rejections. Never retry blindly:
            # look the order up by client id, then fail closed.
            log.warning("%s order %s submission failed (%s); looking it up", side, cid, exc)
            for attempt in range(self.lookup_attempts):
                time.sleep(self.lookup_delay * (attempt + 1))
                try:
                    order = self.ex.fetch_order("", self.symbol, {"clientOrderId": cid})
                    log.warning("%s order %s was placed despite the error (status=%s)", side, cid, order.get("status"))
                    return order  # type: ignore[no-any-return]
                except ccxt.OrderNotFound:
                    raise BrokerError(f"{side} order not placed: {exc}") from exc
                except ccxt.NetworkError:
                    continue
            raise OrderStateUnknown(
                f"{side} order {cid} submitted but its state is unknown after {self.lookup_attempts} lookups "
                f"- check open orders/balances on Binance",
                client_order_id=cid,
            ) from exc

    def _settle(self, before: tuple[float, float], expected: float, side: str) -> tuple[float, float] | None:
        """Wait for the wallet to reflect the WHOLE fill, not just a partial change.

        `expected` is the base-asset amount the exchange reported as filled (net of
        a base-denominated fee on buys). Without it, a partial fill or an unrelated
        transfer could be mistaken for a completed order and leave coins untracked.
        """
        try:
            after = before
            for _ in range(self.settle_attempts):
                after = self.balances(use_cache=False)
                moved = after[0] - before[0] if side == "buy" else before[0] - after[0]
                if expected <= 0 or moved >= expected * 0.999999:
                    return after
                time.sleep(self.settle_delay)
            return after
        except ccxt.NetworkError as exc:
            log.warning("could not read balances after order: %s", exc)
            return None

    @staticmethod
    def _fee(order: dict, ccy: str) -> float:
        """Total fee charged in `ccy` according to the order response."""
        fees = order.get("fees") or ([order["fee"]] if order.get("fee") else [])
        return sum(float(f.get("cost") or 0) for f in fees if f and f.get("currency") == ccy)

    def fill_from_order(self, client_order_id: str, side: str) -> Fill | None:
        """Reconcile an order whose result was lost, by client order id.

        Returns None when the order is unknown, still open or was canceled — the
        caller keeps the position and the halt in place in that case.
        """
        try:
            order = self.ex.fetch_order("", self.symbol, {"clientOrderId": client_order_id})
        except (ccxt.OrderNotFound, ccxt.NetworkError):
            return None
        if order.get("status") in ("canceled", "expired", "rejected"):
            return None
        filled = float(order.get("filled") or 0)
        if filled <= 0:
            return None
        if side == "buy":
            qty = filled - self._fee(order, self.base_ccy)
            quote = float(order.get("cost") or 0) + self._fee(order, self.quote_ccy)
        else:
            qty = filled
            quote = float(order.get("cost") or 0) - self._fee(order, self.quote_ccy)
        if qty <= 0:
            return None
        avg = float(order.get("average") or 0) or (quote / qty)
        return Fill(side, qty, avg, quote, str(order.get("id", "")))

    # ---- orders -----------------------------------------------------------
    def buy_quote(self, quote_amount: float, price: float) -> Fill:
        if quote_amount < self.min_order_quote():
            raise BrokerError(f"order {quote_amount:.2f} below exchange minimum {self.min_order_quote()}")
        before = self.balances()
        cost = float(self.ex.cost_to_precision(self.symbol, quote_amount))
        order = self._submit("buy", lambda p: self.ex.create_market_buy_order_with_cost(self.symbol, cost, p))
        expected = max(0.0, float(order.get("filled") or 0) - self._fee(order, self.base_ccy))
        after = self._settle(before, expected, "buy")
        qty = after[0] - before[0] if after else 0.0
        spent = before[1] - after[1] if after else 0.0
        if qty <= 0:
            # fall back to what the exchange reported for the order itself
            filled = float(order.get("filled") or 0)
            qty = filled - self._fee(order, self.base_ccy)
            spent = float(order.get("cost") or 0) + self._fee(order, self.quote_ccy)
            if qty <= 0:
                if order.get("status") in ("canceled", "expired", "rejected"):
                    raise BrokerError(f"buy order {order.get('id')} {order.get('status')} with no fill")
                raise OrderStateUnknown(
                    f"buy order {order.get('id')} accepted but fill could not be confirmed",
                    client_order_id=order.get("clientOrderId"),
                ) from None
            log.warning("buy fill taken from order response (balances unavailable)")
        avg = order.get("average") or (spent / qty)
        log.info("LIVE BUY %s qty=%.8f avg=%.8f spent=%.4f", self.symbol, qty, avg, spent)
        self.invalidate_balance_cache()
        return Fill("buy", qty, float(avg), spent, str(order.get("id", "")))

    def sell_qty(self, qty: float, price: float) -> Fill:
        before = self.balances()
        if before[0] < qty * 0.5:
            raise PositionMissingError(f"wallet holds {before[0]:.8f} {self.base_ccy}, position is {qty:.8f}")
        qty = min(qty, before[0])
        min_cost, min_amt = self.min_order_quote(), self._limit("amount")
        if qty * price < min_cost or (min_amt and qty < min_amt):
            raise DustError(
                f"{qty:.8f} {self.base_ccy} (~{qty * price:.2f} {self.quote_ccy}) is below the exchange minimum"
            )
        try:
            amount = float(self.ex.amount_to_precision(self.symbol, qty))
        except ccxt.InvalidOrder as exc:
            raise DustError(str(exc)) from exc
        order = self._submit("sell", lambda p: self.ex.create_market_sell_order(self.symbol, amount, p))
        expected = max(0.0, float(order.get("filled") or 0))
        after = self._settle(before, expected, "sell")
        sold = before[0] - after[0] if after else 0.0
        received = after[1] - before[1] if after else 0.0
        if sold <= 0:
            sold = float(order.get("filled") or 0)
            received = float(order.get("cost") or 0) - self._fee(order, self.quote_ccy)
            if sold <= 0:
                if order.get("status") in ("canceled", "expired", "rejected"):
                    raise BrokerError(f"sell order {order.get('id')} {order.get('status')} with no fill")
                raise OrderStateUnknown(
                    f"sell order {order.get('id')} accepted but fill could not be confirmed",
                    client_order_id=order.get("clientOrderId"),
                ) from None
            log.warning("sell fill taken from order response (balances unavailable)")
        avg = order.get("average") or (received / sold if sold else price)
        log.info("LIVE SELL %s qty=%.8f avg=%.8f received=%.4f", self.symbol, sold, avg, received)
        self.invalidate_balance_cache()
        return Fill("sell", sold, float(avg), received, str(order.get("id", "")))

    # ---- server-side stop-loss / take-profit (OCO) ---------------------------------
    def create_stop_loss_order(
        self,
        side: str,
        quantity: float,
        stop_price: float,
        limit_price: float | None = None,
    ) -> dict:
        """Create a server-side stop-loss order.

        Uses Binance STOP_LOSS (market) or STOP_LOSS_LIMIT order type.
        When stop_price is reached, Binance automatically places the order.

        Args:
            side: "BUY" or "SELL"
            quantity: quantity in base asset
            stop_price: trigger price
            limit_price: limit price for STOP_LOSS_LIMIT (None = market stop)

        Returns the order dict from the exchange.
        """
        order_type = "STOP_LOSS_LIMIT" if limit_price else "STOP_LOSS"
        price_precision = getattr(self.ex, "price_to_precision", None)
        create_order_fn = getattr(self.ex, "create_order", None)
        if create_order_fn is None:
            raise BrokerError("exchange does not support server-side orders")
        stop_price_str = price_precision(self.symbol, stop_price) if price_precision else str(stop_price)
        params: dict = {
            "symbol": self.symbol,
            "side": side,
            "type": order_type,
            "quantity": self.ex.amount_to_precision(self.symbol, quantity),
            "stopPrice": stop_price_str,
        }
        if limit_price is not None:
            limit_price_str = price_precision(self.symbol, limit_price) if price_precision else str(limit_price)
            params["price"] = limit_price_str
            params["timeInForce"] = "GTC"

        order = self._submit_server_side("stop-loss", lambda p: self.ex.create_order(**{**params, **p}))
        log.info(
            "LIVE STOP-LOSS %s side=%s qty=%.8f stop=%.8f limit=%s",
            self.symbol,
            side,
            quantity,
            stop_price,
            limit_price,
        )
        return order

    def create_take_profit_order(
        self,
        side: str,
        quantity: float,
        take_price: float,
        limit_price: float | None = None,
    ) -> dict:
        """Create a server-side take-profit order.

        Uses Binance TAKE_PROFIT (market) or TAKE_PROFIT_LIMIT order type.
        When take_price is reached, Binance automatically places the order.

        Args:
            side: "BUY" or "SELL"
            quantity: quantity in base asset
            take_price: trigger price
            limit_price: limit price for TAKE_PROFIT_LIMIT (None = market take-profit)

        Returns the order dict from the exchange.
        """
        order_type = "TAKE_PROFIT_LIMIT" if limit_price else "TAKE_PROFIT"
        price_precision = getattr(self.ex, "price_to_precision", None)
        create_order_fn = getattr(self.ex, "create_order", None)
        if create_order_fn is None:
            raise BrokerError("exchange does not support server-side orders")
        take_price_str = price_precision(self.symbol, take_price) if price_precision else str(take_price)
        params: dict = {
            "symbol": self.symbol,
            "side": side,
            "type": order_type,
            "quantity": self.ex.amount_to_precision(self.symbol, quantity),
            "stopPrice": take_price_str,
        }
        if limit_price is not None:
            limit_price_str = price_precision(self.symbol, limit_price) if price_precision else str(limit_price)
            params["price"] = limit_price_str
            params["timeInForce"] = "GTC"

        order = self._submit_server_side("take-profit", lambda p: self.ex.create_order(**{**params, **p}))
        log.info(
            "LIVE TAKE-PROFIT %s side=%s qty=%.8f take=%.8f limit=%s",
            self.symbol,
            side,
            quantity,
            take_price,
            limit_price,
        )
        return order

    def cancel_order(self, order_id: str) -> dict:
        """Cancel an order by order id."""
        try:
            result = self.ex.cancel_order(self.symbol, order_id)
            log.info("LIVE CANCEL ORDER %s order_id=%s", self.symbol, order_id)
            return result  # type: ignore[no-any-return]
        except ccxt.OrderNotFound:
            log.warning("LIVE CANCEL ORDER %s order_id=%s not found", self.symbol, order_id)
            raise
        except ccxt.NetworkError as exc:
            log.warning("LIVE CANCEL ORDER %s order_id=%s network error: %s", self.symbol, order_id, exc)
            raise

    def cancel_all_orders(self) -> list[dict]:
        """Cancel all open orders for this symbol."""
        try:
            result = self.ex.cancel_all_orders(self.symbol)
            log.info("LIVE CANCEL ALL ORDERS %s canceled=%d orders", self.symbol, len(result))
            return result  # type: ignore[no-any-return]
        except ccxt.NetworkError as exc:
            log.warning("LIVE CANCEL ALL ORDERS %s network error: %s", self.symbol, exc)
            raise

    def _submit_server_side(self, side: str, create) -> dict:
        """Submit a server-side order; on network failure, look it up by client order id."""
        cid = self._client_id(side)
        try:
            return create({"newClientOrderId": cid})  # type: ignore[no-any-return]
        except DEFINITE_REJECTIONS as exc:
            if isinstance(exc, FATAL_ERRORS):
                raise
            raise BrokerError(f"{side} server-side order rejected: {exc}") from exc
        except (ccxt.NetworkError, ccxt.ExchangeError) as exc:
            log.warning("%s server-side order %s submission failed (%s); looking it up", side, cid, exc)
            for attempt in range(self.lookup_attempts):
                time.sleep(self.lookup_delay * (attempt + 1))
                try:
                    order = self.ex.fetch_order("", self.symbol, {"clientOrderId": cid})
                    log.warning(
                        "%s server-side order %s was placed despite error (status=%s)",
                        side,
                        cid,
                        order.get("status"),
                    )
                    return order  # type: ignore[no-any-return]
                except ccxt.OrderNotFound:
                    raise BrokerError(f"{side} server-side order not placed: {exc}") from exc
                except ccxt.NetworkError:
                    continue
            raise OrderStateUnknown(
                f"{side} server-side order {cid} submitted but state unknown after {self.lookup_attempts} lookups",
                client_order_id=cid,
            ) from exc
