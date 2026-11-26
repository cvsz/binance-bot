# คู่มือการรันและดูแลระบบ (Runbook)

## เส้นทางสู่เงินจริง

```mermaid
flowchart LR
    A[backtest\nหลายช่วง/หลายเหรียญ] --> B[paper\n≥ 1–2 สัปดาห์] --> C[testnet\n≥ 1 สัปดาห์] --> D[เงินจริง\nจำนวนน้อย]
```

ข้ามขั้นไม่ได้ — ถ้าขั้นไหนผลแย่หรือมี error ให้ย้อนกลับไปแก้ก่อน (checklist ใน [RISK.md](RISK.md#pre-live-checklist))

## ติดตั้งครั้งแรก

```bash
cd ~/binance-bot
make setup        # .venv + deps (ล็อกเวอร์ชันด้วย constraints.txt) + config.yaml/.env + permissions
make doctor       # ตรวจสภาพแวดล้อม
make check        # lint + tests ต้องผ่าน
```

## วิธีรัน

| วิธี | คำสั่ง | เหมาะกับ |
|---|---|---|
| Foreground | `make paper` / `make live` | ทดลอง ดู log สด (Ctrl+C หยุด) |
| เบื้องหลังด้วย tmux | `make start MODE=paper` | WSL/เครื่องส่วนตัว — ไม่ตายเมื่อปิด SSH |
| Docker Compose | `make up` | 24/7 บน VPS — รีสตาร์ทอัตโนมัติ + healthcheck |

### tmux (`make start`)

```bash
make start MODE=paper        # เริ่ม session binance-bot-paper, log → logs/paper.log
make ps                      # session ที่รันอยู่
make logs MODE=paper         # tail log
make attach MODE=paper       # เข้า session (ออก: Ctrl+B แล้ว D)
make health MODE=paper       # exit 0 = heartbeat ปกติ
make stop MODE=paper         # ส่ง Ctrl+C → บอทบันทึกสถานะแล้วปิด (รอสูงสุด 30 วินาที)
make restart MODE=paper
```

- `make start` ไม่ยอมเริ่มซ้ำถ้า session ยังอยู่ และไม่รองรับเงินจริง (ใช้ `make live-real` แบบ foreground หรือ Docker)
- tmux ไม่รอดการรีบูตเครื่อง/`wsl --shutdown` — หลังรีบูตต้อง `make start` ใหม่ (สถานะเดิมใน DB ยังอยู่)

### Docker Compose (`make up`)

```bash
make up                  # สร้าง data/ ให้ แล้ว build + up bot (paper) + dashboard
make up MODE=live        # บอทโหมด live (testnet ตาม config)
make dps         # สถานะ + healthcheck (bot ใช้ run.py health, dashboard ใช้ /healthz)
make dlogs
make down        # หยุด (data/ ไม่ถูกลบ)
```

- โหมด: `make up MODE=live` (ตั้ง `BOT_MODE` ให้ compose ทั้ง command และ healthcheck) — เงินจริงผ่าน compose ไม่รองรับ (ไม่มี `--real-money`)
- dashboard ใน Docker ต้องตั้ง `DASHBOARD_TOKEN` ใน `.env` และเปิดที่ `http://localhost:8080/?token=<ค่า>`
- log ถูกหมุนเวียนอัตโนมัติ (10 MB × 5 ไฟล์ต่อ service)

### Dashboard

```bash
make dashboard                        # http://localhost:8080 (เฉพาะเครื่องนี้)
make dashboard HOST=0.0.0.0           # ต้องมี DASHBOARD_TOKEN
```

เข้าจากเครื่องอื่นอย่างปลอดภัย: ใช้ SSH tunnel แทนการเปิดพอร์ต เช่น
`ssh -N -L 8080:127.0.0.1:8080 -p 2223 cvsz@<host>` แล้วเปิด http://localhost:8080 บนเครื่องตัวเอง

## งานประจำ

| ความถี่ | งาน | คำสั่ง |
|---|---|---|
| ทุกวัน | ดูสถานะ, ไม้ที่เปิด, halt | `make status MODE=…` หรือ dashboard |
| ทุกวัน | ดู error ใน log | `make errors` |
| ทุกสัปดาห์ | Backup DB | `make backup` (ปลอดภัยแม้บอทรันอยู่) |
| ทุกสัปดาห์ | เทียบผล paper/live กับ backtest ช่วงเดียวกัน | `make backtest DAYS=7` |
| เมื่ออัปเดตโค้ด | หยุด → อัปเดต → `make ci` → เริ่ม | ดูด้านล่าง |

### Monitoring อัตโนมัติ

`run.py health` คืน exit 0 เมื่อ heartbeat ใหม่กว่า `max(3 × poll_seconds, 90)` วินาที ใช้กับ cron ได้:

```cron
*/5 * * * * cd ~/binance-bot && .venv/bin/python run.py health --mode live >/dev/null || echo "binance-bot unhealthy" | mail -s alert you@example.com
```

### อัปเดตโค้ด

```bash
make backup
make stop MODE=live
git pull                       # หรือ merge branch
make install                   # ติดตั้ง deps ใหม่ถ้า requirements เปลี่ยน
make ci
make start MODE=live
make health MODE=live
```

สถานะ (ไม้ที่เปิด, risk state) อยู่ใน DB และถูกโหลดกลับเมื่อเริ่มใหม่ — ไม้ที่เปิดอยู่จะถูกดูแลต่อทันที

## เหตุการณ์ฉุกเฉิน

### บอทแจ้ง `⛔ HALTED … order state unknown`

1. เปิด Binance → Orders → Order History และ Spot Wallet
2. ถ้ามีออเดอร์ซื้อที่ fill แล้วแต่บอทไม่รู้: ตัดสินใจเองว่าจะขายด้วยมือหรือถือไว้ (บอทจะไม่ดูแลเหรียญนั้น)
3. ถ้าเป็นออเดอร์ขาย: บอทเก็บ client order id ไว้ และในรอบถัดไปจะค้นหาออเดอร์ก่อนส่งขายซ้ำ — ถ้าขายไปแล้วจริงจะบันทึก sell/PnL ให้ครบ แทนที่จะทิ้งไม้แบบ `missing`
4. เมื่อบัญชีสอดคล้องแล้ว: `make resume MODE=live`

### บอทแจ้ง `⛔ HALTED … untracked … in wallet (no position/stop)`

ตอนเริ่มต้นบอทพบเหรียญ base ในกระเป๋า แต่ไม่มี position บันทึกอยู่ (ซื้อแล้ว fill แต่สถานะยังไม่เซฟ / crash) — เหรียญส่วนนี้ **ไม่มี stop** และบอทจะหยุดเปิดไม้ใหม่

1. เปิด Binance → Spot Wallet เช็คยอดเหรียญนั้น
2. ตัดสินใจเอง: ขายด้วยมือ หรือรับเป็นไม้ที่บอทจะต้องดูแล (ถ้าต้องการให้บอทดูแล ต้องป้อนสถานะไม้เข้าระบบเอง — ปัจจุบันไม่มี CLI สำหรับทำเรื่องนี้)
3. เมื่อยอดในกระเป๋าสอดคล้องกับ position ที่บอทรู้จักแล้ว: `make resume MODE=…`

### บอทแจ้ง `⛔ max drawdown …`

พอร์ตลดจากจุดสูงสุดเกินกำหนด — ทบทวนกลยุทธ์/ตลาดก่อน ถ้าตัดสินใจไปต่อ: `make resume MODE=…`

### บอทหยุดเองด้วย `STOPPED - fatal error` (exit code 3)

API key ผิด/หมดอายุ/ถูกจำกัดสิทธิ์/IP ไม่อยู่ใน whitelist หรือ symbol ผิด — แก้ `.env`/`config.yaml` แล้วเริ่มใหม่ **ถ้ามีไม้เปิดอยู่ stop ไม่ทำงานระหว่างที่บอทหยุด** ให้ดูแลเองบน Binance

### ต้องการหยุดทุกอย่างทันที (kill switch ด้วยมือ)

```bash
make stop MODE=live            # หรือ make down สำหรับ Docker
```

ไม้ที่เปิดอยู่ยังค้างบน Binance — ขายเองบนแอป/เว็บ Binance ถ้าต้องการปิดสถานะ เมื่อเริ่มบอทใหม่ บอทจะเห็นว่าเหรียญหายไปและเลิกติดตามไม้นั้น

### เครื่องดับ/รีบูต

- Docker: กลับมาเองเมื่อ Docker daemon เริ่ม
- tmux: `make start MODE=…` ใหม่ แล้ว `make status` ตรวจไม้ที่เปิด

## Backup และกู้คืน

```bash
make backup                                   # → backups/bot.<mode>.<YYYYMMDD-HHMMSS>.db
make backups                                  # รายการ backup
make stop MODE=paper
make restore MODE=paper FILE=backups/bot.paper.20261118-153348.db
make start MODE=paper
```

`make restore` ปฏิเสธถ้าบอทยังรันอยู่ และย้าย DB เดิม (รวม `-wal`/`-shm`) ไปเก็บที่ `backups/pre-restore-<ts>/` ก่อนกู้คืน — ย้อนกลับได้เสมอ

> ไฟล์ backup มีประวัติเทรดและยอดเงิน — เก็บในที่ปลอดภัย (ไม่มี API key อยู่ใน DB)

## รีเซ็ต paper trading

```bash
make stop MODE=paper
make reset-paper        # ย้าย DB paper ไป backups/paper-reset-<ts>/ (ไม่ลบ)
make start MODE=paper   # เริ่มด้วยเงิน paper.starting_quote
```
