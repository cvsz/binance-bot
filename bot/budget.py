"""Keeping candle data within indicator limits.

Adapted from TradingAgents' `agents/budget.py`. When a candle window would
exceed the indicator lookback, the oldest candles are removed first, keeping
the window valid. A call keeps its own result, so the conversation stays valid.

Used to manage rolling candle windows so indicators always see enough
history without unbounded memory growth.
"""

from __future__ import annotations

from typing import TypeVar

T = TypeVar("T")

CHARS_PER_TOKEN = 2
SAVED_CHARS_PER_TOKEN = 4
MARGIN_TOKENS = 2048
MIN_ELIDED_CHARS = 400


def estimate_tokens(chars: int, max_output_tokens: int, last_chars: int | None = None) -> int:
    """Tokens a request is expected to need, output included.

    From a measurement, characters added since count at CHARS_PER_TOKEN and
    characters removed since (results elided) at SAVED_CHARS_PER_TOKEN, so
    neither is understated.
    """
    change = chars - (last_chars if last_chars is not None else 0)
    input_tokens = last_chars // CHARS_PER_TOKEN if last_chars is not None else 0
    if change >= 0:
        input_tokens += -(-change // CHARS_PER_TOKEN)  # ceil
    else:
        input_tokens -= -(-change // SAVED_CHARS_PER_TOKEN)  # ceil of negative
    return input_tokens + max_output_tokens + MARGIN_TOKENS


def elide_oldest[T](candles: list[T], keep_last: int = 1) -> int:
    """Remove the oldest elidable candle from the list.

    Returns characters saved, or 0 when nothing is left to elide.
    """
    if len(candles) <= keep_last:
        return 0
    oldest = candles.pop(0)
    return len(repr(oldest))


def fit_to_window[T](window: int, candles: list[T], max_output_tokens: int) -> int | None:
    """Elide candles until the request fits ``window`` tokens.

    Returns how many were elided, or None when it cannot be made to fit.
    """
    elided = 0
    total_chars = sum(len(repr(c)) for c in candles)
    while estimate_tokens(total_chars, max_output_tokens) > window:
        if len(candles) <= 1:
            return None
        saved = elide_oldest(candles)
        if saved == 0:
            return None
        total_chars -= saved
        elided += 1
    return elided


__all__ = ["estimate_tokens", "elide_oldest", "fit_to_window"]
