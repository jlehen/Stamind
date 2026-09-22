"""Calling a goal off stands its future sessions down without destroying
anything, and reinstating it recovers what is still ahead.
"""
import os
import unittest
from datetime import datetime, timedelta, timezone
from unittest.mock import patch

from tests.helpers import clear_all_tables, clock_at, rebind_test_db, save_workout
from tests import test_db_path

TEST_DB_PATH = test_db_path("test_periodization_goal_archival.db")


def _days_out(n: int) -> str:
    return (datetime.now(timezone.utc).date() + timedelta(days=n)).isoformat()


# Fixtures ride on today rather than on fixed dates; test_periodization.py says why.

from stamind.db import Database

test_db = Database(db_path=TEST_DB_PATH)
rebind_test_db(test_db)

from stamind.coach.service import coach_service


class TestGoalArchivalStandsSessionsDown(unittest.TestCase):
    """Calling a goal off stands its future sessions down without destroying anything
    (DESIGN_backward_evaluation.md §14)."""

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

    def _goal_with_plan(self, title: str, target: str, start: str, end: str):
        """A goal plus a one-mesocycle plan, returned as (objective_id, macrocycle_id)."""
        oid = test_db.add_objective(title, target, "running", "", 1)
        mid = test_db.save_macrocycle(
            oid, f"{title} strategy", "gh", "ch",
            [{"name": "Base", "start_date": start, "end_date": end, "focus": "aerobic"}],
        )
        return oid, mid

    @patch("stamind.runtime.calendar_syncer")
    def test_archiving_one_goal_spares_the_other_goals_sessions(self, _cal):
        """The sweep is scoped by plan version, not by date: both sessions sit in the
        same future window, and only the called-off goal's is stood down."""
        a_oid, a_mid = self._goal_with_plan(
            "Race A", _days_out(60), _days_out(0), _days_out(30)
        )
        _b_oid, b_mid = self._goal_with_plan(
            "Race B", _days_out(120), _days_out(31), _days_out(90)
        )
        save_workout(test_db, _days_out(3), "running", "A session", "x",
                             macrocycle_id=a_mid)
        save_workout(test_db, _days_out(5), "cycling", "B session", "x",
                             macrocycle_id=b_mid)

        result = coach_service.goal_archive(a_oid)

        self.assertEqual(result["archived_workouts"], 1)
        self.assertEqual(
            [w["title"] for w in test_db.get_workouts(start_date=_days_out(0))],
            ["B session"],
        )

    @patch("stamind.runtime.calendar_syncer")
    def test_archiving_leaves_untagged_sessions_in_place_and_counts_them(self, _cal):
        """An untagged session belongs to no plan version, so no goal may claim it."""
        oid, mid = self._goal_with_plan(
            "Race A", _days_out(60), _days_out(0), _days_out(30)
        )
        save_workout(test_db, _days_out(3), "running", "Tagged", "x", macrocycle_id=mid)
        # Beyond every mesocycle, so save_workout finds no plan to tag it with.
        save_workout(test_db, _days_out(45), "running", "Untagged", "x")

        result = coach_service.goal_archive(oid)

        self.assertEqual(result["archived_workouts"], 1)
        self.assertEqual(result["untagged"], 1)
        self.assertEqual(
            [w["title"] for w in test_db.get_workouts(start_date=_days_out(0))],
            ["Untagged"],
        )

    @patch("stamind.runtime.calendar_syncer")
    def test_archiving_leaves_the_training_already_done(self, _cal):
        """A called-off race does not un-train the work behind the athlete."""
        oid, mid = self._goal_with_plan(
            "Race A", _days_out(60), _days_out(-30), _days_out(30)
        )
        save_workout(test_db, _days_out(-5), "running", "Done", "x", macrocycle_id=mid)
        save_workout(test_db, _days_out(5), "running", "Ahead", "x", macrocycle_id=mid)

        result = coach_service.goal_archive(oid)

        self.assertEqual(result["archived_workouts"], 1)
        self.assertEqual(
            [w["title"] for w in test_db.get_workouts(start_date=_days_out(-30))],
            ["Done"],
        )

    @patch("stamind.runtime.calendar_syncer")
    def test_archiving_keeps_the_plan_its_versions_and_its_feedback(self, _cal):
        """The whole point of archiving over deleting: the history survives."""
        oid, mid = self._goal_with_plan(
            "Race A", _days_out(60), _days_out(0), _days_out(30)
        )
        test_db.add_plan_feedback(mid, "too much volume in week 3")
        save_workout(test_db, _days_out(3), "running", "A session", "x",
                             macrocycle_id=mid)

        coach_service.goal_archive(oid)

        self.assertIsNotNone(test_db.get_macrocycle(mid))
        self.assertEqual(len(test_db.get_macrocycle_versions(oid)), 1)
        self.assertEqual(len(test_db.get_mesocycles_for_macrocycle(mid)), 1)
        self.assertEqual(len(test_db.list_plan_feedback(mid)), 1)

    @patch("stamind.runtime.calendar_syncer")
    def test_reinstating_brings_the_stood_down_sessions_back(self, _cal):
        """`goal_reinstate` is the exact mirror of `goal_archive`."""
        oid, mid = self._goal_with_plan(
            "Race A", _days_out(60), _days_out(0), _days_out(30)
        )
        save_workout(test_db, _days_out(3), "running", "A session", "x",
                             macrocycle_id=mid)
        coach_service.goal_archive(oid)
        self.assertEqual(test_db.get_workouts(start_date=_days_out(0)), [])

        result = coach_service.goal_reinstate(oid)

        self.assertEqual(result["restored_workouts"], 1)
        self.assertEqual(
            [w["title"] for w in test_db.get_workouts(start_date=_days_out(0))],
            ["A session"],
        )

    @patch("stamind.runtime.calendar_syncer")
    def test_reinstating_recovers_only_what_is_still_ahead(self, _cal):
        """A goal reinstated late gets back the sessions still in front of it, not the
        ones whose dates passed while it was called off (DESIGN_plan_rollback.md §9)."""
        oid, mid = self._goal_with_plan(
            "Race A", _days_out(60), _days_out(-30), _days_out(30)
        )
        save_workout(test_db, _days_out(2), "running", "Soon", "x", macrocycle_id=mid)
        save_workout(test_db, _days_out(9), "cycling", "Later", "x", macrocycle_id=mid)
        coach_service.goal_archive(oid)

        # The clock moves past the first session while the goal is archived.
        with clock_at(_days_out(5)):
            result = coach_service.goal_reinstate(oid)

        self.assertEqual(result["restored_workouts"], 1)
        self.assertEqual(
            [w["title"] for w in test_db.get_workouts(start_date=_days_out(-30))],
            ["Later"],
        )


if __name__ == "__main__":
    unittest.main()
