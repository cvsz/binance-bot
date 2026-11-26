"""Recovery policy for exchange calls.

Adapted from TradingAgents' `agents/recovery.ts`. One policy for every
call the bot makes (exchange steps, history summaries). A failure that may
pass (a stream cut mid-reply included) is tried again after a pause; a
context that did not fit is made smaller once; a reply that came back blank
is asked for once more.

Provides a structured decision tree instead of ad-hoc try/except blocks.
"""

from __future__ import annotations

import asyncio
from dataclasses import dataclass
from typing import TypeVar

T = TypeVar("T")

RETRY_MS = [1000, 2000]


@dataclass(frozen=True, slots=True)
class Attempt:
    """What a single call attempt produced."""

    error: str | None = None
    finish: str | None = None  # "stop", "length", "other"
    text: str = ""
    calls: int = 0


@dataclass(frozen=True, slots=True)
class Tried:
    """What the call has been through so far."""

    backoffs: int = 0
    regenerated: bool = False
    compacted: bool = False


@dataclass(frozen=True, slots=True)
class Allowed:
    """What the caller can do."""

    compact: bool = False
    unseen: bool = False
    output_tokens: int | None = None
    output_ceiling: int | None = None


# Recovery actions
ACTION_DONE = "done"
ACTION_BACKOFF = "backoff"
ACTION_COMPACT = "compact"
ACTION_REGENERATE = "regenerate"
ACTION_FATAL = "fatal"


def recover(attempt: Attempt, tried: Tried, allowed: Allowed) -> dict:
    """Decide what to do after a call attempt.

    Returns a dict with ``action`` and, for backoff, ``delay_ms``.
    """
    if attempt.error is not None:
        if attempt.error == "aborted":
            return {ACTION: ACTION_FATAL}
        delay_ms = RETRY_MS[tried.backoffs] if tried.backoffs < len(RETRY_MS) else None
        if attempt.error == "retryable" and delay_ms is not None:
            return {ACTION: ACTION_BACKOFF, "delay_ms": delay_ms}
        if attempt.error == "context" and allowed.compact and not tried.compacted:
            return {ACTION: ACTION_COMPACT}
        return {ACTION: ACTION_FATAL}

    blank = not attempt.text.strip() and attempt.calls == 0
    cut = attempt.finish == "length" and attempt.calls == 0 and (blank or allowed.unseen)
    if not blank and not cut:
        return {ACTION: ACTION_DONE}
    if cut:
        if (
            allowed.output_tokens is None
            or allowed.output_ceiling is None
            or allowed.output_tokens >= allowed.output_ceiling
        ):
            return {ACTION: ACTION_DONE}
        return {
            ACTION: ACTION_REGENERATE,
            "max_output_tokens": min(allowed.output_tokens * 2, allowed.output_ceiling),
        }
    if attempt.finish in ("stop", "other"):
        return {ACTION: ACTION_REGENERATE}
    return {ACTION: ACTION_DONE}


ACTION = "action"


async def under_policy(
    attempt_call,
    view_call,
    allowed: Allowed,
    signal=None,
    sleep=None,
    on_retry=None,
):
    """One exchange call under the recovery policy.

    ``attempt_call(max_output_tokens)`` makes the call with an output limit.
    ``view_call(attempt)`` reads it for the policy. ``on_retry`` hears of
    each pause. Returns the last attempt plus whether the caller should
    compact or the pause was cancelled.
    """
    if sleep is None:

        async def sleep(ms, sig=None):
            await asyncio.sleep(ms / 1000.0)

    tried = Tried()
    limit = allowed.output_tokens
    set_aside = None
    set_aside_chars = 0

    while True:
        last = await attempt_call(limit)
        decision = recover(view_call(last), tried, allowed)

        if decision.get(ACTION) in (ACTION_DONE, ACTION_FATAL):
            return {"last": last, "set_aside_chars": set_aside_chars}
        if decision.get(ACTION) == ACTION_COMPACT:
            return {"last": last, "set_aside_chars": set_aside_chars, "compact": True}

        # Accumulate set-aside attempt tokens.
        if set_aside is None:
            set_aside = {"input_tokens": 0, "output_tokens": 0}
        set_aside_chars += len(last.text)

        if decision.get(ACTION) == ACTION_REGENERATE:
            tried = Tried(
                backoffs=tried.backoffs,
                regenerated=True,
                compacted=tried.compacted,
            )
            if decision.get("max_output_tokens") is not None:
                limit = decision["max_output_tokens"]
            continue

        tried = Tried(
            backoffs=tried.backoffs + 1,
            regenerated=tried.regenerated,
            compacted=tried.compacted,
        )
        if on_retry is not None:
            on_retry(last, {"attempt": tried.backoffs, "of": len(RETRY_MS)})
        try:
            await sleep(decision["delay_ms"], signal)
        except (asyncio.CancelledError, Exception):
            return {"last": last, "set_aside_chars": set_aside_chars, "cancelled": True}


__all__ = [
    "Attempt",
    "Tried",
    "Allowed",
    "recover",
    "under_policy",
    "ACTION_DONE",
    "ACTION_BACKOFF",
    "ACTION_COMPACT",
    "ACTION_REGENERATE",
    "ACTION_FATAL",
    "RETRY_MS",
]
