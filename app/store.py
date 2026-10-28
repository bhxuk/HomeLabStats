"""SQLite storage for everything HomeLabStats keeps on disk.

One file (DATA_DIR/homelabstats.db) holds metrics history, speed tests, monitors,
monitor heartbeats, the activity log and in-app settings. WAL mode keeps writes
from blocking the dashboard's reads.
"""
from __future__ import annotations

import json
import sqlite3
import threading
from pathlib import Path

SCHEMA = """
CREATE TABLE IF NOT EXISTS meta (key TEXT PRIMARY KEY, value TEXT);

CREATE TABLE IF NOT EXISTS sys_raw (
  ts INTEGER PRIMARY KEY, cpu REAL, mem REAL, swap REAL, load1 REAL, temp REAL,
  rx REAL, tx REAL, dr REAL, dw REAL
);
CREATE TABLE IF NOT EXISTS sys_5m (
  ts INTEGER PRIMARY KEY, cpu REAL, mem REAL, swap REAL, load1 REAL, temp REAL,
  rx REAL, tx REAL, dr REAL, dw REAL, cpu_max REAL, rx_max REAL, tx_max REAL
);
CREATE TABLE IF NOT EXISTS ct_raw (ts INTEGER, name TEXT, cpu REAL, mem REAL, rx REAL, tx REAL, PRIMARY KEY (ts, name));
CREATE TABLE IF NOT EXISTS ct_5m  (ts INTEGER, name TEXT, cpu REAL, mem REAL, rx REAL, tx REAL, PRIMARY KEY (ts, name));
CREATE INDEX IF NOT EXISTS ct_raw_name ON ct_raw (name, ts);
CREATE INDEX IF NOT EXISTS ct_5m_name ON ct_5m (name, ts);

CREATE TABLE IF NOT EXISTS speedtests (
  id INTEGER PRIMARY KEY AUTOINCREMENT, ts REAL, engine TEXT, trigger TEXT,
  download REAL, upload REAL, ping REAL, jitter REAL, server TEXT, isp TEXT, ip TEXT, error TEXT
);
CREATE INDEX IF NOT EXISTS speedtests_ts ON speedtests (ts);

CREATE TABLE IF NOT EXISTS monitors (
  id INTEGER PRIMARY KEY AUTOINCREMENT, name TEXT NOT NULL, type TEXT NOT NULL, target TEXT NOT NULL,
  port INTEGER, interval INTEGER DEFAULT 60, timeout INTEGER DEFAULT 10, keyword TEXT, expect TEXT DEFAULT '200-399',
  method TEXT DEFAULT 'GET', ignore_tls INTEGER DEFAULT 0, invert INTEGER DEFAULT 0, retries INTEGER DEFAULT 1,
  enabled INTEGER DEFAULT 1, notify INTEGER DEFAULT 1, created REAL, sort INTEGER DEFAULT 0
);
CREATE TABLE IF NOT EXISTS beats (monitor_id INTEGER, ts REAL, ok INTEGER, ms REAL, msg TEXT);
CREATE INDEX IF NOT EXISTS beats_m_ts ON beats (monitor_id, ts);
CREATE INDEX IF NOT EXISTS beats_ts ON beats (ts);

CREATE TABLE IF NOT EXISTS events (
  id INTEGER PRIMARY KEY AUTOINCREMENT, ts REAL, kind TEXT, level TEXT, title TEXT, detail TEXT
);
CREATE INDEX IF NOT EXISTS events_ts ON events (ts);
"""


class Store:
    def __init__(self, path: Path) -> None:
        self.path = path
        self.lock = threading.RLock()
        self.conn = sqlite3.connect(str(path), check_same_thread=False, isolation_level=None, timeout=30)
        self.conn.row_factory = sqlite3.Row
        self.conn.execute("PRAGMA journal_mode=WAL")
        self.conn.execute("PRAGMA synchronous=NORMAL")
        self.conn.executescript(SCHEMA)

    def q(self, sql: str, args: tuple | list = ()) -> list[dict]:
        with self.lock:
            return [dict(r) for r in self.conn.execute(sql, args).fetchall()]

    def one(self, sql: str, args: tuple | list = ()) -> dict | None:
        with self.lock:
            r = self.conn.execute(sql, args).fetchone()
            return dict(r) if r else None

    def x(self, sql: str, args: tuple | list = ()) -> sqlite3.Cursor:
        with self.lock:
            return self.conn.execute(sql, args)

    def many(self, sql: str, rows: list) -> None:
        if not rows:
            return
        with self.lock:
            self.conn.execute("BEGIN")
            try:
                self.conn.executemany(sql, rows)
                self.conn.execute("COMMIT")
            except Exception:
                self.conn.execute("ROLLBACK")
                raise

    def get_meta(self, key: str, default=None):
        r = self.one("SELECT value FROM meta WHERE key=?", (key,))
        if not r:
            return default
        try:
            return json.loads(r["value"])
        except ValueError:
            return default

    def set_meta(self, key: str, value) -> None:
        self.x("INSERT INTO meta(key, value) VALUES(?, ?) ON CONFLICT(key) DO UPDATE SET value=excluded.value",
               (key, json.dumps(value)))

    def size(self) -> int:
        total = 0
        for suffix in ("", "-wal", "-shm"):
            p = Path(str(self.path) + suffix)
            if p.exists():
                total += p.stat().st_size
        return total

    def vacuum(self) -> None:
        with self.lock:
            self.conn.execute("PRAGMA wal_checkpoint(TRUNCATE)")
            self.conn.execute("VACUUM")
