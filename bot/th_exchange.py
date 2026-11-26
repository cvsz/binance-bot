"""Minimal signed-REST adapter for Binance TH (https://api.binance.th/api/v1).

TH has no public testnet and ccxt has no `binanceth` class, so this shim exposes
only the ccxt-shaped methods this bot actually uses. It lets the existing
``LiveBroker`` and ``Runner`` work unchanged; no strategy/risk logic is duplicated.
"""

from __future__ import annotations

import hashlib
import hmac
import json
import math
import logging
import time
import urllib.error
import urllib.parse
import urllib.request
from typing import Any

import ccxt

log = logging.getLogger(__name__)

BASE_URL = "https://api.binance.th"
API_PREFIX = "/api/v1"
RECV_WINDOW = 10_000

STATUS_MAP = {
    "NEW": "open",
    "PARTIALLY_FILLED": "open",
    "FILLED": "closed",
    "CANCELED": "canceled",
    "CANCELLED": "canceled",
    "REJECTED": "rejected",
    "EXPIRED": "expired",
}

AUTH_CODES = {-2014, -2015, -2010, -1022}  # invalid key / signature / permissions


class THExchange:
    """ccxt-shaped adapter for Binance TH spot (real money only)."""

    id = "binanceth"
    name = "Binance TH"
    rateLimit = 1000

    def __init__(
        self,
        api_key: str | None,
        api_secret: str | None,
        base_url: str = BASE_URL,
        markets: list[dict] | None = None,
        clock_offset_ms: int = 0,
    ):
        self.apiKey, self.secret = api_key, api_secret
        self.base_url = base_url.rstrip("/")
        self.markets: dict[str, dict] = {}
        self._clock_offset_ms = clock_offset_ms
        self._markets_override = markets
        self._loaded = False
        self._clock_offset_ms = self._sync_clock_offset()

    # ---- credential / sandbox gates -------------------------------------
    def set_sandbox_mode(self, enabled: bool) -> None:
        if enabled:
            raise PermissionError("Binance TH has no testnet/sandbox: every order uses REAL MONEY")

    def _server_time(self) -> int:
        """Fetch server time in ms from TH exchange. Raises on failure."""
        payload = self._request_unsigned("GET", "/time")
        return int(payload["serverTime"])

    def _request_unsigned(self, method: str, path: str, params: dict | None = None) -> Any:
        """Unsigned request (no signature, no API key header)."""
        values = {k: v for k, v in (params or {}).items() if v is not None}
        query = urllib.parse.urlencode(values)
        url = f"{self.base_url}{API_PREFIX}{path}" + (f"?{query}" if query else "")
        request = urllib.request.Request(url, headers={"User-Agent": "binance-bot-th/1.0"})  # noqa: S310
        with urllib.request.urlopen(request, timeout=10) as response:  # noqa: S310
            return json.loads(response.read().decode("utf-8"))

    def _sync_clock_offset(self) -> int:
        """Compute server_ms - local_ms so timestamps match Binance TH server time."""
        try:
            server_ms = self._server_time()
            local_ms = int(time.time() * 1000)
            return server_ms - local_ms
        except Exception as exc:  # keep running; signed requests will surface their own error
            log.warning("could not sync TH server time (%s); using offset 0", exc)
            return 0

    def check_required_credentials(self) -> None:
        if not self.apiKey or not self.secret:
            raise ccxt.AuthenticationError("Binance TH needs BINANCE_TH_API_KEY/SECRET")

    # ---- low-level request / signing -------------------------------------
    def milliseconds(self) -> int:
        return int(time.time() * 1000) + self._clock_offset_ms

    def _sign(self, query: str) -> str:
        self.check_required_credentials()
        if self.secret is None:
            raise ccxt.AuthenticationError("Binance TH secret is required")
        if "PRIVATE KEY" in self.secret:
            raise NotImplementedError(
                "Binance TH RSA/Ed25519 keys are not supported by this adapter yet; use an HMAC key"
            )
        return hmac.new(self.secret.encode(), query.encode(), hashlib.sha256).hexdigest()

    def _request(self, method: str, path: str, params: dict | None = None, *, signed: bool = False) -> Any:
        values = {k: v for k, v in (params or {}).items() if v is not None}
        if signed:
            self.check_required_credentials()
            values["timestamp"] = self.milliseconds()
            values["recvWindow"] = RECV_WINDOW
        query = urllib.parse.urlencode(values)
        if signed:
            query += "&signature=" + self._sign(query)
        headers = {"User-Agent": "binance-bot-th/1.0"}
        data = None
        if signed:
            if self.apiKey is None:
                raise ccxt.AuthenticationError("Binance TH API key is required")
            headers["X-MBX-APIKEY"] = self.apiKey
        if method == "GET":
            url = f"{self.base_url}{API_PREFIX}{path}" + (f"?{query}" if query else "")
        else:
            url = f"{self.base_url}{API_PREFIX}{path}"
            data = query.encode()
            headers["Content-Type"] = "application/x-www-form-urlencoded"
        request = urllib.request.Request(url, data=data, headers=headers, method=method)  # noqa: S310
        try:
            with urllib.request.urlopen(request, timeout=10) as response:  # noqa: S310
                return json.loads(response.read().decode("utf-8"))
        except urllib.error.HTTPError as exc:
            body = exc.read().decode("utf-8", errors="replace")
            try:
                payload = json.loads(body)
                code, message = int(payload.get("code", 0)), str(payload.get("msg", body))
            except (ValueError, TypeError):
                code, message = 0, body
            if exc.code == 401 or code in AUTH_CODES:
                raise ccxt.AuthenticationError(f"binanceth {code}: {message}") from exc
            raise ccxt.ExchangeError(f"binanceth {code}: {message}") from exc
        except urllib.error.URLError as exc:
            raise ccxt.NetworkError(f"binanceth network error: {exc.reason}") from exc

    # ---- market metadata --------------------------------------------------
    @staticmethod
    def _native(symbol: str) -> str:
        return symbol.replace("/", "").upper()

    @staticmethod
    def _common(symbol: str) -> str:
        return f"{symbol[:3]}/{symbol[3:]}" if "/" not in symbol else symbol

    def load_markets(self) -> dict[str, dict]:
        if self._loaded:
            return self.markets
        if self._markets_override is not None:
            symbols = self._markets_override
        else:
            payload = self._request("GET", "/exchangeInfo")
            symbols = payload.get("symbols", [])
        for item in symbols:
            if item.get("status") not in (None, "TRADING"):
                continue
            filters = {f.get("filterType"): f for f in item.get("filters", [])}
            lot = filters.get("LOT_SIZE") or {}
            notional = filters.get("MIN_NOTIONAL") or filters.get("NOTIONAL") or {}
            price = filters.get("PRICE_FILTER") or {}
            common = f"{item['baseAsset']}/{item['quoteAsset']}"
            step = float(lot.get("stepSize") or 1e-8)
            tick = float(price.get("tickSize") or 1e-8)
            self.markets[common] = {
                "spot": True,
                "base": item["baseAsset"],
                "quote": item["quoteAsset"],
                "symbol": common,
                "limits": {
                    "cost": {"min": float(notional.get("minNotional") or 5)},
                    "amount": {"min": float(lot.get("minQty") or 0)},
                },
                "precision": {"amount": step, "price": tick},
                "native": item.get("symbol", self._native(common)),
            }
        self._loaded = True
        return self.markets

    @staticmethod
    def _round_down(value: float, step: float) -> str:
        if step <= 0:
            return str(value)
        decimals = max(0, -int(math.log10(step)))
        rounded = int(value / step) * step
        return f"{rounded:.{decimals}f}"

    def cost_to_precision(self, symbol: str, cost: float) -> str:
        return self._round_down(cost, float(self.markets[symbol]["limits"]["cost"].get("step") or 0.01))

    def amount_to_precision(self, symbol: str, amount: float) -> str:
        step = float(self.markets[symbol]["precision"]["amount"])
        rounded = float(self._round_down(amount, step))
        if rounded <= 0:
            raise ccxt.InvalidOrder("amount must be greater than the minimum step")
        return f"{rounded:.8f}".rstrip("0").rstrip(".")

    def parse_timeframe(self, timeframe: str) -> int:
        units = {"m": 60, "h": 3600, "d": 86400, "w": 604800}
        return int(timeframe[:-1]) * units[timeframe[-1]]

    # ---- public market data ----------------------------------------------
    def fetch_ticker(self, symbol: str) -> dict:
        payload = self._request("GET", "/ticker/price", {"symbol": self._native(symbol)})
        return {"symbol": symbol, "last": float(payload["price"])}

    def fetch_ohlcv(self, symbol: str, timeframe: str, since: int | None = None, limit: int = 500) -> list[list]:
        params: dict[str, Any] = {"symbol": self._native(symbol), "interval": timeframe, "limit": limit}
        if since is not None:
            params["startTime"] = int(since)
        rows = self._request("GET", "/klines", params)
        return [[int(row[0]), *(float(value) for value in row[1:6])] for row in rows]

    # ---- account / orders -------------------------------------------------
    def fetch_balance(self) -> dict:
        payload = self._request("GET", "/account", signed=True)
        free: dict[str, float] = {}
        total: dict[str, float] = {}
        for row in payload.get("balances", []):
            asset = row["asset"]
            free[asset] = float(row.get("free") or 0)
            total[asset] = float(row.get("free") or 0) + float(row.get("locked") or 0)
        return {"free": free, "total": total}

    def _create_order(self, side: str, symbol: str, params: dict) -> dict:
        payload = self._request(
            "POST",
            "/order",
            {
                "symbol": self._native(symbol),
                "side": side,
                "type": "MARKET",
                **params,
            },
            signed=True,
        )
        return self._map_order(payload)

    def create_market_buy_order_with_cost(self, symbol: str, cost: float, params: dict | None = None) -> dict:
        return self._create_order("BUY", symbol, {"quoteOrderQty": cost, **(params or {})})

    def create_market_sell_order(self, symbol: str, amount: float, params: dict | None = None) -> dict:
        return self._create_order("SELL", symbol, {"quantity": amount, **(params or {})})

    def fetch_order(self, order_id: str, symbol: str | None = None, params: dict | None = None) -> dict:
        query: dict[str, Any] = {}
        client_id = (params or {}).get("clientOrderId")
        if client_id:
            query["origClientOrderId"] = client_id
        elif order_id:
            query["orderId"] = order_id
        else:
            raise ccxt.OrderNotFound("fetch_order needs order id or clientOrderId")
        if symbol:
            query["symbol"] = self._native(symbol)
        try:
            payload = self._request("GET", "/order", query, signed=True)
        except ccxt.ExchangeError as exc:
            if "-2013" in str(exc):
                raise ccxt.OrderNotFound(str(exc)) from exc
            raise
        return self._map_order(payload)

    @staticmethod
    def _map_order(payload: dict) -> dict:
        filled = float(payload.get("executedQty") or 0)
        cost = float(payload.get("cummulativeQuoteQty") or 0)
        fees = [
            {"currency": fill.get("commissionAsset"), "cost": float(fill.get("commission") or 0)}
            for fill in payload.get("fills", [])
            if fill.get("commissionAsset")
        ]
        return {
            "id": str(payload.get("orderId", "")),
            "clientOrderId": payload.get("clientOrderId"),
            "symbol": payload.get("symbol", ""),
            "side": str(payload.get("side", "BUY")).lower(),
            "type": str(payload.get("type", "MARKET")).lower(),
            "amount": float(payload.get("origQty") or filled),
            "filled": filled,
            "cost": cost,
            "average": cost / filled if filled else 0.0,
            "status": STATUS_MAP.get(str(payload.get("status", "NEW")), "open"),
            "fees": fees,
        }
