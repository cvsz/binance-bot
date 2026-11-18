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
- **ยืนยัน fill เร็วเกินไปจาก partial fill** → `_settle` รอจนส่วนต่าง balance ตรงกับจำนวนที่ออเดอร์รายงาน
- **live stop ถูกบันทึกเป็น `stop_gap` ทุกครั้ง** → ส่ง `open_=None` จาก runner ให้เหตุผลเป็น `stop_loss`/`trailing_stop` ตามความจริง
- **backtest trailing stop มองดีเกินจริง** → เมื่อเลื่อน stop ด้วย high แล้วเช็คซ้ำกับ low ของแท่งเดียวกัน
- **sell ที่ fill แต่ผลหายแล้วถูกทิ้งเป็น `missing`** → เก็บ client order id และคืนค่า fill/PnL ก่อนลองขายใหม่
- **resume ถูกลบก่อนเซฟสถานะ** → ลบคำขอหลังบันทึก transaction สำเร็จ
- **สัญญาณ/sizing ใช้ราคาเปิดใน backtest ทำให้ kill switch ไม่ตรงกราฟ** → แยก `mark_price` (ราคาปิด) ออกจากราคาส่งคำสั่ง
- **ขนาดไม้ live ใช้ quote ทั้งหมด** → กัน 1% fee headroom
- **เหรียญ base ค้างในกระเป๋าโดยไม่มี position** → halt การเปิดไม้ใหม่และแจ้งเตือนตอน restore
- ใช้ข้อมูลจากออเดอร์เมื่ออ่าน balance หลัง fill ไม่ได้
- ไม้ dust ทำให้ขายล้มเหลวทุก 30 วินาทีไม่รู้จบ → เลิกติดตามพร้อมแจ้งเตือน
- Exception ที่ไม่คาดคิดทำให้ลูปตาย (stop ของไม้ที่เปิดไม่ทำงาน) → ลูปทนทาน; error ด้าน auth หยุดบอทอย่างปลอดภัย (exit 3)
- สถานะ position/balances บันทึกแยก transaction → บันทึกแบบ atomic; trailing stop บันทึกทันที
- Dashboard ที่บอกว่า "อ่านอย่างเดียว" เปิด DB แบบเขียนได้ → เปิดแบบ `mode=ro`
- Telegram ถูกส่งข้อความ error ซ้ำทุกรอบ → กรองข้อความซ้ำ 15 นาที
- Config section ว่างทำให้ crash, ค่าผิด/ชื่อ key สะกดผิดไม่ถูกตรวจ → validate พร้อมข้อความชัดเจน
- Permission: `.env` 755 → 600, โฟลเดอร์ 777 → 755; `.gitignore` ไม่ครอบคลุม `.venv/` และ `*.db`

### Security
- Dashboard ไม่ log query string (กัน `DASHBOARD_TOKEN` รั่วผ่าน log บอท); Docker dashboard ได้เฉพาะ `DASHBOARD_TOKEN`
- Config ปฏิเสธ key ที่สะกดผิดทุก section, parse boolean แบบเข้มงวด, ปฏิเสธ `..` ใน `db_path`, และรายงาน type ผิดเป็น `config error` (exit 2)
- `check_secrets.py` ตรวจ git history ด้วย; `check_docs.py` เข้าใจ anchor ที่ซ้ำกัน; `Makefile` ส่งค่า path ผ่าน argv/env แทนการฝังในโค้ด Python; Telegram dedup จำกัดจำนวนข้อความที่ track
- ตรวจประตูเงินจริงซ้ำใน `Runner.run()` (defense in depth)
- ไม่ log URL ของ Telegram (มี token)
- Container รันด้วย uid 1000 คงที่

## [0.1.0] — baseline (commit `fa494cb`)

- Backtest / paper / live (testnet + เงินจริง) ด้วย ccxt, กลยุทธ์ `ema_cross` และ `rsi_reversion`
- Risk: sizing ตามความเสี่ยง, SL/TP/trailing, daily loss limit, จำกัดไม้ต่อวัน, cooldown
- SQLite state, Telegram, web dashboard แบบ read-only, Docker Compose
