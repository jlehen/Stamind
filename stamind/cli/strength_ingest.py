"""`strength ingest`: the gym log the Mini App sent, stored as an activity's sets
(DESIGN_gym_logger.md §5).

The rows land exactly where Garmin's own would, every set named by the athlete, so the
strength history, the strength planner's habit count and `workout compare` read them
unchanged. The morning pull then hands them to Garmin's activity for that day (§5).
"""
import argparse
from datetime import datetime, timedelta
from typing import Any, Dict, List, Optional

from stamind import clock, runtime
from stamind.clock import fmt_date
from stamind.db.strength import ACTIVE, ATHLETE, REST
from stamind.output import fail, notice
from stamind.strength import logger, prescription, sets
from stamind.text import capitalized, wrap_text
from stamind.types import Workout


def _duration_sec(log: logger.Log) -> float:
    """How long the session ran, from the two clock times the page sent (§4). A session
    that ended before it started ran over midnight."""
    start = datetime.strptime(f"{log.date} {log.start}", "%Y-%m-%d %H:%M")
    end = datetime.strptime(f"{log.date} {log.end}", "%Y-%m-%d %H:%M")
    if end < start:
        end += timedelta(days=1)
    return (end - start).total_seconds()


def _set_rows(log: logger.Log) -> List[Dict[str, Any]]:
    """The log as `exercise_sets` rows (§5): one active row per logged set, named by the
    athlete, and a rest row between two consecutive sets whose seconds are both known."""
    rows: List[Dict[str, Any]] = []
    previous: Optional[float] = None
    for entry in log.exercises:
        for done in entry.sets:
            if previous is not None and done.seconds is not None and done.seconds > previous:
                rows.append({
                    "seq": len(rows) + 1, "set_type": REST, "exercise": None,
                    "garmin_name": None, "reps": None, "load_kg": None,
                    "duration_sec": done.seconds - previous, "named_by": None,
                })
            rows.append({
                "seq": len(rows) + 1, "set_type": ACTIVE, "exercise": entry.name,
                "garmin_name": None, "reps": done.reps, "load_kg": done.load_kg,
                "duration_sec": None, "named_by": ATHLETE,
            })
            previous = done.seconds
    return rows


def _revision(revision_id: Optional[int]) -> Optional[Workout]:
    """The session the page was given, or None when the log carries no revision or that
    revision is gone (§5)."""
    if revision_id is None:
        return None
    found = runtime.db.hydrate_revisions([revision_id])
    return found[0] if found else None


def _done(entry: logger.Entry) -> str:
    """'5 @ 120, 6 @ 140, 5 @ 140': one exercise's sets as they were done. A set with no
    weight is its reps alone."""
    parts = []
    for done in entry.sets:
        if done.load_kg is None:
            parts.append(str(done.reps))
            continue
        parts.append(f"{done.reps} @ {sets.fmt_kg(done.load_kg)}")
    return ", ".join(parts)


def _written(entry: logger.Entry, prescribed: Dict[int, Dict[str, Any]]) -> str:
    """What the session asked for at this exercise's position, in a parenthesis: nothing
    was written there, or it was written for another exercise the athlete swapped (§5)."""
    row = prescribed.get(entry.position) if entry.position is not None else None
    if row is None:
        return " (not written)"
    spec = prescription.spec([row])
    if row["exercise"] == entry.name:
        return f" (written {spec})"
    return f" (instead of {row['exercise']}, written {spec})"


def _not_done(log: logger.Log, prescribed: Dict[int, Dict[str, Any]]) -> List[str]:
    """The prescribed rows no entry of the log stands for, in position order, each with its
    spec: an exercise written as a warm-up row and a working row can have one done and the
    other not, and the name alone would read as a contradiction (§5)."""
    stood_for = {entry.position for entry in log.exercises}
    missing: List[str] = []
    for position in sorted(prescribed):
        if position in stood_for:
            continue
        row = prescribed[position]
        missing.append(f"{row['exercise']} {prescription.spec([row])}")
    return missing


def _summary(log: logger.Log, workout: Optional[Workout], replaced: bool) -> None:
    """What was done, and where it departed from what was written (§5). Without the
    revision there is nothing to compare against, so the lines say only what was done. A
    log sent again for a day says so, since the athlete otherwise reads two logs."""
    prescribed = {row["position"]: row
                  for row in (workout or {}).get("prescribed_sets") or []}
    count = sum(len(entry.sets) for entry in log.exercises)
    head = "Updated the log of" if replaced else "Logged"
    lines = [
        f"{head} {fmt_date(log.date)}, {log.start}–{log.end}: "
        f"{len(log.exercises)} exercise{'' if len(log.exercises) == 1 else 's'}, "
        f"{count} set{'' if count == 1 else 's'}."
    ]
    for entry in log.exercises:
        written = _written(entry, prescribed) if workout else ""
        lines.append(f"{capitalized(entry.name)} {_done(entry)}{written}")
    missing = _not_done(log, prescribed)
    if missing:
        lines.append("Not done: " + ", ".join(missing) + ".")
    print(wrap_text("\n".join(lines)))


def run_strength_ingest(args: argparse.Namespace) -> None:
    """Stores a gym log as the day's sets and says what was done (§5)."""
    try:
        with open(args.file, encoding="utf-8") as handle:
            text = handle.read()
    except OSError as unreadable:
        fail(f"Could not read {args.file}: {unreadable}")
        return
    try:
        log = logger.parse_log(text)
    except logger.LogError as broken:
        fail(str(broken))
        return
    workout = _revision(log.revision_id)
    replaced = runtime.db.gym_log_for_day(log.date) is not None
    activity_id = runtime.db.upsert_logged_activity(
        log.date, f"{log.date} {log.start}:00", _duration_sec(log)
    )
    now = clock.now()
    runtime.db.store_exercise_sets(activity_id, _set_rows(log), now, now)
    runtime.db.save_gym_log(activity_id, log.revision_id, text)
    if log.revision_id is not None and workout is None:
        notice("The session this log was written against is gone, so the summary cannot "
               "say what it departed from.")
    _summary(log, workout, replaced)


def add_ingest_parser(strength_subparsers) -> None:
    """Wires `strength ingest` under the strength command (§5)."""
    s_ingest = strength_subparsers.add_parser(
        "ingest",
        help="Store a gym log from the logger page as that day's sets",
        description=(
            "Read the JSON the gym logger page sent, store it as the day's sets with every "
            "set named, and say what was done and where it departed from what was written. "
            "Ingesting the same day twice replaces the earlier log. The next morning's "
            "pull hands the sets to Garmin's own activity for that day."
        ),
    )
    s_ingest.add_argument("file", metavar="FILE", help="The log the page sent, as JSON")
    s_ingest.set_defaults(func=run_strength_ingest)
