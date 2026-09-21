"""A session carried to another day: what it takes with it, what it leaves
behind, and what it may not displace.
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

TEST_DB_PATH = test_db_path("test_adaptation_moves.db")

from stamind.db import Database
import stamind.config

test_db = Database(db_path=TEST_DB_PATH)
rebind_test_db(test_db)

from stamind.coach.service import CoachService, coach_service
from stamind.coach.proposals import RevisionProposal


class TestAdaptMoves(unittest.TestCase):
    """The benchmark flag travels with the test rather than staying on the date, a
    swap inherits the session it displaced, and the day a move emptied is
    left carrying the coach's sentence rather than a hole."""

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

    def test_adapt_replacing_a_benchmark_strips_its_flag(self):
        """The flag belongs to the test, not to its date: a session that takes over a
        test's date and does not re-emit benchmark_type must not inherit it, or a social
        ride is filed as an FTP result and the mesocycle believes it already tested
        (DESIGN_benchmark_workouts.md §4.2)."""
        save_workout(test_db,
            "2026-06-24", "cycling", "FTP Test", "[FTP Test]\n20-min test or ramp.",
            duration_minutes=75, rpe=9, tss=90, benchmark_type="ftp_20min",
        )
        service = CoachService(db_instance=test_db)
        proposed = [{
            "date": "2026-06-24", "sport_type": "cycling", "title": "Friends Group Ride",
            "description": "[Friends Group Ride]\n90 min social pace.",
            "modification_reason": "Athlete riding with friends; test postponed.",
            "duration_minutes": 90, "rpe": 5, "tss": 60,
        }]
        service.workout_revision_apply(RevisionProposal(
            reason="Social ride replaces the test", workouts=proposed, new_constraints=[],
            range_start="2026-06-24", range_end="2026-06-24",
        ))
        row = test_db.get_workout("2026-06-24", "cycling")
        self.assertEqual(row["title"], "Friends Group Ride")
        self.assertIsNone(row["benchmark_type"])

    def test_adapt_moving_a_benchmark_carries_the_flag_to_its_new_date(self):
        """A move emits the test on its new date and a replacement on the old one. The
        test keeps its flag; the replacement left behind loses it
        (DESIGN_benchmark_workouts.md §4.2)."""
        save_workout(test_db,
            "2026-06-24", "cycling", "FTP Test", "[FTP Test]\n20-min test or ramp.",
            duration_minutes=75, rpe=9, tss=90, benchmark_type="ftp_20min",
        )
        service = CoachService(db_instance=test_db)
        proposed = [
            {
                "date": "2026-06-24", "sport_type": "cycling", "title": "Easy Spin",
                "description": "[Easy Spin]\n45 min Z1.",
                "modification_reason": "Freshening up for the test moved to Friday.",
                "duration_minutes": 45, "rpe": 2, "tss": 25,
            },
            {
                "date": "2026-06-26", "sport_type": "cycling", "title": "FTP Test",
                "description": "[FTP Test]\n20-min test or ramp.",
                "modification_reason": "Moved intact — TSB negative on Wednesday.",
                "duration_minutes": 75, "rpe": 9, "tss": 90,
                "benchmark_type": "ftp_20min",
            },
        ]
        service.workout_revision_apply(RevisionProposal(
            reason="Test moved to a fresher day", workouts=proposed, new_constraints=[],
            range_start="2026-06-24", range_end="2026-06-26",
        ))
        self.assertIsNone(test_db.get_workout("2026-06-24", "cycling")["benchmark_type"])
        self.assertEqual(
            test_db.get_workout("2026-06-26", "cycling")["benchmark_type"], "ftp_20min"
        )

    def test_adapt_swap_inherits_displaced_session_as_original(self):
        """A cross-sport swap (strength -> yoga) deletes the planned strength session
        and inserts a yoga one. The new session should inherit the displaced strength
        session's description + load as its `original_*` snapshot, so the Calendar event
        can surface what was originally planned."""
        save_workout(test_db,
            "2026-07-02", "strength_training", "Heavy Legs",
            "5x5 back squat + accessories.",
            duration_minutes=60, rpe=7, tss=70,
        )

        service = CoachService(db_instance=test_db)
        proposed = [{
            "date": "2026-07-02", "sport_type": "yoga", "title": "Easy Mobility",
            "description": "20 min easy mobility flow.",
            "modification_reason": "Swapped from strength after a workload spike.",
            "duration_minutes": 30, "rpe": 1, "tss": 4,
        }]
        service.workout_revision_apply(RevisionProposal(
            reason="Reduce load", workouts=proposed, new_constraints=[],
            range_start="2026-07-02", range_end="2026-07-02",
        ))

        # The strength row is gone; the yoga row carries the strength session's
        # planned description and load as its original snapshot.
        self.assertIsNone(test_db.get_workout("2026-07-02", "strength_training"))
        row = test_db.get_workout("2026-07-02", "yoga")
        self.assertEqual(row["description"], "20 min easy mobility flow.")
        self.assertEqual(row["original_description"], "5x5 back squat + accessories.")
        self.assertEqual(row["original_duration_minutes"], 60)
        self.assertEqual(row["original_tss"], 70)
        self.assertEqual(row["original_rpe"], 7)
        # Current load reflects the swapped-in yoga session.
        self.assertEqual(row["duration_minutes"], 30)
        self.assertEqual(row["tss"], 4)
        self.assertEqual(row["rpe"], 1)

    # -- a session that changes DAY (DESIGN_workout_revisions.md §11) --

    def _eased_thursday_gym(self):
        """Thursday 11 June holds a gym session two earlier adaptations have already
        walked down from 65 minutes to 45. Returns the session as it now stands."""
        save_workout(test_db,
            "2026-06-11", "strength_training", "Gym: Lower",
            "[Gym: Lower]\n5x5 back squat, accessories.",
            duration_minutes=65, rpe=7, tss=55,
            google_event_id="evt-gym",
        )
        service = CoachService(db_instance=test_db)
        for minutes, load in ((55, 45), (45, 35)):
            with redirect_stdout(io.StringIO()):
                service.workout_revision_apply(RevisionProposal(
                    reason="Recovery still below baseline",
                    range_start="2026-06-11", range_end="2026-06-13",
                    workouts=[{
                        "date": "2026-06-11", "sport_type": "strength_training",
                        "title": "Gym: Lower",
                        "description": f"[Gym: Lower]\n{minutes} min, lighter.",
                        "modification_reason": "Eased while recovery is low.",
                        "duration_minutes": minutes, "rpe": 6, "tss": load,
                    }],
                ))
        thursday = test_db.get_workout("2026-06-11", "strength_training")
        self.assertEqual(thursday["adaptation_count"], 2)
        return thursday

    def _adapt_returning(self, mock_client, reason, adapted, on="2026-06-10"):
        """Runs `workout adapt` on `on` against a canned week-planner answer."""
        with patch.dict(stamind.config.config.data, {
            "user_profile": {"lthr": 165, "max_hr": 185},
            "coach": {"metrics_lookback_days": 3,
                      "minor_activity_load_threshold": 10.0},
        }):
            mock_client.complete.return_value = {
                "change_needed": True, "reason": reason, "adapted_workouts": adapted,
            }
            test_db.save_metric_cache(on, 50, 60, 80, 20, 10.0, 8.0, 1.1)
            test_db.save_baseline(on, 50.0, 2.0, 60.0, 5.0, 80.0, 5.0)
            with redirect_stdout(io.StringIO()):
                return coach_service.workout_adapt(on)

    @patch("stamind.coach.engine.openrouter_client")
    def test_a_moved_session_keeps_its_history_and_its_easing_tally(self, mock_client):
        """It is Wednesday 10 June. Thursday's gym session has already been eased twice.
        The athlete is away Thursday evening, so the coach moves it to Friday and names
        the day it came from in `replaces`.

        Friday's session IS Thursday's session: what it was first prescribed as, the day
        it was first planned for and its easing tally all follow it. That tally is what
        the next morning's adapt reads before deciding whether to cut it again, and
        without the move being said out loud Friday would start over at zero
        (DESIGN_workout_revisions.md §4/§11)."""
        from stamind.coach.formatting import format_planned_workouts_detailed

        thursday = self._eased_thursday_gym()
        proposal = self._adapt_returning(
            mock_client, "Away Thursday evening, so the gym day moves to Friday.",
            [{
                "date": "2026-06-12", "sport_type": "strength_training",
                "title": "Gym: Lower",
                "description": "[Gym: Lower]\n45 min, lighter.",
                "change_reason": "Gym moved to Friday — you are away Thursday evening.",
                "duration_minutes": 45, "rpe": 6, "tss": 35,
                "replaces": {"date": "2026-06-11", "sport_type": "strength_training"},
            }],
        )
        # The move, and the rest day the app writes onto the day it emptied.
        self.assertEqual(
            [(w["date"], w["sport_type"]) for w in proposal.workouts],
            [("2026-06-12", "strength_training"), ("2026-06-11", "rest")],
        )
        self.assertEqual(proposal.removals, ())

        service = CoachService(db_instance=test_db)
        with redirect_stdout(io.StringIO()):
            service.workout_revision_apply(proposal)

        self.assertIsNone(test_db.get_workout("2026-06-11", "strength_training"))
        vacated = test_db.get_workout("2026-06-11", "rest")
        self.assertEqual(vacated["title"], "Rest Day")
        self.assertIn("away Thursday evening", vacated["description"])

        friday = test_db.get_workout("2026-06-12", "strength_training")
        self.assertEqual(friday["id"], thursday["id"], "same session, same lineage")
        # The athlete's calendar shows one event moving, not one deleted and one created:
        # the event handle is keyed by lineage (DESIGN_workout_revisions.md §8).
        self.assertEqual(friday["google_event_id"], "evt-gym")
        self.assertEqual(friday["adaptation_count"], 2)
        self.assertEqual(friday["original_date"], "2026-06-11")
        self.assertEqual(friday["original_duration_minutes"], 65)
        # And so the tag that stops a third cut still fires on Friday morning, carrying
        # the form the two easings started from.
        tag = format_planned_workouts_detailed([friday], eval_date="2026-06-12")
        self.assertIn("first prescribed as 65m", tag)
        self.assertIn("eased 2x", tag)

    @patch("stamind.coach.engine.openrouter_client")
    def test_a_move_leaves_the_day_it_emptied_carrying_the_coach_s_sentence(
        self, mock_client
    ):
        """Thursday is not left as a hole. An empty date and a planned rest day mean
        different things to the adherence record, so the day a move empties becomes a
        rest day — and it says where the session went, because that is the coach's own
        sentence about the change."""
        self._eased_thursday_gym()
        proposal = self._adapt_returning(
            mock_client, "The gym day moves to Friday.",
            [{
                "date": "2026-06-12", "sport_type": "strength_training",
                "title": "Gym: Lower", "description": "[Gym: Lower]\n45 min, lighter.",
                "change_reason": "Gym moved to Friday — you are away Thursday evening.",
                "duration_minutes": 45, "rpe": 6, "tss": 35,
                "replaces": {"date": "2026-06-11", "sport_type": "strength_training"},
            }],
        )
        rest = [w for w in proposal.workouts if w["date"] == "2026-06-11"][0]
        self.assertEqual(rest["sport_type"], "rest")
        self.assertEqual(rest["duration_minutes"], 0)
        self.assertEqual(
            rest["modification_reason"],
            "Gym moved to Friday — you are away Thursday evening.",
        )

    @patch("stamind.coach.engine.openrouter_client")
    def test_a_move_onto_a_day_that_already_carries_work_keeps_that_day(
        self, mock_client
    ):
        """Friday already holds its own gym session. Moving Thursday's onto it would
        write one session over another and hand Thursday's history to Friday's — so the
        move is refused, Friday is revised where it stands and Thursday is left alone."""
        self._eased_thursday_gym()
        save_workout(test_db,
            "2026-06-12", "strength_training", "Gym: Upper",
            "[Gym: Upper]\nBench and rows.",
            duration_minutes=50, rpe=6, tss=40,
        )
        proposal = self._adapt_returning(
            mock_client, "Consolidating the gym days.",
            [{
                "date": "2026-06-12", "sport_type": "strength_training",
                "title": "Gym: Full Body", "description": "[Gym: Full Body]\nBoth days.",
                "change_reason": "One gym day this week.",
                "duration_minutes": 60, "rpe": 7, "tss": 50,
                "replaces": {"date": "2026-06-11", "sport_type": "strength_training"},
            }],
        )
        self.assertEqual(
            [(w["date"], w["sport_type"]) for w in proposal.workouts],
            [("2026-06-12", "strength_training")],
        )
        self.assertIsNone(proposal.workouts[0]["replaces_slot"])

        service = CoachService(db_instance=test_db)
        with redirect_stdout(io.StringIO()):
            service.workout_revision_apply(proposal)

        thursday = test_db.get_workout("2026-06-11", "strength_training")
        self.assertEqual(thursday["title"], "Gym: Lower", "left where it stands")
        friday = test_db.get_workout("2026-06-12", "strength_training")
        self.assertEqual(friday["title"], "Gym: Full Body")
        self.assertEqual(friday["original_duration_minutes"], 50, "Friday's own lineage")

    @patch("stamind.coach.engine.openrouter_client")
    def test_a_move_from_a_day_with_no_session_writes_the_new_one_and_nothing_else(
        self, mock_client
    ):
        """The coach names a Wednesday session that does not exist. Only the half it can
        honour is honoured: Friday's session is written, and no day is emptied on the
        strength of a slot the run was never shown."""
        proposal = self._adapt_returning(
            mock_client, "Adding a gym day.",
            [{
                "date": "2026-06-12", "sport_type": "strength_training",
                "title": "Gym: Lower", "description": "[Gym: Lower]\n45 min.",
                "change_reason": "Moved off Wednesday.",
                "duration_minutes": 45, "rpe": 6, "tss": 35,
                "replaces": {"date": "2026-06-10", "sport_type": "strength_training"},
            }],
        )
        self.assertEqual(
            [(w["date"], w["sport_type"]) for w in proposal.workouts],
            [("2026-06-12", "strength_training")],
        )
        self.assertIsNone(proposal.workouts[0]["replaces_slot"])

    @patch("stamind.coach.engine.openrouter_client")
    def test_a_session_already_trained_cannot_be_moved_off_its_day(self, mock_client):
        """The athlete lifted on Wednesday morning and the coach then tries to carry
        Wednesday's session to Friday. History is not movable: the completed session
        stays on Wednesday with its Calendar event, and Friday's entry is written as a
        session of its own (DESIGN_workout_revisions.md §9.2)."""
        save_workout(test_db,
            "2026-06-10", "strength_training", "Gym: Lower",
            "[Gym: Lower]\n5x5 back squat.",
            duration_minutes=60, rpe=7, tss=50,
        )
        test_db.save_completed_activity(
            "lifted", "2026-06-10", "2026-06-10 07:00:00", "Gym", "strength_training",
            3600.0, 0.0, 0.0, 110, 140, None, 50.0,
        )
        proposal = self._adapt_returning(
            mock_client, "Gym moves to Friday.",
            [{
                "date": "2026-06-12", "sport_type": "strength_training",
                "title": "Gym: Lower", "description": "[Gym: Lower]\n60 min.",
                "change_reason": "Moved to Friday.",
                "duration_minutes": 60, "rpe": 7, "tss": 50,
                "replaces": {"date": "2026-06-10", "sport_type": "strength_training"},
            }],
        )
        self.assertIsNone(proposal.workouts[0]["replaces_slot"])

        service = CoachService(db_instance=test_db)
        with redirect_stdout(io.StringIO()):
            service.workout_revision_apply(proposal)

        wednesday = test_db.get_workout("2026-06-10", "strength_training")
        self.assertIsNotNone(wednesday, "a session already trained is not moved away")
        self.assertEqual(wednesday["title"], "Gym: Lower")
