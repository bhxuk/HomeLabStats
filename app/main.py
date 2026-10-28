"""HomeLabStats: a self-hosted health dashboard for a Linux home server.

Live system stats, processes, Docker management and logs, uptime monitors,
long-term metrics history, network checks and speed tests in one app.

Modules:
  system.py      host metrics sampler, disks, interfaces, alerts
  dockerw.py     Docker list, stats, actions, logs, disk usage
  history.py     metrics recorder and history queries (SQLite)
  monitors.py    uptime monitors and Uptime Kuma import
  speedtest.py   speed tests and their log
  checks.py      network probes and connectivity checks
  notify.py      activity log and alert channels
  appsettings.py settings changed from the dashboard
  updater.py     self-update from GitHub
"""
from __future__ import annotations

import re
import secrets
import threading
import time
from contextlib import asynccontextmanager
from datetime import datetime, timezone

import psutil
from fastapi import Body, Depends, FastAPI, HTTPException
from fastapi.responses import FileResponse, PlainTextResponse, Response
from fastapi.security import HTTPBasic, HTTPBasicCredentials
from fastapi.staticfiles import StaticFiles

from . import notify as notify_mod
from .appsettings import AppSettings
from .checks import default_gateway, net_checker
from .config import DASH_PASSWORD, DASH_USER, DATA_DIR, STATIC_DIR, VERSION
from .dockerw import container_of, docker_watch
from .history import Recorder
from .monitors import Monitors
from .notify import Events
from .speedtest import SpeedTester
from .store import Store
from .system import build_alerts, disks, host_info, interfaces, sampler, sensors_info
from .updater import local_version, updater, vtuple

# --------------------------------------------------------------------------
# Wiring
# --------------------------------------------------------------------------
store = Store(DATA_DIR / "homelabstats.db")
settings = AppSettings(store)
events = Events(store, settings)
docker_watch.events = events
speed = SpeedTester(store, settings, events)
monitors = Monitors(store, events, docker_watch)


class AlertWatcher:
    """Turns critical system alerts and new releases into notifications (rate limited)."""

    def __init__(self) -> None:
        self.last = 0.0
        self.notified_version: str | None = None

    def tick(self) -> None:
        if time.time() - self.last < 60:
            return
        self.last = time.time()
        cur, hist, _ = sampler.snapshot()
        for a in build_alerts(cur, hist, disks(), {"available": False}):
            if a["level"] == "crit":
                key = re.sub(r"[\d.]+", "#", a["message"])
                events.log("system", "crit", a["message"], f"{a['area'].upper()}: {a['message']}",
                           notify="system_alerts", cooldown_key=key, cooldown=6 * 3600)
        latest = (updater.remote or {}).get("latest")
        if latest and vtuple(latest) > vtuple(local_version()) and latest != self.notified_version:
            self.notified_version = latest
            events.log("update", "info", f"HomeLabStats {latest} is available",
                       f"You are on {local_version()}. Open the Updates tab to install it.", notify="update_available")


alert_watch = AlertWatcher()
recorder = Recorder(store, sampler, docker_watch, settings, on_tick=alert_watch.tick)

# --------------------------------------------------------------------------
# App
# --------------------------------------------------------------------------
security = HTTPBasic(auto_error=False)


def auth(creds: HTTPBasicCredentials | None = Depends(security)) -> str:
    if not DASH_PASSWORD:
        return "admin"
    if creds is None or not (
        secrets.compare_digest(creds.username.encode(), DASH_USER.encode())
        and secrets.compare_digest(creds.password.encode(), DASH_PASSWORD.encode())
    ):
        raise HTTPException(status_code=401, detail="Unauthorized", headers={"WWW-Authenticate": 'Basic realm="homelabstats"'})
    return creds.username


@asynccontextmanager
async def lifespan(_app: FastAPI):
    for target in (sampler.run, docker_watch.run, recorder.run, monitors.run, speed.scheduler, updater.scheduler):
        threading.Thread(target=target, daemon=True, name=getattr(target, "__qualname__", "worker")).start()
    events.log("system", "info", f"HomeLabStats {VERSION} started", "")
    yield


app = FastAPI(title="HomeLabStats", version=VERSION, dependencies=[Depends(auth)], lifespan=lifespan,
              docs_url="/api/docs", redoc_url=None, openapi_url="/api/openapi.json")
app.mount("/assets", StaticFiles(directory=STATIC_DIR), name="assets")


def bad(msg: str, code: int = 400) -> HTTPException:
    return HTTPException(status_code=code, detail=msg)


@app.get("/")
def index() -> FileResponse:
    return FileResponse(STATIC_DIR / "index.html", headers={"Cache-Control": "no-cache"})


@app.get("/api/health", include_in_schema=False)
def api_health() -> dict:
    return {"ok": True, "version": VERSION}


# ---- overview -------------------------------------------------------------
@app.get("/api/overview")
def api_overview() -> dict:
    cur, hist, procs = sampler.snapshot()
    dlist = disks()
    dock = docker_watch.snapshot()
    containers = dock.get("containers", [])
    alerts = build_alerts(cur, hist, dlist, dock)
    mon = monitors.summary()
    if mon.get("down"):
        alerts.insert(0, {"level": "crit", "area": "monitor",
                          "message": f"{mon['down']} monitor{'s' if mon['down'] > 1 else ''} down: {', '.join(mon['down_names'][:4])}"})
    level = "crit" if any(a["level"] == "crit" for a in alerts) else "warn" if alerts else "ok"
    return {
        "host": {**host_info(), "container_actions": settings.get("container_actions")},
        "current": cur,
        "history": hist,
        "status": level,
        "alerts": alerts,
        "disks": dlist,
        "docker": {
            "available": dock.get("available"), "error": dock.get("error"),
            "running": sum(1 for c in containers if c["state"] == "running"), "total": len(containers),
            "unhealthy": sum(1 for c in containers if c["health"] == "unhealthy"),
        },
        "monitors": mon,
        "events": events.recent(8),
        "top_cpu": sorted(procs, key=lambda p: p["cpu"], reverse=True)[:6],
        "top_mem": sorted(procs, key=lambda p: p["rss"], reverse=True)[:6],
        "speedtest": speed.last(),
        "traffic_today": recorder.today_traffic(),
        "update": {
            "available": bool((updater.remote or {}).get("latest")) and vtuple(updater.remote["latest"]) > vtuple(local_version()),
            "latest": (updater.remote or {}).get("latest"), "state": updater.state,
        },
    }


@app.get("/api/events")
def api_events(limit: int = 100, kind: str | None = None) -> list[dict]:
    return events.recent(max(1, min(limit, 1000)), kind)


# ---- processes ------------------------------------------------------------
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
                cname = container_of(p["pid"], names)
                if cname:
                    hay += " " + cname.lower()
            if q in hay:
                filtered.append(p)
        rows = filtered
    keys = {"cpu": lambda p: p["cpu"], "mem": lambda p: p["rss"], "pid": lambda p: p["pid"],
            "name": lambda p: p["name"].lower(), "user": lambda p: p["user"],
            "threads": lambda p: p["threads"] or 0, "started": lambda p: p["started"] or 0}
    rows = sorted(rows, key=keys.get(sort, keys["cpu"]), reverse=desc)
    out = []
    for p in rows[:max(1, min(limit, 1000))]:
        p = dict(p)
        try:
            cmd = psutil.Process(p["pid"]).cmdline()
            p["cmd"] = " ".join(cmd)[:400] if cmd else p["name"]
        except psutil.Error:
            p["cmd"] = p["name"]
        p["container"] = container_of(p["pid"], names)
        out.append(p)
    return {"total": len(procs), "matched": len(rows), "processes": out}


@app.post("/api/processes/{pid}/{signal}")
def api_process_signal(pid: int, signal: str, user: str = Depends(auth)) -> dict:
    if not settings.get("container_actions"):
        raise bad("Management actions are turned off in Settings", 403)
    if signal not in ("terminate", "kill"):
        raise bad("signal must be terminate or kill")
    if pid <= 1:
        raise bad("Refusing to signal PID 1")
    try:
        p = psutil.Process(pid)
        name = p.name()
        getattr(p, signal)()
    except psutil.NoSuchProcess:
        raise bad("Process no longer exists", 404)
    except psutil.AccessDenied:
        raise bad("Permission denied", 403)
    events.log("process", "warn", f"{name} ({pid}) {'killed' if signal == 'kill' else 'terminated'}",
               f"{user} sent {signal.upper()} to {name} (PID {pid}).")
    return {"ok": True}


# ---- docker ---------------------------------------------------------------
@app.get("/api/docker")
def api_docker() -> dict:
    return {**docker_watch.snapshot(), "links": settings.get("container_links") or {}}


@app.get("/api/docker/df")
def api_docker_df(force: bool = False) -> dict:
    try:
        return docker_watch.disk_usage(force)
    except Exception as exc:
        raise bad(f"Could not read Docker disk usage: {exc}", 503)


@app.post("/api/docker/prune")
def api_docker_prune(target: str = Body(..., embed=True)) -> dict:
    if not settings.get("container_actions"):
        raise bad("Management actions are turned off in Settings", 403)
    try:
        return docker_watch.prune(target)
    except ValueError as exc:
        raise bad(str(exc))
    except Exception as exc:
        raise bad(str(exc), 500)


@app.get("/api/docker/{cid}/inspect")
def api_docker_inspect(cid: str) -> dict:
    try:
        return docker_watch.inspect(cid)
    except Exception as exc:
        raise bad(str(exc), 404)


def _parse_docker_ts(s: str) -> float:
    m = re.match(r"(\d{4}-\d\d-\d\dT\d\d:\d\d:\d\d)(\.\d+)?Z?", s)
    if not m:
        raise bad("Bad since timestamp")
    base = datetime.strptime(m.group(1), "%Y-%m-%dT%H:%M:%S").replace(tzinfo=timezone.utc).timestamp()
    frac = float("0" + (m.group(2) or ".0"))
    return base + frac + 1e-6


@app.get("/api/docker/{cid}/logs")
def api_docker_logs(cid: str, tail: int = 300, since: str | None = None) -> dict:
    try:
        return docker_watch.logs(cid, tail=tail, since=_parse_docker_ts(since) if since else None)
    except HTTPException:
        raise
    except Exception as exc:
        raise bad(str(exc), 404)


@app.get("/api/docker/{cid}/logs.txt", response_class=PlainTextResponse)
def api_docker_logs_download(cid: str, tail: int = 100000) -> Response:
    try:
        data = docker_watch.logs(cid, tail=tail)
    except Exception as exc:
        raise bad(str(exc), 404)
    fname = f"{data['name']}-{time.strftime('%Y%m%d-%H%M%S')}.log"
    return PlainTextResponse("\n".join(data["lines"]) + "\n",
                             headers={"Content-Disposition": f'attachment; filename="{fname}"'})


@app.get("/api/docker/{cid}/history")
def api_docker_history(cid: str, range: str = "24h") -> dict:
    return recorder.container(cid, range)


@app.post("/api/docker/{cid}/{action}")
def api_docker_action(cid: str, action: str, remove_volumes: bool = False, user: str = Depends(auth)) -> dict:
    if not settings.get("container_actions"):
        raise bad("Container actions are turned off in Settings", 403)
    try:
        return docker_watch.action(cid, action, user=user, remove_volumes=remove_volumes)
    except ValueError as exc:
        raise bad(str(exc))
    except Exception as exc:
        raise bad(str(exc), 500)


# ---- storage, sensors, metrics history ------------------------------------
@app.get("/api/disks")
def api_disks() -> dict:
    cur, _, _ = sampler.snapshot()
    return {"disks": disks(), "io": cur.get("disk_rates", {})}


@app.get("/api/sensors")
def api_sensors() -> dict:
    return sensors_info()


@app.get("/api/metrics/system")
def api_metrics_system(range: str = "1h") -> dict:
    return recorder.system(range)


@app.get("/api/metrics/containers")
def api_metrics_containers(range: str = "1h", metric: str = "cpu", top: int = 8) -> dict:
    return recorder.containers(range, metric, max(1, min(top, 20)))


# ---- network --------------------------------------------------------------
@app.get("/api/network")
def api_network() -> dict:
    iface, gw = default_gateway()
    return {"interfaces": interfaces(), "gateway": {"interface": iface, "ip": gw},
            "last_check": net_checker.last, "check_running": net_checker.running}


@app.post("/api/network/check")
def api_network_check() -> dict:
    res = net_checker.run_checks()
    if res.get("busy"):
        raise bad("A check is already running", 409)
    return res


@app.get("/api/traffic")
def api_traffic() -> dict:
    cur, hist, _ = sampler.snapshot()
    return {"now": cur.get("net_total", {}), "per_interface": cur.get("net_rates", {}),
            "history": [{"t": h["t"], "rx": h["rx"], "tx": h["tx"]} for h in hist],
            "today": recorder.today_traffic()}


# ---- speed tests ----------------------------------------------------------
@app.get("/api/speedtest")
def api_speedtest(days: float = 30) -> dict:
    return {**speed.status(), "history": speed.history(days), "stats": speed.stats()}


@app.post("/api/speedtest")
def api_speedtest_start(engine: str | None = None) -> dict:
    if engine not in (None, "cloudflare", "ookla"):
        raise bad("engine must be cloudflare or ookla")
    if not speed.start(engine):
        raise bad("A speed test is already running", 409)
    return speed.status()


@app.get("/api/speedtest.csv", response_class=PlainTextResponse)
def api_speedtest_csv() -> Response:
    return PlainTextResponse(speed.export_csv(), media_type="text/csv",
                             headers={"Content-Disposition": 'attachment; filename="speedtests.csv"'})


@app.delete("/api/speedtest/{test_id}")
def api_speedtest_delete(test_id: int) -> dict:
    speed.delete(test_id)
    return {"ok": True}


@app.delete("/api/speedtest")
def api_speedtest_clear() -> dict:
    speed.delete(None)
    return {"ok": True}


# ---- monitors -------------------------------------------------------------
@app.get("/api/monitors")
def api_monitors() -> dict:
    return {"monitors": monitors.list(), "summary": monitors.summary()}


@app.post("/api/monitors")
def api_monitor_create(data: dict = Body(...)) -> dict:
    try:
        return monitors.create(data)
    except (ValueError, TypeError) as exc:
        raise bad(str(exc))


@app.get("/api/monitors/kuma")
def api_monitor_kuma_find() -> dict:
    path, note = monitors.find_kuma_db()
    return {"found": bool(path), "message": note}


@app.post("/api/monitors/import-kuma")
def api_monitor_kuma_import(include_notifications: bool = Body(True, embed=True)) -> dict:
    try:
        return monitors.import_kuma(include_notifications, settings)
    except ValueError as exc:
        raise bad(str(exc))
    except Exception as exc:
        raise bad(f"Import failed: {exc}", 500)


@app.get("/api/monitors/{mid}")
def api_monitor_detail(mid: int, range: str = "24h") -> dict:
    d = monitors.detail(mid, range)
    if not d:
        raise bad("Monitor not found", 404)
    return d


@app.put("/api/monitors/{mid}")
def api_monitor_update(mid: int, data: dict = Body(...)) -> dict:
    try:
        r = monitors.update(mid, data)
    except (ValueError, TypeError) as exc:
        raise bad(str(exc))
    if not r:
        raise bad("Monitor not found", 404)
    return r


@app.delete("/api/monitors/{mid}")
def api_monitor_delete(mid: int) -> dict:
    monitors.delete(mid)
    return {"ok": True}


@app.post("/api/monitors/{mid}/check")
def api_monitor_check(mid: int) -> dict:
    d = monitors.check_now(mid)
    if not d:
        raise bad("Monitor not found", 404)
    return d


@app.post("/api/monitors/test")
def api_monitor_test(data: dict = Body(...)) -> dict:
    """Run a monitor definition once without saving it (the Test button in the editor)."""
    try:
        m = {"timeout": 10, "retries": 1, **monitors.clean(data)}
        ok, ms, msg = monitors.probe(m)
    except Exception as exc:
        return {"ok": False, "ms": None, "msg": str(exc)}
    return {"ok": ok, "ms": ms, "msg": msg}


# ---- settings -------------------------------------------------------------
@app.get("/api/settings")
def api_settings() -> dict:
    counts = store.one("SELECT (SELECT COUNT(*) FROM sys_raw) AS sys_raw, (SELECT COUNT(*) FROM sys_5m) AS sys_5m, "
                       "(SELECT COUNT(*) FROM beats) AS beats, (SELECT COUNT(*) FROM speedtests) AS speedtests, "
                       "(SELECT COUNT(*) FROM events) AS events, (SELECT MIN(ts) FROM sys_5m) AS oldest")
    return {"settings": settings.all(), "db": {"path": str(store.path), "size": store.size(), **(counts or {})},
            "version": VERSION}


@app.put("/api/settings")
def api_settings_update(patch: dict = Body(...), user: str = Depends(auth)) -> dict:
    try:
        new = settings.update(patch)
    except (ValueError, TypeError) as exc:
        raise bad(str(exc))
    events.log("settings", "info", "Settings changed", f"{user} changed: {', '.join(sorted(patch))}")
    return {"settings": new}


@app.post("/api/settings/test-channel")
def api_settings_test_channel(channel: dict = Body(..., embed=True)) -> dict:
    try:
        notify_mod.send(channel, "Test alert from HomeLabStats", "If you can read this, alerts are working.", "info")
        return {"ok": True}
    except Exception as exc:
        return {"ok": False, "error": str(exc)}


@app.post("/api/settings/compact")
def api_settings_compact() -> dict:
    recorder.prune()
    store.vacuum()
    return {"ok": True, "size": store.size()}


# ---- updates --------------------------------------------------------------
@app.get("/api/update")
def api_update(check: bool = True, force: bool = False) -> dict:
    return updater.status(check=check, force=force)


@app.post("/api/update")
def api_update_start() -> dict:
    if not updater.start():
        raise bad(updater.error or "An update is already running", 409)
    events.log("update", "info", "Update started", f"Updating from {VERSION}")
    return updater.status()


def main() -> None:
    import os

    import uvicorn
    uvicorn.run(app, host=os.environ.get("BIND", "0.0.0.0"), port=int(os.environ.get("PORT", "8090")),
                log_level=os.environ.get("LOG_LEVEL", "warning"))


if __name__ == "__main__":
    main()
