"""Which voids keep their Calendar event after a change commits, and what it then says.

The pass itself is `gcal/reconcile.py`; the wording of the event it pushes is
`gcal/event.py`, asked here directly rather than through a mocked API.
"""
import os
import unittest
from unittest.mock import MagicMock, patch

from tests.helpers import rebind_test_db
from tests import test_db_path

TEST_DB_PATH = test_db_path("test_trainmate_gcal_reconcile.db")

from trainmate.db import Database
from trainmate.gcal.event import event_body

test_db = Database(db_path=TEST_DB_PATH)
rebind_test_db(test_db)


class TestARemovalLeavesATrace(unittest.TestCase):
    """Which voids keep their Calendar event, and what the athlete reads on it
    (DESIGN_plan_change_continuity.md §5.1/§5.2)."""

    TODAY = "2026-09-09"

    @classmethod
    def setUpClass(cls):
        if os.path.exists(TEST_DB_PATH):
            os.remove(TEST_DB_PATH)
        global test_db
        test_db = Database(db_path=TEST_DB_PATH)
        rebind_test_db(test_db)

    @classmethod
    def tearDownClass(cls):
        if os.path.exists(TEST_DB_PATH):
            try:
                os.remove(TEST_DB_PATH)
            except OSError:
                pass

    def setUp(self):
        from tests.helpers import clear_all_tables, pin_clock
        clear_all_tables(test_db)
        pin_clock(self, self.TODAY)

    # --- fixtures ----------------------------------------------------------------

    def _session(self, date_str, *, kind="generate", commitment_end=None, sport="cycling"):
        """One session, written under a change carrying the given window stamp.

        The automatic reconcile is suppressed throughout this class: these tests ask what
        `_plan` decides, so letting the write path act on that decision first would leave
        nothing to decide."""
        from trainmate.gcal.reconcile import no_calendar_sync
        with no_calendar_sync():
            with test_db.workout_change(
                kind=kind, commitment_end=commitment_end
            ) as change:
                change.append(
                    date=date_str, sport_type=sport, title="Long ride",
                    description="90 min steady.", duration_minutes=90, rpe=5, tss=95,
                )
        session = test_db.get_workout(date_str, sport)
        test_db.mark_workout_pushed(session["id"], f"evt-{session['id']}", "sig")
        return session["id"]

    def _void(self, date_str, *, kind, commitment_end=None, sport="cycling"):
        from trainmate.gcal.reconcile import no_calendar_sync
        with no_calendar_sync():
            with test_db.workout_change(
                kind=kind, commitment_end=commitment_end
            ) as change:
                change.void(date=date_str, sport_type=sport, reason="because")

    def _plan(self, lineage):
        from trainmate.gcal.reconcile import _plan
        return _plan(test_db, [lineage])

    # --- leaves_trace, clause by clause -------------------------------------------

    def test_an_athlete_void_keeps_its_event_outside_the_window(self):
        lineage = self._session("2026-10-20")
        self._void("2026-10-20", kind="stand-down")
        pushes, teardowns = self._plan(lineage)
        self.assertEqual([w["id"] for w in pushes], [lineage])
        self.assertEqual(teardowns, [])

    def test_a_coach_void_inside_the_window_keeps_its_event(self):
        lineage = self._session("2026-09-11")
        self._void("2026-09-11", kind="generate", commitment_end="2026-09-15")
        pushes, teardowns = self._plan(lineage)
        self.assertEqual([w["id"] for w in pushes], [lineage])
        self.assertEqual(teardowns, [])

    def test_a_coach_void_outside_the_window_is_torn_down(self):
        lineage = self._session("2026-09-30")
        self._void("2026-09-30", kind="generate", commitment_end="2026-09-15")
        pushes, teardowns = self._plan(lineage)
        self.assertEqual(pushes, [])
        self.assertEqual([t[0] for t in teardowns], [lineage])

    def test_an_empty_window_leaves_no_trace(self):
        lineage = self._session("2026-09-09")
        self._void("2026-09-09", kind="generate", commitment_end=None)
        pushes, teardowns = self._plan(lineage)
        self.assertEqual(pushes, [])
        self.assertEqual([t[0] for t in teardowns], [lineage])

    def test_the_window_is_read_from_the_change_not_from_the_clock(self):
        """Write with --no-sync and push a fortnight later: the answer must be the one the
        removal had when it was written (§5.2)."""
        from tests.helpers import pin_clock
        lineage = self._session("2026-09-11")
        self._void("2026-09-11", kind="generate", commitment_end="2026-09-15")
        pin_clock(self, "2026-09-30")
        pushes, _teardowns = self._plan(lineage)
        self.assertEqual([w["id"] for w in pushes], [lineage])

    def test_a_rollbacks_restored_copy_reads_the_original_changes_stamp(self):
        from trainmate.gcal.reconcile import no_calendar_sync
        lineage = self._session("2026-09-11")
        self._void("2026-09-11", kind="generate", commitment_end="2026-09-15")
        void_revision = test_db.get_lineage_revisions(lineage)[-1]
        with no_calendar_sync():
            with test_db.workout_change(kind="rollback") as change:
                change.restore(void_revision)
        head = test_db.get_lineage_head(lineage)
        self.assertEqual(head["change_kind"], "generate")
        self.assertEqual(head["commitment_end"], "2026-09-15")

    # --- the lineage read ---------------------------------------------------------

    def test_a_void_covered_in_the_same_slot_still_keeps_its_event(self):
        """`live_workouts` is "highest id in the slot", so a marker written and then
        covered is never the slot's live row — read it from its lineage (§5.2)."""
        from trainmate.gcal.reconcile import no_calendar_sync
        replaced = self._session("2026-09-11")
        with no_calendar_sync():
            with test_db.workout_change(
                kind="generate", commitment_end="2026-09-15"
            ) as change:
                change.void(date="2026-09-11", sport_type="cycling", reason="replaced")
                change.append(
                    date="2026-09-11", sport_type="cycling", title="Another ride",
                    description="60 min.", duration_minutes=60,
                )
        pushes, teardowns = self._plan(replaced)
        self.assertEqual([w["id"] for w in pushes], [replaced])
        self.assertEqual(teardowns, [])

    def test_a_lineage_superseded_in_place_is_still_torn_down(self):
        from trainmate.gcal.reconcile import no_calendar_sync
        lineage = self._session("2026-09-11")
        with no_calendar_sync():
            with test_db.workout_change(kind="tweak") as change:
                change.void(date="2026-09-11", sport_type="cycling", reason="replaced")
                change.append(
                    date="2026-09-11", sport_type="cycling", title="Another ride",
                    description="60 min.", duration_minutes=60,
                )
        # Its own void is inside no window, so the replaced session's event goes.
        pushes, teardowns = self._plan(lineage)
        self.assertEqual(pushes, [])
        self.assertEqual([t[0] for t in teardowns], [lineage])

    def test_a_trace_keeping_void_with_no_event_gets_one(self):
        """A session written and dropped between two syncs never had an event, and would
        otherwise leave no trace at all (§5.2)."""
        from trainmate.gcal.reconcile import no_calendar_sync
        with no_calendar_sync():
            with test_db.workout_change(kind="generate") as change:
                change.append(
                    date="2026-09-11", sport_type="cycling", title="Long ride",
                    description="90 min.", duration_minutes=90,
                )
        lineage = test_db.get_workout("2026-09-11", "cycling")["id"]
        self._void("2026-09-11", kind="generate", commitment_end="2026-09-15")
        pushes, teardowns = self._plan(lineage)
        self.assertEqual([w["id"] for w in pushes], [lineage])
        self.assertEqual(teardowns, [])

    # --- the words --------------------------------------------------------------

    def _summary(self, workout):
        """The event's title. Asked of the renderer, which needs no calendar at all."""
        return event_body(workout)["summary"]

    def test_the_void_word_comes_off_the_change_kind(self):
        base = {
            "date": "2026-09-11", "sport_type": "cycling", "title": "Long ride",
            "description": "90 min.", "removed": True, "removed_reason": "because",
        }
        for kind, word in (
            ("stand-down", "[Deleted]"), ("generate", "[Cancelled]"),
            ("adapt", "[Cancelled]"), ("tweak", "[Cancelled]"),
        ):
            with self.subTest(kind=kind):
                self.assertEqual(
                    self._summary({**base, "change_kind": kind}),
                    f"{word} Long ride",
                )

    def test_a_generate_or_tweak_revision_with_a_reason_is_not_titled_adapted(self):
        """"[Adapted]" means the coach eased this because of how the athlete was doing;
        a `workout generate` revision is the plan being written (§5.1), and a `workout
        tweak` one is what the athlete asked for (DESIGN_workout_tweak.md §3.3)."""
        base = {
            "date": "2026-09-11", "sport_type": "cycling", "title": "Easy spin",
            "description": "60 min.",
            "modification_reason": "never two hard days in a row",
        }
        self.assertEqual(
            self._summary({**base, "change_kind": "generate"}), "Easy spin"
        )
        self.assertEqual(
            self._summary({**base, "change_kind": "tweak"}), "Easy spin"
        )
        self.assertEqual(
            self._summary({**base, "change_kind": "adapt"}), "[Adapted] Easy spin"
        )


class TestMarkingAdherenceOnPastEvents(unittest.TestCase):
    """Which past events the verdict is stamped onto, and which writes are skipped."""

    def test_mark_adherence_from_results_skips_today_and_eventless(self):
        # Only strictly-past planned workouts that already have a Calendar event
        # get marked: today/future and event-less rows are skipped.
        from trainmate.gcal.reconcile import mark_adherence_from_results

        today = "2026-06-20"
        results = [
            {  # past + has event -> marked
                "date": "2026-06-18",
                "planned": {
                    "date": "2026-06-18", "sport_type": "running", "title": "Run",
                    "duration_minutes": 30, "tss": 30, "google_event_id": "evt-past",
                },
                "completed": {
                    "activity_id": "a", "activity_name": "Morning Run",
                    "activity_type": "running", "duration_sec": 1800,
                    "rpe": 6, "tss": 32.0,
                },
            },
            {  # today -> skipped
                "date": today,
                "planned": {
                    "date": today, "sport_type": "running", "title": "Run",
                    "google_event_id": "evt-today",
                },
                "completed": None,
            },
            {  # past but no event -> skipped
                "date": "2026-06-17",
                "planned": {
                    "date": "2026-06-17", "sport_type": "running", "title": "Run",
                    "google_event_id": None,
                },
                "completed": None,
            },
        ]

        with patch("trainmate.runtime.calendar_syncer") as mock_syncer:
            marked = mark_adherence_from_results(results, today_str=today)

        self.assertEqual(marked, 1)
        self.assertEqual(mock_syncer.sync_workout.call_count, 1)
        call = mock_syncer.sync_workout.call_args
        self.assertEqual(call.args[0]["google_event_id"], "evt-past")
        self.assertEqual(call.kwargs["adherence"]["status"], "done")

    def test_mark_adherence_from_results_skips_noop_when_already_marked(self):
        # Re-marking a settled past event is a no-op: the first pass writes and
        # records the adherence signature; a second pass with that signature
        # stored on the row skips the Calendar update entirely.
        from trainmate.gcal.reconcile import mark_adherence_from_results

        today = "2026-06-20"

        def make_results():
            return [{
                "date": "2026-06-18",
                "planned": {
                    "id": 7, "date": "2026-06-18", "sport_type": "running",
                    "title": "Run", "duration_minutes": 30, "tss": 30,
                    "google_event_id": "evt-past",
                },
                "completed": {
                    "activity_id": "a", "activity_name": "Morning Run",
                    "activity_type": "running", "duration_sec": 1800,
                    "rpe": 6, "tss": 32.0,
                },
            }]

        # First pass: nothing recorded yet -> pushes and stamps the signature.
        with patch("trainmate.runtime.calendar_syncer") as mock_syncer, \
                patch("trainmate.runtime.db") as mock_db:
            first = make_results()
            marked = mark_adherence_from_results(first, today_str=today)
            self.assertEqual(marked, 1)
            self.assertEqual(mock_syncer.sync_workout.call_count, 1)
            mock_db.mark_workout_adherence_pushed.assert_called_once()
            wid, signature = mock_db.mark_workout_adherence_pushed.call_args.args
            self.assertEqual(wid, 7)

        # Second pass: the row now carries that signature -> skipped, no write.
        with patch("trainmate.runtime.calendar_syncer") as mock_syncer, \
                patch("trainmate.runtime.db") as mock_db:
            second = make_results()
            second[0]["planned"]["adherence_pushed_signature"] = signature
            marked = mark_adherence_from_results(second, today_str=today)
            self.assertEqual(marked, 0)
            mock_syncer.sync_workout.assert_not_called()
            mock_db.mark_workout_adherence_pushed.assert_not_called()


if __name__ == "__main__":
    unittest.main()
