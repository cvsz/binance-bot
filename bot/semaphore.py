"""At most ``limit`` tasks at a time; the rest wait in order.

Adapted from TradingAgents' `delegation.ts` Semaphore. A finished task hands
its permit straight to the next waiter (nobody can slip in between).

Used to rate-limit exchange API calls across the trading loop so the bot never
hammers the exchange with concurrent requests.
"""

from __future__ import annotations

import asyncio
from collections.abc import Awaitable, Callable
from typing import TypeVar

T = TypeVar("T")


class Semaphore:
    """Bounded concurrency semaphore with ordered handoff to waiters."""

    def __init__(self, limit: int) -> None:
        if limit < 1:
            raise ValueError("semaphore limit must be >= 1")
        self._limit = limit
        self._active = 0
        self._queue: list[asyncio.Future[None]] = []

    @property
    def limit(self) -> int:
        return self._limit

    @property
    def active(self) -> int:
        return self._active

    @property
    def waiting(self) -> int:
        return len(self._queue)

    async def with_task(self, task: Callable[[], Awaitable[T]]) -> T:
        """Run ``task`` under the semaphore, waiting for a permit if needed."""
        if self._active < self._limit:
            self._active += 1
        else:
            loop = asyncio.get_running_loop()
            future: asyncio.Future[None] = loop.create_future()
            self._queue.append(future)
            try:
                await future
            except BaseException:
                self._queue.remove(future)
                raise
            self._active += 1
        try:
            return await task()
        finally:
            self._active -= 1
            if self._queue:
                next_future = self._queue.pop(0)
                self._active += 1
                next_future.set_result(None)


__all__ = ["Semaphore"]
