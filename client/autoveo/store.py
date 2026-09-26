"""SQLite cục bộ: lịch sử job để tắt/mở app vẫn thấy và tiếp tục việc dở."""
from __future__ import annotations

import json
import sqlite3
import threading
from datetime import datetime
from pathlib import Path

FINAL = ("completed", "failed", "cancelled")

SCHEMA = """
CREATE TABLE IF NOT EXISTS jobs (
  id TEXT PRIMARY KEY, idem_key TEXT NOT NULL, batch_id TEXT, line_no INTEGER, mode TEXT NOT NULL,
  prompt TEXT, status TEXT NOT NULL, progress INTEGER NOT NULL DEFAULT 0, queue_pos INTEGER,
  gw_id TEXT, error TEXT, files_json TEXT, thumb TEXT, spec_json TEXT NOT NULL, out_dir TEXT,
  created_at TEXT NOT NULL, finished_at TEXT
);
"""


class Store:
    def __init__(self, path: Path):
        self.conn = sqlite3.connect(str(path), check_same_thread=False, isolation_level=None)
        self.conn.row_factory = sqlite3.Row
        self.lock = threading.RLock()
        with self.lock:
            self.conn.executescript(SCHEMA)

    def add(self, row: dict) -> None:
        cols = ",".join(row)
        with self.lock:
            self.conn.execute(f"INSERT INTO jobs({cols}) VALUES ({','.join('?' * len(row))})", tuple(row.values()))

    def update(self, job_id: str, **fields) -> None:
        if not fields:
            return
        sets = ",".join(f"{k}=?" for k in fields)
        with self.lock:
            self.conn.execute(f"UPDATE jobs SET {sets} WHERE id=?", (*fields.values(), job_id))

    def get(self, job_id: str):
        with self.lock:
            return self.conn.execute("SELECT * FROM jobs WHERE id=?", (job_id,)).fetchone()

    def all(self, where: str = "", params: tuple = ()):
        with self.lock:
            return self.conn.execute(f"SELECT * FROM jobs {where} ORDER BY created_at, line_no", params).fetchall()

    def active(self):
        return self.all("WHERE status NOT IN ('completed','failed','cancelled')")

    def delete(self, job_ids: list[str]) -> None:
        with self.lock:
            self.conn.executemany("DELETE FROM jobs WHERE id=?", [(i,) for i in job_ids])

    def close(self) -> None:
        with self.lock:
            self.conn.close()


def now_iso() -> str:
    return datetime.now().strftime("%Y-%m-%d %H:%M:%S")


def files_of(row) -> list[str]:
    try:
        return json.loads(row["files_json"] or "[]")
    except ValueError:
        return []
