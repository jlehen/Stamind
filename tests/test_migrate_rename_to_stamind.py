"""The one-off migration that moves an instance onto the Stamind identifiers.

It runs once per athlete, by hand, against the only database and the real calendar, so
the parts that cannot be taken back are pinned here: the check that refuses to rename an
open database, and the re-tagging of events that already exist. The script is driven
through fixtures — a temporary directory and an in-memory calendar — and never reaches
Google or the athlete's files.
"""
import copy
import importlib.util
import io
import os
import shutil
import tempfile
import unittest
from contextlib import redirect_stdout

_SCRIPT = os.path.join(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
    "scripts", "migrate_rename_to_stamind.py",
)
_spec = importlib.util.spec_from_file_location("migrate_rename_to_stamind", _SCRIPT)
migrate = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(migrate)

# The pre-rename names, read off the script so the fixtures below cannot drift from what
# it actually looks for. `PreRenameStringsTest` is the one place in this file that spells
# them out, which is what keeps `git grep -i` over the repo down to the script itself.
OLD_DB = migrate.OLD_DB_NAME
OLD_WORKOUT_TAG = migrate.OLD_WORKOUT_TAG
OLD_SIGNAL_TAG = migrate.OLD_SIGNAL_TAG

# A hand-made snapshot of the database, taken long before the rename and still sitting in
# the data directory with `-wal` and `-shm` files of its own.
SNAPSHOT = OLD_DB + ".pre-match-fix-20260909T203718Z"


def _event(event_id: str, source: str, **private) -> dict:
    """A calendar event carrying `source=<source>` plus whatever else the producer put
    in `extendedProperties.private` — `metric` and `value` on a signal event."""
    return {
        "id": event_id,
        "summary": f"event {event_id}",
        "start": {"date": "2026-06-13"},
        "extendedProperties": {"private": dict(private, source=source)},
    }


class _Request:
    """What a Google API call object returns before `.execute()` is called on it."""

    def __init__(self, run):
        self._run = run

    def execute(self):
        return self._run()


class _Events:
    def __init__(self, calendar):
        self._calendar = calendar

    def patch(self, calendarId, eventId, body):
        return _Request(lambda: self._calendar.apply_patch(calendarId, eventId, body))


class _Service:
    def __init__(self, calendar):
        self._calendar = calendar

    def events(self):
        return _Events(self._calendar)


class FakeSyncer:
    """Stands in for `CalendarSyncer` over a dict of events: the tag listing the script
    reads with, and the `service.events().patch` it writes with.

    `apply_patch` *replaces* the whole `private` map rather than merging in the keys it
    is given. That is the pessimistic reading of the API's patch semantics, and the
    script has to survive it: a signal event whose `metric` and `value` were dropped
    would be ingested as a bare `signal` with no number the next time Calendar is pulled.
    """

    calendar_id = "cal-test"

    def __init__(self, events, failing=()):
        self.events = {e["id"]: e for e in events}
        self.failing = set(failing)
        self.patch_calls = []
        self.service = _Service(self)

    def list_events_by_tag(self, tag):
        """Copies, as the API hands back snapshots: a caller cannot write through them."""
        return [
            copy.deepcopy(event) for event in self.events.values()
            if event["extendedProperties"]["private"].get("source") == tag
        ]

    def apply_patch(self, calendar_id, event_id, body):
        self.patch_calls.append(event_id)
        if event_id in self.failing:
            raise RuntimeError("the API said no")
        self.events[event_id]["extendedProperties"]["private"] = dict(
            body["extendedProperties"]["private"]
        )
        return self.events[event_id]

    def source_of(self, event_id):
        return self.events[event_id]["extendedProperties"]["private"].get("source")

    def private_of(self, event_id):
        return self.events[event_id]["extendedProperties"]["private"]


class PreRenameStringsTest(unittest.TestCase):
    """What the migration hunts for, and what it writes in place of it."""

    def test_the_script_looks_for_the_old_names_and_writes_the_new_ones(self):
        """The one place this file spells the pre-rename strings. Without it a typo in
        the script's constants would leave every other test here passing while the
        migration searched for a string no event on the calendar carries."""
        self.assertEqual(migrate.OLD_DB_NAME, "trainmate.db")
        self.assertEqual(
            migrate.tag_renames(),
            [("TrainMate", "stamind"), ("trainmate-context", "stamind-context")],
        )

    def test_the_new_tags_are_read_off_the_app_rather_than_copied(self):
        """So the script cannot drift from what `workout prune-calendar` and the signal
        ingest actually ask Google for."""
        from stamind.config import config
        from stamind.gcal.event import WORKOUT_EVENT_TAG

        self.assertEqual(
            migrate.tag_renames(),
            [(OLD_WORKOUT_TAG, WORKOUT_EVENT_TAG),
             (OLD_SIGNAL_TAG, config.calendar_signal_tag)],
        )

    def test_the_real_syncer_still_has_the_method_the_script_calls(self):
        """`FakeSyncer` below is a hand-written stand-in, so renaming this method on
        `CalendarSyncer` would break the migration while every test here still passed."""
        from stamind.gcal.client import CalendarSyncer

        self.assertTrue(callable(getattr(CalendarSyncer, "list_events_by_tag", None)))


class DatabaseRenameTest(unittest.TestCase):
    """The database file taking its new name, and the four states in which it must not."""

    def setUp(self):
        self.dir = tempfile.mkdtemp(prefix="stamind-migrate-test-")
        self.addCleanup(shutil.rmtree, self.dir, True)
        self.old = os.path.join(self.dir, OLD_DB)
        self.new = os.path.join(self.dir, "stamind.db")

    def _touch(self, name: str) -> str:
        path = os.path.join(self.dir, name)
        with open(path, "w", encoding="utf-8") as f:
            f.write(name)
        return path

    def _rename(self, dry_run=False):
        return migrate.rename_database(self.old, self.new, dry_run)

    def test_a_closed_database_is_renamed(self):
        self._touch(OLD_DB)
        self.assertEqual(self._rename(), "renamed")
        self.assertFalse(os.path.exists(self.old))
        self.assertTrue(os.path.exists(self.new))

    def test_a_wal_file_beside_the_database_refuses_the_rename(self):
        """SQLite keeps a `-wal` file beside a database only while a connection is open.
        Renaming the file out from under that process is what this refusal prevents."""
        self._touch(OLD_DB)
        self._touch(OLD_DB + "-wal")
        self.assertEqual(self._rename(), "open")
        self.assertTrue(os.path.exists(self.old))
        self.assertFalse(os.path.exists(self.new))

    def test_a_shm_file_beside_the_database_refuses_the_rename(self):
        self._touch(OLD_DB)
        self._touch(OLD_DB + "-shm")
        self.assertEqual(self._rename(), "open")
        self.assertTrue(os.path.exists(self.old))

    def test_a_snapshots_own_wal_file_does_not_refuse_the_rename(self):
        """The live database is closed, so the rename must go ahead. What sits beside it
        is a snapshot taken by hand months ago, with `-wal` and `-shm` files of its own.
        Those say nothing about the live database — which is why the check names the two
        sidecar files exactly instead of globbing for them."""
        self._touch(OLD_DB)
        snapshot = self._touch(SNAPSHOT)
        stray_wal = self._touch(SNAPSHOT + "-wal")
        stray_shm = self._touch(SNAPSHOT + "-shm")

        self.assertEqual(migrate.open_database_sidecars(self.old), [])
        self.assertEqual(self._rename(), "renamed")
        self.assertTrue(os.path.exists(self.new))
        for path in (snapshot, stray_wal, stray_shm):
            self.assertTrue(os.path.exists(path))

    def test_the_dry_run_moves_no_file(self):
        self._touch(OLD_DB)
        self.assertEqual(self._rename(dry_run=True), "pending")
        self.assertTrue(os.path.exists(self.old))
        self.assertFalse(os.path.exists(self.new))

    def test_a_second_run_finds_the_database_already_renamed(self):
        self._touch("stamind.db")
        self.assertEqual(self._rename(), "done")
        self.assertTrue(os.path.exists(self.new))

    def test_neither_name_present_is_nothing_to_rename(self):
        self.assertEqual(self._rename(), "missing")

    def test_both_names_present_refuses_rather_than_overwrite(self):
        """A command run after the rename landed creates an empty `stamind.db`. Renaming
        over it would destroy whatever it holds, so the script stops and asks."""
        self._touch(OLD_DB)
        self._touch("stamind.db")
        self.assertEqual(self._rename(), "both")
        with open(self.new, encoding="utf-8") as f:
            self.assertEqual(f.read(), "stamind.db")
        self.assertTrue(os.path.exists(self.old))

    def test_every_outcome_has_a_line_to_print(self):
        """`main` looks the outcome up in `DB_MESSAGES`, so a new one without a message
        would raise a KeyError in front of the athlete."""
        outcomes = {"renamed", "pending", "done", "missing", "open", "both"}
        self.assertEqual(set(migrate.DB_MESSAGES), outcomes)
        self.assertTrue(set(migrate.DB_REFUSALS) <= outcomes)


class RetagEventsTest(unittest.TestCase):
    """The calendar half: events already on the calendar taking the new `source` value."""

    def _retag(self, syncer, old_tag, new_tag, dry_run=False):
        with redirect_stdout(io.StringIO()) as out:
            patched, failed = migrate.retag_events(syncer, old_tag, new_tag, dry_run)
        return patched, failed, out.getvalue()

    def test_workout_events_take_the_new_tag(self):
        syncer = FakeSyncer([
            _event("evt-1", OLD_WORKOUT_TAG),
            _event("evt-2", OLD_WORKOUT_TAG),
            _event("evt-dentist", "something-else"),
        ])

        patched, failed, _ = self._retag(syncer, OLD_WORKOUT_TAG, "stamind")

        self.assertEqual((patched, failed), (2, 0))
        self.assertEqual(syncer.source_of("evt-1"), "stamind")
        self.assertEqual(syncer.source_of("evt-2"), "stamind")
        # An event the app never wrote is not ours to touch.
        self.assertEqual(syncer.source_of("evt-dentist"), "something-else")
        self.assertEqual(sorted(syncer.patch_calls), ["evt-1", "evt-2"])

    def test_a_signal_events_metric_and_value_survive_the_patch(self):
        """The coach reads a signal event's `metric` and `value`. Losing them while
        rewriting `source` would turn "2 drinks on the 13th" into an unnamed signal."""
        syncer = FakeSyncer([
            _event("evt-drink", OLD_SIGNAL_TAG, metric="alcohol", value="2"),
        ])

        patched, failed, _ = self._retag(syncer, OLD_SIGNAL_TAG, "stamind-context")

        self.assertEqual((patched, failed), (1, 0))
        self.assertEqual(
            syncer.private_of("evt-drink"),
            {"source": "stamind-context", "metric": "alcohol", "value": "2"},
        )

    def test_the_dry_run_counts_and_patches_nothing(self):
        syncer = FakeSyncer([_event("evt-1", OLD_WORKOUT_TAG)])

        patched, failed, printed = self._retag(
            syncer, OLD_WORKOUT_TAG, "stamind", dry_run=True
        )

        self.assertEqual((patched, failed), (0, 0))
        self.assertEqual(syncer.patch_calls, [])
        self.assertEqual(syncer.source_of("evt-1"), OLD_WORKOUT_TAG)
        self.assertIn("1 event(s) would become source=stamind", printed)

    def test_a_second_run_finds_nothing_left_to_do(self):
        """The listing asks Google for the *old* tag, so an event the first run patched
        is not returned to the second. Running the script twice is a no-op, not a double
        patch."""
        syncer = FakeSyncer([_event("evt-1", OLD_WORKOUT_TAG)])
        self._retag(syncer, OLD_WORKOUT_TAG, "stamind")
        syncer.patch_calls.clear()

        patched, failed, printed = self._retag(syncer, OLD_WORKOUT_TAG, "stamind")

        self.assertEqual((patched, failed), (0, 0))
        self.assertEqual(syncer.patch_calls, [])
        self.assertIn("no events left to re-tag", printed)

    def test_a_failed_patch_is_counted_and_the_rest_still_run(self):
        """A run that dies half way has to be finishable by running it again, so one
        event the API refuses cannot abort the several thousand behind it."""
        syncer = FakeSyncer(
            [_event(f"evt-{n}", OLD_WORKOUT_TAG) for n in range(3)], failing={"evt-1"}
        )

        patched, failed, _ = self._retag(syncer, OLD_WORKOUT_TAG, "stamind")

        self.assertEqual((patched, failed), (2, 1))
        self.assertEqual(syncer.source_of("evt-0"), "stamind")
        self.assertEqual(syncer.source_of("evt-2"), "stamind")
        # The one that failed still carries the old tag, so the next run picks it up.
        self.assertEqual(syncer.source_of("evt-1"), OLD_WORKOUT_TAG)
        self.assertEqual(
            [e["id"] for e in syncer.list_events_by_tag(OLD_WORKOUT_TAG)], ["evt-1"]
        )


if __name__ == "__main__":
    unittest.main()
