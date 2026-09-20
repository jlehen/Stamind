"""The companion voice on goals, constraints, the plan and the fitness summary
(DESIGN_bot_simple_frontend.md §6, §11).

`trainmate/cli/render/plan_lines.py`. The day-side line builders, and the rules about
the render package itself, are tests/test_simple_render.py.
"""
import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from trainmate.cli.render import plan_lines


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


class PlanLinesTest(unittest.TestCase):
    """`simple_plan_lines` — the companion plan view (§11, §11.2): one stanza per mesocycle,
    a blank line before each — marker and name, then the window and the one thing the
    window cannot say — the active mesocycle's focus headline, and the goal day closing
    the road."""

    GOAL = {"id": 1, "title": "Marathon", "target_date": "2026-09-26",
            "sport_type": "running", "date_type": "event", "status": "active"}
    ACTIVE_MACRO = {"id": 6, "status": "active"}
    MESOCYCLES = [
        {"id": 1, "name": "Base", "start_date": "2026-07-27",
         "end_date": "2026-08-16", "focus": "Aerobic volume."},
        {"id": 2, "name": "Build", "start_date": "2026-08-17",
         "end_date": "2026-09-06", "focus": "Threshold work."},
        {"id": 3, "name": "Peak", "start_date": "2026-09-07",
         "end_date": "2026-09-16", "focus": "Race sharpening."},
    ]

    def _lines(self, today="2026-08-30"):
        return plan_lines.simple_plan_lines(
            self.GOAL, self.ACTIVE_MACRO, self.MESOCYCLES, today
        )

    def test_the_road_by_stanza(self):
        lines = self._lines()
        self.assertEqual(lines[:12], [
            "🧭 The road to Marathon",
            "",
            "✅ Base",
            "Jul 27 – Aug 16",
            "",
            "📍 Build",
            "Aug 17 – Sep 06 · you're in week 2 of 3",
            "Threshold work.",
            "",
            "⏳ Peak",
            "Sep 07 – Sep 16 · 10 days",
            "",
        ])
        self.assertIn("🏁 The big day: Sat Sep 26 (in 4 weeks)", lines[-1])

    def test_a_blank_line_opens_every_stanza(self):
        """A phone flows the text, so whitespace is the only column it can draw
        (§11.2): every marker line, and the close, sits under a blank one."""
        lines = self._lines()
        for i, line in enumerate(lines):
            if line[:1] in ("✅", "📍", "⏳", "🏁"):
                self.assertEqual(lines[i - 1], "", f"no blank line before {line!r}")

    def test_a_finished_mesocycle_says_nothing_past_its_window(self):
        """✅ says done and the window says when, so no tail and no focus behind them."""
        lines = self._lines()
        i = lines.index("✅ Base")
        self.assertEqual(lines[i + 1:i + 3], ["Jul 27 – Aug 16", ""])

    def test_exact_week_mesocycles_read_in_weeks(self):
        lines = plan_lines.simple_plan_lines(
            self.GOAL, self.ACTIVE_MACRO,
            [{"id": 3, "name": "Peak", "start_date": "2026-09-07",
              "end_date": "2026-09-20", "focus": "Race sharpening."}],
            "2026-08-30",
        )
        self.assertEqual(lines[2:4], ["⏳ Peak", "Sep 07 – Sep 20 · 2 weeks"])

    def test_a_long_focus_shrinks_to_its_first_sentence(self):
        wall = ("Three weeks: two loading microcycles plus a deload. LOADING WEEKS: "
                "1-2 threshold sessions accumulating 40+ min in zone, " + "x" * 300)
        mesocycles = [dict(self.MESOCYCLES[1], focus=wall)]
        lines = plan_lines.simple_plan_lines(
            self.GOAL, self.ACTIVE_MACRO, mesocycles, "2026-08-30"
        )
        self.assertEqual(
            lines[4], "Three weeks: two loading microcycles plus a deload."
        )

    def test_a_long_single_sentence_focus_is_cut_at_a_word(self):
        wall = "word " * 100
        mesocycles = [dict(self.MESOCYCLES[1], focus=wall)]
        lines = plan_lines.simple_plan_lines(
            self.GOAL, self.ACTIVE_MACRO, mesocycles, "2026-08-30"
        )
        self.assertTrue(lines[4].endswith("…"))
        self.assertLessEqual(len(lines[4]), 221)

    def test_a_leading_label_is_not_the_headline(self):
        """The `plan generate` model likes to open a focus with "Purpose: …" — a field
        name, not a headline. Only a one-word label goes; a sentence with a colon in it stays."""
        self.assertEqual(
            plan_lines.simple_focus_snippet("Purpose: make the week non-negotiable. Then more."),
            "Make the week non-negotiable.",
        )
        self.assertEqual(
            plan_lines.simple_focus_snippet("Three weeks: two loading microcycles."),
            "Three weeks: two loading microcycles.",
        )

    def test_only_the_active_mesocycle_carries_its_focus(self):
        joined = "\n".join(self._lines())
        self.assertNotIn("Aerobic volume.", joined)
        self.assertNotIn("Race sharpening.", joined)

    def test_a_horizon_goal_closes_without_a_big_day(self):
        goal = dict(self.GOAL, date_type="horizon")
        lines = plan_lines.simple_plan_lines(
            goal, self.ACTIVE_MACRO, self.MESOCYCLES, "2026-08-30"
        )
        self.assertIn("🏁 Building toward ~Sat Sep 26", lines[-1])

    def test_a_superseded_version_says_so(self):
        macro = dict(self.ACTIVE_MACRO, status="superseded")
        lines = plan_lines.simple_plan_lines(
            self.GOAL, macro, self.MESOCYCLES, "2026-08-30"
        )
        self.assertIn("older version", lines[1])

    def test_no_expert_ids_leak(self):
        for line in self._lines():
            self.assertNotIn("ID", line)
            self.assertNotIn("Macrocycle", line)

    def test_no_mesocycles_is_a_gentle_note(self):
        lines = plan_lines.simple_plan_lines(self.GOAL, self.ACTIVE_MACRO, [], "2026-08-30")
        self.assertIn("No training mesocycles drawn up yet", lines[-1])


class MesocycleButtonsTest(unittest.TestCase):
    """`simple_mesocycle_buttons` — the door under the plan view (§11.2): one "Tell me
    more" whose leaves send `bot mesocycle <id>` for the mesocycles under way or ahead."""

    MESOCYCLES = PlanLinesTest.MESOCYCLES

    def test_mesocycles_under_way_or_ahead_sit_behind_one_button(self):
        buttons = plan_lines.simple_mesocycle_buttons(self.MESOCYCLES, "2026-08-30")
        self.assertEqual(len(buttons), 1)
        self.assertEqual(buttons[0]["label"], "🔎 Tell me more")
        leaves = buttons[0]["menu"]
        self.assertEqual([leaf["label"] for leaf in leaves], ["📍 Build", "⏳ Peak"])
        self.assertEqual([leaf["send"] for leaf in leaves], ["bot mesocycle 2", "bot mesocycle 3"])

    def test_a_lone_mesocycle_is_offered_directly(self):
        buttons = plan_lines.simple_mesocycle_buttons(self.MESOCYCLES, "2026-09-10")
        self.assertEqual(buttons, [{"label": "🔎 Tell me more", "send": "bot mesocycle 3"}])

    def test_nothing_ahead_offers_nothing(self):
        self.assertEqual(plan_lines.simple_mesocycle_buttons(self.MESOCYCLES, "2026-09-20"), [])

    def test_a_long_name_is_cut_to_a_label(self):
        mesocycles = [self.MESOCYCLES[1],
                  dict(self.MESOCYCLES[2], name="Climb-Specific Severe / HIIT Transmutation")]
        label = plan_lines.simple_mesocycle_buttons(mesocycles, "2026-08-30")[0]["menu"][1]["label"]
        self.assertLessEqual(len(label), plan_lines.PICKER_LABEL_MAX)
        self.assertTrue(label.endswith("…"))


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
