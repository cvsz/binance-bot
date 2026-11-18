# Changelog

รูปแบบตาม [Keep a Changelog](https://keepachangelog.com/) — วันที่เป็นเวลา UTC+7

## [Unreleased] — branch `audit/hardening`

### Added
- เอกสารครบชุดใน `docs/` (สถาปัตยกรรม, การตั้งค่า, ความเสี่ยง, กลยุทธ์, runbook, ความปลอดภัย, อ้างอิงคำสั่ง, การพัฒนา, แก้ปัญหา) และ `AGENTS.md`
- `Makefile`: setup, quality gates (`check`, `ci`), trading, รันเบื้องหลังด้วย tmux, backup/restore, Docker, ตรวจเอกสาร/ความลับ
- คำสั่ง `run.py health`, `run.py resume`, `run.py backup`
- Kill switch `risk.max_drawdown_halt_pct` (หยุดเปิดไม้เมื่อพอร์ตลดจากจุดสูงสุด, ปลดด้วย `resume`)
- Docker healthcheck, log rotation, `.dockerignore`, `constraints.txt` (เวอร์ชันที่ผ่านเทส), `pyproject.toml` (pytest + ruff)
- Regression tests 27 รายการ (รวม 53)

### Fixed
- **ออเดอร์ที่ fill แล้วหายเมื่อเน็ตหลุดหลังส่งคำสั่ง** → ค้นหาด้วย client order id; ถ้ายืนยันไม่ได้ halt + แจ้งเตือน
- ใช้ข้อมูลจากออเดอร์เมื่ออ่าน balance หลัง fill ไม่ได้
- ไม้ dust ทำให้ขายล้มเหลวทุก 30 วินาทีไม่รู้จบ → เลิกติดตามพร้อมแจ้งเตือน
- Exception ที่ไม่คาดคิดทำให้ลูปตาย (stop ของไม้ที่เปิดไม่ทำงาน) → ลูปทนทาน; error ด้าน auth หยุดบอทอย่างปลอดภัย (exit 3)
- สถานะ position/balances บันทึกแยก transaction → บันทึกแบบ atomic; trailing stop บันทึกทันที
- Dashboard ที่บอกว่า "อ่านอย่างเดียว" เปิด DB แบบเขียนได้ → เปิดแบบ `mode=ro`
- Telegram ถูกส่งข้อความ error ซ้ำทุกรอบ → กรองข้อความซ้ำ 15 นาที
- Config section ว่างทำให้ crash, ค่าผิด/ชื่อ key สะกดผิดไม่ถูกตรวจ → validate พร้อมข้อความชัดเจน
- Permission: `.env` 755 → 600, โฟลเดอร์ 777 → 755; `.gitignore` ไม่ครอบคลุม `.venv/` และ `*.db`

### Security
- ตรวจประตูเงินจริงซ้ำใน `Runner.run()` (defense in depth)
- ไม่ log URL ของ Telegram (มี token)
- Container รันด้วย uid 1000 คงที่

## [0.1.0] — baseline (commit `fa494cb`)

- Backtest / paper / live (testnet + เงินจริง) ด้วย ccxt, กลยุทธ์ `ema_cross` และ `rsi_reversion`
- Risk: sizing ตามความเสี่ยง, SL/TP/trailing, daily loss limit, จำกัดไม้ต่อวัน, cooldown
- SQLite state, Telegram, web dashboard แบบ read-only, Docker Compose
