#!/usr/bin/env python3
"""Binance spot trading bot.

  python run.py backtest --days 180          # test a strategy on history
  python run.py backtest --csv data.csv      # ...or on your own OHLCV CSV
  python run.py paper                        # live prices, simulated money
  python run.py live                         # Binance TESTNET orders (exchange.testnet: true)
  python run.py live --real-money            # REAL orders (needs extra confirmation)
  python run.py status --mode paper          # position, balances, recent trades
  python run.py dashboard                    # web dashboard at http://localhost:8080
  python run.py health --mode paper          # exit 0 if the bot's heartbeat is fresh (Docker/monitoring)
  python run.py resume --mode live           # clear a kill-switch halt after checking the account
  python run.py backup --dir backups         # consistent copy of every bot database (safe while running)
"""
from __future__ import annotations

import argparse
import json
import logging
import os
import sys
from pathlib import Path

from dotenv import load_dotenv

from bot.config import check_live_allowed, load_config


class JsonFormatter(logging.Formatter):
    """JSON log formatter for production log aggregation."""

    def format(self, record: logging.LogRecord) -> str:
        payload = {
            "ts": self.formatTime(record, datefmt="%Y-%m-%dT%H:%M:%S%z"),
            "level": record.levelname,
            "logger": record.name,
            "msg": record.getMessage(),
        }
        if record.exc_info:
            payload["exc_info"] = self.formatException(record.exc_info)
        return json.dumps(payload)


def cmd_backtest(cfg, args) -> int:
    from bot.backtest import run_backtest
    from bot.data import fetch_history, load_csv
    from bot.runner import make_exchange
    from bot.strategies import build_strategy

    if not args.verbose:
        logging.getLogger("bot.engine").setLevel(logging.WARNING)
    if args.csv:
        df = load_csv(args.csv)
    else:
        df = fetch_history(make_exchange(cfg, authenticated=False), cfg.symbol, cfg.timeframe, args.days)
    strategy = build_strategy(cfg.strategy, cfg.strategy_params)
    res = run_backtest(df, strategy, cfg.risk, cfg.symbol, cfg.paper_starting_quote, cfg.fee_pct, cfg.slippage_pct)
    print(f"\n{cfg.symbol} {cfg.timeframe}  {df.index[0]} -> {df.index[-1]}  ({len(df)} candles)")
    print(f"strategy: {cfg.strategy} {cfg.strategy_params}\n")
    for k, v in res.stats.items():
        print(f"  {k:<18} {v}")
    out = Path(args.out)
    out.mkdir(parents=True, exist_ok=True)
    import pandas as pd

    pd.DataFrame(res.trades).to_csv(out / "backtest_trades.csv", index=False)
    res.equity.to_csv(out / "backtest_equity.csv")
    print(f"\n  trades -> {out / 'backtest_trades.csv'}\n  equity -> {out / 'backtest_equity.csv'}")
    return 0


def cmd_run(cfg, args, mode: str) -> int:
    from bot.runner import Runner

    if mode == "live":
        try:
            check_live_allowed(cfg, args.real_money)
        except PermissionError as exc:
            print(f"refusing to start live trading: {exc}", file=sys.stderr)
            return 2
        if not cfg.testnet:
            print("!!! REAL-MONEY MODE: orders will use real funds on Binance !!!", file=sys.stderr)
    return Runner(cfg, mode, real_money=getattr(args, "real_money", False)).run()


def cmd_health(cfg, args) -> int:
    from bot.config import db_path_for
    from bot.dashboard import heartbeat_status
    from bot.store import Store

    path = db_path_for(cfg, args.mode)
    if not path.exists():
        print(f"unhealthy: no database at {path}")
        return 1
    hb = Store(path, read_only=True).get("heartbeat") or {}
    status, age = heartbeat_status(hb)
    print(f"{status}" + (f" (heartbeat {age:.0f}s ago)" if age is not None else ""))
    return 0 if status == "online" else 1


def cmd_resume(cfg, args) -> int:
    from bot.config import db_path_for
    from bot.engine import RESUME_KEY
    from bot.store import Store

    path = db_path_for(cfg, args.mode)
    if not path.exists():
        print(f"no state yet at {path}")
        return 1
    s = Store(path)
    reason = (s.get("risk") or {}).get("halted_reason")
    if not reason:
        print("bot is not halted; nothing to do")
        return 0
    import pandas as pd

    s.put(RESUME_KEY, pd.Timestamp.now(tz="UTC").isoformat())
    print(f"resume requested (was halted: {reason}).\n"
          "A running bot applies it on its next poll; otherwise it applies on next start.")
    return 0


def cmd_status(cfg, args) -> int:
    from bot.config import db_path_for
    from bot.store import Store

    path = db_path_for(cfg, args.mode)
    if not path.exists():
        print(f"no state yet at {path}")
        return 1
    s = Store(path)
    print(json.dumps({
        "position": s.get("position"),
        "risk": s.get("risk"),
        "paper_balances": s.get("paper_balances"),
        "last_bar": s.get("last_bar"),
        "recent_trades": s.trades()[-10:],
    }, indent=2, default=str))
    return 0


def cmd_dashboard(cfg, args) -> int:
    from bot.config import DB_MODES, db_path_for
    from bot.dashboard import serve

    try:
        serve({m: db_path_for(cfg, m) for m in DB_MODES}, args.host, args.port)
    except PermissionError as exc:
        print(f"refusing to start dashboard: {exc}", file=sys.stderr)
        return 2
    return 0


def cmd_backup(cfg, args) -> int:
    import sqlite3
    import time

    from bot.config import DB_MODES

    base = Path(cfg.db_path)
    out = Path(args.dir)
    ts = time.strftime("%Y%m%d-%H%M%S")
    done = 0
    for suffix in DB_MODES.values():
        src = base.with_name(base.stem + suffix + base.suffix)
        if not src.exists():
            continue
        out.mkdir(parents=True, exist_ok=True)
        dst = out / f"{src.stem}.{ts}{src.suffix}"
        # SQLite online backup API: consistent even while the bot is writing
        s = sqlite3.connect(src.resolve().as_uri() + "?mode=ro", uri=True)
        d = sqlite3.connect(dst)
        try:
            s.backup(d)
        finally:
            d.close()
            s.close()
        print(f"  {src} -> {dst}")
        done += 1
    if not done:
        print(f"no databases found next to {base}")
        return 1
    return 0


def main(argv=None) -> int:
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("-c", "--config", default="config.yaml")
    p.add_argument("-v", "--verbose", action="store_true")
    sub = p.add_subparsers(dest="cmd", required=True)
    b = sub.add_parser("backtest")
    b.add_argument("--days", type=int, default=90)
    b.add_argument("--csv")
    b.add_argument("--out", default="reports")
    sub.add_parser("paper")
    lv = sub.add_parser("live")
    lv.add_argument("--real-money", action="store_true")
    st = sub.add_parser("status")
    st.add_argument("--mode", choices=["paper", "live"], default="paper")
    bk = sub.add_parser("backup")
    bk.add_argument("--dir", default="backups")
    for name in ("health", "resume"):
        sp = sub.add_parser(name)
        sp.add_argument("--mode", choices=["paper", "live"], default="paper")
    d = sub.add_parser("dashboard")
    d.add_argument("--host", default="127.0.0.1")
    d.add_argument("--port", type=int, default=8080)
    args = p.parse_args(argv)

    load_dotenv()
    log_format = os.getenv("LOG_FORMAT", "text").lower()
    logging.basicConfig(level=logging.DEBUG if args.verbose else logging.INFO,
                        format="%(asctime)s %(levelname)-7s %(name)s: %(message)s")
    if log_format == "json":
        for handler in logging.getLogger().handlers:
            handler.setFormatter(JsonFormatter())
    try:
        cfg = load_config(args.config)
    except (OSError, ValueError, TypeError) as exc:
        print(f"config error: {exc}", file=sys.stderr)
        return 2
    if args.cmd == "health":
        return cmd_health(cfg, args)
    if args.cmd == "resume":
        return cmd_resume(cfg, args)
    if args.cmd == "backup":
        return cmd_backup(cfg, args)
    if args.cmd == "backtest":
        return cmd_backtest(cfg, args)
    if args.cmd == "status":
        return cmd_status(cfg, args)
    if args.cmd == "dashboard":
        return cmd_dashboard(cfg, args)
    return cmd_run(cfg, args, args.cmd)


if __name__ == "__main__":
    sys.exit(main())
