#!/usr/bin/env python3
"""One-off migration and backfill: the macrocycle summaries written before schema 23.

`plan generate` writes a `summary` of the strategy beside it, which `plan show` prints in
place of the strategy unless `-v` is given (DESIGN_output_verbosity.md §5.1). A plan
written before the column existed has none. This adds `macrocycles.summary` when it is
missing, then asks the router model for the summary of every macrocycle without one,
active or superseded, from its strategy, one call each.

It opens the file with plain `sqlite3` to add the column: opening it through `Database`
would stamp version 23 first and leave the column missing. It only fills what is empty, so
a second run picks up what a failed one left.

It operates on the instance named by `STAMIND_CONFIG`. Run it once per athlete, from the
repository root, before the bots restart on the new code; `--dry-run` adds the column but
prints the answers and writes nothing else:

    venv/bin/python scripts/backfill_plan_summaries.py --dry-run
    STAMIND_CONFIG=piupiu/config_piupiu.yaml venv/bin/python scripts/backfill_plan_summaries.py
"""
import argparse
import os
import sqlite3
import sys

# Run as `venv/bin/python scripts/<this>` from the repo root: sys.path[0] is scripts/,
# so the package root has to be put on the path explicitly.
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from stamind import runtime  # noqa: E402
from stamind.cli.bot.route import use_router_model  # noqa: E402
from stamind.config import CONFIG_PATH, config  # noqa: E402
from stamind.openrouter import openrouter_client  # noqa: E402

SUMMARY_PROMPT = """You explain a training plan to the athlete who follows it.

## TASK
Write the plan's strategy in at most two plain sentences of at most 200 characters in all,
for the athlete (e.g., Build the aerobic base through the winter, then turn it into
threshold power for the spring climb, with a two-week taper.)

## RESPONSE FORMAT
A JSON object: {"summary": "..."}"""


def add_column(db_path: str) -> None:
    conn = sqlite3.connect(db_path)
    try:
        columns = [row[1] for row in conn.execute("PRAGMA table_info(macrocycles)")]
        if "summary" in columns:
            return
        conn.execute("ALTER TABLE macrocycles ADD COLUMN summary TEXT")
        conn.commit()
        print(f"Added macrocycles.summary to {db_path}.")
    finally:
        conn.close()


def summary(strategy: str) -> str:
    answer = openrouter_client.complete(
        SUMMARY_PROMPT, f"## STRATEGY\n\n{strategy}",
        label="backfill_plan_summary", wait_notice=None,
    )
    text = answer.get("summary")
    if not isinstance(text, str):
        return ""
    return text.strip()


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--dry-run", action="store_true", help="print, write nothing")
    args = parser.parse_args()
    print(f"Instance: {CONFIG_PATH}")
    if not os.path.exists(config.db_path):
        print(f"No database at {config.db_path}. Nothing to backfill.")
        return 0
    add_column(config.db_path)
    use_router_model(argparse.Namespace())
    print(f"Model: {openrouter_client.model}")
    with runtime.db.transaction() as conn:
        rows = conn.execute(
            "SELECT id, status, created_at, strategy FROM macrocycles"
            " WHERE summary IS NULL ORDER BY id"
        ).fetchall()
    print(f"{len(rows)} macrocycles without a summary.")
    for row in rows:
        text = summary(row["strategy"])
        print(f"  [{row['id']}] {row['status']}, {row['created_at'][:10]}\n"
              f"      {text or '(none)'}")
        if args.dry_run or not text:
            continue
        with runtime.db.transaction() as conn:
            conn.execute("UPDATE macrocycles SET summary = ? WHERE id = ?", (text, row["id"]))
    return 0


if __name__ == "__main__":
    sys.exit(main())
