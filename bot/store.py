"""SQLite persistence: trade journal + bot state (survives restarts)."""
from __future__ import annotations

import json
import sqlite3
from pathlib import Path


class Store:
    def __init__(self, path: str | Path = ":memory:"):
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
            CREATE TABLE IF NOT EXISTS state (k TEXT PRIMARY KEY, v TEXT);
            CREATE TABLE IF NOT EXISTS equity (ts TEXT PRIMARY KEY, equity REAL, price REAL);
            """
        )

    def log_trade(self, **row) -> None:
        cols = ",".join(row)
        self.db.execute(f"INSERT INTO trades ({cols}) VALUES ({','.join('?' * len(row))})", tuple(row.values()))
        self.db.commit()

    def trades(self) -> list[dict]:
        cur = self.db.execute("SELECT * FROM trades ORDER BY id")
        names = [d[0] for d in cur.description]
        return [dict(zip(names, r)) for r in cur.fetchall()]

    def get(self, key: str, default=None):
        row = self.db.execute("SELECT v FROM state WHERE k=?", (key,)).fetchone()
        return json.loads(row[0]) if row else default

    def put(self, key: str, value) -> None:
        self.db.execute("INSERT OR REPLACE INTO state (k, v) VALUES (?, ?)", (key, json.dumps(value)))
        self.db.commit()

    def log_equity(self, ts: str, equity: float, price: float) -> None:
        self.db.execute("INSERT OR REPLACE INTO equity (ts, equity, price) VALUES (?, ?, ?)", (ts, equity, price))
        self.db.commit()

    def equity_series(self, limit: int = 2000) -> list[dict]:
        rows = self.db.execute(
            "SELECT ts, equity, price FROM (SELECT * FROM equity ORDER BY ts DESC LIMIT ?) ORDER BY ts", (limit,)
        ).fetchall()
        return [{"ts": t, "equity": e, "price": p} for t, e, p in rows]
