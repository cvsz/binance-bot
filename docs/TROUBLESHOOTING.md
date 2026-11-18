# แก้ปัญหา

เริ่มจาก `make doctor` และดู log (`make logs MODE=…` หรือ `make dlogs`) ก่อนเสมอ

## เริ่มบอทไม่ได้

| อาการ | สาเหตุ | วิธีแก้ |
|---|---|---|
| `config error: config.yaml not found` | ยังไม่ได้สร้าง config | `make config` |
| `config error: unknown risk settings: […]` / `unknown config keys` / `unknown <section> settings` | สะกดชื่อ key ผิด (ทุก section ตรวจ) | แก้ตามรายชื่อที่แสดงใน error |
| `config error: … must be true or false` | `testnet` เป็น string เช่น `"false"` (or `'yes'`) | ใช้ `true` / `false` แบบไม่ใส่เครื่องหมายคำพูด |
| `config error: db_path must not contain '..'` | พยายามชี้ DB ออกนอกโปรเจกต์ | ใช้ path สัมพัทธ์ในโปรเจกต์ |
| `config error: timeframe must look like …` | timeframe ผิดรูปแบบ | ใช้ `1m 5m 15m 1h 4h 1d` |
| `invalid params for strategy 'ema_cross'` | ชื่อพารามิเตอร์ใน `strategy.params` ผิด | ดู [STRATEGIES.md](STRATEGIES.md) |
| `refusing to start live trading: live mode needs BINANCE_TESTNET_API_KEY/SECRET` | ไม่มี key ใน `.env` | ใส่ key แล้ว `make doctor` |
| `exchange.testnet is false: add --real-money` / `set BOT_CONFIRM_REAL_MONEY=…` | ประตูเงินจริงยังไม่ครบ | ตั้งใจใช้เงินจริงจริงหรือไม่? ดู [SECURITY.md](SECURITY.md#real-money-gates) |
| `refusing to start dashboard: binding to a non-local address requires DASHBOARD_TOKEN` | `HOST=0.0.0.0` โดยไม่มี token | ตั้ง `DASHBOARD_TOKEN` หรือใช้ `127.0.0.1` + SSH tunnel |
| `make start` → `bot exited immediately` | error ตอนเริ่ม | ดู 20 บรรทัดที่แสดง หรือ `tail logs/<mode>.log` |
| `… already running (make attach / make stop)` | มี tmux session อยู่แล้ว | `make stop` ก่อน หรือ `make attach` |
| `ModuleNotFoundError: ccxt` | ไม่ได้ใช้ venv | ใช้ `make …` หรือ `.venv/bin/python run.py …` |

## ระหว่างรัน

| อาการ / ข้อความ | สาเหตุ | วิธีแก้ |
|---|---|---|
| `network error, retry in Ns` | เน็ต/Binance ช้า | ปกติ บอท backoff เอง (สูงสุด 10 นาที) ถ้าเกิดตลอดให้เพิ่ม `poll_seconds` |
| `network error, retry in Ns` พร้อม `rate_limited` | โดน rate limit | บอทอ่าน `retry-after` จาก exchange ถ้ามี; ถ้าเจอบ่อยให้เพิ่ม `poll_seconds` หรือลดจำนวนคู่เทรด |
| `exchange error (rejected): …` | exchange ปฏิเสธคำสั่ง (เช่น insufficient funds) | แก้เงิน/พารามิเตอร์; บอทไม่เพิ่ม backoff แต่ยังเช็ค stop ตามปกติ |
| `Timestamp for this request was 1000ms ahead` / `-1021` | นาฬิกาเครื่องเพี้ยน (พบบ่อยใน WSL หลัง sleep) | บอทเปิด `adjustForTimeDifference` แล้ว; ถ้ายังเกิด: `sudo hwclock -s` หรือ `wsl --shutdown` แล้วเปิดใหม่ |
| `⛔ STOPPED - fatal error: … Invalid API-key, IP, or permissions` (exit 3) | key ผิด, ไม่ได้เปิด Spot Trading, IP ไม่อยู่ใน whitelist | แก้ที่ Binance API Management/`.env` แล้วเริ่มใหม่ |
| `entry skipped: size X below minimum order` | พอร์ตเล็กเกินไปสำหรับขั้นต่ำ 5 USDT ตาม sizing | เพิ่มเงิน หรือเพิ่ม `risk_per_trade_pct`/`max_position_pct` อย่างระวัง |
| `entry skipped: daily loss …` / `max drawdown …` | kill switch ทำงาน | ดู [RISK.md](RISK.md) — daily ปลดเองวันถัดไป, drawdown ต้อง `make resume` |
| `entry skipped: cooldown` / `max trades per day reached` | ข้อจำกัดตาม config | ปกติ |
| `⛔ HALTED … order state unknown` | ส่งออเดอร์แล้วยืนยันผลไม่ได้ | ทำตาม [OPERATIONS.md](OPERATIONS.md) หัวข้อเหตุการณ์ฉุกเฉิน แล้ว `make resume` |
| `⛔ HALTED … untracked … in wallet (no position/stop)` | มีเหรียญ base ค้างในกระเป๋าแต่ไม่มี position (ซื้อแล้ว fill แต่สถานะไม่เซฟ / crash) | ตรวจบน Binance ว่าจะขายหรือติดตามไม้เอง แล้ว `make resume MODE=…` |
| `position … dropped (dust)` | ไม้เล็กกว่าขั้นต่ำ ขายไม่ได้ | เหรียญค้างในกระเป๋า แปลงเป็น BNB บน Binance ได้ |
| `position … dropped (missing)` / `missing from wallet; cleared` | ขายด้วยมือ/โอนออก/เหรียญถูกล็อกใน open order | ตรวจกระเป๋า; ยกเลิก open order ที่ล็อกเหรียญถ้าไม่ได้ตั้งใจ |
| `not enough candles yet` | คู่เทรดใหม่หรือ testnet มีข้อมูลน้อยกว่า warmup | ลด warmup (เช่น `trend_ema`) หรือใช้คู่อื่น |
| `⚠️ SELL FAILED …` ซ้ำๆ | Binance ปฏิเสธคำสั่งขาย | อ่านข้อความ error; ข้อความซ้ำถูกส่ง Telegram ทุก 15 นาทีเท่านั้นแต่ log ทุกครั้ง |

## Dashboard

| อาการ | วิธีแก้ |
|---|---|
| สถานะ `offline` | ยังไม่เคยรันบอทในโหมดนั้น หรือ DB อยู่คนละ `db_path` — เลือกโหมดใน dropdown ให้ถูก |
| สถานะ `stale` | บอทหยุด/ค้าง — `make health`, `make ps`, ดู log |
| `unauthorized` | ใส่ `?token=<DASHBOARD_TOKEN>` ใน URL |
| `no data for mode …` | ยังไม่มี DB ของโหมดนั้น |
| เปิดจาก Windows ไม่ได้ | WSL2 มักส่งต่อ localhost ให้เอง; ถ้าไม่ได้ใช้ `ssh -N -L 8080:127.0.0.1:8080 -p 2223 cvsz@<host>` |
| มูลค่าพอร์ตใน live ไม่ตรงกับที่บอทลงทุน | ปกติ — นับเหรียญ base + quote ทั้งบัญชี |

## Docker

| อาการ | วิธีแก้ |
|---|---|
| `sqlite3.OperationalError: unable to open database file` | `./data` ถูก Docker สร้างเป็น root — `sudo chown -R 1000:1000 data` หรือใช้ `make up` (สร้าง `data/` ให้ก่อน) |
| container `unhealthy` | `make dlogs`; bot healthcheck ต้องตรงโหมดที่รัน (`MODE` ของ `make up`) |
| container รีสตาร์ทวนซ้ำ (exit 2) | ประตู live ไม่ผ่าน/config ผิด — ดู log |

## Backtest

| อาการ | วิธีแก้ |
|---|---|
| `need more than N candles` | เพิ่ม `DAYS` หรือใช้ timeframe เล็กลง |
| `CSV missing columns` | ต้องมี `timestamp,open,high,low,close,volume` |
| ผลต่างจาก paper มาก | backtest ไม่จำลอง order book/latency; ตรวจ `fee_pct`/`slippage_pct` ให้ใกล้ของจริง |

## Tests

| อาการ | วิธีแก้ |
|---|---|
| `No module named pytest` | `make install` (หรือ `make reinstall`) |
| `make install` บอก `venv ready` แต่ไม่ติดตั้งอะไร | ปกติ — deps ตรงกับ requirements แล้ว; บังคับด้วย `make reinstall` |
| `make ci` fail ที่ `docs-check` | แก้ลิงก์ที่แสดงเป็น `BROKEN` |
| `make ci` fail ที่ `secrets-check` | ทำตามข้อความ (`make perms`, `git rm --cached <file>`) — อย่า commit ความลับ |
| test ช้า | ใช้ `make test-fast` ระหว่างพัฒนา |
