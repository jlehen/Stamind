#!/usr/bin/env python3
"""One-off backfill: a short line for the coming sessions written before short messages.

The chat shows a session's short line, and its whole description when it has none
(DESIGN_short_messages.md §4). A schedule written before the short lines landed therefore
stays long until a planner next writes each session. This asks the fast model for the short
line of every coming session without one, rest days aside, one call each, then writes them all
in one transaction, with the append-only triggers dropped and put back. It only fills what is
empty, so a second run picks up what a failed one left. The calendar event does not render the
short line, so nothing is pushed again.

It operates on the instance named by `STAMIND_CONFIG`. Run it from the repository root;
`--dry-run` prints the answers and writes nothing:

    venv/bin/python scripts/backfill_session_short_lines.py --dry-run
    STAMIND_CONFIG=piupiu/config_piupiu.yaml venv/bin/python scripts/backfill_session_short_lines.py
"""
import argparse
import os
import sys
from typing import Dict

# Run as `venv/bin/python scripts/<this>` from the repo root: sys.path[0] is scripts/,
# so the package root has to be put on the path explicitly.
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from stamind import clock, runtime  # noqa: E402
from stamind.cli.bot.route import use_fast_model  # noqa: E402
from stamind.config import CONFIG_PATH  # noqa: E402
from stamind.db.schema import WORKOUTS_APPEND_ONLY_TRIGGERS  # noqa: E402
from stamind.openrouter import openrouter_client  # noqa: E402
from stamind.sports import canonical_sport  # noqa: E402

SHORT_LINE_PROMPT = """You write for the athlete who trains from this session.

## TASK
Write the session's short line: at most 2 short sentences, about 20 words, a hard limit. What
to do, and the one or two numbers to hold. Plain words, no name coined in the description.
Say what the session is, never why it moved or what the coach thinks of it.
(e.g., Ride easy at 155-175 W on a flat route. Ease off past 178 W.)
(e.g., Six exercises, heavy, two reps short of failure. Split squats are at 36 kg.)

## RESPONSE FORMAT
A JSON object: {"summary": "..."}"""


def short_line(workout: dict) -> str:
    answer = openrouter_client.complete(
        SHORT_LINE_PROMPT,
        f"## SESSION\n\n{workout['title']}, {workout['duration_minutes']} min\n\n"
        f"{workout['description']}",
        label="backfill_session_short_line", wait_notice=None,
    )
    text = answer.get("summary")
    if not isinstance(text, str):
        return ""
    return text.strip()


def write_short_lines(lines: Dict[int, str]) -> None:
    # The live revision is written in place: a short line alone is not a change, as
    # `backfill_calendar_texts.py` says of a short name.
    with runtime.db.transaction() as conn:
        conn.execute("DROP TRIGGER IF EXISTS workouts_no_update")
        for workout_id, text in lines.items():
            conn.execute("UPDATE workouts SET summary = ? WHERE id = ?", (text, workout_id))
        for statement in WORKOUTS_APPEND_ONLY_TRIGGERS:
            conn.execute(statement)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--dry-run", action="store_true", help="print, write nothing")
    args = parser.parse_args()
    print(f"Instance: {CONFIG_PATH}")
    use_fast_model(argparse.Namespace())
    print(f"Model: {openrouter_client.model}")
    workouts = [
        w for w in runtime.db.get_workouts(start_date=clock.today_str())
        if not w.get("summary") and canonical_sport(w["sport_type"]) != "rest"
    ]
    print(f"{len(workouts)} coming sessions without a short line.")
    lines = {}
    for workout in workouts:
        text = short_line(workout)
        print(f"  [{workout['id']}] {workout['date']} {workout['title']}\n"
              f"      {text or '(none)'}")
        if text:
            lines[workout["id"]] = text
    if not args.dry_run:
        write_short_lines(lines)
    return 0


if __name__ == "__main__":
    sys.exit(main())
