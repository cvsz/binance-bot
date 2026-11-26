"""Decimal money handling and currency utilities.

Adapted from zksato's money module. Provides immutable, decimal-precision
money values to avoid floating-point rounding errors in financial
calculations. Supports multiple quote currencies (USDT, THB) used by
binance-bot.
"""

from __future__ import annotations

from dataclasses import dataclass
from decimal import ROUND_HALF_UP, Decimal

Numeric = int | float | Decimal


@dataclass(frozen=True, slots=True)
class Money:
    """Immutable money value with currency.

    All arithmetic uses ``decimal.Decimal`` to avoid binary floating-point
    rounding errors that can accumulate in financial calculations.
    """

    amount: Decimal
    currency: str = "USDT"

    def __post_init__(self) -> None:
        object.__setattr__(self, "amount", Decimal(str(self.amount)))

    def __add__(self, other: Money) -> Money:
        if not isinstance(other, Money):
            return NotImplemented
        if self.currency != other.currency:
            raise ValueError(f"currency mismatch: {self.currency} vs {other.currency}")
        return Money(self.amount + other.amount, self.currency)

    def __sub__(self, other: Money) -> Money:
        if not isinstance(other, Money):
            return NotImplemented
        if self.currency != other.currency:
            raise ValueError(f"currency mismatch: {self.currency} vs {other.currency}")
        return Money(self.amount - other.amount, self.currency)

    def __mul__(self, factor: Numeric) -> Money:
        if not isinstance(factor, (int, float, Decimal)):
            return NotImplemented
        return Money(self.amount * Decimal(str(factor)), self.currency)

    def __rmul__(self, factor: Numeric) -> Money:
        return self.__mul__(factor)

    def __truediv__(self, divisor: Numeric) -> Money:
        if not isinstance(divisor, (int, float, Decimal)):
            return NotImplemented
        divisor_d = Decimal(str(divisor))
        if divisor_d == 0:
            raise ZeroDivisionError("cannot divide by zero")
        return Money(self.amount / divisor_d, self.currency)

    def __neg__(self) -> Money:
        return Money(-self.amount, self.currency)

    def __lt__(self, other: Money) -> bool:
        if not isinstance(other, Money):
            return NotImplemented
        if self.currency != other.currency:
            raise ValueError(f"currency mismatch: {self.currency} vs {other.currency}")
        return self.amount < other.amount

    def __le__(self, other: Money) -> bool:
        return self == other or self < other

    def __gt__(self, other: Money) -> bool:
        if not isinstance(other, Money):
            return NotImplemented
        if self.currency != other.currency:
            raise ValueError(f"currency mismatch: {self.currency} vs {other.currency}")
        return self.amount > other.amount

    def __ge__(self, other: Money) -> bool:
        return self == other or self > other

    def __eq__(self, other: object) -> bool:
        if not isinstance(other, Money):
            return NotImplemented
        return self.amount == other.amount and self.currency == other.currency

    def __hash__(self) -> int:
        return hash((self.amount, self.currency))

    def abs(self) -> Money:
        return Money(abs(self.amount), self.currency)

    def quantize(self, exp: str = "0.01") -> Money:
        """Quantize to a fixed number of decimal places."""
        return Money(
            self.amount.quantize(Decimal(exp), rounding=ROUND_HALF_UP),
            self.currency,
        )

    def to_float(self) -> float:
        return float(self.amount)

    def to_int(self) -> int:
        return int(self.amount)

    @classmethod
    def zero(cls, currency: str = "USDT") -> Money:
        return cls(Decimal("0"), currency)

    @classmethod
    def from_float(cls, value: float, currency: str = "USDT") -> Money:
        return cls(Decimal(str(value)), currency)

    def __str__(self) -> str:
        return f"{self.amount:.2f} {self.currency}"

    def __repr__(self) -> str:
        return f"Money({self.amount!r}, {self.currency!r})"


def usdt(amount: Numeric) -> Money:
    """Create a Money value in USDT."""
    return Money(Decimal(str(amount)), "USDT")


def thb(amount: Numeric) -> Money:
    """Create a Money value in THB."""
    return Money(Decimal(str(amount)), "THB")


__all__ = [
    "Money",
    "Numeric",
    "usdt",
    "thb",
]
