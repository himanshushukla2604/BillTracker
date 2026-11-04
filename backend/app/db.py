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
    user_id        INTEGER REFERENCES users(id) ON DELETE CASCADE,  -- NULL only for pre-account rows (hidden)
    name           TEXT    NOT NULL,
    amount         REAL    NOT NULL CHECK (amount > 0),
    reimbursed     REAL    NOT NULL DEFAULT 0,    -- part someone else paid back to you
    reimbursed_note TEXT,                          -- who / what for
    due_date       TEXT    NOT NULL,              -- ISO date
    category       TEXT    NOT NULL,
    recurring      TEXT    NOT NULL DEFAULT 'none',
    anchor_day     INTEGER NOT NULL,              -- original day-of-month, for month-end clamping
    paid           INTEGER NOT NULL DEFAULT 0,
    paid_on        TEXT,
    generated_from INTEGER REFERENCES expenses(id) ON DELETE SET NULL,
    payment_mode   TEXT,                           -- cash | upi | debit_card | net_banking | credit_card
    card_id        INTEGER REFERENCES cards(id) ON DELETE SET NULL,  -- set when paid by credit card
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

-- Credit cards: purchases charged to a card are grouped into statements by statement_day,
-- each payable by due_day; EMIs add a fixed instalment to each statement for `months` months.
CREATE TABLE IF NOT EXISTS cards (
    id            INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id       INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    name          TEXT    NOT NULL,
    kind          TEXT    NOT NULL DEFAULT 'credit',  -- credit | debit (debit: days unused)
    statement_day INTEGER NOT NULL CHECK (statement_day BETWEEN 1 AND 31),
    due_day       INTEGER NOT NULL CHECK (due_day BETWEEN 1 AND 31),
    created_at    TEXT    NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS emis (
    id             INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id        INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    card_id        INTEGER NOT NULL REFERENCES cards(id) ON DELETE CASCADE,
    name           TEXT    NOT NULL,
    category       TEXT    NOT NULL,
    monthly_amount REAL    NOT NULL CHECK (monthly_amount > 0),
    first_date     TEXT    NOT NULL,              -- date of the first instalment
    months         INTEGER NOT NULL CHECK (months > 0),
    created_at     TEXT    NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS card_payments (
    id             INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id        INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    card_id        INTEGER NOT NULL REFERENCES cards(id) ON DELETE CASCADE,
    statement_date TEXT    NOT NULL,
    amount         REAL    NOT NULL CHECK (amount > 0),
    paid_on        TEXT    NOT NULL
);

-- Money lent to someone, repaid in parts; reminders repeat every remind_every_days.
CREATE TABLE IF NOT EXISTS loans (
    id                INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id           INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    person            TEXT    NOT NULL,
    amount            REAL    NOT NULL CHECK (amount > 0),
    lent_on           TEXT    NOT NULL,
    due_date          TEXT,                         -- when you expect it back (optional)
    note              TEXT,
    remind_every_days INTEGER,                      -- NULL = no reminders
    next_remind_on    TEXT,
    created_at        TEXT    NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS loan_repayments (
    id      INTEGER PRIMARY KEY AUTOINCREMENT,
    loan_id INTEGER NOT NULL REFERENCES loans(id) ON DELETE CASCADE,
    amount  REAL    NOT NULL CHECK (amount > 0),
    paid_on TEXT    NOT NULL
);

CREATE TABLE IF NOT EXISTS settings (
    user_id INTEGER REFERENCES users(id) ON DELETE CASCADE,
    key     TEXT NOT NULL,
    value   TEXT NOT NULL,
    PRIMARY KEY (user_id, key)
);
"""
SCHEMA_VERSION = 4


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
        _add_missing_columns(conn)
        conn.execute(f"PRAGMA user_version = {SCHEMA_VERSION}")
        conn.commit()
    finally:
        conn.close()


def _add_missing_columns(conn: sqlite3.Connection) -> None:
    """Additive upgrades (v1 -> v2 paid-back amounts, v2 -> v3 payment modes, v3 -> v4 debit cards): older databases
    just gain the columns."""
    have = {r[1] for r in conn.execute("PRAGMA table_info(expenses)")}
    if "reimbursed" not in have:
        conn.execute("ALTER TABLE expenses ADD COLUMN reimbursed REAL NOT NULL DEFAULT 0")
    if "reimbursed_note" not in have:
        conn.execute("ALTER TABLE expenses ADD COLUMN reimbursed_note TEXT")
    # v2 -> v3: how each expense was paid
    if "payment_mode" not in have:
        conn.execute("ALTER TABLE expenses ADD COLUMN payment_mode TEXT")
    if "card_id" not in have:
        conn.execute("ALTER TABLE expenses ADD COLUMN card_id INTEGER REFERENCES cards(id) ON DELETE SET NULL")
    # v3 -> v4: debit cards
    if "kind" not in {r[1] for r in conn.execute("PRAGMA table_info(cards)")}:
        conn.execute("ALTER TABLE cards ADD COLUMN kind TEXT NOT NULL DEFAULT 'credit'")


def _migrate_to_accounts(conn: sqlite3.Connection) -> None:
    """v0 -> v1: give every table an owner column. Rows from before accounts existed keep
    user_id NULL, so no account can see them. A copy of the old file is kept."""
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
