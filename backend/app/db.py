"""SQLite access. One small file-backed database; no ORM needed."""
from __future__ import annotations

import os
import sqlite3
from contextlib import closing
from pathlib import Path
from typing import Iterator

DEFAULT_DB = Path(__file__).resolve().parent.parent / "data" / "finance.db"


def db_path() -> str:
    return os.environ.get("FT_DB", str(DEFAULT_DB))


SCHEMA = """
CREATE TABLE IF NOT EXISTS users (
    id            INTEGER PRIMARY KEY AUTOINCREMENT,
    email         TEXT    NOT NULL UNIQUE COLLATE NOCASE,
    password_hash TEXT    NOT NULL,
    created_at    TEXT    NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS sessions (
    token_hash TEXT    PRIMARY KEY,                -- sha256 of the cookie value
    user_id    INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    expires_at TEXT    NOT NULL
);

CREATE TABLE IF NOT EXISTS expenses (
    id             INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id        INTEGER REFERENCES users(id) ON DELETE CASCADE,  -- NULL only for pre-account data
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
CREATE INDEX IF NOT EXISTS idx_expenses_user_due ON expenses(user_id, due_date);
CREATE INDEX IF NOT EXISTS idx_expenses_cat ON expenses(category);

CREATE TABLE IF NOT EXISTS budgets (
    user_id        INTEGER REFERENCES users(id) ON DELETE CASCADE,
    category       TEXT NOT NULL,
    monthly_target REAL NOT NULL CHECK (monthly_target >= 0),
    PRIMARY KEY (user_id, category)
);

CREATE TABLE IF NOT EXISTS settings (
    user_id INTEGER REFERENCES users(id) ON DELETE CASCADE,
    key     TEXT NOT NULL,
    value   TEXT NOT NULL,
    PRIMARY KEY (user_id, key)
);
"""
SCHEMA_VERSION = 1


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
        version = conn.execute("PRAGMA user_version").fetchone()[0]
        has_data = conn.execute(
            "SELECT 1 FROM sqlite_master WHERE type='table' AND name='expenses'"
        ).fetchone()
        if version == 0 and has_data:
            _migrate_to_accounts(conn)
        conn.executescript(SCHEMA)
        conn.execute(f"PRAGMA user_version = {SCHEMA_VERSION}")
        conn.commit()
    finally:
        conn.close()


def _migrate_to_accounts(conn: sqlite3.Connection) -> None:
    """v0 -> v1: give every table an owner. Existing rows keep user_id NULL until the
    first account is registered, which adopts them. A copy of the old file is kept."""
    path = db_path()
    if path != ":memory:":
        saved = Path(path).with_name(Path(path).stem + ".pre-accounts.db")
        if not saved.exists():
            with closing(sqlite3.connect(saved)) as out:
                conn.backup(out)
    conn.executescript("""
        ALTER TABLE expenses ADD COLUMN user_id INTEGER REFERENCES users(id) ON DELETE CASCADE;
        ALTER TABLE budgets  RENAME TO budgets_v0;
        ALTER TABLE settings RENAME TO settings_v0;
    """)
    conn.executescript(SCHEMA)
    conn.executescript("""
        INSERT INTO budgets (user_id, category, monthly_target) SELECT NULL, category, monthly_target FROM budgets_v0;
        INSERT INTO settings (user_id, key, value) SELECT NULL, key, value FROM settings_v0 WHERE key != 'seeded';
        DROP TABLE budgets_v0;
        DROP TABLE settings_v0;
        DROP INDEX IF EXISTS idx_expenses_due;
    """)


def get_conn() -> Iterator[sqlite3.Connection]:
    """FastAPI dependency: one connection per request."""
    conn = connect()
    try:
        yield conn
    finally:
        conn.close()
