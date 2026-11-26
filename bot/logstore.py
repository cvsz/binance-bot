"""Append-only JSON-lines log store.

Adapted from TradingAgents' `store/log.ts`. One JSON value per line, written
whole by a single write, never edited. A crash can leave a last line without
its newline; opening for append cuts that torn tail first, so the next line
does not join it; reading skips it. Any other line that is not JSON is damage
the store will not guess around.

Used as a crash-proof trade/event journal alongside SQLite in
:class:`bot.store.Store`.
"""

from __future__ import annotations

import contextlib
import json
import os
import stat
from pathlib import Path


class DamagedLogError(Exception):
    """Raised when a log line before the end is not valid JSON."""

    def __init__(self, path: str, line: int) -> None:
        self.path = path
        self.line = line
        super().__init__(f"damaged log line {line} in {path}")


def read_log(path: str | Path) -> list:
    """Every value in the file, in order.

    A torn last line (bytes after the last newline) is not read. Refuses a
    file with a broken line before its end.
    """
    text = Path(path).read_text(encoding="utf-8")
    end = text.rfind("\n") + 1
    values: list = []
    lines = text[:end].split("\n")
    lines.pop()  # drop the empty after the final newline
    for index, line in enumerate(lines):
        try:
            values.append(json.loads(line))
        except ValueError as err:
            raise DamagedLogError(str(path), index + 1) from err
    return values


def read_log_head(path: str | Path, bytes_limit: int = 8192) -> list:
    """The first values of a file, reading at most ``bytes_limit`` bytes.

    Enough to list a session without reading it all. Stops at the first
    unparseable line.
    """
    data = Path(path).read_bytes()[:bytes_limit]
    text = data.decode("utf-8", errors="replace")
    end = text.rfind("\n") + 1
    values: list = []
    for line in text[:end].split("\n"):
        if not line:
            continue
        try:
            values.append(json.loads(line))
        except ValueError:
            break
    return values


class LogWriter:
    """Append values to a JSON-lines log, one line per write."""

    def __init__(self, handle: int, path: str, repaired_bytes: int) -> None:
        self._handle = handle
        self._path = path
        self.repaired_bytes = repaired_bytes

    @classmethod
    async def open(cls, path: str | Path, header=None):  # pragma: no cover - async helper
        """Open ``path`` for appending, creating it private to the user.

        A new file starts with ``header``; an existing one is made private
        again and has a torn last line cut first. A symbolic link is refused.
        """
        path_str = str(path)
        parent = Path(path_str).parent
        parent.mkdir(parents=True, exist_ok=True)

        # Open without following a symlink.
        flags = os.O_RDWR | os.O_APPEND | os.O_NOFOLLOW
        try:
            fd = os.open(path_str, flags | os.O_CREAT | os.O_EXCL, 0o600)
            created = True
        except FileExistsError:
            fd = os.open(path_str, flags)
            created = False
        try:
            st = os.fstat(fd)
            if not stat.S_ISREG(st.st_mode):
                os.close(fd)
                raise ValueError(f"not a regular file: {path_str}")
            if hasattr(os, "chmod") and st.st_mode & 0o077:
                os.chmod(path_str, 0o600)
            if created:
                if header is not None:
                    os.write(fd, (json.dumps(header) + "\n").encode("utf-8"))
                return cls(fd, path_str, 0)
            repaired = cls._cut_torn_tail(fd)
            return cls(fd, path_str, repaired)
        except BaseException:
            with contextlib.suppress(OSError):
                os.close(fd)
            if created:
                with contextlib.suppress(FileNotFoundError):
                    os.unlink(path_str)
            raise

    @staticmethod
    def _cut_torn_tail(fd: int) -> int:
        """Cut everything after the last newline; returns bytes cut."""
        size = os.fstat(fd).st_size
        if size == 0:
            return 0
        block = 65_536
        end = size
        while end > 0:
            start = max(0, end - block)
            buf = os.pread(fd, end - start, start)
            newline = buf.rfind(b"\n")
            if newline >= 0:
                keep = start + newline + 1
                if keep < size:
                    os.ftruncate(fd, keep)
                return size - keep
            end = start
        os.ftruncate(fd, 0)
        return size

    async def append(self, *values: object) -> None:
        """Append values, one line each, in a single write."""
        if not values:
            return
        data = "".join(json.dumps(v) + "\n" for v in values).encode("utf-8")
        os.write(self._handle, data)

    async def sync(self) -> None:
        """Make what was appended durable."""
        os.fsync(self._handle)

    async def size(self) -> int:
        """The file's size in bytes."""
        return os.fstat(self._handle).st_size

    async def close(self) -> None:
        os.close(self._handle)


__all__ = ["DamagedLogError", "LogWriter", "read_log", "read_log_head"]
