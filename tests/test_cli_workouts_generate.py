"""What `workout generate` asks the athlete before it writes, and the undo that
takes a written batch back.

Which days the run covers is `test_cli_workouts_generate_span.py`.
"""
import os
import unittest
from datetime import datetime, timedelta, timezone
from unittest.mock import patch

from tests.helpers import clear_all_tables, run_cli, rebind_test_db, save_workout
from trainmate.clock import fmt_date
from trainmate.coach.proposals import RevisionProposal, GenerateProposal
from tests import test_db_path

TEST_DB_PATH = test_db_path("test_cli_workouts_generate.db")

from trainmate.db import Database

test_db = Database(db_path=TEST_DB_PATH)
rebind_test_db(test_db)

PROPOSED_DATE = (datetime.now(timezone.utc).date() + timedelta(days=1)).strftime("%Y-%m-%d")


def _proposal(displaced=()):
    """One proposed session, as `workout generate` hands it to the CLI for preview."""
    today = datetime.now(timezone.utc).date()
    return GenerateProposal(
        reasoning="Reasoning",
        workouts=({
            "date": PROPOSED_DATE, "sport_type": "running", "title": "Base Run",
            "description": "45 min easy", "duration_minutes": 45, "tss": 40, "rpe": 4,
            "planned_zone_currency": "hr", "planned_zone_sec": [600, 2100, 0, 0, 0],
        },),
        displaced=tuple(displaced),
        gen_start=today.strftime("%Y-%m-%d"),
        gen_end=(today + timedelta(days=27)).strftime("%Y-%m-%d"),
    )


class TestCliWorkoutsGenerate(unittest.TestCase):
    """A regeneration is archive-and-rebuild, so a live plan is confirmed before the model
    call and the proposed sessions are previewed before the write — and `workout batches`
    with `workout rollback` is how a batch already written is taken back."""

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

    @patch("trainmate.runtime.coach_service")
    def test_workout_batches_and_rollback(self, mock_coach):
        """`workout batches` lists every change and `workout rollback` picks one
        (DESIGN_workout_revisions.md §10)."""
        exit_code, stdout, _ = self.run_cli(["workout", "batches"])
        self.assertEqual(exit_code, 0)
        self.assertIn("Nothing has written workouts yet", stdout)

        # Nothing written yet: rollback declines without reaching the service.
        exit_code, stdout, _ = self.run_cli(["workout", "rollback"])
        self.assertEqual(exit_code, 0)
        self.assertIn("No workout changes to roll back", stdout)
        mock_coach.workout_rollback.assert_not_called()

        today = datetime.now(timezone.utc).date()
        future_str = (today + timedelta(days=2)).strftime("%Y-%m-%d")
        save_workout(test_db,
            date=future_str, sport_type="running", title="First Run",
            description="45 mins", duration_minutes=45,
        )

        exit_code, stdout, _ = self.run_cli(["workout", "batches"])
        self.assertEqual(exit_code, 0)
        self.assertIn("#1", stdout)
        self.assertIn("generate", stdout)
        self.assertIn("1 revision(s)", stdout)
        # The change that wrote the live plan is itself listed and itself undoable: there
        # is no separate unnumbered "live" row any more (§10).
        self.assertNotIn("in force", stdout)

        # An adapt is a change like any other, so it heads the list and is undoable alone.
        save_workout(test_db,
            date=future_str, sport_type="running", title="First Run",
            description="30 mins", duration_minutes=30,
            adaptation_summary="eased", modification_reason="eased",
        )
        exit_code, stdout, _ = self.run_cli(["workout", "batches"])
        self.assertEqual(exit_code, 0)
        self.assertIn("adapt", stdout)
        newest = next(ln for ln in stdout.splitlines() if "#1" in ln)
        self.assertIn("adapt", newest)

        # An out-of-range number is refused before anything is written.
        exit_code, stdout, _ = self.run_cli(["workout", "rollback", "--batch", "9"])
        self.assertEqual(exit_code, 0)
        self.assertIn("No change #9", stdout)
        mock_coach.workout_rollback.assert_not_called()

        changes = test_db.get_workout_changes(from_date=today.strftime("%Y-%m-%d"))
        mock_coach.workout_rollback.return_value = {
            "change": changes[0], "restored_workouts": 1,
            "first_date": future_str, "last_date": future_str, "unhonored": [],
        }
        exit_code, stdout, _ = self.run_cli(["workout", "rollback", "-y"])
        self.assertEqual(exit_code, 0)
        self.assertIn("restored 1 session(s)", stdout)
        # The CLI resolves the positional #N to the change id.
        self.assertEqual(
            mock_coach.workout_rollback.call_args.kwargs.get("change_id"), changes[0]["id"]
        )
        # Calendar chatter is off by default (a count and a progress bar stand in for it)
        # and -v turns the per-event lines back on.
        self.assertFalse(mock_coach.workout_rollback.call_args.kwargs.get("verbose"))
        self.run_cli(["workout", "rollback", "-y", "-v"])
        self.assertTrue(mock_coach.workout_rollback.call_args.kwargs.get("verbose"))

    @patch("trainmate.cli.workouts.generate.ensure_recent_data")
    @patch("trainmate.runtime.prompt")
    @patch("trainmate.runtime.coach_service")
    def test_generate_confirms_before_replacing_live_plan(
        self, mock_coach, mock_prompt, _ensure
    ):
        """A regen is archive-and-rebuild, so an existing upcoming plan is confirmed
        before the LLM call; --force skips the prompt.

        The sessions at stake are the ones inside the span about to be rebuilt, here the
        one inside `-d`, not the one before it (§8)."""
        mock_coach.workout_generate.return_value = _proposal()
        today = datetime.now(timezone.utc).date()
        d1 = (today + timedelta(days=1)).strftime("%Y-%m-%d")
        d2 = (today + timedelta(days=5)).strftime("%Y-%m-%d")
        span = ["-d", f"{d2}..{(today + timedelta(days=8)).strftime('%Y-%m-%d')}"]

        # Empty plan: nothing to lose, so no prompt stands between the athlete and the
        # coach — the only question asked is the apply gate, after the preview.
        mock_prompt.confirm.return_value = False
        exit_code, _, _ = self.run_cli(["workout", "generate"])
        self.assertEqual(exit_code, 0)
        mock_prompt.confirm.assert_called_once()
        mock_coach.workout_generate.assert_called_once()

        save_workout(test_db,
            date=d1, sport_type="running", title="Tempo", description="30 min",
        )
        save_workout(test_db,
            date=d2, sport_type="running", title="Long", description="90 min",
        )

        # Declining leaves the live plan alone and never spends the LLM call.
        mock_prompt.confirm.reset_mock()
        mock_coach.workout_generate.reset_mock()
        exit_code, stdout, _ = self.run_cli(["workout", "generate", *span])
        self.assertEqual(exit_code, 0)
        # The question is wrapped for the terminal; compare on a single logical line.
        question = " ".join(mock_prompt.confirm.call_args.args[0].split())
        # Counted over the span about to be rebuilt, not "everything from today on" — a
        # bounded regen only puts the sessions inside it at stake (§8).
        self.assertIn("You already have 1 workout(s) planned in this span", question)
        # d1 lies before the span, so it is not at stake.
        self.assertNotIn(fmt_date(d1), question)
        self.assertIn(fmt_date(d2), question)
        self.assertIn("your schedule is unchanged", stdout)
        mock_coach.workout_generate.assert_not_called()

        # Accepting proceeds.
        mock_prompt.confirm.return_value = True
        exit_code, _, _ = self.run_cli(["workout", "generate", *span])
        self.assertEqual(exit_code, 0)
        mock_coach.workout_generate.assert_called_once()

        # --force skips both questions, even when confirm would decline.
        mock_prompt.confirm.reset_mock()
        mock_prompt.confirm.return_value = False
        mock_coach.workout_generate.reset_mock()
        mock_coach.workout_generate_apply.reset_mock()
        exit_code, _, _ = self.run_cli(["workout", "generate", "--force", *span])
        self.assertEqual(exit_code, 0)
        mock_prompt.confirm.assert_not_called()
        mock_coach.workout_generate.assert_called_once()
        mock_coach.workout_generate_apply.assert_called_once()

    @patch("trainmate.cli.workouts.generate.ensure_recent_data")
    @patch("trainmate.runtime.prompt")
    @patch("trainmate.runtime.coach_service")
    def test_generate_fresh_reaches_the_service_and_promises_nothing(
        self, mock_coach, mock_prompt, _ensure
    ):
        """`--fresh` holds no session, so the question before the LLM call stops saying the
        near days are the athlete's (DESIGN_plan_change_continuity.md §4.4)."""
        mock_coach.workout_generate.return_value = _proposal()
        test_db.set_setting("workout_commitment_days", "7")
        tomorrow = datetime.now(timezone.utc).date() + timedelta(days=1)
        save_workout(test_db,
            date=tomorrow.strftime("%Y-%m-%d"), sport_type="running", title="Tempo",
            description="30 min",
        )
        mock_prompt.confirm.return_value = False

        self.run_cli(["workout", "generate", "-d", "today.."])
        question = " ".join(mock_prompt.confirm.call_args.args[0].split())
        self.assertIn("The next 7 day(s) are yours", question)

        self.run_cli(["workout", "generate", "-d", "today..", "--fresh"])
        question = " ".join(mock_prompt.confirm.call_args.args[0].split())
        self.assertNotIn("are yours", question)
        mock_coach.workout_generate.assert_not_called()

        self.run_cli(["workout", "generate", "-d", "today..", "--fresh", "-f"])
        self.assertTrue(mock_coach.workout_generate.call_args.kwargs["fresh"])
        self.run_cli(["workout", "generate", "-d", "today..", "-f"])
        self.assertFalse(mock_coach.workout_generate.call_args.kwargs["fresh"])

    @patch("trainmate.cli.workouts.generate.ensure_recent_data")
    @patch("trainmate.runtime.prompt")
    @patch("trainmate.runtime.coach_service")
    def test_generate_promises_no_held_day_to_a_span_past_them(
        self, mock_coach, mock_prompt, _ensure
    ):
        """The span opens on the tenth day: the seven held days are not in it."""
        test_db.set_setting("workout_commitment_days", "7")
        tenth = datetime.now(timezone.utc).date() + timedelta(days=10)
        save_workout(test_db,
            date=tenth.strftime("%Y-%m-%d"), sport_type="running", title="Tempo",
            description="30 min",
        )
        mock_prompt.confirm.return_value = False
        self.run_cli(["workout", "generate", "-d", f"{tenth:%Y-%m-%d}.."])
        question = " ".join(mock_prompt.confirm.call_args.args[0].split())
        self.assertIn("Regenerate?", question)
        self.assertNotIn("are yours", question)

    @patch("trainmate.cli.workouts.generate.ensure_recent_data")
    @patch("trainmate.runtime.prompt")
    @patch("trainmate.runtime.coach_service")
    def test_generate_strength_only_counts_and_writes_the_strength_sessions(
        self, mock_coach, mock_prompt, _ensure
    ):
        """No other session can change, so the question counts the strength sessions and
        the week planner's path is never taken (DESIGN_strength_tracking.md §9)."""
        tomorrow = datetime.now(timezone.utc).date() + timedelta(days=1)
        day = tomorrow.strftime("%Y-%m-%d")
        save_workout(test_db, date=day, sport_type="running", title="Tempo",
                     description="30 min")
        save_workout(test_db, date=day, sport_type="strength_training", title="Gym",
                     description="[Gym]\nHeavy full-body.")
        mock_coach.workout_generate_strength.return_value = RevisionProposal(
            reason="Your strength sessions stand as written.", workouts=[],
            range_start=day, range_end=day,
        )
        mock_prompt.confirm.return_value = False

        self.run_cli(["workout", "generate", "-d", "today..", "--strength-only"])
        question = " ".join(mock_prompt.confirm.call_args.args[0].split())
        self.assertIn("You have 1 strength session(s)", question)
        mock_coach.workout_generate_strength.assert_not_called()

        self.run_cli(["workout", "generate", "-d", "today..", "--strength-only", "-f"])
        start, end = mock_coach.workout_generate_strength.call_args.args
        self.assertEqual(end, day)
        mock_coach.workout_revision_record_no_change.assert_called_once()
        mock_coach.workout_generate.assert_not_called()

        exit_code, _, _ = self.run_cli(
            ["workout", "generate", "--strength-only", "--fresh", "-f"]
        )
        self.assertNotEqual(exit_code, 0)

    @patch("trainmate.cli.workouts.generate.ensure_recent_data")
    @patch("trainmate.runtime.prompt")
    @patch("trainmate.runtime.coach_service")
    def test_generate_previews_the_workouts_then_asks_before_writing(
        self, mock_coach, mock_prompt, _ensure
    ):
        """The proposed sessions are shown the way `workout list` shows them, and nothing
        is written until the athlete accepts."""
        today = datetime.now(timezone.utc).date()
        displaced = {
            "id": 7, "date": today.strftime("%Y-%m-%d"), "sport_type": "running",
            "title": "Old Tempo", "description": "30 min",
        }
        proposal = _proposal(displaced=(displaced,))
        mock_coach.workout_generate.return_value = proposal

        # Declining writes nothing.
        mock_prompt.confirm.return_value = False
        exit_code, stdout, _ = self.run_cli(["workout", "generate"])
        self.assertEqual(exit_code, 0)
        self.assertIn("WORKOUTS PROPOSED BY COACH", stdout)
        # Rendered by the same `workout_line` the listing uses — the date, the sport, the
        # title and the load, with no ID, since the session has no row yet.
        self.assertIn(fmt_date(PROPOSED_DATE), stdout)
        self.assertIn("RUNNING", stdout)
        self.assertIn("Base Run", stdout)
        self.assertIn("45min", stdout)
        self.assertNotIn("ID:", stdout)
        # Under it, the zones as the week planner wrote them, the line `workout list -v` draws.
        self.assertIn("Target: ~10min recovery, ~35min aerobic", stdout)
        self.assertIn("Workouts discarded", stdout)
        mock_coach.workout_generate_apply.assert_not_called()

        # The apply question names what it would archive.
        question = " ".join(mock_prompt.confirm.call_args.args[0].split())
        self.assertIn("Schedule these 1 workout(s)", question)
        self.assertIn("archives the 1 session(s)", question)

        # Accepting hands the very same proposal to the writer — the preview and the
        # write cannot disagree about what is scheduled.
        mock_prompt.confirm.return_value = True
        mock_coach.workout_generate_apply.return_value = [displaced]
        exit_code, stdout, _ = self.run_cli(["workout", "generate"])
        self.assertEqual(exit_code, 0)
        self.assertIs(mock_coach.workout_generate_apply.call_args.args[0], proposal)
        self.assertIn("Scheduled 1 workout(s)", stdout)
        # Same verbosity contract as rollback: quiet by default, per-event lines under -v.
        self.assertFalse(mock_coach.workout_generate_apply.call_args.kwargs["verbose"])
        self.run_cli(["workout", "generate", "-v"])
        self.assertTrue(mock_coach.workout_generate_apply.call_args.kwargs["verbose"])

    @patch("trainmate.cli.workouts.generate.ensure_recent_data")
    @patch("trainmate.runtime.prompt")
    @patch("trainmate.runtime.coach_service")
    def test_generate_with_no_proposed_sessions_asks_nothing(
        self, mock_coach, mock_prompt, _ensure
    ):
        """A coach that proposes nothing must not archive the live plan for an empty
        rebuild — there is nothing to apply, so there is nothing to ask."""
        mock_coach.workout_generate.return_value = GenerateProposal(
            reasoning="No active goals found."
        )
        mock_prompt.confirm.return_value = True
        exit_code, stdout, _ = self.run_cli(["workout", "generate"])
        self.assertEqual(exit_code, 0)
        self.assertIn("No active goals found.", stdout)
        self.assertIn("nothing to apply", stdout)
        mock_prompt.confirm.assert_not_called()
        mock_coach.workout_generate_apply.assert_not_called()

    @patch("trainmate.cli.workouts.generate.ensure_recent_data")
    @patch("trainmate.runtime.prompt")
    @patch("trainmate.runtime.coach_service")
    def test_generate_force_keeps_out_of_date_plan_warning(
        self, mock_coach, mock_prompt, _ensure
    ):
        """--force proceeds past the out-of-date-plan warning without stamping the
        config hash — only an explicit confirmation accepts the stale plan."""
        mock_coach.workout_generate.return_value = _proposal()
        mock_coach.config_changed.return_value = "athlete profile changed"
        obj_id = test_db.add_objective(
            title="London Marathon", target_date="2026-09-20",
            sport_type="running",
        )
        test_db.save_macrocycle(
            objective_id=obj_id, strategy="Build then taper", goals_hash="g",
            constraints_hash="c",
            mesocycles=[{
                "name": "Base", "start_date": "2026-06-01", "end_date": "2026-06-28",
                "focus": "Aerobic volume",
            }],
        )

        # Declining stops before the LLM call and leaves the plan flagged as stale.
        mock_prompt.confirm.return_value = False
        with patch.object(test_db, "update_macrocycle_config_hash") as mock_stamp:
            exit_code, stdout, _ = self.run_cli(["workout", "generate"])
            self.assertEqual(exit_code, 0)
            self.assertIn("Workout generation cancelled. Please run", stdout)
            mock_stamp.assert_not_called()
        mock_coach.workout_generate.assert_not_called()

        # --force proceeds, says why, and still leaves the warning live for next time.
        with patch.object(test_db, "update_macrocycle_config_hash") as mock_stamp:
            exit_code, stdout, _ = self.run_cli(["workout", "generate", "-f"])
            self.assertEqual(exit_code, 0)
            # `notice` wraps, so the phrase can straddle a line break.
            self.assertIn("Proceeding anyway (--force)", " ".join(stdout.split()))
            mock_stamp.assert_not_called()
        mock_coach.workout_generate.assert_called_once()
