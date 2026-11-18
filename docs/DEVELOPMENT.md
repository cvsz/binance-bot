# การพัฒนา

## สภาพแวดล้อม

| เครื่องมือ | เวอร์ชัน | หมายเหตุ |
|---|---|---|
| Python | 3.12+ (dev ใช้ 3.14, Docker ใช้ 3.12) | โค้ดใช้ `X \| None`, `datetime.UTC`, `zip(strict=)` |
| GNU Make | 4.x | |
| ruff | ≥ 0.6 | ติดตั้งผ่าน `requirements-dev.txt` |
| tmux / Docker | ไม่บังคับ | สำหรับรันเบื้องหลัง |

```bash
make install        # .venv + requirements-dev.txt ตาม constraints.txt
make ci             # gate เต็ม (lint, docs, secrets, tests) ต้องผ่านก่อน commit ทุกครั้ง
```

โปรเจกต์อยู่ใน WSL (`~/binance-bot`) — เข้าทาง SSH ได้ที่ `ssh -p 2223 cvsz@192.168.1.85` ควรเก็บไฟล์บน filesystem ของ Linux ไม่ใช่ `/mnt/c` (เร็วกว่ามาก)

## โครงสร้าง repo

```
bot/                โค้ดหลัก (ดู ARCHITECTURE.md)
tests/
  test_bot.py         indicators, strategies (no-lookahead), risk, broker, engine, backtest, ประตู live
  test_runner.py      Runner + FakeExchange (จำลอง ccxt รวมการจำลอง timeout/error)
  test_dashboard.py   summary, HTTP endpoints, token
  test_hardening.py   regression tests ของการแก้ไขจาก audit (order recovery, dust, kill switch, config ฯลฯ)
  test_production.py  regression tests ของ production hardening (fill confirmation, stop reason, reconciliation, config, dashboard, kill switch)
docs/               เอกสาร
scripts/            check_docs.py, check_secrets.py (ใช้โดย make ci)
run.py              CLI
Makefile            คำสั่งสำหรับ dev/ops
pyproject.toml      ตั้งค่า pytest + ruff
requirements*.txt   dependency (มีเพดานเวอร์ชัน)
constraints.txt     เวอร์ชันที่ล็อกแล้ว (ผ่านเทส)
```

## Tests

```bash
make test                   # ทั้งหมด (~1 นาที)
make test-fast              # ข้าม test ที่ mark slow (~2 วินาที) — ใช้ระหว่างเขียนโค้ด
make test ARGS="-k dust -v" # เลือกเฉพาะบาง test
```

- Test ทั้งหมด **ไม่ต่อเน็ต** — ใช้ข้อมูลสังเคราะห์ (`tests/test_bot.py::synthetic`) และ `FakeExchange` ที่มี signature เหมือน ccxt
- `FakeExchange` จำลองความผิดพลาดได้: `fail_submit_after_fill`, `fail_submit_before_fill`, `fail_lookup`, `fail_balance_after_order`
- Test ที่ใช้เวลานานให้ใส่ `@pytest.mark.slow`
- แก้บั๊ก: เขียน test ที่ fail ก่อน แล้วค่อยแก้ (regression test)

### สิ่งที่ test บังคับไว้ (ห้ามทำให้พัง)

- ไม่มี lookahead ในทุกกลยุทธ์
- Stop เป็นสิ่งบังคับ, sizing ไม่เกินเพดาน
- ออเดอร์ที่ fill แล้วแต่ submit timeout ต้องถูกกู้คืน
- สถานะ position + balances บันทึกแบบ atomic
- Dashboard เขียน DB ไม่ได้, bind นอก localhost ต้องมี token
- ประตูเงินจริงทุกข้อ

## Lint และรูปแบบโค้ด

```bash
make lint          # ruff: E, F, W, B, UP, SIM, S (security)
make fix           # แก้อัตโนมัติที่ปลอดภัย
```

- บรรทัดยาวสูงสุด 120, type hints ทุก public function, docstring อธิบาย "ทำไม" ไม่ใช่ "ทำอะไร"
- โค้ด/คอมเมนต์/ชื่อตัวแปร เป็นภาษาอังกฤษ; เอกสารผู้ใช้เป็นภาษาไทย
- ห้าม `print` ใน `bot/` (ใช้ `logging`), ห้าม log ค่าความลับ
- Error ที่ผู้ใช้แก้ได้ → `ValueError`/`PermissionError` พร้อมข้อความบอกวิธีแก้

## Dependencies

```bash
# อัปเดต dependency
.venv/bin/pip install -U ccxt          # ภายในเพดานของ requirements.txt
make check
make lock                              # เขียน constraints.txt ใหม่ (รัน check ก่อนเสมอ)
git diff constraints.txt               # review
```

เพิ่ม dependency ใหม่เฉพาะเมื่อจำเป็นจริง — dashboard ตั้งใจใช้ stdlib เท่านั้น

## Git workflow

- `main` = โค้ดที่ใช้งานได้; ทำงานบน branch แยก (เช่น `audit/hardening`, `feat/<name>`, `fix/<name>`)
- `make ci` ต้องผ่านก่อน commit
- Commit message: `type: summary` (`feat`, `fix`, `docs`, `chore`, `test`, `refactor`)
- ห้าม commit `.env`, `config.yaml`, `data/`, `backups/`, `logs/` (ถูก ignore แล้ว — ตรวจ `git status` ทุกครั้ง)
- อัปเดต `CHANGELOG.md` และเอกสารใน `docs/` เมื่อพฤติกรรม/คำสั่ง/ค่า config เปลี่ยน

## จุดที่ควรพัฒนาต่อ

| หัวข้อ | เหตุผล |
|---|---|
| วาง stop/OCO บน Binance | stop ทำงานแม้บอทดับ |
| Equity เฉพาะส่วนของบอทในโหมด live | ไม่ให้เหรียญเดิมในบัญชีมีผลต่อ sizing/kill switch |
| Walk-forward / parameter sweep ใน backtest | ลด overfitting |
| CI (GitHub Actions) | รัน `make check` อัตโนมัติเมื่อมี remote |
| Retry การเข้าไม้ซ้ำในแท่งเดียวกันหลัง ExchangeError | ปัจจุบันจะลองใหม่ทุกรอบ poll จนกว่าจะสำเร็จหรือแท่งใหม่มา |
