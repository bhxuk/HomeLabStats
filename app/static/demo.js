/* HomeLabStats demo mode: a simulated API used by the GitHub Pages preview.
   Loaded only when the dashboard is opened with ?demo or window.HLS_DEMO = true. */
(function () {
  "use strict";
  const GB = 1024 ** 3, MB = 1024 ** 2;
  const now = () => Date.now() / 1000;
  const rnd = (a, b) => a + Math.random() * (b - a);
  const clamp = (v, a, b) => Math.max(a, Math.min(b, v));
  const walk = (v, step, a, b) => clamp(v + rnd(-step, step), a, b);
  const seeded = s => () => (s = (s * 16807) % 2147483647) / 2147483647;
  const boot = now() - (18 * 86400 + 7 * 3600 + 23 * 60);
  const CORES = 12, MEM = 31.2 * GB, VERSION = "1.2.0";

  const host = {
    hostname: "homelab", os: "Ubuntu 24.04.3 LTS", kernel: "6.8.0-87-generic", arch: "x86_64",
    cpu_model: "Intel(R) Core(TM) i5-12500", cores_physical: 6, cores_logical: CORES, cpu_freq_mhz: 3412,
    boot_time: boot, version: VERSION, install_method: "docker", container_actions: true,
  };

  /* ---------- live samples ---------- */
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
  for (let i = 0; i < 180; i++) tick();
  history.forEach((h, i) => (h.t = Math.round(now() - (180 - i) * 2)));
  setInterval(tick, 2000);

  /* ---------- containers ---------- */
  const mk = (name, image, project, cpu, mem, opts = {}) => ({
    id: Math.random().toString(16).slice(2, 14), full_id: "", name, image, project,
    state: opts.state || "running", health: opts.health ?? null, exit_code: opts.exit ?? 0,
    started: now() - (opts.up ?? rnd(2, 18) * 86400), finished: opts.finished ? now() - opts.finished : null,
    created: now() - 40 * 86400, restart_count: opts.restarts || 0, restart_policy: "unless-stopped",
    ports: opts.ports || [], network_mode: opts.net || "bridge", _cpu: cpu, _mem: mem, is_self: !!opts.self,
  });
  const containers = [
    mk("plex", "lscr.io/linuxserver/plex:latest", "media", 6.5, 1.9 * GB, { net: "host", health: "healthy" }),
    mk("sonarr", "lscr.io/linuxserver/sonarr:latest", "media", 0.6, 310 * MB, { ports: ["8989:8989/tcp"] }),
    mk("radarr", "lscr.io/linuxserver/radarr:latest", "media", 0.5, 290 * MB, { ports: ["7878:7878/tcp"] }),
    mk("prowlarr", "lscr.io/linuxserver/prowlarr:latest", "media", 0.2, 180 * MB, { ports: ["9696:9696/tcp"] }),
    mk("qbittorrent", "lscr.io/linuxserver/qbittorrent:latest", "media", 2.1, 520 * MB, { ports: ["8080:8080/tcp", "6881:6881/tcp", "6881:6881/udp"] }),
    mk("immich-server", "ghcr.io/immich-app/immich-server:release", "immich", 1.4, 880 * MB, { ports: ["2283:2283/tcp"], health: "healthy" }),
    mk("immich-postgres", "ghcr.io/immich-app/postgres:14", "immich", 0.3, 210 * MB, { health: "healthy" }),
    mk("immich-ml", "ghcr.io/immich-app/immich-machine-learning:release", "immich", 0.1, 1.1 * GB, { health: "healthy" }),
    mk("homeassistant", "ghcr.io/home-assistant/home-assistant:stable", null, 0.9, 640 * MB, { net: "host" }),
    mk("pihole", "pihole/pihole:latest", null, 0.2, 95 * MB, { ports: ["53:53/tcp", "53:53/udp", "8053:80/tcp"], health: "healthy" }),
    mk("nginx-proxy-manager", "jc21/nginx-proxy-manager:latest", null, 0.1, 140 * MB, { ports: ["80:80/tcp", "443:443/tcp", "81:81/tcp"] }),
    mk("portainer", "portainer/portainer-ce:latest", null, 0.1, 60 * MB, { ports: ["9443:9443/tcp"] }),
    mk("homelabstats", "homelabstats:local", "homelabstats", 0.6, 74 * MB, { net: "host", up: 3600 * 5, self: true }),
    mk("uptime-kuma", "louislam/uptime-kuma:1", null, 0, 0, { state: "exited", exit: 0, finished: 2 * 86400 }),
    mk("netdata", "netdata/netdata:latest", null, 0, 0, { state: "exited", exit: 0, finished: 2 * 86400 }),
    mk("bazarr", "lscr.io/linuxserver/bazarr:latest", "media", 0, 0, { state: "exited", exit: 137, finished: 3 * 3600 }),
  ];
  const HOST_PORTS = { plex: [32400], homeassistant: [8123], homelabstats: [8090] };
  containers.forEach(c => {
    c.full_id = c.id.padEnd(64, "0"); c.net_rx = rnd(0.2, 40) * GB; c.net_tx = rnd(0.05, 9) * GB;
    c.port_list = c.ports.map(p => { const [h, rest] = p.split(":"); const [cp, proto] = rest.split("/"); return { host: +h, container: +cp, proto, ip: "0.0.0.0" }; });
    c.host_ports = c.state === "running" ? (HOST_PORTS[c.name] || []) : []; c.url_label = null;
  });
  const links = { pihole: "http://{host}:8053/admin" };
  const findC = id => containers.find(c => c.id === id || c.name === id);

  /* ---------- processes ---------- */
  const procNames = [
    ["Plex Media Server", "plex", "/usr/lib/plexmediaserver/Plex Media Server", 6, 1.2 * GB, "plex"],
    ["Plex Transcoder", "plex", "/usr/lib/plexmediaserver/Plex Transcoder -codec:0 h264 -crf 21", 9, 410 * MB, "plex"],
    ["dockerd", "root", "/usr/bin/dockerd -H fd:// --containerd=/run/containerd/containerd.sock", 0.8, 160 * MB],
    ["containerd", "root", "/usr/bin/containerd", 0.4, 70 * MB],
    ["python", "root", "python -m app.main", 0.6, 74 * MB, "homelabstats"],
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
    ["tailscaled", "root", "/usr/sbin/tailscaled --state=/var/lib/tailscale/tailscaled.state", 0.3, 45 * MB],
    ["systemd", "root", "/sbin/init splash", 0, 12 * MB],
    ["systemd-journald", "root", "/usr/lib/systemd/systemd-journald", 0.1, 40 * MB],
    ["sshd", "root", "sshd: /usr/sbin/sshd -D [listener]", 0, 9 * MB],
    ["smbd", "root", "/usr/sbin/smbd --foreground --no-process-group", 0.1, 22 * MB],
    ["bash", "admin", "-bash", 0, 6 * MB],
    ["htop", "admin", "htop", 0.4, 5 * MB],
    ["cron", "root", "/usr/sbin/cron -f -P", 0, 3 * MB],
    ["rsyslogd", "syslog", "/usr/sbin/rsyslogd -n -iNONE", 0, 7 * MB],
    ["systemd-resolved", "systemd-resolve", "/usr/lib/systemd/systemd-resolved", 0, 13 * MB],
  ];
  let pid = 812;
  const procs = procNames.map(([name, user, cmd, cpu, rss, container]) => ({
    pid: (pid += Math.floor(rnd(3, 400))), ppid: 1, name, user, cmd, container: container || null,
    _cpu: cpu, rss, threads: Math.floor(rnd(1, 60)), status: "sleeping", started: now() - rnd(0.2, 18) * 86400,
  }));
  procs.find(p => p.name === "systemd").pid = 1;
  for (let i = 0; i < 190; i++) procs.push({ pid: 3000 + i * 7, ppid: 1, name: ["kworker", "bash", "sleep", "s6-supervise", "containerd-shim"][i % 5], user: "root", cmd: "", container: null, _cpu: 0, rss: rnd(1, 12) * MB, threads: 1, status: "sleeping", started: now() - rnd(0, 18) * 86400 });
  procs.forEach(p => { if (!p.cmd) p.cmd = p.name; });

  /* ---------- disks ---------- */
  const disks = [
    { device: "/dev/nvme0n1p2", mount: "/", fstype: "ext4", total: 468 * GB, used: 187 * GB },
    { device: "/dev/nvme0n1p1", mount: "/boot/efi", fstype: "vfat", total: 1.05 * GB, used: 0.006 * GB },
    { device: "/dev/sda1", mount: "/mnt/media", fstype: "ext4", total: 3.64 * 1024 * GB, used: 3.13 * 1024 * GB },
    { device: "/dev/sdb1", mount: "/mnt/backup", fstype: "ext4", total: 1.82 * 1024 * GB, used: 0.71 * 1024 * GB },
    { device: "//nas/media-2tb", mount: "/mnt/nas", fstype: "cifs", total: 1.82 * 1024 * GB, used: 1.6 * 1024 * GB },
  ].map(d => ({ ...d, free: d.total - d.used, percent: +(d.used / d.total * 100).toFixed(1), network: d.fstype === "cifs" }));

  /* ---------- long-term metrics (deterministic so charts look stable) ---------- */
  const RANGES = { "1h": 3600, "6h": 21600, "24h": 86400, "48h": 172800, "7d": 604800, "30d": 2592000, "90d": 7776000 };
  function sysPoint(t, r) {
    const hour = new Date(t * 1000).getHours() + new Date(t * 1000).getMinutes() / 60;
    const evening = Math.max(0, Math.sin((hour - 16) / 24 * 2 * Math.PI)) ;
    const night = hour > 2 && hour < 4;
    const cpu = clamp(9 + evening * 22 + (night ? 35 : 0) + r() * 10 + (r() < .03 ? 40 : 0), 2, 98);
    const rx = (1.5e6 + evening * 9e6 + (night ? 2.5e7 : 0)) * (0.5 + r());
    const tx = (0.3e6 + evening * 2.2e6) * (0.5 + r());
    return { t, cpu, mem: 55 + evening * 6 + r() * 3, swap: 3 + r() * .5, load1: cpu / 100 * CORES * .6, temp: 38 + cpu * .4 + r() * 2,
      rx, tx, dr: (night ? 6e7 : 2e6) * r(), dw: (night ? 4e7 : 3e6) * r(), cpu_max: Math.min(100, cpu * (1.2 + r())), rx_max: rx * (1.3 + r()), tx_max: tx * (1.3 + r()) };
  }
  function metricsSystem(range) {
    const span = RANGES[range] || 3600, base = span <= 172800 ? 10 : 300;
    const bucket = Math.max(base, Math.floor(span / 360 / base) * base), since = Math.floor(now() - span);
    const pts = []; const r = seeded(Math.floor(since / bucket));
    for (let t = Math.ceil(since / bucket) * bucket; t < now(); t += bucket) pts.push(sysPoint(t, r));
    const avg = k => pts.reduce((a, p) => a + p[k], 0) / pts.length, max = k => Math.max(...pts.map(p => p[k]));
    const step = base;
    return { range, bucket, since, points: pts, summary: { cpu_avg: avg("cpu"), cpu_peak: max("cpu_max"), mem_avg: avg("mem"), mem_peak: max("mem"),
      temp_avg: avg("temp"), temp_peak: max("temp"), rx_peak: max("rx_max"), tx_peak: max("tx_max"),
      rx_total: avg("rx") * span, tx_total: avg("tx") * span, n: pts.length * bucket / step } };
  }
  function metricsContainers(range, metric) {
    const span = RANGES[range] || 3600, base = span <= 172800 ? 30 : 300;
    const bucket = Math.max(base, Math.floor(span / 360 / base) * base), since = Math.floor(now() - span);
    const run = containers.filter(c => c.state === "running").sort((a, b) => metric === "mem" ? b._mem - a._mem : b._cpu - a._cpu).slice(0, 8);
    const series = {}, leaders = [];
    run.forEach((c, i) => {
      const r = seeded(i + 7); const pts = [];
      for (let t = Math.ceil(since / bucket) * bucket; t < now(); t += bucket) {
        const hour = new Date(t * 1000).getHours(), ev = hour >= 18 && hour <= 23 ? 1 : 0;
        const v = metric === "cpu" ? c._cpu / CORES * 2 * (0.4 + r() + (c.name === "plex" ? ev * 3 : 0))
          : metric === "mem" ? c._mem * (0.95 + r() * .1) : (c.name === "plex" || c.name === "qbittorrent" ? 3e6 : 4e4) * (0.2 + r() * (1 + ev * 2));
        pts.push([t, v]);
      }
      series[c.name] = pts;
      leaders.push({ name: c.name, avg: pts.reduce((a, p) => a + p[1], 0) / pts.length, peak: Math.max(...pts.map(p => p[1])) });
    });
    leaders.sort((a, b) => b.avg - a.avg);
    return { range, metric, bucket, since, leaders, series };
  }

  /* ---------- speed tests ---------- */
  let stId = 1;
  const speedHistory = [];
  { const r = seeded(42);
    for (let i = 120; i >= 1; i--) {
      const t = now() - i * 6 * 3600 - r() * 600, h = new Date(t * 1000).getHours(), busy = h >= 19 && h <= 22;
      speedHistory.unshift({ id: stId++, ts: t, engine: "cloudflare", trigger: "scheduled", download: +(busy ? 640 + r() * 180 : 860 + r() * 80).toFixed(2), upload: +(95 + r() * 15).toFixed(2), ping: +(8 + r() * 6).toFixed(1), jitter: +(0.4 + r() * 2).toFixed(1), server: "Cloudflare London (LHR)", isp: "AS5089", ip: "203.0.113.42", error: null });
    }
    speedHistory.splice(9, 0, { id: stId++, ts: now() - 2.2 * 86400, engine: "cloudflare", trigger: "scheduled", download: null, upload: null, ping: null, jitter: null, server: null, isp: null, ip: null, error: "TimeoutError: timed out" });
  }
  const speed = { running: false, phase: null, engine: null, t0: 0 };
  function speedStats() {
    const out = {};
    for (const [k, d] of [["24h", 1], ["7d", 7], ["30d", 30], ["all", 36500]]) {
      const xs = speedHistory.filter(x => x.ts >= now() - d * 86400), ok = xs.filter(x => !x.error);
      const a = f => ok.length ? ok.reduce((s, x) => s + x[f], 0) / ok.length : null, mn = f => ok.length ? Math.min(...ok.map(x => x[f])) : null, mx = f => ok.length ? Math.max(...ok.map(x => x[f])) : null;
      out[k] = { n: ok.length, failed: xs.length - ok.length, down_avg: a("download"), down_min: mn("download"), down_max: mx("download"), up_avg: a("upload"), up_min: mn("upload"), up_max: mx("upload"), ping_avg: a("ping") };
    }
    return out;
  }
  function speedStatus(days = 30) {
    let live = {};
    if (speed.running && (speed.phase === "download" || speed.phase === "upload")) {
      const p = clamp((Date.now() - speed.t0) / 1500, 0, 1), top = speed.phase === "download" ? 905 : 104;
      live = { mbps: +(top * (0.4 + 0.6 * p) * rnd(0.95, 1.05)).toFixed(1) };
    }
    return { running: speed.running, phase: speed.phase, engine: speed.engine, error: null, live, last: speedHistory.find(x => !x.error),
      interval_hours: settings.speedtest_interval_hours, next_run: speedHistory[0].ts + settings.speedtest_interval_hours * 3600,
      history: speedHistory.filter(x => x.ts >= now() - days * 86400), stats: speedStats() };
  }
  function runSpeed() {
    speed.running = true; speed.phase = "latency";
    let t = 0;
    [["latency", 1500], ["download", 5000], ["upload", 4000]].forEach(([ph, dur]) => { setTimeout(() => { speed.phase = ph; speed.t0 = Date.now(); }, t); t += dur; });
    setTimeout(() => {
      speedHistory.unshift({ id: stId++, ts: now(), engine: speed.engine, trigger: "manual", download: +rnd(860, 940).toFixed(2), upload: +rnd(98, 110).toFixed(2), ping: +rnd(8, 12).toFixed(1), jitter: +rnd(0.5, 2).toFixed(1), server: speed.engine === "ookla" ? "Community Fibre (London)" : "Cloudflare London (LHR)", isp: "AS5089", ip: "203.0.113.42", error: null });
      speed.running = false; speed.phase = null;
    }, t);
  }

  /* ---------- monitors ---------- */
  let monId = 1;
  const M = (name, type, target, extra = {}) => ({ id: monId++, name, type, target, port: null, interval: 60, timeout: 10, keyword: null, expect: "200-399", method: "GET", ignore_tls: 0, invert: 0, retries: 2, enabled: 1, notify: 1, created: now() - 30 * 86400, sort: 0, _base: 20, _flaky: 0, ...extra });
  const monitors = [
    M("Plex", "http", "http://192.168.0.150:32400/identity", { _base: 6 }),
    M("Sonarr", "http", "http://192.168.0.150:8989", { _base: 14 }),
    M("Radarr", "http", "http://192.168.0.150:7878", { _base: 12 }),
    M("Immich", "http", "https://photos.example.com", { keyword: "Immich", _base: 85 }),
    M("Home Assistant", "http", "http://192.168.0.150:8123", { _base: 9 }),
    M("Pi-hole DNS", "dns", "google.com", { _base: 3 }),
    M("NAS", "ping", "nas", { _base: 2, _flaky: .004 }),
    M("Router", "ping", "192.168.0.1", { _base: 1 }),
    M("qBittorrent web UI", "tcp", "192.168.0.150", { port: 8080, _base: 1 }),
    M("Bazarr", "docker", "bazarr", { interval: 30 }),
    M("Public website", "http", "https://example.com", { interval: 300, _base: 120, _flaky: .01 }),
  ];
  const beatCache = {};
  function beats(m, n = 60) {
    if (!beatCache[m.id]) {
      const r = seeded(m.id * 97), arr = [];
      for (let i = 2000; i > 0; i--) {
        const ts = now() - i * m.interval; let ok = r() > m._flaky;
        if (m.type === "docker") ok = ts < now() - 3 * 3600;
        if (m.name === "Sonarr" && i > 900 && i < 905) ok = false;
        arr.push({ ts, ok: ok ? 1 : 0, ms: m.type === "docker" ? null : ok ? +(m._base * (0.7 + r() * .8)).toFixed(1) : null, msg: ok ? (m.type === "http" ? "HTTP 200" + (m.keyword ? ", keyword found" : "") : m.type === "docker" ? "Running" : m.type === "tcp" ? "Port 8080 open" : "OK") : (m.type === "docker" ? "Container exited (exit 137)" : "Timed out") });
      }
      beatCache[m.id] = arr;
    }
    return beatCache[m.id].slice(-n);
  }
  function monStatus(m) { if (!m.enabled) return "paused"; const b = beats(m, 2); return b.at(-1)?.ok ? "up" : "down"; }
  function upt(m, secs) { const xs = beatCache[m.id] ? beatCache[m.id].filter(b => b.ts >= now() - secs) : beats(m, 2000).filter(b => b.ts >= now() - secs); return xs.length ? xs.reduce((a, b) => a + b.ok, 0) / xs.length * 100 : null; }
  function monRow(m) {
    const all = beats(m, 2000), day = all.filter(b => b.ts > now() - 86400 && b.ms != null);
    const st = monStatus(m); let since = all[0].ts;
    for (let i = all.length - 1; i >= 0; i--) { if ((all[i].ok ? "up" : "down") !== st) { since = all[i + 1]?.ts || all[i].ts; break; } }
    return { ...m, status: st, since, uptime_24h: upt(m, 86400), uptime_7d: upt(m, 7 * 86400), uptime_30d: upt(m, 30 * 86400), avg_ms_24h: day.length ? day.reduce((a, b) => a + b.ms, 0) / day.length : null, last: all.at(-1), beats: all.slice(-60) };
  }
  function monSummary() {
    const rows = monitors.map(monRow), c = { up: 0, down: 0, pending: 0, paused: 0 };
    rows.forEach(r => c[r.status]++);
    return { ...c, total: rows.length, down_names: rows.filter(r => r.status === "down").map(r => r.name) };
  }
  function monDetail(m, range) {
    const span = { "1h": 3600, "24h": 86400, "7d": 604800, "30d": 2592000, "90d": 7776000 }[range] || 86400, bucket = Math.max(60, Math.floor(span / 240));
    const all = beats(m, 2000).filter(b => b.ts >= now() - span), g = {};
    all.forEach(b => { const t = Math.floor(b.ts / bucket) * bucket; (g[t] ||= []).push(b); });
    const series = Object.entries(g).map(([t, bs]) => { const ms = bs.filter(b => b.ms != null); return { t: +t, ms: ms.length ? ms.reduce((a, b) => a + b.ms, 0) / ms.length : null, ok: Math.min(...bs.map(b => b.ok)), n: bs.length }; });
    const incidents = m.type === "docker" ? [{ ts: now() - 3 * 3600, level: "crit", title: `${m.name} is down`, detail: `${m.name} (container bazarr): Container exited (exit 137)` }]
      : m.name === "Sonarr" ? [{ ts: now() - 900 * 60 + 300, level: "ok", title: "Sonarr is back up", detail: "Sonarr recovered after 4m. HTTP 200" }, { ts: now() - 905 * 60, level: "crit", title: "Sonarr is down", detail: "Sonarr (http://192.168.0.150:8989): Timed out" }] : [];
    return { ...monRow(m), range, series, recent: beats(m, 100).reverse(), incidents };
  }

  /* ---------- settings & events ---------- */
  const settings = {
    container_actions: true, speedtest_interval_hours: 6, speedtest_engine: "cloudflare", speedtest_alert_below_mbps: 400, retention_days: 90,
    notify_channels: [{ id: "a1", type: "discord", name: "Homelab Discord", url: "https://discord.com/api/webhooks/…", token: "", chat_id: "", enabled: true }, { id: "a2", type: "ntfy", name: "Phone", url: "https://ntfy.sh/my-homelab", token: "", chat_id: "", enabled: true }],
    notify_on: { monitor_down: true, monitor_up: true, container_stopped: true, container_unhealthy: true, system_alerts: true, speedtest_slow: true, update_available: false },
  };
  const events = [
    [300, "speedtest", "info", "Speed test: 905 / 104 Mbps", "Down 905 Mbps, up 104 Mbps, ping 9 ms (Cloudflare London (LHR))"],
    [3 * 3600, "docker", "crit", "bazarr stopped", "Container bazarr stopped with exit code 137."],
    [3 * 3600 - 20, "monitor", "crit", "Bazarr is down", "Bazarr (container bazarr): Container exited (exit 137)"],
    [5 * 3600, "system", "info", `HomeLabStats ${VERSION} started`, ""],
    [5 * 3600 + 60, "update", "info", "Update started", "Updating from 1.0.0"],
    [2 * 86400, "docker", "info", "uptime-kuma stopped", "admin stopped uptime-kuma from HomeLabStats."],
    [2 * 86400 + 30, "docker", "info", "netdata stopped", "admin stopped netdata from HomeLabStats."],
    [2 * 86400 + 600, "monitor", "info", "Imported 11 monitors from Uptime Kuma", "Skipped 0 already present, 1 unsupported. Added 2 notification channels."],
    [15 * 3600, "monitor", "ok", "Sonarr is back up", "Sonarr recovered after 4m. HTTP 200"],
    [15 * 3600 + 300, "monitor", "crit", "Sonarr is down", "Sonarr (http://192.168.0.150:8989): Timed out"],
    [26 * 3600, "docker", "info", "Docker cleanup: images unused", "Removed 14 item(s), freed 8.42 GB."],
  ].map(([ago, kind, level, title, detail], i) => ({ id: 100 - i, ts: now() - ago, kind, level, title, detail }));
  const logEvent = (kind, level, title, detail = "") => events.unshift({ id: Date.now(), ts: now(), kind, level, title, detail });

  /* ---------- live helpers ---------- */
  function current() {
    const used = S.mem / 100 * MEM;
    return {
      time: now(), cpu: +S.cpu.toFixed(1), per_cpu: S.per.map(v => +v.toFixed(1)),
      load: [+(S.cpu / 100 * CORES * 0.55).toFixed(2), 1.34, 1.12],
      mem: { total: MEM, used, available: MEM - used, percent: +S.mem.toFixed(1) },
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
      return { ...p, cpu: +cpu.toFixed(1), mem: +(p.rss / MEM * 100).toFixed(2) };
    });
  }
  function dockerRows() {
    return containers.map(c => {
      const running = c.state === "running", cpu = running ? +(c._cpu * rnd(0.5, 1.5) / CORES * 2).toFixed(2) : 0;
      return { ...c, stats: running ? { cpu, cpu_cores: +(cpu * CORES).toFixed(1), mem_used: c._mem * rnd(0.97, 1.03), mem_limit: MEM, mem_pct: +(c._mem / MEM * 100).toFixed(2), net_rx: c.net_rx, net_tx: c.net_tx, pids: 20 } : null };
    });
  }
  function alerts() {
    const out = [];
    disks.forEach(d => { if (d.percent >= 95) out.push({ level: "crit", area: "disk", message: `${d.mount} is ${d.percent.toFixed(0)}% full` }); else if (d.percent >= 85) out.push({ level: "warn", area: "disk", message: `${d.mount} is ${d.percent.toFixed(0)}% full (${(d.free / GB).toFixed(0)} GB free)` }); });
    const b = containers.find(c => c.name === "bazarr");
    if (b.state === "exited" && b.exit_code) out.push({ level: "warn", area: "docker", message: "bazarr exited with code 137" });
    const ms = monSummary();
    if (ms.down) out.unshift({ level: "crit", area: "monitor", message: `${ms.down} monitor${ms.down > 1 ? "s" : ""} down: ${ms.down_names.join(", ")}` });
    if (S.cpu > 75) out.unshift({ level: "warn", area: "cpu", message: `CPU averaging ${S.cpu.toFixed(0)}% over the last 30s` });
    return out;
  }
  function todayTraffic() { return { rx: 41.7 * GB, tx: 6.2 * GB, rx_peak: 1.1e8, tx_peak: 1.3e7, since: now() - 14 * 3600 }; }
  function fakeLogs(c, n) {
    const lines = [], r = seeded(c.name.length * 13);
    const msgs = { plex: ["Request: [192.168.0.42:51122] GET /library/sections", "Transcoder: starting session 7f2", "Scanner: scanning section 2 (TV Shows)", "Butler: optimizing database"],
      sonarr: ["RssSyncService: RSS Sync Completed. Reports found: 98, Reports grabbed: 0", "DownloadDecisionMaker: Processing 98 releases", "CommandExecutor: Starting RefreshMonitoredDownloads", "HttpClient: Indexer request took 2.4s (slow)"] };
    const set = msgs[c.name] || ["Health check OK", "GET /api/status 200 4ms", "Scheduled job finished in 120ms", "Cache pruned, 12 entries removed", "Slow response from upstream (2.1s)"];
    for (let i = n; i > 0; i--) {
      const t = new Date(Date.now() - i * 4100), lvl = r() < .05 ? "ERROR" : r() < .12 ? "WARN" : r() < .3 ? "DEBUG" : "INFO";
      lines.push(`${t.toISOString().replace("Z", "123456Z")} [${lvl}] ${set[Math.floor(r() * set.length)]}${lvl === "ERROR" ? " (connection reset by peer)" : ""}`);
    }
    if (c.name === "bazarr") lines.push(`${new Date(Date.now() - 3 * 3600e3).toISOString()} [CRITICAL] Out of memory: killed by the kernel`);
    return lines;
  }

  /* ---------- router ---------- */
  const delay = ms => new Promise(r => setTimeout(r, ms));
  const ping = (target, base, method = "icmp") => { const avg = base * rnd(0.85, 1.2); return { target, method, ok: true, loss: 0, min: +(avg * 0.8).toFixed(2), avg: +avg.toFixed(2), max: +(avg * 1.4).toFixed(2), jitter: +(avg * 0.12).toFixed(2), error: null }; };
  let lastCheck = null;

  async function api(path, opts = {}) {
    const method = (opts.method || "GET").toUpperCase(), body = opts.json || {};
    const url = new URL(path.replace(/^\/?/, "/"), "http://demo"), q = url.searchParams, p = url.pathname;
    await delay(rnd(30, 120));
    let m;
    if (p === "/api/overview") {
      const pr = procRows(), dr = dockerRows(), al = alerts();
      return { host: { ...host, container_actions: settings.container_actions }, current: current(), history: history.slice(), status: al.some(a => a.level === "crit") ? "crit" : al.length ? "warn" : "ok", alerts: al, disks,
        docker: { available: true, error: null, running: dr.filter(c => c.state === "running").length, total: dr.length, unhealthy: 0 },
        monitors: monSummary(), events: events.slice(0, 8),
        top_cpu: pr.slice().sort((a, b) => b.cpu - a.cpu).slice(0, 6), top_mem: pr.slice().sort((a, b) => b.rss - a.rss).slice(0, 6),
        speedtest: speedHistory.find(x => !x.error), traffic_today: todayTraffic(), update: { available: false, latest: VERSION, state: "idle" } };
    }
    if (p === "/api/events") { const k = q.get("kind"); return events.filter(e => !k || e.kind === k).slice(0, +(q.get("limit") || 100)); }
    if (p === "/api/processes") {
      let rows = procRows(); const term = (q.get("q") || "").toLowerCase();
      if (term) rows = rows.filter(x => `${x.name} ${x.user} ${x.pid} ${x.cmd} ${x.container || ""}`.toLowerCase().includes(term));
      const sort = q.get("sort") || "cpu", desc = q.get("desc") !== "false";
      const key = { cpu: x => x.cpu, mem: x => x.rss, pid: x => x.pid, name: x => x.name.toLowerCase(), user: x => x.user, threads: x => x.threads, started: x => x.started }[sort] || (x => x.cpu);
      rows.sort((a, b) => { const x = key(a), y = key(b); return (x < y ? -1 : x > y ? 1 : 0) * (desc ? -1 : 1); });
      return { total: procs.length, matched: rows.length, processes: rows.slice(0, +(q.get("limit") || 100)) };
    }
    if ((m = p.match(/^\/api\/processes\/(\d+)\/(terminate|kill)$/))) { logEvent("process", "warn", `Process ${m[1]} ended`, "Demo only: nothing was really stopped."); return { ok: true }; }
    if (p === "/api/docker") return { available: true, error: null, containers: dockerRows(), info: { version: "28.5.1", images: 31, driver: "overlay2", cpus: CORES, mem: MEM }, time: now() - 1, links };
    if (p === "/api/docker/df") return { images: { count: 31, size: 24.6 * GB, unused_count: 9, unused_size: 7.8 * GB, dangling_count: 6, dangling_size: 2.1 * GB }, containers: { count: 16, size: 410 * MB, stopped: 3 },
      volumes: { count: 12, size: 18.3 * GB, unused_count: 2 }, build_cache: { count: 48, size: 3.4 * GB, reclaimable: 3.4 * GB },
      top_images: [["lscr.io/linuxserver/plex:latest", 3.1, true], ["ghcr.io/immich-app/immich-machine-learning:release", 2.9, true], ["netdata/netdata:latest", 1.6, false], ["ghcr.io/home-assistant/home-assistant:stable", 1.9, true], ["ghcr.io/immich-app/immich-server:release", 1.4, true], ["nicolargo/glances:latest", 0.9, false], ["louislam/uptime-kuma:1", 0.6, false], ["amir20/dozzle:latest", 0.05, false]].map(([tag, s, u]) => ({ tag, size: s * GB, in_use: u, created: now() - 9e6 })), time: now() };
    if (p === "/api/docker/prune") { const freed = { images_unused: 7.8, images_dangling: 2.1, build_cache: 3.4, containers: 0.4 }[body.target] * GB; logEvent("docker", "info", "Docker cleanup (demo)", "Nothing was really removed in the demo."); return { target: body.target, freed, removed: 6 }; }
    if ((m = p.match(/^\/api\/docker\/([^/]+)\/inspect$/))) {
      const c = findC(m[1]);
      return { id: c.id, name: c.name, image: c.image, image_id: "9a1c2e7f0b3d", created: c.created, started: c.started, finished: c.finished, state: c.state, exit_code: c.exit_code, oom_killed: c.exit_code === 137, error: null,
        restart_count: c.restart_count, restart_policy: c.restart_policy, command: "/init", workdir: "/", user: "root", network_mode: c.network_mode, privileged: false, mem_limit: null, cpu_limit: null,
        mounts: [{ type: "bind", source: `/opt/docker/${c.name}/config`, dest: "/config", rw: true }, ...(c.project === "media" ? [{ type: "bind", source: "/mnt/media", dest: "/data", rw: true }] : [])],
        networks: c.network_mode === "host" ? [{ name: "host", ip: "" }] : [{ name: c.project ? c.project + "_default" : "bridge", ip: "172.18.0." + (5 + c.name.length) }],
        env_keys: ["PUID", "PGID", "TZ", "PATH"], ports: c.ports.map(x => "0.0.0.0:" + x.replace(":", " -> ")), compose_project: c.project, compose_service: c.name, compose_dir: c.project ? `/opt/docker/${c.project}` : null,
        health: c.health ? { status: c.health, failing_streak: 0, log: [1, 2, 3].map(i => ({ start: now() - i * 30, exit: 0, output: "OK" })) } : {} };
    }
    if ((m = p.match(/^\/api\/docker\/([^/]+)\/history$/))) {
      const c = findC(decodeURIComponent(m[1])), range = q.get("range") || "24h", span = RANGES[range], bucket = Math.max(30, Math.floor(span / 240 / 30) * 30), r = seeded(c.name.length), pts = [];
      if (c.state === "running") for (let t = Math.ceil((now() - span) / bucket) * bucket; t < now(); t += bucket) pts.push({ t, cpu: c._cpu / CORES * 2 * (0.4 + r()), mem: c._mem * (0.95 + r() * .1), rx: 1e5 * r(), tx: 2e4 * r() });
      return { range, bucket, points: pts };
    }
    if ((m = p.match(/^\/api\/docker\/([^/]+)\/logs$/))) {
      const c = findC(m[1]);
      if (q.get("since")) { const l = `${new Date().toISOString().replace("Z", "654321Z")} [INFO] ${["Health check OK", "GET /api/v3/system/status 200 4ms", "Scheduled task finished"][Math.floor(Math.random() * 3)]}`; return { name: c.name, state: c.state, lines: c.state === "running" && Math.random() < .7 ? [l] : [], last_ts: l.split(" ")[0] }; }
      const lines = fakeLogs(c, Math.min(+(q.get("tail") || 300), 400));
      return { name: c.name, state: c.state, lines, last_ts: lines.at(-1).split(" ")[0] };
    }
    if ((m = p.match(/^\/api\/docker\/([^/]+)\/(start|stop|restart|pause|unpause|remove)$/))) {
      const c = findC(m[1]);
      if (m[2] === "remove") { containers.splice(containers.indexOf(c), 1); }
      else { c.state = { stop: "exited", pause: "paused" }[m[2]] || "running"; c.exit_code = 0; if (c.state === "running") { c.started = now(); if (!c._cpu) { c._cpu = 0.3; c._mem = 150 * MB; } } else c.finished = now(); }
      logEvent("docker", "info", `${c.name} ${{ start: "started", stop: "stopped", restart: "restarted", pause: "paused", unpause: "resumed", remove: "removed" }[m[2]]}`, "Demo: nothing real was changed.");
      return { ok: true, action: m[2], container: c.name };
    }
    if (p === "/api/disks") return { disks, io: current().disk_rates };
    if (p === "/api/sensors") return { temps: [...current().temps, { chip: "coretemp", label: "Core 0", current: S.temp - 2 }, { chip: "coretemp", label: "Core 1", current: S.temp - 1 }, { chip: "acpitz", label: "acpitz 0", current: 27.8 }, { chip: "drivetemp", label: "sdb", current: 33 }],
      fans: [{ chip: "nct6798", label: "CPU fan", rpm: Math.round(900 + S.cpu * 8) }, { chip: "nct6798", label: "Case fan 1", rpm: 720 }, { chip: "nct6798", label: "Case fan 2", rpm: 715 }],
      battery: null, freqs: S.per.map(v => Math.round(1200 + v * 32)), users: [{ name: "admin", terminal: "pts/0", host: "100.64.0.7", started: now() - 3600 }], cpu_stats: null };
    if (p === "/api/metrics/system") return metricsSystem(q.get("range") || "1h");
    if (p === "/api/metrics/containers") return metricsContainers(q.get("range") || "1h", q.get("metric") || "cpu");
    if (p === "/api/traffic") return { now: { rx: S.rx, tx: S.tx }, per_interface: current().net_rates, history: history.map(h => ({ t: h.t, rx: h.rx, tx: h.tx })), today: todayTraffic() };
    if (p === "/api/network") {
      const cur = current();
      return { gateway: { interface: "enp3s0", ip: "192.168.0.1" }, last_check: lastCheck, check_running: false, interfaces: [
        { name: "enp3s0", kind: "physical", up: true, speed: 2500, mtu: 1500, ipv4: ["192.168.0.150"], ipv6: [], mac: "a8:a1:59:3c:11:02", rx: cur.net_rates.enp3s0.rx, tx: cur.net_rates.enp3s0.tx, rx_total: 4.2 * 1024 * GB, tx_total: 812 * GB, errors: 0, drops: 0 },
        { name: "tailscale0", kind: "tailscale", up: true, speed: 0, mtu: 1280, ipv4: ["100.101.42.7"], ipv6: [], mac: null, rx: cur.net_rates.tailscale0.rx, tx: cur.net_rates.tailscale0.tx, rx_total: 96 * GB, tx_total: 211 * GB, errors: 0, drops: 0 },
        { name: "docker0", kind: "container", up: true, speed: 10000, mtu: 1500, ipv4: ["172.17.0.1"], ipv6: [], mac: "02:42:9b:7e:01:aa", rx: cur.net_rates.docker0.rx, tx: cur.net_rates.docker0.tx, rx_total: 340 * GB, tx_total: 1.1 * 1024 * GB, errors: 0, drops: 0 },
        { name: "lo", kind: "loopback", up: true, speed: 0, mtu: 65536, ipv4: ["127.0.0.1"], ipv6: ["::1"], mac: null, rx: 30000, tx: 30000, rx_total: 22 * GB, tx_total: 22 * GB, errors: 0, drops: 0 }] };
    }
    if (p === "/api/network/check") {
      await delay(1400);
      lastCheck = { time: now(), gateway: { interface: "enp3s0", ip: "192.168.0.1", ping: ping("192.168.0.1", 0.45) },
        pings: [ping("1.1.1.1", 9.1), ping("8.8.8.8", 10.4), ping("google.com", 11.2), ping("nas", 2.1)],
        dns: [["google.com", "142.250.187.206"], ["cloudflare.com", "104.16.132.229"], ["github.com", "20.26.156.215"]].map(([name, a]) => ({ name, ok: true, ms: +rnd(1, 18).toFixed(1), addresses: [a] })),
        http: [{ url: "https://www.google.com/generate_204", ok: true, status: 204, ms: +rnd(40, 70).toFixed(1) }, { url: "https://github.com", ok: true, status: 200, ms: +rnd(90, 160).toFixed(1) }],
        public_ip: { ip: "203.0.113.42", source: "api.ipify.org" }, summary: { passed: 11, total: 11 } };
      return lastCheck;
    }
    if (p === "/api/speedtest") { if (method === "POST" && !speed.running) { speed.engine = q.get("engine") || settings.speedtest_engine; runSpeed(); } return speedStatus(+(q.get("days") || 30)); }
    if ((m = p.match(/^\/api\/speedtest\/(\d+)$/))) { const i = speedHistory.findIndex(x => x.id === +m[1]); if (i >= 0) speedHistory.splice(i, 1); return { ok: true }; }
    if (p === "/api/monitors" && method === "GET") return { monitors: monitors.map(monRow), summary: monSummary() };
    if (p === "/api/monitors" && method === "POST") { const mo = M(body.name || body.target, body.type, body.target, { ...body, _base: 15 }); monitors.push(mo); return mo; }
    if (p === "/api/monitors/test") return { ok: true, ms: rnd(3, 40), msg: body.type === "http" ? "HTTP 200" : "OK" };
    if (p === "/api/monitors/kuma") return { found: false, message: "The demo has no Uptime Kuma to import from. On your server this finds the uptime-kuma container's database automatically." };
    if ((m = p.match(/^\/api\/monitors\/(\d+)(\/check)?$/))) {
      const mo = monitors.find(x => x.id === +m[1]);
      if (method === "DELETE") { monitors.splice(monitors.indexOf(mo), 1); return { ok: true }; }
      if (method === "PUT") { Object.assign(mo, body, { enabled: body.enabled === undefined ? mo.enabled : body.enabled ? 1 : 0 }); delete beatCache[mo.id]; return mo; }
      return monDetail(mo, q.get("range") || "24h");
    }
    if (p === "/api/settings" && method === "GET") return { settings, db: { path: "/data/homelabstats.db", size: 48.2 * MB, sys_raw: 17280, sys_5m: 25920, beats: 312400, speedtests: speedHistory.length, events: 1820, oldest: now() - 90 * 86400 }, version: VERSION };
    if (p === "/api/settings" && method === "PUT") {
      for (const [k, v] of Object.entries(body)) { if (k === "notify_on") Object.assign(settings.notify_on, v); else if (k === "container_links") { Object.keys(links).forEach(x => delete links[x]); Object.assign(links, v); } else settings[k] = v; }
      settings.notify_channels = settings.notify_channels.map(c => ({ ...c, id: c.id || Math.random().toString(16).slice(2, 10) }));
      return { settings };
    }
    if (p === "/api/settings/test-channel") return { ok: true };
    if (p === "/api/settings/compact") return { ok: true, size: 41.7 * MB };
    if (p === "/api/update") {
      if (method === "POST") throw new Error("Updates are disabled in the demo");
      return { current: VERSION, running: VERSION, latest: VERSION, update_available: false, check_error: null, last_check: now() - 40, can_update: true, reason: null, install_method: "docker", auto_update: false,
        repo: "bhxuk/HomeLabStats", branch: "main", state: "idle", log: [], error: null, changelog: window.HLS_CHANGELOG || [{ version: VERSION, date: "", installed: true, new: false, body: "See CHANGELOG.md on GitHub." }] };
    }
    if (p === "/api/health") return { ok: true, version: VERSION };
    throw new Error("Not available in the demo");
  }
  window.HLSDemo = { api };
})();
