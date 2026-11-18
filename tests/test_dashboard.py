import json
import threading
import urllib.error
import urllib.request
from http.server import ThreadingHTTPServer

import pytest

from bot.config import AppConfig, db_path_for
from bot.dashboard import build_summary, make_handler, serve
from bot.notify import NullNotifier
from bot.runner import Runner
from bot.store import Store
from tests.test_bot import synthetic
from tests.test_runner import FakeExchange


@pytest.fixture
def populated(tmp_path):
    cfg = AppConfig(db_path=str(tmp_path / "bot.db"))
    ex = FakeExchange(synthetic(1500))
    r = Runner(cfg, "paper", exchange=ex, notifier=NullNotifier())
    r.restore()
    for _ in range(1100):
        r.step(); ex.i += 1
    return cfg


def start(handler):
    httpd = ThreadingHTTPServer(("127.0.0.1", 0), handler)
    threading.Thread(target=httpd.serve_forever, daemon=True).start()
    return httpd, f"http://127.0.0.1:{httpd.server_address[1]}"


def get(url, headers=None):
    req = urllib.request.Request(url, headers=headers or {})
    with urllib.request.urlopen(req) as r:
        return r.status, r.read()


def test_db_paths():
    cfg = AppConfig(db_path="data/bot.db", testnet=True)
    assert str(db_path_for(cfg, "paper")).endswith("bot.paper.db")
    assert str(db_path_for(cfg, "live")).endswith("bot.live.testnet.db")
    assert str(db_path_for(AppConfig(testnet=False), "live")).endswith("bot.live.db")


def test_summary_contents(populated):
    s = build_summary(Store(db_path_for(populated, "paper")))
    assert s["status"] == "online"
    assert s["equity"] > 0 and s["start_equity"] > 0
    assert s["stats"]["closed_trades"] > 0
    assert s["bot"]["symbol"] == "BTC/USDT"
    assert len(Store(db_path_for(populated, "paper")).equity_series()) > 100


def test_http_endpoints(populated):
    paths = {"paper": db_path_for(populated, "paper"), "live": db_path_for(populated, "live")}
    httpd, base = start(make_handler(paths, token=None))
    try:
        code, body = get(base + "/")
        assert code == 200 and b"Trading Bot" in body
        assert json.loads(get(base + "/api/modes")[1]) == ["paper"]
        assert json.loads(get(base + "/api/summary?mode=paper")[1])["equity"] > 0
        assert len(json.loads(get(base + "/api/trades?mode=paper")[1])) > 0
        assert len(json.loads(get(base + "/api/equity?mode=paper")[1])) > 0
        with pytest.raises(urllib.error.HTTPError) as e:
            get(base + "/api/summary?mode=live")
        assert e.value.code == 404
    finally:
        httpd.shutdown()


def test_token_required(populated):
    httpd, base = start(make_handler({"paper": db_path_for(populated, "paper")}, token="s3cret"))
    try:
        with pytest.raises(urllib.error.HTTPError) as e:
            get(base + "/api/summary")
        assert e.value.code == 401
        assert get(base + "/api/summary?token=s3cret")[0] == 200
        assert get(base + "/api/summary", {"X-Dashboard-Token": "s3cret"})[0] == 200
        assert get(base + "/healthz")[0] == 200
    finally:
        httpd.shutdown()


def test_public_bind_needs_token(monkeypatch):
    monkeypatch.delenv("DASHBOARD_TOKEN", raising=False)
    with pytest.raises(PermissionError):
        serve({}, host="0.0.0.0", port=0)
