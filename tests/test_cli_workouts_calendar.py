"""`workout push`, `workout wipe` and `workout prune-calendar`: the commands
that keep Google Calendar in step with the database.
"""
import os
import unittest
from datetime import datetime, timedelta, timezone
from unittest.mock import patch

from tests.helpers import clear_all_tables, run_cli, rebind_test_db, save_workout
from tests import test_db_path

TEST_DB_PATH = test_db_path("test_cli_workouts_calendar.db")

from trainmate.db import Database

test_db = Database(db_path=TEST_DB_PATH)
rebind_test_db(test_db)


class TestCliWorkoutsCalendarSync(unittest.TestCase):
    """Push defaults to today onward, so a past row a failed push left stale is
    warned about rather than silently skipped; and a marker is not an orphan
    just because a session took its slot."""

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
        clear_all_tables(test_db)

    def run_cli(self, args, input_value="n"):
        return run_cli(args, input_value)

    @patch("trainmate.runtime.calendar_syncer")
    def test_workout_push_command(self, mock_calendar):
        exit_code, stdout, stderr = self.run_cli(["workout", "push"])
        self.assertEqual(exit_code, 0)
        self.assertIn("No new or modified workouts to sync", stdout)
        mock_calendar.sync_multiple.assert_not_called()

        today_str = datetime.now(timezone.utc).strftime("%Y-%m-%d")
        save_workout(test_db,
            date=today_str, sport_type="running", title="Tempo Run",
            description="30 mins fast",
        )

        exit_code, stdout, stderr = self.run_cli(["workout", "push"])
        self.assertEqual(exit_code, 0)
        self.assertIn("Syncing 1 workouts to Google Calendar", stdout)
        mock_calendar.sync_multiple.assert_called_once()

    @patch("trainmate.runtime.calendar_syncer")
    def test_workout_push_warns_about_stale_past_workouts(self, mock_calendar):
        """`push` defaults to today onward, so a past row left stale by a failed push
        has nothing that would re-push it. It must at least be surfaced."""
        from trainmate.workout_state import calendar_signature
        today = datetime.now(timezone.utc).date()
        past = (today - timedelta(days=4)).strftime("%Y-%m-%d")

        wid = save_workout(test_db,
            date=past, sport_type="running", title="Old Run", description="easy",
        )
        test_db.mark_workout_pushed(
            wid, "evt-past", calendar_signature(test_db.get_workout_by_id(wid))
        )
        # A push that never landed: content moves on, signature does not.
        save_workout(test_db,
            date=past, sport_type="running", title="Old Run", description="HARD",
        )

        exit_code, stdout, stderr = self.run_cli(["workout", "push"])
        self.assertEqual(exit_code, 0)
        self.assertIn("1 workout before", stdout)
        self.assertIn("[STALE]", stdout)
        # `notice` wraps, and the command can land across the break.
        self.assertIn(f"workout push -d {past}..", " ".join(stdout.split()))
        # Warning only — the past row stays outside the pushed window.
        mock_calendar.sync_multiple.assert_not_called()

    @patch("trainmate.runtime.calendar_syncer")
    def test_workout_push_no_warning_when_past_is_clean(self, mock_calendar):
        """A past workout that is synced (or was never pushed) must not warn."""
        today = datetime.now(timezone.utc).date()
        past = (today - timedelta(days=4)).strftime("%Y-%m-%d")
        save_workout(test_db,
            date=past, sport_type="running", title="Old Run", description="easy",
        )
        exit_code, stdout, stderr = self.run_cli(["workout", "push"])
        self.assertEqual(exit_code, 0)
        self.assertNotIn("still read [STALE]", stdout)

    @patch("trainmate.runtime.calendar_syncer")
    def test_workout_wipe(self, mock_calendar):
        save_workout(test_db,
            date="2026-06-02", sport_type="running", title="Run 1",
            description="30 mins", google_event_id="ge_1",
        )
        save_workout(test_db,
            date="2026-06-03", sport_type="running", title="Run 2",
            description="30 mins",
        )
        self.assertEqual(len(test_db.get_workouts()), 2)

        exit_code, stdout, stderr = self.run_cli(["workout", "wipe"], input_value="n")
        self.assertEqual(exit_code, 0)
        self.assertEqual(len(test_db.get_workouts()), 2)
        mock_calendar.delete_event.assert_not_called()

        exit_code, stdout, stderr = self.run_cli(["workout", "wipe"], input_value="y")
        self.assertEqual(exit_code, 0)
        self.assertIn("All workouts wiped successfully.", stdout)
        self.assertEqual(len(test_db.get_workouts()), 0)
        mock_calendar.delete_event.assert_called_once_with("ge_1")

        mock_calendar.reset_mock()
        save_workout(test_db,
            date="2026-06-02", sport_type="running", title="Run 1",
            description="30 mins", google_event_id="ge_2",
        )
        exit_code, stdout, stderr = self.run_cli(["workout", "wipe", "-y"])
        self.assertEqual(exit_code, 0)
        self.assertEqual(len(test_db.get_workouts()), 0)
        mock_calendar.delete_event.assert_called_once_with("ge_2")

    @patch("trainmate.runtime.calendar_syncer")
    def test_workout_prune_calendar(self, mock_calendar):
        # One live workout, one soft-removed (keeps its event), and two calendar
        # events no row claims — the fresh-database case.
        save_workout(test_db,
            date="2026-06-02", sport_type="running", title="Run 1",
            description="30 mins", google_event_id="ge_live",
        )
        removed_id = save_workout(test_db,
            date="2026-06-03", sport_type="running", title="Run 2",
            description="30 mins", google_event_id="ge_removed",
        )
        with test_db.workout_change(kind="stand-down") as change:
            change.void(date="2026-06-03", sport_type="running", reason="not today")

        mock_calendar.list_workout_events.return_value = [
            {"id": "ge_live", "summary": "Run 1", "start": {"date": "2026-06-02"}},
            {"id": "ge_removed", "summary": "[Deleted] Run 2", "start": {"date": "2026-06-03"}},
            {"id": "ge_orphan_a", "summary": "Old Ride", "start": {"date": "2026-05-01"}},
            {"id": "ge_orphan_b", "summary": "Old Swim", "start": {"date": "2026-06-10"}},
        ]
        mock_calendar.delete_event.return_value = True

        # Dry run reports both orphans and deletes nothing.
        exit_code, stdout, _ = self.run_cli(["workout", "prune-calendar", "--dry-run"])
        self.assertEqual(exit_code, 0)
        self.assertIn("Old Ride", stdout)
        self.assertIn("Old Swim", stdout)
        self.assertNotIn("Run 1", stdout)
        self.assertNotIn("[Deleted] Run 2", stdout)
        mock_calendar.delete_event.assert_not_called()

        # Declining the confirmation deletes nothing either.
        exit_code, stdout, _ = self.run_cli(["workout", "prune-calendar"], input_value="n")
        self.assertEqual(exit_code, 0)
        self.assertIn("Prune cancelled.", stdout)
        mock_calendar.delete_event.assert_not_called()

        # A date window bounds which orphans go.
        exit_code, stdout, _ = self.run_cli(
            ["workout", "prune-calendar", "-d", "2026-06-01..", "-y"]
        )
        self.assertEqual(exit_code, 0)
        self.assertIn("Pruned 1 orphaned Calendar event.", stdout)
        mock_calendar.delete_event.assert_called_once_with("ge_orphan_b")

        # Unbounded, the remaining orphan goes and the claimed events survive.
        mock_calendar.reset_mock()
        mock_calendar.delete_event.return_value = True
        exit_code, stdout, _ = self.run_cli(["workout", "prune-calendar", "-y"])
        self.assertEqual(exit_code, 0)
        self.assertIn("Pruned 2 orphaned Calendar events.", stdout)
        self.assertEqual(
            sorted(c.args[0] for c in mock_calendar.delete_event.call_args_list),
            ["ge_orphan_a", "ge_orphan_b"],
        )

    @patch("trainmate.runtime.calendar_syncer")
    def test_workout_prune_calendar_nothing_to_do(self, mock_calendar):
        save_workout(test_db,
            date="2026-06-02", sport_type="running", title="Run 1",
            description="30 mins", google_event_id="ge_live",
        )
        mock_calendar.list_workout_events.return_value = [
            {"id": "ge_live", "summary": "Run 1", "start": {"date": "2026-06-02"}},
        ]
        exit_code, stdout, _ = self.run_cli(["workout", "prune-calendar", "-y"])
        self.assertEqual(exit_code, 0)
        self.assertIn("No orphaned Calendar events", stdout)
        mock_calendar.delete_event.assert_not_called()

    @patch("trainmate.runtime.calendar_syncer")
    def test_workout_prune_calendar_keeps_a_marker_covered_in_its_slot(self, mock_calendar):
        """A marker is not an orphan just because a session took its slot
        (DESIGN_plan_change_continuity.md §5.6)."""
        from trainmate.gcal.reconcile import no_calendar_sync
        # The reconcile is suppressed so the ownership rows stay as written: this test
        # asks what `prune-calendar` reads, not what the sync would have done first.
        with no_calendar_sync():
            save_workout(test_db,
                date="2026-06-02", sport_type="running", title="Club run",
                description="45 mins", google_event_id="ge_marker",
            )
            with test_db.workout_change(
                kind="generate", commitment_end="2026-06-08"
            ) as change:
                change.void(date="2026-06-02", sport_type="running", reason="replaced")
            with test_db.workout_change(
                kind="generate", commitment_end="2026-06-08"
            ) as change:
                change.append(
                    date="2026-06-02", sport_type="running", title="Tempo 6x800",
                    description="intervals", duration_minutes=60, rpe=7, tss=70,
                )
            covering = test_db.get_workout("2026-06-02", "running")
            test_db.mark_workout_pushed(covering["id"], "ge_new", "sig")

        mock_calendar.list_workout_events.return_value = [
            {"id": "ge_marker", "summary": "[Cancelled] Club run",
             "start": {"date": "2026-06-02"}},
            {"id": "ge_new", "summary": "Tempo 6x800", "start": {"date": "2026-06-02"}},
            {"id": "ge_orphan", "summary": "Old Swim", "start": {"date": "2026-06-10"}},
        ]
        mock_calendar.delete_event.return_value = True

        exit_code, stdout, _ = self.run_cli(["workout", "prune-calendar", "-y"])
        self.assertEqual(exit_code, 0)
        self.assertNotIn("Club run", stdout)
        mock_calendar.delete_event.assert_called_once_with("ge_orphan")
