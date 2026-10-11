#!/usr/bin/env python3
"""One-off migration: the athlete queue's rows get a ready time and a sent time.

`athlete_queue.ready_at` is the time from which an item may be sent, and `sent_at` is when
the bot last sent it (DESIGN_athlete_queue.md §13.2). They replace `remind_at`. `_init_db`
only creates tables and never changes one that exists, so a database made before
SCHEMA_VERSION 27 needs this script.

An item that was put off keeps its time: `ready_at` is its `remind_at`. Every other item is
ready from the moment it was queued. No item counts as sent, so the first item of the line
goes out on the bot's next wake in the daytime.

It rebuilds the table whenever `ready_at` is missing, whatever version the database is
stamped with, and does nothing when it is already there. It opens the file with plain
`sqlite3`: opening it through `Database` would stamp version 27 first and leave the table as
it was.

It operates on the instance named by `STAMIND_CONFIG`, or on the default config when that
variable is unset (ARCHITECTURE.md §9). Run it once per athlete, from the repository root:

    venv/bin/python scripts/migrate_queue_ready.py
    STAMIND_CONFIG=piupiu/config_piupiu.yaml venv/bin/python scripts/migrate_queue_ready.py

Land the code, run this and restart both bots back to back, at an hour when nobody is in
the chat and away from the morning message. A bot runs each command from the checkout, so
between the three steps the old bot meets the new code. Before this script has run, every
command that reads the queue fails. Once it has run, the old bot's scheduler fails on each
wake until the restart (DESIGN_athlete_queue.md §13.7).
"""
import os
import sqlite3
import sys

# Run as `venv/bin/python scripts/<this>` from the repo root: sys.path[0] is scripts/,
# so the package root has to be put on the path explicitly.
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from stamind.config import CONFIG_PATH, config

# The table as `db/schema.py` creates it at version 27.
NEW_TABLE = """
    CREATE TABLE athlete_queue_new (
        id         INTEGER PRIMARY KEY AUTOINCREMENT,
        kind       TEXT NOT NULL,
        subject    TEXT NOT NULL,
        payload    TEXT NOT NULL,
        queued_at  TEXT NOT NULL,
        ready_at   TEXT NOT NULL,
        sent_at    TEXT,
        closed_at  TEXT,
        outcome    TEXT,
        UNIQUE (kind, subject)
    )
"""


def migrate(db_path: str) -> bool:
    """Rebuilds `athlete_queue` with `ready_at` and `sent_at` in place of `remind_at`. False
    when the table already has `ready_at`, or does not exist."""
    conn = sqlite3.connect(db_path)
    try:
        columns = [row[1] for row in conn.execute("PRAGMA table_info(athlete_queue)")]
        if not columns or "ready_at" in columns:
            return False
        # One transaction, opened by hand because a CREATE does not open one: a failure
        # leaves the old table as it was and no half-built one beside it.
        with conn:
            conn.execute("BEGIN")
            conn.execute(NEW_TABLE)
            conn.execute(
                "INSERT INTO athlete_queue_new "
                "(id, kind, subject, payload, queued_at, ready_at, closed_at, outcome) "
                "SELECT id, kind, subject, payload, queued_at, "
                "COALESCE(remind_at, queued_at), closed_at, outcome FROM athlete_queue"
            )
            conn.execute("DROP TABLE athlete_queue")
            conn.execute("ALTER TABLE athlete_queue_new RENAME TO athlete_queue")
        return True
    finally:
        conn.close()


def main() -> int:
    print(f"Instance: {CONFIG_PATH}")
    db_path = config.db_path
    if not os.path.exists(db_path):
        print(f"No database at {db_path}. Nothing to migrate.")
        return 0
    if migrate(db_path):
        print(f"Rebuilt athlete_queue in {db_path} with ready_at and sent_at.")
        return 0
    print(f"{db_path} already has athlete_queue.ready_at. Nothing to do.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
