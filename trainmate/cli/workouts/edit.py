"""Workout CLI: push / wipe / prune-calendar (the Calendar and the database, no session
edits)."""
import argparse
import sys
from typing import Optional
from trainmate import runtime
from trainmate.calendar_state import calendar_status
from trainmate.util import (
    step, dim, green, red, cyan, cmd, fmt_date, fmt_span, today_str as _today_str, notice,
)
from trainmate.cli.selectors import resolve_window

from trainmate.cli.workouts._helpers import warn_stale_before


def run_workout_push(args: argparse.Namespace) -> None:
    """Synchronizes planned workouts with Google Calendar."""
    today_str = _today_str()
    force = getattr(args, 'force', False)

    start_date, end_date = resolve_window(args)

    all_workouts = runtime.db.get_workouts(
        start_date=start_date,
        end_date=end_date,
        sport_type=getattr(args, 'sport_type', None),
        include_removed=True,
    )

    to_push = []
    for w in all_workouts:
        is_fresh = calendar_status(w) == 'synced'
        if not w.get('removed'):
            if force or not is_fresh:
                to_push.append(w)
        else:
            # A removed workout only needs pushing if it has an event to update.
            if w.get('google_event_id') and (force or not is_fresh):
                to_push.append(w)

    if not to_push:
        if force:
            print("No workouts found in the specified range.")
        else:
            print(green(
                "No new or modified workouts to sync. "
                f"Run {cmd('workout generate')} to generate a schedule, "
                "or use -f to re-push already-synced workouts."
            ))
        warn_stale_before(start_date)
        return

    step(f"Syncing {len(to_push)} workouts to Google Calendar...")
    try:
        runtime.calendar_syncer.sync_multiple(to_push)
        print(green("Google Calendar synchronization completed."))
    except Exception as e:
        notice(f"Error syncing to Google Calendar: {e}", red)
    warn_stale_before(start_date)


def run_workout_wipe(args: argparse.Namespace) -> None:
    """Wipes all workouts from the database and Google Calendar after confirmation."""
    if not args.yes:
        if not runtime.prompt.confirm(
            "Are you sure you want to wipe all workouts "
            "(including Google Calendar events)?", danger=True
        ):
            print("Wipe cancelled.")
            return

    workouts = runtime.db.get_workouts(include_removed=True)
    synced_workouts = [w for w in workouts if w.get('google_event_id')]
    if synced_workouts:
        step(f"Deleting {len(synced_workouts)} events from Google Calendar...")
        for w in synced_workouts:
            ge_id = w['google_event_id']
            if ge_id:
                runtime.calendar_syncer.delete_workout_event(ge_id)

    runtime.db.wipe_workouts()
    print(green("All workouts wiped successfully."))


def _event_day(event: dict) -> Optional[str]:
    """The day an event sits on. Workout events are all-day (`start.date`); a timed
    start is tolerated in case one was hand-edited in Google Calendar."""
    start = event.get('start') or {}
    return start.get('date') or (start.get('dateTime') or "")[:10] or None


def run_workout_prune_calendar(args: argparse.Namespace) -> None:
    """Deletes workout events on the calendar that no local workout row references.

    Ownership is read from the calendar side (the `source=TrainMate` tag), because the
    orphans this cleans up are exactly the ones the database can no longer name — a
    fresh DB, a restored backup, or a wipe that never reached Calendar.
    """
    start_date, end_date = resolve_window(args)

    try:
        events = runtime.calendar_syncer.list_workout_events()
    except Exception as e:
        notice(f"Error reading Google Calendar: {e}", red)
        sys.exit(1)

    # Every id a lineage still claims — the ownership record, so a removal that keeps
    # its event on purpose ("[Deleted]", "[Cancelled]") is never read as an orphan, even
    # when another session has since taken its slot. Read *after* the calendar, so a
    # workout pushed mid-command lands in `known` rather than in a stale event list —
    # the race then errs towards keeping.
    known = runtime.db.claimed_calendar_event_ids()

    orphans = []
    for event in events:
        if event.get('id') in known:
            continue
        day = _event_day(event)
        if start_date and (day is None or day < start_date):
            continue
        if end_date and (day is None or day > end_date):
            continue
        orphans.append((day or "?", event))
    orphans.sort(key=lambda pair: pair[0])

    if start_date and end_date:
        window = f" dated {fmt_span(start_date, end_date)}"
    elif start_date:
        window = f" dated {fmt_date(start_date)} onward"
    elif end_date:
        window = f" dated up to {fmt_date(end_date)}"
    else:
        window = ""

    if not orphans:
        print(green(
            f"No orphaned Calendar events{window}. "
            f"{len(events)} workout event(s) all match a local workout."
        ))
        return

    for day, event in orphans:
        print(f"{cyan(fmt_date(day))}  {event.get('summary') or dim('(no title)')}")
    print(dim(
        f"{len(orphans)} of {len(events)} workout event(s) on the calendar "
        f"match no local workout{window}."
    ))

    if getattr(args, 'dry_run', False):
        notice(f"Dry run: nothing deleted. Re-run without --dry-run to prune.")
        return

    if not args.yes:
        if not runtime.prompt.confirm(
            f"Delete these {len(orphans)} Google Calendar event(s)?", danger=True
        ):
            print("Prune cancelled.")
            return

    deleted = sum(
        1 for _, event in orphans if runtime.calendar_syncer.delete_event(event['id'])
    )
    print(green(f"Pruned {deleted} orphaned Calendar event{'s' if deleted != 1 else ''}."))
    if deleted != len(orphans):
        notice(f"{len(orphans) - deleted} event(s) could not be deleted (see above).")
