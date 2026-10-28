"""Activity log and outgoing alerts (Discord, Telegram, ntfy, Slack, generic webhook)."""
from __future__ import annotations

import json
import socket
import threading
import time
import urllib.request

from .appsettings import AppSettings
from .config import VERSION
from .store import Store

LEVEL_COLOR = {"crit": 0xF87171, "warn": 0xFBBF24, "ok": 0x34D399, "info": 0x22D3EE}
LEVEL_EMOJI = {"crit": "🔴", "warn": "🟠", "ok": "🟢", "info": "🔵"}


def _post(url: str, body: bytes, headers: dict, timeout: float = 10) -> None:
    req = urllib.request.Request(url, data=body, method="POST",
                                 headers={"User-Agent": f"homelabstats/{VERSION}", **headers})
    with urllib.request.urlopen(req, timeout=timeout) as r:
        r.read(256)


def send(channel: dict, title: str, message: str, level: str = "info") -> None:
    """Send one notification. Raises on failure so the Test button can show the error."""
    host = socket.gethostname()
    t = channel.get("type")
    emoji = LEVEL_EMOJI.get(level, "")
    if t == "discord":
        payload = {"username": "HomeLabStats", "embeds": [{
            "title": f"{emoji} {title}", "description": message, "color": LEVEL_COLOR.get(level, 0x22D3EE),
            "footer": {"text": f"{host} · HomeLabStats"}, "timestamp": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        }]}
        _post(channel["url"], json.dumps(payload).encode(), {"Content-Type": "application/json"})
    elif t == "slack":
        _post(channel["url"], json.dumps({"text": f"{emoji} *{title}*\n{message}\n_{host}_"}).encode(),
              {"Content-Type": "application/json"})
    elif t == "telegram":
        if not channel.get("token") or not channel.get("chat_id"):
            raise ValueError("Telegram needs a bot token and a chat ID")
        url = f"https://api.telegram.org/bot{channel['token']}/sendMessage"
        text = f"{emoji} <b>{_html(title)}</b>\n{_html(message)}\n<i>{_html(host)}</i>"
        _post(url, json.dumps({"chat_id": channel["chat_id"], "text": text, "parse_mode": "HTML"}).encode(),
              {"Content-Type": "application/json"})
    elif t == "ntfy":
        headers = {"Title": f"{title}".encode("utf-8").decode("latin-1", "ignore"),
                   "Priority": {"crit": "5", "warn": "4"}.get(level, "3"),
                   "Tags": {"crit": "rotating_light", "warn": "warning", "ok": "white_check_mark"}.get(level, "information_source")}
        if channel.get("token"):
            headers["Authorization"] = f"Bearer {channel['token']}"
        _post(channel["url"], message.encode(), headers)
    else:
        _post(channel["url"], json.dumps({"title": title, "message": message, "level": level, "host": host,
                                          "ts": time.time(), "source": "homelabstats"}).encode(),
              {"Content-Type": "application/json"})


def _html(s: str) -> str:
    return str(s).replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")


class Events:
    """Writes the activity log and fans notable events out to notification channels."""

    def __init__(self, store: Store, settings: AppSettings) -> None:
        self.store = store
        self.settings = settings
        self._cooldown: dict[str, float] = {}

    def log(self, kind: str, level: str, title: str, detail: str = "", notify: str | None = None,
            cooldown_key: str | None = None, cooldown: float = 0) -> None:
        self.store.x("INSERT INTO events(ts, kind, level, title, detail) VALUES(?,?,?,?,?)",
                     (time.time(), kind, level, title, detail))
        if not notify or not self.settings.get("notify_on").get(notify, False):
            return
        if cooldown_key:
            last = self._cooldown.get(cooldown_key, 0)
            if time.time() - last < cooldown:
                return
            self._cooldown[cooldown_key] = time.time()
        channels = [c for c in self.settings.get("notify_channels") if c.get("enabled")]
        for ch in channels:
            threading.Thread(target=self._send_safe, args=(ch, title, detail, level), daemon=True).start()

    def _send_safe(self, ch: dict, title: str, detail: str, level: str) -> None:
        try:
            send(ch, title, detail or title, level)
        except Exception as exc:
            print(f"[notify] {ch.get('name')}: {exc}", flush=True)
            self.store.x("INSERT INTO events(ts, kind, level, title, detail) VALUES(?,?,?,?,?)",
                         (time.time(), "notify", "warn", f"Could not send alert to {ch.get('name')}", str(exc)[:300]))

    def recent(self, limit: int = 50, kind: str | None = None) -> list[dict]:
        if kind:
            return self.store.q("SELECT * FROM events WHERE kind=? ORDER BY ts DESC LIMIT ?", (kind, limit))
        return self.store.q("SELECT * FROM events ORDER BY ts DESC LIMIT ?", (limit,))
