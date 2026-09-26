"""Which of the week planner's answers are real changes to the schedule, and
which are it naming a session so that nothing displaces it.
"""
import io
import os
import unittest
from contextlib import redirect_stdout
from unittest.mock import patch

from tests.helpers import (
    clear_all_tables, rebind_test_db, save_workout, skip_strength_planner,
)
from tests import test_db_path

TEST_DB_PATH = test_db_path("test_adaptation_revisions.db")

from stamind.db import Database
import stamind.config

test_db = Database(db_path=TEST_DB_PATH)
rebind_test_db(test_db)

from stamind.coach.service import CoachService, coach_service


class TestAdaptRevisions(unittest.TestCase):
    """A session re-listed unchanged is held, not rewritten and not deleted; a
    softened zone target is a change even when the words and the load hold."""

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

    @patch("stamind.coach.engine.openrouter_client")
    def test_adapt_drops_noop_relisted_session(self, mock_client):
        """No-op backstop: if the model re-lists a session unchanged (here verbatim, plus a
        cosmetic whitespace-only variant), it is dropped so an untouched session is never
        re-stamped as adapted. A genuinely changed session on the same run is kept."""
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
                "reason": "Mostly on track; only the Friday tempo needs easing.",
                "adapted_workouts": [
                    # Verbatim re-list of the planned session — a no-op, must be dropped.
                    {
                        "date": "2026-06-04",
                        "sport_type": "running",
                        "title": "Easy Run",
                        "description": "30 mins easy Z2",
                        "duration_minutes": 30,
                        "rpe": 4,
                        "tss": 20.0,
                    },
                    # Same content but cosmetic whitespace churn + int/float tss — still a
                    # no-op, must be dropped.
                    {
                        "date": "2026-06-05",
                        "sport_type": "cycling",
                        "title": "Endurance Ride",
                        "description": "60 mins  aerobic   base",
                        "duration_minutes": 60,
                        "rpe": 5,
                        "tss": 40,
                    },
                    # Genuine change — must survive.
                    {
                        "date": "2026-06-06",
                        "sport_type": "running",
                        "title": "Eased Tempo",
                        "description": "Cut to easy Z2 to shed intensity.",
                        "duration_minutes": 35,
                        "rpe": 5,
                        "tss": 30.0,
                    },
                ],
            }

            test_db.save_metric_cache("2026-06-03", 50, 60, 80, 20, 10.0, 8.0, 1.1)
            test_db.save_baseline("2026-06-03", 50.0, 2.0, 60.0, 5.0, 80.0, 5.0)

            save_workout(test_db,
                "2026-06-04", "running", "Easy Run", "30 mins easy Z2",
                duration_minutes=30, rpe=4, tss=20,
            )
            save_workout(test_db,
                "2026-06-05", "cycling", "Endurance Ride", "60 mins aerobic base",
                duration_minutes=60, rpe=5, tss=40,
            )
            save_workout(test_db,
                "2026-06-06", "running", "Friday Tempo", "45 mins w/ tempo intervals",
                duration_minutes=45, rpe=7, tss=55,
            )

            _p = coach_service.workout_adapt("2026-06-03")
            reason, proposed, _new_constraints = _p.reason, _p.workouts, _p.new_constraints

            dates = {p["date"] for p in proposed}
            self.assertEqual(dates, {"2026-06-06"})
            self.assertEqual(len(proposed), 1)
            self.assertEqual(proposed[0]["title"], "Eased Tempo")

    @patch("stamind.coach.engine.openrouter_client")
    def test_adapt_keeps_a_revision_that_only_moves_the_intensity_target(self, mock_client):
        """A softened zone target is a change, even when the words and the load hold.

        The backstop used to compare five fields — title, description, duration, RPE and
        TSS — so a session re-written with the same prose and the same 60 minutes, and
        only its Z2 minutes moved down into Z1, was read as a verbatim re-list and
        dropped. The athlete's day then kept the target the coach had just eased. The
        write path and the preview both count the target, and now so does this
        (DESIGN_intensity_distribution.md §9.8)."""
        with patch.dict(stamind.config.config.data, {
            "user_profile": {"lthr": 165, "max_hr": 185},
            "coach": {"metrics_lookback_days": 3, "minor_activity_load_threshold": 10.0},
        }):
            mock_client.complete.return_value = {
                "change_needed": True,
                "reason": "HRV is down, so the aerobic work goes easier.",
                "adapted_workouts": [
                    {
                        "date": "2026-06-04",
                        "sport_type": "running",
                        "title": "Easy Run",
                        "description": "60 mins easy",
                        "duration_minutes": 60,
                        "rpe": 4,
                        "tss": 40.0,
                        "planned_zone_currency": "hr",
                        "planned_zone_sec": [1800, 1800, 0, 0, 0],
                    },
                ],
            }

            test_db.save_metric_cache("2026-06-03", 50, 60, 80, 20, 10.0, 8.0, 1.1)
            test_db.save_baseline("2026-06-03", 50.0, 2.0, 60.0, 5.0, 80.0, 5.0)
            save_workout(test_db,
                "2026-06-04", "running", "Easy Run", "60 mins easy",
                duration_minutes=60, rpe=4, tss=40,
                planned_zone_currency="hr", planned_zone_sec=[0, 2400, 0, 0, 0],
            )

            proposal = coach_service.workout_adapt("2026-06-03")
            proposed = proposal.workouts

            self.assertEqual([p["date"] for p in proposed], ["2026-06-04"])
            self.assertEqual(proposed[0]["planned_zone_sec"][:2], [1800, 1800])

            # And it reaches the row: the target used to be asked for, returned, and then
            # dropped by the proposal's row shape, so the day kept its old one.
            coach_service.workout_revision_apply(proposal)
            live = test_db.get_workout("2026-06-04", "running")
            self.assertEqual(live["planned_zone_currency"], "hr")
            self.assertEqual(
                (live["planned_zone1_sec"], live["planned_zone2_sec"]), (1800, 1800)
            )

    @patch("stamind.coach.engine.openrouter_client")
    def test_the_short_name_the_week_planner_writes_reaches_the_row(self, mock_client):
        """DESIGN_calendar_miniapp.md §3.6: the prompt asks for it, and apply stores it."""
        with patch.dict(stamind.config.config.data, {
            "user_profile": {"lthr": 165, "max_hr": 185},
            "coach": {"metrics_lookback_days": 3, "minor_activity_load_threshold": 10.0},
        }):
            mock_client.complete.return_value = {
                "change_needed": True,
                "reason": "Short on time Thursday.",
                "adapted_workouts": [{
                    "date": "2026-06-04", "sport_type": "running",
                    "title": "Short hill repeats", "short_name": "Hills",
                    "description": "4x90s uphill", "duration_minutes": 40,
                    "rpe": 7, "tss": 45,
                }],
            }
            test_db.save_metric_cache("2026-06-03", 50, 60, 80, 20, 10.0, 8.0, 1.1)
            test_db.save_baseline("2026-06-03", 50.0, 2.0, 60.0, 5.0, 80.0, 5.0)
            save_workout(test_db,
                "2026-06-04", "running", "Hill repeats", "6x90s uphill",
                duration_minutes=60, rpe=7, tss=60,
            )

            proposal = coach_service.workout_adapt("2026-06-03")
            self.assertIn('"short_name"', mock_client.complete.call_args.args[0])
            coach_service.workout_revision_apply(proposal)

            live = test_db.get_workout("2026-06-04", "running")
            self.assertEqual(live["title"], "Short hill repeats")
            self.assertEqual(live["short_name"], "Hills")

    @patch("stamind.coach.engine.openrouter_client")
    def test_adapt_holds_a_relisted_session_instead_of_deleting_it(self, mock_client):
        """A verbatim re-list is the model protecting a same-day session of another sport
        from the displacement rule. Dropping it as a no-op used to delete the very session
        it was protecting, because the same list decides what a date keeps (§9.1)."""
        with patch.dict(stamind.config.config.data, {
            "user_profile": {"lthr": 165, "max_hr": 185},
            "coach": {
                "metrics_lookback_days": 3,
                "minor_activity_load_threshold": 10.0,
            }
        }):
            mock_client.complete.return_value = {
                "change_needed": True,
                "reason": "On-call weekend forbids outdoor riding; same session indoors.",
                "adapted_workouts": [
                    {
                        "date": "2026-06-05", "sport_type": "cycling",
                        "title": "Climb Threshold — Indoors",
                        "change_reason": "On-call weekend; moved onto a Zwift climb.",
                        "description": "85 mins, 2x20 at threshold on the trainer.",
                        "duration_minutes": 85, "rpe": 7, "tss": 84,
                    },
                    # Verbatim re-list: "listed only so the ride does not displace it".
                    {
                        "date": "2026-06-05", "sport_type": "strength_training",
                        "title": "Kettlebell Full-Body",
                        "change_reason": "Unchanged; listed only so the ride keeps it.",
                        "description": "35 mins non-failure kettlebell work.",
                        "duration_minutes": 35, "rpe": 6, "tss": 15,
                    },
                ],
            }
            test_db.save_metric_cache("2026-06-03", 50, 60, 80, 20, 10.0, 8.0, 1.1)
            test_db.save_baseline("2026-06-03", 50.0, 2.0, 60.0, 5.0, 80.0, 5.0)

            save_workout(test_db,
                "2026-06-05", "cycling", "Climb Threshold — Outdoors",
                "85 mins, 2x20 at threshold on the Witikon climb.",
                duration_minutes=85, rpe=7, tss=84,
            )
            save_workout(test_db,
                "2026-06-05", "strength_training", "Kettlebell Full-Body",
                "35 mins non-failure kettlebell work.",
                duration_minutes=35, rpe=6, tss=15,
            )

            proposal = coach_service.workout_adapt("2026-06-03")

            # The re-list appends nothing — it is not a change.
            self.assertEqual(
                [(w["date"], w["sport_type"]) for w in proposal.workouts],
                [("2026-06-05", "cycling")],
            )
            # ...but it is not a removal either. The preview must not offer to delete it.
            self.assertEqual(proposal.removals, ())
            self.assertEqual(proposal.held, (("2026-06-05", "strength_training"),))

            service = CoachService(db_instance=test_db)
            with redirect_stdout(io.StringIO()):
                service.workout_revision_apply(proposal)

            lift = test_db.get_workout("2026-06-05", "strength_training")
            self.assertIsNotNone(lift, "the held lift was deleted by the ride's revision")
            self.assertEqual(lift["title"], "Kettlebell Full-Body")
            # Held means held: no revision row, so no adaptation is recorded against it.
            self.assertEqual(lift["adaptation_count"], 0)
            self.assertIsNone(lift["adapted_at"])

    @patch("stamind.coach.engine.openrouter_client")
    def test_adapt_keep_marker_holds_a_session_without_restating_it(self, mock_client):
        """`{"keep": true}` says "hold this, I am only naming it so it is not displaced".
        It costs no prose, so it cannot drift into a spurious adaptation the way a
        verbatim re-list does (§9.1)."""
        with patch.dict(stamind.config.config.data, {
            "user_profile": {"lthr": 165, "max_hr": 185},
            "coach": {
                "metrics_lookback_days": 3,
                "minor_activity_load_threshold": 10.0,
            }
        }):
            mock_client.complete.return_value = {
                "change_needed": True,
                "reason": "On-call weekend forbids outdoor riding; same session indoors.",
                "adapted_workouts": [
                    {
                        "date": "2026-06-05", "sport_type": "cycling",
                        "title": "Climb Threshold — Indoors",
                        "change_reason": "On-call weekend; moved onto a Zwift climb.",
                        "description": "85 mins, 2x20 at threshold on the trainer.",
                        "duration_minutes": 85, "rpe": 7, "tss": 84,
                    },
                    {
                        "date": "2026-06-05", "sport_type": "strength_training",
                        "keep": True,
                    },
                ],
            }
            test_db.save_metric_cache("2026-06-03", 50, 60, 80, 20, 10.0, 8.0, 1.1)
            test_db.save_baseline("2026-06-03", 50.0, 2.0, 60.0, 5.0, 80.0, 5.0)

            save_workout(test_db,
                "2026-06-05", "cycling", "Climb Threshold — Outdoors",
                "85 mins, 2x20 at threshold on the Witikon climb.",
                duration_minutes=85, rpe=7, tss=84,
            )
            save_workout(test_db,
                "2026-06-05", "strength_training", "Kettlebell Full-Body",
                "35 mins non-failure kettlebell work.",
                duration_minutes=35, rpe=6, tss=15,
            )

            proposal = coach_service.workout_adapt("2026-06-03")

            self.assertEqual(
                [(w["date"], w["sport_type"]) for w in proposal.workouts],
                [("2026-06-05", "cycling")],
            )
            self.assertEqual(proposal.removals, ())
            self.assertEqual(proposal.held, (("2026-06-05", "strength_training"),))

            service = CoachService(db_instance=test_db)
            with redirect_stdout(io.StringIO()):
                service.workout_revision_apply(proposal)

            lift = test_db.get_workout("2026-06-05", "strength_training")
            self.assertIsNotNone(lift)
            self.assertEqual(lift["description"], "35 mins non-failure kettlebell work.")
            self.assertEqual(lift["adaptation_count"], 0)
