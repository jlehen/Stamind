#!/usr/bin/env python3
"""One-off migration: add the `short_name` column to `workouts`.

`short_name` is what kind of session it is, in at most five characters, for the calendar
(DESIGN_calendar_miniapp.md §3.6). `_init_db` only creates tables and never adds a column
to one that exists, so a database made before SCHEMA_VERSION 20 needs this script.

It adds the column whenever it is missing, whatever version the database is stamped with,
and does nothing when it is already there. It opens the file with plain `sqlite3`: opening
it through `Database` would stamp version 20 first and leave the column missing.

It operates on the instance named by `STAMIND_CONFIG`, or on the default config when that
variable is unset (ARCHITECTURE.md §9). Run it once per athlete, from the repository root,
before the bots restart on the new code:

    venv/bin/python scripts/migrate_add_short_name.py
    STAMIND_CONFIG=piupiu/config_piupiu.yaml venv/bin/python scripts/migrate_add_short_name.py
"""
import os
import sqlite3
import sys

# Run as `venv/bin/python scripts/<this>` from the repo root: sys.path[0] is scripts/,
# so the package root has to be put on the path explicitly.
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from stamind.config import CONFIG_PATH, config


def add_short_name(db_path: str) -> bool:
    """Adds `workouts.short_name` when it is missing. Returns whether it added it."""
    conn = sqlite3.connect(db_path)
    try:
        columns = [row[1] for row in conn.execute("PRAGMA table_info(workouts)")]
        if "short_name" in columns:
            return False
        conn.execute("ALTER TABLE workouts ADD COLUMN short_name TEXT")
        conn.commit()
        return True
    finally:
        conn.close()


def main() -> int:
    print(f"Instance: {CONFIG_PATH}")
    db_path = config.db_path
    if not os.path.exists(db_path):
        print(f"No database at {db_path}. Nothing to migrate.")
        return 0
    if add_short_name(db_path):
        print(f"Added workouts.short_name to {db_path}.")
        return 0
    print(f"{db_path} already has workouts.short_name. Nothing to do.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
