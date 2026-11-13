"""The companion voice on goals and constraints
(DESIGN_bot_simple_frontend.md §6, §11).

`stamind/cli/render/plan_lines.py`. The day-side line builders, and the rules about
the render package itself, are tests/test_simple_render.py.
"""
import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from stamind.cli.render import plan_lines


class GoalLinesTest(unittest.TestCase):
    """`simple_goal_lines` — the companion goals view (§11): countdown words, no IDs
    or state tags, archived goals silent, completed ones one celebration line."""

    EVENT = {"id": 1, "title": "Marathon", "target_date": "2026-09-26",
             "sport_type": "running", "date_type": "event", "status": "active",
             "description": "Sub 4 hours."}
    HORIZON = {"id": 2, "title": "Climb faster", "target_date": "2026-09-30",
               "sport_type": "cycling", "date_type": "horizon", "status": "active",
               "description": ""}

    def test_event_goal_names_the_day_and_the_countdown(self):
        lines = plan_lines.simple_goal_lines([self.EVENT], "2026-08-25")
        self.assertIn("🎯 What you're training for:", lines[0])
        self.assertIn("🏃 Marathon — on Sat Sep 26 (in 5 weeks)", lines[1])
        self.assertIn("Sub 4 hours.", lines[2])

    def test_horizon_goal_reads_as_by_approximately(self):
        lines = plan_lines.simple_goal_lines([self.HORIZON], "2026-08-25")
        self.assertIn("🚴 Climb faster — by ~Wed Sep 30 (in 5 weeks)", lines[1])

    def test_no_expert_ids_or_tags_leak(self):
        for line in plan_lines.simple_goal_lines([self.EVENT], "2026-08-25"):
            self.assertNotIn("ID", line)
            self.assertNotIn("[UPCOMING]", line)

    def test_completed_goals_become_one_celebration_line(self):
        past = dict(self.EVENT, target_date="2026-05-01")
        lines = plan_lines.simple_goal_lines([past, self.EVENT], "2026-08-25")
        self.assertIn("Marathon — on Sat Sep 26", "\n".join(lines))
        # ✅, not 🏁: a goal behind her is checked off like anything else done, and 🏁
        # is left to mean the target still ahead on every surface (§11.1).
        self.assertIn("✅ 1 goal already behind you", lines[-1])

    def test_archived_goals_say_nothing(self):
        archived = dict(self.HORIZON, status="archived")
        lines = plan_lines.simple_goal_lines([self.EVENT, archived], "2026-08-25")
        self.assertNotIn("Climb faster", "\n".join(lines))

    def test_empty_is_an_invitation(self):
        lines = plan_lines.simple_goal_lines([], "2026-08-25")
        self.assertEqual(len(lines), 1)
        self.assertIn("No goal on the horizon", lines[0])


class ConstraintLinesTest(unittest.TestCase):
    """simple_constraint_lines — the §5.5 companion constraints view: day words, no
    IDs or tier tags, and an empty list that reads as a clean slate."""

    TODAY = "2026-08-25"

    def _line(self, **kw):
        c = {"title": "no run Thursday", "start_date": "2026-08-27",
             "end_date": "2026-08-27", "rest": 0}
        c.update(kw)
        return plan_lines.simple_constraint_lines([c], self.TODAY)[1]

    def test_empty_is_a_clean_slate(self):
        [line] = plan_lines.simple_constraint_lines([], self.TODAY)
        self.assertIn("Nothing on the list", line)

    def test_single_day_reads_as_the_day(self):
        self.assertEqual(self._line(), "• no run Thursday — Thu Aug 27")

    def test_today_reads_as_today(self):
        line = self._line(start_date=self.TODAY, end_date=self.TODAY)
        self.assertTrue(line.endswith("— today"), line)

    def test_range_names_both_ends(self):
        self.assertIn("Thu Aug 27 to Fri Sep 04", self._line(end_date="2026-09-04"))

    def test_rest_gets_the_sleep_bullet(self):
        self.assertTrue(self._line(rest=1).startswith("🛌"))

    def test_no_expert_ids_leak(self):
        line = self._line()
        self.assertNotIn("ID", line)
        self.assertNotIn("advisory", line)

if __name__ == "__main__":
    unittest.main()
