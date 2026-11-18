# การตั้งค่า

บอทใช้ 2 แหล่ง:

| ไฟล์ | เก็บอะไร | Git |
|---|---|---|
| `config.yaml` | พฤติกรรมการเทรด (ไม่มีความลับ) | ไม่ commit (คัดลอกจาก `config.example.yaml`) |
| `.env` | API key, token (ความลับ) | ไม่ commit (คัดลอกจาก `.env.example`, ต้อง `chmod 600`) |

สร้างทั้งสองไฟล์: `make config` (ไม่เขียนทับไฟล์ที่มีอยู่) — ใช้ไฟล์ config อื่นด้วย `python run.py -c other.yaml …` หรือ `make … CONFIG=other.yaml`

ค่าที่ผิดจะถูกปฏิเสธตอนเริ่มพร้อมข้อความชัดเจน (`config error: …`, exit code 2 รวมกรณี type ผิด) — ตรวจได้ด้วย `make doctor` **ชื่อ key ที่สะกดผิดทุก section (รวมระดับบน) ถูกปฏิเสธ** ไม่มีการเงียบไว้

## `config.yaml`

### ระดับบน

| Key | ค่าเริ่มต้น | กฎ | ความหมาย |
|---|---|---|---|
| `symbol` | `BTC/USDT` | รูปแบบ `BASE/QUOTE` ตัวพิมพ์ใหญ่ (แปลงให้อัตโนมัติ) | คู่เทรด spot |
| `timeframe` | `15m` | ตัวเลข + `s m h d w M` เช่น `1m 5m 15m 1h 4h 1d` | ขนาดแท่งเทียน |
| `db_path` | `data/bot.db` | ห้ามมี `..` | ฐานของชื่อไฟล์ DB (เติม `.paper` / `.live.testnet` / `.live` ให้อัตโนมัติ) |

### `exchange`

| Key | ค่าเริ่มต้น | ความหมาย |
|---|---|---|
| `testnet` | `true` | เฉพาะ `true` / `false` (หรือ YAML boolean) — `bool("false")` ไม่ถูกแปลงเป็น false · `true` = Binance Spot Testnet (เงินปลอม) · `false` = เงินจริง (ต้องผ่านประตูความปลอดภัยเพิ่ม ดู [SECURITY.md](SECURITY.md#real-money-gates)) |

### `strategy`

| Key | ความหมาย |
|---|---|
| `name` | `ema_cross` หรือ `rsi_reversion` |
| `params` | พารามิเตอร์ของกลยุทธ์ (ชื่อผิด → `invalid params for strategy`) — รายละเอียดใน [STRATEGIES.md](STRATEGIES.md) |

### `risk`

รายละเอียดการทำงานอยู่ใน [RISK.md](RISK.md) — ชื่อ key ที่สะกดผิดจะถูกปฏิเสธ (`unknown risk settings`)

| Key | ค่าเริ่มต้น | กฎ | ความหมาย |
|---|---|---|---|
| `risk_per_trade_pct` | `1.0` | (0, 5] | % ของพอร์ตที่ยอมเสียถ้าโดน stop |
| `stop_loss_pct` | `2.0` | (0, 100) | ระยะ stop จากราคาเข้า (บังคับมีเสมอ) |
| `take_profit_pct` | `4.0` | > 0 หรือ `null` | ระยะ TP (`null` = ไม่ใช้) |
| `trailing_stop_pct` | `null` | (0, 100) หรือ `null` | ระยะ trailing จากราคาสูงสุดหลังเข้า |
| `max_position_pct` | `25` | (0, 100] | เพดานเงินต่อไม้ (% ของพอร์ต) |
| `max_daily_loss_pct` | `3.0` | (0, 100] | ขาดทุนรายวัน (UTC) เกินนี้ → หยุดเปิดไม้ถึงวันถัดไป |
| `max_trades_per_day` | `10` | ≥ 1 | จำนวนไม้ใหม่สูงสุดต่อวัน (UTC) |
| `cooldown_bars` | `2` | ≥ 0 | จำนวนแท่งที่รอหลังปิดไม้ก่อนเข้าใหม่ |
| `max_drawdown_halt_pct` | `null` | (0, 100] หรือ `null` | พอร์ตลดจากจุดสูงสุดเกินนี้ → หยุดเปิดไม้จนกว่าจะ `resume` |

### `paper`

ใช้กับ **backtest และ paper** (live ใช้ยอดจริงในบัญชี)

| Key | ค่าเริ่มต้น | กฎ | ความหมาย |
|---|---|---|---|
| `starting_quote` | `1000` | > 0 | เงินเริ่มต้น (สกุล quote เช่น USDT) |
| `fee_pct` | `0.1` | [0, 5) | ค่าธรรมเนียมต่อฝั่ง (Binance spot ปกติ 0.1%) |
| `slippage_pct` | `0.05` | [0, 5) | ราคาที่แย่ลงต่อฝั่ง |

### `loop`

| Key | ค่าเริ่มต้น | กฎ | ความหมาย |
|---|---|---|---|
| `poll_seconds` | `30` | ≥ 5 | ความถี่เช็คราคา/stop (ต่ำเกินไปเสี่ยงโดน rate limit) |

### ตัวอย่าง: rsi_reversion บน 1h พร้อม trailing และ drawdown kill switch

```yaml
symbol: ETH/USDT
timeframe: 1h
exchange:
  testnet: true
strategy:
  name: rsi_reversion
  params: {rsi_period: 14, oversold: 30, overbought: 70, trend_ema: 200}
risk:
  risk_per_trade_pct: 0.5
  stop_loss_pct: 3.0
  take_profit_pct: null
  trailing_stop_pct: 2.0
  max_position_pct: 20
  max_daily_loss_pct: 2.0
  max_trades_per_day: 5
  cooldown_bars: 1
  max_drawdown_halt_pct: 10
paper: {starting_quote: 1000, fee_pct: 0.1, slippage_pct: 0.05}
loop: {poll_seconds: 30}
db_path: data/eth.db
```

> รันหลายเหรียญพร้อมกัน: ใช้ config แยกไฟล์และ `db_path` คนละชื่อ เช่น `make start MODE=paper CONFIG=eth.yaml SESSION=binance-bot-eth`

## `.env`

| ตัวแปร | ใช้เมื่อ | หมายเหตุ |
|---|---|---|
| `BINANCE_TESTNET_API_KEY` / `BINANCE_TESTNET_API_SECRET` | `live` + `testnet: true` | สร้างที่ https://testnet.binance.vision |
| `BINANCE_API_KEY` / `BINANCE_API_SECRET` | `live` + `testnet: false` | เปิดเฉพาะ Spot Trading, ปิด Withdrawals, ผูก IP whitelist |
| `BOT_CONFIRM_REAL_MONEY` | เงินจริง | ต้องเป็น `YES_I_ACCEPT_THE_RISK` ทุกตัวอักษร |
| `TELEGRAM_BOT_TOKEN` / `TELEGRAM_CHAT_ID` | ไม่บังคับ | เปิดการแจ้งเตือน (ต้องมีทั้งคู่) |
| `DASHBOARD_TOKEN` | dashboard ที่ bind นอก localhost | ใช้ค่าสุ่มยาว เช่น `python -c "import secrets;print(secrets.token_urlsafe(32))"` |

ตัวแปรใน environment จริงมีผลเหนือกว่าค่าใน `.env` (พฤติกรรมของ `python-dotenv`)

## ตรวจ config

```bash
make doctor     # config ถูกต้องไหม, .env permission, key ไหนตั้งแล้ว (ไม่แสดงค่า)
```
