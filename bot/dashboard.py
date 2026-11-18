"""Read-only web dashboard for a running bot (stdlib only, no extra dependencies).

It only reads the bot's SQLite database, so it can run in a separate process or
container and can never place or cancel orders.
"""
from __future__ import annotations

import hmac
import json
import logging
import os
from datetime import datetime, timezone
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlparse

from .store import Store

log = logging.getLogger(__name__)
LOOPBACK = {"127.0.0.1", "localhost", "::1"}


def build_summary(store: Store) -> dict:
    hb = store.get("heartbeat") or {}
    pos = store.get("position")
    risk = store.get("risk") or {}
    trades = store.trades()
    sells = [t for t in trades if t["side"] == "sell" and t["pnl_quote"] is not None]
    pnls = [t["pnl_quote"] for t in sells]
    wins = [p for p in pnls if p > 0]
    losses = [p for p in pnls if p <= 0]

    age = None
    if hb.get("ts"):
        age = (datetime.now(timezone.utc) - datetime.fromisoformat(hb["ts"])).total_seconds()
    poll = hb.get("poll_seconds") or 30
    status = "offline" if age is None else ("online" if age < max(3 * poll, 90) else "stale")

    price = hb.get("price")
    if pos and price:
        pos = dict(pos)
        value = pos["qty"] * price
        pos["unrealized_pnl"] = value - pos["cost_quote"]
        pos["unrealized_pct"] = (value / pos["cost_quote"] - 1) * 100 if pos["cost_quote"] else 0.0

    start = hb.get("start_equity")
    equity = hb.get("equity")
    return {
        "status": status,
        "heartbeat_age_s": round(age, 1) if age is not None else None,
        "bot": {k: hb.get(k) for k in ("mode", "symbol", "timeframe", "strategy", "ts")},
        "price": price,
        "equity": equity,
        "start_equity": start,
        "total_return_pct": round((equity / start - 1) * 100, 2) if equity and start else None,
        "balances": {"base": hb.get("base"), "quote": hb.get("quote")},
        "position": pos,
        "risk": risk,
        "stats": {
            "closed_trades": len(sells),
            "realized_pnl": round(sum(pnls), 4),
            "win_rate_pct": round(len(wins) / len(sells) * 100, 1) if sells else None,
            "profit_factor": round(sum(wins) / abs(sum(losses)), 2) if losses and sum(losses) else None,
            "best_trade": round(max(pnls), 4) if pnls else None,
            "worst_trade": round(min(pnls), 4) if pnls else None,
        },
    }


def make_handler(db_paths: dict[str, Path], token: str | None):
    html = (Path(__file__).parent / "dashboard.html").read_bytes()
    stores: dict[str, Store] = {}

    def store_for(mode: str) -> Store | None:
        path = db_paths.get(mode)
        if not path or not path.exists():
            return None
        if mode not in stores:
            stores[mode] = Store(path)
        return stores[mode]

    class Handler(BaseHTTPRequestHandler):
        server_version = "BotDashboard/1.0"

        def log_message(self, fmt, *args):
            log.debug("%s %s", self.address_string(), fmt % args)

        def _send(self, code: int, body: bytes, ctype: str) -> None:
            self.send_response(code)
            self.send_header("Content-Type", ctype)
            self.send_header("Content-Length", str(len(body)))
            self.send_header("Cache-Control", "no-store")
            self.send_header("X-Content-Type-Options", "nosniff")
            self.send_header("X-Frame-Options", "DENY")
            self.send_header("Referrer-Policy", "no-referrer")
            self.send_header("Content-Security-Policy",
                             "default-src 'self'; script-src 'self' 'unsafe-inline'; "
                             "style-src 'self' 'unsafe-inline'; connect-src 'self'")
            self.end_headers()
            self.wfile.write(body)

        def _json(self, obj, code: int = 200) -> None:
            self._send(code, json.dumps(obj, default=str).encode(), "application/json")

        def _authorized(self, qs: dict) -> bool:
            if not token:
                return True
            supplied = self.headers.get("X-Dashboard-Token") or (qs.get("token") or [""])[0]
            return hmac.compare_digest(supplied.encode(), token.encode())

        def do_GET(self):  # noqa: N802
            url = urlparse(self.path)
            qs = parse_qs(url.query)
            if url.path == "/healthz":
                return self._json({"ok": True})
            if not self._authorized(qs):
                return self._json({"error": "unauthorized"}, 401)
            if url.path in ("/", "/index.html"):
                return self._send(200, html, "text/html; charset=utf-8")
            if url.path == "/api/modes":
                return self._json([m for m, p in db_paths.items() if p.exists()])

            mode = (qs.get("mode") or ["paper"])[0]
            store = store_for(mode)
            if store is None:
                return self._json({"error": f"no data for mode '{mode}' yet - start the bot first"}, 404)
            if url.path == "/api/summary":
                return self._json(build_summary(store))
            if url.path == "/api/trades":
                return self._json(list(reversed(store.trades()[-200:])))
            if url.path == "/api/equity":
                return self._json(store.equity_series())
            return self._json({"error": "not found"}, 404)

    return Handler


def serve(db_paths: dict[str, Path], host: str = "127.0.0.1", port: int = 8080) -> None:
    token = os.getenv("DASHBOARD_TOKEN") or None
    if host not in LOOPBACK and not token:
        raise PermissionError("binding to a non-local address requires DASHBOARD_TOKEN to be set")
    httpd = ThreadingHTTPServer((host, port), make_handler(db_paths, token))
    url = f"http://{'localhost' if host in LOOPBACK else host}:{port}/" + (f"?token=<DASHBOARD_TOKEN>" if token else "")
    print(f"dashboard: {url}  (Ctrl+C to stop)")
    try:
        httpd.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        httpd.server_close()
