"""Self-update support for HomeLabStats.

Both install methods run from a git checkout of the repo:
  * Docker: the repo folder is mounted into the container at /app and the
    container's restart policy brings it back up after the process exits.
  * systemd: the installer clones into /opt/homelabstats and the unit uses
    Restart=always.

An update is: git fetch, fast-forward merge, reinstall Python requirements if
they changed, then exit so the supervisor restarts us on the new code. User
settings live in untracked files (.env, /etc/homelabstats.env), so updates
never touch them.
"""
from __future__ import annotations

import hashlib
import os
import re
import shutil
import subprocess
import sys
import threading
import time
import urllib.request
from pathlib import Path

REPO_DIR = Path(__file__).resolve().parent.parent
VERSION_FILE = Path(__file__).resolve().parent / "VERSION"
CHANGELOG_FILE = REPO_DIR / "CHANGELOG.md"
UPDATE_REPO = os.environ.get("UPDATE_REPO", "bhxuk/HomeLabStats")
UPDATE_BRANCH = os.environ.get("UPDATE_BRANCH", "main")
INSTALL_METHOD = os.environ.get("INSTALL_METHOD", "manual")  # docker | systemd | manual
AUTO_UPDATE = os.environ.get("AUTO_UPDATE", "false").strip().lower() in ("1", "true", "yes", "on")
CHECK_INTERVAL_HOURS = float(os.environ.get("UPDATE_CHECK_HOURS", "6"))
RAW_BASE = os.environ.get("UPDATE_RAW_BASE", f"https://raw.githubusercontent.com/{UPDATE_REPO}/{UPDATE_BRANCH}").rstrip("/")

HEADING_RE = re.compile(r"^##\s+\[?v?(\d+\.\d+\.\d+)\]?(?:\s*[-–]\s*(.+?))?\s*$", re.M)


def local_version() -> str:
    try:
        return VERSION_FILE.read_text().strip()
    except OSError:
        return "0.0.0"


def vtuple(v: str) -> tuple[int, ...]:
    try:
        return tuple(int(x) for x in re.findall(r"\d+", v)[:3])
    except ValueError:
        return (0,)


def parse_changelog(text: str) -> list[dict]:
    entries = []
    matches = list(HEADING_RE.finditer(text))
    for i, m in enumerate(matches):
        end = matches[i + 1].start() if i + 1 < len(matches) else len(text)
        body = text[m.end():end].strip()
        entries.append({"version": m.group(1), "date": (m.group(2) or "").strip(), "body": body})
    return entries


def _fetch(path: str, timeout: float = 8) -> str:
    url = f"{RAW_BASE}/{path}?t={int(time.time())}"
    req = urllib.request.Request(url, headers={"User-Agent": "homelabstats-updater", "Cache-Control": "no-cache"})
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return r.read().decode("utf-8", errors="replace")


def _git(*args: str, timeout: float = 120) -> subprocess.CompletedProcess:
    return subprocess.run(["git", "-C", str(REPO_DIR), *args], capture_output=True, text=True, timeout=timeout)


def _req_hash() -> str:
    try:
        return hashlib.sha256((REPO_DIR / "requirements.txt").read_bytes()).hexdigest()
    except OSError:
        return ""


class Updater:
    def __init__(self) -> None:
        self.lock = threading.Lock()
        self.state = "idle"  # idle | checking | updating | restarting | restart_required | error
        self.log: list[str] = []
        self.error: str | None = None
        self.last_check: float | None = None
        self.remote: dict | None = None
        self.started_version = local_version()

    # ---- capability ---------------------------------------------------------
    def can_update(self) -> tuple[bool, str | None]:
        if not (REPO_DIR / ".git").exists():
            return False, "This install is not a git checkout, so it cannot update itself. Reinstall using the README steps."
        if not shutil.which("git"):
            return False, "git is not installed."
        if not os.access(REPO_DIR, os.W_OK) or not os.access(REPO_DIR / ".git", os.W_OK):
            return False, f"No write access to {REPO_DIR}. Re-run the installer to fix permissions."
        return True, None

    # ---- checking -----------------------------------------------------------
    def check(self, force: bool = False) -> dict:
        if not force and self.remote and self.last_check and time.time() - self.last_check < 600:
            return self.remote
        prev = self.state
        if prev == "idle":
            self.state = "checking"
        try:
            latest = _fetch("app/VERSION").strip()
            try:
                changelog = parse_changelog(_fetch("CHANGELOG.md"))
            except Exception:
                changelog = []
            self.remote = {"latest": latest, "changelog": changelog, "error": None}
        except Exception as exc:
            self.remote = {"latest": None, "changelog": [], "error": f"Could not reach GitHub: {exc}"}
        finally:
            self.last_check = time.time()
            if self.state == "checking":
                self.state = prev
        return self.remote

    def status(self, check: bool = False, force: bool = False) -> dict:
        remote = self.check(force=force) if check else (self.remote or {"latest": None, "changelog": [], "error": None})
        current = local_version()
        latest = remote.get("latest")
        try:
            local_log = parse_changelog(CHANGELOG_FILE.read_text())
        except OSError:
            local_log = []
        changelog = remote.get("changelog") or local_log
        for e in changelog:
            e["new"] = vtuple(e["version"]) > vtuple(current)
            e["installed"] = e["version"] == current
        ok, reason = self.can_update()
        return {
            "current": current,
            "running": self.started_version,
            "latest": latest,
            "update_available": bool(latest) and vtuple(latest) > vtuple(current),
            "changelog": changelog,
            "check_error": remote.get("error"),
            "last_check": self.last_check,
            "can_update": ok,
            "reason": reason,
            "install_method": INSTALL_METHOD,
            "auto_update": AUTO_UPDATE,
            "repo": UPDATE_REPO,
            "branch": UPDATE_BRANCH,
            "state": self.state,
            "log": self.log[-200:],
            "error": self.error,
        }

    # ---- applying -----------------------------------------------------------
    def start(self) -> bool:
        ok, reason = self.can_update()
        if not ok:
            self.error = reason
            return False
        with self.lock:
            if self.state in ("updating", "restarting"):
                return False
            self.state = "updating"
            self.error = None
            self.log = []
        threading.Thread(target=self._run, daemon=True).start()
        return True

    def _say(self, msg: str) -> None:
        self.log.append(f"[{time.strftime('%H:%M:%S')}] {msg}")
        print(f"[updater] {msg}", flush=True)

    def _run(self) -> None:
        try:
            before = local_version()
            req_before = _req_hash()
            _git("config", "--global", "--add", "safe.directory", str(REPO_DIR))
            self._say(f"Current version {before}. Fetching {UPDATE_REPO}@{UPDATE_BRANCH}")
            if (REPO_DIR / ".git" / "shallow").exists():
                r = _git("fetch", "--unshallow", "origin", UPDATE_BRANCH, timeout=300)
                if r.returncode != 0:
                    r = _git("fetch", "origin", UPDATE_BRANCH, timeout=300)
            else:
                r = _git("fetch", "origin", UPDATE_BRANCH, timeout=300)
            if r.returncode != 0:
                raise RuntimeError(f"git fetch failed: {(r.stderr or r.stdout).strip()}")

            head = _git("rev-parse", "--short", "HEAD").stdout.strip()
            target = _git("rev-parse", "--short", "FETCH_HEAD").stdout.strip()
            if head == target:
                self._say("Already up to date.")
                self.state = "idle"
                return
            self._say(f"Updating {head} -> {target}")
            r = _git("merge", "--ff-only", "FETCH_HEAD")
            if r.returncode != 0:
                raise RuntimeError(
                    "Could not fast-forward. Files in the install folder were changed locally. "
                    "Run `git status` there to see them. Details: " + (r.stderr or r.stdout).strip()
                )
            self._fix_ownership()
            after = local_version()
            self._say(f"Code updated to version {after}")

            if _req_hash() != req_before:
                self._say("Requirements changed, installing Python packages")
                pip = [sys.executable, "-m", "pip", "install", "-q", "-r", str(REPO_DIR / "requirements.txt")]
                if INSTALL_METHOD == "docker":
                    pip.insert(4, "--root-user-action=ignore")
                r = subprocess.run(pip, capture_output=True, text=True, timeout=600)
                if r.returncode != 0:
                    raise RuntimeError(f"pip install failed: {(r.stderr or r.stdout).strip()[-800:]}")
                self._say("Packages installed")

            if INSTALL_METHOD in ("docker", "systemd"):
                self._say("Restarting HomeLabStats")
                self.state = "restarting"
                threading.Thread(target=self._exit_soon, daemon=True).start()
            else:
                self._say("Done. Restart HomeLabStats to load the new version.")
                self.state = "restart_required"
        except Exception as exc:
            self.error = str(exc)
            self._say(f"Update failed: {exc}")
            self.state = "error"

    def _fix_ownership(self) -> None:
        """When running as root in Docker, keep the mounted repo owned by its original user."""
        if os.geteuid() != 0:
            return
        st = REPO_DIR.stat()
        if st.st_uid == 0:
            return
        subprocess.run(["chown", "-R", f"{st.st_uid}:{st.st_gid}", str(REPO_DIR)], capture_output=True)

    @staticmethod
    def _exit_soon() -> None:
        time.sleep(1.5)
        os._exit(3)  # non-zero so Restart=on-failure style supervisors restart us too

    def scheduler(self) -> None:
        time.sleep(30)
        while True:
            try:
                st = self.status(check=True, force=True)
                if AUTO_UPDATE and st["update_available"] and st["can_update"] and self.state == "idle":
                    self._say(f"Auto-update: {st['current']} -> {st['latest']}")
                    self.start()
            except Exception as exc:
                print(f"[updater] check failed: {exc!r}", flush=True)
            time.sleep(max(CHECK_INTERVAL_HOURS, 0.25) * 3600)


updater = Updater()
