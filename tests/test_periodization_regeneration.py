"""What a regeneration clears and what it preserves: a completed session on
today's date, a workout already pushed to the calendar, and one pushed and
since adapted so that the calendar copy is stale.
"""
import os
import unittest
from datetime import datetime, timedelta, timezone
from unittest.mock import patch

from tests.helpers import clear_all_tables, rebind_test_db, save_workout
from tests import test_db_path

TEST_DB_PATH = test_db_path("test_periodization_regeneration.db")


def _days_out(n: int) -> str:
    return (datetime.now(timezone.utc).date() + timedelta(days=n)).isoformat()


# Fixtures ride on today rather than on fixed dates; test_periodization.py says why.
GOAL_DATE = _days_out(71)

from stamind.db import Database

test_db = Database(db_path=TEST_DB_PATH)
rebind_test_db(test_db)

from stamind.coach.service import coach_service


def _generate_workouts(**kwargs):
    """`workout generate` end to end: propose, then accept, as the CLI does on a `y`.

    Generation is two halves so the athlete reads the plan before it is written; tests
    exercising the write want both, and the proposal alone is called directly where only
    the refusal or the prompt is under test."""
    proposal = coach_service.workout_generate(**kwargs)
    return proposal.reasoning, coach_service.workout_generate_apply(proposal)


def _session_titles(rows) -> list:
    """The titles of the real sessions in a listing.

    Generation now covers every date of its span, filling the ones the model left out
    with explicit rest (DESIGN_runway_nudge.md §2.1), so a fixture whose mocked response
    holds one session gets that session plus a rest row per remaining day. These tests are
    about which sessions survive a regeneration or a rollback, not about the coverage."""
    return [w["title"] for w in rows if w["sport_type"] != "rest"]


class TestRegenerationClearsTheOldSessions(unittest.TestCase):
    """Regenerating is archive-and-rebuild, so the previous plan's future sessions
    are wiped — but never a session the athlete has already performed."""

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

    @patch("stamind.runtime.calendar_syncer")
    @patch("stamind.coach.engine.openrouter_client")
    def test_generate_plan_and_workouts_separately(self, mock_client, mock_calendar):
        obj_id = test_db.add_objective(
            title="Zurich Marathon", target_date=GOAL_DATE,
            sport_type="running",
        )

        mock_client.complete.return_value = {
            "strategy": "Separate strategy philosophy",
            "mesocycles": [{
                "name": "Base Phase", "start_date": "2026-06-01",
                "end_date": "2026-06-28", "focus": "Base",
            }],
        }

        with self.assertRaises(ValueError):
            coach_service.workout_generate()

        proposal = coach_service.plan_generate(force=False)
        strategy, mesos = proposal['strategy'], proposal['mesocycles']
        self.assertEqual(strategy, "Separate strategy philosophy")
        self.assertEqual(len(mesos), 1)
        mock_client.complete.assert_called_once()

        mock_client.complete.reset_mock()
        mock_client.complete.return_value = {
            "reasoning": "Separate workout reasoning",
            "workouts": [{
                "date": _days_out(0), "sport_type": "running",
                "title": "Base Run", "description": "30 mins",
            }],
        }
        reason, workouts = _generate_workouts()
        self.assertEqual(reason, "Separate workout reasoning")
        self.assertEqual(_session_titles(workouts), ["Base Run"])
        mock_client.complete.assert_called_once()

    @patch("stamind.runtime.calendar_syncer")
    @patch("stamind.coach.engine.openrouter_client")
    def test_generate_preserves_completed_today_workout(
        self, mock_client, mock_calendar
    ):
        """When today's planned session has a matching completed activity, regeneration
        must keep today's workout and start the new sessions tomorrow."""
        test_db.add_objective(
            title="Zurich Marathon", target_date=GOAL_DATE,
            sport_type="running",
        )
        mock_client.complete.return_value = {
            "strategy": "Strategy", "mesocycles": [{
                "name": "Base", "start_date": "2026-06-01",
                "end_date": "2026-06-28", "focus": "Base",
            }],
        }
        coach_service.plan_generate(force=False)

        today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
        tomorrow = (datetime.now(timezone.utc) + timedelta(days=1)).strftime("%Y-%m-%d")

        # Today's planned workout, already done (a matching Garmin run today).
        save_workout(test_db,
            date=today, sport_type="running", title="Today Done",
            description="completed session", google_event_id="evt-today",
        )
        test_db.save_completed_activity(
            activity_id="act-today", date=today, start_time=None,
            activity_name="Morning Run", activity_type="running",
            duration_sec=3600, distance_km=10.0, elevation_gain_m=50.0,
            avg_hr=150, max_hr=170, rpe=6, tss=50.0,
        )

        # The model is asked to start tomorrow; it (correctly) dates its workout tomorrow.
        mock_client.complete.reset_mock()
        mock_client.complete.return_value = {
            "reasoning": "New plan", "workouts": [{
                "date": tomorrow, "sport_type": "running",
                "title": "Tomorrow Run", "description": "fresh",
            }],
        }
        _generate_workouts()

        # Today's completed workout survives; the new sessions begin tomorrow.
        titles = _session_titles(test_db.get_workouts(start_date=today))
        self.assertEqual(titles, ["Today Done", "Tomorrow Run"])
        # Today's Calendar event was left untouched (only future days are torn down).
        for call in mock_calendar.delete_event.call_args_list:
            self.assertNotEqual(call.args[0], "evt-today")

    @patch("stamind.runtime.calendar_syncer")
    @patch("stamind.coach.engine.openrouter_client")
    def test_generate_workouts_clears_stale_synced_workouts(
        self, mock_client, mock_calendar
    ):
        """Regenerating workouts must wipe the previous plan's future workouts,
        including synced ones (and delete their Google Calendar events).

        Past the commitment window, where the plan is the plan and a session the athlete
        has not read yet leaves no trace behind (DESIGN_plan_change_continuity.md §5.2)."""
        test_db.add_objective(
            title="Zurich Marathon", target_date=GOAL_DATE,
            sport_type="running",
        )

        mock_client.complete.return_value = {
            "strategy": "Strategy", "mesocycles": [{
                "name": "Base", "start_date": "2026-06-01",
                "end_date": "2026-06-28", "focus": "Base",
            }],
        }
        coach_service.plan_generate(force=False)

        # Simulate a stale session from an earlier generation that was synced to Calendar.
        today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
        future = (datetime.now(timezone.utc) + timedelta(days=10)).strftime("%Y-%m-%d")
        save_workout(test_db,
            date=future, sport_type="running", title="Old Plan Run",
            description="stale", google_event_id="evt-old-123",
        )

        mock_client.complete.reset_mock()
        mock_client.complete.return_value = {
            "reasoning": "New plan", "workouts": [{
                "date": today, "sport_type": "running",
                "title": "New Run", "description": "fresh",
            }],
        }
        _generate_workouts()

        # The stale synced workout is gone, and only the new workout remains.
        remaining = test_db.get_workouts(start_date=today)
        titles = _session_titles(remaining)
        self.assertNotIn("Old Plan Run", titles)
        self.assertEqual(titles, ["New Run"])
        # Its Google Calendar event was deleted.
        mock_calendar.delete_event.assert_called_once_with("evt-old-123")

    @patch("stamind.runtime.calendar_syncer")
    @patch("stamind.coach.engine.openrouter_client")
    def test_generate_workouts_clears_stale_unsynced_calendar_workouts(
        self, mock_client, mock_calendar
    ):
        """A workout that was pushed then adapted/swapped (stale but with a
        google_event_id) must still have its Calendar event deleted on regenerate —
        i.e. cleanup keys on google_event_id, not the freshness state (orphan guard)."""
        test_db.add_objective(
            title="Zurich Marathon", target_date=GOAL_DATE,
            sport_type="running",
        )

        mock_client.complete.return_value = {
            "strategy": "Strategy", "mesocycles": [{
                "name": "Base", "start_date": "2026-06-01",
                "end_date": "2026-06-28", "focus": "Base",
            }],
        }
        coach_service.plan_generate(force=False)

        today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
        future = (datetime.now(timezone.utc) + timedelta(days=10)).strftime("%Y-%m-%d")
        # On the calendar (google_event_id) but pending re-push after an adaptation.
        save_workout(test_db,
            date=future, sport_type="running", title="Adapted Run",
            description="adapted", google_event_id="evt-stale-456",
            modification_reason="swapped",
        )

        mock_client.complete.reset_mock()
        mock_client.complete.return_value = {
            "reasoning": "New plan", "workouts": [{
                "date": today, "sport_type": "running",
                "title": "New Run", "description": "fresh",
            }],
        }
        _generate_workouts()

        remaining = test_db.get_workouts(start_date=today)
        self.assertEqual(_session_titles(remaining), ["New Run"])
        mock_calendar.delete_event.assert_called_once_with("evt-stale-456")


if __name__ == "__main__":
    unittest.main()
