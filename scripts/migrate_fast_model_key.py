#!/usr/bin/env python3
"""One-off migration: the stored fast-model choice moves to the row key `fast_llm_model`.

`settings set fast-model` keeps the athlete's choice in the `settings` table. The row was
keyed `router_llm_model` while the setting was called `router-model`. The code now reads
`fast_llm_model`, so a choice left under the old key is not read: until this script has
run, `fast-model` falls back to `llm.fast_model` in config.yaml, or to the thinking model
when that is unset.

It renames the row and keeps its value and its date. It does nothing when no row holds the
old key. A choice already stored under the new key is the newer one: it is kept, and the
old row stays where nothing reads it.

The config key was renamed with the setting: a config.yaml that sets `router_model:` under
`llm:` must say `fast_model:` instead. This script does not edit that file.

It operates on the instance named by `STAMIND_CONFIG`, or on the default config when that
variable is unset (ARCHITECTURE.md §9). Run it once per athlete, from the repository root,
before the bots restart on the new code:

    venv/bin/python scripts/migrate_fast_model_key.py
    STAMIND_CONFIG=piupiu/config_piupiu.yaml venv/bin/python scripts/migrate_fast_model_key.py
"""
import os
import sqlite3
import sys

# Run as `venv/bin/python scripts/<this>` from the repo root: sys.path[0] is scripts/,
# so the package root has to be put on the path explicitly.
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from stamind import settings  # noqa: E402
from stamind.config import CONFIG_PATH, config  # noqa: E402

OLD_KEY = "router_llm_model"
NEW_KEY = settings.get(settings.FAST_MODEL).key


def rename_key(db_path: str) -> bool:
    """Moves the row keyed `OLD_KEY` to `NEW_KEY`. Returns whether it moved one."""
    conn = sqlite3.connect(db_path)
    try:
        # OR IGNORE leaves both rows alone when the new key already holds a choice.
        moved = conn.execute(
            "UPDATE OR IGNORE settings SET key = ? WHERE key = ?", (NEW_KEY, OLD_KEY)
        ).rowcount
        conn.commit()
        return bool(moved)
    finally:
        conn.close()


def main() -> int:
    print(f"Instance: {CONFIG_PATH}")
    db_path = config.db_path
    if not os.path.exists(db_path):
        print(f"No database at {db_path}. Nothing to migrate.")
        return 0
    if rename_key(db_path):
        print(f"Renamed the `{OLD_KEY}` row to `{NEW_KEY}` in {db_path}.")
        return 0
    print(f"{db_path} has no `{OLD_KEY}` row to rename. Nothing to do.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
