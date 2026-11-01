"""Daily SQLite snapshots, plus a small CLI to back up or restore by hand.

Snapshots go to FT_BACKUP_DIR (default: a `backups/` folder next to the database) as
finance-YYYY-MM-DD.db, at most one per day; only the newest FT_BACKUP_KEEP (default 14)
are kept. Point FT_BACKUP_DIR at a synced folder (iCloud Drive, Dropbox) to keep copies
off this disk.

    python -m app.backup                    # snapshot now (replaces today's)
    python -m app.backup --list
    python -m app.backup --restore FILE     # stop the server first
"""
from __future__ import annotations

import argparse
import os
import shutil
import sqlite3
import sys
from contextlib import closing
from datetime import date
from pathlib import Path
from typing import Optional

from . import db

PREFIX = "finance-"


def enabled() -> bool:
    return os.environ.get("FT_BACKUP", "1") != "0" and db.db_path() != ":memory:"


def backup_dir() -> Path:
    return Path(os.environ.get("FT_BACKUP_DIR", Path(db.db_path()).parent / "backups"))


def keep_count() -> int:
    return max(1, int(os.environ.get("FT_BACKUP_KEEP", "14")))


def list_backups() -> list[Path]:
    """Newest first."""
    d = backup_dir()
    return sorted(d.glob(f"{PREFIX}*.db"), reverse=True) if d.is_dir() else []


def snapshot(dest: Path) -> Path:
    """Consistent copy of the live database (safe while the server is running)."""
    dest.parent.mkdir(parents=True, exist_ok=True)
    tmp = dest.with_suffix(".tmp")
    src = db.connect()
    try:
        out = sqlite3.connect(tmp)
        try:
            src.backup(out)
        finally:
            out.close()
    finally:
        src.close()
    tmp.replace(dest)
    return dest


def backup_if_due(today: Optional[date] = None, force: bool = False) -> Optional[Path]:
    """Take today's snapshot unless it exists already, then prune old ones."""
    if not enabled() or not Path(db.db_path()).exists():
        return None
    dest = backup_dir() / f"{PREFIX}{(today or date.today()).isoformat()}.db"
    if dest.exists() and not force:
        return None
    snapshot(dest)
    for old in list_backups()[keep_count():]:
        old.unlink()
    return dest


def restore(src: Path) -> Path:
    """Replace the database with `src`, saving the current one first. Run with the server stopped."""
    with closing(sqlite3.connect(f"file:{src}?mode=ro", uri=True)) as check:
        if check.execute("PRAGMA integrity_check").fetchone()[0] != "ok":
            raise ValueError(f"{src} is not a healthy SQLite database")
        check.execute("SELECT 1 FROM expenses LIMIT 1")
    live = Path(db.db_path())
    saved = live.with_name(f"{live.stem}.before-restore{live.suffix}")
    if live.exists():
        shutil.copy2(live, saved)
    shutil.copy2(src, live)
    return saved


def main(argv: Optional[list[str]] = None) -> int:
    p = argparse.ArgumentParser(prog="python -m app.backup", description="Back up or restore the bill tracker database.")
    g = p.add_mutually_exclusive_group()
    g.add_argument("--list", action="store_true", help="list snapshots, newest first")
    g.add_argument("--restore", metavar="FILE", type=Path, help="replace the database with FILE (stop the server first)")
    args = p.parse_args(argv)

    if args.list:
        for f in list_backups():
            print(f)
        return 0
    if args.restore:
        try:
            saved = restore(args.restore)
        except (ValueError, sqlite3.DatabaseError) as e:
            print(f"Not restored: {e}", file=sys.stderr)
            return 1
        print(f"Restored {args.restore}. The previous database was saved to {saved}.")
        return 0
    path = backup_if_due(force=True)
    print(f"Backed up to {path}" if path else "Nothing to back up (no database yet, or FT_BACKUP=0).")
    return 0


if __name__ == "__main__":
    sys.exit(main())
