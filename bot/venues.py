"""Exchange venue registry.

A venue is a ccxt exchange class plus the matching API-key environment prefix.
The registry is deliberately small: only venues whose order API this bot has
actually been written against are accepted. Pattern inspired by zksato's
per-exchange credential handling (MIT, github.com/cvsz/zksato), adapted to the
single-pair sync architecture here.
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class Venue:
    id: str
    ccxt_id: str
    key_prefix: str
    label: str
    supports_testnet: bool = True
    note: str = ""
    # Alternative env-var prefixes accepted for the same venue (e.g. BINANCE_US_).
    # The first prefix with BOTH key and secret set wins.
    aliases: tuple[str, ...] = ()
    # Custom (non-ccxt) exchange adapter, when ccxt has no class for the venue.
    custom: str | None = None


VENUES: dict[str, Venue] = {
    "binance": Venue("binance", "binance", "BINANCE", "Binance global (spot)", aliases=("BINANCE", "BINANCE_TH")),
    "binanceus": Venue("binanceus", "binanceus", "BINANCEUS", "Binance.US (spot)", aliases=("BINANCEUS", "BINANCE_US")),
    # ccxt has no `binanceth` class and TH uses /api/v1 (not /api/v3), so this
    # venue uses a dedicated signed-REST adapter bot/th_exchange.py.
    # TH has NO public testnet: every order is REAL MONEY.
    "binanceth": Venue(
        "binanceth",
        "",
        "BINANCETH",
        "Binance TH (THB, real money only)",
        supports_testnet=False,
        aliases=("BINANCETH", "BINANCE_TH"),
        custom="THExchange",
        note="real money only; no testnet; uses bot/th_exchange.py",
    ),
}

DEFAULT_VENUE = "binance"


def get_venue(name: str) -> Venue:
    """Look up a venue by config id, with an actionable error for unsupported ones."""
    venue = VENUES.get(str(name).strip().lower())
    if venue is None:
        raise ValueError(f"unknown exchange.name {name!r} (valid: {', '.join(sorted(VENUES))})")
    if not venue.ccxt_id and not venue.custom:
        raise ValueError(f"exchange.name={venue.id} is not supported: {venue.note}")
    return venue
