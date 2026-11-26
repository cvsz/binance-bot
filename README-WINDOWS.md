# Binance Spot Trading Bot — Windows 11

Run the bot on Windows with a local Python installation. No Docker required.

## 1. Requirements

- Python 3.12+ (https://www.python.org) — add to PATH during install
- Git (optional, for cloning)
- PowerShell (built into Windows 11)

## 2. First-time setup

```powershell
# Clone or unzip this project, then:
.\setup-windows.ps1
```

This creates `.venv`, installs pinned dependencies (`requirements.txt` + `constraints.txt`), and copies `config.example.yaml` → `config.yaml` and `.env.example` → `.env`.

## 3. Configure

- Edit `.env` and add your API keys/secrets (never commit this file).
- Edit `config.yaml` if you want a different symbol/timeframe/venue.

### Venue (`exchange.name`)

- `binance` — Binance global Spot (default)
- `binanceus` — Binance.US Spot
- `binanceth` — Binance TH Spot (**เงินจริงเท่านั้น**, ไม่มี testnet)

### Real-money gates (all must be true)

1. `exchange.testnet: false`
2. `BINANCE_API_KEY` / `BINANCE_API_SECRET` set in `.env`
3. Run with `--real-money`
4. `BOT_CONFIRM_REAL_MONEY=YES_I_ACCEPT_THE_RISK` in `.env`

Without all four, the bot refuses to start.

## 4. Run

### Interactive (PowerShell)

```powershell
.\setup-windows.ps1          # first time only
.\run.bat paper              # paper trading (live prices, simulated money)
.\run.bat live               # testnet (testnet: true in config.yaml)
.\run.bat live --real-money  # REAL MONEY (only if all gates pass)
.\run.bat dashboard          # web dashboard at http://localhost:8080
.\run.bat backtest --days 180
.\run.bat status --mode paper
.\run.bat health --mode live
.\run.bat resume --mode live
.\run.bat backup --dir backups
```

### Non-interactive / scheduled

```powershell
.\run.bat paper
```

`run.bat` passes all arguments through to `run.py`. See `docs/CLI.md` for the full command reference.

## 5. Stop

Press `Ctrl+C` in the terminal. The bot saves state and exits cleanly.

Or use Task Scheduler to run `run.bat paper` on login for 24/7 operation.

## 6. Backtest with public data

```powershell
python scripts/fetch_public_data.py --symbol BTCUSDT --interval 15m --days 365
python run.py backtest --csv reports/public_BTCUSDT_15m.csv
```

## 7. Uninstall

Delete the folder. Optionally remove `%USERPROFILE%\.binance-bot` if you created one. No registry changes are made.

## 8. Professional Installer (Inno Setup)

For a traditional Windows `.exe` installer with Start Menu shortcuts and
Add/Remove Programs entry, compile `installer/setup-windows.iss` using
[Inno Setup Compiler](https://jrsoftware.org/isinfo.php) (free, Windows only):

```powershell
# On Windows, after installing Inno Setup Compiler:
iscc installer/setup-windows.iss
```

This produces `binance-bot-windows-setup-1.0.0.exe` in `reports/release/`,
which includes:
- Start Menu shortcut
- Optional desktop icon
- Uninstaller via Add/Remove Programs
- Pre-install safety warning about real-money trading

---

## Safety

- **Stop-loss is bot-side** — if this Windows machine sleeps or loses network, stops do **not** run on Binance.
- **Dashboard binds to `0.0.0.0:8080` by default** — set `DASHBOARD_TOKEN` for remote access; use SSH tunnel or Cloudflare Tunnel for additional security.
- **Never commit `.env`, `config.yaml`, or `data/*.db` to git.**

## Safety

- Stop-loss is **bot-side** — if this Windows machine sleeps or loses network, stops do **not** run on Binance.
- Dashboard is **read-only** and binds to `0.0.0.0` by default.
- Never commit `.env`, `config.yaml`, or `data/*.db` to git.
