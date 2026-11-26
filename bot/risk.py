"""Position sizing, stop/take-profit levels and account-level kill switches.

Enhanced with zksato-inspired trailing stop types (percentage / ATR / fixed)
and activation price, plus a TrailingStopConfig/TrailingStopState model.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass, fields
from enum import StrEnum

DAILY_PREFIX = "daily"


class TrailingStopType(StrEnum):
    """Trailing stop calculation methods."""

    PERCENTAGE = "percentage"
    ATR = "atr"
    FIXED = "fixed"


@dataclass(frozen=True, slots=True)
class TrailingStopConfig:
    """Configuration for a trailing stop."""

    stop_type: TrailingStopType = TrailingStopType.PERCENTAGE
    percentage: float = 2.0  # % below peak for long positions
    atr_multiplier: float = 2.0  # multiplier applied to ATR value
    atr_period: int = 14  # ATR lookback period
    fixed_amount: float | None = None  # fixed quote amount below peak
    activation_price: float | None = None  # price at which trailing activates


@dataclass(frozen=True, slots=True)
class TrailingStopState:
    """Current state of a trailing stop for a position."""

    symbol: str
    config: TrailingStopConfig
    highest_price: float = 0.0  # highest price seen since entry (long)
    lowest_price: float = 0.0  # lowest price seen since entry (short)
    stop_price: float = 0.0  # current stop price
    activated: bool = False  # whether trailing is active


@dataclass
class RiskConfig:
    risk_per_trade_pct: float = 1.0  # % of equity lost if the stop is hit
    stop_loss_pct: float = 2.0  # stop distance from entry
    take_profit_pct: float | None = 4.0
    trailing_stop_pct: float | None = None
    trailing_stop_type: str = "percentage"  # percentage | atr | fixed
    trailing_stop_atr_multiplier: float = 2.0
    trailing_stop_atr_period: int = 14
    trailing_stop_fixed_amount: float | None = None
    trailing_stop_activation_price: float | None = None
    max_position_pct: float = 25.0  # cap on % of equity in one position
    max_daily_loss_pct: float = 3.0  # stop opening trades after this daily drawdown
    max_trades_per_day: int = 10
    cooldown_bars: int = 2  # bars to wait after an exit
    # stop opening trades (until `run.py resume`) once equity falls this far below its peak
    max_drawdown_halt_pct: float | None = None

    def __post_init__(self):
        if self.stop_loss_pct <= 0 or self.stop_loss_pct >= 100:
            raise ValueError("stop_loss_pct must be in (0, 100) (a stop is mandatory)")
        if not 0 < self.risk_per_trade_pct <= 5:
            raise ValueError("risk_per_trade_pct must be in (0, 5]")
        if not 0 < self.max_position_pct <= 100:
            raise ValueError("max_position_pct must be in (0, 100]")
        if self.take_profit_pct is not None and self.take_profit_pct <= 0:
            raise ValueError("take_profit_pct must be > 0 or null")
        if self.trailing_stop_pct is not None and not 0 < self.trailing_stop_pct < 100:
            raise ValueError("trailing_stop_pct must be in (0, 100) or null")
        if self.trailing_stop_type not in ("percentage", "atr", "fixed"):
            raise ValueError("trailing_stop_type must be 'percentage', 'atr', or 'fixed'")
        if not 0 < self.trailing_stop_atr_multiplier <= 10:
            raise ValueError("trailing_stop_atr_multiplier must be in (0, 10]")
        if int(self.trailing_stop_atr_period) < 1:
            raise ValueError("trailing_stop_atr_period must be >= 1")
        if self.trailing_stop_fixed_amount is not None and self.trailing_stop_fixed_amount <= 0:
            raise ValueError("trailing_stop_fixed_amount must be > 0 or null")
        if self.trailing_stop_activation_price is not None and self.trailing_stop_activation_price <= 0:
            raise ValueError("trailing_stop_activation_price must be > 0 or null")
        if not 0 < self.max_daily_loss_pct <= 100:
            raise ValueError("max_daily_loss_pct must be in (0, 100]")
        if self.max_drawdown_halt_pct is not None and not 0 < self.max_drawdown_halt_pct <= 100:
            raise ValueError("max_drawdown_halt_pct must be in (0, 100] or null")
        if int(self.max_trades_per_day) < 1:
            raise ValueError("max_trades_per_day must be >= 1")
        if int(self.cooldown_bars) < 0:
            raise ValueError("cooldown_bars must be >= 0")

    @classmethod
    def from_dict(cls, raw: dict | None) -> RiskConfig:
        raw = raw or {}
        known = {f.name for f in fields(cls)}
        unknown = set(raw) - known
        if unknown:
            raise ValueError(f"unknown risk settings: {sorted(unknown)} (valid: {sorted(known)})")
        return cls(**raw)


@dataclass
class Position:
    qty: float
    entry_price: float
    cost_quote: float  # quote spent including fees
    stop: float
    take: float | None
    peak: float
    opened_at: str
    pending_order_id: str | None = None  # client id of a sell whose result is unconfirmed
    # Server-side order IDs for exchange-managed stop-loss / take-profit (OCO)
    stop_order_id: str | None = None  # server-side stop-loss order id
    take_order_id: str | None = None  # server-side take-profit order id


@dataclass
class RiskState:
    day: str | None = None
    day_start_equity: float = 0.0
    trades_today: int = 0
    last_exit_bar: int | None = None
    halted_reason: str | None = None
    peak_equity: float = 0.0

    @classmethod
    def from_dict(cls, raw: dict | None) -> RiskState:
        known = {f.name for f in fields(cls)}
        return cls(**{k: v for k, v in (raw or {}).items() if k in known})


class RiskManager:
    def __init__(self, cfg: RiskConfig, state: RiskState | None = None):
        self.cfg = cfg
        self.state = state or RiskState()

    # ---- sizing / levels -------------------------------------------------
    def position_size_quote(self, equity: float, free_quote: float) -> float:
        by_risk = equity * (self.cfg.risk_per_trade_pct / 100) / (self.cfg.stop_loss_pct / 100)
        cap = equity * self.cfg.max_position_pct / 100
        return max(0.0, min(by_risk, cap, free_quote))

    def levels(self, entry: float) -> tuple[float, float | None]:
        stop = entry * (1 - self.cfg.stop_loss_pct / 100)
        take = entry * (1 + self.cfg.take_profit_pct / 100) if self.cfg.take_profit_pct else None
        return stop, take

    def update_trailing(self, pos: Position, high: float, atr_value: float | None = None) -> None:
        """Update trailing stop for ``pos`` using the configured stop type.

        ``atr_value`` is required when ``trailing_stop_type == "atr"``.
        Activation price (if set) gates when trailing begins.
        """
        cfg = self.cfg
        pos.peak = max(pos.peak, high)

        # Determine if trailing is activated
        activated = True
        if cfg.trailing_stop_activation_price is not None and high < cfg.trailing_stop_activation_price:
            activated = False

        if not activated:
            return

        stop_type = cfg.trailing_stop_type
        if stop_type == "percentage" and cfg.trailing_stop_pct:
            new_stop = pos.peak * (1 - cfg.trailing_stop_pct / 100)
            pos.stop = max(pos.stop, new_stop)
        elif stop_type == "atr" and atr_value is not None:
            new_stop = pos.peak - (cfg.trailing_stop_atr_multiplier * atr_value)
            pos.stop = max(pos.stop, new_stop)
        elif stop_type == "fixed" and cfg.trailing_stop_fixed_amount is not None:
            new_stop = pos.peak - cfg.trailing_stop_fixed_amount
            pos.stop = max(pos.stop, new_stop)

    # ---- account guards --------------------------------------------------
    def roll_day(self, day: str, equity: float) -> None:
        if self.state.day != day:
            self.state.day = day
            self.state.day_start_equity = equity
            self.state.trades_today = 0
            if self.state.halted_reason and self.state.halted_reason.startswith(DAILY_PREFIX):
                self.state.halted_reason = None

    def observe_equity(self, equity: float) -> None:
        """Track peak equity and trip the max-drawdown kill switch."""
        s = self.state
        s.peak_equity = max(s.peak_equity, equity)
        lim = self.cfg.max_drawdown_halt_pct
        if lim and s.peak_equity > 0 and not s.halted_reason:
            dd = (s.peak_equity - equity) / s.peak_equity * 100
            if dd >= lim:
                s.halted_reason = f"max drawdown {dd:.2f}% >= {lim}% from peak {s.peak_equity:.2f}"

    def halt(self, reason: str) -> None:
        """Manual/fatal halt: only cleared by resume()."""
        self.state.halted_reason = reason

    def resume(self, equity: float | None = None) -> str | None:
        """Clear any halt. Re-bases the drawdown peak so the halt doesn't immediately re-trip."""
        prev = self.state.halted_reason
        self.state.halted_reason = None
        if equity is not None:
            self.state.peak_equity = equity
        return prev

    def can_enter(self, equity: float, bar_index: int) -> tuple[bool, str]:
        s = self.state
        if s.halted_reason:
            return False, s.halted_reason
        if s.day_start_equity > 0:
            dd = (s.day_start_equity - equity) / s.day_start_equity * 100
            if dd >= self.cfg.max_daily_loss_pct:
                s.halted_reason = f"{DAILY_PREFIX} loss {dd:.2f}% >= {self.cfg.max_daily_loss_pct}%"
                return False, s.halted_reason
        if s.trades_today >= self.cfg.max_trades_per_day:
            return False, "max trades per day reached"
        if s.last_exit_bar is not None and bar_index - s.last_exit_bar < self.cfg.cooldown_bars:
            return False, "cooldown"
        return True, "ok"

    def record_entry(self) -> None:
        self.state.trades_today += 1

    def record_exit(self, bar_index: int) -> None:
        self.state.last_exit_bar = bar_index

    def state_dict(self) -> dict:
        return asdict(self.state)


__all__ = [
    "TrailingStopType",
    "TrailingStopConfig",
    "TrailingStopState",
    "RiskConfig",
    "Position",
    "RiskState",
    "RiskManager",
    "DAILY_PREFIX",
]
