"""Settings read from the environment, and shared constants."""
from __future__ import annotations

import os
import re
from datetime import datetime, timezone
from pathlib import Path

from .updater import INSTALL_METHOD, local_version  # noqa: F401  (re-exported)

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

