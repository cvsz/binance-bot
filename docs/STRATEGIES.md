# กลยุทธ์และการ backtest

กลยุทธ์อยู่ใน `bot/strategies.py` แต่ละกลยุทธ์รับ DataFrame OHLCV แล้วคืนสัญญาณต่อแท่ง: `BUY = 1`, `SELL = -1`, `HOLD = 0`

กฎสำคัญ: สัญญาณที่แท่ง `i` ต้องคำนวณจากแท่ง `≤ i` เท่านั้น (ไม่มี lookahead) — มี test `test_no_lookahead` บังคับไว้ทุกกลยุทธ์

## กลยุทธ์ที่มี

### `ema_cross` — ตามเทรนด์

| พารามิเตอร์ | ค่าเริ่มต้น | กฎ |
|---|---|---|
| `fast` | 9 | `1 < fast < slow` |
| `slow` | 21 | |
| `rsi_period` | 14 | ≥ 2 |
| `rsi_max_entry` | 70 | (0, 100] |

- **BUY**: EMA(fast) ตัดขึ้นเหนือ EMA(slow) และ RSI < `rsi_max_entry` (กันไล่ราคาตอน overbought)
- **SELL**: EMA(fast) ตัดลงใต้ EMA(slow)
- Warmup: `slow × 3` แท่ง

### `rsi_reversion` — ซื้อตอนย่อในขาขึ้น

| พารามิเตอร์ | ค่าเริ่มต้น | กฎ |
|---|---|---|
| `rsi_period` | 14 | ≥ 2 |
| `oversold` | 30 | `0 < oversold < overbought < 100` |
| `overbought` | 70 | |
| `trend_ema` | 200 | ≥ 2 |

- **BUY**: RSI ฟื้นขึ้นจาก ≤ `oversold` มาเหนือ `oversold` และราคาปิด > EMA(`trend_ema`)
- **SELL**: RSI ≥ `overbought`
- Warmup: `max(trend_ema, rsi_period × 3)` แท่ง

> สัญญาณ SELL ปิดไม้ด้วยเหตุผล `signal` — นอกจากนี้ไม้ยังถูกปิดด้วย stop/TP/trailing ตาม [RISK.md](RISK.md) เสมอ

## การเพิ่มกลยุทธ์ใหม่

1. เขียนคลาสใน `bot/strategies.py`:

```python
class MacdTrend(Strategy):
    """Buy when MACD crosses above its signal line while price is above EMA(trend)."""

    name = "macd_trend"

    def __init__(self, fast: int = 12, slow: int = 26, signal: int = 9, trend: int = 200):
        if not 1 < fast < slow:
            raise ValueError("macd_trend requires 1 < fast < slow")
        self.fast, self.slow, self.signal_p, self.trend = fast, slow, signal, trend
        self.warmup = max(slow * 3, trend)

    def signals(self, df: pd.DataFrame) -> pd.Series:
        close = df["close"]
        macd = ema(close, self.fast) - ema(close, self.slow)
        sig_line = macd.ewm(span=self.signal_p, adjust=False).mean()
        above = (macd > sig_line) & sig_line.notna()
        prev = above.shift(1, fill_value=False)
        out = pd.Series(HOLD, index=df.index, dtype="int64")
        out[above & ~prev & (close > ema(close, self.trend))] = BUY
        out[~above & prev] = SELL
        out.iloc[: self.warmup] = HOLD
        return out
```

2. ลงทะเบียนใน registry: `STRATEGIES = {cls.name: cls for cls in (EmaCross, RsiReversion, MacdTrend)}`
3. เพิ่มกลยุทธ์ลงใน `@pytest.mark.parametrize` ของ `test_no_lookahead` ใน `tests/test_bot.py` และเขียน test validation ของพารามิเตอร์
4. `make check` แล้ว backtest ตามวิธีด้านล่าง

ข้อควรทำ:
- validate พารามิเตอร์ใน `__init__` และ raise `ValueError` พร้อมข้อความชัด
- ตั้ง `warmup` ให้พอให้ indicator นิ่ง และ set สัญญาณช่วง warmup เป็น `HOLD`
- ใช้ indicator แบบ causal (`ewm(adjust=False)`, `rolling`) — ห้าม `shift(-n)`, ห้าม `center=True`, ห้ามใช้สถิติทั้งชุดข้อมูล (เช่น normalize ด้วย mean ของทั้ง series)

## การ backtest

```bash
make backtest                         # 90 วันจาก Binance (ข้อมูลสาธารณะ ไม่ต้องใช้ key)
make backtest DAYS=365
make backtest CSV=my_ohlcv.csv        # คอลัมน์: timestamp,open,high,low,close,volume
make backtest VERBOSE=1               # log ทุกไม้

# ทางเลือก: ใช้ชุดข้อมูลสาธารณะ (ไม่ติด rate limit, มี checksum, ทำ walk-forward/OOS ง่าย)
make public-data SYMBOL=BTCUSDT INTERVAL=15m DAYS=365
make backtest CSV=reports/public_BTCUSDT_15m.csv
# หรือระบุช่วง: make public-data START=2024-01-01 END=2025-12-31
```

ผลลัพธ์ที่พิมพ์: `total_return_pct`, `buy_and_hold_pct`, `max_drawdown_pct`, `closed_trades`, `win_rate_pct`, `profit_factor`, `avg_trade_pnl`, `sharpe` (annualized ตามขนาดแท่ง), `exit_reasons` และไฟล์ `reports/backtest_trades.csv`, `reports/backtest_equity.csv`

CSV: `timestamp` เป็น epoch ms หรือข้อความวันที่ก็ได้; แถวที่ซ้ำ timestamp จะใช้แถวสุดท้าย, แถวที่มีค่าว่างถูกตัดทิ้ง

`make public-data` โหลดจาก [Binance Data Collection](https://data.binance.vision/) (daily/monthly klines ทุก symbol) ตรวจ SHA-256 ทุก zip และแปลง timestamp ไมโครวินาทีของ Spot ตั้งแต่ 2025-01-01 ให้เป็น ms ก่อนเขียน CSV (cache อยู่ใน `data/public-cache/`) — ข้อมูลมี [Dataset Terms](https://github.com/binance/binance-public-data/blob/master/TERMS_AND_CONDITIONS.md) ของ Binance ควรอ่านก่อนใช้เชิงพาณิชย์ สคริปต์นี้ **ไม่แตะ** ตรรกะ backtest/Engine

### โมเดลการจำลอง

- สัญญาณตอนปิดแท่ง → ส่งคำสั่งที่ **ราคาเปิดแท่งถัดไป**
- ค่าธรรมเนียม `paper.fee_pct` และ slippage `paper.slippage_pct` ทั้งขาเข้าและขาออก
- แท่งเดียวแตะทั้ง stop และ TP → ถือว่าโดน stop ก่อน
- ไม่จำลอง: ความลึกของ order book, การหยุดเทรดของตลาด, ความล่าช้าของ poll ในของจริง

### อ่านผลอย่างไรไม่ให้หลอกตัวเอง

1. **เทียบกับ buy & hold** — ในขาลงกลยุทธ์อาจ "ขาดทุนน้อยกว่า" แต่ยังขาดทุน; ดู `profit_factor` (> 1 = ได้มากกว่าเสีย) และ `avg_trade_pnl` (> 0)
2. **จำนวนไม้** — น้อยกว่า ~30 ไม้ สถิติยังไม่น่าเชื่อถือ
3. **หลายช่วงเวลา/หลายเหรียญ** — กลยุทธ์ที่ดีแค่ช่วงเดียวคือ overfit
4. **Walk-forward** — ปรับพารามิเตอร์บนข้อมูลช่วงแรก แล้ววัดผลบนช่วงหลังที่ไม่เคยเห็น ห้ามเลือกพารามิเตอร์จากผลบนช่วงทดสอบ
5. **ค่าธรรมเนียม** — timeframe เล็ก (1m/5m) เทรดบ่อย ค่าธรรมเนียม 0.2% ต่อรอบมักกินกำไรหมด

### ผลอ้างอิงล่าสุด

Backtest ค่าเริ่มต้น (`ema_cross` 9/21, BTC/USDT 15m) วันที่ 2026-11-18 ช่วง 30 วัน: ผลตอบแทน −6.06%, buy & hold −21.62%, win rate 14.3%, profit factor 0.2, 56 ไม้ — **ค่า expectancy ติดลบ** ยังไม่ควรใช้กับเงินจริงโดยไม่ปรับและทดสอบเพิ่ม
