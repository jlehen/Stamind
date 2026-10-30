"""Deload weeks the plan dates (DESIGN_deload_weeks.md): the repair pass, the stored date, a
started deload kept through a replan, the prompts' line, and what the terminal and the
calendar's snapshot say."""
import unittest
from datetime import datetime
from unittest.mock import patch

from tests import test_db_path
from tests.helpers import clear_all_tables, pin_clock, rebind_test_db, run_cli, save_workout

from stamind import calendar_days, plan_versions
from stamind.cli.render import calendar_grid, calendar_page
from stamind.coach.formatting import mesocycle_text
from stamind.coach.service import coach_service
from stamind.db import Database
from stamind.db.periodization import repair_mesocycle_contiguity

TEST_DB_PATH = test_db_path("test_deload_weeks.db")
test_db = Database(db_path=TEST_DB_PATH)
rebind_test_db(test_db)


def _meso(name, start, end, deload=None):
    meso = {"name": name, "start_date": start, "end_date": end, "focus": "f"}
    if deload is not None:
        meso["deload_start"] = deload
    return meso


def _goal(target="2026-12-13"):
    return test_db.add_objective(title="Winter 10k", target_date=target, sport_type="running")


def _save(goal_id, *mesocycles):
    return test_db.save_macrocycle(
        objective_id=goal_id, strategy="s", goals_hash="g", constraints_hash="c",
        mesocycles=list(mesocycles),
    )


class RepairTest(unittest.TestCase):

    def test_a_moved_start_takes_the_first_day_it_overtook(self):
        race = _meso("Race", "2026-10-01", "2026-10-25")
        recovery = _meso("Recovery", "2026-10-25", "2026-11-01", deload="2026-10-25")
        repaired, notes = repair_mesocycle_contiguity([race, recovery])
        self.assertEqual(repaired[1]["start_date"], "2026-10-26")
        self.assertEqual(repaired[1]["deload_start"], "2026-10-26")
        self.assertEqual(len(notes), 1)
        self.assertIn("deload", notes[0])
        self.assertEqual(repair_mesocycle_contiguity(repaired), (repaired, []))

    def test_a_moved_start_leaves_a_first_day_it_did_not_reach(self):
        race = _meso("Race", "2026-10-01", "2026-10-25")
        build = _meso("Build", "2026-10-25", "2026-11-15", deload="2026-11-09")
        repaired, notes = repair_mesocycle_contiguity([race, build])
        self.assertEqual(repaired[1]["deload_start"], "2026-11-09")
        self.assertNotIn("deload", notes[0])

    def test_a_first_day_outside_its_mesocycle_is_dropped_and_named(self):
        for first_day, words in (("2026-11-10", "after the mesocycle"),
                                 ("2025-11-02", "before the mesocycle"),
                                 ("next week", "not a date"),
                                 ("2026-11-2", "not a date")):
            with self.subTest(first_day=first_day):
                block = _meso("HIIT Block 1", "2026-10-19", "2026-11-08", deload=first_day)
                repaired, notes = repair_mesocycle_contiguity([block])
                self.assertIsNone(repaired[0]["deload_start"])
                self.assertEqual(len(notes), 1)
                self.assertIn(f"dropped the deload of 'HIIT Block 1' (from {first_day})",
                              notes[0])
                self.assertIn(words, notes[0])

    def test_a_first_day_inside_is_left_alone(self):
        block = _meso("Build", "2026-10-19", "2026-11-08", deload="2026-11-02")
        self.assertEqual(repair_mesocycle_contiguity([block]), ([block], []))


class StoredDateTest(unittest.TestCase):

    def setUp(self):
        rebind_test_db(test_db)
        clear_all_tables(test_db)

    def test_the_date_reads_back_and_no_key_reads_as_none(self):
        macro_id = _save(_goal(), _meso("Build", "2026-10-19", "2026-11-08", deload="2026-11-02"),
                         _meso("Peak", "2026-11-09", "2026-12-13"))
        build, peak = test_db.get_mesocycles_for_macrocycle(macro_id)
        self.assertEqual(build["deload_start"], "2026-11-02")
        self.assertIsNone(peak["deload_start"])


class KeptMesocycleTest(unittest.TestCase):
    """A replan on a day the mesocycle under way is in or before its deload (§3.3)."""

    def setUp(self):
        rebind_test_db(test_db)
        clear_all_tables(test_db)
        self.goal_id = _goal()
        _save(self.goal_id, _meso("Build", "2026-10-19", "2026-11-08", deload="2026-11-02"),
              _meso("Peak", "2026-11-09", "2026-12-13"))

    def _replan(self, mesocycles):
        with patch("stamind.coach.engine.openrouter_client") as client:
            client.complete.return_value = {"strategy": "New", "mesocycles": mesocycles}
            proposal = coach_service.plan_generate(force=True, auto_apply=False)
        return proposal["mesocycles"], client.complete.call_args[0][0]

    def test_a_started_deload_is_copied_back_with_its_last_day(self):
        pin_clock(self, "2026-11-04")
        mesocycles, prompt = self._replan([
            _meso("Build", "2026-10-19", "2026-11-15", deload="2026-11-10"),
            _meso("Peak", "2026-11-16", "2026-12-13"),
        ])
        self.assertEqual(mesocycles[0]["deload_start"], "2026-11-02")
        self.assertEqual(mesocycles[0]["end_date"], "2026-11-08")
        self.assertEqual(mesocycles[1]["start_date"], "2026-11-16")
        self.assertIn("Deload: from 2026-11-02", prompt)

    def test_a_deload_still_ahead_stays_as_the_model_returned_it(self):
        pin_clock(self, "2026-10-22")
        mesocycles, _ = self._replan([
            _meso("Build", "2026-10-19", "2026-11-01", deload="2026-10-26"),
            _meso("Peak", "2026-11-02", "2026-12-13"),
        ])
        self.assertEqual(mesocycles[0]["deload_start"], "2026-10-26")
        self.assertEqual(mesocycles[0]["end_date"], "2026-11-01")

    def test_a_mesocycle_the_model_discarded_gets_nothing_back(self):
        pin_clock(self, "2026-11-04")
        mesocycles, _ = self._replan([_meso("New", "2026-11-04", "2026-12-13")])
        self.assertEqual(mesocycles, [_meso("New", "2026-11-04", "2026-12-13")])


class PromptLineTest(unittest.TestCase):

    def test_the_line_ends_with_the_deload_when_there_is_one(self):
        self.assertEqual(mesocycle_text(_meso("Build", "2026-10-19", "2026-11-08")),
                         "Build (2026-10-19 to 2026-11-08): f")
        self.assertEqual(
            mesocycle_text(_meso("Build", "2026-10-19", "2026-11-08", deload="2026-11-02")),
            "Build (2026-10-19 to 2026-11-08): f Deload 2026-11-02 to 2026-11-08.",
        )


class PlanDiffTest(unittest.TestCase):

    def test_a_moved_deload_is_a_change_of_its_mesocycle(self):
        old = _meso("Build", "2026-10-19", "2026-11-08", deload="2026-11-02")
        new = _meso("Build", "2026-10-19", "2026-11-08", deload="2026-11-03")
        entry = plan_versions.diff_mesocycles([old], [new])[0]
        self.assertEqual(entry["change"], "changed")
        self.assertEqual(entry["fields"], [
            {"field": "deload_start", "from": "2026-11-02", "to": "2026-11-03"},
        ])


class TerminalTest(unittest.TestCase):

    def setUp(self):
        rebind_test_db(test_db)
        clear_all_tables(test_db)
        pin_clock(self, "2026-10-26")
        self.goal_id = _goal()

    def _generate(self):
        """`plan generate` accepted with a `y`, the coach mocked; returns what it printed."""
        goal = test_db.get_objective(self.goal_id)
        with patch("stamind.runtime.garmin"), patch("stamind.runtime.coach_service") as coach:
            coach.plan_generate.return_value = {
                "strategy": "s", "reused": False, "goal": goal,
                "mesocycles": [_meso("Build", "2026-10-26", "2026-11-15", deload="2026-11-09"),
                               _meso("Peak", "2026-11-16", "2026-12-13")],
            }
            coach.plan_apply.return_value = self.goal_id
            _, stdout, _ = run_cli(["plan", "generate", "--goal", str(self.goal_id)], "y")
        return " ".join(stdout.split())

    def test_the_preview_prints_a_deload_and_says_when_there_is_none(self):
        stdout = self._generate()
        self.assertIn("Deload Mon 9 Nov to Sun 15 Nov (7 days)", stdout)
        self.assertIn("Deload: none", stdout)

    def test_sessions_past_today_are_named_with_the_range_that_rewrites_them(self):
        save_workout(test_db, date="2026-11-15", sport_type="running", title="Long run")
        stdout = self._generate()
        self.assertIn("Sessions are written up to Sun 15 Nov under the old plan.", stdout)
        self.assertIn("workout generate -d today..2026-11-15", stdout)

    def test_no_session_past_today_keeps_the_bare_command(self):
        save_workout(test_db, date="2026-10-26", sport_type="running", title="Easy run")
        stdout = self._generate()
        self.assertIn("workout generate", stdout)
        self.assertIn("to schedule workouts based on this plan", stdout)
        self.assertNotIn(" -d today", stdout)

    def test_plan_show_prints_the_deload_of_a_mesocycle_that_has_one(self):
        _save(self.goal_id, _meso("Build", "2026-10-26", "2026-11-15", deload="2026-11-09"),
              _meso("Peak", "2026-11-16", "2026-12-13"))
        _, stdout, _ = run_cli(["plan", "show"])
        self.assertIn("Deload Mon 9 Nov to Sun 15 Nov (7 days)", stdout)
        self.assertEqual(stdout.count("Deload"), 1)


class CalendarTest(unittest.TestCase):

    def setUp(self):
        rebind_test_db(test_db)
        clear_all_tables(test_db)
        pin_clock(self, "2026-10-26")
        _save(_goal(), _meso("Build", "2026-10-19", "2026-11-08", deload="2026-11-02"),
              _meso("Peak", "2026-11-09", "2026-12-13"))
        self.cal = calendar_days.gather(test_db, "2026-10-19", "2026-11-30", "2026-10-26")

    def test_sm_calendar_prints_the_line_under_the_week_the_deload_starts_in(self):
        lines = calendar_grid.month_lines(self.cal, 2026, 11)
        deload = [i for i, line in enumerate(lines) if "── Deload" in line]
        self.assertEqual(len(deload), 1)
        self.assertIn("── Deload Mon 2 Nov to Sun 8 Nov", lines[deload[0]])
        # November's first week holds only Sunday 1, then two lines for the week of the 2nd.
        self.assertTrue(lines[deload[0] - 2].lstrip().startswith("2"))
        self.assertEqual(
            [line for line in calendar_grid.month_lines(self.cal, 2026, 10) if "Deload" in line],
            [],
        )

    def test_the_snapshot_carries_d_only_for_a_mesocycle_with_a_deload(self):
        meso = calendar_page.header(self.cal, datetime(2026, 10, 26, 7, 0))["meso"]
        self.assertEqual(meso[0]["d"], "2026-11-02")
        self.assertNotIn("d", meso[1])


if __name__ == "__main__":
    unittest.main()
