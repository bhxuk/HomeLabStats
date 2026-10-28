#!/usr/bin/env bash
# HomeLabStats bare-metal installer (no Docker needed to run the dashboard itself).
# Installs to /opt/homelabstats, creates a "homelabstats" system user and a systemd service.
#
#   curl -fsSL https://raw.githubusercontent.com/bhxuk/HomeLabStats/main/install.sh | sudo bash
#   or, from a clone:  sudo ./install.sh
set -euo pipefail

REPO="https://github.com/bhxuk/HomeLabStats.git"
DIR="/opt/homelabstats"
ENV_FILE="/etc/homelabstats.env"
SVC="/etc/systemd/system/homelabstats.service"
PORT="${PORT:-8090}"

c() { printf '\033[36m==>\033[0m %s\n' "$*"; }
die() { printf '\033[31merror:\033[0m %s\n' "$*" >&2; exit 1; }

[ "$(id -u)" -eq 0 ] || die "run as root (sudo ./install.sh)"
command -v systemctl >/dev/null || die "systemd is required"

c "Installing system packages"
if command -v apt-get >/dev/null; then
  apt-get update -qq
  apt-get install -y -qq python3 python3-venv python3-pip git iputils-ping >/dev/null
elif command -v dnf >/dev/null; then
  dnf install -y -q python3 python3-pip git iputils
elif command -v pacman >/dev/null; then
  pacman -Sy --noconfirm --needed python python-pip git iputils
else
  die "unsupported package manager: install python3, venv, git and ping yourself"
fi

c "Creating service user"
id homelabstats >/dev/null 2>&1 || useradd --system --home-dir "$DIR" --shell /usr/sbin/nologin homelabstats
if getent group docker >/dev/null; then
  usermod -aG docker homelabstats
  c "Added homelabstats to the docker group (needed for the Docker tab)"
fi

c "Fetching HomeLabStats into $DIR"
if [ -d "$DIR/.git" ]; then
  git config --global --add safe.directory "$DIR" 2>/dev/null || true
  git -C "$DIR" pull --ff-only
else
  rm -rf "$DIR"
  git clone "$REPO" "$DIR"
fi
# The service owns its folder so the in-app updater can pull new versions.
chown -R homelabstats:homelabstats "$DIR"

c "Creating Python environment"
runuser -u homelabstats -- python3 -m venv "$DIR/.venv"
runuser -u homelabstats -- "$DIR/.venv/bin/pip" install -q --upgrade pip
runuser -u homelabstats -- "$DIR/.venv/bin/pip" install -q -r "$DIR/requirements.txt"

mkdir -p /var/lib/homelabstats
chown -R homelabstats:homelabstats /var/lib/homelabstats "$DIR"

if [ ! -f "$ENV_FILE" ]; then
  c "Writing config to $ENV_FILE"
  PASS="$(head -c 18 /dev/urandom | base64 | tr -dc 'A-Za-z0-9' | head -c 16)"
  cat > "$ENV_FILE" <<EOF
# HomeLabStats settings. Restart after editing: sudo systemctl restart homelabstats
PORT=$PORT
BIND=0.0.0.0
DATA_DIR=/var/lib/homelabstats
DASH_USER=admin
DASH_PASSWORD=$PASS
PING_TARGETS=1.1.1.1,8.8.8.8,google.com
DNS_NAMES=google.com,cloudflare.com,github.com
UPDATE_CHECK_HOURS=6
AUTO_UPDATE=false
EOF
  chmod 640 "$ENV_FILE"
  chgrp homelabstats "$ENV_FILE"
  NEW_PASS="$PASS"
fi

c "Installing systemd service"
cat > "$SVC" <<EOF
[Unit]
Description=HomeLabStats server dashboard
After=network-online.target docker.service
Wants=network-online.target

[Service]
User=homelabstats
Group=homelabstats
WorkingDirectory=$DIR
EnvironmentFile=$ENV_FILE
Environment=INSTALL_METHOD=systemd HOME=$DIR
ExecStart=$DIR/.venv/bin/python -m app.main
# Always restart: the in-app updater exits after installing a new version.
Restart=always
RestartSec=3
AmbientCapabilities=CAP_NET_RAW
NoNewPrivileges=true
ProtectSystem=strict
ReadWritePaths=/var/lib/homelabstats $DIR
ProtectHome=read-only
PrivateTmp=true

[Install]
WantedBy=multi-user.target
EOF

systemctl daemon-reload
systemctl enable --now homelabstats >/dev/null
systemctl restart homelabstats

IP="$(hostname -I 2>/dev/null | awk '{print $1}')"
echo
c "HomeLabStats is running: http://${IP:-localhost}:$PORT"
if [ -n "${NEW_PASS:-}" ]; then
  echo "    username: admin"
  echo "    password: $NEW_PASS   (change it in $ENV_FILE)"
fi
echo "    logs:     journalctl -u homelabstats -f"
echo "    updates:  use the Updates tab in the dashboard, or re-run this installer"
