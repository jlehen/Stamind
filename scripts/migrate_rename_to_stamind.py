#!/usr/bin/env python3
r"""One-off migration: move one athlete's stored identifiers onto the Stamind names.

Two things carry the old name outside the repository, so no substitution inside it can
reach them (RENAME_to_stamind.md §2.3):

  - The SQLite file. It is called `trainmate.db` on disk, and `config.db_path` now says
    `stamind.db`.
  - The `source` tag on every Google Calendar event the app has written. Workout events
    carry `source=TrainMate`, signal events carry `source=trainmate-context`. The new
    code asks Google for `source=stamind` and `source=stamind-context`, so until the
    events are re-tagged `workout prune-calendar` cannot find its own leftovers and
    the signal ingest cannot find the signals.

This is the only file in the repository allowed to name the old strings.

It operates on the instance named by `STAMIND_CONFIG`, or on the default config when
that variable is unset — the rule every other entry point follows (ARCHITECTURE.md §9).
Run it once per athlete, from the repository root:

    venv/bin/python scripts/migrate_rename_to_stamind.py --dry-run
    venv/bin/python scripts/migrate_rename_to_stamind.py

    STAMIND_CONFIG=piupiu/config_piupiu.yaml \
        venv/bin/python scripts/migrate_rename_to_stamind.py --dry-run

Safe to run twice, and safe to re-run after a run that died part way: the calendar query
asks Google for the *old* tags, so an event already patched is not returned again, and
the database step is a no-op once the file sits under the new name.
"""
import argparse
import os
import sys
from typing import List, Optional, Tuple

# Run as `venv/bin/python scripts/<this>` from the repo root: sys.path[0] is scripts/,
# so the package root has to be put on the path explicitly.
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from stamind import runtime
from stamind.config import CONFIG_PATH, config
from stamind.gcal.event import WORKOUT_EVENT_TAG
from stamind.output import Progress, warn

# What the database file was called before the rename, beside whatever `config.db_path`
# names now.
OLD_DB_NAME = "trainmate.db"

# The `source` values the app wrote before the rename.
OLD_WORKOUT_TAG = "TrainMate"
OLD_SIGNAL_TAG = "trainmate-context"

# What `rename_database` reports, and the line printed for each outcome.
DB_MESSAGES = {
    "renamed": "Database: renamed {old} to {new}.",
    "pending": "Database: would rename {old} to {new}.",
    "done": "Database: already named {new}. Nothing to rename.",
    "missing": "Database: no file at {old} or {new}. Nothing to rename.",
    "open": "Database: REFUSED. A -wal or -shm file sits beside {old}, so a process "
            "still has it open. Stop the bots and any running command, then re-run.",
    "both": "Database: REFUSED. Both {old} and {new} exist, and renaming would "
            "overwrite {new}. A command run after the rename landed created the new "
            "file. Move it aside, then re-run.",
}

# The two outcomes that stop the script rather than let it carry on.
DB_REFUSALS = ("open", "both")


def tag_renames() -> List[Tuple[str, str]]:
    """The `source` values to rewrite, as (old, new) pairs.

    The new values are read off the code and the config rather than spelled out again,
    so this script cannot come to disagree with what the app looks for.
    """
    return [
        (OLD_WORKOUT_TAG, WORKOUT_EVENT_TAG),
        (OLD_SIGNAL_TAG, config.calendar_signal_tag),
    ]


def db_paths() -> Tuple[str, str]:
    """This instance's database file under its old name and its new one, in that order.

    The new path is `config.db_path`, so the file lands exactly where the app will look
    for it; the old one is the pre-rename name in the same directory.
    """
    new_path = config.db_path
    return os.path.join(os.path.dirname(new_path), OLD_DB_NAME), new_path


def open_database_sidecars(db_path: str) -> List[str]:
    """Whichever of the `-wal` and `-shm` files SQLite keeps beside an open database
    exist right now. An empty list means no process holds the file open.

    Matched by exact name and never by glob. A hand-made snapshot such as
    `trainmate.db.pre-match-fix-20260909T203718Z` has sidecars of its own sitting in the
    same directory, and a glob for `trainmate.db*-wal` would find those and refuse the
    rename over a file that has nothing to do with the live database.
    """
    return [p for p in (db_path + "-wal", db_path + "-shm") if os.path.exists(p)]


def rename_database(old_path: str, new_path: str, dry_run: bool) -> str:
    """Moves the database from its old name to its new one. Returns one word:

    "renamed"  the file moved.
    "pending"  a dry run: the file would have moved.
    "done"     the file is already under the new name, so there was nothing to move.
    "missing"  neither name exists, so this instance has no database file yet.
    "open"     a sidecar says a process still has the old file open; nothing was moved.
    "both"     both names exist, so moving would overwrite the new file; nothing moved.
    """
    if not os.path.exists(old_path):
        return "done" if os.path.exists(new_path) else "missing"
    if open_database_sidecars(old_path):
        return "open"
    if os.path.exists(new_path):
        return "both"
    if dry_run:
        return "pending"
    os.rename(old_path, new_path)
    return "renamed"


def retag_one(syncer, event: dict, new_tag: str) -> Optional[str]:
    """Rewrites one event's `source` property. Returns None on success, or the line to
    warn about on failure.

    The whole `private` map is sent back, not just the one key, so the `metric` and
    `value` a signal event carries survive whatever merge rule the API applies to a
    patch. An API error is reported rather than raised: an event deleted between the
    listing and the patch must not stop the several thousand behind it.
    """
    event_id = event.get('id')
    if not event_id:
        return "an event came back without an id and was left alone"
    private = dict((event.get('extendedProperties') or {}).get('private') or {})
    private['source'] = new_tag
    try:
        syncer.service.events().patch(
            calendarId=syncer.calendar_id,
            eventId=event_id,
            body={'extendedProperties': {'private': private}},
        ).execute()
        return None
    except Exception as e:
        return f"could not re-tag event {event_id}: {e}"


def retag_events(syncer, old_tag: str, new_tag: str, dry_run: bool) -> Tuple[int, int]:
    """Rewrites `source=<old_tag>` to `source=<new_tag>` on every event still carrying
    the old value, whole calendar, past and future. Returns (patched, failed).

    The listing asks Google for the old tag, which is what makes a second run find
    nothing and a half-finished run pick up exactly the events it never reached.
    """
    events = syncer.list_events_by_tag(old_tag)
    if not events:
        print(f"source={old_tag}: no events left to re-tag.")
        return 0, 0
    if dry_run:
        print(f"source={old_tag}: {len(events)} event(s) would become source={new_tag}.")
        return 0, 0

    print(f"source={old_tag}: re-tagging {len(events)} event(s) as source={new_tag}...")
    patched, failures = 0, []
    with Progress(len(events)) as bar:
        for event in events:
            failure = retag_one(syncer, event, new_tag)
            if failure:
                failures.append(failure)
            else:
                patched += 1
            bar.step()
    # After the bar, never inside it: the bar erases its own line on every step, so a
    # warning printed mid-loop is wiped by the next one.
    for failure in failures:
        warn(failure)
    print(f"source={old_tag}: {patched} event(s) re-tagged, {len(failures)} failed.")
    return patched, len(failures)


def main() -> int:
    parser = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    parser.add_argument(
        "-n", "--dry-run", action="store_true",
        help="Count what would change, write nothing, and touch no file."
    )
    args = parser.parse_args()

    print(f"Instance: {CONFIG_PATH}")
    if args.dry_run:
        print("Dry run: nothing is renamed and no event is patched.")

    old_path, new_path = db_paths()
    status = rename_database(old_path, new_path, args.dry_run)
    print(DB_MESSAGES[status].format(old=old_path, new=new_path))
    # A refused rename stops a real run before anything is written. A dry run prints the
    # refusal and carries on, so one preview still shows both halves of the job.
    if status in DB_REFUSALS and not args.dry_run:
        return 1

    if not config.google_calendar_id:
        print("Calendar: none configured for this instance. No events to re-tag.")
        return 0

    syncer = runtime.calendar_syncer
    total_patched = total_failed = 0
    for old_tag, new_tag in tag_renames():
        patched, failed = retag_events(syncer, old_tag, new_tag, args.dry_run)
        total_patched += patched
        total_failed += failed

    if args.dry_run:
        if status in DB_REFUSALS:
            print("Dry run complete. Nothing was changed, and the database rename would "
                  "be refused — see the Database line above.")
            return 0
        print("Dry run complete. Nothing was changed.")
        return 0
    print(f"Done. {total_patched} event(s) re-tagged, {total_failed} failed.")
    if total_failed:
        print("Re-run the script to retry the failures.")
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
