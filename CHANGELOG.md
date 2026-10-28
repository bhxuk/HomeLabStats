# Changelog

All notable changes to HomeLabStats are listed here. The in-app **Updates** tab reads this file,
so every release needs an entry. Versions follow [semantic versioning](https://semver.org).

## [1.2.0] - 2026-10-28

### Added
- **Open buttons:** every container with a web interface gets an Open button, and every port is a clickable link. Links use the address you are browsing from, so they work on your LAN and over Tailscale
- Host-network containers (like Plex and Home Assistant) have their listening ports detected automatically, so they get links too
- **Set web address:** give any container its own URL (for example a path like `/admin`, or a reverse proxy domain) from its ⋯ menu or details panel. Containers with a `homelabstats.url` or `homepage.href` label use that automatically

### Changed
- The Docker table fits narrower screens: container controls moved into a ⋯ menu next to Open and Logs, and the Image, Net I/O, Uptime and Ports columns hide in turn as the window narrows (they are all still in the details panel)

## [1.1.0] - 2026-10-28

Everything you need to retire Netdata, Glances, Dozzle, Uptime Kuma and Speedtest Tracker.

### Added
- **Docker management:** start, stop, restart, pause, resume and remove containers, with a details panel per container (ports, volumes, networks, restart policy, health check log and CPU and memory history)
- **Docker disk usage and cleanup:** see space used by images, build cache, stopped containers and volumes, and clear unused images, dangling images, build cache or stopped containers in one click
- **Logs tab:** live-tailing container logs with search (regex works), error and warning highlighting, level filter, wrap and timestamp toggles and download
- **Monitors tab:** uptime checks for websites (with status codes and keyword matching), TCP ports, ping, DNS and Docker containers, with uptime %, response time charts, incidents and heartbeat bars
- **Import from Uptime Kuma:** copies your existing monitors and Discord, Telegram, ntfy, Slack and webhook alert channels straight from the Uptime Kuma container
- **Alerts:** Discord, Telegram, ntfy, Slack and webhook notifications when a monitor goes down or recovers, a container crashes or turns unhealthy, a disk is nearly full, a speed test is slow, or an update is out
- **Metrics tab:** CPU, memory, swap, load, temperature, network and disk I/O history from 1 hour to 90 days, per-container CPU, memory and network history, plus every temperature sensor, fan, core clock and logged-in user
- **Speed test log:** every result is saved, with automatic tests on a schedule, 24h / 7d / 30d / all-time averages, a history chart, failed tests listed, CSV export and an alert when download drops below your threshold
- **Live bandwidth:** current incoming and outgoing speed, today's totals and peaks, and the busiest interfaces
- **Settings tab** to change all of this from the app, plus a full activity log
- End or force-kill processes from the Processes tab
- Group containers by compose project

### Changed
- Container controls are now on by default and are switched on or off in **Settings**. The `ALLOW_CONTAINER_ACTIONS` setting is no longer used
- Speed test history moved into the new database. Existing results are migrated automatically
- HomeLabStats refuses to stop, pause or remove its own container, so you can't lock yourself out

## [1.0.0] - 2026-10-28

### Added
- Overview with live CPU, memory, temperature, load average and network charts, per-core usage and health alerts
- Process explorer covering every process on the host, sortable and searchable, showing which Docker container owns each process
- Docker tab with container health, CPU, memory, network I/O, ports, uptime, a live log viewer and optional start, stop and restart buttons
- Storage tab with used, free and total space for every real disk (including SMB and NFS mounts) and live disk activity
- Network tab with gateway, ping, DNS and HTTPS checks, public IP, per-interface throughput and Cloudflare or Ookla speed tests with history
- In-app **Updates** tab: checks GitHub for new versions, shows this changelog and installs updates with one click, then restarts itself
- Optional password protection, scheduled speed tests and automatic updates
- Docker Compose and bare-metal (systemd) installs
