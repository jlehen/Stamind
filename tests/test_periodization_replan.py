"""What a replan reuses and what it offers to keep: the cached plan an
up-to-date run hands back, the mesocycle already under way that the athlete
may let finish, and what `--fresh` withholds.
"""
import os
import unittest
from datetime import datetime, timedelta, timezone
from unittest.mock import patch

from tests.helpers import clear_all_tables, pin_clock, rebind_test_db
from tests import test_db_path

TEST_DB_PATH = test_db_path("test_periodization_replan.db")


def _days_out(n: int) -> str:
    return (datetime.now(timezone.utc).date() + timedelta(days=n)).isoformat()


# Fixtures ride on today rather than on fixed dates; test_periodization.py says why.
GOAL_DATE = _days_out(71)

from stamind import plan_inputs
from stamind.db import Database

test_db = Database(db_path=TEST_DB_PATH)
rebind_test_db(test_db)

from stamind.coach.service import coach_service


def _session_titles(rows) -> list:
    """The titles of the real sessions in a listing.

    Generation now covers every date of its span, filling the ones the model left out
    with explicit rest (DESIGN_runway_nudge.md §2.1), so a fixture whose mocked response
    holds one session gets that session plus a rest row per remaining day. These tests are
    about which sessions survive a regeneration or a rollback, not about the coverage."""
    return [w["title"] for w in rows if w["sport_type"] != "rest"]


class TestReplan(unittest.TestCase):
    """Mid-mesocycle a replan may let that mesocycle finish, which means
    repeating it; a clean slate is never asked to finish what it is leaving."""

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

    @patch("stamind.runtime.calendar_syncer")
    @patch("stamind.coach.engine.openrouter_client")
    def test_replan_logic_and_caching(self, mock_client, mock_calendar):
        # Every clock, not just the service's: whether a goal is still ahead is now a date
        # question the DB answers, so a half-pinned clock reads real "today" there and the
        # fixture's future-dated goals silently become past ones.
        pin_clock(self, "2026-06-01")
        obj_id = test_db.add_objective(
            title="Berlin Marathon", target_date="2026-09-27",
            sport_type="running",
        )

        mock_macro_response = {
            "strategy": "Simulated overall strategy",
            "mesocycles": [
                {"name": "Base Building", "start_date": "2026-06-01",
                 "end_date": "2026-06-28", "focus": "Endurance"},
                {"name": "Peak & Taper", "start_date": "2026-06-29",
                 "end_date": "2026-07-05", "focus": "Taper"},
            ],
        }
        mock_workouts_response = {
            "reasoning": "Microcycle generated reasoning",
            "learning_updates": [{"op": "add", "text": "Simulated learnings"}],
            "workouts": [{
                "date": "2026-06-01", "sport_type": "running",
                "title": "Base Run", "description": "45 mins zone 2",
            }],
        }

        mock_client.complete.side_effect = [mock_macro_response, mock_workouts_response]
        reason, workouts = coach_service.replan(force=False)
        self.assertEqual(reason, "Microcycle generated reasoning")
        self.assertEqual(_session_titles(workouts), ["Base Run"])
        self.assertEqual(mock_client.complete.call_count, 2)

        macro = test_db.get_macrocycle_for_objective(obj_id)
        self.assertIsNotNone(macro)
        self.assertEqual(macro["strategy"], "Simulated overall strategy")
        self.assertEqual(len(test_db.get_mesocycles_for_macrocycle(macro["id"])), 2)

        # No changes + force=False → reuse macrocycle, generate workouts only
        mock_client.complete.reset_mock()
        mock_client.complete.side_effect = [mock_workouts_response]
        coach_service.replan(force=False)
        self.assertEqual(mock_client.complete.call_count, 1)

        # force=True → regenerate everything
        mock_client.complete.reset_mock()
        mock_client.complete.side_effect = [mock_macro_response, mock_workouts_response]
        coach_service.replan(force=True)
        self.assertEqual(mock_client.complete.call_count, 2)

        # New goal added → hash mismatch → regenerate everything
        test_db.add_objective(
            title="Mini Triathlon", target_date="2026-08-01",
            sport_type="cycling",
        )
        mock_client.complete.reset_mock()
        mock_client.complete.side_effect = [mock_macro_response, mock_workouts_response]
        coach_service.replan(force=False)
        self.assertEqual(mock_client.complete.call_count, 2)

    def _plan_with_mesocycle_under_way(self, target_date: str = "2026-11-01") -> int:
        """A goal whose active plan holds one mesocycle straddling the pinned today."""
        obj_id = test_db.add_objective(
            title="Zurich Marathon", target_date=target_date,
            sport_type="running",
        )
        test_db.save_macrocycle(
            objective_id=obj_id,
            strategy="Build aerobic base",
            goals_hash="old_goals_hash",
            constraints_hash="old_constraints_hash",
            mesocycles=[{
                "name": "Build", "start_date": "2026-08-03",
                "end_date": "2026-08-30", "focus": "Threshold work",
            }],
        )
        return obj_id

    @patch("stamind.coach.engine.openrouter_client")
    def test_replan_offers_to_keep_the_mesocycle_under_way(self, mock_client):
        """Mid-mesocycle, the replan may let that mesocycle finish — which means repeating its
        ORIGINAL start date, since mesocycles own their sessions by date containment
        (DESIGN_mesocycle_progress.md §7)."""
        pin_clock(self, "2026-08-23")
        self._plan_with_mesocycle_under_way()
        mock_client.complete.return_value = {
            "strategy": "Kept the Build mesocycle; it still fits.",
            "mesocycles": [{
                "name": "Build", "start_date": "2026-08-03",
                "end_date": "2026-08-30", "focus": "Threshold work",
            }],
        }

        coach_service.plan_generate(force=True)

        prompt = mock_client.complete.call_args_list[0][0][0]
        self.assertIn("### THE MESOCYCLE ALREADY UNDER WAY", prompt)
        self.assertIn('"Build" (2026-08-03 to 2026-08-30)', prompt)
        self.assertIn("Already trained: 20 days of it, starting 2026-08-03.", prompt)
        # The whole point of the change: keeping it means the original start date.
        self.assertIn("ORIGINAL start date", prompt)
        self.assertIn("(2026-08-03), its original end date (2026-08-30)", prompt)
        self.assertIn("Do NOT re-date it to 2026-08-23", prompt)
        # ...and the unconditional "start today" sentence is withdrawn while it applies.
        self.assertNotIn("The first mesocycle must start on the start date", prompt)

    @patch("stamind.coach.engine.openrouter_client")
    def test_mesocycle_starting_today_is_not_offered(self, mock_client):
        """Nothing is under way yet, so there is nothing to let finish."""
        pin_clock(self, "2026-08-03")
        self._plan_with_mesocycle_under_way()
        mock_client.complete.return_value = {"strategy": "s", "mesocycles": []}

        coach_service.plan_generate(force=True)

        prompt = mock_client.complete.call_args_list[0][0][0]
        self.assertNotIn("### THE MESOCYCLE ALREADY UNDER WAY", prompt)
        self.assertIn(
            "The first mesocycle must start on the start date (2026-08-03).", prompt
        )

    @patch("stamind.coach.engine.openrouter_client")
    def test_fresh_withholds_the_mesocycle_under_way(self, mock_client):
        """A clean slate is not asked to finish the mesocycle it is departing from."""
        pin_clock(self, "2026-08-23")
        self._plan_with_mesocycle_under_way()
        mock_client.complete.return_value = {"strategy": "s", "mesocycles": []}

        coach_service.plan_generate(fresh=True)

        prompt = mock_client.complete.call_args_list[0][0][0]
        self.assertNotIn("### THE MESOCYCLE ALREADY UNDER WAY", prompt)
        self.assertIn(
            "The first mesocycle must start on the start date (2026-08-23).", prompt
        )

    @patch("stamind.coach.engine.openrouter_client")
    def test_mesocycle_not_offered_when_plan_start_is_pinned_past_today(self, mock_client):
        """A preceding goal's plan pins the start after today; reaching back past that
        would overlap that goal's season, so the keep option is withheld."""
        pin_clock(self, "2026-08-23")
        early_id = test_db.add_objective(
            title="Tune-up 10k", target_date="2026-09-15",
            sport_type="running",
        )
        test_db.save_macrocycle(
            objective_id=early_id, strategy="Sharpen",
            goals_hash="g", constraints_hash="c",
            mesocycles=[{
                "name": "Sharpen", "start_date": "2026-08-25",
                "end_date": "2026-09-15", "focus": "Speed",
            }],
        )
        obj_id = self._plan_with_mesocycle_under_way()
        mock_client.complete.return_value = {"strategy": "s", "mesocycles": []}

        # Named explicitly: the bare call would plan for the sooner tune-up goal.
        coach_service.plan_generate(force=True, objective_id=obj_id)

        prompt = mock_client.complete.call_args_list[0][0][0]
        self.assertNotIn("### THE MESOCYCLE ALREADY UNDER WAY", prompt)
        self.assertIn(
            "The first mesocycle must start on the start date (2026-09-16).", prompt
        )

    @patch("stamind.coach.engine.openrouter_client")
    def test_fresh_withholds_the_plan_in_place(self, mock_client):
        """`--fresh`: the intent is withheld, the evidence is not
        (DESIGN_backward_evaluation.md §6.1)."""
        obj_id = test_db.add_objective(
            title="Zurich Marathon", target_date=GOAL_DATE,
            sport_type="running",
        )
        test_db.save_macrocycle(
            objective_id=obj_id,
            strategy="Keep heart rate low",
            goals_hash="old_goals_hash",
            constraints_hash="old_constraints_hash",
            mesocycles=[{
                "name": "Base Building", "start_date": "2026-06-01",
                "end_date": "2026-06-28", "focus": "Aerobic conditioning",
            }],
        )
        test_db.save_completed_activity(
            activity_id="a1", date="2026-06-01", start_time="08:00:00",
            activity_name="Base Run", activity_type="running",
            duration_sec=3600.0, distance_km=10.0, elevation_gain_m=50.0,
            avg_hr=140, max_hr=160, rpe=5, tss=60.0,
            zone1_sec=300, zone2_sec=2700, zone3_sec=400, zone4_sec=200, zone5_sec=0,
        )
        mock_client.complete.return_value = {
            "strategy": "New strategy", "mesocycles": [{
                "name": "Build", "start_date": "2026-06-08",
                "end_date": "2026-10-15", "focus": "Threshold",
            }],
        }

        coach_service.plan_generate(fresh=True, objective_id=obj_id, auto_apply=False)

        system_prompt = mock_client.complete.call_args[0][0]
        self.assertNotIn("PREVIOUS PERIODIZATION STRATEGY", system_prompt)
        self.assertNotIn("CONTINUITY WITH THE PREVIOUS PLAN", system_prompt)
        self.assertNotIn("Keep heart rate low", system_prompt)
        # What the athlete trained under that plan still reaches the prompt.
        self.assertIn("PLANNED vs ACTUAL", system_prompt)
        self.assertIn("Aerobic conditioning", system_prompt)

    @patch("stamind.coach.engine.openrouter_client")
    def test_fresh_implies_force(self, mock_client):
        """A clean slate is a regeneration: an up-to-date plan is not reused."""
        obj_id = test_db.add_objective(
            title="Zurich Marathon", target_date=GOAL_DATE,
            sport_type="running",
        )
        test_db.save_macrocycle(
            objective_id=obj_id,
            strategy="Keep heart rate low",
            goals_hash=plan_inputs.goals_hash(test_db.upcoming_objectives()),
            constraints_hash=plan_inputs.constraints_hash([]),
            config_hash=plan_inputs.plan_config_hash(),
            config_snapshot=coach_service._get_config_snapshot(),
            mesocycles=[{
                "name": "Base Building", "start_date": "2026-06-01",
                "end_date": "2026-06-28", "focus": "Aerobic conditioning",
            }],
        )
        mock_client.complete.return_value = {
            "strategy": "New strategy", "mesocycles": [{
                "name": "Build", "start_date": "2026-06-08",
                "end_date": "2026-10-15", "focus": "Threshold",
            }],
        }

        # Same inputs, so without `fresh` this would be reused without an LLM call.
        reused = coach_service.plan_generate(
            objective_id=obj_id, auto_apply=False
        )['reused']
        self.assertTrue(reused)

        proposal = coach_service.plan_generate(
            fresh=True, objective_id=obj_id, auto_apply=False
        )
        self.assertFalse(proposal['reused'])
        self.assertEqual(proposal['strategy'], "New strategy")


if __name__ == "__main__":
    unittest.main()
