"""`workout generate` reads its periodization off the dates it is writing, not
off today.
"""
import io
import os
import unittest
from datetime import datetime, timedelta, timezone
from unittest.mock import patch

from tests.helpers import clear_all_tables, rebind_test_db
from tests import test_db_path

TEST_DB_PATH = test_db_path("test_periodization_date_keyed.db")


def _days_out(n: int) -> str:
    return (datetime.now(timezone.utc).date() + timedelta(days=n)).isoformat()


# Fixtures ride on today rather than on fixed dates; test_periodization.py says why.

from stamind.db import Database

test_db = Database(db_path=TEST_DB_PATH)
rebind_test_db(test_db)

from stamind.coach.service import coach_service


def _generate_workouts(**kwargs):
    """`workout generate` end to end: propose, then accept, as the CLI does on a `y`.

    Generation is two halves so the athlete reads the plan before it is written; tests
    exercising the write want both, and the proposal alone is called directly where only
    the refusal or the prompt is under test."""
    proposal = coach_service.workout_generate(**kwargs)
    return proposal.reasoning, coach_service.workout_generate_apply(proposal)


class TestDateKeyedGeneration(unittest.TestCase):
    """`workout generate` reads its periodization off the dates it is writing, not off a
    goal the caller names (DESIGN_cli_selectors.md §8). The goal used to be an
    indirection to the macrocycle and nothing more, which meant the earliest goal's plan
    shaped the sessions even when a different plan governed the days in question."""

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

    def _goal(self, title, target_date):
        return test_db.add_objective(
            title=title, target_date=target_date, sport_type="running",
        )

    def _plan(self, obj_id, strategy, mesocycles):
        return test_db.save_macrocycle(
            objective_id=obj_id, strategy=strategy, goals_hash="g", constraints_hash="c",
            mesocycles=[{"name": name, "start_date": start, "end_date": end,
                         "focus": f"focus of {name}"} for name, start, end in mesocycles],
        )

    @staticmethod
    def _one_session_response(date_str):
        return {
            "reasoning": "why",
            "workouts": [{
                "date": date_str, "sport_type": "running",
                "title": "Run", "description": "[Run]\n30 mins",
            }],
        }

    # --- the DB rule on its own ---------------------------------------------------

    def test_sequential_plans_both_govern_a_long_window(self):
        """A horizon can legitimately run out of one goal's last mesocycle into the next
        goal's first, so neither plan is dropped."""
        first = self._goal("Spring 10k", _days_out(30))
        self._plan(first, "spring", [("Base", _days_out(0), _days_out(30))])
        second = self._goal("Autumn Marathon", _days_out(90))
        self._plan(second, "autumn", [("Build", _days_out(31), _days_out(90))])

        mesocycles, dropped = test_db.get_governing_mesocycles(_days_out(0), _days_out(60))
        self.assertEqual([b["name"] for b in mesocycles], ["Base", "Build"])
        self.assertEqual(dropped, [])

    def test_plans_covering_the_same_days_are_settled_by_recency(self):
        """Two plans cannot both be followed on one day; the more recently generated one
        wins, the same tiebreak get_periodization_ids_for_date makes."""
        first = self._goal("Spring 10k", _days_out(40))
        old = self._plan(first, "spring", [("Base", _days_out(0), _days_out(40))])
        second = self._goal("Autumn Marathon", _days_out(90))
        new = self._plan(second, "autumn", [("Build", _days_out(0), _days_out(90))])

        mesocycles, dropped = test_db.get_governing_mesocycles(_days_out(0), _days_out(30))
        self.assertEqual([b["macrocycle_id"] for b in mesocycles], [new])
        self.assertEqual(dropped, [old])

        # Naming a plan settles it the other way instead.
        mesocycles, dropped = test_db.get_governing_mesocycles(
            _days_out(0), _days_out(30), prefer_macro_id=old
        )
        self.assertEqual([b["macrocycle_id"] for b in mesocycles], [old])
        self.assertEqual(dropped, [new])

    def test_a_window_no_mesocycle_covers_falls_back_rather_than_answering_empty(self):
        """A plan that has run out still answers, so generation reports "no strategy"
        only when there is genuinely none."""
        goal = self._goal("Spring 10k", _days_out(-5))
        self._plan(goal, "spring", [("Base", _days_out(-40), _days_out(-10))])

        mesocycles, dropped = test_db.get_governing_mesocycles(_days_out(0), _days_out(27))
        self.assertEqual([b["name"] for b in mesocycles], ["Base"])
        self.assertEqual(dropped, [])

        clear_all_tables(test_db)
        self.assertEqual(
            test_db.get_governing_mesocycles(_days_out(0), _days_out(27)), ([], [])
        )

    def test_the_strict_readers_answer_only_with_mesocycles_that_cover_their_target(self):
        """The strict question, for every caller that goes on to treat the answer as
        covering what it asked about — a mesocycle that does not contain the target is not
        something to name (DESIGN_constraint_honoring.md §4.1). The window form is
        internal to get_governing_mesocycles; the single-date form is the public reader
        the constraint messages use.
        """
        goal = self._goal("Spring 10k", _days_out(-5))
        self._plan(goal, "spring", [("Base", _days_out(-40), _days_out(-10))])

        self.assertEqual(
            test_db._get_covering_mesocycles(_days_out(0), _days_out(27)),
            ([], []),
        )
        self.assertIsNone(test_db.get_covering_mesocycle(_days_out(0)))
        # The governing readers still fall back, because `generate` depends on it.
        self.assertIsNotNone(test_db.get_active_mesocycle(_days_out(0)))
        # And a window a mesocycle really does cover answers with it through either reader.
        covered = _days_out(-20)
        self.assertEqual(
            [b["name"] for b in test_db.get_governing_mesocycles(covered, covered)[0]],
            ["Base"],
        )

    def test_single_date_readers_prefer_the_newest_plan_on_overlapping_days(self):
        """Overlapping plans are settled by recency in every reader, so the mesocycle a
        message names and the mesocycle a workout is stamped with are the same one."""
        first = self._goal("Spring 10k", _days_out(40))
        self._plan(first, "spring", [("Base", _days_out(0), _days_out(40))])
        second = self._goal("Autumn Marathon", _days_out(90))
        new = self._plan(second, "autumn", [("Build", _days_out(0), _days_out(90))])

        covering = test_db.get_covering_mesocycle(_days_out(10))
        self.assertEqual(covering["macrocycle_id"], new)
        self.assertEqual(test_db.get_active_mesocycle(_days_out(10))["id"], covering["id"])
        ids = test_db.get_periodization_ids_for_date(_days_out(10))
        self.assertEqual(ids[1], new)
        self.assertEqual(ids[2], covering["id"])

    # --- what generation actually does with it ------------------------------------

    @patch("stamind.runtime.calendar_syncer")
    @patch("stamind.coach.engine.openrouter_client")
    def test_the_plan_covering_today_shapes_the_sessions_not_the_earliest_goal(
        self, mock_client, _mock_calendar
    ):
        """The regression the goal indirection caused: the nearest goal's plan was used
        even when its mesocycles were long finished and another plan covered today."""
        stale = self._goal("Club 10k", _days_out(20))
        self._plan(stale, "STALE STRATEGY", [("Old", _days_out(-60), _days_out(-30))])
        live = self._goal("Autumn Marathon", _days_out(90))
        self._plan(live, "LIVE STRATEGY", [("Build", _days_out(-1), _days_out(60))])

        mock_client.complete.return_value = self._one_session_response(_days_out(1))
        _generate_workouts()

        system_prompt = mock_client.complete.call_args.args[0]
        self.assertIn("LIVE STRATEGY", system_prompt)
        self.assertNotIn("STALE STRATEGY", system_prompt)
        # The covered mesocycle is marked, so the model no longer has to infer which mesocycles
        # the span falls in from the dates alone.
        self.assertIn("> Build", system_prompt)

    @patch("stamind.runtime.calendar_syncer")
    @patch("stamind.coach.engine.openrouter_client")
    def test_a_span_crossing_two_plans_tags_each_session_with_its_own(
        self, mock_client, _mock_calendar
    ):
        """`plan rollback` accounting keys off macrocycle_id, so a session belongs to the
        plan governing its date — not to one id stamped across the whole batch."""
        first = self._goal("Spring 10k", _days_out(20))
        early = self._plan(first, "spring", [("Base", _days_out(0), _days_out(20))])
        second = self._goal("Autumn Marathon", _days_out(90))
        late = self._plan(second, "autumn", [("Build", _days_out(21), _days_out(90))])

        mock_client.complete.return_value = {
            "reasoning": "why",
            "workouts": [
                {"date": _days_out(5), "sport_type": "running",
                 "title": "Early", "description": "[Early]\n30 mins"},
                {"date": _days_out(40), "sport_type": "running",
                 "title": "Late", "description": "[Late]\n30 mins"},
            ],
        }
        _, workouts = _generate_workouts(end_date=_days_out(60))

        by_title = {w["title"]: w for w in workouts}
        self.assertEqual(by_title["Early"]["macrocycle_id"], early)
        self.assertEqual(by_title["Late"]["macrocycle_id"], late)
        # Both strategies reached the prompt: the span is genuinely governed by both.
        system_prompt = mock_client.complete.call_args.args[0]
        self.assertIn("spring", system_prompt)
        self.assertIn("autumn", system_prompt)

    @patch("stamind.runtime.calendar_syncer")
    @patch("stamind.coach.engine.openrouter_client")
    def test_a_horizon_past_the_last_mesocycle_says_so(self, mock_client, _mock_calendar):
        """Days past the plan's end have no mesocycle to follow — a date-keyed view can see
        that and say it, where the goal-keyed one could not."""
        goal = self._goal("Autumn Marathon", _days_out(90))
        self._plan(goal, "autumn", [("Base", _days_out(0), _days_out(20))])

        mock_client.complete.return_value = self._one_session_response(_days_out(1))
        with patch("sys.stdout", new_callable=io.StringIO) as out:
            coach_service.workout_generate(end_date=_days_out(60))
        self.assertIn("The plan runs out on", out.getvalue())
        self.assertIn(_days_out(20), out.getvalue())

    @patch("stamind.runtime.calendar_syncer")
    @patch("stamind.coach.engine.openrouter_client")
    def test_no_plan_at_all_still_names_plan_generate(self, mock_client, _mock_calendar):
        self._goal("Autumn Marathon", _days_out(90))
        with self.assertRaises(ValueError) as ctx:
            coach_service.workout_generate()
        self.assertIn("plan generate", str(ctx.exception))
        mock_client.complete.assert_not_called()


if __name__ == "__main__":
    unittest.main()
