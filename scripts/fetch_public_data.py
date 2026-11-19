#!/usr/bin/env python3
"""Download Binance public klines from data.binance.vision and write a backtest CSV.

The output has exactly the columns `bot.data.load_csv` expects, with timestamps in
milliseconds. Spot klines from 2025-01-01 use microseconds upstream, so they are
converted here. Every archive is verified against its published SHA-256 checksum.

No network is used on import — the conversion helpers are importable by tests.
"""
from __future__ import annotations

import argparse
import calendar
import hashlib
import io
import sys
import urllib.error
import urllib.request
import zipfile
from datetime import date, timedelta
from pathlib import Path

BASE_URL = "https://data.binance.vision/data/spot"
COLUMNS = ("timestamp", "open", "high", "low", "close", "volume")
USER_AGENT = "binance-bot-public-data/1.0"
MICROSECOND_THRESHOLD = 10**14  # ms ~1.7e12, us ~1.7e15


def normalize_timestamp(raw: int | str) -> int:
    """Return milliseconds, converting upstream microsecond timestamps."""
    value = int(raw)
    return value // 1000 if value >= MICROSECOND_THRESHOLD else value


def parse_kline(line: str) -> list:
    """Convert one upstream kline row to the 6 columns our CSV needs."""
    parts = line.strip().split(",")
    if len(parts) < 6:
        raise ValueError(f"malformed kline row: {line!r}")
    try:
        return [
            normalize_timestamp(parts[0]),
            float(parts[1]), float(parts[2]), float(parts[3]), float(parts[4]), float(parts[5]),
        ]
    except ValueError as exc:
        raise ValueError(f"malformed kline row: {line!r}") from exc


def rows_from_zip(data: bytes) -> list[list]:
    """Parse all CSV files inside a downloaded klines zip."""
    with zipfile.ZipFile(io.BytesIO(data)) as archive:
        names = [name for name in archive.namelist() if name.lower().endswith(".csv")]
        if not names:
            raise ValueError("archive contains no CSV file")
        rows: list[list] = []
        for name in names:
            text = archive.read(name).decode("utf-8")
            rows.extend(parse_kline(line) for line in text.splitlines() if line.strip())
    return rows


def verify_checksum(data: bytes, checksum_text: str) -> None:
    """Check the SHA-256 from the published `.CHECKSUM` file (never prints data)."""
    fields = checksum_text.split()
    if not fields:
        raise ValueError("empty checksum file")
    expected, actual = fields[0].strip().lower(), hashlib.sha256(data).hexdigest()
    if expected != actual:
        raise ValueError(f"checksum mismatch: expected {expected}, computed {actual}")


def write_csv(rows: list[list], path: Path) -> int:
    """Dedupe by timestamp (keep last), sort, and write a load_csv-compatible CSV."""
    by_timestamp = {row[0]: row for row in rows}
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="") as handle:
        handle.write(",".join(COLUMNS) + "\n")
        for row in sorted(by_timestamp.values()):
            handle.write(",".join(str(value) for value in row) + "\n")
    return len(by_timestamp)


def month_plan(start: date, end: date, today: date) -> list[tuple[int, int, date, date, bool]]:
    """Per-month (year, month, first, last, try_monthly) for the requested range."""
    plan = []
    year, month = start.year, start.month
    while date(year, month, 1) <= end:
        first = max(start, date(year, month, 1))
        last = min(end, date(year, month, calendar.monthrange(year, month)[1]))
        month_ended = date(year, month, calendar.monthrange(year, month)[1]) < today
        plan.append((year, month, first, last, month_ended))
        year, month = (year + 1, 1) if month == 12 else (year, month + 1)
    return plan


def build_url(kind: str, period: str, symbol: str, interval: str, base: str = BASE_URL) -> str:
    return f"{base}/{kind}/klines/{symbol}/{interval}/{symbol}-{interval}-{period}.zip"


def _fetch(url: str) -> bytes:
    request = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})  # noqa: S310 - https only
    with urllib.request.urlopen(request, timeout=60) as response:  # noqa: S310 - fixed https URL
        return response.read()


def download_verified(url: str, cache: Path) -> bytes:
    """Fetch a zip (cached locally) and verify it against its .CHECKSUM."""
    cache.mkdir(parents=True, exist_ok=True)
    cached = cache / url.rsplit("/", 1)[-1]
    data = cached.read_bytes() if cached.exists() else _fetch(url)
    verify_checksum(data, _fetch(url + ".CHECKSUM").decode("utf-8"))
    if not cached.exists():
        cached.write_bytes(data)
    return data


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--symbol", default="BTCUSDT")
    parser.add_argument("--interval", default="15m")
    parser.add_argument("--days", type=int, default=180)
    parser.add_argument("--start", help="YYYY-MM-DD (overrides --days)")
    parser.add_argument("--end", help="YYYY-MM-DD (default: yesterday UTC)")
    parser.add_argument("--out", default="reports/public_klines.csv")
    parser.add_argument("--cache", default="data/public-cache")
    parser.add_argument("--base-url", default=BASE_URL, help=argparse.SUPPRESS)
    args = parser.parse_args(argv)

    today = date.today()
    end = date.fromisoformat(args.end) if args.end else today - timedelta(days=1)
    start = date.fromisoformat(args.start) if args.start else end - timedelta(days=args.days - 1)
    if start > end:
        parser.error("start must not be after end")

    rows: list[list] = []
    for year, month, first, last, try_monthly in month_plan(start, end, today):
        if try_monthly:
            url = build_url("monthly", f"{year:04d}-{month:02d}", args.symbol, args.interval, args.base_url)
            try:
                rows.extend(rows_from_zip(download_verified(url, Path(args.cache))))
                continue
            except urllib.error.HTTPError as exc:
                if exc.code != 404:
                    raise
        for day in _days(first, last):
            url = build_url("daily", day.isoformat(), args.symbol, args.interval, args.base_url)
            rows.extend(rows_from_zip(download_verified(url, Path(args.cache))))

    count = write_csv(rows, Path(args.out))
    if not count:
        print("no klines found for the requested range", file=sys.stderr)
        return 1
    first_ms, last_ms = min(row[0] for row in rows), max(row[0] for row in rows)
    print(f"{args.symbol} {args.interval}: {count} candles -> {args.out} "
          f"({first_ms} .. {last_ms} ms)")
    return 0


def _days(first: date, last: date):
    while first <= last:
        yield first
        first += timedelta(days=1)


if __name__ == "__main__":
    raise SystemExit(main())
