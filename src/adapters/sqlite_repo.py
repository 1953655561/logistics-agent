"""SQLite 仓储：审核单状态 + 事件流。

W5：连接允许跨线程复用（FastAPI/兜底服务都是多线程），所有读写用一把锁串行化。
"""
from __future__ import annotations

import json
import os
import sqlite3
import threading
from datetime import datetime

SCHEMA = """
CREATE TABLE IF NOT EXISTS cases (
    case_id    TEXT PRIMARY KEY,
    state      TEXT NOT NULL,
    payload    TEXT NOT NULL DEFAULT '{}',
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS events (
    id       INTEGER PRIMARY KEY AUTOINCREMENT,
    case_id  TEXT NOT NULL,
    ts       TEXT NOT NULL,
    kind     TEXT NOT NULL,
    payload  TEXT NOT NULL DEFAULT '{}'
);
CREATE INDEX IF NOT EXISTS idx_events_case ON events(case_id, id);
"""


def _now() -> str:
    return datetime.now().isoformat(timespec="seconds")


class SqliteRepo:
    def __init__(self, path: str):
        self.path = path
        d = os.path.dirname(os.path.abspath(path))
        os.makedirs(d, exist_ok=True)
        self._conn = sqlite3.connect(path, check_same_thread=False)
        self._conn.row_factory = sqlite3.Row
        self._lock = threading.RLock()
        with self._lock:
            self._conn.executescript(SCHEMA)
            self._conn.commit()

    def save_case(self, case: dict) -> None:
        cid = case["case_id"]
        payload = json.dumps(case.get("payload", {}), ensure_ascii=False)
        with self._lock:
            row = self._conn.execute(
                "SELECT created_at FROM cases WHERE case_id=?", (cid,)).fetchone()
            if row:
                self._conn.execute(
                    "UPDATE cases SET state=?, payload=?, updated_at=? WHERE case_id=?",
                    (case["state"], payload, _now(), cid))
            else:
                self._conn.execute(
                    "INSERT INTO cases(case_id,state,payload,created_at,updated_at) "
                    "VALUES(?,?,?,?,?)",
                    (cid, case["state"], payload, _now(), _now()))
            self._conn.commit()

    def load_case(self, case_id: str) -> dict | None:
        with self._lock:
            row = self._conn.execute(
                "SELECT * FROM cases WHERE case_id=?", (case_id,)).fetchone()
        if not row:
            return None
        return {"case_id": row["case_id"], "state": row["state"],
                "payload": json.loads(row["payload"]),
                "created_at": row["created_at"], "updated_at": row["updated_at"]}

    def list_cases(self, limit: int = 20) -> list[dict]:
        with self._lock:
            rows = self._conn.execute(
                "SELECT case_id,state,payload,updated_at FROM cases "
                "ORDER BY updated_at DESC LIMIT ?", (limit,)).fetchall()
        return [{"case_id": r["case_id"], "state": r["state"],
                 "payload": json.loads(r["payload"]), "updated_at": r["updated_at"]}
                for r in rows]

    def append_event(self, case_id: str, event: dict) -> None:
        with self._lock:
            self._conn.execute(
                "INSERT INTO events(case_id,ts,kind,payload) VALUES(?,?,?,?)",
                (case_id, event.get("ts", _now()), event.get("kind", "event"),
                 json.dumps(event, ensure_ascii=False)))
            self._conn.commit()

    def events(self, case_id: str) -> list[dict]:
        with self._lock:
            rows = self._conn.execute(
                "SELECT payload FROM events WHERE case_id=? ORDER BY id",
                (case_id,)).fetchall()
        return [json.loads(r["payload"]) for r in rows]

    def close(self) -> None:
        with self._lock:
            self._conn.close()
