#!/usr/bin/env python3
"""Binance spot trading bot.

  python run.py backtest --days 180          # test a strategy on history
  python run.py backtest --csv data.csv      # ...or on your own OHLCV CSV
  python run.py paper                        # live prices, simulated money
  python run.py live                         # Binance TESTNET orders (exchange.testnet: true)
  python run.py live --real-money            # REAL orders (needs extra confirmation)
  python run.py status --mode paper          # position, balances, recent trades
  python run.py dashboard                    # web dashboard at http://localhost:8080
"""
from __future__ import annotations

import argparse
import json
import logging
import sys
from pathlib import Path

from dotenv import load_dotenv

from bot.config import check_live_allowed, load_config


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
    Runner(cfg, mode).run()
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
    d = sub.add_parser("dashboard")
    d.add_argument("--host", default="127.0.0.1")
    d.add_argument("--port", type=int, default=8080)
    args = p.parse_args(argv)

    load_dotenv()
    logging.basicConfig(level=logging.DEBUG if args.verbose else logging.INFO,
                        format="%(asctime)s %(levelname)-7s %(name)s: %(message)s")
    cfg = load_config(args.config)
    if args.cmd == "backtest":
        return cmd_backtest(cfg, args)
    if args.cmd == "status":
        return cmd_status(cfg, args)
    if args.cmd == "dashboard":
        return cmd_dashboard(cfg, args)
    return cmd_run(cfg, args, args.cmd)


if __name__ == "__main__":
    sys.exit(main())
