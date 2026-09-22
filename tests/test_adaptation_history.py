"""What `workout adapt` may not rewrite: a day past the mesocycle it is working
in, and a session the athlete has already performed.
"""
import io
import os
import unittest
from datetime import date
from contextlib import redirect_stdout
from unittest.mock import patch

from tests.helpers import (
    clear_all_tables, rebind_test_db, save_workout, skip_strength_planner,
)
from tests import test_db_path

TEST_DB_PATH = test_db_path("test_adaptation_history.db")

from stamind.db import Database
import stamind.config

test_db = Database(db_path=TEST_DB_PATH)
rebind_test_db(test_db)

from stamind.analytics.adherence import REST_VIOLATION, analyze_adherence
from stamind.coach.service import CoachService, coach_service
from stamind.sports import canonical_sport


class TestAdaptLeavesHistoryAlone(unittest.TestCase):
    """A session already performed is locked history, and the next mesocycle is
    out of adapt's reach — on the write side as well as in the prompt."""

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
    def test_adapt_drops_proposal_past_mesocycle_end(self, mock_client):
        """The next mesocycle is out of adapt's reach on the write side too: a proposal dated
        past the mesocycle's end is dropped, so the applied range can never stretch into the next
        mesocycle (DESIGN_mesocycle_boundary.md §1)."""
        self._save_two_mesocycle_plan()
        with patch.dict(stamind.config.config.data, {
            "user_profile": {"lthr": 165, "max_hr": 185},
            "coach": {
                "metrics_lookback_days": 3,
                "minor_activity_load_threshold": 10.0,
            }
        }):
            # The model invents a session in the NEXT mesocycle (starts 2026-07-01) alongside a
            # legitimate in-mesocycle one.
            mock_client.complete.return_value = {
                "change_needed": True,
                "reason": "Ease into the mesocycle's last days.",
                "adapted_workouts": [
                    {
                        "date": "2026-06-29", "sport_type": "running",
                        "title": "Easy Run", "description": "30 mins easy Z2",
                        "duration_minutes": 30, "rpe": 4, "tss": 20.0,
                    },
                    {
                        "date": "2026-07-02", "sport_type": "running",
                        "title": "Next-mesocycle Session (should be dropped)",
                        "description": "Past the boundary.",
                        "duration_minutes": 60, "rpe": 7, "tss": 55.0,
                    },
                ],
            }
            test_db.save_metric_cache("2026-06-28", 56, 42, 60, 35, 14.0, 8.0, 1.75)
            test_db.save_baseline("2026-06-28", 50.0, 2.0, 60.0, 5.0, 80.0, 5.0)

            _p = coach_service.workout_adapt("2026-06-28")
            _reason, proposed, _new_constraints = _p.reason, _p.workouts, _p.new_constraints

            self.assertEqual([p["date"] for p in proposed], ["2026-06-29"])

    @patch("stamind.coach.engine.openrouter_client")
    def test_adapt_drops_already_completed_session(self, mock_client):
        """A session already performed (matched by a completed activity) is locked history:
        the guard drops any proposal targeting it, even if the model returns one — you cannot
        adapt a workout you have already finished today."""
        test_profile = {"lthr": 165, "max_hr": 185}
        with patch.dict(stamind.config.config.data, {
            "user_profile": test_profile,
            "coach": {
                "metrics_lookback_days": 3,
                "minor_activity_load_threshold": 10.0,
            }
        }):
            # The model tries to "adapt" today's already-completed ride (date == eval date),
            # plus legitimately adapt a future session still ahead of the athlete.
            mock_client.complete.return_value = {
                "change_needed": True,
                "reason": "Mild fatigue; ease the upcoming interval session.",
                "adapted_workouts": [
                    {
                        "date": "2026-06-03",
                        "sport_type": "cycling",
                        "title": "Rewritten Ride (should be dropped)",
                        "description": "Restating the finished ride to match actual.",
                        "duration_minutes": 82,
                        "rpe": 4,
                        "tss": 52.0,
                    },
                    {
                        "date": "2026-06-04",
                        "sport_type": "running",
                        "title": "Eased Intervals",
                        "description": "Cut intensity for the future session.",
                        "duration_minutes": 40,
                        "rpe": 5,
                        "tss": 35.0,
                    },
                ],
            }

            test_db.save_metric_cache("2026-06-03", 56, 42, 60, 35, 14.0, 8.0, 1.75)
            test_db.save_baseline("2026-06-03", 50.0, 2.0, 60.0, 5.0, 80.0, 5.0)

            # Today's planned ride and a future running session.
            save_workout(test_db,
                "2026-06-03", "cycling", "Aerobic Base Endurance", "70 mins",
                duration_minutes=70, rpe=4, tss=45,
            )
            save_workout(test_db,
                "2026-06-04", "running", "Interval Session", "45 mins",
                duration_minutes=45, rpe=8, tss=60,
            )

            # The ride was actually completed today — this is what locks it.
            test_db.save_completed_activity(
                "act_ride", "2026-06-03", "2026-06-03 08:00:00", "Zwift Ride",
                "cycling", 4920.0, 30.0, 250.0, 132, 150, 4, 52.0,
            )

            _p = coach_service.workout_adapt("2026-06-03")
            reason, proposed, _new_constraints = _p.reason, _p.workouts, _p.new_constraints

            dates = {p["date"] for p in proposed}
            self.assertNotIn("2026-06-03", dates)  # completed session dropped
            self.assertEqual(len(proposed), 1)
            self.assertEqual(proposed[0]["date"], "2026-06-04")
            self.assertEqual(proposed[0]["title"], "Eased Intervals")

            # The completed session is surfaced to the model as locked history (the
            # authoritative signal), not left for it to re-derive from the activity list.
            prompt_user_content = mock_client.complete.call_args[0][1]
            self.assertIn(
                "Aerobic Base Endurance | Expected duration: 70m, RPE: 4, TSS: 45 "
                "[COMPLETED — locked history, not adaptable]",
                prompt_user_content,
            )

    @patch("stamind.coach.engine.openrouter_client")
    def test_adapt_rest_day_does_not_displace_a_completed_session(self, mock_client):
        """Dropping the day's OTHER session must not take the finished one with it.

        Observed 2026-08-30: the athlete rode a 150-minute Z2 session and then said they
        were skipping the afternoon kettlebell workout. The week planner encoded that as a single
        `rest` entry for the day, and the displacement rule read the finished ride — whose
        sport the entry never names — as a session the week planner wanted gone
        (DESIGN_workout_revisions.md §9.2).
        """
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
                "reason": "Athlete is dropping today's lift.",
                "adapted_workouts": [
                    {
                        "date": "2026-06-03",
                        "sport_type": "rest",
                        "title": "Rest — Kettlebell Session Dropped",
                        "description": "No lift today; the long Z2 ride is done.",
                        "duration_minutes": 0,
                        "rpe": 0,
                        "tss": 0,
                    },
                ],
            }

            test_db.save_metric_cache("2026-06-03", 56, 42, 60, 35, 14.0, 8.0, 1.75)
            test_db.save_baseline("2026-06-03", 50.0, 2.0, 60.0, 5.0, 80.0, 5.0)

            save_workout(test_db,
                "2026-06-03", "cycling", "Long Indoor Z2", "120 mins",
                duration_minutes=120, rpe=4, tss=92,
            )
            save_workout(test_db,
                "2026-06-03", "strength_training", "Kettlebell Strength", "45 mins",
                duration_minutes=45, rpe=5, tss=20,
            )

            # Ridden in full — longer than planned, so it locks.
            test_db.save_completed_activity(
                "act_ride", "2026-06-03", "2026-06-03 09:00:00", "Indoor Cycling",
                "indoor_cycling", 8994.0, 55.0, 0.0, 133, 147, 4, 107.7,
            )

            proposal = coach_service.workout_adapt("2026-06-03")

            # The ride is spoken for by history, so it is neither rewritten nor deleted.
            self.assertIn(("2026-06-03", "cycling"), proposal.held)
            self.assertEqual(proposal.removals, ())
            # The rest entry lands on the session actually being dropped.
            swaps = [p for p in proposal.pairs if p.is_swap]
            self.assertEqual(len(swaps), 1)
            self.assertEqual(swaps[0].original["sport_type"], "strength_training")

            service = CoachService(db_instance=test_db)
            with redirect_stdout(io.StringIO()):
                service.workout_revision_apply(proposal)

            ride = test_db.get_workout("2026-06-03", "cycling")
            self.assertIsNotNone(ride, "the completed ride was voided by the rest day")
            self.assertEqual(ride["title"], "Long Indoor Z2")
            self.assertEqual(ride["duration_minutes"], 120)
            self.assertEqual(ride["adaptation_count"], 0)
            self.assertIsNone(test_db.get_workout("2026-06-03", "strength_training"))

            # And the rest day it left behind is not read back as a rest broken: the ride
            # pairs with its own session first, so tomorrow's coach sees a day that went
            # as revised, not an athlete who trained through a rest day.
            discrepancies, _m, _i = analyze_adherence(
                planned_workouts=test_db.get_workouts(
                    start_date="2026-06-03", end_date="2026-06-03"
                ),
                completed_activities=test_db.get_completed_activities(
                    start_date="2026-06-03", end_date="2026-06-03"
                ),
                start_date_obj=date(2026, 6, 3), history_days=1,
                minor_activity_load_threshold=10.0,
            )
            self.assertEqual([d for d in discrepancies if d.kind == REST_VIOLATION], [])

    @patch("stamind.coach.engine.openrouter_client")
    def test_rest_constraint_does_not_clear_a_completed_session(self, mock_client):
        """A `rest` constraint outranks a hold (§6 over §9.1) but not history: the day's
        remaining session is forced to rest while the finished one stands (§9.2)."""
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
            test_db.add_constraint(
                title="Family day", start_date="2026-06-03", end_date="2026-06-03",
                rest=1,
            )

            save_workout(test_db,
                "2026-06-03", "cycling", "Long Indoor Z2", "120 mins",
                duration_minutes=120, rpe=4, tss=92,
            )
            save_workout(test_db,
                "2026-06-03", "strength_training", "Kettlebell Strength", "45 mins",
                duration_minutes=45, rpe=5, tss=20,
            )
            test_db.save_completed_activity(
                "act_ride", "2026-06-03", "2026-06-03 09:00:00", "Indoor Cycling",
                "indoor_cycling", 8994.0, 55.0, 0.0, 133, 147, 4, 107.7,
            )

            proposal = coach_service.workout_adapt("2026-06-03")
            self.assertIn(("2026-06-03", "cycling"), proposal.held)

            service = CoachService(db_instance=test_db)
            with redirect_stdout(io.StringIO()):
                service.workout_revision_apply(proposal)

            ride = test_db.get_workout("2026-06-03", "cycling")
            self.assertIsNotNone(ride, "the rest constraint voided a finished ride")
            self.assertEqual(ride["title"], "Long Indoor Z2")
            self.assertIsNone(test_db.get_workout("2026-06-03", "strength_training"))

    @patch("stamind.coach.engine.openrouter_client")
    def test_adapt_abandoned_session_is_partial_not_completed(self, mock_client):
        """A session the athlete abandoned after the warm-up is NOT completed history.

        `indoor_cardio` is an alias of `strength_training`, so a 10-minute warm-up pairs
        with the 65-minute lift it preceded. The prompt used to call that pairing
        "[COMPLETED — locked history, not adaptable]" and the guard dropped any proposal
        touching it, so the week planner was told a session the athlete never did was in the bank
        and forbidden from salvaging the rest of the day (ARCHITECTURE.md §15)."""
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
                "reason": "Only the warm-up happened; salvage a short lift tonight.",
                "adapted_workouts": [
                    {
                        "date": "2026-06-03",
                        "sport_type": "rest",
                        "title": "Rest Day (Lift Abandoned)",
                        "description": "Paged after the warm-up; the day is a wash.",
                        "duration_minutes": 0,
                        "rpe": 0,
                        "tss": 0,
                    },
                ],
            }

            test_db.save_metric_cache("2026-06-03", 56, 42, 60, 35, 14.0, 8.0, 1.75)
            test_db.save_baseline("2026-06-03", 50.0, 2.0, 60.0, 5.0, 80.0, 5.0)

            save_workout(test_db,
                "2026-06-03", "strength_training", "Full-Body Strength", "65 mins",
                duration_minutes=65, rpe=6, tss=30,
            )
            # Ten minutes of warm-up and nothing else — the athlete stopped there.
            test_db.save_completed_activity(
                "act_warmup", "2026-06-03", "2026-06-03 12:00:00", "Warm-up",
                "indoor_cardio", 600.0, 1.6, None, 107, 120, 1, 1.6,
            )

            _p = coach_service.workout_adapt("2026-06-03")
            proposed = _p.workouts

            prompt_user_content = mock_client.complete.call_args[0][1]
            # The tag tells the truth: partial, with what was actually performed, and the
            # day is not over so the rest of the session is still on the table.
            self.assertIn("[PARTIAL — performed so far today: 10m, load 1.6;",
                          prompt_user_content)
            self.assertNotIn("Full-Body Strength | Expected duration: 65m, RPE: 6, TSS: 30 "
                             "[COMPLETED", prompt_user_content)
            # ...and the guard no longer drops the write-off the model proposed for today,
            # which swaps the abandoned lift out for rest so the calendar records the day
            # that actually happened.
            self.assertEqual([p["date"] for p in proposed], ["2026-06-03"])
            self.assertEqual(proposed[0]["sport_type"], "rest")
            swaps = [p for p in _p.pairs if p.is_swap]
            self.assertEqual(len(swaps), 1)
            self.assertEqual(
                canonical_sport(swaps[0].original["sport_type"]), "strength_training"
            )
