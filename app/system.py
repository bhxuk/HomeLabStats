"""Host metrics: CPU, memory, temperatures, processes, disks, interfaces and alerts."""
from __future__ import annotations

import os
import platform
import re
import socket
import threading
import time
from collections import deque
from pathlib import Path

import psutil

from .config import (
    CPU_TEMP_CHIPS, DISK_PATHS, HISTORY_POINTS, HOST_ROOT, INSTALL_METHOD, NETWORK_FS, PHYS_DISK_RE, REAL_FS,
    SAMPLE_INTERVAL, VERSION, VIRTUAL_NIC_PREFIX, host_path,
)

# --------------------------------------------------------------------------
# Host info helpers
# --------------------------------------------------------------------------
def read_text(*paths: str) -> str | None:
    for p in paths:
        try:
            return Path(p).read_text()
        except OSError:
            continue
    return None


def host_info() -> dict:
    osr = read_text(host_path("/etc/os-release"), "/etc/os-release") or ""
    m = re.search(r'^PRETTY_NAME="?([^"\n]+)"?', osr, re.M)
    hostname = (read_text(host_path("/etc/hostname")) or "").strip() if HOST_ROOT else ""
    cpuinfo = read_text("/proc/cpuinfo") or ""
    model = re.search(r"^model name\s*:\s*(.+)$", cpuinfo, re.M)
    if not model:
        model = re.search(r"^Model\s*:\s*(.+)$", cpuinfo, re.M)
    freq = None
    try:
        f = psutil.cpu_freq()
        freq = round(f.current) if f else None
    except Exception:
        pass
    return {
        "hostname": hostname or socket.gethostname(),
        "os": m.group(1) if m else platform.system(),
        "kernel": platform.release(),
        "arch": platform.machine(),
        "cpu_model": model.group(1).strip() if model else platform.processor() or "Unknown CPU",
        "cores_physical": psutil.cpu_count(logical=False),
        "cores_logical": psutil.cpu_count(),
        "cpu_freq_mhz": freq,
        "boot_time": psutil.boot_time(),
        "version": VERSION,
        "install_method": INSTALL_METHOD,
    }


_uid_cache: dict = {"t": 0.0, "map": {}}


def uid_map() -> dict[int, str]:
    if time.time() - _uid_cache["t"] > 300:
        m: dict[int, str] = {}
        text = read_text(host_path("/etc/passwd"), "/etc/passwd") or ""
        for line in text.splitlines():
            parts = line.split(":")
            if len(parts) > 2:
                try:
                    m[int(parts[2])] = parts[0]
                except ValueError:
                    pass
        _uid_cache.update(t=time.time(), map=m)
    return _uid_cache["map"]


def read_temps() -> list[dict]:
    out = []
    try:
        temps = psutil.sensors_temperatures()
    except Exception:
        return out
    for chip, entries in (temps or {}).items():
        for i, e in enumerate(entries):
            if e.current is None or e.current <= 0 or e.current > 150:
                continue
            out.append({
                "chip": chip,
                "label": e.label or f"{chip} {i}",
                "current": round(e.current, 1),
                "high": e.high,
                "critical": e.critical,
            })
    return out


def cpu_temp(temps: list[dict]) -> float | None:
    for chip in CPU_TEMP_CHIPS:
        group = [t for t in temps if t["chip"] == chip]
        if not group:
            continue
        for pref in ("Package id 0", "Tctl", "Tdie"):
            for t in group:
                if t["label"] == pref:
                    return t["current"]
        return max(t["current"] for t in group)
    return None


# --------------------------------------------------------------------------
# Background sampler: CPU, memory, network/disk rates, processes
# --------------------------------------------------------------------------
class Sampler:
    def __init__(self) -> None:
        self.lock = threading.Lock()
        self.history: deque = deque(maxlen=HISTORY_POINTS)
        self.current: dict = {}
        self.procs: list[dict] = []
        self.last: dict | None = None

    def run(self) -> None:
        psutil.cpu_percent(percpu=True)
        for p in psutil.process_iter():
            try:
                p.cpu_percent(None)
            except psutil.Error:
                pass
        time.sleep(0.5)
        while True:
            try:
                self.sample()
            except Exception as exc:  # keep the sampler alive no matter what
                print(f"[sampler] {exc!r}", flush=True)
            time.sleep(SAMPLE_INTERVAL)

    def sample(self) -> None:
        now = time.time()
        per = psutil.cpu_percent(percpu=True)
        cpu = round(sum(per) / max(len(per), 1), 1)
        vm = psutil.virtual_memory()
        sw = psutil.swap_memory()
        net = psutil.net_io_counters(pernic=True)
        try:
            dio = psutil.disk_io_counters(perdisk=True) or {}
        except Exception:
            dio = {}

        net_rates: dict = {}
        disk_rates: dict = {}
        rx_total = tx_total = 0.0
        if self.last and now > self.last["t"]:
            dt = now - self.last["t"]
            for nic, c in net.items():
                p = self.last["net"].get(nic)
                if not p:
                    continue
                rx = max(c.bytes_recv - p.bytes_recv, 0) / dt
                tx = max(c.bytes_sent - p.bytes_sent, 0) / dt
                net_rates[nic] = {"rx": rx, "tx": tx}
                if not nic.startswith(VIRTUAL_NIC_PREFIX):
                    rx_total += rx
                    tx_total += tx
            for disk, c in dio.items():
                if not PHYS_DISK_RE.match(disk):
                    continue
                p = self.last["disk"].get(disk)
                if not p:
                    continue
                disk_rates[disk] = {
                    "read": max(c.read_bytes - p.read_bytes, 0) / dt,
                    "write": max(c.write_bytes - p.write_bytes, 0) / dt,
                    "busy": min(100.0, max(getattr(c, "busy_time", 0) - getattr(p, "busy_time", 0), 0) / (dt * 10)),
                }
        self.last = {"t": now, "net": net, "disk": dio}

        procs = self._sample_procs(vm.total)
        temps = read_temps()
        try:
            load = os.getloadavg()
        except OSError:
            load = (0.0, 0.0, 0.0)

        current = {
            "time": now,
            "cpu": cpu,
            "per_cpu": per,
            "load": [round(x, 2) for x in load],
            "mem": {"total": vm.total, "used": vm.total - vm.available, "available": vm.available,
                    "percent": vm.percent, "cached": getattr(vm, "cached", 0), "buffers": getattr(vm, "buffers", 0)},
            "swap": {"total": sw.total, "used": sw.used, "percent": sw.percent},
            "net_rates": net_rates,
            "net_total": {"rx": rx_total, "tx": tx_total},
            "disk_rates": disk_rates,
            "temps": temps,
            "cpu_temp": cpu_temp(temps),
            "proc_count": len(procs),
            "uptime": now - psutil.boot_time(),
        }
        with self.lock:
            self.current = current
            self.procs = procs
            self.history.append({
                "t": round(now), "cpu": cpu, "mem": vm.percent, "swap": sw.percent,
                "rx": round(rx_total), "tx": round(tx_total), "temp": current["cpu_temp"],
            })

    def _sample_procs(self, mem_total: int) -> list[dict]:
        rows = []
        umap = uid_map()
        ncpu = psutil.cpu_count() or 1
        attrs = ["pid", "ppid", "name", "uids", "memory_info", "status", "num_threads", "create_time"]
        for p in psutil.process_iter(attrs):
            try:
                cpu = p.cpu_percent(None)
            except psutil.Error:
                continue
            info = p.info
            mi = info.get("memory_info")
            if mi is None or mi.rss == 0:  # skip kernel threads
                continue
            uids = info.get("uids")
            uid = uids.real if uids else None
            rows.append({
                "pid": info["pid"],
                "ppid": info.get("ppid"),
                "name": info.get("name") or "?",
                "user": umap.get(uid, str(uid)) if uid is not None else "?",
                "cpu": round(cpu / ncpu, 1),
                "rss": mi.rss,
                "mem": round(mi.rss / mem_total * 100, 2) if mem_total else 0,
                "threads": info.get("num_threads"),
                "status": info.get("status"),
                "started": info.get("create_time"),
            })
        return rows

    def snapshot(self) -> tuple[dict, list[dict], list[dict]]:
        with self.lock:
            return dict(self.current), list(self.history), list(self.procs)


sampler = Sampler()



# --------------------------------------------------------------------------
# Disks
# --------------------------------------------------------------------------
def list_mounts() -> list[tuple[str, str, str]]:
    """Return (device, mountpoint, fstype) as the host sees them."""
    mounts: list[tuple[str, str, str]] = []
    text = None
    if HOST_ROOT:
        text = read_text("/proc/1/mounts")  # with pid: host this is the host's init
    if text:
        for line in text.splitlines():
            f = line.split()
            if len(f) >= 3:
                mnt = f[1].replace("\\040", " ")
                mounts.append((f[0], mnt, f[2]))
    else:
        for p in psutil.disk_partitions(all=True):
            mounts.append((p.device, p.mountpoint, p.fstype))
    return mounts


def disks() -> list[dict]:
    seen_dev: dict[str, dict] = {}
    out: list[dict] = []
    candidates = list_mounts()
    if DISK_PATHS:
        candidates = [c for c in candidates if c[1] in DISK_PATHS] or [("", p, "") for p in DISK_PATHS]
    for dev, mnt, fs in candidates:
        if not DISK_PATHS and fs not in REAL_FS:
            continue
        if mnt.startswith(("/snap/", "/var/lib/docker/", "/run/", "/proc", "/sys")):
            continue
        try:
            u = psutil.disk_usage(host_path(mnt))
        except (OSError, PermissionError):
            continue
        if u.total == 0:
            continue
        row = {
            "device": dev, "mount": mnt, "fstype": fs, "network": fs in NETWORK_FS,
            "total": u.total, "used": u.used, "free": u.free, "percent": u.percent,
        }
        key = dev if dev.startswith("/dev/") else f"{dev}|{mnt}"
        prev = seen_dev.get(key)
        if prev:  # same device mounted twice (bind mounts, btrfs subvols): keep shortest path
            if len(mnt) < len(prev["mount"]):
                prev.update(row)
            continue
        seen_dev[key] = row
        out.append(row)
    out.sort(key=lambda r: (r["network"], r["mount"] != "/", r["mount"]))
    return out



def nic_kind(name: str) -> str:
    if name == "lo":
        return "loopback"
    if name.startswith("tailscale"):
        return "tailscale"
    if name.startswith(("wg", "tun", "zt")):
        return "vpn"
    if name.startswith(("docker", "br-", "veth", "cni", "flannel", "virbr")):
        return "container"
    if name.startswith(("wl", "wlan")):
        return "wifi"
    return "physical"


def interfaces() -> list[dict]:
    addrs = psutil.net_if_addrs()
    stats = psutil.net_if_stats()
    counters = psutil.net_io_counters(pernic=True)
    rates = sampler.snapshot()[0].get("net_rates", {})
    rows = []
    for name, alist in addrs.items():
        if name.startswith("veth"):
            continue
        st = stats.get(name)
        c = counters.get(name)
        rows.append({
            "name": name,
            "kind": nic_kind(name),
            "up": bool(st and st.isup),
            "speed": st.speed if st else 0,
            "mtu": st.mtu if st else None,
            "ipv4": [a.address for a in alist if a.family == socket.AF_INET],
            "ipv6": [a.address.split("%")[0] for a in alist
                     if a.family == socket.AF_INET6 and not a.address.lower().startswith("fe80")],
            "mac": next((a.address for a in alist if a.family == psutil.AF_LINK), None),
            "rx": rates.get(name, {}).get("rx", 0), "tx": rates.get(name, {}).get("tx", 0),
            "rx_total": c.bytes_recv if c else 0, "tx_total": c.bytes_sent if c else 0,
            "errors": (c.errin + c.errout) if c else 0, "drops": (c.dropin + c.dropout) if c else 0,
        })
    order = {"physical": 0, "wifi": 1, "tailscale": 2, "vpn": 3, "container": 4, "loopback": 5}
    rows.sort(key=lambda r: (order.get(r["kind"], 9), r["name"]))
    return rows



# --------------------------------------------------------------------------
# Health alerts
# --------------------------------------------------------------------------
def build_alerts(cur: dict, hist: list[dict], dlist: list[dict], dock: dict) -> list[dict]:
    alerts: list[dict] = []

    def add(level: str, area: str, msg: str) -> None:
        alerts.append({"level": level, "area": area, "message": msg})

    recent = [h["cpu"] for h in hist[-15:]]
    if recent:
        avg = sum(recent) / len(recent)
        if avg >= 90:
            add("crit", "cpu", f"CPU averaging {avg:.0f}% over the last {len(recent) * SAMPLE_INTERVAL:.0f}s")
        elif avg >= 75:
            add("warn", "cpu", f"CPU averaging {avg:.0f}% over the last {len(recent) * SAMPLE_INTERVAL:.0f}s")
    mem = cur.get("mem", {}).get("percent", 0)
    if mem >= 95:
        add("crit", "memory", f"Memory at {mem:.0f}%")
    elif mem >= 85:
        add("warn", "memory", f"Memory at {mem:.0f}%")
    sw = cur.get("swap", {})
    if sw.get("total") and sw.get("percent", 0) >= 80:
        add("warn", "memory", f"Swap at {sw['percent']:.0f}%")
    ncpu = psutil.cpu_count() or 1
    load1 = (cur.get("load") or [0])[0]
    if load1 > ncpu * 1.5:
        add("warn", "cpu", f"Load average {load1} is high for {ncpu} threads")
    t = cur.get("cpu_temp")
    if t is not None:
        if t >= 90:
            add("crit", "temp", f"CPU temperature {t:.0f}°C")
        elif t >= 80:
            add("warn", "temp", f"CPU temperature {t:.0f}°C")
    for d in dlist:
        if d["percent"] >= 95:
            add("crit", "disk", f"{d['mount']} is {d['percent']:.0f}% full ({fmt_bytes(d['free'])} free)")
        elif d["percent"] >= 85:
            add("warn", "disk", f"{d['mount']} is {d['percent']:.0f}% full ({fmt_bytes(d['free'])} free)")
    if dock.get("available"):
        for c in dock.get("containers", []):
            if c["health"] == "unhealthy":
                add("crit", "docker", f"{c['name']} is unhealthy")
            elif c["state"] == "restarting":
                add("warn", "docker", f"{c['name']} is restarting (restarts: {c['restart_count']})")
            elif c["state"] == "exited" and c["exit_code"] not in (0, None) and c["restart_policy"] != "no":
                add("warn", "docker", f"{c['name']} exited with code {c['exit_code']}")
    order = {"crit": 0, "warn": 1}
    alerts.sort(key=lambda a: order.get(a["level"], 2))
    return alerts


def fmt_bytes(n: float) -> str:
    for unit in ("B", "KB", "MB", "GB", "TB", "PB"):
        if abs(n) < 1024:
            return f"{n:.1f} {unit}" if unit != "B" else f"{n:.0f} B"
        n /= 1024
    return f"{n:.1f} EB"




def sensors_info() -> dict:
    """Everything Glances shows in its sensors pane: temperatures, fans, battery, per-core clocks, users."""
    temps = read_temps()
    fans = []
    try:
        for chip, entries in (psutil.sensors_fans() or {}).items():
            for i, f in enumerate(entries):
                fans.append({"chip": chip, "label": f.label or f"{chip} {i}", "rpm": f.current})
    except Exception:
        pass
    battery = None
    try:
        b = psutil.sensors_battery()
        if b:
            battery = {"percent": b.percent, "plugged": b.power_plugged, "secs_left": b.secsleft if b.secsleft > 0 else None}
    except Exception:
        pass
    freqs = []
    try:
        freqs = [round(f.current) for f in (psutil.cpu_freq(percpu=True) or [])]
    except Exception:
        pass
    users = []
    try:
        users = [{"name": u.name, "terminal": u.terminal, "host": u.host, "started": u.started} for u in psutil.users()]
    except Exception:
        pass
    ctx = None
    try:
        st = psutil.cpu_stats()
        ctx = {"ctx_switches": st.ctx_switches, "interrupts": st.interrupts}
    except Exception:
        pass
    return {"temps": temps, "fans": fans, "battery": battery, "freqs": freqs, "users": users, "cpu_stats": ctx}
