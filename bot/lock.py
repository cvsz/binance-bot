"""File-based lock held by one process, naming its holder.

Adapted from TradingAgents' `store/lock.ts`. A lock appears with its contents
complete: written to a private file first, then linked into place; the link
fails if a lock is already there. A lock whose holder was a process on this
machine that no longer exists is stale, and so is one whose process number now
names another process. A stale lock is removed only by the holder of a second
lock beside it (``<path>.break``). A lock from another machine, or one that
cannot be read, is never taken.

Provides cross-process mutual exclusion for a SQLite database path, so two bot
instances can never write the same DB simultaneously.
"""

from __future__ import annotations

import contextlib
import os
import secrets
from pathlib import Path


class LockError(RuntimeError):
    """Raised when a lock cannot be taken or released."""


class Lock:
    """A file lock held by one process.

    Instances are created only by :meth:`acquire`. Releasing removes the file
    only if this holder still owns it; releasing again is a no-op.
    """

    def __init__(self, path: str | Path, token: str) -> None:
        self._path = str(path)
        self._token = token
        self._released = False

    @property
    def path(self) -> str:
        return self._path

    @classmethod
    def acquire(cls, path: str | Path) -> Lock:
        """Take the lock at ``path``.

        Raises :class:`LockError` if the lock is held by another live process,
        is held on another host, or cannot be read.
        """
        path_str = str(path)
        parent = Path(path_str).parent
        parent.mkdir(parents=True, exist_ok=True)

        token = secrets.token_hex(12)
        me_pid = os.getpid()
        me_host = _hostname()

        # Two tries: the second after removing a stale lock.
        for _attempt in range(2):
            if _publish(path_str, me_pid, me_host, token):
                return cls(path_str, token)
            holder = _read_holder(path_str)
            if holder is None or not _is_stale(holder, me_pid, me_host, token):
                raise LockError(
                    f"lock held by pid {holder.get('pid') if holder else 'unknown'} "
                    f"on {holder.get('host') if holder else 'unknown'}"
                )
            stuck = _break_stale(path_str, holder.get("token", ""), me_pid, me_host)
            if stuck:
                raise LockError(
                    f"lock stale but takeover blocked by {stuck}; remove it by hand"
                )
        raise LockError(f"could not take lock at {path_str}")

    def release(self) -> None:
        """Remove the lock if this holder still owns it. No-op if already released."""
        if self._released:
            return
        holder = _read_holder(self._path)
        if holder is not None and holder.get("token") == self._token:
            with contextlib.suppress(FileNotFoundError):
                os.unlink(self._path)
        self._released = True

    def __enter__(self) -> Lock:
        return self

    def __exit__(self, *exc_info: object) -> None:
        self.release()


def _hostname() -> str:
    try:
        return os.uname().nodename
    except AttributeError:  # pragma: no cover - Windows
        import platform

        return platform.node()


def _publish(path: str, pid: int, host: str, token: str) -> bool:
    """Put a lock with ``holder`` at ``path`` unless one is there.

    Returns True when the lock was put.
    """
    import json

    draft = f".{token}.draft"
    draft_path = Path(path).parent / draft
    try:
        draft_path.write_text(
            json.dumps({"pid": pid, "host": host, "token": token}),
            encoding="utf-8",
        )
    except OSError:
        return False
    try:
        # link() fails with FileExistsError if a lock already exists.
        os.link(str(draft_path), path)
        return True
    except FileExistsError:
        return False
    finally:
        with contextlib.suppress(FileNotFoundError):
            draft_path.unlink()


def _read_holder(path: str) -> dict | None:
    import json

    try:
        text = Path(path).read_text(encoding="utf-8")
        value = json.loads(text)
    except (OSError, ValueError):
        return None
    if (
        isinstance(value, dict)
        and isinstance(value.get("pid"), int)
        and isinstance(value.get("host"), str)
        and isinstance(value.get("token"), str)
    ):
        return value
    return None


def _is_stale(holder: dict, me_pid: int, me_host: str, my_token: str) -> bool:
    """Return True if ``holder`` describes a dead process or another host."""
    if holder.get("host") != me_host:
        return False  # another machine: never take
    if holder.get("pid") == me_pid:
        # This process's own number: another lock by it is one left by an
        # earlier process that had the number, unless it is us right now.
        return holder.get("token") != my_token
    try:
        os.kill(int(holder["pid"]), 0)
    except ProcessLookupError:
        return True
    except PermissionError:
        return False  # alive but not ours to signal: assume live
    except OSError:
        return False
    return False


def _break_stale(path: str, token: str, me_pid: int, me_host: str) -> str | None:
    """Remove the stale lock at ``path`` while holding its breaker lock.

    Returns the breaker's path when a crashed breaker blocks the takeover,
    else None.
    """
    breaker = f"{path}.break"
    breaker_token = secrets.token_hex(12)
    if not _publish(breaker, me_pid, me_host, breaker_token):
        # Another process is breaking it, or one that crashed doing so.
        other = _read_holder(breaker)
        if other is not None and _is_stale(other, me_pid, me_host, breaker_token):
            return breaker
        return None
    try:
        holder = _read_holder(path)
        if holder is not None and holder.get("token") == token:
            with contextlib.suppress(FileNotFoundError):
                os.unlink(path)
    finally:
        with contextlib.suppress(FileNotFoundError):
            os.unlink(breaker)
    return None


__all__ = ["Lock", "LockError"]
