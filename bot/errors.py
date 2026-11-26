"""Broker error taxonomy and retry policy.

Pattern ported from the MIT-licensed `zksato` project (github.com/cvsz/zksato,
`packages/zksato-broker/src/zksato_broker/errors.py`), adapted to ccxt's sync API
used by this bot. The goal is the same: an order whose outcome is unknown is
never retried blindly, and each error class gets its own retry behaviour.
"""

from __future__ import annotations

import re
from enum import StrEnum

import ccxt


class ErrorCategory(StrEnum):
    TRANSIENT = "transient"  # backoff then retry
    RATE_LIMITED = "rate_limited"  # respect retry-after, then retry
    AUTH_FAILED = "auth_failed"  # stop the bot, never retry
    INVALID_ORDER = "invalid_order"  # do not retry as-is
    REJECTED = "rejected"  # do not retry as-is
    UNKNOWN = "unknown"  # backoff, alert a human


# Fatal: retrying cannot fix these. Kept identical to the existing runner gate.
FATAL_ERRORS = (ccxt.AuthenticationError, ccxt.AccountSuspended, ccxt.BadSymbol)
# The exchange definitely did NOT accept the order — safe to treat as a clean failure.
NO_RETRY_ERRORS = (ccxt.InsufficientFunds, ccxt.InvalidOrder, ccxt.ArgumentsRequired)
DEFINITE_REJECTIONS = FATAL_ERRORS + NO_RETRY_ERRORS

_RETRY_AFTER_RE = re.compile(r"retry.?after[:\s]+(\d+)", re.IGNORECASE)


def classify_error(exc: Exception) -> ErrorCategory:
    """Classify an exception by ccxt type first, then by message keywords."""
    if isinstance(exc, FATAL_ERRORS):
        return ErrorCategory.AUTH_FAILED
    if isinstance(exc, (ccxt.RateLimitExceeded, ccxt.DDoSProtection)):
        return ErrorCategory.RATE_LIMITED
    if isinstance(exc, NO_RETRY_ERRORS):
        return ErrorCategory.REJECTED
    if isinstance(exc, ccxt.NetworkError):
        return ErrorCategory.TRANSIENT

    text = str(exc).lower()
    if any(k in text for k in ("rate limit", "429", "too many requests", "throttle")):
        return ErrorCategory.RATE_LIMITED
    if any(k in text for k in ("timeout", "connection", "network", "dns", "unreachable")):
        return ErrorCategory.TRANSIENT
    if any(k in text for k in ("unauthorized", "401", "invalid api", "invalid secret")):
        return ErrorCategory.AUTH_FAILED
    if any(k in text for k in ("insufficient", "not enough", "invalid order", "bad request")):
        return ErrorCategory.REJECTED
    return ErrorCategory.UNKNOWN


def retry_after(exc: Exception) -> float | None:
    """Extract a `retry-after: N` hint from the message, when the exchange gives one."""
    match = _RETRY_AFTER_RE.search(str(exc))
    return float(match.group(1)) if match else None
