"""SQLite persistence: trade journal + bot state (survives restarts)."""

from __future__ import annotations

import json
import sqlite3
import threading
from pathlib import Path

TRADE_COLS = ("ts", "mode", "symbol", "side", "qty", "price", "quote", "reason", "pnl_quote", "order_id")


class Store:
    """Trade journal and key/value state.

    read_only=True opens an existing database without ever writing to it (used by the
    dashboard); write methods then raise sqlite3.OperationalError.
    """

    def __init__(self, path: str | Path = ":memory:", read_only: bool = False):
        self._lock = threading.RLock()
        self.read_only = read_only
        if read_only:
            p = Path(path).resolve()
            if not p.exists():
                raise FileNotFoundError(p)
            self.db = sqlite3.connect(p.as_uri() + "?mode=ro", uri=True, check_same_thread=False, timeout=10)
            return
        if path != ":memory:":
            Path(path).parent.mkdir(parents=True, exist_ok=True)
        self.db = sqlite3.connect(str(path), check_same_thread=False, timeout=10)
        if path != ":memory:":
            self.db.execute("PRAGMA journal_mode=WAL")  # dashboard can read while the bot writes
        self.db.executescript(
            """
            CREATE TABLE IF NOT EXISTS trades (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                ts TEXT, mode TEXT, symbol TEXT, side TEXT, qty REAL, price REAL,
                quote REAL, reason TEXT, pnl_quote REAL, order_id TEXT
            );
            CREATE INDEX IF NOT EXISTS idx_trades_ts ON trades(ts);
            CREATE TABLE IF NOT EXISTS state (k TEXT PRIMARY KEY, v TEXT);
            CREATE TABLE IF NOT EXISTS equity (ts TEXT PRIMARY KEY, equity REAL, price REAL);
            """
        )

    def log_trade(self, **row) -> None:
        unknown = set(row) - set(TRADE_COLS)
        if unknown:
            raise ValueError(f"unknown trade columns: {sorted(unknown)}")
        cols = [c for c in TRADE_COLS if c in row]
        sql = f"INSERT INTO trades ({','.join(cols)}) VALUES ({','.join('?' * len(cols))})"  # noqa: S608 - whitelisted
        with self._lock, self.db:
            self.db.execute(sql, tuple(row[c] for c in cols))

    def trades(self, limit: int | None = None) -> list[dict]:
        with self._lock:
            if limit:
                cur = self.db.execute(
                    "SELECT * FROM (SELECT * FROM trades ORDER BY id DESC LIMIT ?) ORDER BY id", (limit,)
                )
            else:
                cur = self.db.execute("SELECT * FROM trades ORDER BY id")
            names = [d[0] for d in cur.description]
            return [dict(zip(names, r, strict=True)) for r in cur.fetchall()]

    def get(self, key: str, default=None):
        with self._lock:
            row = self.db.execute("SELECT v FROM state WHERE k=?", (key,)).fetchone()
        return json.loads(row[0]) if row else default

    def put(self, key: str, value) -> None:
        self.put_many({key: value})

    def put_many(self, items: dict) -> None:
        """Write several keys in ONE transaction (all or nothing)."""
        with self._lock, self.db:
            self.db.executemany(
                "INSERT OR REPLACE INTO state (k, v) VALUES (?, ?)", [(k, json.dumps(v)) for k, v in items.items()]
            )

    def delete(self, key: str) -> None:
        with self._lock, self.db:
            self.db.execute("DELETE FROM state WHERE k=?", (key,))

    def log_equity(self, ts: str, equity: float, price: float) -> None:
        with self._lock, self.db:
            self.db.execute("INSERT OR REPLACE INTO equity (ts, equity, price) VALUES (?, ?, ?)", (ts, equity, price))

    def equity_series(self, limit: int = 2000) -> list[dict]:
        with self._lock:
            rows = self.db.execute(
                "SELECT ts, equity, price FROM (SELECT * FROM equity ORDER BY ts DESC LIMIT ?) ORDER BY ts",
                (limit,),
            ).fetchall()
        return [{"ts": t, "equity": e, "price": p} for t, e, p in rows]
