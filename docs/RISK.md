# การบริหารความเสี่ยง

ทุกการตัดสินใจเรื่องความเสี่ยงอยู่ใน `bot/risk.py` (`RiskManager`) และถูกเรียกจาก `bot/engine.py` เหมือนกันทุกโหมด

## ขนาดไม้ (position sizing)

```
ขนาดตามความเสี่ยง = equity × risk_per_trade_pct% ÷ stop_loss_pct%
ขนาดจริง         = min(ขนาดตามความเสี่ยง, equity × max_position_pct%, quote ที่ว่าง)
```

ตัวอย่าง: พอร์ต 1,000 USDT, risk 1%, stop 2% → ขนาดตามความเสี่ยง = 500 แต่เพดาน 25% → **ไม้ละ 250 USDT** ถ้าโดน stop เสีย ≈ 5 USDT (0.5%) + ค่าธรรมเนียม/slippage

- ไม้ที่เล็กกว่าขั้นต่ำของตลาด (`limits.cost.min` ของ Binance, ปกติ 5 USDT) จะถูกข้าม
- ค่าธรรมเนียมไม่ได้ถูกรวมในสูตร — ความเสี่ยงจริงสูงกว่า `risk_per_trade_pct` เล็กน้อย (≈ 2 × fee + slippage)
- **live**: `equity` = มูลค่า base + quote **ทั้งบัญชี** ถ้ามีเหรียญเดิมอยู่ ขนาดไม้และขีดจำกัดต่างๆ จะคิดรวมเหรียญเดิมด้วย → แนะนำ **sub-account แยกสำหรับบอท**
- **live** กันไว้ 1% ของ quote ว่างก่อนคำนวณขนาดไม้ (fee headroom) เพื่อไม่ให้ market buy + ค่าธรรมเนียมเกินยอดคงเหลือ
- **live** ไม่เปิดไม้ใหม่ถ้าราคาล่าสุดจาก exchange มี timestamp เก่าเกิน `max(3 × poll_seconds, 90)` วินาที (กันส่งคำสั่งที่ราคาเก่าหลัง feed ค้าง) — stop ของไม้ที่เปิดอยู่ยังเช็คตามปกติ

## Stop-loss / Take-profit / Trailing

| ระดับ | คำนวณจาก | หมายเหตุ |
|---|---|---|
| Stop | `entry × (1 − stop_loss_pct%)` | บังคับมีเสมอ |
| Take profit | `entry × (1 + take_profit_pct%)` | `null` = ไม่ใช้ |
| Trailing | `peak × (1 − trailing_stop_pct%)` | stop เลื่อนขึ้นอย่างเดียว ไม่เลื่อนลง; บันทึกลง DB ทันทีที่เลื่อน; ถ้า stop ใหม่ถูก low ของแท่งเดียวกันทะลุจะออกที่ stop ใหม่ในแท่งนั้นเลย |

เหตุผลการออก (`reason` ในตาราง trades): `signal`, `stop_loss`, `trailing_stop` (stop อยู่เหนือราคาเข้า), `stop_gap` (ราคาเปิด gap ต่ำกว่า stop — backtest เท่านั้น), `take_profit`

<a id="bot-side-stops"></a>
### ข้อจำกัดของ stop ฝั่งบอท

Stop/TP **ไม่ได้วางไว้บน Binance** — บอทเช็คราคาทุก `poll_seconds` แล้วส่ง market order เอง ผลคือ:

- ถ้าบอท/เครื่อง/เน็ตดับ **stop ไม่ทำงาน** → ใช้ Docker `restart: unless-stopped` หรือ `make start` บนเครื่องที่เปิดตลอด และเปิด Telegram
- ราคาออกจริงอาจแย่กว่าระดับ stop ในตลาดที่ผันผวน (ระหว่างรอบ poll และ slippage ของ market order)

## Kill switches และการหยุดเปิดไม้ (halt)

เมื่อ halt บอท **หยุดเปิดไม้ใหม่เท่านั้น** — ไม้ที่เปิดอยู่ยังถูกดูแล stop/TP ตามปกติ

| ตัวกระตุ้น | เงื่อนไข | ปลดอย่างไร |
|---|---|---|
| ขาดทุนรายวัน | `(equity ต้นวัน − equity) / equity ต้นวัน ≥ max_daily_loss_pct` (วัน UTC = 07:00 เวลาไทย) | อัตโนมัติเมื่อขึ้นวันใหม่ |
| Drawdown จากจุดสูงสุด | `(peak − equity) / peak ≥ max_drawdown_halt_pct` (ถ้าตั้งค่า) | `make resume MODE=…` |
| สถานะออเดอร์ไม่แน่นอน | ส่งออเดอร์แล้วยืนยันผลไม่ได้แม้ค้นหาด้วย client order id แล้ว | ตรวจบัญชีบน Binance ก่อน แล้ว `make resume MODE=…` |
| เหรียญในกระเป๋าโดยไม่มี position | ซื้อแล้ว fill แต่สถานะยังไม่เซฟ / crash แล้วมี base ค้าง | ตรวจบัญชีว่าจะขายหรือติดตามไม้เอง แล้ว `make resume MODE=…` |
| จำนวนเหรียญไม่ตรงกับ position (`quantity mismatch`) | ขาย/โอน/ซื้อเพิ่มด้วยมือ หรือ fill ไม่ตรงที่ track | ตรวจบัญชี ปรับให้ตรงหรือยอมรับไม้จริง แล้ว `make resume MODE=…` |

ข้อจำกัดอื่นที่ไม่ใช่ halt (แค่ข้ามการเข้าไม้):

- `max_trades_per_day` — นับเฉพาะไม้ที่เปิด, รีเซ็ตทุกวัน UTC
- `cooldown_bars` — ต้องผ่านไปกี่แท่งหลังปิดไม้

### Resume

```bash
make resume MODE=live        # หรือ python run.py resume --mode live
```

- เขียนคำขอ `resume_requested` ลง DB — บอทที่รันอยู่จะนำไปใช้ในรอบ poll ถัดไป, บอทที่หยุดอยู่จะใช้ตอนเริ่มรอบแรก
- ตอน resume จุดสูงสุด (peak) ของ drawdown ถูกตั้งใหม่เป็น equity ปัจจุบัน เพื่อไม่ให้ halt ซ้ำทันที
- ถ้าบอทไม่ได้ halt คำสั่งนี้ไม่ทำอะไร

## ไม้ที่ขายไม่ได้

| สถานการณ์ | พฤติกรรม |
|---|---|
| มูลค่าไม้ต่ำกว่าขั้นต่ำของ Binance (dust) เช่นหลังราคาร่วงหนัก | เลิกติดตามไม้, บันทึก `abandon/dust`, แจ้งเตือนครั้งเดียว — **เหรียญยังค้างในกระเป๋า** ขายเองได้ด้วย "Convert small balance to BNB" |
| เหรียญในกระเป๋าเหลือไม่ถึงครึ่งของไม้ (ขายมือ/โอนออก/ล็อกใน open order) | เลิกติดตามไม้, บันทึก `abandon/missing`, แจ้งเตือน |
| ขายไม่สำเร็จด้วยเหตุผลอื่น | เก็บไม้ไว้ ลองใหม่รอบถัดไป, แจ้งเตือน (ข้อความซ้ำถูกกรองทุก 15 นาที) |

## ประตูความปลอดภัยของโหมด live

ดู [SECURITY.md](SECURITY.md#real-money-gates) — บอทจะไม่ใช้เงินจริงถ้าขาดเงื่อนไขใดเงื่อนไขหนึ่ง และเงื่อนไขถูกตรวจทั้งใน CLI และใน `Runner.run()`

<a id="pre-live-checklist"></a>
## Checklist ก่อนใช้เงินจริง

- [ ] Backtest หลายช่วงเวลา (ขาขึ้น/ขาลง/sideways) และหลายเหรียญ — ผลดีกว่า buy & hold แบบปรับความเสี่ยงแล้ว และ profit factor > 1
- [ ] Paper trading ≥ 1–2 สัปดาห์ ผลใกล้เคียง backtest
- [ ] Testnet ≥ 1 สัปดาห์ ไม่มี error ใน log
- [ ] ตั้ง `max_drawdown_halt_pct` และเปิด Telegram
- [ ] ใช้ sub-account + API key ที่ปิด withdrawal + IP whitelist
- [ ] เริ่มด้วยเงินจำนวนน้อยที่เสียได้
