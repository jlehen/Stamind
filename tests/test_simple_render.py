"""The companion voice on a day, and the companion-mode config knobs
(DESIGN_bot_simple_frontend.md §3, §4.3, §6).

`trainmate/cli/render/session_lines.py`, plus the two rules about the render package
itself: which voice `TRAINMATE_RENDER` picks, and that no command module imports the
package back. The plan-side line builders are tests/test_simple_render_plan.py.
"""
import os
import sys
import unittest
from unittest.mock import patch

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from tests.helpers import pin_clock

from trainmate.cli import render
from trainmate.cli.render import session_lines
from trainmate.cli.render.companion import CompanionRenderer
from trainmate.cli.render.expert import ExpertRenderer
from trainmate.config import Config


class MakeRendererTest(unittest.TestCase):
    """The one place TRAINMATE_RENDER is read (DESIGN_render_persona.md §4)."""

    def test_unset_is_expert(self):
        with patch.dict(os.environ, {}, clear=False):
            os.environ.pop("TRAINMATE_RENDER", None)
            self.assertIsInstance(render.make_renderer(), ExpertRenderer)

    def test_simple_selects_the_companion_rendering(self):
        with patch.dict(os.environ, {"TRAINMATE_RENDER": "simple"}):
            self.assertIsInstance(render.make_renderer(), CompanionRenderer)
        with patch.dict(os.environ, {"TRAINMATE_RENDER": " SIMPLE "}):
            self.assertIsInstance(render.make_renderer(), CompanionRenderer)

    def test_other_values_stay_expert(self):
        with patch.dict(os.environ, {"TRAINMATE_RENDER": "fancy"}):
            renderer = render.make_renderer()
        self.assertIsInstance(renderer, ExpertRenderer)
        self.assertNotIsInstance(renderer, CompanionRenderer)

    def test_the_companion_inherits_every_surface_it_does_not_word_itself(self):
        """The opt-in list is the override set, so a surface nobody thought about gets
        the expert form rather than nothing (§2)."""
        for name in dir(ExpertRenderer):
            if name.startswith("_"):
                continue
            self.assertTrue(hasattr(CompanionRenderer, name))


class RenderImportDirectionTest(unittest.TestCase):
    """`cli/render/` imports the command modules; they must not import it back
    (DESIGN_render_persona.md §7).

    The graph is acyclic only in that direction: the render package reaches into the
    commands for their expert renderers, and the commands reach the render package
    through `runtime.render`, whose builder defers the import. A command module that
    imports it directly closes the loop, and a function-local import added to dodge that
    is the sign the graph has gone wrong, not a fix — so this looks for the module name
    anywhere in the file. Keyed on a directory glob, so a CLI module written tomorrow is
    covered tomorrow rather than whenever someone remembers the rule."""

    # The `bot` package is the exception the design names: the companion-only surfaces
    # call the line builders directly, because for them there is nothing to choose (§3).
    # Each exempt file is listed by its path under `cli/`, not by its bare name, so a
    # `views.py` in another command package is still covered — and not by the directory
    # either, so a new file under `cli/bot/` has to be added here deliberately. The
    # render package's own files are exempt by directory, so cutting it into more files
    # never quietly widens the exemption.
    ALLOWED = {"bot/views.py", "bot/capture.py", "bot/edit.py"}

    def test_no_command_module_imports_the_renderer(self):
        from pathlib import Path
        from trainmate.cli import render as render_package
        render_dir = Path(render_package.__file__).parent
        cli_dir = render_dir.parent
        offenders = [
            path.relative_to(cli_dir.parent).as_posix()
            for path in sorted(cli_dir.rglob("*.py"))
            if path.relative_to(cli_dir).as_posix() not in self.ALLOWED
            and render_dir not in path.parents
            and "cli.render" in path.read_text()
        ]
        self.assertEqual(offenders, [])


class SessionLineTest(unittest.TestCase):
    def test_full_line_with_lead_and_duration(self):
        w = {"sport_type": "running", "title": "Easy run", "duration_minutes": 40}
        self.assertEqual(
            session_lines.simple_session_line(w, lead="Today"), "🏃 Today: Easy run — 40 min"
        )

    def test_without_duration_or_lead(self):
        w = {"sport_type": "cycling", "title": "Spin"}
        self.assertEqual(session_lines.simple_session_line(w), "🚴 Spin")

    def test_unknown_sport_gets_the_generic_emoji(self):
        w = {"sport_type": "curling", "title": "Sweep"}
        self.assertTrue(
            session_lines.simple_session_line(w).startswith(session_lines.DEFAULT_SPORT_EMOJI)
        )

    def test_every_canonical_sport_has_its_own_emoji(self):
        from trainmate.sports import CANONICAL_SPORTS
        for sport in CANONICAL_SPORTS:
            self.assertIn(sport, session_lines.SPORT_EMOJI)


class DayLinesTest(unittest.TestCase):
    def setUp(self):
        pin_clock(self, "2026-08-25")

    def test_empty_day_is_a_rest_day(self):
        self.assertEqual(
            session_lines.simple_day_lines([], "2026-08-25"), [session_lines.REST_DAY_LINE]
        )

    def test_session_day_includes_the_description(self):
        lines = session_lines.simple_day_lines(
            [{"sport_type": "running", "title": "Easy run",
              "duration_minutes": 40, "date": "2026-08-25",
              "description": "Conversational pace."}],
            "2026-08-25",
        )
        self.assertEqual(lines[0], "🏃 Today: Easy run — 40 min")
        self.assertIn("Conversational pace.", lines[1])

    def test_another_day_is_named_not_called_today(self):
        lines = session_lines.simple_day_lines(
            [{"sport_type": "running", "title": "Long run",
              "date": "2026-08-27"}],
            "2026-08-27",
        )
        self.assertNotIn("Today", lines[0])
        self.assertIn("2026-08-27", lines[0])

    def test_two_sessions_on_a_day_are_separated_by_a_rule(self):
        """A prescription has blank lines in it, so a blank line cannot also be what
        ends one session — without the rule the second header reads as another
        paragraph of the first one's text (DESIGN_bot_simple_frontend.md §6)."""
        lines = session_lines.simple_day_lines(
            [{"sport_type": "cycling", "title": "HIIT 4x5", "date": "2026-08-25",
              "duration_minutes": 85,
              "description": "Warm up 15 min.\n\nMain set: 4x5 min.\n\nCool down."},
             {"sport_type": "strength_training", "title": "Strength",
              "date": "2026-08-25", "duration_minutes": 40,
              "description": "Squat 3x4.\n\nRDL 3x4."}],
            "2026-08-25",
        )
        text = "\n".join(lines)
        rule = session_lines.SIMPLE_SESSION_RULE
        self.assertEqual(text.count(f"\n{rule}\n"), 1, text)
        head, tail = text.split(rule)
        self.assertIn("HIIT 4x5", head)
        self.assertIn("Cool down.", head)
        self.assertIn("Strength", tail)
        self.assertNotIn("HIIT 4x5", tail)

    def test_a_lone_session_gets_no_rule(self):
        """The rule separates sessions; with one session there is nothing to separate."""
        lines = session_lines.simple_day_lines(
            [{"sport_type": "running", "title": "Easy run", "date": "2026-08-25",
              "duration_minutes": 40, "description": "Conversational pace."}],
            "2026-08-25",
        )
        self.assertNotIn(session_lines.SIMPLE_SESSION_RULE, "\n".join(lines))


    def _today(self, verdicts=None):
        return session_lines.simple_day_lines(
            [{"id": 7, "sport_type": "running", "title": "Easy run",
              "duration_minutes": 40, "date": "2026-08-25",
              "description": "Conversational pace."}],
            "2026-08-25", verdicts,
        )

    def test_a_session_already_trained_is_acknowledged(self):
        """Asking for a day you have already trained should say so, not just re-read the
        prescription back (DESIGN_bot_simple_frontend.md §6)."""
        lines = self._today({7: {"status": "done", "label": "Done", "reasons": []}})
        self.assertEqual(lines[1], session_lines.SIMPLE_DONE_LINE)

    def test_a_session_that_came_in_off_plan_still_counts_as_done(self):
        lines = self._today({7: {"status": "partial", "label": "Partial",
                                 "reasons": ["duration mismatch"]}})
        self.assertEqual(lines[1], session_lines.SIMPLE_DONE_LINE)
        # The mismatch itself is expert detail — the companion never reads it out.
        self.assertFalse(any("mismatch" in line for line in lines))

    def test_a_session_still_ahead_or_missed_says_nothing(self):
        """The §6 tone rule: a gap is never the lead, and 'you have not done it yet' is
        not news to someone reading their own day."""
        for status, label in (("pending", "Not yet"), ("missed", "Missed")):
            lines = self._today({7: {"status": status, "label": label, "reasons": []}})
            self.assertNotIn(session_lines.SIMPLE_DONE_LINE, lines)
            self.assertEqual(lines, self._today())


class WeekLinesTest(unittest.TestCase):
    def test_empty_window_is_a_break(self):
        lines = session_lines.simple_week_lines([])
        self.assertEqual(len(lines), 1)
        self.assertIn("enjoy the break", lines[0])

    def test_sessions_are_dated_and_counted(self):
        lines = session_lines.simple_week_lines([
            {"sport_type": "running", "title": "Easy run",
             "duration_minutes": 40, "date": "2026-08-25"},
            {"sport_type": "cycling", "title": "Endurance ride",
             "duration_minutes": 60, "date": "2026-08-27"},
        ])
        self.assertIn("🗓 Coming up:", lines[0])
        self.assertIn("Tue 25 · 🏃 Easy run — 40 min", lines[1])
        self.assertIn("2 sessions planned", lines[-1])

    def test_singular_session_word(self):
        lines = session_lines.simple_week_lines(
            [{"sport_type": "running", "title": "Easy run", "date": "2026-08-25"}]
        )
        self.assertIn("1 session planned", lines[-1])

    def test_a_trained_session_gets_the_check_and_the_count(self):
        lines = session_lines.simple_week_lines(
            [{"id": 1, "sport_type": "running", "title": "Easy run",
              "date": "2026-08-25"},
             {"id": 2, "sport_type": "cycling", "title": "Endurance ride",
              "date": "2026-08-27"}],
            verdicts={1: {"status": "done"}},
        )
        self.assertIn("✅", lines[1])
        self.assertNotIn("✅", lines[2])
        self.assertIn("1 of 2 sessions already done", lines[-1])

    def test_missed_and_pending_sessions_say_nothing(self):
        # §6 tone rule: a gap is never remarked on in the listing.
        lines = session_lines.simple_week_lines(
            [{"id": 1, "sport_type": "running", "title": "Easy run",
              "date": "2026-08-25"}],
            verdicts={1: {"status": "missed"}},
        )
        self.assertNotIn("✅", lines[1])
        self.assertIn("1 session planned", lines[-1])


class CompareLinesTest(unittest.TestCase):
    """The look back: one glyph per line is the whole verdict (§6)."""

    TODAY = "2026-08-30"

    @staticmethod
    def planned(date, sport="running", title="Easy run", minutes=40, act=None, pending=False):
        w = {"id": 1, "date": date, "sport_type": sport, "title": title,
             "duration_minutes": minutes}
        return {"date": date, "planned": w, "completed": act, "pending": pending}

    @staticmethod
    def activity(name="Morning Run", kind="running", minutes=43):
        return {"activity_id": "a1", "activity_name": name, "activity_type": kind,
                "duration_sec": minutes * 60}

    def lines(self, days, start="2026-08-24", end=TODAY):
        return session_lines.simple_compare_lines(days, start, end, self.TODAY)

    def test_a_trained_session_is_checked_with_what_was_done(self):
        lines = self.lines([
            ("2026-08-25", [self.planned("2026-08-25", act=self.activity())], []),
        ])
        self.assertEqual(lines[0], "🔎 Looking back, Mon Aug 24 to today:")
        self.assertEqual(lines[1], "Tue 25 · ✅ 🏃 Easy run — 40 min (you did 43 min)")
        self.assertIn("All 1 session done", lines[-1])

    def test_a_missed_session_gets_the_cross_and_the_count_stays_kind(self):
        lines = self.lines([
            ("2026-08-25", [self.planned("2026-08-25", act=self.activity())], []),
            ("2026-08-27", [self.planned("2026-08-27", "cycling", "Endurance ride", 60)], []),
        ])
        self.assertEqual(lines[2], "Thu 27 · ❌ 🚴 Endurance ride — 60 min")
        self.assertIn("1 of 2 sessions done — keep it rolling", lines[-1])

    def test_nothing_done_is_a_number_not_a_reproach(self):
        lines = self.lines([("2026-08-25", [self.planned("2026-08-25")], [])])
        self.assertTrue(lines[-1].startswith("\n0 of 1 session done"))
        self.assertIn("ready when you are", lines[-1])

    def test_today_is_still_ahead_and_not_counted(self):
        lines = self.lines([
            ("2026-08-30", [self.planned("2026-08-30", pending=True)], []),
        ])
        self.assertEqual(lines[1], "Sun 30 · ⏳ 🏃 Easy run — 40 min")
        self.assertIn("No sessions were due", lines[-1])

    def test_rest_days_kept_and_broken(self):
        lines = self.lines([
            ("2026-08-25", [self.planned("2026-08-25", "rest", "Rest", None)], []),
            ("2026-08-26", [self.planned(
                "2026-08-26", "rest", "Rest", None,
                act=self.activity("Evening Ride", "road_biking", 90),
            )], []),
            ("2026-08-30", [self.planned("2026-08-30", "rest", "Rest", None, pending=True)], []),
        ])
        self.assertEqual(lines[1], "Tue 25 · ✅ 🛌 Rest day")
        self.assertEqual(
            lines[2], "Wed 26 · ❌ 🛌 Rest day, but you trained: 🚴 Evening Ride — 90 min"
        )
        self.assertEqual(lines[3], "Sun 30 · 🛌 Rest day")
        # Rest days are not sessions to count.
        self.assertIn("No sessions were due", lines[-1])

    def test_an_extra_effort_is_a_plus_with_the_sport_emoji(self):
        lines = self.lines([
            ("2026-08-27", [], [self.activity("Zürich Loop", "road_biking", 90)]),
        ])
        self.assertEqual(lines[1], "Thu 27 · ➕ 🚴 Zürich Loop — 90 min, not on the plan")

    def test_an_empty_window_is_not_a_miss(self):
        lines = self.lines([])
        self.assertEqual(len(lines), 1)
        self.assertNotIn("❌", lines[0])
        self.assertIn("ahead of you", lines[0])

    def test_no_expert_vocabulary_leaks(self):
        lines = self.lines([
            ("2026-08-25", [self.planned("2026-08-25", act=self.activity())],
             [self.activity("Walk", "walking", 20)]),
        ])
        text = "\n".join(lines)
        for word in ("PLANNED", "ACTUAL", "UNPLANNED", "load", "TSS", "RPE", "2026-"):
            self.assertNotIn(word, text)


class WhenWordsTest(unittest.TestCase):
    """`simple_when` — the countdown vocabulary of the goal and plan views (§11)."""

    def test_the_near_words(self):
        self.assertEqual(session_lines.simple_when("2026-08-25", "2026-08-25"), "today")
        self.assertEqual(session_lines.simple_when("2026-08-26", "2026-08-25"), "tomorrow")
        self.assertEqual(session_lines.simple_when("2026-08-30", "2026-08-25"), "in 5 days")

    def test_weeks_then_months(self):
        self.assertEqual(session_lines.simple_when("2026-09-26", "2026-08-25"), "in 5 weeks")
        self.assertEqual(session_lines.simple_when("2027-04-30", "2026-08-30"), "in 8 months")

    def test_a_past_date_reads_as_passed(self):
        self.assertEqual(session_lines.simple_when("2026-08-20", "2026-08-25"), "passed")


class CompanionConfigKnobsTest(unittest.TestCase):
    """`telegram.ui` — the one companion knob config.yaml alone decides (§3). The push
    window and the router model resolve through the registry, and are covered against it
    in tests/test_cli_settings.py (DESIGN_settings.md §3)."""

    def _config(self, data):
        cfg = object.__new__(Config)
        cfg.data = data
        return cfg

    def test_ui_defaults_to_simple(self):
        self.assertEqual(self._config({}).telegram_ui, "simple")
        self.assertEqual(self._config({"telegram": {}}).telegram_ui, "simple")

    def test_ui_is_read_case_and_space_insensitively(self):
        cfg = self._config({"telegram": {"ui": " Expert "}})
        self.assertEqual(cfg.telegram_ui, "expert")

    def test_the_operator_is_named_or_described(self):
        """"Coach" is the app in the athlete's vocabulary, so the human with the CLI is
        named — and described when config.yaml gives no name (DESIGN_render_persona.md
        §5)."""
        cfg = self._config({"telegram": {"operator_name": " Alex "}})
        self.assertEqual(cfg.telegram_operator_name, "Alex")
        for data in ({}, {"telegram": {}}, {"telegram": {"operator_name": "  "}}):
            self.assertEqual(
                self._config(data).telegram_operator_name,
                "the person who set this up for you",
            )

    def test_a_nested_key_path_reads_absent_levels_as_nothing(self):
        """What every registry entry seeded from config.yaml is built on (§3)."""
        cfg = self._config({"telegram": {"push": {"morning_time": "07:30"}}})
        self.assertEqual(cfg.raw("telegram", "push", "morning_time"), "07:30")
        self.assertIsNone(cfg.raw("telegram", "push", "enabled"))
        self.assertIsNone(cfg.raw("telegram", "nothing", "here"))
        self.assertIsNone(cfg.raw("absent"))

if __name__ == "__main__":
    unittest.main()
