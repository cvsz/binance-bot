"""Broker error taxonomy and retry policy.

Pattern ported from the MIT-licensed `zksato` project (github.com/cvsz/zksato,
`packages/zksato-broker/src/zksato_broker/errors.py`), adapted to ccxt's sync API
used by this bot. The goal is the same: an order whose outcome is unknown is
never retried blindly, and each error class gets its own retry behaviour.
"""

from __future__ import annotations

import random
import re
from dataclasses import dataclass
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


# ---- Retry policy (pattern adapted from zksato) -----------------------------


@dataclass(frozen=True, slots=True)
class RetryPolicy:
    """Retry policy for a specific error category.

    Attributes:
        max_attempts: Maximum number of retry attempts (0 = never retry).
        base_delay: Initial delay in seconds before the first retry.
        max_delay: Maximum delay cap in seconds.
        exponential_base: Base for exponential backoff multiplication.
        jitter: Whether to apply random jitter to the delay.
    """

    max_attempts: int = 3
    base_delay: float = 1.0
    max_delay: float = 30.0
    exponential_base: float = 2.0
    jitter: bool = True

    def get_delay(self, attempt: int) -> float:
        """Calculate the delay (in seconds) for a given 0-indexed attempt number.

        Returns 0.0 when ``attempt >= max_attempts`` (no more retries allowed).

        Uses :func:`random.random` for non-cryptographic jitter only — not for
        any security-sensitive purpose.
        """
        if attempt >= self.max_attempts:
            return 0.0
        delay = min(self.base_delay * (self.exponential_base**attempt), self.max_delay)
        if self.jitter:
            delay *= 0.5 + random.random()  # noqa: S311 - retry jitter, not crypto
        return delay


# Default retry policies per error category. Kept conservative so that
# transient/network errors retry but auth/order rejections never do.
RETRY_POLICIES: dict[ErrorCategory, RetryPolicy] = {
    ErrorCategory.TRANSIENT: RetryPolicy(max_attempts=3, base_delay=1.0, max_delay=30.0),
    ErrorCategory.RATE_LIMITED: RetryPolicy(max_attempts=5, base_delay=5.0, max_delay=60.0),
    ErrorCategory.AUTH_FAILED: RetryPolicy(max_attempts=0),
    ErrorCategory.INVALID_ORDER: RetryPolicy(max_attempts=0),
    ErrorCategory.REJECTED: RetryPolicy(max_attempts=0),
    ErrorCategory.UNKNOWN: RetryPolicy(max_attempts=1, base_delay=10.0, max_delay=10.0),
}


def is_retryable_error(error: Exception) -> bool:
    """Return True if ``error`` belongs to a retryable category.

    Transient, rate-limited, and unknown errors are retryable. Auth failures,
    invalid orders, and rejections are not.
    """
    category = classify_error(error)
    return category in (
        ErrorCategory.TRANSIENT,
        ErrorCategory.RATE_LIMITED,
        ErrorCategory.UNKNOWN,
    )


def is_fatal_error(error: Exception) -> bool:
    """Return True if ``error`` is fatal and should stop the bot immediately.

    Fatal errors are authentication failures, invalid orders, and rejections —
    none of which can be resolved by retrying.
    """
    category = classify_error(error)
    return category in (
        ErrorCategory.AUTH_FAILED,
        ErrorCategory.INVALID_ORDER,
        ErrorCategory.REJECTED,
    )


def should_retry(error: Exception, attempt: int) -> tuple[bool, float]:
    """Determine whether to retry ``error`` and the delay to apply.

    Returns a ``(should_retry, delay_seconds)`` tuple. ``delay_seconds`` is
    0.0 when no retry should be attempted.
    """
    policy = RETRY_POLICIES.get(classify_error(error), RETRY_POLICIES[ErrorCategory.UNKNOWN])
    if attempt >= policy.max_attempts:
        return False, 0.0
    return True, policy.get_delay(attempt)


__all__ = [
    "ErrorCategory",
    "FATAL_ERRORS",
    "NO_RETRY_ERRORS",
    "DEFINITE_REJECTIONS",
    "classify_error",
    "retry_after",
    "RetryPolicy",
    "RETRY_POLICIES",
    "is_retryable_error",
    "is_fatal_error",
    "should_retry",
]
