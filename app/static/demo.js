/* HomeLabStats demo mode: simulated API used by the GitHub Pages preview.
   Loaded only when the dashboard is opened with ?demo or window.HLS_DEMO = true. */
(function () {
  "use strict";
  const GB = 1024 ** 3, MB = 1024 ** 2;
  const now = () => Date.now() / 1000;
  const rnd = (a, b) => a + Math.random() * (b - a);
  const clamp = (v, a, b) => Math.max(a, Math.min(b, v));
  const walk = (v, step, a, b) => clamp(v + rnd(-step, step), a, b);
  const boot = now() - (18 * 86400 + 7 * 3600 + 23 * 60);
  const CORES = 12;

  const host = {
    hostname: "homelab", os: "Ubuntu 24.04.3 LTS", kernel: "6.8.0-87-generic", arch: "x86_64",
    cpu_model: "Intel(R) Core(TM) i5-12500", cores_physical: 6, cores_logical: CORES, cpu_freq_mhz: 3412,
    boot_time: boot, version: "1.0.0", allow_actions: true,
  };

  const S = { cpu: 18, mem: 58, temp: 47, rx: 4.2e6, tx: 0.6e6, per: Array.from({ length: CORES }, () => rnd(5, 30)), burst: 0 };
  const history = [];
  function tick() {
    if (Math.random() < 0.04) S.burst = Math.floor(rnd(5, 15));
    const target = S.burst > 0 ? 62 : 16;
    if (S.burst > 0) S.burst--;
    S.cpu = clamp(S.cpu + (target - S.cpu) * 0.35 + rnd(-4, 4), 3, 97);
    S.per = S.per.map(v => clamp(v + (S.cpu - v) * 0.4 + rnd(-12, 12), 0, 100));
    S.mem = walk(S.mem, 0.4, 52, 66);
    S.temp = clamp(38 + S.cpu * 0.42 + rnd(-1.5, 1.5), 35, 92);
    const stream = Math.sin(now() / 40) > 0.2;
    S.rx = clamp((stream ? 9.5e6 : 2.1e6) * rnd(0.6, 1.4), 2e5, 1.2e8);
    S.tx = clamp((stream ? 2.4e6 : 0.4e6) * rnd(0.5, 1.5), 5e4, 4e7);
    history.push({ t: Math.round(now()), cpu: +S.cpu.toFixed(1), mem: +S.mem.toFixed(1), swap: 3.1, rx: Math.round(S.rx), tx: Math.round(S.tx), temp: +S.temp.toFixed(1) });
    if (history.length > 180) history.shift();
  }
  for (let i = 0; i < 150; i++) tick();
  history.forEach((h, i) => (h.t = Math.round(now() - (150 - i) * 2)));

  const C = (name, image, project, cpu, mem, opts = {}) => ({
    id: Math.random().toString(16).slice(2, 14), full_id: "", name, image, project,
    state: opts.state || "running", health: opts.health ?? null, exit_code: opts.exit ?? 0,
    started: now() - (opts.up ?? rnd(2, 18) * 86400), finished: opts.finished ? now() - opts.finished : null,
    created: now() - 40 * 86400, restart_count: opts.restarts || 0, restart_policy: "unless-stopped",
    ports: opts.ports || [], network_mode: opts.net || "bridge", _cpu: cpu, _mem: mem,
  });
  const containers = [
    C("plex", "lscr.io/linuxserver/plex:latest", "media", 6.5, 1.9 * GB, { net: "host", health: "healthy" }),
    C("sonarr", "lscr.io/linuxserver/sonarr:latest", "media", 0.6, 310 * MB, { ports: ["8989:8989/tcp"] }),
    C("radarr", "lscr.io/linuxserver/radarr:latest", "media", 0.5, 290 * MB, { ports: ["7878:7878/tcp"] }),
    C("prowlarr", "lscr.io/linuxserver/prowlarr:latest", "media", 0.2, 180 * MB, { ports: ["9696:9696/tcp"] }),
    C("qbittorrent", "lscr.io/linuxserver/qbittorrent:latest", "media", 2.1, 520 * MB, { ports: ["8080:8080/tcp", "6881:6881/tcp", "6881:6881/udp"] }),
    C("immich-server", "ghcr.io/immich-app/immich-server:release", "immich", 1.4, 880 * MB, { ports: ["2283:2283/tcp"], health: "healthy" }),
    C("immich-postgres", "ghcr.io/immich-app/postgres:14", "immich", 0.3, 210 * MB, { health: "healthy" }),
    C("immich-ml", "ghcr.io/immich-app/immich-machine-learning:release", "immich", 0.1, 1.1 * GB, { health: "healthy" }),
    C("homeassistant", "ghcr.io/home-assistant/home-assistant:stable", null, 0.9, 640 * MB, { net: "host" }),
    C("pihole", "pihole/pihole:latest", null, 0.2, 95 * MB, { ports: ["53:53/tcp", "53:53/udp", "8053:80/tcp"], health: "healthy" }),
    C("nginx-proxy-manager", "jc21/nginx-proxy-manager:latest", null, 0.1, 140 * MB, { ports: ["80:80/tcp", "443:443/tcp", "81:81/tcp"] }),
    C("uptime-kuma", "louislam/uptime-kuma:1", null, 0.4, 120 * MB, { ports: ["3001:3001/tcp"], health: "healthy" }),
    C("portainer", "portainer/portainer-ce:latest", null, 0.1, 60 * MB, { ports: ["9443:9443/tcp"] }),
    C("homelabstats", "homelabstats:latest", "homelabstats", 0.6, 58 * MB, { net: "host", up: 3600 * 5 }),
    C("tautulli", "lscr.io/linuxserver/tautulli:latest", "media", 0, 0, { state: "exited", exit: 0, finished: 3 * 86400 }),
    C("bazarr", "lscr.io/linuxserver/bazarr:latest", "media", 0, 0, { state: "exited", exit: 137, finished: 3 * 3600 }),
  ];
  containers.forEach(c => { c.full_id = c.id.padEnd(64, "0"); c.net_rx = rnd(0.2, 40) * GB; c.net_tx = rnd(0.05, 9) * GB; });

  const procNames = [
    ["Plex Media Server", "plex", "/usr/lib/plexmediaserver/Plex Media Server", 6, 1.2 * GB, "plex"],
    ["Plex Transcoder", "plex", "/usr/lib/plexmediaserver/Plex Transcoder -codec:0 h264 -crf 21", 9, 410 * MB, "plex"],
    ["dockerd", "root", "/usr/bin/dockerd -H fd:// --containerd=/run/containerd/containerd.sock", 0.8, 160 * MB],
    ["containerd", "root", "/usr/bin/containerd", 0.4, 70 * MB],
    ["python3", "root", "python -m app.main", 0.6, 58 * MB, "homelabstats"],
    ["Sonarr", "abc", "/app/sonarr/bin/Sonarr -nobrowser -data=/config", 0.6, 300 * MB, "sonarr"],
    ["Radarr", "abc", "/app/radarr/bin/Radarr -nobrowser -data=/config", 0.5, 280 * MB, "radarr"],
    ["Prowlarr", "abc", "/app/prowlarr/bin/Prowlarr -nobrowser -data=/config", 0.2, 170 * MB, "prowlarr"],
    ["qbittorrent-nox", "abc", "/usr/bin/qbittorrent-nox --webui-port=8080", 2, 500 * MB, "qbittorrent"],
    ["immich", "root", "node /usr/src/app/dist/main", 1.2, 820 * MB, "immich-server"],
    ["postgres", "999", "postgres: immich immich 172.18.0.4(51234) idle", 0.3, 190 * MB, "immich-postgres"],
    ["python", "root", "python -m immich_ml", 0.1, 1.05 * GB, "immich-ml"],
    ["python3", "root", "python3 -m homeassistant --config /config", 0.9, 610 * MB, "homeassistant"],
    ["pihole-FTL", "999", "/usr/bin/pihole-FTL -f", 0.2, 80 * MB, "pihole"],
    ["nginx", "root", "nginx: master process nginx", 0.1, 30 * MB, "nginx-proxy-manager"],
    ["node", "root", "node server/server.js", 0.4, 110 * MB, "uptime-kuma"],
    ["tailscaled", "root", "/usr/sbin/tailscaled --state=/var/lib/tailscale/tailscaled.state", 0.3, 45 * MB],
    ["systemd", "root", "/sbin/init splash", 0, 12 * MB],
    ["systemd-journald", "root", "/usr/lib/systemd/systemd-journald", 0.1, 40 * MB],
    ["sshd", "root", "sshd: /usr/sbin/sshd -D [listener]", 0, 9 * MB],
    ["smbd", "root", "/usr/sbin/smbd --foreground --no-process-group", 0.1, 22 * MB],
    ["node", "shaam", "node /opt/paperclip/server.js --port 3100", 0.3, 140 * MB],
    ["bash", "shaam", "-bash", 0, 6 * MB],
    ["htop", "shaam", "htop", 0.4, 5 * MB],
    ["cron", "root", "/usr/sbin/cron -f -P", 0, 3 * MB],
    ["rsyslogd", "syslog", "/usr/sbin/rsyslogd -n -iNONE", 0, 7 * MB],
    ["systemd-resolved", "systemd-resolve", "/usr/lib/systemd/systemd-resolved", 0, 13 * MB],
    ["snapd", "root", "/usr/lib/snapd/snapd", 0, 35 * MB],
  ];
  let pid = 812;
  const procs = procNames.map(([name, user, cmd, cpu, rss, container]) => ({
    pid: (pid += Math.floor(rnd(3, 400))), ppid: 1, name, user, cmd, container: container || null,
    _cpu: cpu, rss, threads: Math.floor(rnd(1, 60)), status: "sleeping", started: now() - rnd(0.2, 18) * 86400,
  }));
  procs[0].pid = 1; procs.find(p => p.name === "systemd").pid = 1; procs[0].pid = 2210;
  for (let i = 0; i < 190; i++) procs.push({ pid: 3000 + i * 7, ppid: 1, name: ["kworker", "bash", "sleep", "s6-supervise", "containerd-shim"][i % 5], user: "root", cmd: "", container: null, _cpu: 0, rss: rnd(1, 12) * MB, threads: 1, status: "sleeping", started: now() - rnd(0, 18) * 86400 });
  procs.forEach(p => { if (!p.cmd) p.cmd = p.name; });

  const disks = [
    { device: "/dev/nvme0n1p2", mount: "/", fstype: "ext4", total: 468 * GB, used: 187 * GB },
    { device: "/dev/nvme0n1p1", mount: "/boot/efi", fstype: "vfat", total: 1.05 * GB, used: 0.006 * GB },
    { device: "/dev/sda1", mount: "/mnt/media", fstype: "ext4", total: 3.64 * 1024 * GB, used: 3.13 * 1024 * GB },
    { device: "/dev/sdb1", mount: "/mnt/backup", fstype: "ext4", total: 1.82 * 1024 * GB, used: 0.71 * 1024 * GB },
    { device: "//bhxuk-nas/NAS-2TB-A", mount: "/mnt/nas", fstype: "cifs", total: 1.82 * 1024 * GB, used: 1.76 * 1024 * GB },
  ].map(d => ({ ...d, free: d.total - d.used, percent: +(d.used / d.total * 100).toFixed(1), network: d.fstype === "cifs" }));

  let speedHistory = Array.from({ length: 14 }, (_, i) => ({
    time: now() - (i + 1) * 6 * 3600 - rnd(0, 1200), engine: "cloudflare",
    download: +rnd(840, 935).toFixed(2), upload: +rnd(96, 112).toFixed(2), ping: +rnd(8, 14).toFixed(1), jitter: +rnd(0.4, 2.5).toFixed(1),
    server: "Cloudflare London (LHR)", isp: "AS5089", ip: "203.0.113.42",
  }));
  const speed = { running: false, phase: null, engine: null, error: null, live: {}, t0: 0 };
  let lastCheck = null;

  function current() {
    const used = S.mem / 100 * 31.2 * GB;
    return {
      time: now(), cpu: +S.cpu.toFixed(1), per_cpu: S.per.map(v => +v.toFixed(1)),
      load: [+(S.cpu / 100 * CORES * 0.55).toFixed(2), 1.34, 1.12],
      mem: { total: 31.2 * GB, used, available: 31.2 * GB - used, percent: +S.mem.toFixed(1) },
      swap: { total: 4 * GB, used: 0.12 * GB, percent: 3.1 },
      net_rates: { enp3s0: { rx: S.rx, tx: S.tx }, tailscale0: { rx: S.rx * 0.08, tx: S.tx * 0.3 }, docker0: { rx: S.rx * 0.3, tx: S.tx * 0.2 } },
      net_total: { rx: S.rx, tx: S.tx },
      disk_rates: { nvme0n1: { read: rnd(0.2, 9) * MB, write: rnd(0.5, 14) * MB, busy: rnd(1, 12) }, sda: { read: rnd(5, 60) * MB, write: rnd(0, 3) * MB, busy: rnd(8, 45) }, sdb: { read: 0, write: rnd(0, 0.3) * MB, busy: rnd(0, 2) } },
      temps: [{ chip: "coretemp", label: "Package id 0", current: +S.temp.toFixed(1) }, { chip: "nvme", label: "Composite", current: 41.9 }, { chip: "drivetemp", label: "sda", current: 36 }],
      cpu_temp: +S.temp.toFixed(1), proc_count: procs.length, uptime: now() - boot,
    };
  }
  function procRows() {
    return procs.map(p => {
      const cpu = p._cpu ? clamp(p._cpu * rnd(0.5, 1.6) * (p.name === "Plex Transcoder" && S.burst ? 4 : 1) / CORES * 4, 0, 100) : (Math.random() < 0.02 ? 0.1 : 0);
      return { ...p, cpu: +cpu.toFixed(1), mem: +(p.rss / (31.2 * GB) * 100).toFixed(2) };
    });
  }
  function dockerRows() {
    return containers.map(c => {
      const running = c.state === "running";
      const cpu = running ? +(c._cpu * rnd(0.5, 1.5) / CORES * 2).toFixed(2) : 0;
      return {
        ...c,
        stats: running ? { cpu, cpu_cores: +(cpu * CORES).toFixed(1), mem_used: c._mem * rnd(0.97, 1.03), mem_limit: 31.2 * GB, mem_pct: +(c._mem / (31.2 * GB) * 100).toFixed(2), net_rx: c.net_rx, net_tx: c.net_tx, pids: 20 } : null,
      };
    });
  }
  function alerts() {
    const out = [];
    disks.forEach(d => { if (d.percent >= 95) out.push({ level: "crit", area: "disk", message: `${d.mount} is ${d.percent.toFixed(0)}% full` }); else if (d.percent >= 85) out.push({ level: "warn", area: "disk", message: `${d.mount} is ${d.percent.toFixed(0)}% full (${(d.free / 1024 ** 3).toFixed(0)} GB free)` }); });
    out.push({ level: "warn", area: "docker", message: "bazarr exited with code 137" });
    if (S.cpu > 75) out.unshift({ level: "warn", area: "cpu", message: `CPU averaging ${S.cpu.toFixed(0)}% over the last 30s` });
    return out.sort((a, b) => (a.level === "crit" ? -1 : 1) - (b.level === "crit" ? -1 : 1));
  }
  const delay = ms => new Promise(r => setTimeout(r, ms));
  const ping = (target, base, method = "icmp") => { const avg = base * rnd(0.85, 1.2); return { target, method, ok: true, loss: 0, min: +(avg * 0.8).toFixed(2), avg: +avg.toFixed(2), max: +(avg * 1.4).toFixed(2), jitter: +(avg * 0.12).toFixed(2), error: null }; };

  function runSpeed() {
    speed.running = true; speed.error = null; speed.phase = "latency"; speed.live = {};
    const phases = [["latency", 1500], ["download", 5000], ["upload", 4000]];
    let t = 0;
    phases.forEach(([ph, dur]) => { setTimeout(() => { speed.phase = ph; speed.t0 = Date.now(); }, t); t += dur; });
    setTimeout(() => {
      speedHistory.unshift({ time: now(), engine: speed.engine, download: +rnd(860, 940).toFixed(2), upload: +rnd(98, 110).toFixed(2), ping: +rnd(8, 12).toFixed(1), jitter: +rnd(0.5, 2).toFixed(1), server: speed.engine === "ookla" ? "Community Fibre (London)" : "Cloudflare London (LHR)", isp: "AS5089", ip: "203.0.113.42" });
      speed.running = false; speed.phase = null;
    }, t);
  }
  function speedStatus() {
    let live = {};
    if (speed.running && (speed.phase === "download" || speed.phase === "upload")) {
      const p = clamp((Date.now() - speed.t0) / 1500, 0, 1), top = speed.phase === "download" ? 905 : 104;
      live = { mbps: +(top * (0.4 + 0.6 * p) * rnd(0.95, 1.05)).toFixed(1) };
    }
    return { running: speed.running, phase: speed.phase, engine: speed.engine, error: null, live, last: speedHistory[0] || null, history: speedHistory.slice(0, 50) };
  }

  setInterval(tick, 2000);

  async function api(path, opts = {}) {
    const method = (opts.method || "GET").toUpperCase();
    const url = new URL(path, "http://demo");
    const q = url.searchParams;
    await delay(rnd(30, 120));
    switch (url.pathname) {
      case "/api/overview": {
        const pr = procRows();
        const dr = dockerRows();
        const al = alerts();
        return {
          host, current: current(), history: history.slice(), status: al.some(a => a.level === "crit") ? "crit" : al.length ? "warn" : "ok", alerts: al, disks,
          docker: { available: true, error: null, running: dr.filter(c => c.state === "running").length, total: dr.length, unhealthy: 0 },
          update: { available: false, latest: "1.0.0", state: "idle" },
          top_cpu: pr.slice().sort((a, b) => b.cpu - a.cpu).slice(0, 6), top_mem: pr.slice().sort((a, b) => b.rss - a.rss).slice(0, 6), speedtest: speedHistory[0],
        };
      }
      case "/api/processes": {
        let rows = procRows();
        const term = (q.get("q") || "").toLowerCase();
        if (term) rows = rows.filter(p => `${p.name} ${p.user} ${p.pid} ${p.cmd}`.toLowerCase().includes(term));
        const sort = q.get("sort") || "cpu", desc = q.get("desc") !== "false";
        const key = { cpu: p => p.cpu, mem: p => p.rss, pid: p => p.pid, name: p => p.name.toLowerCase(), user: p => p.user, threads: p => p.threads, started: p => p.started }[sort] || (p => p.cpu);
        rows.sort((a, b) => { const x = key(a), y = key(b); return (x < y ? -1 : x > y ? 1 : 0) * (desc ? -1 : 1); });
        return { total: procs.length, matched: rows.length, processes: rows.slice(0, +(q.get("limit") || 100)) };
      }
      case "/api/docker":
        return { available: true, error: null, containers: dockerRows(), info: { version: "28.5.1", images: 31, driver: "overlay2", cpus: CORES, mem: 31.2 * GB }, time: now() - 1 };
      case "/api/disks":
        return { disks, io: current().disk_rates };
      case "/api/network": {
        const cur = current();
        return {
          gateway: { interface: "enp3s0", ip: "192.168.1.1" }, last_check: lastCheck, check_running: false,
          interfaces: [
            { name: "enp3s0", kind: "physical", up: true, speed: 2500, mtu: 1500, ipv4: ["192.168.1.20"], ipv6: [], mac: "a8:a1:59:3c:11:02", rx: cur.net_rates.enp3s0.rx, tx: cur.net_rates.enp3s0.tx, rx_total: 4.2 * 1024 * GB, tx_total: 812 * GB, errors: 0, drops: 0 },
            { name: "tailscale0", kind: "tailscale", up: true, speed: 0, mtu: 1280, ipv4: ["100.101.42.7"], ipv6: [], mac: null, rx: cur.net_rates.tailscale0.rx, tx: cur.net_rates.tailscale0.tx, rx_total: 96 * GB, tx_total: 211 * GB, errors: 0, drops: 0 },
            { name: "docker0", kind: "container", up: true, speed: 10000, mtu: 1500, ipv4: ["172.17.0.1"], ipv6: [], mac: "02:42:9b:7e:01:aa", rx: cur.net_rates.docker0.rx, tx: cur.net_rates.docker0.tx, rx_total: 340 * GB, tx_total: 1.1 * 1024 * GB, errors: 0, drops: 0 },
            { name: "br-5f2c1d7e9a10", kind: "container", up: true, speed: 10000, mtu: 1500, ipv4: ["172.18.0.1"], ipv6: [], mac: "02:42:1c:44:9e:02", rx: 12000, tx: 8000, rx_total: 58 * GB, tx_total: 61 * GB, errors: 0, drops: 0 },
            { name: "lo", kind: "loopback", up: true, speed: 0, mtu: 65536, ipv4: ["127.0.0.1"], ipv6: ["::1"], mac: null, rx: 30000, tx: 30000, rx_total: 22 * GB, tx_total: 22 * GB, errors: 0, drops: 0 },
          ],
        };
      }
      case "/api/network/check": {
        await delay(1600);
        lastCheck = {
          time: now(),
          gateway: { interface: "enp3s0", ip: "192.168.1.1", ping: ping("192.168.1.1", 0.45) },
          pings: [ping("1.1.1.1", 9.1), ping("8.8.8.8", 10.4), ping("google.com", 11.2), ping("100.88.12.4", 2.1)],
          dns: [["google.com", "142.250.187.206"], ["cloudflare.com", "104.16.132.229"], ["github.com", "20.26.156.215"]].map(([name, a]) => ({ name, ok: true, ms: +rnd(1, 18).toFixed(1), addresses: [a] })),
          http: [{ url: "https://www.google.com/generate_204", ok: true, status: 204, ms: +rnd(40, 70).toFixed(1) }, { url: "https://github.com", ok: true, status: 200, ms: +rnd(90, 160).toFixed(1) }],
          public_ip: { ip: "203.0.113.42", source: "api.ipify.org" },
        };
        lastCheck.pings[3].target = "bhxuk-nas";
        lastCheck.summary = { passed: 11, total: 11 };
        return lastCheck;
      }
      case "/api/update":
        if (method === "POST") throw new Error("Updates are disabled in the demo");
        return {
          current: "1.0.0", running: "1.0.0", latest: "1.0.0", update_available: false, check_error: null, last_check: now() - 40,
          can_update: true, reason: null, install_method: "docker", auto_update: false, repo: "bhxuk/HomeLabStats", branch: "main",
          state: "idle", log: [], error: null,
          changelog: [{ version: "1.0.0", date: "2026-10-28", installed: true, new: false, body: "### Added\n- Overview with live CPU, memory, temperature, load and network charts\n- Process explorer with container mapping\n- Docker tab with stats, health, ports and live logs\n- Storage, network checks and Cloudflare / Ookla speed tests\n- In-app updates with changelog" }],
        };
      case "/api/speedtest":
        if (method === "POST") { if (!speed.running) { speed.engine = q.get("engine") || "cloudflare"; runSpeed(); } }
        return speedStatus();
      default: {
        const m = url.pathname.match(/^\/api\/docker\/([^/]+)\/(logs|start|stop|restart)$/);
        if (m && m[2] === "logs") {
          const c = containers.find(x => x.id === m[1]);
          const lines = [];
          for (let i = 60; i > 0; i--) {
            const t = new Date(Date.now() - i * 37000).toISOString();
            lines.push(`${t} [${["INFO", "INFO", "INFO", "DEBUG", "WARN"][i % 5]}] ${c ? c.name : "app"}: ${["Health check OK", "Request GET /api/v3/system/status 200 4ms", "Scheduled task RefreshMonitoredDownloads completed", "Cache pruned, 12 entries removed", "Slow response from indexer (2.4s)"][i % 5]}`);
          }
          return lines.join("\n") + "\n";
        }
        if (m) {
          const c = containers.find(x => x.id === m[1]);
          if (c) { c.state = m[2] === "stop" ? "exited" : "running"; c.exit_code = 0; if (m[2] !== "stop") c.started = now(); else c.finished = now(); if (m[2] !== "stop" && !c._cpu) { c._cpu = 0.3; c._mem = 150 * MB; } }
          return { ok: true, action: m[2], container: m[1] };
        }
        throw new Error("Not found in demo");
      }
    }
  }
  window.HLSDemo = { api };
})();
