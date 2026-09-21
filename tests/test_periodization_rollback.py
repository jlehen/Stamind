"""Plan versions and the two rollbacks: `plan rollback` puts the previous
periodization and its sessions back, and `workout rollback` puts one written
batch back without touching which plan is active.
"""
import os
import unittest
from datetime import datetime, timedelta, timezone
from unittest.mock import patch

from tests.helpers import clear_all_tables, rebind_test_db, save_workout
from tests import test_db_path

TEST_DB_PATH = test_db_path("test_periodization_rollback.db")


def _days_out(n: int) -> str:
    return (datetime.now(timezone.utc).date() + timedelta(days=n)).isoformat()


# Fixtures ride on today rather than on fixed dates; test_periodization.py says why.
GOAL_DATE = _days_out(71)

from trainmate.db import Database

test_db = Database(db_path=TEST_DB_PATH)
rebind_test_db(test_db)

from trainmate.coach.service import coach_service


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


class TestPlanAndWorkoutRollback(unittest.TestCase):
    """A regeneration keeps the plan it replaced as a superseded version, which is
    what both rollbacks restore from; a rollback with nothing behind it is
    rejected rather than silently doing nothing."""

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

    @patch("trainmate.coach.engine.openrouter_client")
    def test_plan_regenerate_supersedes_prior_version(self, mock_client):
        """Regenerating a plan keeps the prior macrocycle as a superseded version
        rather than deleting it (see DESIGN_plan_rollback.md)."""
        test_db.add_objective(
            title="Zurich Marathon", target_date=GOAL_DATE,
            sport_type="running",
        )
        meso = [{
            "name": "Base", "start_date": "2026-06-01",
            "end_date": "2026-06-28", "focus": "Base",
        }]
        mock_client.complete.return_value = {"strategy": "v1", "mesocycles": meso}
        coach_service.plan_generate(force=False)
        obj_id = test_db.get_active_objective()["id"]
        v1 = test_db.get_macrocycle_for_objective(obj_id)

        mock_client.complete.return_value = {"strategy": "v2", "mesocycles": meso}
        coach_service.plan_generate(force=True)

        versions = test_db.get_macrocycle_versions(obj_id)
        self.assertEqual(len(versions), 2)
        active = test_db.get_macrocycle_for_objective(obj_id)
        self.assertEqual(active["strategy"], "v2")
        self.assertNotEqual(active["id"], v1["id"])
        superseded = [v for v in versions if v["status"] == "superseded"]
        self.assertEqual([v["id"] for v in superseded], [v1["id"]])

    @patch("trainmate.runtime.calendar_syncer")
    @patch("trainmate.coach.engine.openrouter_client")
    def test_plan_rollback_restores_plan_and_workouts(self, mock_client, mock_calendar):
        """`plan rollback` restores the previous plan version, resurrects its workouts,
        archives the current plan's, and reconciles Google Calendar symmetrically."""
        mock_calendar.sync_workout.return_value = "evt-new"
        test_db.add_objective(
            title="Zurich Marathon", target_date=GOAL_DATE,
            sport_type="running",
        )
        meso = [{
            "name": "Base", "start_date": "2026-06-01",
            "end_date": "2026-06-28", "focus": "Base",
        }]
        today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
        obj_id = None

        # --- Plan v1 + its workouts ---
        mock_client.complete.return_value = {"strategy": "v1", "mesocycles": meso}
        coach_service.plan_generate(force=False)
        obj_id = test_db.get_active_objective()["id"]
        v1_id = test_db.get_macrocycle_for_objective(obj_id)["id"]
        mock_client.complete.return_value = {
            "reasoning": "w1", "workouts": [{
                "date": today, "sport_type": "running",
                "title": "V1 Run", "description": "v1 session",
            }],
        }
        _generate_workouts()

        # --- Plan v2 + its workouts (archives v1's) ---
        mock_client.complete.return_value = {"strategy": "v2", "mesocycles": meso}
        coach_service.plan_generate(force=True)
        v2_id = test_db.get_macrocycle_for_objective(obj_id)["id"]
        mock_client.complete.return_value = {
            "reasoning": "w2", "workouts": [{
                "date": today, "sport_type": "running",
                "title": "V2 Run", "description": "v2 session",
            }],
        }
        _generate_workouts()
        self.assertEqual(
            _session_titles(test_db.get_workouts(start_date=today)), ["V2 Run"]
        )

        # --- Roll back to v1 ---
        result = coach_service.plan_rollback(objective_id=obj_id)

        self.assertEqual(result["to"]["id"], v1_id)
        self.assertEqual(result["from"]["id"], v2_id)
        self.assertEqual(test_db.get_macrocycle_for_objective(obj_id)["strategy"], "v1")
        # V1's workout is live again; V2's is an older sibling in the same slot.
        live = test_db.get_workouts(start_date=today)
        self.assertEqual(_session_titles(live), ["V1 Run"])
        self.assertEqual(result["restored_workouts"], 1)
        # The restored workout was re-pushed to Calendar.
        self.assertTrue(mock_calendar.sync_workout.called)

    @patch("trainmate.coach.engine.openrouter_client")
    def test_plan_rollback_without_history_raises(self, mock_client):
        """Rolling back a plan with no earlier version is rejected."""
        test_db.add_objective(
            title="Zurich Marathon", target_date=GOAL_DATE,
            sport_type="running",
        )
        mock_client.complete.return_value = {"strategy": "v1", "mesocycles": [{
            "name": "Base", "start_date": "2026-06-01",
            "end_date": "2026-06-28", "focus": "Base",
        }]}
        coach_service.plan_generate(force=False)
        obj_id = test_db.get_active_objective()["id"]
        with self.assertRaises(ValueError):
            coach_service.plan_rollback(objective_id=obj_id)

    def _plan_v1(self, mock_client, strategy: str = "v1", force: bool = False) -> int:
        """Generates a periodization plan and returns the active macrocycle id."""
        # The mesocycle has to still be live for `workout generate` to have anything to
        # place into, so it rides on today like the goal does.
        mock_client.complete.return_value = {"strategy": strategy, "mesocycles": [{
            "name": "Base", "start_date": _days_out(-1),
            "end_date": _days_out(27), "focus": "Base",
        }]}
        coach_service.plan_generate(force=force)
        obj_id = test_db.get_active_objective()["id"]
        return test_db.get_macrocycle_for_objective(obj_id)["id"]

    @staticmethod
    def _generate_workout(mock_client, today: str, title: str) -> None:
        """Runs `workout generate` with a single-session response."""
        mock_client.complete.return_value = {
            "reasoning": title, "workouts": [{
                "date": today, "sport_type": "running",
                "title": title, "description": f"{title} session",
            }],
        }
        _generate_workouts()

    @patch("trainmate.runtime.calendar_syncer")
    @patch("trainmate.coach.engine.openrouter_client")
    def test_workout_rollback_restores_batch_leaving_plan_active(
        self, mock_client, mock_calendar
    ):
        """`workout rollback` restores the archived batch and re-pushes it, without
        touching the active plan version (see DESIGN_plan_rollback.md §9)."""
        mock_calendar.sync_workout.return_value = "evt-new"
        test_db.add_objective(
            title="Zurich Marathon", target_date=GOAL_DATE,
            sport_type="running",
        )
        today = datetime.now(timezone.utc).strftime("%Y-%m-%d")

        self._plan_v1(mock_client)
        self._generate_workout(mock_client, today, "V1 Run")
        v2_id = self._plan_v1(mock_client, strategy="v2", force=True)
        self._generate_workout(mock_client, today, "V2 Run")

        result = coach_service.workout_rollback()

        obj_id = test_db.get_active_objective()["id"]
        self.assertEqual(test_db.get_macrocycle_for_objective(obj_id)["id"], v2_id)
        self.assertEqual(
            _session_titles(test_db.get_workouts(start_date=today)), ["V1 Run"]
        )
        self.assertEqual(result["restored_workouts"], 1)
        self.assertTrue(mock_calendar.sync_workout.called)

    @patch("trainmate.runtime.calendar_syncer")
    @patch("trainmate.coach.engine.openrouter_client")
    def test_workout_rollback_within_one_plan_version(self, mock_client, mock_calendar):
        """Two regenerations under the same plan are separate changes, so a rollback
        undoes the second one (the case `plan rollback`'s version-keyed target cannot
        express)."""
        mock_calendar.sync_workout.return_value = "evt-new"
        test_db.add_objective(
            title="Zurich Marathon", target_date=GOAL_DATE,
            sport_type="running",
        )
        today = datetime.now(timezone.utc).strftime("%Y-%m-%d")

        macro_id = self._plan_v1(mock_client)
        self._generate_workout(mock_client, today, "First Run")
        self._generate_workout(mock_client, today, "Second Run")

        coach_service.workout_rollback()

        live = test_db.get_workouts(start_date=today)
        self.assertEqual(_session_titles(live), ["First Run"])
        self.assertEqual(live[0]["macrocycle_id"], macro_id)

        # A second rollback steps forward again: the batch just archived is now newest.
        coach_service.workout_rollback()
        self.assertEqual(
            _session_titles(test_db.get_workouts(start_date=today)), ["Second Run"]
        )

    def test_workout_rollback_without_archive_raises(self):
        """Rolling back workouts with nothing written is rejected."""
        with self.assertRaises(ValueError):
            coach_service.workout_rollback()

    def test_rollback_leaves_slots_before_the_floor_alone(self):
        """A rollback restores nothing dated before the floor.

        Appending a copy into a past slot would silently make it the live session for a
        day already trained — the same rule the archive-and-restore model had, keyed to
        the change instead of the archive stamp (DESIGN_workout_revisions.md §10)."""
        save_workout(test_db,
            date="2026-06-01", sport_type="running", title="Old Mon", description="x"
        )
        save_workout(test_db,
            date="2026-06-05", sport_type="running", title="Old Fri", description="x"
        )
        changes = test_db.get_workout_changes()
        first_change = changes[-1]["id"]
        # A later generation rewrites both slots.
        with test_db.workout_change(kind="generate") as change:
            change.append(date="2026-06-01", sport_type="running",
                          title="New Mon", description="y")
            change.append(date="2026-06-05", sport_type="running",
                          title="New Fri", description="y")
        rewrite = test_db.get_workout_changes()[0]["id"]

        restored, _unhonored = test_db.rollback_to_change(rewrite, "2026-06-03")

        self.assertEqual([w["title"] for w in restored], ["Old Fri"])
        # One live session per slot: the past-dated Monday kept the newer session, because
        # the floor is what stops a rollback rewriting a day already trained.
        self.assertEqual(
            [w["title"] for w in test_db.get_workouts(start_date="2026-06-01")],
            ["New Mon", "Old Fri"],
        )
        self.assertGreater(rewrite, first_change)


if __name__ == "__main__":
    unittest.main()
