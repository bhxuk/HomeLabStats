"""HomeLabStats: a lightweight self-hosted health dashboard for a Linux server.

Shows CPU, memory, processes, Docker containers, disks, network checks
and speed tests. Designed to run in Docker with host PID/network access,
or directly on the host as a systemd service.
"""
from __future__ import annotations

import http.client
import json
import os
import platform
import re
import secrets
import socket
import ssl
import struct
import subprocess
import threading
import time
import urllib.request
from collections import deque
from concurrent.futures import ThreadPoolExecutor
from contextlib import asynccontextmanager
from datetime import datetime, timezone
from pathlib import Path

import psutil
from fastapi import Depends, FastAPI, HTTPException
from fastapi.responses import FileResponse, PlainTextResponse
from fastapi.security import HTTPBasic, HTTPBasicCredentials

from .updater import INSTALL_METHOD, local_version, updater, vtuple

VERSION = local_version()


# --------------------------------------------------------------------------
# Config
# --------------------------------------------------------------------------
def env_bool(name: str, default: bool = False) -> bool:
    v = os.environ.get(name)
    if v is None:
        return default
    return v.strip().lower() in ("1", "true", "yes", "on")


def env_list(name: str, default: str) -> list[str]:
    return [x.strip() for x in os.environ.get(name, default).split(",") if x.strip()]


HOST_ROOT = os.environ.get("HOST_ROOT", "").rstrip("/")
DATA_DIR = Path(os.environ.get("DATA_DIR", Path(__file__).resolve().parent.parent / "data"))
DASH_USER = os.environ.get("DASH_USER", "admin")
DASH_PASSWORD = os.environ.get("DASH_PASSWORD", "")
ALLOW_ACTIONS = env_bool("ALLOW_CONTAINER_ACTIONS", False)
PING_TARGETS = env_list("PING_TARGETS", "1.1.1.1,8.8.8.8,google.com")
DNS_NAMES = env_list("DNS_NAMES", "google.com,cloudflare.com,github.com")
HTTP_CHECKS = env_list("HTTP_CHECKS", "https://www.google.com/generate_204,https://github.com")
SAMPLE_INTERVAL = float(os.environ.get("SAMPLE_INTERVAL", "2"))
HISTORY_POINTS = int(os.environ.get("HISTORY_POINTS", "180"))
DOCKER_INTERVAL = float(os.environ.get("DOCKER_INTERVAL", "5"))
SPEEDTEST_INTERVAL_HOURS = float(os.environ.get("SPEEDTEST_INTERVAL_HOURS", "0"))
DISK_PATHS = env_list("DISK_PATHS", "")
STATIC_DIR = Path(__file__).resolve().parent / "static"

DATA_DIR.mkdir(parents=True, exist_ok=True)

REAL_FS = {
    "ext2", "ext3", "ext4", "xfs", "btrfs", "zfs", "vfat", "exfat", "ntfs", "ntfs3",
    "fuseblk", "f2fs", "jfs", "reiserfs", "bcachefs", "cifs", "smb3", "nfs", "nfs4",
    "fuse.mergerfs", "fuse.sshfs", "fuse.rclone",
}
NETWORK_FS = {"cifs", "smb3", "nfs", "nfs4", "fuse.sshfs", "fuse.rclone"}
PHYS_DISK_RE = re.compile(r"^(sd[a-z]+|hd[a-z]+|vd[a-z]+|xvd[a-z]+|nvme\d+n\d+|mmcblk\d+)$")
VIRTUAL_NIC_PREFIX = ("lo", "veth", "br-", "docker", "virbr", "tailscale", "wg", "tun", "zt", "cni", "flannel")
CPU_TEMP_CHIPS = ("coretemp", "k10temp", "zenpower", "cpu_thermal", "cpu-thermal", "soc_thermal", "acpitz")


def host_path(p: str) -> str:
    return f"{HOST_ROOT}{p}" if HOST_ROOT else p


def iso_to_ts(s: str | None) -> float | None:
    if not s or s.startswith("0001-"):
        return None
    try:
        return datetime.strptime(s[:19], "%Y-%m-%dT%H:%M:%S").replace(tzinfo=timezone.utc).timestamp()
    except ValueError:
        return None


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
        "allow_actions": ALLOW_ACTIONS,
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
# Docker
# --------------------------------------------------------------------------
class DockerWatcher:
    def __init__(self) -> None:
        self.lock = threading.Lock()
        self.client = None
        self.data: dict = {"available": False, "error": "Not polled yet", "containers": [], "info": {}}

    def _client(self):
        if self.client is None:
            import docker  # imported lazily so the app still runs without it
            self.client = docker.from_env(timeout=15)
        return self.client

    def run(self) -> None:
        while True:
            try:
                self.poll()
            except Exception as exc:
                print(f"[docker] {exc!r}", flush=True)
            time.sleep(DOCKER_INTERVAL)

    def poll(self) -> None:
        try:
            client = self._client()
            containers = client.containers.list(all=True)
            running = [c for c in containers if c.status == "running"]
            with ThreadPoolExecutor(max_workers=8) as ex:
                stats = dict(zip([c.id for c in running], ex.map(self._stats, running)))
            rows = [self._row(c, stats.get(c.id)) for c in containers]
            rows.sort(key=lambda r: (r["state"] != "running", r["name"].lower()))
            try:
                i = client.info()
                info = {"version": i.get("ServerVersion"), "images": i.get("Images"),
                        "driver": i.get("Driver"), "cpus": i.get("NCPU"), "mem": i.get("MemTotal")}
            except Exception:
                info = {}
            data = {"available": True, "error": None, "containers": rows, "info": info, "time": time.time()}
        except Exception as exc:
            self.client = None
            data = {"available": False, "error": str(exc), "containers": [], "info": {}, "time": time.time()}
        with self.lock:
            self.data = data

    @staticmethod
    def _stats(ct) -> dict | None:
        try:
            s = ct.stats(stream=False)
        except Exception:
            return None
        try:
            cpu_s, pre = s.get("cpu_stats", {}), s.get("precpu_stats", {})
            cpu_delta = cpu_s.get("cpu_usage", {}).get("total_usage", 0) - pre.get("cpu_usage", {}).get("total_usage", 0)
            sys_delta = cpu_s.get("system_cpu_usage", 0) - pre.get("system_cpu_usage", 0)
            ncpu = cpu_s.get("online_cpus") or len(cpu_s.get("cpu_usage", {}).get("percpu_usage") or []) or 1
            cpu_pct = (cpu_delta / sys_delta) * ncpu * 100 if sys_delta > 0 and cpu_delta > 0 else 0.0
            mem = s.get("memory_stats", {})
            mstats = mem.get("stats", {})
            cache = mstats.get("inactive_file", mstats.get("total_inactive_file", 0))
            mem_used = max(mem.get("usage", 0) - cache, 0)
            mem_limit = mem.get("limit", 0)
            rx = tx = 0
            for n in (s.get("networks") or {}).values():
                rx += n.get("rx_bytes", 0)
                tx += n.get("tx_bytes", 0)
            blk_r = blk_w = 0
            for e in (s.get("blkio_stats", {}).get("io_service_bytes_recursive") or []):
                op = (e.get("op") or "").lower()
                if op == "read":
                    blk_r += e.get("value", 0)
                elif op == "write":
                    blk_w += e.get("value", 0)
            return {
                "cpu": round(cpu_pct / ncpu, 2),  # percent of whole machine, matches the process view
                "cpu_cores": round(cpu_pct, 1),  # docker stats style (100% = one core)
                "mem_used": mem_used, "mem_limit": mem_limit,
                "mem_pct": round(mem_used / mem_limit * 100, 2) if mem_limit else 0,
                "net_rx": rx, "net_tx": tx, "blk_read": blk_r, "blk_write": blk_w,
                "pids": s.get("pids_stats", {}).get("current"),
            }
        except Exception:
            return None

    @staticmethod
    def _row(ct, stats: dict | None) -> dict:
        a = ct.attrs or {}
        st = a.get("State", {}) or {}
        cfg = a.get("Config", {}) or {}
        labels = cfg.get("Labels") or {}
        ports = []
        for cport, binds in ((a.get("NetworkSettings", {}) or {}).get("Ports") or {}).items():
            for b in binds or []:
                ports.append(f"{b.get('HostPort')}:{cport}")
        ports = sorted(set(ports), key=lambda x: (len(x), x))
        net_mode = (a.get("HostConfig", {}) or {}).get("NetworkMode", "")
        return {
            "id": ct.id[:12],
            "full_id": ct.id,
            "name": ct.name,
            "image": cfg.get("Image") or (ct.image.tags[0] if ct.image and ct.image.tags else "?"),
            "state": st.get("Status", ct.status),
            "health": (st.get("Health") or {}).get("Status"),
            "exit_code": st.get("ExitCode"),
            "started": iso_to_ts(st.get("StartedAt")),
            "finished": iso_to_ts(st.get("FinishedAt")),
            "created": iso_to_ts(a.get("Created")),
            "restart_count": a.get("RestartCount", 0),
            "restart_policy": ((a.get("HostConfig", {}) or {}).get("RestartPolicy") or {}).get("Name") or "no",
            "ports": ports,
            "network_mode": net_mode,
            "project": labels.get("com.docker.compose.project"),
            "stats": stats,
        }

    def snapshot(self) -> dict:
        with self.lock:
            return dict(self.data)

    def name_map(self) -> dict[str, str]:
        return {c["full_id"]: c["name"] for c in self.snapshot().get("containers", [])}


docker_watch = DockerWatcher()
CGROUP_ID_RE = re.compile(r"([0-9a-f]{64})")


def container_of(pid: int, names: dict[str, str]) -> str | None:
    try:
        text = Path(f"/proc/{pid}/cgroup").read_text()
    except OSError:
        return None
    if "docker" not in text and "containerd" not in text:
        return None
    m = CGROUP_ID_RE.search(text)
    if not m:
        return None
    return names.get(m.group(1), m.group(1)[:12])


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


# --------------------------------------------------------------------------
# Network
# --------------------------------------------------------------------------
def default_gateway() -> tuple[str | None, str | None]:
    try:
        for line in Path("/proc/net/route").read_text().splitlines()[1:]:
            f = line.split()
            if len(f) > 3 and f[1] == "00000000" and int(f[3], 16) & 2:
                return f[0], socket.inet_ntoa(struct.pack("<L", int(f[2], 16)))
    except (OSError, ValueError):
        pass
    return None, None


def tcp_ping(host: str, port: int = 443, count: int = 4) -> dict:
    times = []
    err = None
    for _ in range(count):
        t0 = time.perf_counter()
        try:
            with socket.create_connection((host, port), timeout=2):
                times.append((time.perf_counter() - t0) * 1000)
        except ConnectionRefusedError:  # host answered with a reset, so it is up
            times.append((time.perf_counter() - t0) * 1000)
        except OSError as exc:
            err = str(exc)
    res = {"target": host, "method": f"tcp/{port}", "ok": bool(times),
           "loss": round((count - len(times)) / count * 100, 1), "error": None if times else err}
    if times:
        res.update(min=round(min(times), 2), avg=round(sum(times) / len(times), 2), max=round(max(times), 2),
                   jitter=round(sum(abs(a - b) for a, b in zip(times, times[1:])) / max(len(times) - 1, 1), 2))
    return res


def ping_host(host: str, count: int = 4) -> dict:
    try:
        r = subprocess.run(["ping", "-n", "-c", str(count), "-i", "0.2", "-W", "2", host],
                           capture_output=True, text=True, timeout=20)
    except FileNotFoundError:
        return tcp_ping(host)
    except subprocess.TimeoutExpired:
        return {"target": host, "method": "icmp", "ok": False, "loss": 100.0, "error": "timeout"}
    out = (r.stdout or "") + (r.stderr or "")
    if "not permitted" in out.lower() or "permission denied" in out.lower():
        return tcp_ping(host)
    loss = re.search(r"([\d.]+)% packet loss", out)
    rtt = re.search(r"= ([\d.]+)/([\d.]+)/([\d.]+)/([\d.]+) ms", out)
    res = {"target": host, "method": "icmp", "ok": r.returncode == 0,
           "loss": float(loss.group(1)) if loss else 100.0, "error": None}
    if rtt:
        res.update(min=float(rtt.group(1)), avg=float(rtt.group(2)), max=float(rtt.group(3)), jitter=float(rtt.group(4)))
    if r.returncode != 0:
        lines = [x for x in out.strip().splitlines() if x.strip()]
        res["error"] = lines[-1] if lines else "unreachable"
    return res


def dns_check(name: str) -> dict:
    t0 = time.perf_counter()
    try:
        infos = socket.getaddrinfo(name, None)
        ms = (time.perf_counter() - t0) * 1000
        addrs = sorted({i[4][0] for i in infos}, key=lambda a: (":" in a, a))[:3]
        return {"name": name, "ok": True, "ms": round(ms, 1), "addresses": addrs}
    except socket.gaierror as exc:
        return {"name": name, "ok": False, "ms": round((time.perf_counter() - t0) * 1000, 1), "error": str(exc)}


def http_check(url: str) -> dict:
    t0 = time.perf_counter()
    try:
        req = urllib.request.Request(url, headers={"User-Agent": f"homelabstats/{VERSION}"})
        with urllib.request.urlopen(req, timeout=8) as r:
            r.read(1024)
            return {"url": url, "ok": 200 <= r.status < 400, "status": r.status,
                    "ms": round((time.perf_counter() - t0) * 1000, 1)}
    except Exception as exc:
        status = getattr(exc, "code", None)
        return {"url": url, "ok": False, "status": status, "ms": round((time.perf_counter() - t0) * 1000, 1),
                "error": str(exc)}


def public_ip() -> dict:
    for url in ("https://api.ipify.org?format=json", "https://ifconfig.co/json"):
        try:
            req = urllib.request.Request(url, headers={"User-Agent": f"homelabstats/{VERSION}", "Accept": "application/json"})
            with urllib.request.urlopen(req, timeout=6) as r:
                d = json.loads(r.read().decode())
                return {"ip": d.get("ip"), "source": url.split("/")[2]}
        except Exception:
            continue
    return {"ip": None, "error": "Could not determine public IP"}


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


class NetworkChecker:
    def __init__(self) -> None:
        self.lock = threading.Lock()
        self.running = False
        self.last: dict | None = None

    def run_checks(self) -> dict:
        with self.lock:
            if self.running:
                return {"busy": True}
            self.running = True
        try:
            iface, gw = default_gateway()
            with ThreadPoolExecutor(max_workers=12) as ex:
                gw_f = ex.submit(ping_host, gw) if gw else None
                ping_f = [ex.submit(ping_host, t) for t in PING_TARGETS]
                dns_f = [ex.submit(dns_check, n) for n in DNS_NAMES]
                http_f = [ex.submit(http_check, u) for u in HTTP_CHECKS]
                ip_f = ex.submit(public_ip)
                result = {
                    "time": time.time(),
                    "gateway": {"interface": iface, "ip": gw, "ping": gw_f.result() if gw_f else None},
                    "pings": [f.result() for f in ping_f],
                    "dns": [f.result() for f in dns_f],
                    "http": [f.result() for f in http_f],
                    "public_ip": ip_f.result(),
                }
            ok = [result["gateway"]["ping"]["ok"]] if result["gateway"]["ping"] else []
            ok += [p["ok"] for p in result["pings"]] + [d["ok"] for d in result["dns"]] + [h["ok"] for h in result["http"]]
            result["summary"] = {"passed": sum(ok), "total": len(ok)}
            self.last = result
            return result
        finally:
            with self.lock:
                self.running = False


net_checker = NetworkChecker()


# --------------------------------------------------------------------------
# Speed test (Cloudflare by default, Ookla via speedtest-cli optional)
# --------------------------------------------------------------------------
CF_HOST = "speed.cloudflare.com"


class SpeedTester:
    def __init__(self) -> None:
        self.lock = threading.Lock()
        self.file = DATA_DIR / "speedtests.json"
        self.running = False
        self.phase: str | None = None
        self.engine: str | None = None
        self.error: str | None = None
        self.live: dict = {}
        self.history: list[dict] = self._load()

    def _load(self) -> list[dict]:
        try:
            return json.loads(self.file.read_text())
        except (OSError, ValueError):
            return []

    def _save(self) -> None:
        tmp = self.file.with_suffix(".tmp")
        tmp.write_text(json.dumps(self.history[:200]))
        tmp.replace(self.file)

    def status(self) -> dict:
        live = dict(self.live)
        if live.get("start") and self.phase in ("download", "upload"):
            elapsed = max(time.perf_counter() - live["start"], 0.001)
            live = {"mbps": round(live["bytes"][0] * 8 / elapsed / 1e6, 1), "elapsed": round(elapsed, 1)}
        else:
            live = {}
        return {"running": self.running, "phase": self.phase, "engine": self.engine, "error": self.error,
                "live": live, "last": self.history[0] if self.history else None, "history": self.history[:50]}

    def start(self, engine: str = "cloudflare") -> bool:
        with self.lock:
            if self.running:
                return False
            self.running = True
            self.engine = engine
            self.error = None
            self.phase = "starting"
        threading.Thread(target=self._run, args=(engine,), daemon=True).start()
        return True

    def _run(self, engine: str) -> None:
        try:
            res = self._ookla() if engine == "ookla" else self._cloudflare()
            res["time"] = time.time()
            res["engine"] = engine
            self.history.insert(0, res)
            self._save()
        except Exception as exc:
            self.error = f"{type(exc).__name__}: {exc}"
        finally:
            self.phase = None
            self.live = {}
            self.running = False

    # Cloudflare -----------------------------------------------------------
    @staticmethod
    def _conn() -> http.client.HTTPSConnection:
        return http.client.HTTPSConnection(CF_HOST, timeout=15, context=ssl.create_default_context())

    def _cloudflare(self) -> dict:
        headers = {"User-Agent": f"homelabstats/{VERSION}"}
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
        ordered = sorted(samples)
        latency = ordered[len(ordered) // 2]
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
                        conn.request("GET", "/__down?bytes=100000000", headers=headers)
                        r = conn.getresponse()
                        while time.perf_counter() < stop:
                            chunk = r.read(65536)
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
        if counter[0] == 0:
            raise RuntimeError(f"{direction}load failed: {errors[0] if errors else 'no data transferred'}")
        return counter[0] * 8 / elapsed / 1e6

    # Ookla ----------------------------------------------------------------
    def _ookla(self) -> dict:
        import speedtest  # speedtest-cli
        self.phase = "finding server"
        s = speedtest.Speedtest(secure=True)
        s.get_best_server()
        self.phase = "download"
        s.download()
        self.phase = "upload"
        s.upload(pre_allocate=False)
        r = s.results.dict()
        srv = r.get("server", {})
        return {"download": round(r["download"] / 1e6, 2), "upload": round(r["upload"] / 1e6, 2),
                "ping": round(r["ping"], 1), "jitter": None,
                "server": f"{srv.get('sponsor', '?')} ({srv.get('name', '?')})",
                "isp": r.get("client", {}).get("isp"), "ip": r.get("client", {}).get("ip")}

    def scheduler(self) -> None:
        if SPEEDTEST_INTERVAL_HOURS <= 0:
            return
        interval = SPEEDTEST_INTERVAL_HOURS * 3600
        while True:
            last = self.history[0]["time"] if self.history else 0
            wait = max(60, last + interval - time.time())
            time.sleep(wait)
            if not self.running:
                self.start("cloudflare")


speed = SpeedTester()


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


# --------------------------------------------------------------------------
# API
# --------------------------------------------------------------------------
security = HTTPBasic(auto_error=False)


def auth(creds: HTTPBasicCredentials | None = Depends(security)) -> None:
    if not DASH_PASSWORD:
        return
    if creds is None or not (
        secrets.compare_digest(creds.username.encode(), DASH_USER.encode())
        and secrets.compare_digest(creds.password.encode(), DASH_PASSWORD.encode())
    ):
        raise HTTPException(status_code=401, detail="Unauthorized", headers={"WWW-Authenticate": 'Basic realm="homelabstats"'})


@asynccontextmanager
async def lifespan(_app: FastAPI):
    for target in (sampler.run, docker_watch.run, speed.scheduler, updater.scheduler):
        threading.Thread(target=target, daemon=True).start()
    yield


app = FastAPI(title="HomeLabStats", version=VERSION, dependencies=[Depends(auth)], lifespan=lifespan,
              docs_url="/api/docs", redoc_url=None, openapi_url="/api/openapi.json")


@app.get("/")
def index() -> FileResponse:
    return FileResponse(STATIC_DIR / "index.html", headers={"Cache-Control": "no-cache"})


@app.get("/demo.js", include_in_schema=False)
def demo_js() -> FileResponse:
    return FileResponse(STATIC_DIR / "demo.js", media_type="application/javascript")


@app.get("/api/overview")
def api_overview() -> dict:
    cur, hist, procs = sampler.snapshot()
    dlist = disks()
    dock = docker_watch.snapshot()
    containers = dock.get("containers", [])
    alerts = build_alerts(cur, hist, dlist, dock)
    level = "crit" if any(a["level"] == "crit" for a in alerts) else "warn" if alerts else "ok"
    top_cpu = sorted(procs, key=lambda p: p["cpu"], reverse=True)[:6]
    top_mem = sorted(procs, key=lambda p: p["rss"], reverse=True)[:6]
    return {
        "host": host_info(),
        "current": cur,
        "history": hist,
        "status": level,
        "alerts": alerts,
        "disks": dlist,
        "docker": {
            "available": dock.get("available"),
            "error": dock.get("error"),
            "running": sum(1 for c in containers if c["state"] == "running"),
            "total": len(containers),
            "unhealthy": sum(1 for c in containers if c["health"] == "unhealthy"),
        },
        "top_cpu": top_cpu,
        "top_mem": top_mem,
        "speedtest": speed.history[0] if speed.history else None,
        "update": {
            "available": bool((updater.remote or {}).get("latest"))
            and vtuple(updater.remote["latest"]) > vtuple(local_version()),
            "latest": (updater.remote or {}).get("latest"),
            "state": updater.state,
        },
    }


@app.get("/api/processes")
def api_processes(sort: str = "cpu", limit: int = 100, q: str = "", desc: bool = True) -> dict:
    _, _, procs = sampler.snapshot()
    names = docker_watch.name_map()
    q = q.strip().lower()
    rows = procs
    if q:
        filtered = []
        for p in rows:
            hay = f"{p['name']} {p['user']} {p['pid']}".lower()
            if q not in hay:
                try:
                    hay += " " + " ".join(psutil.Process(p["pid"]).cmdline()).lower()
                except psutil.Error:
                    pass
            if q in hay:
                filtered.append(p)
        rows = filtered
    keys = {"cpu": lambda p: p["cpu"], "mem": lambda p: p["rss"], "pid": lambda p: p["pid"],
            "name": lambda p: p["name"].lower(), "user": lambda p: p["user"],
            "threads": lambda p: p["threads"] or 0, "started": lambda p: p["started"] or 0}
    rows = sorted(rows, key=keys.get(sort, keys["cpu"]), reverse=desc)
    limit = max(1, min(limit, 1000))
    out = []
    for p in rows[:limit]:
        p = dict(p)
        try:
            cmd = psutil.Process(p["pid"]).cmdline()
            p["cmd"] = " ".join(cmd)[:400] if cmd else p["name"]
        except psutil.Error:
            p["cmd"] = p["name"]
        p["container"] = container_of(p["pid"], names)
        out.append(p)
    return {"total": len(procs), "matched": len(rows), "processes": out}


@app.get("/api/docker")
def api_docker() -> dict:
    return docker_watch.snapshot()


@app.get("/api/docker/{cid}/logs", response_class=PlainTextResponse)
def api_docker_logs(cid: str, tail: int = 200) -> str:
    try:
        ct = docker_watch._client().containers.get(cid)
        raw = ct.logs(tail=max(1, min(tail, 5000)), timestamps=True)
        return raw.decode("utf-8", errors="replace")
    except Exception as exc:
        raise HTTPException(status_code=404, detail=str(exc))


@app.post("/api/docker/{cid}/{action}")
def api_docker_action(cid: str, action: str) -> dict:
    if not ALLOW_ACTIONS:
        raise HTTPException(status_code=403, detail="Container actions are disabled (set ALLOW_CONTAINER_ACTIONS=true)")
    if action not in ("start", "stop", "restart"):
        raise HTTPException(status_code=400, detail="Unknown action")
    try:
        ct = docker_watch._client().containers.get(cid)
        getattr(ct, action)()
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc))
    threading.Thread(target=docker_watch.poll, daemon=True).start()
    return {"ok": True, "action": action, "container": cid}


@app.get("/api/disks")
def api_disks() -> dict:
    cur, _, _ = sampler.snapshot()
    return {"disks": disks(), "io": cur.get("disk_rates", {})}


@app.get("/api/network")
def api_network() -> dict:
    iface, gw = default_gateway()
    return {"interfaces": interfaces(), "gateway": {"interface": iface, "ip": gw},
            "last_check": net_checker.last, "check_running": net_checker.running}


@app.post("/api/network/check")
def api_network_check() -> dict:
    res = net_checker.run_checks()
    if res.get("busy"):
        raise HTTPException(status_code=409, detail="A check is already running")
    return res


@app.get("/api/speedtest")
def api_speedtest() -> dict:
    return speed.status()


@app.post("/api/speedtest")
def api_speedtest_start(engine: str = "cloudflare") -> dict:
    if engine not in ("cloudflare", "ookla"):
        raise HTTPException(status_code=400, detail="engine must be cloudflare or ookla")
    if not speed.start(engine):
        raise HTTPException(status_code=409, detail="A speed test is already running")
    return speed.status()


@app.delete("/api/speedtest")
def api_speedtest_clear() -> dict:
    speed.history = []
    speed._save()
    return {"ok": True}


@app.get("/api/update")
def api_update(check: bool = True, force: bool = False) -> dict:
    return updater.status(check=check, force=force)


@app.post("/api/update")
def api_update_start() -> dict:
    if not updater.start():
        raise HTTPException(status_code=409, detail=updater.error or "An update is already running")
    return updater.status()


@app.get("/api/health", include_in_schema=False)
def api_health() -> dict:
    return {"ok": True, "version": VERSION}


def main() -> None:
    import uvicorn
    uvicorn.run(app, host=os.environ.get("BIND", "0.0.0.0"), port=int(os.environ.get("PORT", "8090")),
                log_level=os.environ.get("LOG_LEVEL", "warning"))


if __name__ == "__main__":
    main()
