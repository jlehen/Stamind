"""Whether a constraint rebuilds the plan, and which goals it rebuilds
(DESIGN_constraints.md §7): the displaced-load magnitude heuristic that
decides a replan is worth offering, and the goals the offer covers.
"""
import io
import os
import unittest
from contextlib import redirect_stdout
from unittest.mock import patch

from tests import test_db_path
from tests.helpers import (
    clear_all_tables, pin_clock, rebind_test_db, save_workout,
)

TEST_DB_PATH = test_db_path("test_constraints_replan.db")

from trainmate.db import Database

test_db = Database(db_path=TEST_DB_PATH)
rebind_test_db(test_db)

from trainmate.coach.service import coach_service


def tearDownModule():
    """The classes here recreate the database file without removing it, so the cleanup
    belongs to the module rather than to any one class."""
    if os.path.exists(TEST_DB_PATH):
        try:
            os.remove(TEST_DB_PATH)
        except OSError:
            pass


class TestConstraintPlanImpact(unittest.TestCase):
    """The concrete §7 magnitude heuristic: relative displaced-load trigger (vs the
    plan's trailing weekly planned load) OR a rest-window floor — either firing proposes
    a replan. No per-session "importance" term (see DESIGN_constraints.md §7/§11)."""

    @classmethod
    def setUpClass(cls):
        global test_db
        test_db = Database(db_path=TEST_DB_PATH)
        rebind_test_db(test_db)

    def setUp(self):
        clear_all_tables(test_db)
        # `constraint_plan_impact` measures from max(start, today), so a fixture whose
        # window sits in the past displaces nothing. Pin the clock to the eve of these
        # dates rather than making them relative: the trailing-week arithmetic below is
        # only readable when the dates are literal.
        pin_clock(self, "2026-07-31")

    def test_displaced_load_trigger_fires_even_when_advisory(self):
        # Trailing week (2026-07-25..2026-07-31, the 7 days before the constraint
        # starts) carries 200 TSS of planned load.
        save_workout(test_db, date="2026-07-28", sport_type="running",
                             title="Long Run", description="", tss=200)
        # The constraint's 3-day window overlaps 120 TSS — 60% of the trailing week,
        # over the default 50% threshold.
        save_workout(test_db, date="2026-08-02", sport_type="running",
                             title="Tempo", description="", tss=120)
        c = {"rest": 0, "start_date": "2026-08-01",
             "end_date": "2026-08-03", "title": "big trip"}
        impact = coach_service.constraint_plan_impact(c)
        self.assertGreaterEqual(impact["displaced_pct"], 50)
        self.assertTrue(coach_service.constraint_is_plan_shaping(c, impact))

    def test_small_displaced_load_is_not_plan_shaping(self):
        save_workout(test_db, date="2026-07-28", sport_type="running",
                             title="Long Run", description="", tss=200)
        save_workout(test_db, date="2026-08-01", sport_type="running",
                             title="Easy", description="", tss=20)  # 10% of the trailing week
        c = {"rest": 0, "start_date": "2026-08-01",
             "end_date": "2026-08-01", "title": "no run"}
        impact = coach_service.constraint_plan_impact(c)
        self.assertLess(impact["displaced_pct"], 50)
        self.assertFalse(coach_service.constraint_is_plan_shaping(c, impact))

    def test_rest_window_floor_fires_regardless_of_load(self):
        # No workouts at all — zero displaced load — but a 3-day rest window still
        # trips the independent rest-window floor (default replan_rest_span_days=3).
        c = {"rest": 1, "start_date": "2026-08-01",
             "end_date": "2026-08-03", "title": "injury"}
        impact = coach_service.constraint_plan_impact(c)
        self.assertEqual(impact["displaced_pct"], 0.0)
        self.assertEqual(impact["days"], 3)
        self.assertTrue(coach_service.constraint_is_plan_shaping(c, impact))

    def test_short_rest_window_below_floor_is_not_plan_shaping(self):
        c = {"rest": 1, "start_date": "2026-08-01",
             "end_date": "2026-08-01", "title": "no run"}
        impact = coach_service.constraint_plan_impact(c)
        self.assertFalse(coach_service.constraint_is_plan_shaping(c, impact))

    def test_single_advisory_day_with_no_history_is_not_plan_shaping(self):
        c = {"rest": 0, "start_date": "2026-08-01",
             "end_date": "2026-08-01", "title": "no run"}
        impact = coach_service.constraint_plan_impact(c)
        self.assertFalse(coach_service.constraint_is_plan_shaping(c, impact))


class TestConstraintReplanTarget(unittest.TestCase):
    """§7: which goals a constraint-triggered replan rebuilds.

    The ones whose own span holds the disrupted days — never "the next goal", which is
    what a stale `goal_id=` kwarg silently meant after d10208b renamed it. The magnitude
    that raises the proposal is measured over the constraint's OWN window, so the plan a
    `y` rewrites has to be the one covering that window.
    """

    @classmethod
    def setUpClass(cls):
        if os.path.exists(TEST_DB_PATH):
            os.remove(TEST_DB_PATH)
        global test_db
        test_db = Database(db_path=TEST_DB_PATH)
        rebind_test_db(test_db)

    def setUp(self):
        clear_all_tables(test_db)
        pin_clock(self, "2026-08-31")
        # Two goals, so the timeline has a seam to get wrong: goal A owns today through
        # 09-20, goal B the day after through 11-15.
        self.half = test_db.add_objective(
            title="Half marathon", target_date="2026-09-20", sport_type="running"
        )
        self.marathon = test_db.add_objective(
            title="Marathon", target_date="2026-11-15", sport_type="running"
        )

    def _constraint(self, start, end, rest=1, title="Away"):
        return test_db.get_constraint(test_db.add_constraint(
            title=title, start_date=start, end_date=end, rest=rest, source="manual",
        ))

    def _targets(self, start, end):
        from trainmate.cli.constraints import _replan_targets
        return _replan_targets(self._constraint(start, end))

    def test_a_far_window_targets_the_goal_it_lands_in_not_the_next_one(self):
        # A November holiday sits in the marathon's span; the half is over by then and
        # has nothing in it to reshape.
        rng = self._targets("2026-11-03", "2026-11-10")
        self.assertEqual((rng.start, rng.end), (self.marathon, self.marathon))

    def test_a_near_window_targets_only_the_near_goal(self):
        rng = self._targets("2026-09-05", "2026-09-08")
        self.assertEqual((rng.start, rng.end), (self.half, self.half))

    def test_a_straddling_window_targets_both_plans_it_breaks(self):
        # An injury from inside the half's span into the marathon's first weeks invalidates
        # both plans at once, so both are rebuilt — each still previewed and confirmed.
        rng = self._targets("2026-09-10", "2026-10-05")
        self.assertEqual((rng.start, rng.end), (self.half, self.marathon))

    def test_a_window_already_behind_us_targets_nothing(self):
        # Training that has been and gone cannot be planned around, however long the
        # window: the rest floor reads the constraint's FULL span, so it still proposes.
        self.assertIsNone(self._targets("2026-08-01", "2026-08-10"))

    def test_a_window_past_the_last_goal_targets_nothing(self):
        self.assertIsNone(self._targets("2026-12-01", "2026-12-10"))

    def test_the_flow_hands_plan_generate_the_goals_and_not_a_dead_kwarg(self):
        """The regression itself. `goal_id=` was read by nothing, so `plan generate` saw
        no goal and fell back to the next one on the calendar."""
        from trainmate.cli.constraints import _run_replan_flow
        constraint = self._constraint("2026-11-03", "2026-11-10")
        with patch("trainmate.cli.constraints.run_plan_generate") as generate, \
                patch("builtins.print"):
            _run_replan_flow("Family holiday", constraint)
        ns = generate.call_args[0][0]
        self.assertEqual((ns.goal_range.start, ns.goal_range.end),
                         (self.marathon, self.marathon))
        self.assertFalse(hasattr(ns, "goal_id"))

    def test_nothing_to_target_reports_instead_of_regenerating(self):
        from trainmate.cli.constraints import _run_replan_flow
        constraint = self._constraint("2026-08-01", "2026-08-10")
        buf = io.StringIO()
        with patch("trainmate.cli.constraints.run_plan_generate") as generate, \
                patch("trainmate.cli.constraints._today_str", return_value="2026-08-31"), \
                redirect_stdout(buf):
            _run_replan_flow("Was ill", constraint)
        generate.assert_not_called()
        out = " ".join(buf.getvalue().split())
        self.assertIn("cannot be planned around", out)
        self.assertIn("feeds the next plan", out)

    def test_the_proposal_is_not_raised_when_no_plan_covers_the_window(self):
        """"Replan around it?" presupposes a plan holding those days. A 10-day rest window
        in the past clears the §7 rest floor, but there is nothing a `y` could rebuild."""
        from trainmate.cli.constraints import _maybe_replan
        cid = test_db.add_constraint(
            title="Was ill", start_date="2026-08-01", end_date="2026-08-10",
            rest=1, source="manual",
        )
        with patch("trainmate.runtime.prompt") as prompt, patch("builtins.print"):
            _maybe_replan(cid, "Was ill", None)
        prompt.confirm.assert_not_called()
        self.assertEqual(test_db.get_constraint(cid)["replan"], 0)

    def test_the_proposal_is_still_raised_for_a_window_a_plan_covers(self):
        # The guard above must not swallow the ordinary case it sits in front of.
        from trainmate.cli.constraints import _maybe_replan
        cid = test_db.add_constraint(
            title="Family holiday", start_date="2026-11-03", end_date="2026-11-10",
            rest=1, source="manual",
        )
        with patch("trainmate.runtime.prompt") as prompt, patch("builtins.print"):
            prompt.confirm.return_value = False
            _maybe_replan(cid, "Family holiday", None)
        prompt.confirm.assert_called_once()


if __name__ == "__main__":
    unittest.main()
