"""Offline tests for the Binance TH signed-REST adapter (no network, no real orders)."""
import hashlib
import hmac
import io
import urllib.error

import ccxt
import pytest

from bot.broker import LiveBroker
from bot.th_exchange import THExchange

MARKET = {
    "symbol": "BTCTHB",
    "baseAsset": "BTC",
    "quoteAsset": "THB",
    "status": "TRADING",
    "filters": [
        {"filterType": "LOT_SIZE", "stepSize": "0.00001", "minQty": "0.00001"},
        {"filterType": "MIN_NOTIONAL", "minNotional": "5"},
        {"filterType": "PRICE_FILTER", "tickSize": "0.01"},
    ],
}


def make_exchange(**kwargs):
    return THExchange("k", "s", markets=[MARKET], **kwargs)


def test_sandbox_is_refused():
    with pytest.raises(PermissionError, match="REAL MONEY"):
        make_exchange().set_sandbox_mode(True)


def test_sign_uses_hmac_sha256():
    assert make_exchange()._sign("a=1&b=2") == hmac.new(
        b"s", b"a=1&b=2", hashlib.sha256).hexdigest()


def test_pem_secret_is_rejected_with_clear_message():
    ex = THExchange("k", "-----BEGIN PRIVATE KEY-----\nFAKE\n-----END PRIVATE KEY-----")
    with pytest.raises(NotImplementedError, match="HMAC key"):
        ex._sign("a=1")


def test_load_markets_and_precision_helpers():
    ex = make_exchange()
    market = ex.load_markets()["BTC/THB"]
    assert market["base"] == "BTC" and market["quote"] == "THB"
    assert market["limits"]["cost"]["min"] == 5
    assert ex.amount_to_precision("BTC/THB", 0.123456) == "0.12345"  # rounded DOWN to step
    assert float(ex.cost_to_precision("BTC/THB", 100.999)) <= 100.999
    with pytest.raises(ccxt.InvalidOrder):
        ex.amount_to_precision("BTC/THB", 0.000001)


def test_public_market_data_shapes(monkeypatch):
    ex = make_exchange()

    def fake(method, path, params=None, signed=False):
        if path == "/ticker/price":
            assert params == {"symbol": "BTCTHB"} and not signed
            return {"price": "1234.50"}
        if path == "/klines":
            return [[1700000000000, "1", "2", "0.5", "1.5", "10", 0, 0, 0, 0, 0, 0]]
        raise AssertionError(path)

    monkeypatch.setattr(ex, "_request", fake)
    assert ex.fetch_ticker("BTC/THB")["last"] == pytest.approx(1234.5)
    assert ex.fetch_ohlcv("BTC/THB", "15m", since=1, limit=5)[0] == [1700000000000, 1.0, 2.0, 0.5, 1.5, 10.0]


def test_request_signing_and_headers(monkeypatch):
    ex = make_exchange()
    captured = {}

    def fake_urlopen(request, timeout=None):
        captured["url"] = request.full_url
        captured["headers"] = request.headers
        return io.BytesIO(b'{"ok": true}')

    monkeypatch.setattr("urllib.request.urlopen", fake_urlopen)
    ex._request("GET", "/account", signed=True)
    assert any(k.lower() == "x-mbx-apikey" for k in captured["headers"])
    assert "signature=" in captured["url"] and "timestamp=" in captured["url"]


def test_http_401_maps_to_authentication_error(monkeypatch):
    ex = make_exchange()

    def fake_urlopen(request, timeout=None):
        raise urllib.error.HTTPError(
            request.full_url, 401, "Unauthorized", {},
            io.BytesIO(b'{"code":-2015,"msg":"Invalid API-key"}'))

    monkeypatch.setattr("urllib.request.urlopen", fake_urlopen)
    with pytest.raises(ccxt.AuthenticationError, match="-2015"):
        ex.fetch_balance()


class FakeTH(THExchange):
    """Stateful in-memory TH API for broker integration tests."""

    def __init__(self):
        super().__init__("k", "s", markets=[MARKET])
        self.base, self.quote = 0.0, 1000.0
        self.orders: dict[str, dict] = {}

    def _request(self, method, path, params=None, signed=False):
        params = params or {}
        if path == "/exchangeInfo":
            return {"symbols": [MARKET]}
        if path == "/account":
            return {"balances": [
                {"asset": "BTC", "free": str(self.base), "locked": "0"},
                {"asset": "THB", "free": str(self.quote), "locked": "0"},
            ]}
        if path == "/order" and method == "POST":
            if "quoteOrderQty" in params:
                spent = float(params["quoteOrderQty"])
                qty = spent / 1000 * 0.999
                self.quote -= spent
                self.base += qty
                side = "BUY"
            else:
                qty = float(params["quantity"])
                spent = qty * 1000
                self.base -= qty
                self.quote += spent * 0.999
                side = "SELL"
            order = {
                "orderId": str(len(self.orders) + 1),
                "clientOrderId": params.get("newClientOrderId"),
                "symbol": "BTCTHB", "side": side, "type": "MARKET",
                "origQty": str(qty), "executedQty": str(qty), "cummulativeQuoteQty": str(spent),
                "status": "FILLED", "fills": [{"commissionAsset": "THB", "commission": str(spent * 0.001)}],
            }
            self.orders[order["clientOrderId"]] = order
            return order
        if path == "/order" and method == "GET":
            return self.orders[params["origClientOrderId"]]
        raise AssertionError(path)


def test_live_broker_round_trip_through_th_adapter():
    exchange = FakeTH()
    broker = LiveBroker(exchange, "BTC/THB", settle_attempts=2, settle_delay=0,
                        lookup_attempts=2, lookup_delay=0)
    buy = broker.buy_quote(100, 1000)
    assert buy.qty > 0 and buy.quote > 0
    sell = broker.sell_qty(buy.qty, 1000)
    assert sell.qty == pytest.approx(buy.qty)
    assert exchange.quote > 0
