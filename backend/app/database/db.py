"""SQLite access helpers (stdlib sqlite3, one connection per request/thread)."""
from __future__ import annotations

import json
import sqlite3
import threading
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path

from app.config import settings

SCHEMA = Path(__file__).with_name("schema.sql")
_local = threading.local()


def now_iso() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


def connect(path: Path | None = None) -> sqlite3.Connection:
    path = Path(path or settings.db_path)
    path.parent.mkdir(parents=True, exist_ok=True)
    con = sqlite3.connect(str(path), check_same_thread=False, timeout=30)
    con.row_factory = sqlite3.Row
    con.execute("PRAGMA journal_mode=WAL")
    con.execute("PRAGMA synchronous=NORMAL")
    con.execute("PRAGMA foreign_keys=ON")
    return con


def get_conn() -> sqlite3.Connection:
    """Thread-local connection for the API process."""
    con = getattr(_local, "con", None)
    if con is None or getattr(_local, "path", None) != str(settings.db_path):
        con = connect()
        _local.con, _local.path = con, str(settings.db_path)
    return con


def init_schema(con: sqlite3.Connection):
    con.executescript(SCHEMA.read_text())
    con.commit()


@contextmanager
def tx(con: sqlite3.Connection):
    try:
        yield con
        con.commit()
    except Exception:
        con.rollback()
        raise


def rows(con, sql, params=()) -> list[dict]:
    return [dict(r) for r in con.execute(sql, params).fetchall()]


def one(con, sql, params=()) -> dict | None:
    r = con.execute(sql, params).fetchone()
    return dict(r) if r else None


def audit(con, action: str, actor: str | None = None, entity: str | None = None, entity_id: str | None = None,
          detail: dict | None = None, rule_version: str | None = None, model_version: str | None = None):
    con.execute("INSERT INTO audit_logs (ts, actor, action, entity, entity_id, rule_version, model_version, detail_json) VALUES (?,?,?,?,?,?,?,?)",
                (now_iso(), actor, action, entity, entity_id, rule_version, model_version, json.dumps(detail or {}, default=str)))
