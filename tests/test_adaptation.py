"""What the week planner is told when `workout adapt` runs, and the fixture the
whole family shares.

Every case needs a plan, because adapt refuses without one, so `setUp` saves
one wide mesocycle out of the way and a test that cares about mesocycle
edges saves its own over it. The rest of `workout adapt` is
`test_adaptation_history.py` (what it may not rewrite),
`test_adaptation_matching.py` (the pairing it had to guess at),
`test_adaptation_revisions.py` (which answers are real changes),
`test_adaptation_easing.py` (what an easing costs and leaves behind) and
`test_adaptation_moves.py` (a session carried to another day).
"""
import os
import unittest
from unittest.mock import patch

from tests.helpers import (
    clear_all_tables, rebind_test_db, save_workout, skip_strength_planner,
)
from tests import test_db_path

TEST_DB_PATH = test_db_path("test_adaptation.db")

from stamind.db import Database
import stamind.config

test_db = Database(db_path=TEST_DB_PATH)
rebind_test_db(test_db)

from stamind.coach.service import coach_service


class TestAdaptPrompt(unittest.TestCase):
    """What reaches the adapt prompt: the discrepancies behind the athlete, the
    learnings it reads but never writes, the athlete's own message, the
    mesocycle's terminal window, the sections it shares with generate, and
    the measured distribution with its drift branch. Plus the refusal that
    comes before any of it, when there is no plan to judge against."""

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

    @staticmethod
    def _clear_plans():
        """Drops setUp's background plan so a test's own plan is the governing one."""
        with test_db._get_connection() as conn:
            for table in ("mesocycles", "macrocycles", "objectives"):
                conn.execute(f"DELETE FROM {table}")
            conn.commit()

    @patch("stamind.coach.engine.openrouter_client")
    def test_adaptation_matching_and_discrepancies(self, mock_client):
        test_profile = {"lthr": 165, "max_hr": 185}

        with patch.dict(stamind.config.config.data, {
            "user_profile": test_profile,
            "coach": {
                "metrics_lookback_days": 3,
                "minor_activity_load_threshold": 10.0,
            }
        }):
            mock_client.complete.return_value = {
                "change_needed": True,
                "reason": "Fatigue detected, RHR is elevated and HRV is suppressed.",
                "adapted_workouts": [
                    {
                        "date": "2026-06-03",
                        "sport_type": "rest",
                        "title": "Adapted Rest Day",
                        "description": "Swapped tempo run to rest.",
                        "duration_minutes": 0,
                        "rpe": 0,
                        "tss": 0.0,
                    }
                ],
            }

            test_db.save_metric_cache("2026-06-01", 50, 60, 80, 20, 10.0, 8.0, 1.2)
            test_db.save_metric_cache("2026-06-02", 52, 55, 75, 25, 12.0, 8.0, 1.5)
            test_db.save_metric_cache("2026-06-03", 56, 42, 60, 35, 14.0, 8.0, 1.75)
            test_db.save_baseline("2026-06-03", 50.0, 2.0, 60.0, 5.0, 80.0, 5.0)

            save_workout(test_db,
                "2026-06-01", "running", "Easy Run", "30 mins",
                duration_minutes=30, rpe=4, tss=20,
            )
            save_workout(test_db,
                "2026-06-02", "cycling", "Tempo Ride", "60 mins",
                duration_minutes=60, rpe=6, tss=40,
            )
            # Never trained, on a day that is over -> a real miss.
            save_workout(test_db,
                "2026-06-02", "running", "Skipped Recovery Jog", "20 mins",
                duration_minutes=20, rpe=2, tss=10,
            )
            # On the evaluation date itself: not trained YET, so pending, not missed.
            save_workout(test_db,
                "2026-06-03", "running", "Interval Session", "45 mins",
                duration_minutes=45, rpe=8, tss=60,
            )

            test_db.save_completed_activity(
                "act_1", "2026-06-01", "2026-06-01 08:00:00", "Easy Run",
                "running", 1800.0, 5.0, 50.0, 132, 150, 4, 20.0,
            )
            test_db.save_completed_activity(
                "act_2", "2026-06-02", "2026-06-02 08:00:00", "Short Cycling",
                "cycling", 1800.0, 12.0, 100.0, 132, 150, 4, 20.0,
            )

            _p = coach_service.workout_adapt("2026-06-03")
            reason, proposed, _new_constraints = _p.reason, _p.workouts, _p.new_constraints

            self.assertTrue(mock_client.complete.called)
            self.assertEqual(reason, "Fatigue detected, RHR is elevated and HRV is suppressed.")
            self.assertEqual(len(proposed), 1)
            self.assertEqual(proposed[0]["title"], "Adapted Rest Day")
            self.assertEqual(proposed[0]["sport_type"], "rest")

            prompt_user_content = mock_client.complete.call_args[0][1]
            self.assertIn(
                "Complete Miss! Missed planned workout 'Skipped Recovery Jog'",
                prompt_user_content,
            )
            # The evaluation date's own session is still ahead of the athlete: calling it
            # a miss made adapt reschedule work that was never skipped (it duplicated a
            # benchmark that way). It stays in the plan listing, out of the discrepancies.
            self.assertNotIn("'Interval Session'", prompt_user_content)
            self.assertIn("Interval Session", prompt_user_content)
            self.assertIn("duration mismatch", prompt_user_content)

    @patch("stamind.coach.engine.openrouter_client")
    def test_adapt_is_read_only_for_learnings(self, mock_client):
        """Daily adaptation consumes coach learnings as context but authors none — durable,
        evidence-backed observations are written only by the weekly history analysis
        (DESIGN_evidence_based_confidence.md §2/§11)."""
        test_profile = {"lthr": 165, "max_hr": 185}
        with patch.dict(stamind.config.config.data, {
            "user_profile": test_profile,
            "coach": {
                "metrics_lookback_days": 3,
                "minor_activity_load_threshold": 10.0,
            }
        }):
            # Pre-existing observation shown to the model as context.
            lid = test_db.add_learning(
                "Elevated RHR after consecutive hard days", sports="running"
            )

            # Even if the model returns learning_updates, adapt must ignore them.
            mock_client.complete.return_value = {
                "change_needed": False,
                "reason": "On track.",
                "adapted_workouts": [],
                "learning_updates": [
                    {"op": "add", "text": "Should NOT be saved by adapt"},
                ],
            }

            test_db.save_metric_cache("2026-06-03", 56, 42, 60, 35, 14.0, 8.0, 1.75)
            test_db.save_baseline("2026-06-03", 50.0, 2.0, 60.0, 5.0, 80.0, 5.0)

            _p = coach_service.workout_adapt("2026-06-03")
            reason, proposed, _new_constraints = _p.reason, _p.workouts, _p.new_constraints
            self.assertEqual(reason, "On track.")
            self.assertEqual(proposed, [])

            # The adapt prompt still surfaces the existing observation by id as context.
            system_prompt = mock_client.complete.call_args[0][0]
            self.assertIn(f"[{lid}|running|", system_prompt)

            # No learnings were written: only the pre-existing one remains.
            learnings = {l["id"]: l for l in test_db.get_learnings()}
            self.assertEqual(len(learnings), 1)
            self.assertIn(lid, learnings)

    @patch("stamind.coach.engine.openrouter_client")
    def test_adapt_message_surfaced_in_prompt(self, mock_client):
        """An athlete message for the run is rendered as a bounded section of the adapt
        prompt (advisory, ephemeral) and omitted entirely when no message is given."""
        test_profile = {"lthr": 165, "max_hr": 185}
        with patch.dict(stamind.config.config.data, {
            "user_profile": test_profile,
            "coach": {
                "metrics_lookback_days": 3,
                "minor_activity_load_threshold": 10.0,
            }
        }):
            mock_client.complete.return_value = {
                "change_needed": False,
                "reason": "On track.",
                "adapted_workouts": [],
            }

            test_db.save_metric_cache("2026-06-03", 56, 42, 60, 35, 14.0, 8.0, 1.75)
            test_db.save_baseline("2026-06-03", 50.0, 2.0, 60.0, 5.0, 80.0, 5.0)

            coach_service.workout_adapt(
                "2026-06-03", message="  knee is sore, keep impact low  "
            )
            user_content = mock_client.complete.call_args[0][1]
            system_prompt = mock_client.complete.call_args[0][0]
            self.assertIn("ATHLETE'S NOTE FOR THIS ADAPTATION", user_content)
            # Surrounding whitespace is trimmed before rendering.
            self.assertIn("knee is sore, keep impact low", user_content)
            self.assertNotIn("  knee is sore", user_content)
            self.assertIn("### ATHLETE'S NOTE FOR TODAY", system_prompt)

            # No message → the section is absent (message-less run is unchanged).
            mock_client.complete.reset_mock()
            mock_client.complete.return_value = {
                "change_needed": False,
                "reason": "On track.",
                "adapted_workouts": [],
            }
            coach_service.workout_adapt("2026-06-03")
            self.assertNotIn(
                "ATHLETE'S NOTE FOR THIS ADAPTATION",
                mock_client.complete.call_args[0][1],
            )

    def _save_two_mesocycle_plan(self):
        """Saves a plan whose first mesocycle ends 2026-06-30 and whose second opens 2026-07-01."""
        self._clear_plans()
        obj_id = test_db.add_objective(
            title="Zurich Marathon", target_date="2026-10-15",
            sport_type="running",
        )
        test_db.save_macrocycle(
            objective_id=obj_id,
            strategy="Build aerobic base, then sharpen.",
            goals_hash="hash1",
            constraints_hash="hash2",
            mesocycles=[
                {"name": "Base Building", "start_date": "2026-06-01",
                 "end_date": "2026-06-30", "focus": "Zone 2 runs"},
                {"name": "Peak & Taper", "start_date": "2026-07-01",
                 "end_date": "2026-07-21", "focus": "Race pace"},
            ],
        )

    @patch("stamind.coach.engine.openrouter_client")
    def test_adapt_terminal_window_section_in_prompt(self, mock_client):
        """Near the mesocycle's end the prompt warns the model that an easing cannot rebound and
        the next mesocycle is out of reach; mid-mesocycle that section is absent entirely
        (DESIGN_mesocycle_boundary.md §3)."""
        self._save_two_mesocycle_plan()
        with patch.dict(stamind.config.config.data, {
            "user_profile": {"lthr": 165, "max_hr": 185},
            "coach": {
                "metrics_lookback_days": 3,
                "minor_activity_load_threshold": 10.0,
            }
        }):
            mock_client.complete.return_value = {
                "change_needed": False,
                "reason": "On track.",
                "adapted_workouts": [],
            }
            test_db.save_metric_cache("2026-06-28", 56, 42, 60, 35, 14.0, 8.0, 1.75)
            test_db.save_baseline("2026-06-28", 50.0, 2.0, 60.0, 5.0, 80.0, 5.0)

            # Two days before the mesocycle ends -> inside the default 3-day terminal window.
            coach_service.workout_adapt("2026-06-28")
            system_prompt = mock_client.complete.call_args[0][0]
            self.assertIn("THIS MESOCYCLE IS ENDING", system_prompt)
            self.assertIn("ends in 2 day(s), on 2026-06-30", system_prompt)

            # Mid-mesocycle -> the section is omitted (prompt unchanged for the common case).
            mock_client.complete.reset_mock()
            mock_client.complete.return_value = {
                "change_needed": False,
                "reason": "On track.",
                "adapted_workouts": [],
            }
            coach_service.workout_adapt("2026-06-10")
            self.assertNotIn("THIS MESOCYCLE IS ENDING", mock_client.complete.call_args[0][0])

    @patch("stamind.coach.engine.openrouter_client")
    def test_the_shared_revision_sections_render_adapts_scope(self, mock_client):
        """The benchmark and vacate sections are built by helpers rather than written
        inline, so what has to hold here is that adapt gets their wording in full
        (DESIGN_adapt_task_prompt.md §2)."""
        with patch.dict(stamind.config.config.data, {
            "user_profile": {"lthr": 165, "max_hr": 185},
            "coach": {"metrics_lookback_days": 3, "minor_activity_load_threshold": 10.0},
        }):
            mock_client.complete.return_value = {
                "change_needed": False, "reason": "On track.", "adapted_workouts": [],
            }
            test_db.save_metric_cache("2026-06-10", 50, 60, 80, 20, 10.0, 8.0, 1.2)
            test_db.save_baseline("2026-06-10", 50.0, 2.0, 60.0, 5.0, 80.0, 5.0)
            coach_service.workout_adapt("2026-06-10")
            system_prompt = mock_client.complete.call_args[0][0]

        # Always-on: an ordinary move needs the encoding as much as a test move does,
        # and only the benchmark section used to state it.
        self.assertIn("### MOVING A SESSION TO ANOTHER DAY", system_prompt)
        # Rule 2 keeps adapt's own three signals, not the window pass's constraint wording.
        self.assertIn("a depressed morning, a note, a drift reading", system_prompt)
        self.assertNotIn("No constraint, however disruptive,", system_prompt)
        # The benchmark section keeps the mesocycle scope its postponement escape rests on.
        self.assertIn("to a later day within THIS mesocycle", system_prompt)
        self.assertIn(
            "The next generated mesocycle re-places the test when it is due.", system_prompt
        )

    def _seed_mesocycle_with_drift(self):
        """A 3-week-elapsed mesocycle whose 'easy' running has drifted into Z3."""
        self._clear_plans()
        obj_id = test_db.add_objective(
            title="Autumn Half", target_date="2026-09-01",
            sport_type="running",
        )
        test_db.save_macrocycle(
            objective_id=obj_id, strategy="s", goals_hash="g", constraints_hash="c",
            mesocycles=[{
                "name": "Base 2", "start_date": "2026-06-01",
                "end_date": "2026-06-28", "focus": "aerobic volume",
            }],
        )
        for i, day in enumerate(("2026-06-02", "2026-06-09", "2026-06-16")):
            test_db.save_completed_activity(
                f"drift_{i}", day, f"{day} 08:00:00", "Easy Run", "running",
                5400.0, 12.0, 80.0, 150, 172, None, 70.0,
                zone1_sec=300, zone2_sec=1800, zone3_sec=2700, zone4_sec=600,
                zone5_sec=0,
            )

    @patch("stamind.coach.engine.openrouter_client")
    def test_adapt_prompt_carries_the_measured_distribution_and_drift_branch(
        self, mock_client
    ):
        """§9.3/§9.4: the mesocycle's measured distribution reaches the adapt prompt as its
        own section, and it gates both the fourth TASK branch and CORRECTING EXECUTION
        DRIFT — the case no other branch covers, since the athlete showed up for
        everything and feels fine."""
        self._seed_mesocycle_with_drift()
        mock_client.complete.return_value = {"change_needed": False, "reason": "ok"}
        coach_service.workout_adapt("2026-06-24")

        system_prompt, user_content = mock_client.complete.call_args[0][:2]
        flat = " ".join(user_content.split())
        self.assertIn("MEASURED INTENSITY DISTRIBUTION OF THE ACTIVE MESOCYCLE", flat)
        self.assertIn('Base 2 — focus "aerobic volume"', flat)
        self.assertIn("Z3 tempo", flat)
        self.assertIn("Current week so far", flat)
        self.assertIn("NOT extrapolated", flat)
        self.assertIn("### CORRECTING EXECUTION DRIFT", system_prompt)
        self.assertIn("even when\n  recovery metrics are fine", system_prompt)
        # §9.2: adapt may move a session's intensity, never the mesocycle's composition.
        self.assertIn("belongs to the next `workout generate`", system_prompt)
        # §4.1: the mesocycle-over-mesocycle delta is a generate view; adapt must not see it.
        self.assertNotIn("Change vs", user_content)

    @patch("stamind.coach.engine.openrouter_client")
    def test_adapt_refuses_without_a_plan(self, mock_client):
        """Every judgement adapt makes is relative to the mesocycle, so with no plan there is
        nothing to adapt towards: refuse rather than invent a bare 7-day range
        (DESIGN_mesocycle_boundary.md §6). No LLM call is made."""
        self._clear_plans()
        with self.assertRaises(ValueError) as ctx:
            coach_service.workout_adapt("2026-06-24")
        self.assertIn("plan generate", str(ctx.exception))
        mock_client.complete.assert_not_called()
