"""Configuration loading (YAML for settings, environment/.env for secrets)."""
from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path

import yaml

from .risk import RiskConfig


@dataclass
class AppConfig:
    symbol: str = "BTC/USDT"
    timeframe: str = "15m"
    testnet: bool = True
    strategy: str = "ema_cross"
    strategy_params: dict = field(default_factory=dict)
    risk: RiskConfig = field(default_factory=RiskConfig)
    paper_starting_quote: float = 1000.0
    fee_pct: float = 0.1
    slippage_pct: float = 0.05
    poll_seconds: int = 30
    db_path: str = "data/bot.db"


def load_config(path: str | Path) -> AppConfig:
    raw = yaml.safe_load(Path(path).read_text(encoding="utf-8")) or {}
    ex = raw.get("exchange", {})
    strat = raw.get("strategy", {})
    paper = raw.get("paper", {})
    loop = raw.get("loop", {})
    cfg = AppConfig(
        symbol=raw.get("symbol", "BTC/USDT"),
        timeframe=raw.get("timeframe", "15m"),
        testnet=bool(ex.get("testnet", True)),
        strategy=strat.get("name", "ema_cross"),
        strategy_params=strat.get("params", {}) or {},
        risk=RiskConfig(**(raw.get("risk", {}) or {})),
        paper_starting_quote=float(paper.get("starting_quote", 1000)),
        fee_pct=float(paper.get("fee_pct", 0.1)),
        slippage_pct=float(paper.get("slippage_pct", 0.05)),
        poll_seconds=int(loop.get("poll_seconds", 30)),
        db_path=raw.get("db_path", "data/bot.db"),
    )
    if cfg.poll_seconds < 5:
        raise ValueError("poll_seconds must be >= 5 to respect exchange rate limits")
    return cfg


DB_MODES = {"paper": ".paper", "live-testnet": ".live.testnet", "live": ".live"}


def db_path_for(cfg: AppConfig, mode: str) -> Path:
    """mode: 'paper' | 'live' (resolved to live-testnet when cfg.testnet) | 'live-testnet'."""
    if mode == "live" and cfg.testnet:
        mode = "live-testnet"
    p = Path(cfg.db_path)
    return p.with_name(p.stem + DB_MODES[mode] + p.suffix)


def api_keys(testnet: bool) -> tuple[str | None, str | None]:
    prefix = "BINANCE_TESTNET_" if testnet else "BINANCE_"
    return os.getenv(prefix + "API_KEY"), os.getenv(prefix + "API_SECRET")


REAL_MONEY_ENV = "BOT_CONFIRM_REAL_MONEY"
REAL_MONEY_VALUE = "YES_I_ACCEPT_THE_RISK"


def check_live_allowed(cfg: AppConfig, real_money_flag: bool) -> None:
    """Raise unless every safety gate for live trading is satisfied."""
    key, secret = api_keys(cfg.testnet)
    if not key or not secret:
        which = "BINANCE_TESTNET_API_KEY/SECRET" if cfg.testnet else "BINANCE_API_KEY/SECRET"
        raise PermissionError(f"live mode needs {which} in the environment or .env")
    if cfg.testnet:
        return
    if not real_money_flag:
        raise PermissionError("exchange.testnet is false: add --real-money to trade with real funds")
    if os.getenv(REAL_MONEY_ENV) != REAL_MONEY_VALUE:
        raise PermissionError(f"set {REAL_MONEY_ENV}={REAL_MONEY_VALUE} to confirm real-money trading")
