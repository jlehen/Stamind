#!/usr/bin/env python3
"""One-off migration: add the columns the calendar, the "Goals & plan" page and the chat read.

`workouts.short_name` is what kind of session it is, in at most five characters
(DESIGN_calendar_miniapp.md §3.6). `mesocycles.summary` is one line on what a mesocycle is
for (§3.7). `workouts.summary` is a session's short line (DESIGN_short_messages.md §4).
`mesocycles.deload_start` is the first day of a mesocycle's deload (DESIGN_deload_weeks.md
§4.1). `_init_db` only creates tables and never adds a column to one that exists, so a database
made before the SCHEMA_VERSION that brought a column (22, 29, 30) needs this script.

It adds each column whenever it is missing, whatever version the database is stamped with,
and does nothing when it is already there. It opens the file with plain `sqlite3`: opening
it through `Database` would stamp the new version first and leave the columns missing.

It operates on the instance named by `STAMIND_CONFIG`, or on the default config when that
variable is unset (ARCHITECTURE.md §9). Run it once per athlete, from the repository root,
before main moves to the new code: the bot runs each command from the checkout, so the new
code is live without a restart.

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

COLUMNS = (("workouts", "short_name"), ("mesocycles", "summary"), ("workouts", "summary"),
           ("mesocycles", "deload_start"))


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
    print(f"{db_path} already has every column. Nothing to do.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
