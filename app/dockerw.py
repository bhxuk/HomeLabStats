"""Docker: container list, live stats, actions, logs and disk usage."""
from __future__ import annotations

import re
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

from .config import DOCKER_INTERVAL, iso_to_ts

# --------------------------------------------------------------------------
# Docker
# --------------------------------------------------------------------------
ACTIONS = ("start", "stop", "restart", "pause", "unpause", "kill", "remove")
LOG_TS_RE = re.compile(r"^(\d{4}-\d\d-\d\dT\d\d:\d\d:\d\d(?:\.\d+)?Z) ")


def _own_container_id() -> str | None:
    """The container ID HomeLabStats itself runs in, if any (so the UI can protect it)."""
    try:
        text = Path("/proc/self/cgroup").read_text() + Path("/proc/self/mountinfo").read_text()
    except OSError:
        return None
    m = re.search(r"(?:docker[-/]|/containers/)([0-9a-f]{64})", text)
    return m.group(1) if m else None


class DockerWatcher:
    def __init__(self) -> None:
        self.lock = threading.Lock()
        self.client = None
        self.events = None  # set by main once the event log exists
        self.data: dict = {"available": False, "error": "Not polled yet", "containers": [], "info": {}}
        self.prev: dict[str, dict] = {}
        self.recent_actions: dict[str, float] = {}
        self.self_id = _own_container_id()
        self._df_cache: tuple[float, dict] | None = None

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
            listening = self._listening_ports()
            for r in rows:
                r["is_self"] = bool(self.self_id and r["full_id"] == self.self_id)
                if r["network_mode"] == "host" and r["state"] == "running":
                    r["host_ports"] = listening.get(r["full_id"], [])
            rows.sort(key=lambda r: (r["state"] != "running", r["name"].lower()))
            self._diff(rows)
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

    def _listening_ports(self) -> dict[str, list[int]]:
        """TCP ports that each container's processes listen on. Used for host-network containers
        (Plex, Home Assistant...) where Docker itself has no port mappings to show."""
        cached = getattr(self, "_lp_cache", None)
        if cached and time.time() - cached[0] < 60:
            return cached[1]
        out: dict[str, set[int]] = {}
        cg_cache: dict[int, str | None] = {}
        try:
            import psutil
            conns = psutil.net_connections("tcp")
        except Exception:
            conns = []
        for c in conns:
            if c.status != "LISTEN" or not c.pid or not c.laddr:
                continue
            if c.laddr.ip.startswith("127.") or c.laddr.ip == "::1":
                continue
            if c.pid not in cg_cache:
                try:
                    m = re.search(r"([0-9a-f]{64})", Path(f"/proc/{c.pid}/cgroup").read_text())
                    cg_cache[c.pid] = m.group(1) if m else None
                except OSError:
                    cg_cache[c.pid] = None
            cid = cg_cache[c.pid]
            if cid:
                out.setdefault(cid, set()).add(c.laddr.port)
        result = {k: sorted(v) for k, v in out.items()}
        self._lp_cache = (time.time(), result)
        return result

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
        ports, port_list, seen = [], [], set()
        for cport, binds in ((a.get("NetworkSettings", {}) or {}).get("Ports") or {}).items():
            cnum, _, proto = cport.partition("/")
            for b in binds or []:
                try:
                    hp = int(b.get("HostPort") or 0)
                except ValueError:
                    continue
                if not hp or (hp, proto) in seen:
                    continue
                seen.add((hp, proto))
                ports.append(f"{hp}:{cport}")
                port_list.append({"host": hp, "container": int(cnum) if cnum.isdigit() else None, "proto": proto or "tcp",
                                  "ip": b.get("HostIp") or ""})
        ports.sort(key=lambda x: (len(x), x))
        port_list.sort(key=lambda p: (p["proto"] != "tcp", p["host"]))
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
            "port_list": port_list,
            "host_ports": [],
            "url_label": labels.get("homelabstats.url") or labels.get("homepage.href") or None,
            "network_mode": net_mode,
            "project": labels.get("com.docker.compose.project"),
            "stats": stats,
        }

    def snapshot(self) -> dict:
        with self.lock:
            return dict(self.data)

    def name_map(self) -> dict[str, str]:
        return {c["full_id"]: c["name"] for c in self.snapshot().get("containers", [])}


    # ---- change detection ---------------------------------------------------
    def _diff(self, rows: list[dict]) -> None:
        if self.events is None:
            self.prev = {r["full_id"]: r for r in rows}
            return
        now = time.time()
        first = not self.prev
        for r in rows:
            old = self.prev.get(r["full_id"])
            if first or not old:
                continue
            ours = now - self.recent_actions.get(r["name"], 0) < 60
            if old["state"] == "running" and r["state"] in ("exited", "dead") and not ours:
                code = r.get("exit_code")
                level = "warn" if code in (0, None) else "crit"
                self.events.log("docker", level, f"{r['name']} stopped",
                                f"Container {r['name']} stopped with exit code {code}.",
                                notify="container_stopped" if code not in (0, None) else None)
            elif old["state"] != "running" and r["state"] == "running" and not ours:
                self.events.log("docker", "info", f"{r['name']} started", f"Container {r['name']} is running.")
            if old.get("health") != "unhealthy" and r.get("health") == "unhealthy":
                self.events.log("docker", "crit", f"{r['name']} is unhealthy",
                                f"Docker health check for {r['name']} is failing.", notify="container_unhealthy")
            if r["restart_count"] > old.get("restart_count", 0) + 2:
                self.events.log("docker", "warn", f"{r['name']} keeps restarting",
                                f"Restart count is now {r['restart_count']}.", notify="container_stopped",
                                cooldown_key=f"restarts:{r['name']}", cooldown=3600)
        if not first:
            for fid, old in self.prev.items():
                if fid not in {r["full_id"] for r in rows} and not now - self.recent_actions.get(old["name"], 0) < 60:
                    self.events.log("docker", "info", f"{old['name']} removed", f"Container {old['name']} no longer exists.")
        self.prev = {r["full_id"]: r for r in rows}

    # ---- actions ------------------------------------------------------------
    def find(self, cid: str):
        return self._client().containers.get(cid)

    def action(self, cid: str, action: str, user: str = "admin", remove_volumes: bool = False) -> dict:
        if action not in ACTIONS:
            raise ValueError("Unknown action")
        ct = self.find(cid)
        name = ct.name
        if self.self_id and ct.id == self.self_id and action in ("stop", "kill", "remove", "pause"):
            raise ValueError("That would shut down HomeLabStats itself. Use restart instead.")
        self.recent_actions[name] = time.time()
        if action == "remove":
            if ct.status == "running":
                raise ValueError("Stop the container before removing it.")
            ct.remove(v=remove_volumes)
        elif action == "stop":
            ct.stop(timeout=20)
        elif action == "restart":
            ct.restart(timeout=20)
        else:
            getattr(ct, action)()
        verb = {"start": "started", "stop": "stopped", "restart": "restarted", "pause": "paused",
                "unpause": "resumed", "kill": "killed", "remove": "removed"}[action]
        if self.events:
            self.events.log("docker", "info", f"{name} {verb}", f"{user} {verb} {name} from HomeLabStats.")
        threading.Thread(target=self.poll, daemon=True).start()
        return {"ok": True, "action": action, "container": name}

    def inspect(self, cid: str) -> dict:
        a = self.find(cid).attrs
        cfg, hc, st = a.get("Config", {}) or {}, a.get("HostConfig", {}) or {}, a.get("State", {}) or {}
        labels = cfg.get("Labels") or {}
        health = st.get("Health") or {}
        mounts = [{"type": m.get("Type"), "source": m.get("Source") or m.get("Name"), "dest": m.get("Destination"),
                   "rw": m.get("RW")} for m in a.get("Mounts", [])]
        nets = [{"name": k, "ip": v.get("IPAddress"), "gateway": v.get("Gateway")}
                for k, v in ((a.get("NetworkSettings", {}) or {}).get("Networks") or {}).items()]
        env_keys = sorted({e.split("=", 1)[0] for e in (cfg.get("Env") or [])})
        return {
            "id": a.get("Id", "")[:12], "name": a.get("Name", "").lstrip("/"), "image": cfg.get("Image"),
            "image_id": (a.get("Image") or "")[7:19], "created": iso_to_ts(a.get("Created")),
            "started": iso_to_ts(st.get("StartedAt")), "finished": iso_to_ts(st.get("FinishedAt")),
            "state": st.get("Status"), "exit_code": st.get("ExitCode"), "oom_killed": st.get("OOMKilled"),
            "error": st.get("Error") or None, "restart_count": a.get("RestartCount"),
            "restart_policy": (hc.get("RestartPolicy") or {}).get("Name") or "no",
            "command": " ".join((cfg.get("Entrypoint") or []) + (cfg.get("Cmd") or [])),
            "workdir": cfg.get("WorkingDir"), "user": cfg.get("User") or "root",
            "network_mode": hc.get("NetworkMode"), "privileged": hc.get("Privileged"),
            "mem_limit": hc.get("Memory") or None, "cpu_limit": (hc.get("NanoCpus") or 0) / 1e9 or None,
            "mounts": mounts, "networks": nets, "env_keys": env_keys,
            "ports": sorted({f"{b.get('HostIp') or '0.0.0.0'}:{b.get('HostPort')} -> {p}" for p, bs in
                             ((a.get("NetworkSettings", {}) or {}).get("Ports") or {}).items() for b in (bs or [])}),
            "compose_project": labels.get("com.docker.compose.project"),
            "compose_service": labels.get("com.docker.compose.service"),
            "compose_dir": labels.get("com.docker.compose.project.working_dir"),
            "health": {"status": health.get("Status"), "failing_streak": health.get("FailingStreak"),
                       "log": [{"start": iso_to_ts(h.get("Start")), "exit": h.get("ExitCode"),
                                "output": (h.get("Output") or "").strip()[-300:]} for h in (health.get("Log") or [])[-5:]]},
        }

    def logs(self, cid: str, tail: int = 300, since: float | None = None) -> dict:
        ct = self.find(cid)
        kwargs = {"timestamps": True}
        if since:
            kwargs["since"] = since
        else:
            kwargs["tail"] = max(1, min(int(tail), 20000))
        raw = ct.logs(**kwargs).decode("utf-8", errors="replace")
        lines = raw.splitlines()
        last_ts = None
        if lines:
            m = LOG_TS_RE.match(lines[-1])
            if m:
                last_ts = m.group(1)
        return {"name": ct.name, "state": ct.status, "lines": lines, "last_ts": last_ts}

    def disk_usage(self, force: bool = False) -> dict:
        if not force and self._df_cache and time.time() - self._df_cache[0] < 120:
            return self._df_cache[1]
        df = self._client().df()
        images = df.get("Images") or []
        used_ids = {c.get("ImageID") for c in (df.get("Containers") or [])}
        dangling = [i for i in images if not i.get("RepoTags") or i.get("RepoTags") == ["<none>:<none>"]]
        unused = [i for i in images if i.get("Id") not in used_ids]
        vols = df.get("Volumes") or []
        cache = df.get("BuildCache") or []
        out = {
            "images": {"count": len(images), "size": sum(i.get("Size", 0) for i in images),
                       "unused_count": len(unused), "unused_size": sum(i.get("Size", 0) for i in unused),
                       "dangling_count": len(dangling), "dangling_size": sum(i.get("Size", 0) for i in dangling)},
            "containers": {"count": len(df.get("Containers") or []),
                           "size": sum(c.get("SizeRw", 0) or 0 for c in (df.get("Containers") or [])),
                           "stopped": sum(1 for c in (df.get("Containers") or []) if c.get("State") != "running")},
            "volumes": {"count": len(vols), "size": sum(((v.get("UsageData") or {}).get("Size") or 0) for v in vols),
                        "unused_count": sum(1 for v in vols if ((v.get("UsageData") or {}).get("RefCount") or 0) == 0)},
            "build_cache": {"count": len(cache), "size": sum(c.get("Size", 0) for c in cache),
                            "reclaimable": sum(c.get("Size", 0) for c in cache if not c.get("InUse"))},
            "top_images": sorted([{"tag": (i.get("RepoTags") or ["<none>"])[0], "size": i.get("Size", 0),
                                   "in_use": i.get("Id") in used_ids, "created": i.get("Created")} for i in images],
                                 key=lambda x: -x["size"])[:15],
            "time": time.time(),
        }
        self._df_cache = (time.time(), out)
        return out

    def prune(self, target: str) -> dict:
        c = self._client()
        if target == "images_dangling":
            r = c.images.prune(filters={"dangling": True})
        elif target == "images_unused":
            r = c.images.prune(filters={"dangling": False})
        elif target == "build_cache":
            r = c.api.prune_builds()
        elif target == "containers":
            r = c.containers.prune()
        elif target == "networks":
            r = c.networks.prune()
        else:
            raise ValueError("Unknown prune target")
        freed = (r or {}).get("SpaceReclaimed") or 0
        removed = len((r or {}).get("ImagesDeleted") or (r or {}).get("ContainersDeleted") or
                      (r or {}).get("NetworksDeleted") or (r or {}).get("CachesDeleted") or [])
        self._df_cache = None
        if self.events:
            self.events.log("docker", "info", f"Docker cleanup: {target.replace('_', ' ')}",
                            f"Removed {removed} item(s), freed {freed / 1e9:.2f} GB.")
        return {"target": target, "freed": freed, "removed": removed}


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
