"""Long-term metrics history.

Every 10 seconds the recorder writes host CPU, memory, swap, load, temperature,
network and disk throughput to `sys_raw`, and every 30 seconds each container's
CPU, memory and network to `ct_raw`. Raw rows are kept for 48 hours and rolled
up into 5 minute averages (`sys_5m`, `ct_5m`) that are kept for the retention
period set in Settings (90 days by default).
"""
from __future__ import annotations

import time

import psutil

from .config import PHYS_DISK_RE, VIRTUAL_NIC_PREFIX
from .store import Store

RAW_INTERVAL = 10
CT_INTERVAL = 30
RAW_KEEP = 48 * 3600
ROLLUP = 300

RANGES = {"1h": 3600, "6h": 6 * 3600, "24h": 86400, "48h": 2 * 86400, "7d": 7 * 86400,
          "30d": 30 * 86400, "90d": 90 * 86400, "365d": 365 * 86400}
SYS_COLS = ("cpu", "mem", "swap", "load1", "temp", "rx", "tx", "dr", "dw")


def _phys_net() -> tuple[int, int]:
    rx = tx = 0
    for nic, c in psutil.net_io_counters(pernic=True).items():
        if not nic.startswith(VIRTUAL_NIC_PREFIX):
            rx += c.bytes_recv
            tx += c.bytes_sent
    return rx, tx


def _phys_disk() -> tuple[int, int]:
    r = w = 0
    try:
        for d, c in (psutil.disk_io_counters(perdisk=True) or {}).items():
            if PHYS_DISK_RE.match(d):
                r += c.read_bytes
                w += c.write_bytes
    except Exception:
        pass
    return r, w


class Recorder:
    def __init__(self, store: Store, sampler, docker_watch, settings, on_tick=None) -> None:
        self.store = store
        self.sampler = sampler
        self.docker = docker_watch
        self.settings = settings
        self.on_tick = on_tick
        self._last: dict | None = None
        self._ct_last: dict[str, tuple[float, int, int]] = {}
        self._last_ct_write = 0.0
        self._last_rollup = 0.0
        self._last_prune = 0.0

    def run(self) -> None:
        time.sleep(3)
        while True:
            start = time.time()
            try:
                self.tick()
            except Exception as exc:
                print(f"[history] {exc!r}", flush=True)
            time.sleep(max(1.0, RAW_INTERVAL - (time.time() - start)))

    def tick(self) -> None:
        now = time.time()
        rx, tx = _phys_net()
        dr, dw = _phys_disk()
        if self._last:
            dt = max(now - self._last["t"], 0.5)
            cur, hist, _ = self.sampler.snapshot()
            window = [h for h in hist if h["t"] > now - RAW_INTERVAL - 1] or hist[-1:]
            cpu = sum(h["cpu"] for h in window) / len(window) if window else cur.get("cpu", 0)
            row = (
                int(now), round(cpu, 2), cur.get("mem", {}).get("percent"), cur.get("swap", {}).get("percent"),
                (cur.get("load") or [None])[0], cur.get("cpu_temp"),
                max(rx - self._last["rx"], 0) / dt, max(tx - self._last["tx"], 0) / dt,
                max(dr - self._last["dr"], 0) / dt, max(dw - self._last["dw"], 0) / dt,
            )
            self.store.x("INSERT OR REPLACE INTO sys_raw(ts,cpu,mem,swap,load1,temp,rx,tx,dr,dw) VALUES(?,?,?,?,?,?,?,?,?,?)", row)
        self._last = {"t": now, "rx": rx, "tx": tx, "dr": dr, "dw": dw}

        if now - self._last_ct_write >= CT_INTERVAL:
            self._last_ct_write = now
            self._write_containers(now)
        if now - self._last_rollup >= 60:
            self._last_rollup = now
            self.rollup()
        if now - self._last_prune >= 3600:
            self._last_prune = now
            self.prune()
        if self.on_tick:
            self.on_tick()

    def _write_containers(self, now: float) -> None:
        snap = self.docker.snapshot()
        if not snap.get("available"):
            return
        rows = []
        seen = set()
        for c in snap.get("containers", []):
            s = c.get("stats")
            if not s:
                continue
            name = c["name"]
            seen.add(name)
            prev = self._ct_last.get(name)
            rx_rate = tx_rate = 0.0
            if prev and now > prev[0]:
                dt = now - prev[0]
                rx_rate = max(s["net_rx"] - prev[1], 0) / dt
                tx_rate = max(s["net_tx"] - prev[2], 0) / dt
            self._ct_last[name] = (now, s["net_rx"], s["net_tx"])
            rows.append((int(now), name, s["cpu"], s["mem_used"], rx_rate, tx_rate))
        for gone in set(self._ct_last) - seen:
            self._ct_last.pop(gone, None)
        self.store.many("INSERT OR REPLACE INTO ct_raw(ts,name,cpu,mem,rx,tx) VALUES(?,?,?,?,?,?)", rows)

    def rollup(self) -> None:
        """Average complete 5 minute buckets of raw data into the long-term tables."""
        upto = int(time.time()) // ROLLUP * ROLLUP
        since = self.store.get_meta("rollup_upto", 0) or 0
        if since == 0:
            first = self.store.one("SELECT MIN(ts) AS t FROM sys_raw")
            since = (first["t"] // ROLLUP * ROLLUP) if first and first["t"] else upto
        if upto <= since:
            return
        self.store.x(
            "INSERT OR REPLACE INTO sys_5m(ts,cpu,mem,swap,load1,temp,rx,tx,dr,dw,cpu_max,rx_max,tx_max) "
            "SELECT (ts/300)*300, AVG(cpu), AVG(mem), AVG(swap), AVG(load1), AVG(temp), AVG(rx), AVG(tx), AVG(dr), AVG(dw), "
            "MAX(cpu), MAX(rx), MAX(tx) FROM sys_raw WHERE ts>=? AND ts<? GROUP BY ts/300", (since, upto))
        self.store.x(
            "INSERT OR REPLACE INTO ct_5m(ts,name,cpu,mem,rx,tx) "
            "SELECT (ts/300)*300, name, AVG(cpu), AVG(mem), AVG(rx), AVG(tx) FROM ct_raw WHERE ts>=? AND ts<? "
            "GROUP BY ts/300, name", (since, upto))
        self.store.set_meta("rollup_upto", upto)

    def prune(self) -> None:
        now = time.time()
        keep = int(self.settings.get("retention_days") or 90) * 86400
        self.store.x("DELETE FROM sys_raw WHERE ts<?", (now - RAW_KEEP,))
        self.store.x("DELETE FROM ct_raw WHERE ts<?", (now - RAW_KEEP,))
        self.store.x("DELETE FROM sys_5m WHERE ts<?", (now - keep,))
        self.store.x("DELETE FROM ct_5m WHERE ts<?", (now - keep,))
        self.store.x("DELETE FROM beats WHERE ts<?", (now - keep,))
        self.store.x("DELETE FROM events WHERE ts<?", (now - keep,))

    # ---- queries ------------------------------------------------------------
    @staticmethod
    def _plan(rng: str) -> tuple[int, str, int]:
        span = RANGES.get(rng, 3600)
        table = "raw" if span <= RAW_KEEP else "5m"
        base = RAW_INTERVAL if table == "raw" else ROLLUP
        bucket = max(base, (span // 360) // base * base)
        return span, table, bucket

    def system(self, rng: str = "1h") -> dict:
        span, table, bucket = self._plan(rng)
        since = int(time.time()) - span
        extra = ", MAX(cpu_max) AS cpu_max, MAX(rx_max) AS rx_max, MAX(tx_max) AS tx_max" if table == "5m" else \
                ", MAX(cpu) AS cpu_max, MAX(rx) AS rx_max, MAX(tx) AS tx_max"
        cols = ", ".join(f"AVG({c}) AS {c}" for c in SYS_COLS)
        rows = self.store.q(
            f"SELECT (ts/{bucket})*{bucket} AS t, {cols}{extra} FROM sys_{table} WHERE ts>=? GROUP BY ts/{bucket} ORDER BY t",
            (since,))
        summary = self.store.one(
            f"SELECT AVG(cpu) AS cpu_avg, MAX(cpu) AS cpu_peak, AVG(mem) AS mem_avg, MAX(mem) AS mem_peak, "
            f"MAX(temp) AS temp_peak, AVG(temp) AS temp_avg, MAX(rx) AS rx_peak, MAX(tx) AS tx_peak, "
            f"SUM(rx) AS rx_sum, SUM(tx) AS tx_sum, COUNT(*) AS n FROM sys_{table} WHERE ts>=?", (since,)) or {}
        step = RAW_INTERVAL if table == "raw" else ROLLUP
        summary["rx_total"] = (summary.get("rx_sum") or 0) * step
        summary["tx_total"] = (summary.get("tx_sum") or 0) * step
        return {"range": rng, "bucket": bucket, "since": since, "points": rows, "summary": summary}

    def containers(self, rng: str = "1h", metric: str = "cpu", top: int = 8) -> dict:
        if metric not in ("cpu", "mem", "rx", "tx"):
            metric = "cpu"
        span, table, bucket = self._plan(rng)
        bucket = max(bucket, CT_INTERVAL if table == "raw" else ROLLUP)
        since = int(time.time()) - span
        leaders = self.store.q(
            f"SELECT name, AVG({metric}) AS avg, MAX({metric}) AS peak FROM ct_{table} WHERE ts>=? GROUP BY name "
            f"ORDER BY avg DESC LIMIT ?", (since, top))
        names = [r["name"] for r in leaders]
        series: dict[str, list] = {n: [] for n in names}
        if names:
            marks = ",".join("?" * len(names))
            for r in self.store.q(
                    f"SELECT (ts/{bucket})*{bucket} AS t, name, AVG({metric}) AS v FROM ct_{table} "
                    f"WHERE ts>=? AND name IN ({marks}) GROUP BY ts/{bucket}, name ORDER BY t", (since, *names)):
                series[r["name"]].append([r["t"], r["v"]])
        return {"range": rng, "metric": metric, "bucket": bucket, "since": since, "leaders": leaders, "series": series}

    def container(self, name: str, rng: str = "24h") -> dict:
        span, table, bucket = self._plan(rng)
        bucket = max(bucket, CT_INTERVAL if table == "raw" else ROLLUP)
        since = int(time.time()) - span
        rows = self.store.q(
            f"SELECT (ts/{bucket})*{bucket} AS t, AVG(cpu) AS cpu, AVG(mem) AS mem, AVG(rx) AS rx, AVG(tx) AS tx "
            f"FROM ct_{table} WHERE ts>=? AND name=? GROUP BY ts/{bucket} ORDER BY t", (since, name))
        return {"range": rng, "bucket": bucket, "points": rows}

    def today_traffic(self) -> dict:
        lt = time.localtime()
        midnight = time.mktime((lt.tm_year, lt.tm_mon, lt.tm_mday, 0, 0, 0, 0, 0, -1))
        r = self.store.one("SELECT SUM(rx) AS rx, SUM(tx) AS tx, MAX(rx) AS rx_peak, MAX(tx) AS tx_peak "
                           "FROM sys_raw WHERE ts>=?", (midnight,)) or {}
        return {"rx": (r.get("rx") or 0) * RAW_INTERVAL, "tx": (r.get("tx") or 0) * RAW_INTERVAL,
                "rx_peak": r.get("rx_peak") or 0, "tx_peak": r.get("tx_peak") or 0, "since": midnight}

