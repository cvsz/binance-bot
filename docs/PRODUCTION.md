# ความพร้อมสำหรับ production

เอกสารนี้สรุปสิ่งที่ต้องทำให้ครบก่อนและหลังปล่อยบอทให้รันจริง 24/7 อ่านคู่กับ [OPERATIONS.md](OPERATIONS.md) (runbook) และ [SECURITY.md](SECURITY.md) (ความปลอดภัย)

## 1. เกณฑ์ผ่านก่อนปล่อย (exit gate)

ทำ **`make ci`** ใน WSL ให้ผ่านทุกครั้งก่อน commit/merge และก่อนเริ่ม live:

| ตรวจ | คำสั่ง | เกณฑ์ผ่าน |
|---|---|---|
| Lint | `make lint` | `All checks passed!` |
| เอกสาร | `make docs-check` | `0 broken link(s)` |
| ความลับ | `make secrets-check` | `0 problem(s)` (ตรวจทั้งไฟล์ปัจจุบันและ git history) |
| ทดสอบ | `make test` | ทุก test ผ่าน (ไม่มี test ใดแตะ network) |
| Docker | `make dconfig` หรือ `make ci` | `compose: valid` |

> ห้ามใช้ `make test-fast` แทน `make test` ตอนตัดสินใจปล่อย — `test-fast` ข้าม slow test (การจำลองตลาดยาวๆ)

## 2. Checklist ก่อนใช้เงินจริง

ดู [RISK.md](RISK.md#pre-live-checklist) และ [SECURITY.md](SECURITY.md#real-money-gates) ด้วย สรุปขั้นต่ำ:

- [ ] `make ci` ผ่านบน commit ที่จะรันจริง (record commit hash ไว้)
- [ ] Backtest หลายช่วง (ขาขึ้น/ขาลง/sideways) หลายเหรียญ ผลดีกว่า buy & hold หลังปรับความเสี่ยง และ profit factor > 1
- [ ] Paper ≥ 1–2 สัปดาห์ และ testnet ≥ 1 สัปดาห์ ไม่มี `WARNING`/`ERROR` ที่อธิบายไม่ได้ (`make errors`)
- [ ] ประตูเงินจริงครบ 4 ชั้น: `testnet: false` + key จริง + `--real-money` + `BOT_CONFIRM_REAL_MONEY=YES_I_ACCEPT_THE_RISK`
- [ ] ใช้ **sub-account** ที่โอนเข้าเฉพาะเงินที่เสียได้, key ปิด Withdrawals/Futures, ผูก IP whitelist
- [ ] ถ้าใช้ `exchange.name` ไม่ใช่ `binance`: ตรวจว่า key prefix ตรง venue (`BINANCEUS_*`) และ DB suffix ใหม่ถูกต้อง (`make info`)
- [ ] ตั้ง `max_drawdown_halt_pct` และเปิด Telegram (token/chat id ใน `.env`)
- [ ] `.env` เป็น `chmod 600` (`make perms`), `config.yaml` 644, โฟลเดอร์ 755
- [ ] ตั้ง `DASHBOARD_TOKEN` แบบสุ่มยาวถ้าเปิด dashboard นอก localhost; ใช้ SSH/Cloudflare tunnel เสมอ (ไม่มี HTTPS ในตัว)
- [ ] `make backup` สำเร็จอย่างน้อย 1 ครั้ง และทดสอบ restore ในสภาพแวดล้อมทดสอบ

## 3. Deployment

**tmux (เครื่อง/VPS ส่วนตัว):** `make start MODE=live` → `make health MODE=live` → `make logs MODE=live`
**Docker:** `mkdir -p data` ก่อน → `make up MODE=live` → `make dps` (healthcheck ทุก 60s, `restart: unless-stopped`)

ข้อควรระวัง:
- `make start` / `make up` **ไม่รองรับเงินจริง** (ตั้งใจ) — เงินจริงต้อง `make live-real CONFIRM=YES_I_ACCEPT_THE_RISK` ใน foreground เท่านั้น
- หนึ่งคู่เทรดต่อหนึ่งโปรเซส ถ้าต้องการหลายเหรียญใช้ config + `db_path` แยก (ดู [CONFIGURATION.md](CONFIGURATION.md))
- ติดตั้ง `adjustForTimeDifference` ไว้แล้ว แต่ถ้าเจอ `-1021` ให้แก้นาฬิกา (ดู [TROUBLESHOOTING.md](TROUBLESHOOTING.md))

## 4. Monitoring และ alerting

| สิ่งที่ต้องดู | วิธี | สัญญาณเตือน |
|---|---|---|
| Heartbeat | `make health MODE=live` หรือ `GET /healthz` | exit 1 = ไม่ online; dashboard แสดง `stale`/`offline` |
| ข้อความจากบอท | Telegram | `⛔ HALTED`, `⛔ STOPPED`, `stale price`, `SELL FAILED`, `position dropped` ต้องมีคนตอบสนอง |
| ความสดของราคา | heartbeat `price_stale` / `price_age_s` | `price_stale: true` แปลว่าไม่มีการเปิดไม้ใหม่จนกว่าราคาจะสด |
| Log | `make errors`, `make logs` | `HALTED`/`STOPPED`/`CRITICAL` ซ้ำผิดปกติ |
| ฐานข้อมูล | `make info` | ขนาด/วันที่ของ `data/*.db` ไม่ควรค้างนาน |

Dashboard ตัดสินสถานะจาก heartbeat: `online` ถ้าอายุ < `max(3 × poll_seconds, 90)` วินาที มิฉะนั้น `stale`

ข้อจำกัดที่ต้องยอมรับ: **stop ทำงานฝั่งบอท** ถ้าโปรเซส/เครื่อง/เน็ตดับ stop ไม่ทำงาน — Docker `restart: unless-stopped` + Telegram คือแนวป้องกันหลัก อย่าถือว่ามี stop บน Binance

## 5. Backup / Restore

- `make backup` ใช้ SQLite online backup API → consistency แม้บอทกำลังเขียน เก็บใน `backups/`
- ควร copies ไปที่อื่นนอกเครื่องด้วย (backup ในเครื่องเดียวกันไม่พอถ้าเครื่องเสีย)
- `make restore MODE=… FILE=backups/bot.live.<ts>.db` **ต้องหยุดบอทก่อน** (`make stop` / `make down`); ระบบตรวจ integrity + ตารางก่อน และย้าย DB เดิมไป `backups/pre-restore-<ts>/` เสมอ
- อย่าลบ `data/` หรือ `backups/` manually

## 6. เหตุการณ์ฉุกเฉิน

| เหตุการณ์ | การตอบสนอง |
|---|---|
| `⛔ HALTED … order state unknown` / `untracked … in wallet` | ห้ามกด resume ทันที — เช็คยอด/ออเดอร์บน Binance ว่าขายไปหรือยัง แล้วค่อย `make resume MODE=live` |
| `⛔ STOPPED - fatal error` (exit 3) | key/IP/symbol ผิด — แก้แล้ว restart; ถ้ามีไม้เปิดอยู่ stop **ไม่ถูกดูแล** ให้จัดการไม้นั้นด้วยมือ |
| เน็ตหลุดชั่วคราว | ปกติ: backoff ×2 สูงสุด 600s และลูปไม่ตาย; ถ้านานเกิน 10 นาทีให้ดู log/health |
| ไม้ dust / missing | บอทเลิกติดตามและแจ้งเตือน — เหรียญยังอยู่ในกระเป๋า จัดการเองบน Binance |
| ต้องการหยุดด่วน | `make stop` (tmux) หรือ `make down` (Docker) — SIGINT/SIGTERM บันทึกสถานะก่อนออก |

การ `resume` ตั้ง peak ของ drawdown ใหม่เป็น equity ปัจจุบัน เพื่อไม่ให้ halt ซ้ำทันที (ดู [RISK.md](RISK.md#resume))

## 7. การเปลี่ยนแปลง (change control)

- Branch ต่อการเปลี่ยนแปลง (`feat/…`, `fix/…`, `docs/…`), commit message `type: summary`
- **ห้าม**ลดความเข้มงวดของ: stop-loss บังคับ, validation ของ `RiskConfig`, no-lookahead, atomic state save, dashboard แบบ read-only, client-order-id recovery, ประตูเงินจริง
- ทุก bug fix ต้องมี regression test; กลยุทธ์ใหม่ต้อง backtest หลายช่วงก่อนปล่อย
- เปลี่ยนพฤติกรรม/CLI/config/make target → อัปเดต `docs/`, `README.md`, `CHANGELOG.md` ใน commit เดียวกัน
- หลัง deploy ทุกครั้ง: `make health` + `make logs` + ยืนยัน commit hash ที่รันตรงกับที่ผ่าน `make ci`

## 8. สถานะการตรวจล่าสุด

 documented ไว้ใน [CHANGELOG.md](../CHANGELOG.md) หัวข้อ `[Unreleased]` — ผลจริงต้องรัน `make ci` เอง ณ commit ที่จะปล่อย อย่าเชื่อ record เก่า
