"""Offline tests for the Binance public-data downloader/converter."""
import hashlib
import io
import zipfile
from datetime import date

import pytest

from bot.data import load_csv
from scripts.fetch_public_data import (
    build_url,
    month_plan,
    normalize_timestamp,
    parse_kline,
    rows_from_zip,
    verify_checksum,
    write_csv,
)


def make_zip(csv_text: str) -> bytes:
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w") as archive:
        archive.writestr("BTCUSDT-15m-2025-01-01.csv", csv_text)
    return buffer.getvalue()


def test_normalize_timestamp():
    assert normalize_timestamp("1735689600000") == 1735689600000       # ms
    assert normalize_timestamp("1735689600000866") == 1735689600000    # us (spot since 2025)


def test_parse_kline():
    row = parse_kline("1735689600000,4.1,4.2,4.0,4.15,10,0,0,0,0,0,0")
    assert row == [1735689600000, 4.1, 4.2, 4.0, 4.15, 10.0]
    with pytest.raises(ValueError, match="malformed"):
        parse_kline("1,2,3")


def test_rows_from_zip_write_csv_and_load(tmp_path):
    data = make_zip(
        "1735689600000,1,2,0.5,1.5,10,0,0,0,0,0,0\n"
        "1735689600000,1,2,0.5,1.6,10,0,0,0,0,0,0\n"
    )
    rows = rows_from_zip(data)
    assert len(rows) == 2
    out = tmp_path / "k.csv"
    assert write_csv(rows, out) == 1  # deduped, last value kept
    frame = load_csv(out)
    assert len(frame) == 1 and frame["close"].iloc[0] == pytest.approx(1.6)


def test_microsecond_rows_load_to_correct_date(tmp_path):
    data = make_zip("1735689600000866,1,2,0.5,1.5,10,0,0,0,0,0,0\n")
    out = tmp_path / "k.csv"
    write_csv(rows_from_zip(data), out)
    frame = load_csv(out)
    assert frame.index[0].year == 2025


def test_verify_checksum():
    data = b"kline-archive"
    verify_checksum(data, f"{hashlib.sha256(data).hexdigest()}  file.zip\n")
    with pytest.raises(ValueError, match="checksum mismatch"):
        verify_checksum(data, "0" * 64 + "  file.zip")


def test_month_plan_uses_monthly_only_for_complete_months():
    plan = month_plan(date(2025, 1, 20), date(2025, 3, 5), date(2025, 3, 20))
    assert [entry[4] for entry in plan] == [True, True, False]
    assert plan[2][2] == date(2025, 3, 1) and plan[2][3] == date(2025, 3, 5)


def test_build_url():
    assert build_url("monthly", "2025-01", "BTCUSDT", "15m").endswith(
        "/spot/monthly/klines/BTCUSDT/15m/BTCUSDT-15m-2025-01.zip")
