"""The pairing the matcher had to guess at, raised as a question before the
model call rather than assumed.
"""
import os
import unittest
from unittest.mock import patch

from tests.helpers import (
    clear_all_tables, rebind_test_db, save_workout, skip_strength_planner,
)
from tests import test_db_path

TEST_DB_PATH = test_db_path("test_adaptation_matching.db")

from trainmate.db import Database
import trainmate.config

test_db = Database(db_path=TEST_DB_PATH)
rebind_test_db(test_db)

from trainmate.coach.service import coach_service


class TestAdaptAsksAboutAGuessedPairing(unittest.TestCase):
    """A pairing adapt is sure of costs the athlete nothing; one it guessed at is
    asked about, and the answer sticks."""

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
        skip_strength_planner(self)
        # `adapt` refuses without a plan (§6), so every case needs one. A single wide
        # mesocycle keeps it out of the way: tests that care about mesocycle edges save their
        # own plan over this one.
        self._save_background_plan()

    @staticmethod
    def _save_background_plan():
        obj_id = test_db.add_objective(
            title="Background goal", target_date="2026-12-31",
            sport_type="running",
        )
        test_db.save_macrocycle(
            objective_id=obj_id, strategy="General preparation.",
            goals_hash="bg", constraints_hash="bg",
            mesocycles=[{
                "name": "Base", "start_date": "2026-01-01",
                "end_date": "2026-12-31", "focus": "Aerobic base",
            }],
        )

    @patch("trainmate.coach.engine.openrouter_client")
    def test_ambiguous_match_is_asked_about_and_the_answer_sticks(self, mock_client):
        """A pairing the matcher had to GUESS at is raised as a question before the LLM
        call, and answering "no" keeps the activity out of the session.

        `indoor_cardio` is an alias of `strength_training`, so a 10-minute warm-up pairs
        with a 65-minute lift on load-sorted first-come matching. That is a guess, not a
        fact, and it used to reach the week planner as "this session was performed"
        (ARCHITECTURE.md §15)."""
        test_profile = {"lthr": 165, "max_hr": 185}
        with patch.dict(trainmate.config.config.data, {
            "user_profile": test_profile,
            "coach": {
                "metrics_lookback_days": 3,
                "minor_activity_load_threshold": 10.0,
            }
        }):
            mock_client.complete.return_value = {
                "change_needed": False, "reason": "Holding.", "adapted_workouts": [],
            }
            test_db.save_metric_cache("2026-06-03", 56, 42, 60, 35, 14.0, 8.0, 1.75)
            test_db.save_baseline("2026-06-03", 50.0, 2.0, 60.0, 5.0, 80.0, 5.0)
            save_workout(test_db,
                "2026-06-03", "strength_training", "Full-Body Strength", "65 mins",
                duration_minutes=65, rpe=6, tss=30,
            )
            test_db.save_completed_activity(
                "act_warmup", "2026-06-03", "2026-06-03 12:00:00", "Warm-up",
                "indoor_cardio", 600.0, 1.6, None, 107, 120, 1, 1.6,
            )

            # The guess is surfaced rather than silently believed.
            questions = coach_service.pending_match_questions("2026-06-03")
            self.assertEqual(len(questions), 1)
            self.assertEqual(questions[0]["activity_id"], "act_warmup")
            self.assertEqual(questions[0]["sport"], "strength_training")

            # Say no: that warm-up was not the lift.
            coach_service.record_match_decision("act_warmup", "strength_training", False)

            # Asked once, not every run.
            self.assertEqual(coach_service.pending_match_questions("2026-06-03"), [])

            coach_service.workout_adapt("2026-06-03")
            prompt_user_content = mock_client.complete.call_args[0][1]
            # The session now carries no performed-tag at all: nothing was done.
            self.assertNotIn("[PARTIAL", prompt_user_content)
            self.assertNotIn("[COMPLETED", prompt_user_content)

    @patch("trainmate.coach.engine.openrouter_client")
    def test_same_sport_but_far_too_short_is_also_asked_about(self, mock_client):
        """The sport check has already done its work by the time a pairing exists, so the
        question turns on DURATION alone — an exact sport match that ran far short is as
        unclear as an aliased one. A 10-minute strength activity against a 65-minute lift
        is either the session cut short or a warm-up to discard, and only the athlete
        knows which (ARCHITECTURE.md §15)."""
        test_profile = {"lthr": 165, "max_hr": 185}
        with patch.dict(trainmate.config.config.data, {
            "user_profile": test_profile,
            "coach": {
                "metrics_lookback_days": 3,
                "minor_activity_load_threshold": 10.0,
            }
        }):
            test_db.save_metric_cache("2026-06-03", 56, 42, 60, 35, 14.0, 8.0, 1.75)
            test_db.save_baseline("2026-06-03", 50.0, 2.0, 60.0, 5.0, 80.0, 5.0)
            save_workout(test_db,
                "2026-06-03", "strength_training", "Full-Body Strength", "65 mins",
                duration_minutes=65, rpe=6, tss=30,
            )
            test_db.save_completed_activity(
                "act_short_lift", "2026-06-03", "2026-06-03 12:00:00", "Strength",
                "strength_training", 600.0, 5.0, None, 120, 140, 3, 5.0,
            )

            questions = coach_service.pending_match_questions("2026-06-03")
            self.assertEqual(len(questions), 1)
            self.assertEqual(questions[0]["activity_id"], "act_short_lift")

    @patch("trainmate.coach.engine.openrouter_client")
    def test_a_session_that_ran_its_length_is_never_questioned(self, mock_client):
        """The question costs nothing on an ordinary day. An activity that ran roughly the
        planned length is the session, whether its type is the planned sport's own name or
        one of its aliases — a 62-minute virtual_ride IS the 60-minute cycling session."""
        test_profile = {"lthr": 165, "max_hr": 185}
        with patch.dict(trainmate.config.config.data, {
            "user_profile": test_profile,
            "coach": {
                "metrics_lookback_days": 3,
                "minor_activity_load_threshold": 10.0,
            }
        }):
            test_db.save_metric_cache("2026-06-03", 56, 42, 60, 35, 14.0, 8.0, 1.75)
            test_db.save_baseline("2026-06-03", 50.0, 2.0, 60.0, 5.0, 80.0, 5.0)
            # Aliased sport, right length.
            save_workout(test_db,
                "2026-06-03", "cycling", "Endurance Ride", "60 mins",
                duration_minutes=60, rpe=4, tss=40,
            )
            test_db.save_completed_activity(
                "act_ride", "2026-06-03", "2026-06-03 08:00:00", "Zwift",
                "virtual_ride", 3720.0, 42.0, 250.0, 132, 150, 4, 42.0,
            )
            # Exact sport, right length.
            save_workout(test_db,
                "2026-06-02", "strength_training", "Full-Body Strength", "65 mins",
                duration_minutes=65, rpe=6, tss=30,
            )
            test_db.save_completed_activity(
                "act_lift", "2026-06-02", "2026-06-02 12:00:00", "Strength",
                "strength_training", 3840.0, 31.0, None, 120, 140, 6, 31.0,
            )

            self.assertEqual(coach_service.pending_match_questions("2026-06-03"), [])
