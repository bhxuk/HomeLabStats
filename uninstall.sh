#!/usr/bin/env bash
# Removes a bare-metal HomeLabStats install. Speed test history in /var/lib/homelabstats is kept
# unless you pass --purge.
set -euo pipefail
[ "$(id -u)" -eq 0 ] || { echo "run as root"; exit 1; }
systemctl disable --now homelabstats 2>/dev/null || true
rm -f /etc/systemd/system/homelabstats.service
systemctl daemon-reload
rm -rf /opt/homelabstats
if [ "${1:-}" = "--purge" ]; then
  rm -rf /var/lib/homelabstats /etc/homelabstats.env
  userdel homelabstats 2>/dev/null || true
fi
echo "HomeLabStats removed."
