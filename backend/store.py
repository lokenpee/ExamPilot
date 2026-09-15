from __future__ import annotations

import json
import os
import sqlite3
import time
import uuid
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DATA = Path(os.environ.get("EXAMPILOT_DATA_DIR", ROOT / "data")).resolve()


def uid(prefix: str) -> str:
    return prefix + "_" + uuid.uuid4().hex[:16]


class Store:
    """Small durable document store. All application mutations run on one event loop."""

    def __init__(self, directory: Path = DATA, readonly: bool = False):
        self.directory = directory
        self.path = directory / "exampilot.sqlite3"
        self.readonly = readonly
        if not readonly:
            directory.mkdir(parents=True, exist_ok=True)
            with self.connect() as db:
                db.execute("PRAGMA journal_mode=WAL")
                db.execute("CREATE TABLE IF NOT EXISTS records (kind TEXT NOT NULL, id TEXT NOT NULL, payload TEXT NOT NULL, PRIMARY KEY(kind,id))")
                db.execute("PRAGMA user_version=1")

    def connect(self):
        if self.readonly:
            db = sqlite3.connect(self.path.as_uri() + "?mode=ro", uri=True, timeout=10)
        else:
            db = sqlite3.connect(self.path, timeout=10)
        return db

    def get(self, kind: str, ident: str):
        with self.connect() as db:
            row = db.execute("SELECT payload FROM records WHERE kind=? AND id=?", (kind, ident)).fetchone()
        return json.loads(row[0]) if row else None

    def all(self, kind: str):
        with self.connect() as db:
            rows = db.execute("SELECT payload FROM records WHERE kind=? ORDER BY rowid", (kind,)).fetchall()
        return [json.loads(row[0]) for row in rows]

    def put(self, kind: str, item: dict):
        self.put_many([(kind, item)])
        return item

    def put_many(self, entries: list[tuple[str, dict]]):
        if self.readonly:
            raise PermissionError("Read-only store")
        with self.connect() as db:
            db.executemany("INSERT INTO records(kind,id,payload) VALUES(?,?,?) ON CONFLICT(kind,id) DO UPDATE SET payload=excluded.payload", [(k, v["id"], json.dumps(v, ensure_ascii=False)) for k, v in entries])

    def event(self, job_id: str, name: str, detail: dict):
        return self.put("events", {"id": uid("ev"), "job_id": job_id, "name": name, "time": time.time(), **detail})

