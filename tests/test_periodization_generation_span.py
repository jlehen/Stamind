"""The span `workout generate` writes: the selectors pick both of its ends.
"""
import argparse
import os
import unittest
from datetime import datetime, timedelta, timezone
from unittest.mock import patch

from tests.helpers import clear_all_tables, rebind_test_db, save_workout
from tests import test_db_path

TEST_DB_PATH = test_db_path("test_periodization_generation_span.db")


def _days_out(n: int) -> str:
    return (datetime.now(timezone.utc).date() + timedelta(days=n)).isoformat()


# Fixtures ride on today rather than on fixed dates; test_periodization.py says why.

from trainmate.cli.workouts import generate as generate_cli
from trainmate.config import config
from trainmate.cli.selectors import IdRange
from trainmate.db import Database

test_db = Database(db_path=TEST_DB_PATH)
rebind_test_db(test_db)

from trainmate.coach.service import coach_service


class TestGenerationSpanIsBounded(unittest.TestCase):
    """The selectors pick the whole span `workout generate` writes, both ends of it
    (DESIGN_cli_selectors.md §8). A bounded regeneration rebuilds the days it was given
    and leaves every other day of the plan exactly as it was."""

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
        obj_id = test_db.add_objective(
            title="Autumn Marathon", target_date=_days_out(90), sport_type="running",
        )
        test_db.save_macrocycle(
            objective_id=obj_id, strategy="build", goals_hash="g", constraints_hash="c",
            mesocycles=[{"name": "Base", "start_date": _days_out(0),
                         "end_date": _days_out(90), "focus": "aerobic"}],
        )

    @staticmethod
    def _response(*dates):
        return {
            "reasoning": "why",
            "workouts": [
                {"date": d, "sport_type": "running", "title": f"Run {d}",
                 "description": f"[Run {d}]\n30 mins"}
                for d in dates
            ],
        }

    @staticmethod
    def _existing(date_str, title):
        save_workout(
            test_db, date=date_str, sport_type="running", title=title,
            description=f"[{title}]\n30 mins", duration_minutes=30,
        )

    @patch("trainmate.runtime.calendar_syncer")
    @patch("trainmate.coach.engine.openrouter_client")
    def test_the_span_opens_where_the_caller_put_it(self, mock_client, _mock_calendar):
        """A mesocycle that starts next month is generated from its own first day: `-m` names
        a span, not a horizon reaching back to today."""
        mock_client.complete.return_value = self._response(_days_out(31))
        proposal = coach_service.workout_generate(
            start_date=_days_out(30), end_date=_days_out(40)
        )

        self.assertEqual(proposal.gen_start, _days_out(30))
        self.assertEqual(proposal.gen_end, _days_out(40))
        # The model is told which day to start on, so it does not lay sessions from today.
        prompt = "".join(str(a) for a in mock_client.complete.call_args.args)
        self.assertIn(f"starting from {_days_out(30)}", prompt)

    @patch("trainmate.runtime.calendar_syncer")
    @patch("trainmate.coach.engine.openrouter_client")
    def test_the_span_never_opens_in_the_past(self, mock_client, _mock_calendar):
        """A mesocycle already under way is regenerated from today: yesterday is history."""
        mock_client.complete.return_value = self._response(_days_out(1))
        proposal = coach_service.workout_generate(
            start_date=_days_out(-10), end_date=_days_out(10)
        )
        self.assertEqual(proposal.gen_start, _days_out(0))
        self.assertEqual(proposal.gen_end, _days_out(10))

    @patch("trainmate.runtime.calendar_syncer")
    @patch("trainmate.coach.engine.openrouter_client")
    def test_only_the_sessions_inside_the_span_are_displaced(
        self, mock_client, _mock_calendar
    ):
        """The days either side of the span keep the sessions they already have — before
        §8 the rebuild ran from its start with no end and cancelled all of them."""
        self._existing(_days_out(2), "Before")
        self._existing(_days_out(35), "Inside")
        self._existing(_days_out(50), "After")

        mock_client.complete.return_value = self._response(_days_out(31))
        proposal = coach_service.workout_generate(
            start_date=_days_out(30), end_date=_days_out(40)
        )
        self.assertEqual([w["title"] for w in proposal.displaced], ["Inside"])

        coach_service.workout_generate_apply(proposal)
        live = {w["title"] for w in test_db.get_workouts(start_date=_days_out(0))}
        self.assertIn("Before", live)
        self.assertIn("After", live)
        # A session the rebuilt span no longer holds is still cancelled inside it.
        self.assertNotIn("Inside", live)
        self.assertIn(f"Run {_days_out(31)}", live)

    @patch("trainmate.runtime.calendar_syncer")
    @patch("trainmate.coach.engine.openrouter_client")
    def test_an_ordinary_session_written_over_a_test_is_not_a_test(
        self, mock_client, _mock_calendar
    ):
        """The append carries `benchmark_type` forward on a same-slot rewrite, so a
        regeneration that replaces a scheduled FTP test with an easy run must blank the
        flag the way adapt does (DESIGN_benchmark_workouts.md §4.2), or the run is
        silently a test."""
        save_workout(
            test_db, date=_days_out(31), sport_type="running", title="LT test",
            description="[LT test]\n30 mins", duration_minutes=30,
            benchmark_type="lthr_30min",
        )
        mock_client.complete.return_value = self._response(_days_out(31))
        proposal = coach_service.workout_generate(
            start_date=_days_out(30), end_date=_days_out(40)
        )
        coach_service.workout_generate_apply(proposal)

        written = test_db.get_workout(_days_out(31), "running")
        self.assertEqual(written["title"], f"Run {_days_out(31)}")
        self.assertIsNone(written["benchmark_type"])

    def test_a_bare_span_opens_after_the_generated_schedule_stops(self):
        """Generation carries the schedule on rather than rewriting days it already
        covers — a run that rewrote them would leave the runway nudge standing (§8)."""
        self._existing(_days_out(3), "Planned")
        self.assertEqual(
            generate_cli._resolve_span(argparse.Namespace()),
            (_days_out(4), _days_out(4 + config.workout_generation_span_days - 1)),
        )

    def test_a_bare_span_opens_today_once_the_schedule_has_run_out(self):
        self._existing(_days_out(-3), "History")
        self.assertEqual(
            generate_cli._resolve_span(argparse.Namespace()),
            (_days_out(0), _days_out(config.workout_generation_span_days - 1)),
        )

    def test_a_bare_span_opens_today_with_nothing_generated_yet(self):
        self.assertEqual(
            generate_cli._resolve_span(argparse.Namespace()),
            (_days_out(0), _days_out(config.workout_generation_span_days - 1)),
        )

    def test_a_plan_covered_to_its_last_day_has_nothing_left_to_generate(self):
        """Carrying on past the plan would write days no mesocycle governs — the plan-cliff
        state, whose fix is a new goal rather than another span."""
        self._existing(_days_out(90), "Final")
        self.assertIsNone(generate_cli._resolve_span(argparse.Namespace()))

    def test_a_selector_still_opens_today(self):
        """Only the unselected case carries on. A forward-direction selector fills its own
        start in `resolve_window`, so `-m ..<id>` keeps meaning today through that mesocycle."""
        self._existing(_days_out(3), "Planned")
        meso_id = test_db.get_mesocycles_for_macrocycle(
            test_db.get_governing_macrocycle()["id"]
        )[0]["id"]
        args = argparse.Namespace(
            meso_range=IdRange(start=None, end=meso_id),
            _selector_policy=("forward", None, 7),
        )
        self.assertEqual(
            generate_cli._resolve_span(args), (_days_out(0), _days_out(90)),
        )

    @patch("trainmate.runtime.calendar_syncer")
    @patch("trainmate.coach.engine.openrouter_client")
    def test_no_span_at_all_is_the_config_horizon_from_today(
        self, mock_client, _mock_calendar
    ):
        """With no selector the span is still bounded at both ends, so the default run
        behaves like every other one."""
        mock_client.complete.return_value = self._response(_days_out(1))
        proposal = coach_service.workout_generate()
        self.assertEqual(proposal.gen_start, _days_out(0))
        self.assertEqual(
            proposal.gen_end, _days_out(config.workout_generation_span_days - 1)
        )


if __name__ == "__main__":
    unittest.main()
