"""What the `plan generate` strategy prompt is told.

The periodization vocabulary, the athlete's profile and weekly schedule, the science
guidelines banner, the strategy the plan being replaced was built on, and the recent
training summary that both this call and `workout generate` carry.

The rest of the family is named `test_periodization_<x>.py`, where `<x>` is: `review`,
the reconstruction of the training behind the athlete; `fingerprint` and `staleness`,
what the plan's inputs hash over and which change makes the plan stale; `replan` and
`goal_window`, which days a plan covers; `regeneration` and `rollback`, what a
regeneration clears and how it is put back; `lineage`, `date_keyed`, `generation_span`
and `standing`, what `workout generate` reads off the plan; and `goal_archival`.
"""
import os
import shutil
import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from unittest.mock import patch

from tests.helpers import clear_all_tables, pin_clock, rebind_test_db
from tests import test_db_path

TEST_DB_PATH = test_db_path("test_trainmate_periodization.db")


def _days_out(n: int) -> str:
    return (datetime.now(timezone.utc).date() + timedelta(days=n)).isoformat()


# Goal and constraint fixtures ride on today rather than on fixed dates: a plan window
# needs its goal in the future, so hardcoding one expires the tests the day it passes
# (same rot 2a7cd71 fixed in test_constraints.py).
GOAL_DATE = _days_out(71)

import trainmate.config
from trainmate.db import Database

test_db = Database(db_path=TEST_DB_PATH)
rebind_test_db(test_db)

from trainmate.coach.service import coach_service


def _generate_workouts(**kwargs):
    """`workout generate` end to end: propose, then accept, as the CLI does on a `y`.

    Generation is two halves so the athlete reads the plan before it is written; tests
    exercising the write want both, and the proposal alone is called directly where only
    the refusal or the prompt is under test."""
    proposal = coach_service.workout_generate(**kwargs)
    return proposal.reasoning, coach_service.workout_generate_apply(proposal)


class TestPlanGeneratePrompt(unittest.TestCase):
    """Every section the strategy prompt carries, asserted on the text the model
    would receive."""

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

    def test_system_prompt_inserts_periodization(self):
        obj_id = test_db.add_objective(
            title="Zurich Marathon", target_date=GOAL_DATE,
            sport_type="running",
        )
        test_db.save_macrocycle(
            objective_id=obj_id,
            strategy="Run long and slow",
            goals_hash="hash1",
            constraints_hash="hash2",
            mesocycles=[
                {"name": "Base Building", "start_date": "2026-06-01",
                 "end_date": "2026-06-28", "focus": "Zone 2 runs"},
                {"name": "Peak & Taper", "start_date": "2026-06-29",
                 "end_date": "2026-07-05", "focus": "Tapering"},
            ],
        )

        objs = test_db.get_objectives(status="active")
        prompt = coach_service._get_coach_system_prompt(objs, [])

        self.assertIn("Run long and slow", prompt)
        self.assertIn("Base Building (2026-06-01 to 2026-06-28): Zone 2 runs", prompt)
        self.assertIn("Peak & Taper (2026-06-29 to 2026-07-05): Tapering", prompt)
        self.assertIn("## COACH LEARNINGS & ACTIVE PERIODIZATION STRATEGY", prompt)
        self.assertIn("START OF TRAINMATE SPORTS SCIENCE GUIDELINES", prompt)
        self.assertIn("END OF TRAINMATE SPORTS SCIENCE GUIDELINES", prompt)

    @patch("trainmate.coach.engine.openrouter_client")
    def test_replan_provides_previous_strategy_context_to_llm(self, mock_client):
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

        mock_client.complete.side_effect = [
            {
                "strategy": "New strategy building on previous",
                "mesocycles": [{
                    "name": "Specific Prep", "start_date": "2026-06-01",
                    "end_date": "2026-06-28", "focus": "Faster runs",
                }],
            },
            {"reasoning": "Reasoning", "workouts": []},
        ]

        # A plan-shaping constraint triggers hash mismatch → replanning
        test_db.add_constraint(
            title="Business Trip", start_date="2026-06-10", end_date="2026-06-12",
            description="limited training time", replan=1,
        )

        coach_service.replan(force=False)

        self.assertEqual(mock_client.complete.call_count, 2)
        system_prompt = mock_client.complete.call_args_list[0][0][0]
        self.assertIn("## PREVIOUS PERIODIZATION STRATEGY (FOR CONTEXT)", system_prompt)
        self.assertIn("Keep heart rate low", system_prompt)
        self.assertIn(
            "Base Building (2026-06-01 to 2026-06-28): Aerobic conditioning",
            system_prompt,
        )
        self.assertIn("### CONTINUITY WITH THE PREVIOUS PLAN", system_prompt)
        self.assertIn(
            "The PREVIOUS periodization strategy that was in place before this",
            system_prompt,
        )

    def test_system_prompt_inserts_athlete_profile(self):
        test_profile = {
            "name": "Jane Doe",
            "birth_year": 1990,
            "max_hr": 190,
            "lthr": 170,
            "weekly_target_hours": 8.0,
            "sport_preferences": ["running", "yoga"],
            "chronic_injuries": "Tendency for runner's knee.",
            "preferences": "Enjoys morning runs.",
            "equipment": ["Garmin Watch", "Yoga Mat"],
            "weekly_schedule": {
                "Monday": {
                    "total_available_hours": 1.5,
                    "max_sessions": 2,
                    "certainty_percent": 95,
                    "equipment": ["treadmill"],
                },
                "Wednesday": 0.0,
            },
        }
        with patch.dict(trainmate.config.config.data, {"user_profile": test_profile}):
            prompt = coach_service._get_coach_system_prompt([], [])
            self.assertIn("Jane Doe", prompt)
            self.assertIn("Birth Year: 1990", prompt)
            self.assertIn("Tendency for runner's knee.", prompt)
            self.assertIn("Enjoys morning runs.", prompt)
            self.assertIn("Garmin Watch, Yoga Mat", prompt)
            self.assertIn(
                "Monday: 1.5 hours | Max sessions: 2 | Certainty: 95% (Equipment: treadmill)",
                prompt,
            )
            self.assertIn("Wednesday: 0.0 hours", prompt)

    def test_system_prompt_without_weekly_schedule(self):
        # weekly_schedule is optional: the prompt must say so explicitly and must not
        # instruct adherence to a day-by-day schedule that does not exist.
        test_profile = {
            "name": "Jane Doe",
            "weekly_target_hours": 8.0,
        }
        with patch.dict(trainmate.config.config.data, {"user_profile": test_profile}):
            prompt = coach_service._get_coach_system_prompt([], [])
            self.assertIn("no day-by-day schedule configured", prompt)
            self.assertIn("No day-by-day availability schedule is configured", prompt)
            self.assertNotIn("Adhere to the day-by-day weekly availability schedule", prompt)
            self.assertNotIn("No availability configured", prompt)

    @patch("trainmate.runtime.config")
    def test_load_science_guidelines(self, mock_config):
        temp_app_dir = tempfile.mkdtemp()
        temp_user_dir = tempfile.mkdtemp()

        try:
            mock_config.app_science_dir = temp_app_dir
            mock_config.science_dir = temp_user_dir

            with open(os.path.join(temp_app_dir, "app_science.md"), "w") as f:
                f.write("App guideline text")
            with open(os.path.join(temp_user_dir, "user_science.md"), "w") as f:
                f.write("User guideline text")
            with open(os.path.join(temp_user_dir, "notes.txt"), "w") as f:
                f.write("Ignored guideline text")

            guidelines = coach_service._load_science_guidelines()

            self.assertIn("--- app_science.md ---", guidelines)
            self.assertIn("App guideline text", guidelines)
            self.assertIn("--- user_science.md ---", guidelines)
            self.assertIn("User guideline text", guidelines)
            self.assertNotIn("Ignored guideline text", guidelines)
            # Each source gets its own banner, so the coach can tell whose material it is
            # reading (DESIGN_prompt_structure.md §3): the app's text must close out before
            # the athlete's banner opens.
            self.assertLess(
                guidelines.index("App guideline text"),
                guidelines.index("END OF TRAINMATE SPORTS SCIENCE GUIDELINES"),
            )
            self.assertLess(
                guidelines.index("END OF TRAINMATE SPORTS SCIENCE GUIDELINES"),
                guidelines.index("START OF ATHLETE-PROVIDED SPORTS SCIENCE GUIDELINES"),
            )
            self.assertLess(
                guidelines.index("START OF ATHLETE-PROVIDED SPORTS SCIENCE GUIDELINES"),
                guidelines.index("User guideline text"),
            )
        finally:
            shutil.rmtree(temp_app_dir)
            shutil.rmtree(temp_user_dir)

    @patch("trainmate.runtime.config")
    def test_science_guidelines_omit_banner_for_empty_source(self, mock_config):
        """A fresh install has no `science/` dir — it must produce no athlete banner at
        all, rather than an empty one (DESIGN_prompt_structure.md §3)."""
        temp_app_dir = tempfile.mkdtemp()
        try:
            mock_config.app_science_dir = temp_app_dir
            mock_config.science_dir = os.path.join(temp_app_dir, "does_not_exist")
            with open(os.path.join(temp_app_dir, "app_science.md"), "w") as f:
                f.write("App guideline text")

            guidelines = coach_service._load_science_guidelines()

            self.assertIn("START OF TRAINMATE SPORTS SCIENCE GUIDELINES", guidelines)
            self.assertNotIn("ATHLETE-PROVIDED", guidelines)
        finally:
            shutil.rmtree(temp_app_dir)

    @patch("trainmate.coach.engine.openrouter_client")
    def test_recent_history_summary_periodization_plan(self, mock_client):
        pin_clock(self, "2026-06-18")
        obj_id = test_db.add_objective(
            title="Zurich Marathon", target_date=GOAL_DATE,
            sport_type="running",
        )
        test_db.save_completed_activity(
            activity_id="act_test_1", date="2026-06-04", start_time="08:00:00",
            activity_name="Morning Run", activity_type="running",
            duration_sec=3600.0, distance_km=10.0, elevation_gain_m=100.0,
            avg_hr=150, max_hr=170, rpe=6, tss=60.0,
        )
        test_db.save_metric_cache(
            date="2026-06-04", rhr=55, hrv=60, sleep_score=80, stress=25,
            ctl=58.0, atl=61.0, tsb=-3.0,
        )

        mock_client.complete.return_value = {
            "strategy": "Separate strategy philosophy",
            "mesocycles": [{
                "name": "Base Phase", "start_date": "2026-06-01",
                "end_date": "2026-06-28", "focus": "Base",
            }],
        }

        coach_service.plan_generate(force=True)

        system_prompt = mock_client.complete.call_args[0][0]
        self.assertIn("## ATHLETE RECENT TRAINING SUMMARY (PAST 15 DAYS)", system_prompt)
        self.assertIn("Completed Activities (Past 15 days):", system_prompt)
        self.assertIn("running: 1 activity", system_prompt)
        self.assertIn("Resting Heart Rate: 55.0 bpm", system_prompt)

    @patch("trainmate.runtime.calendar_syncer")
    @patch("trainmate.coach.engine.openrouter_client")
    def test_recent_history_workout_generation(self, mock_client, mock_calendar):
        pin_clock(self, "2026-06-18")
        obj_id = test_db.add_objective(
            title="Zurich Marathon", target_date=GOAL_DATE,
            sport_type="running",
        )
        test_db.save_macrocycle(
            objective_id=obj_id,
            strategy="Keep heart rate low",
            goals_hash="hash1",
            constraints_hash="hash2",
            mesocycles=[{
                "name": "Base Phase", "start_date": "2026-06-01",
                "end_date": "2026-06-28", "focus": "Base",
            }],
        )
        test_db.save_metric_cache(
            date="2026-06-04", rhr=55, hrv=60, sleep_score=80, stress=25,
            ctl=58.0, atl=61.0, tsb=-3.0,
        )

        mock_client.complete.return_value = {
            "reasoning": "Separate workout reasoning",
            "workouts": [{
                "date": "2026-06-05", "sport_type": "running",
                "title": "Base Run", "description": "30 mins",
            }],
        }

        _generate_workouts()

        user_content = mock_client.complete.call_args[0][1]
        self.assertIn("## ATHLETE'S METRICS HISTORY (PAST 15 DAYS)", user_content)
        self.assertIn("RHR=55bpm, HRV=60ms", user_content)


if __name__ == "__main__":
    unittest.main()
