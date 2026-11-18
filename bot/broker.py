"""Order execution: PaperBroker (simulated) and LiveBroker (Binance via ccxt)."""
from __future__ import annotations

import logging
import time
from dataclasses import dataclass

log = logging.getLogger(__name__)


@dataclass
class Fill:
    side: str
    qty: float          # base units actually received (buy) or sold (sell)
    price: float        # average fill price
    quote: float        # quote spent (buy, incl. fees) or received (sell, net of fees)
    order_id: str = ""


class BrokerError(RuntimeError):
    pass


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
            raise BrokerError("nothing to sell")
        px = price * (1 - self.slip)
        net = qty * px * (1 - self.fee)
        self.base -= qty
        self.quote += net
        self._n += 1
        return Fill("sell", qty, px, net, f"paper-{self._n}")


class LiveBroker:
    """Binance spot through ccxt. Only market orders; respects exchange limits/precision.

    Quantities are measured from balance deltas, so fees charged in the base asset
    (or in BNB) are handled correctly.
    """

    live = True

    def __init__(self, exchange, symbol: str):
        self.ex = exchange
        self.symbol = symbol
        self.ex.load_markets()
        if symbol not in self.ex.markets:
            raise BrokerError(f"symbol {symbol} not available on {self.ex.id}")
        self.market = self.ex.markets[symbol]
        if not self.market.get("spot", True):
            raise BrokerError("only spot markets are supported")
        self.base_ccy, self.quote_ccy = self.market["base"], self.market["quote"]

    def balances(self) -> tuple[float, float]:
        bal = self.ex.fetch_balance()
        free = bal.get("free", {})
        return float(free.get(self.base_ccy) or 0), float(free.get(self.quote_ccy) or 0)

    def min_order_quote(self) -> float:
        cost_min = ((self.market.get("limits") or {}).get("cost") or {}).get("min")
        return float(cost_min) if cost_min else 5.0

    def _settle(self, before: tuple[float, float]) -> tuple[float, float]:
        # balances can lag the fill by a moment
        for _ in range(5):
            after = self.balances()
            if after != before:
                return after
            time.sleep(1)
        return self.balances()

    def buy_quote(self, quote_amount: float, price: float) -> Fill:
        if quote_amount < self.min_order_quote():
            raise BrokerError(f"order {quote_amount:.2f} below exchange minimum {self.min_order_quote()}")
        before = self.balances()
        cost = float(self.ex.cost_to_precision(self.symbol, quote_amount))
        order = self.ex.create_market_buy_order_with_cost(self.symbol, cost)
        after = self._settle(before)
        qty = after[0] - before[0]
        spent = before[1] - after[1]
        if qty <= 0:
            raise BrokerError(f"buy order {order.get('id')} produced no base balance change")
        avg = order.get("average") or (spent / qty)
        log.info("LIVE BUY %s qty=%.8f avg=%.8f spent=%.4f", self.symbol, qty, avg, spent)
        return Fill("buy", qty, float(avg), spent, str(order.get("id", "")))

    def sell_qty(self, qty: float, price: float) -> Fill:
        before = self.balances()
        qty = min(qty, before[0])
        amount = float(self.ex.amount_to_precision(self.symbol, qty))
        if amount <= 0:
            raise BrokerError("sell amount rounds to zero")
        order = self.ex.create_market_sell_order(self.symbol, amount)
        after = self._settle(before)
        sold = before[0] - after[0]
        received = after[1] - before[1]
        avg = order.get("average") or (received / sold if sold else price)
        log.info("LIVE SELL %s qty=%.8f avg=%.8f received=%.4f", self.symbol, sold, avg, received)
        return Fill("sell", sold, float(avg), received, str(order.get("id", "")))
