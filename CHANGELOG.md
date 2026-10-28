# Changelog

All notable changes to HomeLabStats are listed here. The in-app **Updates** tab reads this file,
so every release needs an entry. Versions follow [semantic versioning](https://semver.org).

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
