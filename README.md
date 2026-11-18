# Binance Spot Trading Bot

บอทเทรด Binance Spot อัตโนมัติ (Python + ccxt) — ซื้อ/ขายตามกลยุทธ์ มี stop-loss บังคับ, จำกัดขาดทุนรายวัน, backtest ได้ และเริ่มต้นแบบไม่ใช้เงินจริงเสมอ

> ⚠️ **คำเตือน**: การเทรดคริปโตมีความเสี่ยงสูง บอทนี้ **ไม่รับประกันกำไร** ผล backtest ในอดีตไม่ได้บอกอนาคต
> เริ่มที่ `backtest` → `paper` → `live` (testnet) ก่อนจะคิดใช้เงินจริง และใช้เงินที่เสียได้เท่านั้น

## ทำอะไรได้บ้าง

| โหมด | ราคา | เงิน | คำสั่ง |
|---|---|---|---|
| **backtest** | ข้อมูลย้อนหลัง | จำลอง | `python run.py backtest --days 180` |
| **paper** | ราคาจริงแบบ real-time | จำลอง | `python run.py paper` |
| **live (testnet)** | Binance Testnet | เงินปลอมของ testnet | `python run.py live` |
| **live (เงินจริง)** | Binance | **เงินจริง** | `python run.py live --real-money` + ยืนยันใน `.env` |

- **กลยุทธ์**: `ema_cross` (ตามเทรนด์ EMA ตัดกัน + กรอง RSI) และ `rsi_reversion` (ซื้อตอน RSI ฟื้นจาก oversold ในขาขึ้น) — เพิ่มเองได้ใน `bot/strategies.py`
- **บริหารความเสี่ยง**: คำนวณขนาดไม้จาก % ความเสี่ยงต่อไม้, stop-loss บังคับ, take-profit, trailing stop, จำกัดเงินต่อไม้, หยุดเปิดไม้เมื่อขาดทุนรายวันเกินกำหนด, จำกัดจำนวนไม้ต่อวัน, cooldown, และ kill switch เมื่อพอร์ตลดจากจุดสูงสุดเกิน `max_drawdown_halt_pct` (ไม่บังคับ)
- **ไม่มี lookahead**: สัญญาณใช้เฉพาะแท่งเทียนที่ปิดแล้ว, backtest ส่งคำสั่งที่ราคาเปิดของแท่งถัดไป (เหมือนของจริง) และคิดค่าธรรมเนียม + slippage
- **ทนทาน**: บันทึกสถานะลง SQLite แบบ transaction เดียว (รีสตาร์ทแล้วทำต่อได้), retry เมื่อเน็ตหลุด, ลูปไม่ตายเมื่อเจอ error ที่ไม่คาดคิด, หยุดทันทีเมื่อ API key ใช้ไม่ได้, ปิดอย่างปลอดภัยเมื่อกด Ctrl+C
- **คำสั่งซื้อขายไม่หาย**: ทุกออเดอร์มี client order id ถ้าเน็ตหลุดหลังส่งออเดอร์ บอทจะค้นหาออเดอร์นั้นแทนการลืมไป ถ้ายืนยันสถานะไม่ได้จะ **หยุดเปิดไม้ใหม่** และแจ้งเตือนให้ตรวจบัญชี (รอบถัดไปพยายามคืนค่า sell ที่ fill จริงจาก client order id ก่อนขายซ้ำ)
- **รอ fill ให้ครบ**: ไม่ยืนยันออเดอร์จากยอดคงเหลือที่เปลี่ยนครั้งแรก (กัน partial fill ทำให้ขายไม่ครบหรือเหรียญค้างโดยไม่มี stop)
- **กันเหรียญไร้เจ้าของ**: ถ้าเจอเหรียญ base ในกระเป๋าโดยไม่มี position บันทึกอยู่ตอนเริ่มต้น จะหยุดเปิดไม้ใหม่และแจ้งเตือนให้ตรวจบัญชี
- **ไม่แตะเหรียญเดิมของคุณ**: บอทขายเฉพาะจำนวนที่ตัวเองซื้อ
- **แจ้งเตือน Telegram** (ไม่บังคับ)

## เอกสาร

คู่มือครบชุดอยู่ใน [docs/](docs/README.md): [สถาปัตยกรรม](docs/ARCHITECTURE.md) · [การตั้งค่า](docs/CONFIGURATION.md) · [ความเสี่ยง](docs/RISK.md) · [กลยุทธ์](docs/STRATEGIES.md) · [Runbook](docs/OPERATIONS.md) · [ความปลอดภัย](docs/SECURITY.md) · [คำสั่ง](docs/CLI.md) · [การพัฒนา](docs/DEVELOPMENT.md) · [แก้ปัญหา](docs/TROUBLESHOOTING.md) — ประวัติการเปลี่ยนแปลง: [CHANGELOG.md](CHANGELOG.md)

## เริ่มใช้งาน (Makefile)

```bash
make setup        # venv + deps + config.yaml/.env + permissions
make doctor       # ตรวจสภาพแวดล้อม
make ci           # lint + docs + secrets + tests
make backtest     # แล้ว make start / make dashboard
```

`make` เฉยๆ แสดงคำสั่งทั้งหมด — รายละเอียดใน [docs/CLI.md](docs/CLI.md)

## เริ่มใช้งาน (ด้วยมือ)

```bash
python -m venv .venv && source .venv/bin/activate     # Windows: .venv\Scripts\activate
pip install -r requirements.txt
cp config.example.yaml config.yaml
cp .env.example .env
```

### 1) Backtest
```bash
python run.py backtest --days 180
python run.py backtest --csv my_ohlcv.csv          # CSV: timestamp,open,high,low,close,volume
```
ผลลัพธ์: ผลตอบแทน, เทียบกับ buy & hold, max drawdown, win rate, profit factor, Sharpe และไฟล์ `reports/backtest_trades.csv`, `reports/backtest_equity.csv`

ลองปรับ `strategy`/`risk` ใน `config.yaml` แล้ว backtest หลายช่วงเวลา/หลายเหรียญ ถ้ากลยุทธ์แพ้ buy & hold หรือ drawdown สูง อย่าเพิ่งไปต่อ

### 2) Paper trading (ราคาจริง เงินจำลอง)
```bash
python run.py paper
python run.py status --mode paper     # ดูสถานะ/ไม้ล่าสุด
python run.py health --mode paper     # exit 0 ถ้าบอทยังส่ง heartbeat (ใช้กับ Docker/monitoring)
```
ปล่อยรันอย่างน้อย 1–2 สัปดาห์

### 3) Binance Testnet
1. สมัคร/ล็อกอินที่ https://testnet.binance.vision แล้วสร้าง API key
2. ใส่ `BINANCE_TESTNET_API_KEY` / `BINANCE_TESTNET_API_SECRET` ใน `.env`
3. `exchange.testnet: true` ใน `config.yaml` แล้ว `python run.py live`

### 4) เงินจริง (ทำเมื่อมั่นใจแล้วเท่านั้น)
1. สร้าง API key บน Binance: เปิด **Enable Spot & Margin Trading** เท่านั้น, **ปิด Withdrawals**, ตั้ง **IP whitelist**
2. ใส่ `BINANCE_API_KEY` / `BINANCE_API_SECRET` ใน `.env`
3. ตั้ง `exchange.testnet: false` และเพิ่ม `BOT_CONFIRM_REAL_MONEY=YES_I_ACCEPT_THE_RISK` ใน `.env`
4. `python run.py live --real-money`

ขาดข้อใดข้อหนึ่ง บอทจะไม่ยอมเริ่ม

## เมื่อบอทหยุดเปิดไม้ (HALTED)

บอทจะหยุดเปิดไม้ใหม่ (แต่ยังดูแล stop-loss ของไม้ที่เปิดอยู่) เมื่อ:
- ขาดทุนรายวันเกิน `max_daily_loss_pct` — ปลดเองอัตโนมัติวันถัดไป (UTC)
- พอร์ตลดจากจุดสูงสุดเกิน `max_drawdown_halt_pct` — **ต้องปลดเอง**
- ส่งออเดอร์แล้วยืนยันผลไม่ได้ (เช่นเน็ตหลุดนานๆ) — **ต้องตรวจบัญชีบน Binance ก่อนแล้วค่อยปลด**

```bash
python run.py resume --mode live      # ใช้ได้ทั้งตอนบอทรันอยู่และหยุดอยู่
```

ถ้าไม้มีขนาดเล็กกว่าขั้นต่ำของ Binance (dust) จนขายไม่ได้ บอทจะเลิกติดตามไม้นั้น (เหรียญยังอยู่ในกระเป๋า) และแจ้งเตือน แทนการพยายามขายซ้ำไม่รู้จบ

## Dashboard

```bash
python run.py dashboard              # เปิด http://localhost:8080
```
เปิดอีกหน้าต่างเทอร์มินัลแยกจากตัวบอท (บอทกับ dashboard เป็นคนละโปรเซส) แสดง:
- สถานะบอท ออนไลน์/ออฟไลน์ และแจ้งเมื่อหยุดเปิดไม้เพราะขาดทุนรายวันเกิน
- มูลค่าพอร์ต, % กำไรจากเริ่มต้น, ราคาล่าสุด, ยอดเหรียญ/USDT
- กำไรที่ปิดแล้ว, win rate, profit factor, ไม้ดีสุด/แย่สุด
- กราฟมูลค่าพอร์ต, ไม้ที่เปิดอยู่ (ราคาเข้า, SL, TP, กำไรที่ยังไม่ปิด)
- ประวัติเทรด 200 รายการล่าสุด และสลับโหมด paper / live-testnet / live ได้
- รีเฟรชอัตโนมัติทุก 10 วินาที รองรับมือถือและธีมมืด/สว่าง

**ดูได้อย่างเดียว** หน้านี้อ่านแค่ฐานข้อมูลของบอท ไม่มีทางส่งคำสั่งซื้อขาย
ถ้าจะเปิดให้เข้าจากเครื่องอื่น (`--host 0.0.0.0`) ต้องตั้ง `DASHBOARD_TOKEN` ใน `.env` แล้วเข้าด้วย `http://<ip>:8080/?token=<ค่า token>`
แนะนำให้เข้าผ่าน SSH tunnel หรือ Cloudflare Tunnel/Access แทนการเปิดพอร์ตสู่อินเทอร์เน็ตตรงๆ (dashboard ไม่มี HTTPS ในตัว)

> ในโหมด live มูลค่าพอร์ตนับรวมเหรียญ base และ USDT ทั้งหมดในบัญชี spot ไม่ใช่เฉพาะที่บอทซื้อ

## รันแบบ 24/7 ด้วย Docker
```bash
mkdir -p data                       # สร้างเองก่อน ไม่งั้น Docker สร้างเป็น root แล้วบอทเขียนไม่ได้
docker compose up -d --build        # บอท (paper) + dashboard ที่ http://localhost:8080/?token=<DASHBOARD_TOKEN>
docker compose ps                   # ดูสถานะ healthcheck
docker compose logs -f
```
เวอร์ชันแพ็กเกจที่ผ่านเทสถูกล็อกไว้ใน `constraints.txt` (Docker ใช้ไฟล์นี้)

## ข้อควรรู้
- **Long-only spot**: ซื้อแล้วขาย ไม่มี short/leverage/futures (ตั้งใจเพื่อความปลอดภัย)
- **Stop-loss/TP ทำงานฝั่งบอท** (บอทเช็คราคาทุก `poll_seconds`) ถ้าบอทดับ stop จะไม่ทำงาน — ควรรันบน VPS/Docker ที่ `restart: unless-stopped` และเปิดแจ้งเตือน Telegram
- จำกัดขาดทุนรายวันนับตามวัน **UTC** (07:00 เวลาไทย)
- ในโหมด live ขนาดไม้/ขาดทุนรายวัน/drawdown คำนวณจาก **ยอดทั้งบัญชี** (base + quote) ถ้ามีเหรียญเดิมอยู่ ราคาเหรียญเดิมจะมีผลด้วย — แนะนำใช้ sub-account แยกสำหรับบอท
- `.env` ควรเป็น `chmod 600` (อ่านได้เฉพาะเจ้าของ)
- ใช้ Binance global (binance.com) — **Binance TH** เป็นคนละระบบ/API ใช้กับบอทนี้ไม่ได้โดยตรง
- กำหนดค่าธรรมเนียม/slippage ใน `paper` ให้ใกล้ของจริง (Binance spot ปกติ 0.1%)

## โครงสร้าง
```
bot/indicators.py   EMA, RSI
bot/strategies.py   กลยุทธ์ (เพิ่มคลาสใหม่แล้วลงทะเบียนใน STRATEGIES)
bot/risk.py         ขนาดไม้, SL/TP/trailing, kill switch
bot/broker.py       PaperBroker / LiveBroker (ccxt)
bot/engine.py       ตรรกะเข้า-ออก ใช้ร่วมกันทุกโหมด
bot/backtest.py     backtester + สถิติ
bot/runner.py       ลูปรัน paper/live
bot/store.py        SQLite: บันทึกเทรด + สถานะ
bot/dashboard.py    web dashboard (stdlib, read-only) + dashboard.html
run.py              CLI
Makefile            คำสั่ง dev/ops (make เพื่อดูทั้งหมด)
docs/               เอกสารครบชุด
scripts/            ตรวจเอกสาร/ความลับ (make ci)
tests/              pytest (53 tests)
```

## ทดสอบ
```bash
pip install -r requirements-dev.txt -c constraints.txt
pytest -q
ruff check .
```
