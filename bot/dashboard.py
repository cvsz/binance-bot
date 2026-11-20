"""Read-only web dashboard for a running bot (stdlib only, no extra dependencies).

It only reads the bot's SQLite database, so it can run in a separate process or
container and can never place or cancel orders.
"""
from __future__ import annotations

import hmac
import json
import logging
import os
import re
from datetime import UTC, datetime
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlparse

from .store import Store

log = logging.getLogger(__name__)
LOOPBACK = {"127.0.0.1", "localhost", "::1"}


def heartbeat_status(hb: dict) -> tuple[str, float | None]:
    """('online'|'stale'|'offline', age in seconds) from a heartbeat record."""
    if not hb.get("ts"):
        return "offline", None
    age = (datetime.now(UTC) - datetime.fromisoformat(hb["ts"])).total_seconds()
    poll = hb.get("poll_seconds") or 30
    return ("online" if age < max(3 * poll, 90) else "stale"), age


def build_summary(store: Store) -> dict:
    hb = store.get("heartbeat") or {}
    pos = store.get("position")
    risk = store.get("risk") or {}
    trades = store.trades()
    sells = [t for t in trades if t["side"] == "sell" and t["pnl_quote"] is not None]
    pnls = [t["pnl_quote"] for t in sells]
    wins = [p for p in pnls if p > 0]
    losses = [p for p in pnls if p <= 0]

    status, age = heartbeat_status(hb)

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
            stores[mode] = Store(path, read_only=True)  # dashboard must never write
        return stores[mode]

    class Handler(BaseHTTPRequestHandler):
        server_version = "BotDashboard/1.0"

        def log_request(self, code="-", size="-"):
            # BaseHTTPRequestHandler logs the whole request line, which contains
            # ?token=<DASHBOARD_TOKEN>. Log only the path.
            log.debug("%s %s %s", self.address_string(), code, urlparse(self.path).path)

        def log_message(self, fmt, *args):
            message = re.sub(r"token=[^&\s]+", "token=<redacted>", fmt % args)
            log.debug("%s %s", self.address_string(), message)

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

        def _metrics(self, store: Store) -> str:
            """Prometheus-compatible text exposition format.

            Reads from the store (source of truth) so no mutable counter state is
            needed; safe to expose on the read-only dashboard.
            """
            hb = store.get("heartbeat") or {}
            pos = store.get("position")
            trades = store.trades(limit=10000)
            sells = [t for t in trades if t["side"] == "sell" and t["pnl_quote"] is not None]
            pnls = [t["pnl_quote"] for t in sells]
            wins = [p for p in pnls if p > 0]
            mode = hb.get("mode", "unknown")
            symbol = hb.get("symbol", "unknown")
            strategy = hb.get("strategy", "unknown")
            lines = [
                "# HELP bot_info Bot information",
                "# TYPE bot_info gauge",
                f'bot_info{{mode="{mode}",symbol="{symbol}",strategy="{strategy}"}} 1',
                "",
                "# HELP bot_heartbeat_age_seconds Age of the last heartbeat in seconds",
                "# TYPE bot_heartbeat_age_seconds gauge",
            ]
            age = hb.get("heartbeat_age_s")
            if age is not None:
                lines.append(f"bot_heartbeat_age_seconds {age}")
            lines += [
                "",
                "# HELP bot_equity Current equity in quote currency",
                "# TYPE bot_equity gauge",
            ]
            equity = hb.get("equity")
            if equity is not None:
                lines.append(f"bot_equity {equity}")
            lines += [
                "",
                "# HELP bot_position_qty Position quantity in base currency",
                "# TYPE bot_position_qty gauge",
            ]
            if pos:
                lines.append(f'bot_position_qty{{symbol="{pos.get("symbol","unknown")}"}} {pos.get("qty",0)}')
            else:
                lines.append('bot_position_qty{symbol=""} 0')
            lines += [
                "",
                "# HELP bot_trades_total Total closed trades",
                "# TYPE bot_trades_total counter",
                f"bot_trades_total {len(sells)}",
                "",
                "# HELP bot_trades_wins_total Total winning trades",
                "# TYPE bot_trades_wins_total counter",
                f"bot_trades_wins_total {len(wins)}",
                "",
                "# HELP bot_realized_pnl_total Total realized PnL in quote currency",
                "# TYPE bot_realized_pnl_total counter",
                f"bot_realized_pnl_total {sum(pnls) if pnls else 0}",
            ]
            return "\n".join(lines) + "\n"

        def do_GET(self):  # noqa: N802
            url = urlparse(self.path)
            qs = parse_qs(url.query)
            if url.path == "/healthz":
                return self._json({"ok": True})
            if url.path == "/metrics":
                # Metrics are read-only observability; allow without token when no
                # token is configured, otherwise require authorization.
                if not token:
                    store = store_for((qs.get("mode") or ["paper"])[0])
                    if store is None:
                        return self._json({"error": "no data yet"}, 404)
                    return self._send(200, self._metrics(store).encode(), "text/plain; version=0.0.4; charset=utf-8")
                if not self._authorized(qs):
                    return self._json({"error": "unauthorized"}, 401)
                mode = (qs.get("mode") or ["paper"])[0]
                store = store_for(mode)
                if store is None:
                    return self._json({"error": f"no data for mode '{mode}' yet - start the bot first"}, 404)
                return self._send(200, self._metrics(store).encode(), "text/plain; version=0.0.4; charset=utf-8")
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
                return self._json(list(reversed(store.trades(limit=200))))
            if url.path == "/api/equity":
                return self._json(store.equity_series())
            return self._json({"error": "not found"}, 404)

    return Handler


def serve(db_paths: dict[str, Path], host: str = "127.0.0.1", port: int = 8080) -> None:
    token = os.getenv("DASHBOARD_TOKEN") or None
    if host not in LOOPBACK and not token:
        raise PermissionError("binding to a non-local address requires DASHBOARD_TOKEN to be set")
    httpd = ThreadingHTTPServer((host, port), make_handler(db_paths, token))
    url = f"http://{'localhost' if host in LOOPBACK else host}:{port}/" + ("?token=<DASHBOARD_TOKEN>" if token else "")
    print(f"dashboard: {url}  (Ctrl+C to stop)")
    try:
        httpd.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        httpd.server_close()
