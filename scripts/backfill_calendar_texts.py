#!/usr/bin/env python3
"""One-off backfill: the short names and the mesocycle summaries written before schema 22.

`workout generate` and `workout adapt` write a session's short name, and `plan generate` a
mesocycle's summary (DESIGN_calendar_miniapp.md §3.6, §3.7). A session or a plan written
before those columns existed has none. This asks the fast model for them, once:

- every live session without a short name, rest days and cancelled sessions left out,
  from its title and the start of its description, 40 to a call;
- every mesocycle of an active plan without a summary, from its focus, one call each.

It only fills what is empty, so a second run picks up what a failed one left. A short name
is not a change to the session, so it is written onto the live revision in place, with the
append-only triggers dropped and put back as `wipe_workouts` does.

It adds the two columns first when they are missing (`migrate_calendar_columns.py`). It
operates on the instance named by `STAMIND_CONFIG`. Run it once per athlete, from the
repository root; `--dry-run` prints the answers and writes nothing:

    venv/bin/python scripts/backfill_calendar_texts.py --dry-run
    STAMIND_CONFIG=piupiu/config_piupiu.yaml venv/bin/python scripts/backfill_calendar_texts.py
"""
import argparse
import json
import os
import sys
from typing import Any, Dict, List

# Run as `venv/bin/python scripts/<this>` from the repo root: sys.path[0] is scripts/,
# so the package root has to be put on the path explicitly.
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from migrate_calendar_columns import add_columns  # noqa: E402

from stamind import runtime  # noqa: E402
from stamind.cli.bot.route import use_fast_model  # noqa: E402
from stamind.config import CONFIG_PATH, config  # noqa: E402
from stamind.db.schema import WORKOUTS_APPEND_ONLY_TRIGGERS  # noqa: E402
from stamind.openrouter import openrouter_client  # noqa: E402

BATCH = 40
DESCRIPTION_CHARS = 300

SHORT_NAME_PROMPT = """You label training sessions in a calendar whose cells are narrow.

## TASK
For each session, write its short name: at most 5 characters naming the kind of session,
e.g. "Easy", "Long", "Hills", "Tempo", "Z2", "VO2", "Gym". Base it on the title and the
description.

## RESPONSE FORMAT
A JSON object: {"names": [{"id": 12, "short_name": "Hills"}]}, one entry per session."""

SUMMARY_PROMPT = """You explain a training plan to the athlete who follows it.

## TASK
Write what this mesocycle is for, in one plain sentence of at most 90 characters, for the
athlete (e.g., Rebuild the aerobic base and start sprint intervals, ending with an FTP
test.)

## RESPONSE FORMAT
A JSON object: {"summary": "..."}"""


def unnamed_sessions() -> List[Dict[str, Any]]:
    with runtime.db.transaction() as conn:
        rows = conn.execute(
            "SELECT id, date, sport_type, title, description FROM live_workouts"
            " WHERE void = 0 AND short_name IS NULL AND sport_canonical <> 'rest'"
            " ORDER BY date"
        ).fetchall()
    return [dict(row) for row in rows]


def unsummarized_mesocycles() -> List[Dict[str, Any]]:
    # Only an active plan's mesocycles reach the "Goals & plan" page (§3.7).
    with runtime.db.transaction() as conn:
        rows = conn.execute(
            "SELECT m.id, m.name, m.start_date, m.end_date, m.focus FROM mesocycles m"
            " JOIN macrocycles mac ON mac.id = m.macrocycle_id"
            " WHERE COALESCE(mac.status, 'active') = 'active' AND m.summary IS NULL"
            " ORDER BY m.start_date"
        ).fetchall()
    return [dict(row) for row in rows]


def short_names(batch: List[Dict[str, Any]]) -> Dict[int, str]:
    sessions = [
        {"id": s["id"], "sport": s["sport_type"], "title": s["title"],
         "description": (s["description"] or "")[:DESCRIPTION_CHARS]}
        for s in batch
    ]
    answer = openrouter_client.complete(
        SHORT_NAME_PROMPT, "## SESSIONS\n\n" + json.dumps(sessions, ensure_ascii=False),
        label="backfill_short_names", wait_notice=None,
    )
    wanted = {s["id"] for s in batch}
    names = {}
    for entry in answer.get("names") or []:
        name = entry.get("short_name")
        if entry.get("id") not in wanted or not isinstance(name, str) or not name.strip():
            continue
        names[entry["id"]] = name.strip()
    return names


def summary(meso: Dict[str, Any]) -> str:
    answer = openrouter_client.complete(
        SUMMARY_PROMPT,
        f"## MESOCYCLE\n\n{meso['name']}, {meso['start_date']} to {meso['end_date']}\n\n"
        f"{meso['focus']}",
        label="backfill_summary", wait_notice=None,
    )
    text = answer.get("summary")
    if not isinstance(text, str):
        return ""
    return text.strip()


def write_short_names(names: Dict[int, str]) -> None:
    # The live revision is written in place: a short name alone is not a change (§3.6).
    with runtime.db.transaction() as conn:
        conn.execute("DROP TRIGGER IF EXISTS workouts_no_update")
        for workout_id, name in names.items():
            conn.execute("UPDATE workouts SET short_name = ? WHERE id = ?", (name, workout_id))
        for statement in WORKOUTS_APPEND_ONLY_TRIGGERS:
            conn.execute(statement)


def backfill_sessions(dry_run: bool) -> None:
    sessions = unnamed_sessions()
    print(f"{len(sessions)} sessions without a short name.")
    for at in range(0, len(sessions), BATCH):
        batch = sessions[at:at + BATCH]
        names = short_names(batch)
        for s in batch:
            print(f"  {s['date']}  {names.get(s['id'], '(none)'):6}  {s['title']}")
        if not dry_run:
            write_short_names(names)


def backfill_summaries(dry_run: bool) -> None:
    mesos = unsummarized_mesocycles()
    print(f"{len(mesos)} mesocycles of active plans without a summary.")
    for meso in mesos:
        text = summary(meso)
        print(f"  {meso['start_date']}  {meso['name']}\n      {text or '(none)'}")
        if dry_run or not text:
            continue
        with runtime.db.transaction() as conn:
            conn.execute("UPDATE mesocycles SET summary = ? WHERE id = ?", (text, meso["id"]))


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--dry-run", action="store_true", help="print, write nothing")
    args = parser.parse_args()
    print(f"Instance: {CONFIG_PATH}")
    if not os.path.exists(config.db_path):
        print(f"No database at {config.db_path}. Nothing to backfill.")
        return 0
    # Before anything opens the database through `Database`, which would stamp version 22
    # over missing columns (migrate_calendar_columns.py).
    add_columns(config.db_path)
    use_fast_model(argparse.Namespace())
    print(f"Model: {openrouter_client.model}")
    backfill_sessions(args.dry_run)
    backfill_summaries(args.dry_run)
    return 0


if __name__ == "__main__":
    sys.exit(main())
