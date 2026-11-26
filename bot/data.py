"""Market data: Binance OHLCV via ccxt (paginated) or a local CSV."""

from __future__ import annotations

import time

import pandas as pd

COLS = ["timestamp", "open", "high", "low", "close", "volume"]


def to_frame(rows: list[list]) -> pd.DataFrame:
    df = pd.DataFrame(rows, columns=COLS)
    df["timestamp"] = pd.to_datetime(df["timestamp"], unit="ms", utc=True)
    df = df.drop_duplicates("timestamp").set_index("timestamp").sort_index()
    return df.astype(float)


def fetch_history(exchange, symbol: str, timeframe: str, days: int) -> pd.DataFrame:
    tf_ms = exchange.parse_timeframe(timeframe) * 1000
    since = exchange.milliseconds() - days * 86_400_000
    rows: list[list] = []
    while True:
        batch = exchange.fetch_ohlcv(symbol, timeframe, since=since, limit=1000)
        if not batch:
            break
        rows += batch
        since = batch[-1][0] + tf_ms
        if len(batch) < 1000 or since >= exchange.milliseconds():
            break
        time.sleep(exchange.rateLimit / 1000)
    df = to_frame(rows)
    return drop_open_candle(df, tf_ms, exchange.milliseconds())


def fetch_recent(exchange, symbol: str, timeframe: str, limit: int) -> pd.DataFrame:
    tf_ms = exchange.parse_timeframe(timeframe) * 1000
    df = to_frame(exchange.fetch_ohlcv(symbol, timeframe, limit=limit))
    return drop_open_candle(df, tf_ms, exchange.milliseconds())


def drop_open_candle(df: pd.DataFrame, tf_ms: int, now_ms: int) -> pd.DataFrame:
    """Remove the still-forming candle so signals only use closed bars."""
    if len(df) and df.index[-1].value // 1_000_000 + tf_ms > now_ms:
        return df.iloc[:-1]
    return df


def load_csv(path: str) -> pd.DataFrame:
    df = pd.read_csv(path)
    df.columns = [c.lower() for c in df.columns]
    missing = set(COLS) - set(df.columns)
    if missing:
        raise ValueError(f"CSV missing columns: {sorted(missing)}")
    ts = df["timestamp"]
    df["timestamp"] = (
        pd.to_datetime(ts, unit="ms", utc=True) if pd.api.types.is_numeric_dtype(ts) else pd.to_datetime(ts, utc=True)
    )
    df = df[COLS].dropna().drop_duplicates("timestamp", keep="last")
    df = df.set_index("timestamp").sort_index().astype(float)
    if df.empty:
        raise ValueError(f"{path}: no usable rows")
    return df
