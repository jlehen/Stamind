"""What counts as an easing, what applying one stamps on the session, and what
the next adapt prompt is told about a session that has been eased before.
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

TEST_DB_PATH = test_db_path("test_adaptation_easing.db")

from trainmate.db import Database
import trainmate.config

test_db = Database(db_path=TEST_DB_PATH)
rebind_test_db(test_db)

from trainmate.coach.service import CoachService, coach_service
from trainmate.coach.proposals import RevisionProposal


class TestAdaptEasing(unittest.TestCase):
    """Only a revision that moves the load is an easing: a rewritten description
    and a drift correction both change the session and neither costs one."""

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
    def test_adapt_applies_a_text_only_revision_and_it_costs_no_easing(self, mock_client):
        """Rewriting only the description is a real change the week planner makes deliberately —
        the athlete reads it — so it is applied, not suppressed. And it is cheap: `_eased`
        counts a revision only when duration or TSS FELL, so a reworded session never
        renders the `ALREADY EASED` tag that raises the bar for the next adapt (§9.1)."""
        with patch.dict(trainmate.config.config.data, {
            "user_profile": {"lthr": 165, "max_hr": 185},
            "coach": {
                "metrics_lookback_days": 3,
                "minor_activity_load_threshold": 10.0,
            }
        }):
            mock_client.complete.return_value = {
                "change_needed": True,
                "reason": "Holding the mesocycle; the pacing cue now references Wednesday.",
                "adapted_workouts": [
                    {
                        "date": "2026-06-05", "sport_type": "cycling",
                        "title": "Climb Threshold",
                        "change_reason": "Cue now references Wednesday's execution.",
                        "description": (
                            "85 mins, 2x20. Wednesday's execution was exactly right."
                        ),
                        "duration_minutes": 85, "rpe": 7, "tss": 84,
                    },
                ],
            }
            test_db.save_metric_cache("2026-06-03", 50, 60, 80, 20, 10.0, 8.0, 1.1)
            test_db.save_baseline("2026-06-03", 50.0, 2.0, 60.0, 5.0, 80.0, 5.0)
            save_workout(test_db,
                "2026-06-05", "cycling", "Climb Threshold",
                "85 mins, 2x20. Even power beats a good average.",
                duration_minutes=85, rpe=7, tss=84,
            )

            proposal = coach_service.workout_adapt("2026-06-03")

            # The backstop is exact, not fuzzy: the text moved, so this is a change.
            self.assertEqual(len(proposal.workouts), 1)
            self.assertEqual(proposal.held, ())

            service = CoachService(db_instance=test_db)
            with redirect_stdout(io.StringIO()):
                service.workout_revision_apply(proposal)

            ride = test_db.get_workout("2026-06-05", "cycling")
            self.assertIn("Wednesday's execution", ride["description"])
            self.assertEqual(ride["duration_minutes"], 85)
            self.assertEqual(ride["adaptation_count"], 0)
            self.assertIsNone(ride["adapted_at"])

    def test_adapt_apply_stamps_recency_and_bumps_count(self):
        """Applying an adaptation that MOVES THE LOAD stamps `adapted_at` and bumps
        `adaptation_count`; a second load-moving adapt of the same session bumps it
        again. Non-adapt saves leave both untouched."""
        save_workout(test_db,
            "2026-06-20", "running", "Friday Tempo", "45 mins w/ tempo intervals",
            duration_minutes=45, rpe=7, tss=55,
        )
        # A plain save (no adapted_at) must not start the counter.
        row = test_db.get_workout("2026-06-20", "running")
        self.assertIsNone(row["adapted_at"])
        self.assertEqual(row["adaptation_count"], 0)

        service = CoachService(db_instance=test_db)
        proposed = [{
            "date": "2026-06-20", "sport_type": "running", "title": "Easy Tempo",
            "description": "Cut to Z2", "modification_reason": "Eased for fatigue",
            "duration_minutes": 35, "rpe": 5, "tss": 30,
        }]
        service.workout_revision_apply(RevisionProposal(
            reason="Mesocycle too hard", workouts=proposed, new_constraints=[],
            range_start="2026-06-20", range_end="2026-06-20",
        ))
        row = test_db.get_workout("2026-06-20", "running")
        self.assertIsNotNone(row["adapted_at"])
        self.assertEqual(row["adaptation_count"], 1)

        proposed[0]["description"] = "Cut further to easy walk"
        proposed[0]["duration_minutes"] = 25
        proposed[0]["tss"] = 18
        service.workout_revision_apply(RevisionProposal(
            reason="Still fatigued", workouts=proposed, new_constraints=[],
            range_start="2026-06-20", range_end="2026-06-20",
        ))
        row = test_db.get_workout("2026-06-20", "running")
        self.assertEqual(row["adaptation_count"], 2)

    def test_drift_correction_does_not_count_as_an_easing(self):
        """A drift correction rewrites the prescription and holds the load, so it must
        NOT be stamped as an easing (DESIGN_intensity_distribution.md §9.5). Stamping it
        would raise the DO NOT COMPOUND bar for a session that was never cut, blunting
        adapt's fatigue response the next time the athlete is genuinely wrecked."""
        save_workout(test_db,
            "2026-06-21", "running", "Easy Hour", "60 min conversational.",
            duration_minutes=60, rpe=4, tss=40,
        )
        service = CoachService(db_instance=test_db)
        # Same duration, same TSS (as a float against a stored int) — only the
        # prescription's wording sharpens, with an explicit HR guard rail.
        proposed = [{
            "date": "2026-06-21", "sport_type": "running", "title": "Easy Hour",
            "description": "60 min conversational. HR ceiling 145 — hard cap.",
            "modification_reason": "Third mesocycle week where 'easy' runs averaged Z3.",
            "duration_minutes": 60, "rpe": 4, "tss": 40.0,
        }]
        service.workout_revision_apply(RevisionProposal(
            reason="Correcting execution drift", workouts=proposed, new_constraints=[],
            range_start="2026-06-21", range_end="2026-06-21",
        ))
        row = test_db.get_workout("2026-06-21", "running")
        self.assertIsNone(row["adapted_at"])
        self.assertEqual(row["adaptation_count"], 0)
        self.assertIn("HR ceiling 145", row["description"])

        # A genuine cut on the same session still stamps normally.
        proposed[0]["duration_minutes"] = 40
        proposed[0]["tss"] = 25
        service.workout_revision_apply(RevisionProposal(
            reason="Fatigued", workouts=proposed, new_constraints=[],
            range_start="2026-06-21", range_end="2026-06-21",
        ))
        row = test_db.get_workout("2026-06-21", "running")
        self.assertIsNotNone(row["adapted_at"])
        self.assertEqual(row["adaptation_count"], 1)

    def test_already_eased_tag_in_planned_prompt(self):
        """An already-eased session is tagged with its count + recency for the adapt
        prompt; an unadapted session is not."""
        from trainmate.coach.formatting import format_planned_workouts_detailed

        eased = {
            "date": "2026-06-18", "sport_type": "running", "title": "Easy Tempo",
            "description": "Z2", "duration_minutes": 35, "rpe": 5, "tss": 30,
            "modification_reason": "Eased", "adaptation_summary": "Mesocycle too hard",
            "adapted_at": "2026-06-17T08:00:00+00:00", "adaptation_count": 2,
        }
        untouched = {
            "date": "2026-06-19", "sport_type": "yoga", "title": "Mobility",
            "description": "easy", "duration_minutes": 20, "rpe": 2, "tss": 10,
        }
        text = format_planned_workouts_detailed(
            [eased, untouched], eval_date="2026-06-20"
        )
        self.assertIn("eased by a prior adaptation 2x", text)
        self.assertIn("3 days ago", text)
        # The unadapted yoga line carries no such tag.
        yoga_line = [ln for ln in text.splitlines() if "(YOGA)" in ln][0]
        self.assertNotIn("eased", yoga_line)
