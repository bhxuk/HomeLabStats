"""Network probes: ping, TCP, DNS, HTTP, gateway, public IP and the connectivity check runner."""
from __future__ import annotations

import json
import re
import socket
import struct
import subprocess
import threading
import time
import urllib.error
import urllib.request
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

from .config import DNS_NAMES, HTTP_CHECKS, PING_TARGETS, VERSION

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
# Single probes used by monitors. Each returns (ok, response_ms, message).
# --------------------------------------------------------------------------
def parse_expect(spec: str | None) -> list[tuple[int, int]]:
    ranges = []
    for part in (spec or "200-399").replace(" ", "").split(","):
        if not part:
            continue
        try:
            if "-" in part:
                a, b = part.split("-", 1)
                ranges.append((int(a), int(b)))
            elif part.lower().endswith("xx"):
                base = int(part[0]) * 100
                ranges.append((base, base + 99))
            else:
                ranges.append((int(part), int(part)))
        except ValueError:
            continue
    return ranges or [(200, 399)]


def probe_http(url: str, method: str = "GET", timeout: float = 10, expect: str | None = None,
               keyword: str | None = None, invert: bool = False, ignore_tls: bool = False) -> tuple[bool, float | None, str]:
    import ssl
    if not url.lower().startswith(("http://", "https://")):
        url = "http://" + url
    ctx = ssl.create_default_context()
    if ignore_tls:
        ctx.check_hostname = False
        ctx.verify_mode = ssl.CERT_NONE
    opener = urllib.request.build_opener(urllib.request.HTTPSHandler(context=ctx))
    req = urllib.request.Request(url, method=(method or "GET").upper(), headers={
        "User-Agent": f"HomeLabStats/{VERSION} (uptime monitor)", "Accept": "*/*"})
    t0 = time.perf_counter()
    status = None
    body = b""
    try:
        with opener.open(req, timeout=timeout) as r:
            status = r.status
            if keyword:
                body = r.read(2 * 1024 * 1024)
            else:
                r.read(1024)
    except urllib.error.HTTPError as exc:
        status = exc.code
        if keyword:
            try:
                body = exc.read(2 * 1024 * 1024)
            except Exception:
                body = b""
    except Exception as exc:
        reason = getattr(exc, "reason", exc)
        return False, None, _short(reason)
    ms = (time.perf_counter() - t0) * 1000
    ok_status = any(a <= status <= b for a, b in parse_expect(expect))
    if not ok_status:
        return False, ms, f"HTTP {status} (expected {expect or '200-399'})"
    if keyword:
        found = keyword.lower() in body.decode("utf-8", errors="replace").lower()
        if found == bool(invert):
            return False, ms, f"HTTP {status}, keyword {'found' if found else 'not found'}: {keyword}"
        return True, ms, f"HTTP {status}, keyword {'absent' if invert else 'found'}"
    return True, ms, f"HTTP {status}"


def probe_tcp(host: str, port: int, timeout: float = 10) -> tuple[bool, float | None, str]:
    t0 = time.perf_counter()
    try:
        with socket.create_connection((host, int(port)), timeout=timeout):
            return True, (time.perf_counter() - t0) * 1000, f"Port {port} open"
    except Exception as exc:
        return False, None, _short(exc)


def probe_ping(host: str, timeout: float = 10) -> tuple[bool, float | None, str]:
    r = ping_host(host, count=3)
    if r["ok"]:
        return True, r.get("avg"), f"{r.get('avg')} ms, {r.get('loss', 0)}% loss" + (f" ({r['method']})" if r["method"] != "icmp" else "")
    return False, None, r.get("error") or f"{r.get('loss', 100)}% loss"


def probe_dns(name: str, timeout: float = 10) -> tuple[bool, float | None, str]:
    r = dns_check(name)
    if r["ok"]:
        return True, r["ms"], ", ".join(r["addresses"])
    return False, None, r.get("error", "lookup failed")


def _short(exc) -> str:
    s = str(exc)
    for pat, nice in (("timed out", "Timed out"), ("Connection refused", "Connection refused"),
                      ("Name or service not known", "Host not found"), ("No address associated", "Host not found"),
                      ("CERTIFICATE_VERIFY_FAILED", "TLS certificate not valid"), ("Network is unreachable", "Network unreachable"),
                      ("No route to host", "No route to host")):
        if pat in s:
            return nice
    return s[:200]
