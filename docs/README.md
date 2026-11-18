# เอกสารโปรเจกต์ Binance Spot Trading Bot

บอทเทรด Binance Spot แบบ long-only เขียนด้วย Python + ccxt มี backtest, paper trading, live (testnet/เงินจริง), web dashboard และ kill switch หลายชั้น

> ⚠️ บอทนี้ **ไม่รับประกันกำไร** — อ่าน [กลยุทธ์](STRATEGIES.md) และ [ความเสี่ยง](RISK.md) ก่อนใช้เงินจริงทุกครั้ง

## เริ่มต้นเร็ว

```bash
make setup          # สร้าง .venv, ติดตั้ง dependency, สร้าง config.yaml/.env, ตั้ง permission
make check          # lint + tests
make backtest       # ทดสอบกลยุทธ์ย้อนหลัง 90 วัน
make start          # รัน paper trading เบื้องหลัง (tmux)
make dashboard      # http://localhost:8080
```

## สารบัญ

| เอกสาร | เนื้อหา | อ่านเมื่อ |
|---|---|---|
| [ARCHITECTURE.md](ARCHITECTURE.md) | โครงสร้างโมดูล, การไหลของข้อมูล, execution model, สถานะใน SQLite | อยากเข้าใจว่าระบบทำงานอย่างไร / จะแก้โค้ด |
| [CONFIGURATION.md](CONFIGURATION.md) | ทุกค่าใน `config.yaml` และ `.env` พร้อมกฎ validation | ตั้งค่าบอท |
| [RISK.md](RISK.md) | ขนาดไม้, stop/TP/trailing, kill switch, การ halt/resume | ก่อนรัน live |
| [STRATEGIES.md](STRATEGIES.md) | กลยุทธ์ที่มี, การเพิ่มกลยุทธ์ใหม่, วิธี backtest ให้ไม่หลอกตัวเอง | ปรับ/เพิ่มกลยุทธ์ |
| [OPERATIONS.md](OPERATIONS.md) | Runbook: เส้นทาง backtest → paper → testnet → เงินจริง, tmux, Docker, backup, เหตุการณ์ฉุกเฉิน | รันและดูแลบอท |
| [PRODUCTION.md](PRODUCTION.md) | ความพร้อม production: exit gate, checklist ก่อนเงินจริง, monitoring, backup/restore, change control | ก่อน/หลังปล่อยบอทให้รันจริง |
| [SECURITY.md](SECURITY.md) | API key, permission ไฟล์, dashboard, threat model | ก่อนใส่ API key จริง |
| [CLI.md](CLI.md) | อ้างอิงคำสั่ง `run.py`, `make` targets, exit codes, HTTP API ของ dashboard | ต้องการรายละเอียดคำสั่ง |
| [DEVELOPMENT.md](DEVELOPMENT.md) | dev setup, tests, lint, การล็อกเวอร์ชัน, git workflow | พัฒนา/แก้โค้ด |
| [TROUBLESHOOTING.md](TROUBLESHOOTING.md) | อาการ → สาเหตุ → วิธีแก้ | เมื่อมีปัญหา |

ไฟล์อื่นที่ราก repo: [README.md](../README.md) (ภาพรวม), [CHANGELOG.md](../CHANGELOG.md) (ประวัติการเปลี่ยนแปลง), [AGENTS.md](../AGENTS.md) (กติกาสำหรับ AI agents/ผู้ร่วมพัฒนา)

## ข้อจำกัดที่ตั้งใจไว้

- **Spot long-only** — ไม่มี short, margin, futures, leverage
- **คู่เทรดเดียวต่อโปรเซส** — ต้องการหลายเหรียญให้รันหลายโปรเซสด้วย config/`db_path` แยกกัน
- **Market order เท่านั้น** และ **stop-loss ทำงานฝั่งบอท** — ถ้าบอทดับ stop ไม่ทำงาน (ดู [RISK.md](RISK.md#bot-side-stops))
- รองรับ **Binance global** (binance.com) เท่านั้น — Binance TH เป็นคนละ API
