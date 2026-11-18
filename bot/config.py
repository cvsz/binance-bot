"""Configuration loading (YAML for settings, environment/.env for secrets)."""
from __future__ import annotations

import os
import re
from dataclasses import dataclass, field, fields
from pathlib import Path

import yaml

from .risk import RiskConfig

TIMEFRAME_RE = re.compile(r"^\d+[smhdwM]$")
SYMBOL_RE = re.compile(r"^[A-Z0-9]+/[A-Z0-9]+$")

# Unknown keys are rejected everywhere: a typo must never silently change what
# the bot does (especially exchange.testnet). `strategy.params` stays free-form
# because each strategy validates its own parameter names.
TOP_KEYS = {"symbol", "timeframe", "exchange", "strategy", "risk", "paper", "loop", "db_path"}
SECTION_KEYS = {
    "exchange": {"testnet"},
    "strategy": {"name", "params"},
    "paper": {"starting_quote", "fee_pct", "slippage_pct"},
    "loop": {"poll_seconds"},
    "risk": {f.name for f in fields(RiskConfig)},  # same names RiskConfig validates
}


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

    def __post_init__(self):
        if not SYMBOL_RE.match(self.symbol):
            raise ValueError(f"symbol must look like BASE/QUOTE (e.g. BTC/USDT), got {self.symbol!r}")
        if not TIMEFRAME_RE.match(self.timeframe):
            raise ValueError(f"timeframe must look like 1m/15m/1h/4h/1d, got {self.timeframe!r}")
        if self.paper_starting_quote <= 0:
            raise ValueError("paper.starting_quote must be > 0")
        if not 0 <= self.fee_pct < 5 or not 0 <= self.slippage_pct < 5:
            raise ValueError("paper.fee_pct and paper.slippage_pct must be in [0, 5)")
        if self.poll_seconds < 5:
            raise ValueError("poll_seconds must be >= 5 to respect exchange rate limits")
        if ".." in Path(self.db_path).parts:
            raise ValueError("db_path must not contain '..' path segments")


def _section(raw: dict, name: str) -> dict:
    val = raw.get(name)
    if val is None:
        return {}
    if not isinstance(val, dict):
        raise ValueError(f"config section '{name}' must be a mapping")
    unknown = set(val) - SECTION_KEYS[name]
    if unknown:
        raise ValueError(f"unknown {name} settings: {sorted(unknown)} (valid: {sorted(SECTION_KEYS[name])})")
    return val


def _bool(raw: dict, name: str, default: bool) -> bool:
    """Strict boolean parsing: bool('false') is True, which is never what an operator means."""
    value = raw.get(name, default)
    if isinstance(value, bool):
        return value
    if isinstance(value, str) and value.lower() in ("true", "false"):
        return value.lower() == "true"
    if isinstance(value, int) and value in (0, 1):
        return bool(value)
    raise ValueError(f"{name} must be true or false, got {value!r}")


def load_config(path: str | Path) -> AppConfig:
    p = Path(path)
    if not p.exists():
        raise FileNotFoundError(f"{p} not found - copy config.example.yaml to {p.name} first")
    raw = yaml.safe_load(p.read_text(encoding="utf-8")) or {}
    if not isinstance(raw, dict):
        raise ValueError(f"{p} must contain a YAML mapping")
    unknown = set(raw) - TOP_KEYS
    if unknown:
        raise ValueError(f"unknown config keys: {sorted(unknown)} (valid: {sorted(TOP_KEYS)})")
    ex, strat, paper, loop = (_section(raw, n) for n in ("exchange", "strategy", "paper", "loop"))
    return AppConfig(
        symbol=str(raw.get("symbol", "BTC/USDT")).upper(),
        timeframe=str(raw.get("timeframe", "15m")),
        testnet=_bool(ex, "testnet", True),
        strategy=strat.get("name", "ema_cross"),
        strategy_params=strat.get("params") or {},
        risk=RiskConfig.from_dict(_section(raw, "risk")),
        paper_starting_quote=float(paper.get("starting_quote", 1000)),
        fee_pct=float(paper.get("fee_pct", 0.1)),
        slippage_pct=float(paper.get("slippage_pct", 0.05)),
        poll_seconds=int(loop.get("poll_seconds", 30)),
        db_path=str(raw.get("db_path", "data/bot.db")),
    )


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
