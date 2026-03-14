"""
database/migrate.py — Apply schema migrations to an existing Turso/SQLite database.

Run once after pulling this update:
    python database/migrate.py

Idempotent: ignores "duplicate column" errors so it's safe to re-run.
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from database.connection import get_connection

NEW_COLUMNS = [
    ("raw_events", "input_tokens",          "INTEGER"),
    ("raw_events", "output_tokens",         "INTEGER"),
    ("raw_events", "cache_read_tokens",     "INTEGER"),
    ("raw_events", "cache_creation_tokens", "INTEGER"),
]


def run() -> None:
    db = get_connection()
    applied = 0
    skipped = 0
    for table, col, col_type in NEW_COLUMNS:
        try:
            db.execute(f"ALTER TABLE {table} ADD COLUMN {col} {col_type}")
            db.commit()
            print(f"  + {table}.{col}")
            applied += 1
        except Exception as exc:
            msg = str(exc).lower()
            if "duplicate column" in msg or "already exists" in msg:
                print(f"  = {table}.{col} (already exists)")
                skipped += 1
            else:
                print(f"  ! {table}.{col}: {exc}", file=sys.stderr)
                raise
    db.close()
    print(f"\nDone. {applied} column(s) added, {skipped} already present.")


if __name__ == "__main__":
    run()
