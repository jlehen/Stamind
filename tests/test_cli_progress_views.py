"""`sm progress` and its four words (DESIGN_progress_page.md §6): a bare run is the Fitness
view with its flags, `mesocycles` lists every record newest first under the mesocycle under
way, and `intensity SPORT` is what `progress SPORT` printed. The Weeks view is
tests/test_written_week.py, beside its fixtures.

It is Thursday 12 November 2026.
"""
import os
import unittest
from unittest.mock import patch

from tests import test_db_path
from tests.helpers import clear_all_tables, pin_clock, rebind_test_db, run_cli

import stamind_cli
from stamind.cli.progress import run_progress
from stamind.config import config
from stamind.db import Database
from stamind.db.retrospectives import FINISHED, MESOCYCLE, PLAN, REPLACED

TEST_DB_PATH = test_db_path("test_cli_progress_views.db")
test_db = Database(db_path=TEST_DB_PATH)
rebind_test_db(test_db)

TODAY = "2026-11-12"
NUMBERS = {"sessions_done": 5, "sessions_planned": 9, "load_done": 237.0,
           "load_planned": 275.0, "duration_sec": 21060.0, "fitness_start": 16.2,
           "fitness_end": 18.4, "benchmarks": []}


def _progress(*argv):
    code, out, _ = run_cli(["progress", *argv, "--no-pull"])
    return code, out


class _Case(unittest.TestCase):

    def setUp(self):
        rebind_test_db(test_db)
        clear_all_tables(test_db)
        pin_clock(self, TODAY)
        os.environ.pop("STAMIND_RENDER", None)


class BareIsFitnessTest(_Case):

    def test_a_bare_run_prints_the_fitness_view(self):
        bare_code, bare = _progress()
        code, fitness = _progress("fitness")
        self.assertEqual((bare_code, code), (0, 0))
        self.assertIn("FORM today", bare)
        self.assertEqual(bare, fitness)

    def test_a_bare_run_takes_the_fitness_flags(self):
        parser, _ = stamind_cli.build_parser()
        args = parser.parse_args(["progress", "-w", "12", "--chart", "--explain"])
        self.assertIs(args.func, run_progress)
        self.assertEqual((args.weeks, args.chart, args.explain), (12, True, True))

    def test_the_old_spellings_are_gone(self):
        parser, _ = stamind_cli.build_parser()
        with patch("sys.stderr"):
            for argv in (["progress", "-z"], ["progress", "running"]):
                with self.subTest(argv=argv), self.assertRaises(SystemExit):
                    parser.parse_args(argv)


class MesocyclesTest(_Case):
    """Every record newest first, a plan's above the mesocycles it closes; the one under way
    from the plan that governs today (§3.3)."""

    def setUp(self):
        super().setUp()
        goal = test_db.add_objective(title="Spring 10k", target_date="2026-12-20",
                                     sport_type="running")
        test_db.save_macrocycle(
            objective_id=goal, strategy="s", goals_hash="h", constraints_hash="c",
            mesocycles=[{"name": "Build", "start_date": "2026-11-04",
                         "end_date": "2026-12-20", "focus": "Speed."}],
        )
        old = test_db.add_objective(title="Autumn race", target_date="2026-11-03",
                                    sport_type="running")
        first = test_db.add_retrospective(old, MESOCYCLE, "Base", "2026-10-05",
                                          "2026-10-24", FINISHED, "Volume.")
        test_db.write_retrospective(first, NUMBERS, "The athlete completed 5 of 9.",
                                    "You kept your runs going.")
        test_db.set_retrospective_words(first, "felt fresh")
        test_db.add_retrospective(old, MESOCYCLE, "Race-Specific Sharpening", "2026-10-25",
                                  "2026-11-03", REPLACED, "Sharpen.")
        test_db.add_retrospective(old, PLAN, "Autumn race", "2026-10-05", "2026-11-03",
                                  FINISHED, "s")

    def test_newest_first_under_the_mesocycle_under_way(self):
        code, out, _ = run_cli(["progress", "mesocycles"])
        self.assertEqual(code, 0)
        order = [out.index(name) for name in (
            "Build, Wed 4 Nov – Sun 20 Dec (under way)",
            'Plan toward "Autumn race", Mon 5 Oct – Tue 3 Nov (finished)',
            "Race-Specific Sharpening, Sun 25 Oct – Tue 3 Nov (cut short by a new plan)",
            "Base, Mon 5 Oct – Sat 24 Oct (finished)",
        )]
        self.assertEqual(order, sorted(order))

    def test_a_written_record_in_full_and_a_blank_one_not_written_yet(self):
        out = run_cli(["progress", "mesocycles"])[1]
        self.assertIn("Sessions 5 of 9 · load 237 of 275 TSS", out)
        self.assertIn("The athlete completed 5 of 9.", out)
        self.assertIn('Athlete: "felt fresh"', out)
        self.assertIn('Said to the athlete: "You kept your runs going."', out)
        self.assertEqual(out.count("not written yet"), 2)


class IntensityTest(_Case):
    """`progress intensity running` is the old `progress running`: the zone table alone."""

    def test_the_named_sports_zone_table_without_the_load_table(self):
        for n, day in enumerate(("2026-11-02", "2026-11-05", "2026-11-09")):
            test_db.save_completed_activity(
                activity_id=f"run-{n}", date=day, start_time=f"{day}T07:00:00",
                activity_name="Run", activity_type="running", duration_sec=3600.0,
                distance_km=10.0, elevation_gain_m=0.0, avg_hr=140, max_hr=160, rpe=None,
                tss=50.0, zone1_sec=600, zone2_sec=2400, zone3_sec=600,
            )
        with patch.dict(config.data, {"user_profile": {"sport_preferences": ["running"]}}):
            code, out = _progress("intensity", "running")
        self.assertEqual(code, 0)
        self.assertIn("ZONES running [HR", out)
        self.assertNotIn("FORM today", out)


if __name__ == "__main__":
    unittest.main()
