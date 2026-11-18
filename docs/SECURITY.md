# ความปลอดภัย

## สิ่งที่ต้องปกป้อง

| ทรัพย์สิน | ความเสี่ยง | การป้องกันในระบบ |
|---|---|---|
| Binance API key/secret | ถูกขโมยไปเทรดหรือถอนเงิน | อยู่ใน `.env` เท่านั้น (gitignored, dockerignored, `chmod 600`), ไม่เคยถูก log หรือแสดงโดย `make doctor` |
| เงินในบัญชี | บั๊ก/การตั้งค่าผิดทำให้เทรดเงินจริงโดยไม่ตั้งใจ | ประตูความปลอดภัยหลายชั้น (ด้านล่าง), kill switch, testnet เป็นค่าเริ่มต้น |
| Telegram bot token | ปลอมข้อความ/อ่านแชท | อยู่ใน `.env`, ไม่ log URL ที่มี token เมื่อส่งไม่สำเร็จ |
| ประวัติเทรด/ยอดเงิน (`data/*.db`, `backups/`) | ข้อมูลการเงินรั่ว | gitignored, dashboard อ่านอย่างเดียวและต้องใช้ token เมื่อเปิดนอกเครื่อง |

## API key ของ Binance

ตั้งค่าบน Binance (API Management):

- ✅ **Enable Reading** และ **Enable Spot & Margin Trading** เท่านั้น
- ❌ **ปิด Enable Withdrawals** — บอทไม่ต้องใช้ ถ้า key รั่วก็ถอนเงินไม่ได้
- ❌ ปิด Futures/Margin/Universal Transfer
- ✅ **Restrict access to trusted IPs** — ใส่ IP สาธารณะของเครื่องที่รันบอท
- ✅ ใช้ **sub-account** แยกสำหรับบอท และโอนเงินเข้าเท่าที่ยอมเสียได้
- 🔁 หมุนเวียน key เป็นระยะ และทันทีถ้าสงสัยว่ารั่ว (ลบ key บน Binance → สร้างใหม่ → แก้ `.env` → `make restart`)

Testnet key (https://testnet.binance.vision) แยกจาก key จริงโดยสิ้นเชิง

<a id="real-money-gates"></a>
## ประตูก่อนใช้เงินจริง

บอทจะส่งคำสั่งด้วยเงินจริงก็ต่อเมื่อผ่าน **ทุกข้อ**:

1. `exchange.testnet: false` ใน `config.yaml`
2. มี `BINANCE_API_KEY` และ `BINANCE_API_SECRET`
3. สั่งด้วย `--real-money` (หรือ `make live-real CONFIRM=YES_I_ACCEPT_THE_RISK`)
4. `.env` มี `BOT_CONFIRM_REAL_MONEY=YES_I_ACCEPT_THE_RISK`

ตรวจทั้งใน `run.py` (ก่อนสร้าง Runner) และใน `Runner.run()` อีกชั้น — ขาดข้อใดบอทไม่เริ่ม (exit code 2) ส่วน `make start` (tmux) ไม่รองรับเงินจริงโดยตั้งใจ

## ไฟล์และ permission

| ไฟล์ | Permission | ตั้งด้วย |
|---|---|---|
| `.env` | `600` | `make perms` |
| โฟลเดอร์โปรเจกต์ | `755` (ห้าม `777`) | `make perms` |
| `config.yaml` | `644` | `make perms` |

`.gitignore` และ `.dockerignore` กัน `.env`, `.env.*` (ยกเว้น `.env.example`), `config.yaml`, `data/`, `backups/`, `logs/`, `.venv/` — Docker image ไม่มี `.env` ข้างใน (ส่งเข้าตอนรันด้วย `env_file`)

ตรวจก่อน commit ทุกครั้ง: `git status` ต้องไม่มี `.env` หรือ `config.yaml`

## Dashboard

- **อ่านอย่างเดียว**: เปิด SQLite ด้วย `mode=ro` ไม่มี endpoint ที่ส่งคำสั่งเทรดหรือแก้สถานะ
- **bind `127.0.0.1` เป็นค่าเริ่มต้น**; bind ที่อื่นต้องมี `DASHBOARD_TOKEN` ไม่งั้นไม่ยอมเริ่ม
- Token เทียบด้วย `hmac.compare_digest` (กัน timing attack) รับทาง header `X-Dashboard-Token` หรือ query `?token=`
- Header ความปลอดภัย: CSP (`default-src 'self'`), `X-Frame-Options: DENY`, `X-Content-Type-Options: nosniff`, `Referrer-Policy: no-referrer`, `Cache-Control: no-store`
- **ไม่มี HTTPS ในตัว** — token ใน URL อาจติดใน history/log ของ proxy → เข้าจากนอกเครื่องผ่าน **SSH tunnel** หรือ **Cloudflare Tunnel + Access** เท่านั้น อย่าเปิดพอร์ตตรงสู่อินเทอร์เน็ต
- Docker เผยพอร์ตเฉพาะ `127.0.0.1:8080`
- `/healthz` ไม่ต้องใช้ token (ไม่มีข้อมูลภายใน)

## Supply chain

- Dependency มีเพดานเวอร์ชันใน `requirements.txt` และล็อกเวอร์ชันที่ผ่านเทสใน `constraints.txt` (Docker ใช้ไฟล์นี้)
- อัปเดต dependency: ติดตั้งเวอร์ชันใหม่ใน venv → `make check` → `make lock` → review diff ของ `constraints.txt`
- Container รันด้วย user ไม่ใช่ root (`bot`, uid 1000)

## Threat model สรุป

| ภัย | ผลกระทบ | สถานะ |
|---|---|---|
| `.env` ถูก commit/แชร์ | key รั่ว | ป้องกันด้วย ignore + perms; key ปิด withdrawal + IP whitelist จำกัดความเสียหาย |
| เครื่องที่รันบอทถูกเจาะ | ผู้บุกรุกใช้ key เทรดได้ | IP whitelist ไม่ช่วยกรณีนี้ — ใช้ sub-account เงินจำกัด, ปิด withdrawal |
| Dashboard เปิดสู่อินเทอร์เน็ตโดยไม่ตั้งใจ | ข้อมูลพอร์ตรั่ว | ต้องมี token เมื่อ bind นอก localhost; อ่านอย่างเดียว |
| เน็ตหลุดหลังส่งออเดอร์ | ไม้ไม่ถูกติดตาม (ไม่มี stop) | ค้นหาออเดอร์ด้วย client order id; ไม่แน่ใจ → halt + แจ้งเตือน |
| บอทหยุดทำงาน | stop ไม่ทำงาน | healthcheck, Docker restart, แจ้งเตือน Telegram |
| เทรดเงินจริงโดยไม่ตั้งใจ | ขาดทุน | ประตู 4 ชั้น, testnet เป็นค่าเริ่มต้น |

## รายงานปัญหาด้านความปลอดภัย

ถ้าพบช่องโหว่ อย่าเปิด issue สาธารณะที่มีรายละเอียด — แจ้งเจ้าของ repo โดยตรง และหมุนเวียน API key ที่อาจได้รับผลกระทบทันที
