"""Uptime monitors: HTTP(S), keyword, TCP port, ping, DNS and Docker container checks.

Each monitor runs on its own interval. Every result is stored as a heartbeat,
which gives uptime percentages, response time charts and the status bars on
the Monitors tab. A monitor goes DOWN after `retries` consecutive failures and
sends an alert, then sends a recovery alert when it comes back UP.
"""
from __future__ import annotations

import json
import shutil
import sqlite3
import tempfile
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

from . import checks
from .config import HOST_ROOT
from .store import Store

TYPES = ("http", "tcp", "ping", "dns", "docker")
FIELDS = ("name", "type", "target", "port", "interval", "timeout", "keyword", "expect", "method", "ignore_tls",
          "invert", "retries", "enabled", "notify")


def _fmt_dur(sec: float) -> str:
    sec = int(sec)
    d, h, m = sec // 86400, sec % 86400 // 3600, sec % 3600 // 60
    if d:
        return f"{d}d {h}h"
    if h:
        return f"{h}h {m}m"
    if m:
        return f"{m}m"
    return f"{sec}s"


class Monitors:
    def __init__(self, store: Store, events, docker_watch) -> None:
        self.store = store
        self.events = events
        self.docker = docker_watch
        self.pool = ThreadPoolExecutor(max_workers=16, thread_name_prefix="monitor")
        self.lock = threading.Lock()
        self.running: set[int] = set()
        self.next_run: dict[int, float] = {}
        self.state: dict[int, dict] = {}
        self._load_state()

    def _load_state(self) -> None:
        for m in self.store.q("SELECT id, retries FROM monitors"):
            beats = self.store.q("SELECT ts, ok FROM beats WHERE monitor_id=? ORDER BY ts DESC LIMIT 50", (m["id"],))
            if not beats:
                self.state[m["id"]] = {"status": "pending", "since": time.time(), "fails": 0}
                continue
            status = "up" if beats[0]["ok"] else "down"
            since = beats[0]["ts"]
            for b in beats:
                if bool(b["ok"]) != (status == "up"):
                    break
                since = b["ts"]
            fails = 0 if status == "up" else len([b for b in beats[:m["retries"] or 1] if not b["ok"]])
            self.state[m["id"]] = {"status": status, "since": since, "fails": fails}

    # ---- scheduler ----------------------------------------------------------
    def run(self) -> None:
        time.sleep(5)
        while True:
            try:
                now = time.time()
                for m in self.store.q("SELECT * FROM monitors WHERE enabled=1"):
                    mid = m["id"]
                    if mid in self.running or self.next_run.get(mid, 0) > now:
                        continue
                    self.running.add(mid)
                    self.next_run[mid] = now + max(20, int(m["interval"] or 60))
                    self.pool.submit(self._check_and_record, m)
            except Exception as exc:
                print(f"[monitors] {exc!r}", flush=True)
            time.sleep(1)

    def check_now(self, mid: int) -> dict | None:
        m = self.get_row(mid)
        if not m:
            return None
        self._check_and_record(m)
        return self.detail(mid)

    def _check_and_record(self, m: dict) -> None:
        try:
            ok, ms, msg = self.probe(m)
        except Exception as exc:
            ok, ms, msg = False, None, f"Check error: {exc}"
        finally:
            self.running.discard(m["id"])
        self._record(m, ok, ms, msg)

    def probe(self, m: dict) -> tuple[bool, float | None, str]:
        t = m["type"]
        timeout = max(2, min(60, int(m.get("timeout") or 10)))
        if t == "http":
            return checks.probe_http(m["target"], m.get("method") or "GET", timeout, m.get("expect"),
                                     m.get("keyword") or None, bool(m.get("invert")), bool(m.get("ignore_tls")))
        if t == "tcp":
            return checks.probe_tcp(m["target"], int(m.get("port") or 80), timeout)
        if t == "ping":
            return checks.probe_ping(m["target"], timeout)
        if t == "dns":
            return checks.probe_dns(m["target"], timeout)
        if t == "docker":
            snap = self.docker.snapshot()
            if not snap.get("available"):
                return False, None, "Docker not reachable"
            c = next((c for c in snap["containers"] if c["name"] == m["target"]), None)
            if not c:
                return False, None, "Container not found"
            if c["state"] != "running":
                return False, None, f"Container {c['state']}" + (f" (exit {c['exit_code']})" if c["state"] == "exited" else "")
            if c["health"] == "unhealthy":
                return False, None, "Container unhealthy"
            return True, None, f"Running{', ' + c['health'] if c['health'] else ''}"
        return False, None, f"Unknown monitor type {t}"

    def _record(self, m: dict, ok: bool, ms: float | None, msg: str) -> None:
        now = time.time()
        self.store.x("INSERT INTO beats(monitor_id, ts, ok, ms, msg) VALUES(?,?,?,?,?)",
                     (m["id"], now, 1 if ok else 0, None if ms is None else round(ms, 2), (msg or "")[:300]))
        st = self.state.setdefault(m["id"], {"status": "pending", "since": now, "fails": 0})
        retries = max(1, int(m.get("retries") or 1))
        notify = "monitor_down" if m.get("notify", 1) else None
        if ok:
            was_down = st["status"] == "down"
            downtime = now - st["since"]
            st["fails"] = 0
            if st["status"] != "up":
                st["status"], st["since"] = "up", now
            if was_down:
                self.events.log("monitor", "ok", f"{m['name']} is back up",
                                f"{m['name']} recovered after {_fmt_dur(downtime)}. {msg}",
                                notify="monitor_up" if m.get("notify", 1) else None)
        else:
            st["fails"] += 1
            if st["fails"] >= retries and st["status"] != "down":
                st["status"], st["since"] = "down", now
                self.events.log("monitor", "crit", f"{m['name']} is down", f"{m['name']} ({self.describe(m)}): {msg}",
                                notify=notify)

    @staticmethod
    def describe(m: dict) -> str:
        if m["type"] == "tcp":
            return f"{m['target']}:{m.get('port')}"
        if m["type"] == "docker":
            return f"container {m['target']}"
        return m["target"]

    # ---- reads --------------------------------------------------------------
    def get_row(self, mid: int) -> dict | None:
        return self.store.one("SELECT * FROM monitors WHERE id=?", (mid,))

    def _uptimes(self) -> dict[int, dict]:
        out: dict[int, dict] = {}
        now = time.time()
        for label, secs in (("24h", 86400), ("7d", 7 * 86400), ("30d", 30 * 86400)):
            for r in self.store.q("SELECT monitor_id, AVG(ok)*100 AS up, AVG(ms) AS ms, COUNT(*) AS n FROM beats "
                                  "WHERE ts>=? GROUP BY monitor_id", (now - secs,)):
                d = out.setdefault(r["monitor_id"], {})
                d[f"uptime_{label}"] = r["up"]
                if label == "24h":
                    d["avg_ms_24h"] = r["ms"]
        return out

    def list(self) -> list[dict]:
        ups = self._uptimes()
        rows = []
        for m in self.store.q("SELECT * FROM monitors ORDER BY sort, name COLLATE NOCASE"):
            beats = self.store.q("SELECT ts, ok, ms, msg FROM beats WHERE monitor_id=? ORDER BY ts DESC LIMIT 60", (m["id"],))
            st = self.state.get(m["id"], {"status": "pending", "since": None})
            status = st["status"] if m["enabled"] else "paused"
            rows.append({**m, **ups.get(m["id"], {}), "status": status, "since": st.get("since"),
                         "last": beats[0] if beats else None, "beats": list(reversed(beats)),
                         "next_run": self.next_run.get(m["id"])})
        return rows

    def summary(self) -> dict:
        rows = self.store.q("SELECT id, enabled FROM monitors")
        counts = {"up": 0, "down": 0, "pending": 0, "paused": 0}
        for r in rows:
            s = self.state.get(r["id"], {}).get("status", "pending") if r["enabled"] else "paused"
            counts[s] = counts.get(s, 0) + 1
        counts["total"] = len(rows)
        down = [m["name"] for m in self.store.q("SELECT id, name, enabled FROM monitors")
                if m["enabled"] and self.state.get(m["id"], {}).get("status") == "down"]
        counts["down_names"] = down
        return counts

    def detail(self, mid: int, rng: str = "24h") -> dict | None:
        m = self.get_row(mid)
        if not m:
            return None
        span = {"1h": 3600, "24h": 86400, "7d": 7 * 86400, "30d": 30 * 86400, "90d": 90 * 86400}.get(rng, 86400)
        bucket = max(60, span // 240)
        since = time.time() - span
        series = self.store.q(
            f"SELECT CAST(ts/{bucket} AS INTEGER)*{bucket} AS t, AVG(ms) AS ms, MIN(ok) AS ok, COUNT(*) AS n "
            f"FROM beats WHERE monitor_id=? AND ts>=? GROUP BY CAST(ts/{bucket} AS INTEGER) ORDER BY t", (mid, since))
        recent = self.store.q("SELECT ts, ok, ms, msg FROM beats WHERE monitor_id=? ORDER BY ts DESC LIMIT 100", (mid,))
        incidents = self.store.q("SELECT ts, level, title, detail FROM events WHERE kind='monitor' AND title LIKE ? "
                                 "ORDER BY ts DESC LIMIT 30", (f"{m['name']} is %",))
        st = self.state.get(mid, {"status": "pending", "since": None})
        return {**m, **self._uptimes().get(mid, {}), "status": st["status"] if m["enabled"] else "paused",
                "since": st.get("since"), "range": rng, "series": series, "recent": recent, "incidents": incidents}

    # ---- writes -------------------------------------------------------------
    @staticmethod
    def clean(data: dict) -> dict:
        d = {k: data.get(k) for k in FIELDS if k in data}
        if "type" in d and d["type"] not in TYPES:
            raise ValueError(f"type must be one of {', '.join(TYPES)}")
        if "name" in d:
            d["name"] = str(d["name"] or "").strip()[:80]
            if not d["name"]:
                raise ValueError("Name is required")
        if "target" in d:
            d["target"] = str(d["target"] or "").strip()[:500]
            if not d["target"]:
                raise ValueError("Target is required")
        for k, lo, hi in (("interval", 20, 86400), ("timeout", 2, 60), ("retries", 1, 20), ("port", 1, 65535)):
            if d.get(k) not in (None, ""):
                d[k] = int(max(lo, min(hi, int(d[k]))))
            elif k in d:
                d[k] = None
        for k in ("ignore_tls", "invert", "enabled", "notify"):
            if k in d:
                d[k] = 1 if d[k] else 0
        if d.get("method"):
            d["method"] = str(d["method"]).upper()[:10]
        return d

    def create(self, data: dict) -> dict:
        d = self.clean(data)
        for k in ("name", "type", "target"):
            if not d.get(k):
                raise ValueError(f"{k} is required")
        if d["type"] == "tcp" and not d.get("port"):
            raise ValueError("A port is required for TCP monitors")
        d.setdefault("interval", 60)
        d.setdefault("timeout", 10)
        d.setdefault("retries", 2)
        d.setdefault("enabled", 1)
        d.setdefault("notify", 1)
        d["created"] = time.time()
        cols = ", ".join(d)
        cur = self.store.x(f"INSERT INTO monitors({cols}) VALUES({','.join('?' * len(d))})", list(d.values()))
        mid = cur.lastrowid
        self.state[mid] = {"status": "pending", "since": time.time(), "fails": 0}
        self.next_run[mid] = 0
        return self.get_row(mid)

    def update(self, mid: int, data: dict) -> dict | None:
        d = self.clean(data)
        if not d:
            return self.get_row(mid)
        sets = ", ".join(f"{k}=?" for k in d)
        self.store.x(f"UPDATE monitors SET {sets} WHERE id=?", [*d.values(), mid])
        self.next_run[mid] = 0
        if d.get("enabled") == 1 and self.state.get(mid, {}).get("status") == "paused":
            self.state[mid] = {"status": "pending", "since": time.time(), "fails": 0}
        return self.get_row(mid)

    def delete(self, mid: int) -> None:
        self.store.x("DELETE FROM monitors WHERE id=?", (mid,))
        self.store.x("DELETE FROM beats WHERE monitor_id=?", (mid,))
        self.state.pop(mid, None)
        self.next_run.pop(mid, None)

    # ---- import from Uptime Kuma -------------------------------------------
    def find_kuma_db(self) -> tuple[Path | None, str]:
        """Locate kuma.db via the uptime-kuma container's /app/data mount."""
        snap = self.docker.snapshot()
        try:
            client = self.docker._client()
        except Exception as exc:
            return None, f"Docker not reachable: {exc}"
        candidates = [c for c in snap.get("containers", []) if "uptime-kuma" in (c.get("image") or "") or "kuma" in c["name"]]
        if not candidates:
            return None, "No Uptime Kuma container found on this server."
        for c in candidates:
            try:
                attrs = client.containers.get(c["full_id"]).attrs
            except Exception:
                continue
            for mnt in attrs.get("Mounts", []):
                if mnt.get("Destination") in ("/app/data", "/app/data/"):
                    src = mnt.get("Source", "")
                    p = Path(f"{HOST_ROOT}{src}") / "kuma.db"
                    if p.exists():
                        return p, f"Found {src}/kuma.db in container {c['name']}"
                    return None, f"Found the {c['name']} data folder ({src}) but cannot read kuma.db there."
        return None, "Found an Uptime Kuma container but it has no /app/data volume."

    def import_kuma(self, include_notifications: bool = True, settings=None) -> dict:
        path, note = self.find_kuma_db()
        if not path:
            raise ValueError(note)
        tmp = Path(tempfile.mkdtemp(prefix="kuma-"))
        try:
            for suffix in ("", "-wal", "-shm"):
                src = Path(str(path) + suffix)
                if src.exists():
                    shutil.copy2(src, tmp / f"kuma.db{suffix}")
            con = sqlite3.connect(str(tmp / "kuma.db"))
            con.row_factory = sqlite3.Row
            rows = [dict(r) for r in con.execute("SELECT * FROM monitor")]
            notif_rows = []
            if include_notifications:
                try:
                    notif_rows = [dict(r) for r in con.execute("SELECT * FROM notification")]
                except sqlite3.Error:
                    pass
            con.close()
        finally:
            shutil.rmtree(tmp, ignore_errors=True)

        existing = {(m["type"], m["target"], m.get("port")) for m in self.store.q("SELECT type, target, port FROM monitors")}
        added, skipped, unsupported = [], [], []
        for r in rows:
            mapped = self._map_kuma(r)
            if not mapped:
                unsupported.append(f"{r.get('name')} ({r.get('type')})")
                continue
            key = (mapped["type"], mapped["target"], mapped.get("port"))
            if key in existing:
                skipped.append(mapped["name"])
                continue
            try:
                self.create(mapped)
                existing.add(key)
                added.append(mapped["name"])
            except ValueError as exc:
                unsupported.append(f"{r.get('name')} ({exc})")

        channels_added = []
        if include_notifications and settings is not None and notif_rows:
            current = settings.get("notify_channels")
            known = {(c["type"], c.get("url"), c.get("token")) for c in current}
            new = list(current)
            for n in notif_rows:
                ch = self._map_kuma_notification(n)
                if ch and (ch["type"], ch.get("url"), ch.get("token")) not in known:
                    new.append(ch)
                    channels_added.append(ch["name"])
            if channels_added:
                settings.update({"notify_channels": new})

        self.events.log("monitor", "info", f"Imported {len(added)} monitors from Uptime Kuma",
                        f"Skipped {len(skipped)} already present, {len(unsupported)} unsupported. "
                        f"Added {len(channels_added)} notification channels.")
        return {"source": note, "added": added, "skipped": skipped, "unsupported": unsupported,
                "channels_added": channels_added}

    @staticmethod
    def _map_kuma(r: dict) -> dict | None:
        t = (r.get("type") or "").lower()
        base = {"name": r.get("name") or "Imported", "interval": r.get("interval") or 60,
                "retries": max(1, int(r.get("maxretries") or 0) + 1), "enabled": 1 if r.get("active", 1) else 0,
                "timeout": int(r.get("timeout") or 10) if r.get("timeout") else 10}
        if t in ("http", "keyword", "json-query"):
            codes = r.get("accepted_statuscodes_json")
            expect = "200-399"
            try:
                parsed = json.loads(codes) if codes else None
                if parsed:
                    expect = ",".join(str(x).replace("-", "-") for x in parsed)
            except (ValueError, TypeError):
                pass
            return {**base, "type": "http", "target": r.get("url") or "", "method": r.get("method") or "GET",
                    "keyword": r.get("keyword") if t == "keyword" else None, "expect": expect,
                    "invert": 1 if r.get("invert_keyword") else 0, "ignore_tls": 1 if r.get("ignore_tls") else 0}
        if t == "port":
            return {**base, "type": "tcp", "target": r.get("hostname") or "", "port": r.get("port")}
        if t == "ping":
            return {**base, "type": "ping", "target": r.get("hostname") or ""}
        if t == "dns":
            return {**base, "type": "dns", "target": r.get("hostname") or ""}
        if t == "docker":
            return {**base, "type": "docker", "target": r.get("docker_container") or ""}
        return None

    @staticmethod
    def _map_kuma_notification(n: dict) -> dict | None:
        try:
            cfg = json.loads(n.get("config") or "{}")
        except ValueError:
            return None
        t = (cfg.get("type") or "").lower()
        name = n.get("name") or cfg.get("name") or t.title()
        if t == "discord" and cfg.get("discordWebhookUrl"):
            return {"type": "discord", "name": name, "url": cfg["discordWebhookUrl"], "enabled": True}
        if t == "telegram" and cfg.get("telegramBotToken"):
            return {"type": "telegram", "name": name, "token": cfg["telegramBotToken"],
                    "chat_id": str(cfg.get("telegramChatID") or ""), "enabled": True}
        if t == "ntfy" and cfg.get("ntfytopic"):
            server = (cfg.get("ntfyserverurl") or "https://ntfy.sh").rstrip("/")
            return {"type": "ntfy", "name": name, "url": f"{server}/{cfg['ntfytopic']}",
                    "token": cfg.get("ntfyaccesstoken") or "", "enabled": True}
        if t == "slack" and cfg.get("slackwebhookURL"):
            return {"type": "slack", "name": name, "url": cfg["slackwebhookURL"], "enabled": True}
        if t == "webhook" and cfg.get("webhookURL"):
            return {"type": "webhook", "name": name, "url": cfg["webhookURL"], "enabled": True}
        return None
