#!/usr/bin/env python3
"""One-off migration: add the two columns the calendar and the "Goals & plan" page read.

`workouts.short_name` is what kind of session it is, in at most five characters
(DESIGN_calendar_miniapp.md §3.6). `mesocycles.summary` is one line on what a mesocycle is
for (§3.7). `_init_db` only creates tables and never adds a column to one that exists, so a
database made before SCHEMA_VERSION 22 needs this script.

It adds each column whenever it is missing, whatever version the database is stamped with,
and does nothing when it is already there. It opens the file with plain `sqlite3`: opening
it through `Database` would stamp version 22 first and leave the columns missing.

It operates on the instance named by `STAMIND_CONFIG`, or on the default config when that
variable is unset (ARCHITECTURE.md §9). Run it once per athlete, from the repository root,
before the bots restart on the new code:

    venv/bin/python scripts/migrate_calendar_columns.py
    STAMIND_CONFIG=piupiu/config_piupiu.yaml venv/bin/python scripts/migrate_calendar_columns.py
"""
import os
import sqlite3
import sys
from typing import List

# Run as `venv/bin/python scripts/<this>` from the repo root: sys.path[0] is scripts/,
# so the package root has to be put on the path explicitly.
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from stamind.config import CONFIG_PATH, config

COLUMNS = (("workouts", "short_name"), ("mesocycles", "summary"))


def add_columns(db_path: str) -> List[str]:
    """Adds each of `COLUMNS` that is missing, as TEXT. Returns the ones it added."""
    added = []
    conn = sqlite3.connect(db_path)
    try:
        for table, column in COLUMNS:
            if column in [row[1] for row in conn.execute(f"PRAGMA table_info({table})")]:
                continue
            conn.execute(f"ALTER TABLE {table} ADD COLUMN {column} TEXT")
            added.append(f"{table}.{column}")
        conn.commit()
        return added
    finally:
        conn.close()


def main() -> int:
    print(f"Instance: {CONFIG_PATH}")
    db_path = config.db_path
    if not os.path.exists(db_path):
        print(f"No database at {db_path}. Nothing to migrate.")
        return 0
    added = add_columns(db_path)
    if added:
        print(f"Added {', '.join(added)} to {db_path}.")
        return 0
    print(f"{db_path} already has both columns. Nothing to do.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
