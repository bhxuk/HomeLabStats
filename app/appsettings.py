"""Settings changed from the dashboard's Settings tab, stored in the database.

Environment variables still work for anything that has to be known before the
app starts (port, password, data folder). Everything here can be changed live.
"""
from __future__ import annotations

import copy
import os
import secrets
import threading

from .store import Store

CHANNEL_TYPES = ("discord", "telegram", "ntfy", "slack", "webhook")

DEFAULTS: dict = {
    "container_actions": True,
    "speedtest_interval_hours": 0.0,
    "speedtest_engine": "ookla",
    "speedtest_alert_below_mbps": 0.0,
    "retention_days": 90,
    "notify_channels": [],
    "container_links": {},
    "notify_on": {
        "monitor_down": True,
        "monitor_up": True,
        "container_stopped": True,
        "container_unhealthy": True,
        "system_alerts": True,
        "speedtest_slow": True,
        "update_available": False,
    },
}


def _env_float(name: str, default: float) -> float:
    try:
        return float(os.environ.get(name, default))
    except ValueError:
        return default


class AppSettings:
    def __init__(self, store: Store) -> None:
        self.store = store
        self.lock = threading.Lock()
        saved = store.get_meta("settings")
        if saved is None:
            # First run: seed from environment variables so existing installs keep their choices.
            saved = {
                "speedtest_interval_hours": _env_float("SPEEDTEST_INTERVAL_HOURS", 0.0),
            }
            store.set_meta("settings", saved)
        self._data = self._merge(saved)

    @staticmethod
    def _merge(saved: dict) -> dict:
        data = copy.deepcopy(DEFAULTS)
        for k, v in (saved or {}).items():
            if k == "notify_on" and isinstance(v, dict):
                data["notify_on"].update({kk: bool(vv) for kk, vv in v.items() if kk in data["notify_on"]})
            elif k in data:
                data[k] = v
        return data

    def get(self, key: str):
        return self._data.get(key, DEFAULTS.get(key))

    def all(self, redact: bool = False) -> dict:
        data = copy.deepcopy(self._data)
        if redact:
            for ch in data["notify_channels"]:
                for secret in ("token", "url"):
                    if ch.get(secret):
                        ch[f"{secret}_set"] = True
        return data

    def channel(self, cid: str) -> dict | None:
        return next((c for c in self._data["notify_channels"] if c.get("id") == cid), None)

    def update(self, patch: dict) -> dict:
        with self.lock:
            data = copy.deepcopy(self._data)
            if "container_actions" in patch:
                data["container_actions"] = bool(patch["container_actions"])
            if "speedtest_interval_hours" in patch:
                data["speedtest_interval_hours"] = max(0.0, min(168.0, float(patch["speedtest_interval_hours"] or 0)))
            if "speedtest_engine" in patch and patch["speedtest_engine"] in ("cloudflare", "ookla"):
                data["speedtest_engine"] = patch["speedtest_engine"]
            if "speedtest_alert_below_mbps" in patch:
                data["speedtest_alert_below_mbps"] = max(0.0, float(patch["speedtest_alert_below_mbps"] or 0))
            if "retention_days" in patch:
                data["retention_days"] = int(max(7, min(730, int(patch["retention_days"]))))
            if isinstance(patch.get("notify_on"), dict):
                for k, v in patch["notify_on"].items():
                    if k in data["notify_on"]:
                        data["notify_on"][k] = bool(v)
            if isinstance(patch.get("container_links"), dict):
                data["container_links"] = {str(k)[:120]: str(v).strip()[:500] for k, v in patch["container_links"].items()
                                           if str(v or "").strip()}
            if isinstance(patch.get("notify_channels"), list):
                data["notify_channels"] = [self._clean_channel(c) for c in patch["notify_channels"] if isinstance(c, dict)]
            self._data = data
            self.store.set_meta("settings", data)
            return self.all()

    @staticmethod
    def _clean_channel(c: dict) -> dict:
        t = c.get("type") if c.get("type") in CHANNEL_TYPES else "webhook"
        return {
            "id": str(c.get("id") or secrets.token_hex(4)),
            "type": t,
            "name": str(c.get("name") or t.title())[:60],
            "url": str(c.get("url") or "").strip(),
            "token": str(c.get("token") or "").strip(),
            "chat_id": str(c.get("chat_id") or "").strip(),
            "enabled": bool(c.get("enabled", True)),
        }
