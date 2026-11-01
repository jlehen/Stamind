"""The companion voice on goals, constraints and the fitness summary
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


class ProgressLinesTest(unittest.TestCase):
    """The §6 tone rule: every CTL branch reads as good news, and the trend line is
    always first (it doubles as the chart caption)."""

    TODAY = "2026-08-25"

    def _payload(self, start_ctl, end_ctl):
        return {"days": [
            {"date": "2026-07-25", "ctl": start_ctl},
            {"date": self.TODAY, "ctl": end_ctl},
        ]}

    def test_no_history_is_a_beginning(self):
        lines = plan_lines.simple_progress_lines({"days": []}, self.TODAY)
        self.assertIn("getting started", lines[0])
        self.assertEqual(len(lines), 2)

    def test_rising_ctl_is_climbing(self):
        lines = plan_lines.simple_progress_lines(self._payload(40.0, 50.0), self.TODAY)
        self.assertIn("climbing", lines[0])
        self.assertIn("25%", lines[0])

    def test_flat_ctl_is_steady(self):
        lines = plan_lines.simple_progress_lines(self._payload(50.0, 50.5), self.TODAY)
        self.assertIn("steady", lines[0])

    def test_falling_ctl_is_freshening_not_decay(self):
        lines = plan_lines.simple_progress_lines(self._payload(50.0, 40.0), self.TODAY)
        self.assertIn("freshening", lines[0])
        for word in ("down", "lost", "behind", "miss"):
            self.assertNotIn(word, lines[0].lower())

    def test_future_days_are_ignored(self):
        payload = {"days": [
            {"date": "2026-07-25", "ctl": 40.0},
            {"date": self.TODAY, "ctl": 50.0},
            {"date": "2026-09-25", "ctl": 90.0},
        ]}
        lines = plan_lines.simple_progress_lines(payload, self.TODAY)
        self.assertIn("25%", lines[0])

    # TODAY is a Tuesday: this week began Monday 24 August, last week Monday 17 August.
    def _with_weeks(self, last_week=None, this_week=None):
        payload = self._payload(50.0, 50.5)
        payload["weeks"] = [
            {"week_commencing": "2026-08-10", "actual_seconds": 99999.0},
            {"week_commencing": "2026-08-17", "actual_seconds": last_week},
            {"week_commencing": "2026-08-24", "actual_seconds": this_week},
        ]
        return plan_lines.simple_progress_lines(payload, self.TODAY)

    def test_hours_of_last_week_and_this_week_sit_between_trend_and_legend(self):
        lines = self._with_weeks(last_week=39960.0, this_week=9600.0)
        self.assertEqual(len(lines), 3)
        self.assertIn("steady", lines[0])
        self.assertEqual(
            lines[1], "⏱ You trained 11h06 last week, and 2h40 so far this week."
        )
        self.assertIn("chart", lines[2])

    def test_nothing_done_yet_this_week_says_last_week_only(self):
        lines = self._with_weeks(last_week=39960.0, this_week=0.0)
        self.assertEqual(lines[1], "⏱ You trained 11h06 last week.")

    def test_week_after_a_week_off_says_this_week_only_and_minutes_under_an_hour(self):
        lines = self._with_weeks(last_week=0.0, this_week=2700.0)
        self.assertEqual(lines[1], "⏱ You've trained 45 min so far this week.")

    def test_two_weeks_without_a_minute_of_activity_say_nothing_about_hours(self):
        # The 20 seconds are a watch started and stopped by mistake.
        lines = self._with_weeks(last_week=20.0, this_week=None)
        self.assertEqual(len(lines), 2)

    def test_the_week_runs_monday_to_sunday(self):
        weeks = [
            {"week_commencing": "2026-08-17", "actual_seconds": 39960.0},
            {"week_commencing": "2026-08-24", "actual_seconds": 9600.0},
        ]
        expected = "⏱ You trained 11h06 last week, and 2h40 so far this week."
        for day in ("2026-08-24", "2026-08-30"):  # the Monday and the Sunday
            self.assertEqual(plan_lines.simple_week_hours_line(weeks, day), expected)
        self.assertEqual(
            plan_lines.simple_week_hours_line(weeks, "2026-08-31"),  # the next Monday
            "⏱ You trained 2h40 last week.",
        )


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
