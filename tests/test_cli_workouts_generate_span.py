"""Which days `workout generate` writes: the selectors that name both ends of
the span, and the plan that settles a date two of them cover.
"""
import os
import unittest
from datetime import datetime, timedelta, timezone
from unittest.mock import patch

from tests.helpers import clear_all_tables, run_cli, rebind_test_db, save_workout
from stamind.clock import fmt_date
from stamind.coach.proposals import GenerateProposal
from tests import test_db_path

TEST_DB_PATH = test_db_path("test_cli_workouts_generate_span.db")

from stamind.db import Database

test_db = Database(db_path=TEST_DB_PATH)
rebind_test_db(test_db)

PROPOSED_DATE = (datetime.now(timezone.utc).date() + timedelta(days=1)).strftime("%Y-%m-%d")


def _proposal(displaced=()):
    """One proposed session, as `workout generate` hands it to the CLI for preview."""
    today = datetime.now(timezone.utc).date()
    return GenerateProposal(
        reasoning="Reasoning",
        workouts=({
            "date": PROPOSED_DATE, "sport_type": "running", "title": "Base Run",
            "description": "45 min easy", "duration_minutes": 45, "tss": 40, "rpe": 4,
            "planned_zone_currency": "hr", "planned_zone_sec": [600, 2100, 0, 0, 0],
        },),
        displaced=tuple(displaced),
        gen_start=today.strftime("%Y-%m-%d"),
        gen_end=(today + timedelta(days=27)).strftime("%Y-%m-%d"),
    )


class TestCliWorkoutsGenerateSpan(unittest.TestCase):
    """`-g` is a goal's whole span and `-m` a mesocycle's own first day, a span
    entirely behind us is refused, and `-M ID` settles which plan to follow."""

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

    def run_cli(self, args, input_value="n"):
        return run_cli(args, input_value)

    def _goal_with_plan(self, target_days_out: int, mesocycle_days_out: int = 20):
        today_date = datetime.now(timezone.utc).date()
        goal_id = test_db.add_objective(
            title="Autumn Marathon",
            target_date=(
                today_date + timedelta(days=target_days_out)
            ).strftime("%Y-%m-%d"),
            sport_type="running", status="active",
        )
        macro_id = test_db.save_macrocycle(
            objective_id=goal_id, strategy="Build", goals_hash="g", constraints_hash="c",
            mesocycles=[{
                "name": "Base",
                "start_date": today_date.strftime("%Y-%m-%d"),
                "end_date": (
                    today_date + timedelta(days=mesocycle_days_out)
                ).strftime("%Y-%m-%d"),
                "focus": "Aerobic",
            }],
        )
        return goal_id, macro_id

    @patch("stamind.cli.workouts.generate.ensure_recent_data")
    @patch("stamind.runtime.prompt")
    @patch("stamind.runtime.coach_service")
    def test_generate_g_is_the_span_not_a_plan_selector(
        self, mock_coach, mock_prompt, _ensure
    ):
        """`-g` reads like it does everywhere else in the grammar: a goal's whole plan
        span, its plan start through its target date. It replaced `--until-goal`, and it
        no longer picks which plan applies — the dates do that (DESIGN_cli_selectors.md
        §8)."""
        mock_coach.workout_generate.return_value = _proposal()
        mock_coach.config_changed.return_value = None
        goal_id, _ = self._goal_with_plan(target_days_out=100)
        target_date = test_db.get_objective(goal_id)["target_date"]
        today = datetime.now(timezone.utc).date().strftime("%Y-%m-%d")

        exit_code, _, _ = self.run_cli(["workout", "generate", "-g", str(goal_id), "-f"])
        self.assertEqual(exit_code, 0)
        kwargs = mock_coach.workout_generate.call_args.kwargs
        self.assertEqual(kwargs["end_date"], target_date)
        # This plan starts today, so its span does too — and the START is now passed
        # through rather than assumed.
        self.assertEqual(kwargs["start_date"], today)

        # Bare -g is the active goal, the same shorthand every other command gives it.
        mock_coach.workout_generate.reset_mock()
        exit_code, _, _ = self.run_cli(["workout", "generate", "-g", "-f"])
        self.assertEqual(exit_code, 0)
        self.assertEqual(
            mock_coach.workout_generate.call_args.kwargs["end_date"], target_date
        )

        # The retired flag is gone rather than silently ignored.
        exit_code, _, stderr = self.run_cli(["workout", "generate", "--until-goal"])
        self.assertNotEqual(exit_code, 0)
        self.assertIn("unrecognized arguments", stderr)

    def _two_mesocycle_plan(self):
        """A plan whose second mesocycle starts three weeks out, so a `-m` span on it opens
        well after today."""
        today_date = datetime.now(timezone.utc).date()

        def out(n):
            return (today_date + timedelta(days=n)).strftime("%Y-%m-%d")

        goal_id = test_db.add_objective(
            title="Autumn Marathon", target_date=out(90), sport_type="running",
            status="active",
        )
        test_db.save_macrocycle(
            objective_id=goal_id, strategy="Build", goals_hash="g", constraints_hash="c",
            mesocycles=[
                {"name": "Base", "start_date": out(0), "end_date": out(20),
                 "focus": "Aerobic"},
                {"name": "Build", "start_date": out(21), "end_date": out(45),
                 "focus": "Threshold"},
            ],
        )
        mesocycles = test_db.get_mesocycles_for_macrocycle(
            test_db.get_macrocycle_for_objective(goal_id)["id"]
        )
        return {b["name"]: b for b in mesocycles}

    @patch("stamind.cli.workouts.generate.ensure_recent_data")
    @patch("stamind.runtime.prompt")
    @patch("stamind.runtime.coach_service")
    def test_generate_m_writes_the_mesocycle_from_its_own_first_day(
        self, mock_coach, mock_prompt, _ensure
    ):
        """`-m 5` generates mesocycle 5 and nothing else — both ends come from the mesocycle,
        where the span used to reach back to today (DESIGN_cli_selectors.md §8)."""
        mock_coach.workout_generate.return_value = _proposal()
        mock_coach.config_changed.return_value = None
        mesocycles = self._two_mesocycle_plan()
        build = mesocycles["Build"]

        exit_code, _, _ = self.run_cli(
            ["workout", "generate", "-m", str(build["id"]), "-f"]
        )
        self.assertEqual(exit_code, 0)
        kwargs = mock_coach.workout_generate.call_args.kwargs
        self.assertEqual(kwargs["start_date"], build["start_date"])
        self.assertEqual(kwargs["end_date"], build["end_date"])

        # A plain date range is read the same way: both ends, not just the far one.
        mock_coach.workout_generate.reset_mock()
        exit_code, _, _ = self.run_cli(
            ["workout", "generate", "-d", f"{build['start_date']}..{build['end_date']}",
             "-f"]
        )
        self.assertEqual(exit_code, 0)
        kwargs = mock_coach.workout_generate.call_args.kwargs
        self.assertEqual(kwargs["start_date"], build["start_date"])
        self.assertEqual(kwargs["end_date"], build["end_date"])

    @patch("stamind.cli.workouts.generate.ensure_recent_data")
    @patch("stamind.runtime.prompt")
    @patch("stamind.runtime.coach_service")
    def test_generate_warns_only_when_the_old_reading_would_differ(
        self, mock_coach, mock_prompt, _ensure
    ):
        """The span change is transitional, so the run says which days it no longer
        touches — and stays quiet when the two readings agree."""
        mock_coach.workout_generate.return_value = _proposal()
        mock_coach.config_changed.return_value = None
        mesocycles = self._two_mesocycle_plan()
        base, build = mesocycles["Base"], mesocycles["Build"]

        # The notice is wrapped for the terminal; compare on a single logical line.
        def _said(argv):
            exit_code, stdout, _ = self.run_cli(argv)
            self.assertEqual(exit_code, 0)
            return " ".join(stdout.split())

        # A span opening later than today: the days before it are no longer rebuilt.
        said = _said(["workout", "generate", "-m", str(build["id"]), "-f"])
        self.assertIn("now rebuilds a bounded span", said)
        self.assertIn(fmt_date(build["start_date"]), said)
        self.assertIn("keeps the sessions it already has", said)
        self.assertIn("to rebuild from today again", said)

        # A session past the span's end: it is no longer cancelled either.
        save_workout(test_db,
            date=build["end_date"], sport_type="running", title="Later",
            description="30 min",
        )
        said = _said(["workout", "generate", "-m", str(base["id"]), "-f"])
        self.assertIn("keep their place instead of being cancelled", said)

        # Nothing before the span and nothing after it — no warning to give.
        said = _said(["workout", "generate", "-g", "-f"])
        self.assertNotIn("now rebuilds a bounded span", said)

    @patch("stamind.cli.workouts.generate.ensure_recent_data")
    @patch("stamind.runtime.prompt")
    @patch("stamind.runtime.coach_service")
    def test_generate_refuses_a_span_that_is_entirely_behind_us(
        self, mock_coach, mock_prompt, _ensure
    ):
        """A mesocycle that has already run is history. Now that a selector names both ends,
        naming a finished one has to be refused rather than quietly regenerating today."""
        mock_coach.config_changed.return_value = None
        today = datetime.now(timezone.utc).date()

        def out(n):
            return (today + timedelta(days=n)).strftime("%Y-%m-%d")

        goal_id = test_db.add_objective(
            title="Past 10k", target_date=out(-5), sport_type="running", status="active",
        )
        macro_id = test_db.save_macrocycle(
            objective_id=goal_id, strategy="Build", goals_hash="g", constraints_hash="c",
            mesocycles=[{"name": "Done", "start_date": out(-40), "end_date": out(-10),
                         "focus": "Aerobic"}],
        )
        done = test_db.get_mesocycles_for_macrocycle(macro_id)[0]

        exit_code, stdout, _ = self.run_cli(
            ["workout", "generate", "-m", str(done["id"]), "-f"]
        )
        self.assertEqual(exit_code, 0)
        self.assertIn("before today", " ".join(stdout.split()))
        mock_coach.workout_generate.assert_not_called()

    @patch("stamind.cli.workouts.generate.ensure_recent_data")
    @patch("stamind.runtime.prompt")
    @patch("stamind.runtime.coach_service")
    def test_generate_passes_a_named_plan_through_as_the_tiebreaker(
        self, mock_coach, mock_prompt, _ensure
    ):
        """`-M ID` bounds the horizon *and* settles which plan to follow where two cover
        the same days; a bare -M names no single winner, so it does not."""
        mock_coach.workout_generate.return_value = _proposal()
        mock_coach.config_changed.return_value = None
        _, macro_id = self._goal_with_plan(target_days_out=100)

        exit_code, _, _ = self.run_cli(
            ["workout", "generate", "-M", str(macro_id), "-f"]
        )
        self.assertEqual(exit_code, 0)
        self.assertEqual(
            mock_coach.workout_generate.call_args.kwargs["prefer_macro_id"], macro_id
        )

        mock_coach.workout_generate.reset_mock()
        exit_code, _, _ = self.run_cli(["workout", "generate", "-M", "-f"])
        self.assertEqual(exit_code, 0)
        self.assertIsNone(
            mock_coach.workout_generate.call_args.kwargs["prefer_macro_id"]
        )
