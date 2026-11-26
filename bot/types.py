"""Shared enums, type aliases, and constants for the binance-bot domain.

Adapted from zksato's shared types module, simplified for the single-pair
Binance Spot architecture. All types are import-safe (no third-party deps).
"""

from __future__ import annotations

from enum import StrEnum


class Side(StrEnum):
    """Order side: BUY or SELL."""

    BUY = "buy"
    SELL = "sell"


class OrderType(StrEnum):
    """Order type supported by the engine."""

    MARKET = "market"


class OrderStatus(StrEnum):
    """Order lifecycle status."""

    PENDING = "pending"
    ACCEPTED = "accepted"
    REJECTED = "rejected"
    CANCELLED = "cancelled"
    PARTIALLY_FILLED = "partially_filled"
    FILLED = "filled"
    NEEDS_RECONCILIATION = "needs_reconciliation"


class SignalAction(StrEnum):
    """Strategy signal output."""

    BUY = "buy"
    SELL = "sell"
    HOLD = "hold"


class BotState(StrEnum):
    """Bot process state."""

    STOPPED = "stopped"
    RUNNING = "running"
    PAUSED = "paused"
    ERROR = "error"


class TradingMode(StrEnum):
    """Trading mode: paper, sandbox (testnet), or live."""

    PAPER = "paper"
    SANDBOX = "sandbox"
    LIVE = "live"


# ---- Type aliases -----------------------------------------------------------

OrderId = str
ClientOrderId = str
BrokerOrderId = str
FillId = str
Symbol = str
CorrelationId = str
Timestamp = str  # ISO 8601 format
QuoteAmount = float
BaseAmount = float
Price = float
MoneyAmount = float

__all__ = [
    "Side",
    "OrderType",
    "OrderStatus",
    "SignalAction",
    "BotState",
    "TradingMode",
    "OrderId",
    "ClientOrderId",
    "BrokerOrderId",
    "FillId",
    "Symbol",
    "CorrelationId",
    "Timestamp",
    "QuoteAmount",
    "BaseAmount",
    "Price",
    "MoneyAmount",
]
