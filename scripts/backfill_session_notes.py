#!/usr/bin/env python3
"""One-off backfill: the notes the athlete sent before `session_notes` existed.

From schema 24 on, `workout adapt -m` keeps its note with the day's session
(DESIGN_session_notes.md). The messages sent before that are still in the router's logs,
`logs/llm_exchanges/*_bot_route.md`. This keeps the ones the router sent to the coach
(`coach_message`) and that are still inside the look back (`metrics_lookback_days`), by the
same date rule: the day's only session gets the note. A day with no session, or with several,
is printed and skipped, since nobody is there to ask. A note already kept is not kept twice,
so a second run changes nothing.

It operates on the instance named by `STAMIND_CONFIG`. Run it once per athlete, from the
repository root; `--dry-run` prints what it would keep and writes nothing:

    venv/bin/python scripts/backfill_session_notes.py --dry-run
    STAMIND_CONFIG=piupiu/config_piupiu.yaml venv/bin/python scripts/backfill_session_notes.py
"""
import argparse
import glob
import json
import os
import re
import sys
from datetime import datetime, timezone

# Run as `venv/bin/python scripts/<this>` from the repo root: sys.path[0] is scripts/,
# so the package root has to be put on the path explicitly.
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from stamind import clock, runtime  # noqa: E402
from stamind.config import config  # noqa: E402
from stamind.sports import canonical_sport  # noqa: E402

MESSAGE = re.compile(r"## MESSAGE\n\n(.*?)\n```\n\n## Raw Response", re.S)
ANSWER = re.compile(r"## Raw Response \(JSON\)\n```json\n(.*?)\n```", re.S)


def routed_messages(logs_dir: str):
    """(sent, text) for every message the router sent to the coach, oldest first. The file
    name starts with the machine's local time (`openrouter.py`)."""
    for path in sorted(glob.glob(os.path.join(logs_dir, "*_bot_route.md"))):
        with open(path, encoding="utf-8") as handle:
            body = handle.read()
        message, answer = MESSAGE.search(body), ANSWER.search(body)
        if not message or not answer:
            continue
        try:
            intent = json.loads(answer.group(1)).get("intent")
        except ValueError:
            continue
        if intent != "coach_message":
            continue
        sent = datetime.strptime(os.path.basename(path)[:22], "%Y%m%d_%H%M%S_%f")
        yield sent.astimezone(), message.group(1).strip()


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--dry-run", action="store_true", help="Print, write nothing")
    args = parser.parse_args()

    db = runtime.db
    since = clock.shift(clock.today_str(), -(config.metrics_lookback_days - 1))
    for sent, text in routed_messages(config.llm_logs_dir):
        day = clock.day_str(clock.to_local(sent).date())
        if day < since:
            continue
        sessions = [
            w for w in db.get_workouts(start_date=day, end_date=day)
            if canonical_sport(w['sport_type']) != canonical_sport('rest')
        ]
        shown = " ".join(text.split())[:70]
        if len(sessions) != 1:
            print(f"{day}  skipped, {len(sessions)} sessions: {shown}")
            continue
        session = sessions[0]
        if any(note['text'] == text for note in session['athlete_notes']):
            print(f"{day}  already kept: {shown}")
            continue
        print(f"{day}  “{session['title']}” ← {shown}")
        if args.dry_run:
            continue
        with db._get_connection() as conn:
            conn.execute(
                "INSERT INTO session_notes (lineage_id, sent_at, text) VALUES (?, ?, ?)",
                (session['id'], sent.astimezone(timezone.utc).isoformat(), text),
            )
            conn.commit()


if __name__ == "__main__":
    main()
