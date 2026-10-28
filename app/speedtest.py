"""Speed tests (Cloudflare by default, Ookla via speedtest-cli) with a permanent log."""
from __future__ import annotations

import http.client
import json
import os
import platform
import shutil
import ssl
import subprocess
import tarfile
import threading
import time
import urllib.request
from pathlib import Path

from .config import DATA_DIR, VERSION
from .store import Store

CF_HOST = "speed.cloudflare.com"
COLS = "id, ts, engine, trigger, download, upload, ping, jitter, server, isp, ip, error, url"
OOKLA_VERSION = "1.2.0"
OOKLA_ARCH = {"x86_64": "x86_64", "amd64": "x86_64", "aarch64": "aarch64", "arm64": "aarch64",
              "armv7l": "armhf", "armv6l": "armel", "i686": "i386", "i386": "i386"}
CF_HEADERS = {"User-Agent": "Mozilla/5.0 (X11; Linux x86_64) HomeLabStats", "Referer": "https://speed.cloudflare.com/",
              "Origin": "https://speed.cloudflare.com", "Accept": "*/*"}


class SpeedTester:
    def __init__(self, store: Store, settings, events) -> None:
        self.store = store
        self.settings = settings
        self.events = events
        self.lock = threading.Lock()
        self.running = False
        self.phase: str | None = None
        self.engine: str | None = None
        self.error: str | None = None
        self.live: dict = {}
        try:
            self.store.x("ALTER TABLE speedtests ADD COLUMN url TEXT")
        except Exception:
            pass  # column already there
        self._migrate_json()

    def _migrate_json(self) -> None:
        old = Path(DATA_DIR) / "speedtests.json"
        if not old.exists():
            return
        try:
            rows = json.loads(old.read_text())
            self.store.many(
                "INSERT INTO speedtests(ts, engine, trigger, download, upload, ping, jitter, server, isp, ip) VALUES(?,?,?,?,?,?,?,?,?,?)",
                [(r.get("time"), r.get("engine"), "manual", r.get("download"), r.get("upload"), r.get("ping"),
                  r.get("jitter"), r.get("server"), r.get("isp"), r.get("ip")) for r in reversed(rows)])
            old.rename(old.with_suffix(".json.migrated"))
        except Exception as exc:
            print(f"[speedtest] could not migrate old history: {exc!r}", flush=True)

    # ---- queries ------------------------------------------------------------
    def history(self, days: float = 30, limit: int = 500) -> list[dict]:
        since = time.time() - days * 86400
        return self.store.q(f"SELECT {COLS} FROM speedtests WHERE ts>=? ORDER BY ts DESC LIMIT ?", (since, limit))

    def last(self) -> dict | None:
        return self.store.one(f"SELECT {COLS} FROM speedtests WHERE error IS NULL ORDER BY ts DESC LIMIT 1")

    def stats(self) -> dict:
        out = {}
        for label, days in (("24h", 1), ("7d", 7), ("30d", 30), ("all", 36500)):
            r = self.store.one(
                "SELECT COUNT(*) AS n, AVG(download) AS down_avg, MIN(download) AS down_min, MAX(download) AS down_max, "
                "AVG(upload) AS up_avg, MIN(upload) AS up_min, MAX(upload) AS up_max, AVG(ping) AS ping_avg, "
                "MIN(ping) AS ping_min, MAX(ping) AS ping_max FROM speedtests WHERE error IS NULL AND ts>=?",
                (time.time() - days * 86400,))
            fails = self.store.one("SELECT COUNT(*) AS n FROM speedtests WHERE error IS NOT NULL AND ts>=?",
                                   (time.time() - days * 86400,))
            r["failed"] = fails["n"] if fails else 0
            out[label] = r
        return out

    def status(self) -> dict:
        live = {}
        if self.live.get("direct") is not None and self.phase in ("download", "upload"):
            live = {"mbps": round(self.live["direct"], 1)}
        elif self.live.get("start") and self.phase in ("download", "upload"):
            elapsed = max(time.perf_counter() - self.live["start"], 0.001)
            live = {"mbps": round(self.live["bytes"][0] * 8 / elapsed / 1e6, 1), "elapsed": round(elapsed, 1)}
        interval = float(self.settings.get("speedtest_interval_hours") or 0)
        last_any = self.store.one("SELECT ts FROM speedtests ORDER BY ts DESC LIMIT 1")
        nxt = (last_any["ts"] + interval * 3600) if (interval and last_any) else (time.time() + 60 if interval else None)
        return {"running": self.running, "phase": self.phase, "engine": self.engine, "error": self.error, "live": live,
                "last": self.last(), "interval_hours": interval, "next_run": nxt}

    def export_csv(self) -> str:
        lines = ["time,engine,trigger,download_mbps,upload_mbps,ping_ms,jitter_ms,server,isp,ip,error"]
        for r in self.store.q(f"SELECT {COLS} FROM speedtests ORDER BY ts"):
            t = time.strftime("%Y-%m-%d %H:%M:%S", time.localtime(r["ts"]))
            vals = [t, r["engine"], r["trigger"], r["download"], r["upload"], r["ping"], r["jitter"], r["server"],
                    r["isp"], r["ip"], r["error"]]
            lines.append(",".join("" if v is None else '"' + str(v).replace('"', "'") + '"' if isinstance(v, str) else str(v)
                                  for v in vals))
        return "\n".join(lines) + "\n"

    def delete(self, test_id: int | None = None) -> None:
        if test_id is None:
            self.store.x("DELETE FROM speedtests")
        else:
            self.store.x("DELETE FROM speedtests WHERE id=?", (test_id,))

    # ---- running ------------------------------------------------------------
    def start(self, engine: str | None = None, trigger: str = "manual") -> bool:
        engine = engine or self.settings.get("speedtest_engine") or "cloudflare"
        with self.lock:
            if self.running:
                return False
            self.running = True
            self.engine = engine
            self.error = None
            self.phase = "starting"
        threading.Thread(target=self._run, args=(engine, trigger), daemon=True).start()
        return True

    def _run(self, engine: str, trigger: str) -> None:
        try:
            res = self._ookla() if engine == "ookla" else self._cloudflare()
            self.store.x(
                "INSERT INTO speedtests(ts, engine, trigger, download, upload, ping, jitter, server, isp, ip, url) VALUES(?,?,?,?,?,?,?,?,?,?,?)",
                (time.time(), engine, trigger, res["download"], res["upload"], res["ping"], res.get("jitter"),
                 res.get("server"), res.get("isp"), res.get("ip"), res.get("url")))
            floor = float(self.settings.get("speedtest_alert_below_mbps") or 0)
            msg = f"Down {res['download']:.0f} Mbps, up {res['upload']:.0f} Mbps, ping {res['ping']:.0f} ms ({res.get('server')})"
            if floor and res["download"] < floor:
                self.events.log("speedtest", "warn", f"Slow internet: {res['download']:.0f} Mbps down", msg + f". Alert threshold is {floor:.0f} Mbps.",
                                notify="speedtest_slow")
            else:
                self.events.log("speedtest", "info", f"Speed test: {res['download']:.0f} / {res['upload']:.0f} Mbps", msg)
        except Exception as exc:
            self.error = f"{type(exc).__name__}: {exc}"
            self.store.x("INSERT INTO speedtests(ts, engine, trigger, error) VALUES(?,?,?,?)",
                         (time.time(), engine, trigger, self.error[:300]))
            self.events.log("speedtest", "warn", "Speed test failed", self.error, notify="speedtest_slow",
                            cooldown_key="speedtest_fail", cooldown=6 * 3600)
        finally:
            self.phase = None
            self.live = {}
            self.running = False

    @staticmethod
    def _conn() -> http.client.HTTPSConnection:
        return http.client.HTTPSConnection(CF_HOST, timeout=15, context=ssl.create_default_context())

    def _cloudflare(self) -> dict:
        headers = dict(CF_HEADERS)
        self.phase = "latency"
        conn = self._conn()
        conn.request("GET", "/__down?bytes=0", headers=headers)
        r = conn.getresponse()
        r.read()
        meta = {k: r.getheader(f"cf-meta-{k}") for k in ("colo", "city", "country", "asn", "ip")}
        samples = []
        for _ in range(12):
            t0 = time.perf_counter()
            conn.request("GET", "/__down?bytes=0", headers=headers)
            r = conn.getresponse()
            r.read()
            samples.append((time.perf_counter() - t0) * 1000)
        conn.close()
        latency = sorted(samples)[len(samples) // 2]
        jitter = sum(abs(a - b) for a, b in zip(samples, samples[1:])) / (len(samples) - 1)

        self.phase = "download"
        down = self._transfer("down", headers)
        self.phase = "upload"
        up = self._transfer("up", headers)
        server = meta.get("colo") or "Cloudflare"
        if meta.get("city"):
            server = f"{meta['city']} ({meta.get('colo')})"
        return {"download": round(down, 2), "upload": round(up, 2), "ping": round(latency, 1),
                "jitter": round(jitter, 1), "server": f"Cloudflare {server}",
                "isp": f"AS{meta['asn']}" if meta.get("asn") else None, "ip": meta.get("ip")}

    def _transfer(self, direction: str, headers: dict, duration: float = 10.0, threads: int = 6) -> float:
        counter = [0]
        lock = threading.Lock()
        start = time.perf_counter()
        stop = start + duration
        self.live = {"start": start, "bytes": counter}
        payload = os.urandom(2 * 1024 * 1024) if direction == "up" else b""
        errors: list[str] = []

        def worker() -> None:
            conn = self._conn()
            try:
                while time.perf_counter() < stop:
                    if direction == "down":
                        conn.request("GET", "/__down?bytes=25000000", headers=headers)
                        r = conn.getresponse()
                        if r.status != 200:
                            r.read()
                            raise RuntimeError(f"Cloudflare answered HTTP {r.status} to the download request")
                        while time.perf_counter() < stop:
                            chunk = r.read(262144)
                            if not chunk:
                                break
                            with lock:
                                counter[0] += len(chunk)
                        if time.perf_counter() >= stop:
                            break
                    else:
                        h = dict(headers, **{"Content-Type": "application/octet-stream"})
                        conn.request("POST", "/__up", body=payload, headers=h)
                        r = conn.getresponse()
                        r.read()
                        if r.status != 200:
                            raise RuntimeError(f"Cloudflare answered HTTP {r.status} to the upload request")
                        with lock:
                            counter[0] += len(payload)
            except Exception as exc:
                errors.append(str(exc))
            finally:
                conn.close()

        ts = [threading.Thread(target=worker, daemon=True) for _ in range(threads)]
        for t in ts:
            t.start()
        for t in ts:
            t.join(timeout=duration + 20)
        elapsed = time.perf_counter() - start
        mbps = counter[0] * 8 / elapsed / 1e6
        # A refused or cut-off transfer must not be logged as a (very slow) result.
        if counter[0] < 2_000_000 or (errors and len(errors) >= threads):
            raise RuntimeError(f"{direction}load test failed: {errors[0] if errors else 'almost no data transferred'}")
        return mbps

    # Ookla (official Speedtest CLI) ------------------------------------------
    def _ookla_binary(self) -> Path:
        """Download Ookla's official CLI into the data folder on first use."""
        bin_dir = Path(DATA_DIR) / "bin"
        target = bin_dir / f"speedtest-{OOKLA_VERSION}"
        if target.exists():
            return target
        on_path = shutil.which("speedtest")
        if on_path and "Ookla" in subprocess.run([on_path, "--version"], capture_output=True, text=True).stdout:
            return Path(on_path)
        arch = OOKLA_ARCH.get(platform.machine().lower())
        if not arch:
            raise RuntimeError(f"Ookla's CLI has no build for {platform.machine()}. Use the Cloudflare engine.")
        self.phase = "downloading Ookla CLI"
        url = f"https://install.speedtest.net/app/cli/ookla-speedtest-{OOKLA_VERSION}-linux-{arch}.tgz"
        bin_dir.mkdir(parents=True, exist_ok=True)
        tgz = bin_dir / "ookla.tgz"
        with urllib.request.urlopen(urllib.request.Request(url, headers={"User-Agent": f"homelabstats/{VERSION}"}), timeout=60) as r:
            tgz.write_bytes(r.read())
        with tarfile.open(tgz) as tf:
            member = tf.getmember("speedtest")
            with tf.extractfile(member) as src:
                target.write_bytes(src.read())
        tgz.unlink(missing_ok=True)
        target.chmod(0o755)
        return target

    def _ookla(self) -> dict:
        binary = self._ookla_binary()
        self.phase = "finding server"
        env = dict(os.environ, HOME=str(DATA_DIR))
        proc = subprocess.Popen([str(binary), "--accept-license", "--accept-gdpr", "--format=jsonl", "--progress=yes"],
                                stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, env=env, cwd=str(DATA_DIR))
        result, last_error = None, None
        deadline = time.time() + 180
        try:
            for line in proc.stdout:
                if time.time() > deadline:
                    proc.kill()
                    raise RuntimeError("Ookla test took longer than 3 minutes")
                try:
                    ev = json.loads(line)
                except ValueError:
                    continue
                t = ev.get("type")
                if t == "ping":
                    self.phase = "latency"
                elif t in ("download", "upload"):
                    self.phase = t
                    bw = (ev.get(t) or {}).get("bandwidth")
                    if bw:
                        self.live = {"direct": bw / 125000}
                elif t == "result":
                    result = ev
                elif t == "log" and ev.get("level") == "error":
                    last_error = ev.get("message")
            proc.wait(timeout=30)
        finally:
            if proc.poll() is None:
                proc.kill()
        if not result:
            err = last_error or (proc.stderr.read() if proc.stderr else "") or f"exit code {proc.returncode}"
            raise RuntimeError(f"Ookla: {str(err).strip()[:250]}")
        srv = result.get("server") or {}
        return {"download": round(result["download"]["bandwidth"] / 125000, 2),
                "upload": round(result["upload"]["bandwidth"] / 125000, 2),
                "ping": round((result.get("ping") or {}).get("latency") or 0, 1),
                "jitter": round((result.get("ping") or {}).get("jitter") or 0, 1),
                "server": f"{srv.get('name', '?')} ({srv.get('location', '?')})",
                "isp": result.get("isp"), "ip": (result.get("interface") or {}).get("externalIp"),
                "url": (result.get("result") or {}).get("url")}

    def scheduler(self) -> None:
        time.sleep(20)
        while True:
            try:
                hours = float(self.settings.get("speedtest_interval_hours") or 0)
                if hours > 0 and not self.running:
                    last = self.store.one("SELECT ts FROM speedtests ORDER BY ts DESC LIMIT 1")
                    if not last or time.time() - last["ts"] >= hours * 3600:
                        self.start(trigger="scheduled")
            except Exception as exc:
                print(f"[speedtest] scheduler: {exc!r}", flush=True)
            time.sleep(60)
