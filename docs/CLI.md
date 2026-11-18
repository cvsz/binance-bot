# อ้างอิงคำสั่ง

## `run.py`

```
python run.py [-c CONFIG] [-v] <command> [options]
```

| ตัวเลือกทั่วไป | ค่าเริ่มต้น | ความหมาย |
|---|---|---|
| `-c, --config` | `config.yaml` | ไฟล์ config |
| `-v, --verbose` | ปิด | log ระดับ DEBUG (backtest: แสดงทุกไม้) |

`.env` ในโฟลเดอร์ปัจจุบันถูกโหลดอัตโนมัติ

| คำสั่ง | ตัวเลือก | ทำอะไร |
|---|---|---|
| `backtest` | `--days N` (90), `--csv FILE`, `--out DIR` (`reports`) | ทดสอบย้อนหลัง พิมพ์สถิติ และเขียน `backtest_trades.csv`, `backtest_equity.csv` |
| `paper` | — | รันด้วยราคาจริง เงินจำลอง |
| `live` | `--real-money` | ส่งคำสั่งจริง (testnet ถ้า `exchange.testnet: true`) |
| `status` | `--mode paper\|live` | พิมพ์ JSON: position, risk, paper_balances, last_bar, 10 เทรดล่าสุด |
| `health` | `--mode paper\|live` | `online` → exit 0; `stale`/`offline`/ไม่มี DB → exit 1 |
| `resume` | `--mode paper\|live` | ขอปลด halt (บอทที่รันอยู่ใช้ในรอบถัดไป) |
| `backup` | `--dir DIR` (`backups`) | backup ทุก DB ด้วย SQLite online backup API |
| `dashboard` | `--host` (`127.0.0.1`), `--port` (8080) | web dashboard แบบอ่านอย่างเดียว |

`--mode live` จะหมายถึง DB ของ testnet อัตโนมัติเมื่อ `exchange.testnet: true`

### Exit codes

| Code | ความหมาย |
|---|---|
| 0 | สำเร็จ / healthy / ไม่มีอะไรต้องทำ |
| 1 | ไม่พบสถานะ/DB (`status`, `resume`, `backup`), ไม่ healthy (`health`) |
| 2 | config ผิด, ปฏิเสธการเริ่ม live (ขาด key/ประตูเงินจริง), dashboard bind นอก localhost โดยไม่มี token |
| 3 | บอทหยุดเองเพราะ error ร้ายแรง (API key ใช้ไม่ได้, บัญชีถูกระงับ, symbol ผิด) |

## `make`

รัน `make` เฉยๆ เพื่อดูรายการทั้งหมดพร้อมคำอธิบาย

### ตัวแปร (override บนบรรทัดคำสั่ง เช่น `make backtest DAYS=180`)

| ตัวแปร | ค่าเริ่มต้น | ใช้กับ |
|---|---|---|
| `MODE` | `paper` | status, health, resume, start, stop, restart, attach, logs, restore, up |
| `CONFIG` | `config.yaml` | ทุกคำสั่งที่เรียก `run.py` |
| `DAYS` | `90` | backtest |
| `CSV` | — | backtest (ถ้าตั้ง จะใช้แทน `DAYS`) |
| `OUT` | `reports` | backtest, clean-reports |
| `VERBOSE` | — | `1` = ส่ง `-v` |
| `HOST` / `PORT` | `127.0.0.1` / `8080` | dashboard |
| `ARGS` | — | ส่งต่อให้ pytest เช่น `ARGS="-k dust"` |
| `SESSION` | `binance-bot-$(MODE)` | ชื่อ tmux session |
| `BACKUP_DIR` | `backups` | backup |
| `CONFIRM` | — | live-real (ต้องเป็น `YES_I_ACCEPT_THE_RISK`) |
| `FILE` | — | restore (ไฟล์ backup ที่จะกู้คืน) |
| `LOG_DIR` | `logs` | start, logs, errors |
| `PYTHON` / `VENV` | `python3` / `.venv` | install |
| `COMPOSE` / `IMAGE` | `docker compose` / `binance-bot:local` | Docker targets |

### Targets

| กลุ่ม | Target | ทำอะไร |
|---|---|---|
| Setup | `setup` | install + config + perms (ครั้งแรก) |
| | `install` | สร้าง `.venv` และติดตั้ง deps ตาม `constraints.txt` (ติดตั้งซ้ำเฉพาะเมื่อ requirements เปลี่ยน — ถ้าไม่เปลี่ยนจะแสดงแค่ `venv ready`) |
| | `reinstall` | บังคับติดตั้ง deps ใหม่ทั้งหมด |
| | `info` | branch/commit, เวอร์ชัน Python/ccxt/pandas, tmux sessions, ไฟล์ DB |
| | `config` | สร้าง `config.yaml`/`.env` จากตัวอย่างถ้ายังไม่มี (ไม่เขียนทับ), สร้าง `data/` |
| | `perms` | `.env` 600, โฟลเดอร์ 755, config 644 |
| | `lock` | รัน `check` แล้วเขียน `constraints.txt` ใหม่จาก venv |
| | `doctor` | ตรวจ Python, venv, config, `.env` (บอกแค่ว่าตั้งแล้ว/ว่าง), Docker, tmux |
| Quality | `ci` | gate เต็ม: `lint` + `docs-check` + `secrets-check` + `test` + ตรวจ compose (ถ้ามี Docker) |
| | `check` | `lint` + `test` |
| | `docs-check` | ตรวจลิงก์/anchor ใน Markdown ทุกไฟล์ (`scripts/check_docs.py`) |
| | `secrets-check` | fail ถ้า `.env`/`config.yaml`/DB ถูก track, มีค่าคล้าย credential ในไฟล์, หรือ `.env` ไม่ใช่ 600 (`scripts/check_secrets.py`) |
| | `test` / `test-fast` | ทั้งหมด / ข้าม test ที่ mark `slow` และหยุดที่ fail แรก |
| | `lint` / `fix` / `fmt-check` | ruff check / auto-fix / แสดง diff การจัดรูปแบบ |
| Trading | `backtest`, `paper`, `live` | ตาม `run.py` |
| | `live-real` | เงินจริง ต้องมี `CONFIRM=YES_I_ACCEPT_THE_RISK` + ประตูใน `.env` |
| | `status`, `health`, `resume`, `dashboard` | ตาม `run.py` |
| tmux | `start`, `stop`, `restart`, `attach`, `logs`, `ps` | รันเบื้องหลัง — ดู [OPERATIONS.md](OPERATIONS.md#tmux-make-start) |
| | `errors` | 50 บรรทัด WARNING/ERROR/HALTED ล่าสุดจาก log ทั้งหมด |
| Data | `backup` | backup ทุก DB (ปลอดภัยขณะบอทรัน) |
| | `backups` | แสดงรายการ backup |
| | `restore` | `MODE=… FILE=…` กู้คืน DB — ต้องหยุดบอทก่อน, DB เดิมถูกย้ายไป `backups/pre-restore-<ts>/` |
| | `reset-paper` | เริ่ม paper ใหม่ — ย้าย DB paper ไป `backups/paper-reset-<ts>/` (ไม่ลบ, ใช้กับ paper เท่านั้นเสมอ) |
| | `clean-reports` | ลบ `reports/` |
| Docker | `up` | `MODE=paper\|live` → compose up บอท + dashboard (**ปฏิเสธถ้า `DASHBOARD_TOKEN` ว่าง**; dashboard container ได้เฉพาะ token ไม่ได้ `.env` ทั้งไฟล์) |
| | `docker-build`, `down`, `dlogs`, `dps`, `dconfig` | build / down / logs / ps+health / validate compose |
| Housekeeping | `clean`, `distclean` | ลบ cache / + ลบ `.venv` — **ไม่แตะ** `data/`, `backups/`, `logs/`, `.env`, `config.yaml` |

คำสั่งที่เขียน/ย้าย DB (`restore`, `reset-paper`) จะปฏิเสธถ้าบอทของโหมดนั้นรันอยู่ใน tmux หรือ Docker; คำสั่งเทรดทั้งหมดปฏิเสธถ้ายังไม่มี `config.yaml`

## Dashboard HTTP API

ทุก endpoint (ยกเว้น `/healthz`) ต้องส่ง token เมื่อเซิร์ฟเวอร์ตั้ง `DASHBOARD_TOKEN`: header `X-Dashboard-Token: <token>` หรือ `?token=<token>`
endpoint ข้อมูลรับ `?mode=paper|live-testnet|live` (ค่าเริ่มต้น `paper`)

| Method / Path | คืนค่า |
|---|---|
| `GET /healthz` | `{"ok": true}` |
| `GET /` | หน้า dashboard (HTML) |
| `GET /api/modes` | รายชื่อโหมดที่มี DB อยู่ เช่น `["paper"]` |
| `GET /api/summary` | สถานะบอท, อายุ heartbeat, ราคา, equity, % ผลตอบแทน, balances, ไม้ที่เปิด (+ กำไรที่ยังไม่ปิด), risk state, สถิติ |
| `GET /api/trades` | 200 เทรดล่าสุด (ใหม่สุดก่อน) |
| `GET /api/equity` | จุด equity ล่าสุดไม่เกิน 2000 จุด `[{ts, equity, price}]` |

Error: `401 {"error":"unauthorized"}`, `404 {"error":"no data for mode …"}` / `{"error":"not found"}`

ตัวอย่าง:

```bash
curl -s -H "X-Dashboard-Token: $DASHBOARD_TOKEN" "http://127.0.0.1:8080/api/summary?mode=paper" | python -m json.tool
```
