"""`workout adapt` and `workout tweak` on the terminal, and the preview of the
revision they propose — the expert table and the companion prose form of the
same proposal (DESIGN_render_persona.md §7).
"""
import os
import unittest
from datetime import datetime, timedelta
from unittest.mock import patch

from tests.helpers import clear_all_tables, run_cli, rebind_test_db
from trainmate.coach.proposals import RevisionProposal
from trainmate.coach.revisions import RevisionPair
from tests import test_db_path

TEST_DB_PATH = test_db_path("test_cli_workouts_adapt.db")

from trainmate.db import Database

test_db = Database(db_path=TEST_DB_PATH)
rebind_test_db(test_db)


class TestCliWorkoutsAdapt(unittest.TestCase):
    """What the athlete reads before accepting an adaptation: the sentences the
    columns cannot show, the day a moved session came from, and the metrics
    the run was judged on."""

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

    def run_cli(self, args, input_value="n"):
        return run_cli(args, input_value)

    @patch("trainmate.runtime.garmin")
    @patch("trainmate.runtime.coach_service")
    def test_adapt_message_open_ended_rule_is_named_not_stored(self, mock_coach, _garmin):
        """A note with no time bound is not a dated constraint: the terminal says where it
        belongs and asks nothing (DESIGN_bot_simple_frontend.md §12.3, 2026-09-16)."""
        mock_coach.workout_adapt.return_value = RevisionProposal(
            reason="Metrics are green", workouts=[],
            new_constraints=[{"title": "never two workouts in a day",
                              "start_date": None, "end_date": None, "open_ended": True}],
            range_start="2026-06-03", range_end="2026-06-30", pairs=(),
        )
        exit_code, stdout, _ = self.run_cli(
            ["workout", "adapt", "--auto", "-m", "I have no time for two workouts a day"]
        )
        self.assertEqual(exit_code, 0)
        self.assertIn("Not saved", stdout)
        self.assertIn("never two workouts in a day", stdout)
        self.assertIn("user_profile.preferences", stdout)
        mock_coach.capture_message_constraint.assert_not_called()

    @patch("trainmate.runtime.garmin")
    @patch("trainmate.runtime.coach_service")
    def test_workout_commands(self, mock_coach, mock_garmin):
        adapted = {
            "date": "2026-06-03",
            "sport_type": "running",
            "title": "Steady Ride",
            "duration_minutes": 60,
            "rpe": 5,
            "tss": 40.0,
        }
        mock_coach.workout_adapt.return_value = RevisionProposal(
            reason="Metrics are green",
            workouts=[adapted],
            new_constraints=[],
            range_start="2026-06-03",
            range_end="2026-06-30",
            pairs=(RevisionPair(proposal=adapted, original=None, is_swap=False),),
        )

        exit_code, stdout, stderr = self.run_cli(["workout", "list"])
        self.assertEqual(exit_code, 0)
        self.assertIn("=== WORKOUT SCHEDULE ===", stdout)
        self.assertNotIn("Description:", stdout)

        exit_code, stdout, stderr = self.run_cli(["workout", "adapt", "--auto"])
        self.assertEqual(exit_code, 0)
        self.assertIn("Evaluating daily Garmin metrics adaptation", stdout)
        self.assertIn("Metrics are green", stdout)
        self.assertIn("Adaptations applied and synced to calendar successfully.", stdout)
        mock_coach.workout_adapt.assert_called_once()
        # With no -m, the athlete message threads through as None.
        self.assertIsNone(mock_coach.workout_adapt.call_args.kwargs.get("message"))

        # -m/--message is forwarded verbatim to the service for this run.
        mock_coach.workout_adapt.reset_mock()
        exit_code, stdout, stderr = self.run_cli(
            ["workout", "adapt", "--auto", "-m", "knee is sore, keep impact low"]
        )
        self.assertEqual(exit_code, 0)
        self.assertEqual(
            mock_coach.workout_adapt.call_args.kwargs.get("message"),
            "knee is sore, keep impact low",
        )

    @patch("trainmate.cli.workouts.adapt.ensure_recent_data")
    @patch("trainmate.runtime.coach_service")
    def test_a_text_revision_shows_the_sentences_that_moved(
        self, mock_coach, _mock_ensure
    ):
        """Title and load are the only columns the table can show, so a session the week planner
        revised in words alone rendered as `X | X | 85m/RPE7/TSS84 -> 85m/RPE7/TSS84` and
        read as a change made for no reason. Such a revision is real and worth reading, so
        the preview prints what moved (DESIGN_workout_revisions.md §9.1)."""
        original = {
            "date": "2026-06-05", "sport_type": "cycling", "title": "Climb Threshold",
            "description": (
                "2x20 at threshold, seated.\n"
                "Even power beats a good average — this builds the pacing discipline "
                "for the goal climb."
            ),
            "duration_minutes": 85, "rpe": 7, "tss": 84,
        }
        adapted = dict(original, description=(
            "2x20 at threshold, seated.\n"
            "Wednesday's execution was exactly right — same discipline again."
        ))
        mock_coach.workout_adapt.return_value = RevisionProposal(
            reason="Holding the mesocycle; the cue now references Wednesday.",
            workouts=[adapted], new_constraints=[],
            range_start="2026-06-05", range_end="2026-06-30",
            pairs=(RevisionPair(proposal=adapted, original=original, is_swap=False),),
        )

        exit_code, stdout, _stderr = self.run_cli(["workout", "adapt"])

        self.assertEqual(exit_code, 0)
        self.assertIn("85m/RPE7/TSS84 -> 85m/RPE7/TSS84", stdout)
        self.assertIn("[text revised]", stdout)
        # The passage that moved, both halves labelled in words rather than as a
        # `-`/`+` diff (which loses its signs once a phone re-flows the lines), and
        # not the sentence that stayed put.
        self.assertIn("TEXT REVISED", stdout)
        self.assertIn("Was: Even power beats a good average", stdout)
        self.assertIn("Now: Wednesday's execution was exactly right", stdout)
        self.assertNotIn("2x20 at threshold, seated.", stdout.split("TEXT REVISED")[1])
        self.assertNotIn("\n    - ", stdout)
        self.assertNotIn("\n    + ", stdout)

    @patch("trainmate.cli.workouts.adapt.ensure_recent_data")
    @patch("trainmate.runtime.coach_service")
    def test_a_text_revision_wraps_at_the_client_width(self, mock_coach, _mock_ensure):
        """Over the bot the CLI is told the phone's width; the wording diff used to wrap
        at a fixed 88 columns regardless, so the phone re-wrapped every line and the
        old/new halves became indistinguishable."""
        original = {
            "date": "2026-06-05", "sport_type": "cycling", "title": "Climb Threshold",
            "description": (
                "2x20 at threshold, seated. Even power beats a good average — this "
                "builds the pacing discipline for the goal climb, and a steady first "
                "rep is what makes the second one possible."
            ),
            "duration_minutes": 85, "rpe": 7, "tss": 84,
        }
        adapted = dict(original, description=(
            "2x20 at threshold, seated. Wednesday's execution was exactly right — same "
            "discipline again, and hold the second rep to the first rep's number rather "
            "than chasing a higher average."
        ))
        mock_coach.workout_adapt.return_value = RevisionProposal(
            reason="Holding the mesocycle.", workouts=[adapted], new_constraints=[],
            range_start="2026-06-05", range_end="2026-06-30",
            pairs=(RevisionPair(proposal=adapted, original=original, is_swap=False),),
        )

        with patch.dict(os.environ, {"TRAINMATE_WRAP_WIDTH": "48"}):
            exit_code, stdout, _stderr = self.run_cli(["workout", "adapt"])

        self.assertEqual(exit_code, 0)
        revised = stdout.split("TEXT REVISED")[1]
        self.assertIn("Was: Even power", revised)
        self.assertIn("Now: Wednesday's execution", revised)
        passages = [line for line in revised.splitlines() if line.startswith("    ")]
        self.assertTrue(passages and all(len(line) <= 48 for line in passages), revised)

    @patch("trainmate.cli.workouts.adapt.ensure_recent_data")
    @patch("trainmate.runtime.coach_service")
    def test_simple_render_previews_the_revision_as_prose(self, mock_coach, _mock_ensure):
        """Simple mode sends flowed text, not a <pre> message, so the preview is one
        paragraph per touched day — no table, no diff signs — and the ask is in
        companion words (DESIGN_bot_simple_frontend.md §6)."""
        lift = {
            "date": "2026-06-08", "sport_type": "strength_training",
            "title": "Strength — Deload Volume", "description": "Gym, 55 min.",
            "duration_minutes": 55, "rpe": 5, "tss": 22,
        }
        rest = {
            "date": "2026-06-08", "sport_type": "rest", "title": "Rest Day",
            "description": "Complete rest.", "duration_minutes": 0, "rpe": 0, "tss": 0,
            "modification_reason": "No time for the lift today — it moves to Tuesday.",
        }
        original = {
            "date": "2026-06-10", "sport_type": "cycling", "title": "Climb Threshold",
            "description": "2x20 at threshold, seated. Even power beats a good average.",
            "duration_minutes": 85, "rpe": 7, "tss": 84,
        }
        reworded = dict(original, description=(
            "2x20 at threshold, seated. Wednesday's execution was exactly right."
        ), modification_reason="Cue now references Wednesday.")
        mock_coach.workout_adapt.return_value = RevisionProposal(
            reason="Purely your time squeeze.", workouts=[rest, reworded],
            new_constraints=[], range_start="2026-06-08", range_end="2026-06-30",
            pairs=(
                RevisionPair(proposal=rest, original=lift, is_swap=True),
                RevisionPair(proposal=reworded, original=original, is_swap=False),
            ),
        )

        with patch.dict(os.environ, {"TRAINMATE_RENDER": "simple"}):
            exit_code, stdout, _stderr = self.run_cli(["workout", "adapt"])

        self.assertEqual(exit_code, 0)
        self.assertIn("Here's what I'd change:", stdout)
        self.assertIn(
            "🛌 Mon Jun 08: Rest Day (was Strength — Deload Volume, 55 min)\n"
            "No time for the lift today — it moves to Tuesday.", stdout,
        )
        self.assertIn(
            "🚴 Wed Jun 10: Climb Threshold — 85 min (same session, wording updated)\n"
            "Cue now references Wednesday.\n\n"
            "Was: Even power beats a good average.\n"
            "Now: Wednesday's execution was exactly right.", stdout,
        )
        # The wording diff puts blank lines inside a session's own entry, so the day
        # boundary needs a mark of its own (DESIGN_bot_simple_frontend.md §6).
        from trainmate.cli.render.session_lines import SIMPLE_SESSION_RULE
        before, after = stdout.split(SIMPLE_SESSION_RULE)
        self.assertIn("Rest Day (was Strength — Deload Volume", before)
        self.assertNotIn("Climb Threshold", before)
        self.assertIn("Was: Even power beats a good average.", after)
        self.assertNotIn("PROPOSED WORKOUT ADAPTATIONS", stdout)
        self.assertNotIn("Duration/RPE/TSS", stdout)
        self.assertNotIn("TEXT REVISED", stdout)
        self.assertIn("Okay — nothing changed.", stdout)

    @staticmethod
    def _moved_gym_proposal():
        """Thursday's gym, carried to Friday — the proposal both previews below draw."""
        thursday = {
            "date": "2026-06-11", "sport_type": "strength_training",
            "title": "Gym: Lower", "description": "[Gym: Lower]\n5x5 back squat.",
            "duration_minutes": 65, "rpe": 7, "tss": 55,
        }
        friday = dict(
            thursday, date="2026-06-12",
            modification_reason="Gym moved to Friday — you are away Thursday evening.",
            replaces_slot=("2026-06-11", "strength_training"),
        )
        return RevisionProposal(
            reason="Away Thursday evening.", workouts=[friday], new_constraints=[],
            range_start="2026-06-11", range_end="2026-06-30",
            pairs=(RevisionPair(proposal=friday, original=thursday, is_swap=False),),
        )

    @patch("trainmate.cli.workouts.adapt.ensure_recent_data")
    @patch("trainmate.runtime.coach_service")
    def test_the_table_says_which_day_a_moved_session_came_from(
        self, mock_coach, _mock_ensure
    ):
        """The Date column shows only where the session lands, so without the day it
        came from the row reads as a session appearing from nowhere on Friday
        (DESIGN_workout_revisions.md §11)."""
        mock_coach.workout_adapt.return_value = self._moved_gym_proposal()

        exit_code, stdout, _stderr = self.run_cli(["workout", "adapt"])

        self.assertEqual(exit_code, 0)
        self.assertIn("Gym: Lower (from 2026-06-11)", stdout)
        # Same sport on both days, so the sport column must not claim a swap.
        self.assertNotIn("->STRENGTH_TRAINING", stdout)

    @patch("trainmate.cli.workouts.adapt.ensure_recent_data")
    @patch("trainmate.runtime.coach_service")
    def test_the_companion_says_a_session_moved_rather_than_appeared(
        self, mock_coach, _mock_ensure
    ):
        """Unchanged but for its day, the session would otherwise be announced as "new" —
        which is what the athlete reads when a move is told as two unrelated changes."""
        mock_coach.workout_adapt.return_value = self._moved_gym_proposal()

        with patch.dict(os.environ, {"TRAINMATE_RENDER": "simple"}):
            exit_code, stdout, _stderr = self.run_cli(["workout", "adapt"])

        self.assertEqual(exit_code, 0)
        self.assertIn("(moved from Thu Jun 11)", stdout)
        self.assertNotIn("(new)", stdout)

    @patch("trainmate.cli.workouts.adapt.ensure_recent_data")
    @patch("trainmate.runtime.coach_service")
    def test_a_real_load_change_carries_no_text_revision_section(
        self, mock_coach, _mock_ensure
    ):
        """The TEXT REVISED section is for changes the columns CANNOT show. A load change is
        visible in them already, so repeating its prose would be noise."""
        original = {
            "date": "2026-06-05", "sport_type": "cycling", "title": "Climb Threshold",
            "description": "2x20 at threshold.",
            "duration_minutes": 85, "rpe": 7, "tss": 84,
        }
        adapted = dict(original, title="Easy Spin", description="Z2 only.",
                       duration_minutes=45, rpe=3, tss=30)
        mock_coach.workout_adapt.return_value = RevisionProposal(
            reason="Easing for fatigue.", workouts=[adapted], new_constraints=[],
            range_start="2026-06-05", range_end="2026-06-30",
            pairs=(RevisionPair(proposal=adapted, original=original, is_swap=False),),
        )

        exit_code, stdout, _stderr = self.run_cli(["workout", "adapt"])

        self.assertEqual(exit_code, 0)
        self.assertNotIn("[text revised]", stdout)
        self.assertNotIn("TEXT REVISED", stdout)

    def _seed_pmc_metrics(self, n_days: int) -> None:
        """n_days of metrics ending today, each carrying the PMC triple."""
        today = datetime.now().date()
        for i in range(n_days):
            test_db.save_metric_cache(
                date=(today - timedelta(days=n_days - 1 - i)).isoformat(),
                rhr=50, hrv=70, sleep_score=80, stress=20,
                ctl=62.4, atl=71.7, tsb=-8.9,
            )

    @patch("trainmate.cli.workouts.adapt.ensure_recent_data")
    @patch("trainmate.runtime.coach_service")
    def test_adapt_reports_metric_day_count_not_values(self, mock_coach, _mock_ensure):
        # The week planner still reads the full trajectory; the CLI only tells the athlete how
        # many days fed the decision and never prints the raw per-day numbers.
        mock_coach.workout_adapt.return_value = RevisionProposal(
            reason="Metrics are green", workouts=[], new_constraints=[],
            range_start="2026-06-01", range_end="2026-06-30",
        )
        self._seed_pmc_metrics(90)

        exit_code, stdout, stderr = self.run_cli(["workout", "adapt", "--lookback", "3"])

        self.assertEqual(exit_code, 0)
        self.assertNotIn("Could not load metrics trajectory", stdout)
        self.assertIn("Using 3 days of recovery metrics", stdout)
        # No raw HRV/RHR/PMC values leak into the terse summary.
        for value in ("62.4", "71.7", "-8.9"):
            self.assertNotIn(value, stdout)

    @patch("trainmate.runtime.prompt")
    @patch("trainmate.runtime.coach_service")
    def test_the_ambiguous_match_question_carries_its_own_pairing(
        self, mock_coach, mock_prompt
    ):
        """The pairing must travel inside the question, not in a preceding aside.

        Asides are suppressed on the chat front-end, so a `step()` premise left Telegram
        asking "Was that the session, cut short?" about nothing the athlete could see
        (DESIGN_output_verbosity.md §3, ARCHITECTURE.md §15)."""
        from trainmate.cli.workouts.adapt import _resolve_ambiguous_matches

        mock_coach.pending_match_questions.return_value = [{
            "activity_id": "act_warmup",
            "sport": "strength_training",
            "planned": {
                "date": "2026-06-03", "sport_type": "strength_training",
                "title": "Full-Body Strength", "description": "65 mins",
                "duration_minutes": 65, "rpe": 6, "tss": 30,
            },
            "completed": {
                "activity_name": "Warm-up", "activity_type": "indoor_cardio",
                "duration_sec": 600.0, "tss": 8.0,
            },
        }]
        mock_prompt.confirm.return_value = False

        # Asides off is the chat front-end's own setting; the question must survive it.
        with patch.dict(os.environ, {"TRAINMATE_VERBOSE": "0"}):
            _resolve_ambiguous_matches("2026-06-03", auto=False)

        asked = " ".join(mock_prompt.confirm.call_args[0][0].split())
        self.assertIn("Full-Body Strength", asked)
        self.assertIn("Warm-up", asked)
        # Both sides in the same units: a bare "10m" was read as GPS distance, so the
        # activity carries the same duration/load shape as the planned line beside it.
        self.assertIn("65min", asked)
        self.assertIn("TSS 30", asked)
        self.assertIn("10min", asked)
        self.assertIn("TSS 8", asked)
        self.assertNotIn("at 10m", asked)
        self.assertIn("Was that the session, cut short?", asked)
        mock_coach.record_match_decision.assert_called_once_with(
            "act_warmup", "strength_training", False
        )
