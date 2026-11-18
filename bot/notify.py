"""Optional Telegram notifications (set TELEGRAM_BOT_TOKEN and TELEGRAM_CHAT_ID)."""
from __future__ import annotations

import json
import logging
import os
import time
import urllib.request

log = logging.getLogger(__name__)
API = "https://api.telegram.org"


class Notifier:
    """Sends Telegram messages. Identical messages are suppressed for `dedupe_seconds`
    so a recurring error cannot flood the chat (they are still logged)."""

    def __init__(self, token: str | None = None, chat_id: str | None = None, dedupe_seconds: float = 900):
        self.token = token if token is not None else os.getenv("TELEGRAM_BOT_TOKEN")
        self.chat_id = chat_id if chat_id is not None else os.getenv("TELEGRAM_CHAT_ID")
        self.dedupe_seconds = dedupe_seconds
        self._last_sent: dict[str, float] = {}

    @property
    def enabled(self) -> bool:
        return bool(self.token and self.chat_id)

    def _suppressed(self, text: str) -> bool:
        now = time.monotonic()
        last = self._last_sent.get(text)
        if last is not None and now - last < self.dedupe_seconds:
            return True
        self._last_sent[text] = now
        if len(self._last_sent) > 500:  # bound memory
            cutoff = now - self.dedupe_seconds
            self._last_sent = {k: v for k, v in self._last_sent.items() if v >= cutoff}
        return False

    def send(self, text: str) -> None:
        log.info("NOTIFY %s", text)
        if not self.enabled or self._suppressed(text):
            return
        try:
            req = urllib.request.Request(  # noqa: S310 - fixed https URL
                f"{API}/bot{self.token}/sendMessage",
                data=json.dumps({"chat_id": self.chat_id, "text": text[:4000]}).encode(),
                headers={"Content-Type": "application/json"},
            )
            urllib.request.urlopen(req, timeout=10).read()  # noqa: S310 - fixed https URL
        except Exception as exc:  # notifications must never crash trading
            # never log the URL: it contains the bot token
            log.warning("telegram send failed: %s", type(exc).__name__)


class NullNotifier(Notifier):
    def __init__(self):
        super().__init__(token="", chat_id="")

    def send(self, text: str) -> None:
        pass
