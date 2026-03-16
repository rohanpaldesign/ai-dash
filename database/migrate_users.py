"""
database/migrate_users.py — One-time migration for Alpha 0.2 (multi-user auth).

Run once before deploying: python database/migrate_users.py

All steps are idempotent.
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from database.connection import execute_write, query_df


def _add_column(table: str, column: str, col_type: str) -> None:
    """Add a column to a table, silently ignoring 'duplicate column' errors."""
    try:
        execute_write(f"ALTER TABLE {table} ADD COLUMN {column} {col_type}")
        print(f"  Added {table}.{column}")
    except Exception as e:
        if "duplicate column" in str(e).lower() or "already exists" in str(e).lower():
            print(f"  {table}.{column} already exists — skipping")
        else:
            raise


def main() -> None:
    print("=== Alpha 0.2 Migration ===")

    # 1. Create users table
    print("\n[1] Creating users table...")
    execute_write("""
        CREATE TABLE IF NOT EXISTS users (
            user_id       TEXT PRIMARY KEY,
            username      TEXT UNIQUE NOT NULL,
            email         TEXT UNIQUE NOT NULL,
            display_name  TEXT,
            password_hash TEXT,
            google_sub    TEXT UNIQUE,
            created_at    TEXT NOT NULL,
            last_login    TEXT
        )
    """)
    print("  users table: OK")

    # 2. Create auth_otp table
    print("\n[2] Creating auth_otp table...")
    execute_write("""
        CREATE TABLE IF NOT EXISTS auth_otp (
            id          INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id     TEXT NOT NULL,
            code        TEXT NOT NULL,
            expires_at  TEXT NOT NULL,
            used        INTEGER DEFAULT 0
        )
    """)
    print("  auth_otp table: OK")

    # 3. Add user_id columns to data tables
    print("\n[3] Adding user_id columns to data tables...")
    for table in ("raw_events", "sessions", "daily_metrics"):
        _add_column(table, "user_id", "TEXT")

    # 4. Add purpose column to auth_otp
    print("\n[4] Adding purpose column to auth_otp...")
    _add_column("auth_otp", "purpose", "TEXT DEFAULT 'otp'")

    # 5. Add username_changes column to users
    print("\n[5] Adding username_changes column to users...")
    _add_column("users", "username_changes", "INTEGER DEFAULT 0")

    # 6. Add role column to users
    print("\n[6] Adding role column to users...")
    _add_column("users", "role", "TEXT DEFAULT 'basic'")

    # 7. Assign owner role to rohan
    print("\n[7] Assigning owner role to rohan...")
    execute_write("UPDATE users SET role = 'owner' WHERE username = 'rohan'")
    print("  Done (no-op if 'rohan' account does not yet exist).")

    # 8. Create user_sessions table
    print("\n[8] Creating user_sessions table...")
    execute_write("""
        CREATE TABLE IF NOT EXISTS user_sessions (
            token       TEXT PRIMARY KEY,
            user_id     TEXT NOT NULL,
            expires_at  TEXT NOT NULL,
            created_at  TEXT NOT NULL
        )
    """)
    print("  user_sessions table: OK")

    print("\n=== Migration complete. ===")
    print("Note: Existing data will be claimed automatically on first user signup.")


if __name__ == "__main__":
    main()
