"""SQLite access. One small file-backed database; no ORM needed."""
from __future__ import annotations

import os
import sqlite3
from pathlib import Path
from typing import Iterator

DEFAULT_DB = Path(__file__).resolve().parent.parent / "data" / "finance.db"


def db_path() -> str:
    return os.environ.get("FT_DB", str(DEFAULT_DB))


SCHEMA = """
CREATE TABLE IF NOT EXISTS expenses (
    id             INTEGER PRIMARY KEY AUTOINCREMENT,
    name           TEXT    NOT NULL,
    amount         REAL    NOT NULL CHECK (amount > 0),
    due_date       TEXT    NOT NULL,              -- ISO date
    category       TEXT    NOT NULL,
    recurring      TEXT    NOT NULL DEFAULT 'none',
    anchor_day     INTEGER NOT NULL,              -- original day-of-month, for month-end clamping
    paid           INTEGER NOT NULL DEFAULT 0,
    paid_on        TEXT,
    generated_from INTEGER REFERENCES expenses(id) ON DELETE SET NULL,
    created_at     TEXT    NOT NULL DEFAULT CURRENT_TIMESTAMP
);
CREATE INDEX IF NOT EXISTS idx_expenses_due ON expenses(due_date);
CREATE INDEX IF NOT EXISTS idx_expenses_cat ON expenses(category);

CREATE TABLE IF NOT EXISTS budgets (
    category       TEXT PRIMARY KEY,
    monthly_target REAL NOT NULL CHECK (monthly_target >= 0)
);

CREATE TABLE IF NOT EXISTS settings (
    key   TEXT PRIMARY KEY,
    value TEXT NOT NULL
);
"""


def connect() -> sqlite3.Connection:
    path = db_path()
    if path != ":memory:":
        Path(path).parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(path, check_same_thread=False)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    return conn


def init_db() -> None:
    conn = connect()
    try:
        conn.executescript(SCHEMA)
        conn.commit()
    finally:
        conn.close()


def get_conn() -> Iterator[sqlite3.Connection]:
    """FastAPI dependency: one connection per request."""
    conn = connect()
    try:
        yield conn
    finally:
        conn.close()
