import os
import unittest
from datetime import datetime, timedelta, timezone
from unittest.mock import patch

from tests.helpers import clear_all_tables, run_cli, rebind_test_db, save_workout
from trainmate.clock import fmt_date
from trainmate.coach.proposals import RevisionProposal, GenerateProposal
from trainmate.coach.revisions import RevisionPair
from tests import test_db_path

TEST_DB_PATH = test_db_path("test_trainmate_cli_workouts.db")

from trainmate.db import Database
import trainmate_cli

test_db = Database(db_path=TEST_DB_PATH)
rebind_test_db(test_db)

PROPOSED_DATE = (datetime.now(timezone.utc).date() + timedelta(days=1)).strftime("%Y-%m-%d")


def _line_for(stdout, title):
    """The single `workout list` line for one session, found by its title."""
    matches = [
        line for line in stdout.splitlines()
        if line.startswith("ID: ") and f"| {title}" in line
    ]
    assert len(matches) == 1, f"expected one line for {title!r}, got {matches}"
    return matches[0]


def _line_after(stdout, title):
    """The line printed right under one session's `workout list` line."""
    lines = stdout.splitlines()
    return lines[lines.index(_line_for(stdout, title)) + 1]


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


class TestCliWorkouts(unittest.TestCase):
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

    @patch("trainmate.cli.workouts.generate.ensure_recent_data")
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

    @patch("trainmate.cli.workouts.generate.ensure_recent_data")
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

    @patch("trainmate.cli.workouts.generate.ensure_recent_data")
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
        from trainmate.cli.render import SIMPLE_SESSION_RULE
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

    @patch("trainmate.cli.workouts.generate.ensure_recent_data")
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

    @patch("trainmate.cli.workouts.generate.ensure_recent_data")
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

    @patch("trainmate.cli.workouts.generate.ensure_recent_data")
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

    @patch("trainmate.cli.workouts.generate.ensure_recent_data")
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

    @patch("trainmate.runtime.calendar_syncer")
    def test_workout_push_command(self, mock_calendar):
        exit_code, stdout, stderr = self.run_cli(["workout", "push"])
        self.assertEqual(exit_code, 0)
        self.assertIn("No new or modified workouts to sync", stdout)
        mock_calendar.sync_multiple.assert_not_called()

        today_str = datetime.now(timezone.utc).strftime("%Y-%m-%d")
        save_workout(test_db,
            date=today_str, sport_type="running", title="Tempo Run",
            description="30 mins fast",
        )

        exit_code, stdout, stderr = self.run_cli(["workout", "push"])
        self.assertEqual(exit_code, 0)
        self.assertIn("Syncing 1 workouts to Google Calendar", stdout)
        mock_calendar.sync_multiple.assert_called_once()

    @patch("trainmate.runtime.calendar_syncer")
    def test_workout_push_warns_about_stale_past_workouts(self, mock_calendar):
        """`push` defaults to today onward, so a past row left stale by a failed push
        has nothing that would re-push it. It must at least be surfaced."""
        from trainmate.workout_state import calendar_signature
        today = datetime.now(timezone.utc).date()
        past = (today - timedelta(days=4)).strftime("%Y-%m-%d")

        wid = save_workout(test_db,
            date=past, sport_type="running", title="Old Run", description="easy",
        )
        test_db.mark_workout_pushed(
            wid, "evt-past", calendar_signature(test_db.get_workout_by_id(wid))
        )
        # A push that never landed: content moves on, signature does not.
        save_workout(test_db,
            date=past, sport_type="running", title="Old Run", description="HARD",
        )

        exit_code, stdout, stderr = self.run_cli(["workout", "push"])
        self.assertEqual(exit_code, 0)
        self.assertIn("1 workout before", stdout)
        self.assertIn("[STALE]", stdout)
        # `notice` wraps, and the command can land across the break.
        self.assertIn(f"workout push -d {past}..", " ".join(stdout.split()))
        # Warning only — the past row stays outside the pushed window.
        mock_calendar.sync_multiple.assert_not_called()

    @patch("trainmate.runtime.calendar_syncer")
    def test_workout_push_no_warning_when_past_is_clean(self, mock_calendar):
        """A past workout that is synced (or was never pushed) must not warn."""
        today = datetime.now(timezone.utc).date()
        past = (today - timedelta(days=4)).strftime("%Y-%m-%d")
        save_workout(test_db,
            date=past, sport_type="running", title="Old Run", description="easy",
        )
        exit_code, stdout, stderr = self.run_cli(["workout", "push"])
        self.assertEqual(exit_code, 0)
        self.assertNotIn("still read [STALE]", stdout)

    @patch("trainmate.runtime.calendar_syncer")
    def test_workout_wipe(self, mock_calendar):
        save_workout(test_db,
            date="2026-06-02", sport_type="running", title="Run 1",
            description="30 mins", google_event_id="ge_1",
        )
        save_workout(test_db,
            date="2026-06-03", sport_type="running", title="Run 2",
            description="30 mins",
        )
        self.assertEqual(len(test_db.get_workouts()), 2)

        exit_code, stdout, stderr = self.run_cli(["workout", "wipe"], input_value="n")
        self.assertEqual(exit_code, 0)
        self.assertEqual(len(test_db.get_workouts()), 2)
        mock_calendar.delete_event.assert_not_called()

        exit_code, stdout, stderr = self.run_cli(["workout", "wipe"], input_value="y")
        self.assertEqual(exit_code, 0)
        self.assertIn("All workouts wiped successfully.", stdout)
        self.assertEqual(len(test_db.get_workouts()), 0)
        mock_calendar.delete_event.assert_called_once_with("ge_1")

        mock_calendar.reset_mock()
        save_workout(test_db,
            date="2026-06-02", sport_type="running", title="Run 1",
            description="30 mins", google_event_id="ge_2",
        )
        exit_code, stdout, stderr = self.run_cli(["workout", "wipe", "-y"])
        self.assertEqual(exit_code, 0)
        self.assertEqual(len(test_db.get_workouts()), 0)
        mock_calendar.delete_event.assert_called_once_with("ge_2")

    @patch("trainmate.runtime.calendar_syncer")
    def test_workout_prune_calendar(self, mock_calendar):
        # One live workout, one soft-removed (keeps its event), and two calendar
        # events no row claims — the fresh-database case.
        save_workout(test_db,
            date="2026-06-02", sport_type="running", title="Run 1",
            description="30 mins", google_event_id="ge_live",
        )
        removed_id = save_workout(test_db,
            date="2026-06-03", sport_type="running", title="Run 2",
            description="30 mins", google_event_id="ge_removed",
        )
        with test_db.workout_change(kind="stand-down") as change:
            change.void(date="2026-06-03", sport_type="running", reason="not today")

        mock_calendar.list_workout_events.return_value = [
            {"id": "ge_live", "summary": "Run 1", "start": {"date": "2026-06-02"}},
            {"id": "ge_removed", "summary": "[Deleted] Run 2", "start": {"date": "2026-06-03"}},
            {"id": "ge_orphan_a", "summary": "Old Ride", "start": {"date": "2026-05-01"}},
            {"id": "ge_orphan_b", "summary": "Old Swim", "start": {"date": "2026-06-10"}},
        ]
        mock_calendar.delete_event.return_value = True

        # Dry run reports both orphans and deletes nothing.
        exit_code, stdout, _ = self.run_cli(["workout", "prune-calendar", "--dry-run"])
        self.assertEqual(exit_code, 0)
        self.assertIn("Old Ride", stdout)
        self.assertIn("Old Swim", stdout)
        self.assertNotIn("Run 1", stdout)
        self.assertNotIn("[Deleted] Run 2", stdout)
        mock_calendar.delete_event.assert_not_called()

        # Declining the confirmation deletes nothing either.
        exit_code, stdout, _ = self.run_cli(["workout", "prune-calendar"], input_value="n")
        self.assertEqual(exit_code, 0)
        self.assertIn("Prune cancelled.", stdout)
        mock_calendar.delete_event.assert_not_called()

        # A date window bounds which orphans go.
        exit_code, stdout, _ = self.run_cli(
            ["workout", "prune-calendar", "-d", "2026-06-01..", "-y"]
        )
        self.assertEqual(exit_code, 0)
        self.assertIn("Pruned 1 orphaned Calendar event.", stdout)
        mock_calendar.delete_event.assert_called_once_with("ge_orphan_b")

        # Unbounded, the remaining orphan goes and the claimed events survive.
        mock_calendar.reset_mock()
        mock_calendar.delete_event.return_value = True
        exit_code, stdout, _ = self.run_cli(["workout", "prune-calendar", "-y"])
        self.assertEqual(exit_code, 0)
        self.assertIn("Pruned 2 orphaned Calendar events.", stdout)
        self.assertEqual(
            sorted(c.args[0] for c in mock_calendar.delete_event.call_args_list),
            ["ge_orphan_a", "ge_orphan_b"],
        )

    @patch("trainmate.runtime.calendar_syncer")
    def test_workout_prune_calendar_nothing_to_do(self, mock_calendar):
        save_workout(test_db,
            date="2026-06-02", sport_type="running", title="Run 1",
            description="30 mins", google_event_id="ge_live",
        )
        mock_calendar.list_workout_events.return_value = [
            {"id": "ge_live", "summary": "Run 1", "start": {"date": "2026-06-02"}},
        ]
        exit_code, stdout, _ = self.run_cli(["workout", "prune-calendar", "-y"])
        self.assertEqual(exit_code, 0)
        self.assertIn("No orphaned Calendar events", stdout)
        mock_calendar.delete_event.assert_not_called()

    @patch("trainmate.runtime.calendar_syncer")
    def test_workout_prune_calendar_keeps_a_marker_covered_in_its_slot(self, mock_calendar):
        """A marker is not an orphan just because a session took its slot
        (DESIGN_plan_change_continuity.md §5.6)."""
        from trainmate.gcal.reconcile import no_calendar_sync
        # The reconcile is suppressed so the ownership rows stay as written: this test
        # asks what `prune-calendar` reads, not what the sync would have done first.
        with no_calendar_sync():
            save_workout(test_db,
                date="2026-06-02", sport_type="running", title="Club run",
                description="45 mins", google_event_id="ge_marker",
            )
            with test_db.workout_change(
                kind="generate", commitment_end="2026-06-08"
            ) as change:
                change.void(date="2026-06-02", sport_type="running", reason="replaced")
            with test_db.workout_change(
                kind="generate", commitment_end="2026-06-08"
            ) as change:
                change.append(
                    date="2026-06-02", sport_type="running", title="Tempo 6x800",
                    description="intervals", duration_minutes=60, rpe=7, tss=70,
                )
            covering = test_db.get_workout("2026-06-02", "running")
            test_db.mark_workout_pushed(covering["id"], "ge_new", "sig")

        mock_calendar.list_workout_events.return_value = [
            {"id": "ge_marker", "summary": "[Cancelled] Club run",
             "start": {"date": "2026-06-02"}},
            {"id": "ge_new", "summary": "Tempo 6x800", "start": {"date": "2026-06-02"}},
            {"id": "ge_orphan", "summary": "Old Swim", "start": {"date": "2026-06-10"}},
        ]
        mock_calendar.delete_event.return_value = True

        exit_code, stdout, _ = self.run_cli(["workout", "prune-calendar", "-y"])
        self.assertEqual(exit_code, 0)
        self.assertNotIn("Club run", stdout)
        mock_calendar.delete_event.assert_called_once_with("ge_orphan")

    def test_workout_list_filters(self):
        today_date = datetime.now(timezone.utc).date()
        today_str = today_date.strftime("%Y-%m-%d")
        tomorrow_str = (today_date + timedelta(days=1)).strftime("%Y-%m-%d")
        past_str = (today_date - timedelta(days=5)).strftime("%Y-%m-%d")
        future_str = (today_date + timedelta(days=10)).strftime("%Y-%m-%d")

        save_workout(test_db,
            date=today_str, sport_type="running", title="Today Run",
            description="30 mins",
        )
        save_workout(test_db,
            date=tomorrow_str, sport_type="cycling", title="Tomorrow Ride",
            description="60 mins",
        )
        save_workout(test_db,
            date=past_str, sport_type="yoga", title="Past Yoga",
            description="15 mins",
        )
        save_workout(test_db,
            date=future_str, sport_type="strength_training", title="Future Lift",
            description="45 mins",
        )

        goal_id = test_db.add_objective(
            title="Berlin Marathon",
            target_date=(today_date + timedelta(days=20)).strftime("%Y-%m-%d"),
            sport_type="running",
            status="active",
        )
        test_db.save_macrocycle(
            objective_id=goal_id,
            strategy="Base strategy",
            goals_hash="ghash",
            constraints_hash="lhash",
            mesocycles=[{
                "name": "Base Building",
                "start_date": (today_date - timedelta(days=2)).strftime("%Y-%m-%d"),
                "end_date": (today_date + timedelta(days=5)).strftime("%Y-%m-%d"),
                "focus": "Aerobic conditioning",
            }],
        )

        macro = test_db.get_macrocycle_for_objective(goal_id)
        mesos = test_db.get_mesocycles_for_macrocycle(macro["id"])
        meso_id = mesos[0]["id"]

        exit_code, stdout, stderr = self.run_cli(["workout", "list"])
        self.assertEqual(exit_code, 0)
        self.assertIn("Today Run", stdout)
        self.assertIn("Tomorrow Ride", stdout)
        self.assertNotIn("Past Yoga", stdout)
        self.assertNotIn("Future Lift", stdout)

        exit_code, stdout, stderr = self.run_cli(["workout", "list", "--type", "running"])
        self.assertEqual(exit_code, 0)
        self.assertIn("Today Run", stdout)
        self.assertNotIn("Tomorrow Ride", stdout)
        self.assertNotIn("Past Yoga", stdout)

        exit_code, stdout, stderr = self.run_cli(["workout", "list", "-d", "2d"])
        self.assertEqual(exit_code, 0)
        self.assertIn("Today Run", stdout)
        self.assertIn("Tomorrow Ride", stdout)
        self.assertNotIn("Past Yoga", stdout)
        self.assertNotIn("Future Lift", stdout)

        exit_code, stdout, stderr = self.run_cli([
            "workout", "list", "-d", tomorrow_str
        ])
        self.assertEqual(exit_code, 0)
        self.assertNotIn("Today Run", stdout)
        self.assertIn("Tomorrow Ride", stdout)
        self.assertNotIn("Past Yoga", stdout)
        self.assertNotIn("Future Lift", stdout)

        exit_code, stdout, stderr = self.run_cli([
            "workout", "list", "-m", str(meso_id)
        ])
        self.assertEqual(exit_code, 0)
        self.assertNotIn("Past Yoga", stdout)
        self.assertIn("Today Run", stdout)
        self.assertIn("Tomorrow Ride", stdout)
        self.assertNotIn("Future Lift", stdout)

        exit_code, stdout, stderr = self.run_cli([
            "workout", "list", "-m", f"..{meso_id}"
        ])
        self.assertEqual(exit_code, 0)
        self.assertNotIn("Past Yoga", stdout)
        self.assertIn("Today Run", stdout)
        self.assertIn("Tomorrow Ride", stdout)
        self.assertNotIn("Future Lift", stdout)

        exit_code, stdout, stderr = self.run_cli([
            "workout", "list", "-g", str(goal_id)
        ])
        self.assertEqual(exit_code, 0)
        self.assertNotIn("Past Yoga", stdout)
        self.assertIn("Today Run", stdout)
        self.assertIn("Tomorrow Ride", stdout)
        self.assertIn("Future Lift", stdout)

        # Bare -m is the current mesocycle, bounded both ends; -m ID.. keeps the end open.
        exit_code, stdout, stderr = self.run_cli(["workout", "list", "-m"])
        self.assertEqual(exit_code, 0)
        self.assertNotIn("Past Yoga", stdout)
        self.assertIn("Today Run", stdout)
        self.assertIn("Tomorrow Ride", stdout)
        self.assertNotIn("Future Lift", stdout)

        exit_code, stdout, stderr = self.run_cli([
            "workout", "list", "-m", f"{meso_id}.."
        ])
        self.assertEqual(exit_code, 0)
        self.assertNotIn("Past Yoga", stdout)
        self.assertIn("Today Run", stdout)
        self.assertIn("Tomorrow Ride", stdout)
        self.assertIn("Future Lift", stdout)

    def test_workout_list_v_draws_the_short_form_under_each_session(self):
        """-v adds gray lines under each session: a strength session's exercises, none
        until the strength planner wrote them, and the zones of any other. -vv is the full
        detail, and still carries the zones, which the description never does."""
        today_str = datetime.now(timezone.utc).date().strftime("%Y-%m-%d")
        tomorrow_str = (
            datetime.now(timezone.utc).date() + timedelta(days=1)
        ).strftime("%Y-%m-%d")
        save_workout(test_db,
            date=today_str, sport_type="strength_training", title="Gym",
            description="Heavy lower body.\n\nBelt squat 3×4–6 @ 140 kg",
            planned_zone_currency="hr", planned_zone_sec=[1200, 600, 0, 0, 0],
            prescribed_sets=[{"exercise": "belt squat", "sets": 3, "reps_low": 4,
                              "reps_high": 6, "load_kg": 140.0}],
        )
        save_workout(test_db,
            date=tomorrow_str, sport_type="cycling", title="Sharpener",
            description="3x5 min at 240-250 W",
            planned_zone_currency="power", planned_zone_sec=[900, 1500, 0, 180, 900],
        )
        # A gym day the week planner wrote before the strength planner existed.
        save_workout(test_db,
            date=tomorrow_str, sport_type="strength_training", title="Old Gym",
            description="Squat 3x4, press 3x5",
            planned_zone_currency="hr", planned_zone_sec=[1800, 600, 0, 0, 0],
        )

        exit_code, plain, _ = self.run_cli(["workout", "list", "--no-pull"])
        self.assertEqual(exit_code, 0)
        self.assertNotIn("Belt squat", plain)
        self.assertNotIn("Target:", plain)

        exit_code, short, _ = self.run_cli(["workout", "list", "-v", "--no-pull"])
        self.assertEqual(exit_code, 0)
        self.assertIn("Belt squat 3×4–6 @ 140 kg", _line_after(short, "Gym"))
        self.assertIn(
            "Target: ~15min recovery, ~25min endurance, ~3min threshold, ~15min VO2max",
            _line_after(short, "Sharpener"),
        )
        # A strength session shows its exercises, never the zones the week planner put on it.
        self.assertNotIn("~20min recovery", short)
        self.assertNotIn("~30min recovery", short)
        self.assertNotIn("Description:", short)

        exit_code, full, _ = self.run_cli(["workout", "list", "-vv", "--no-pull"])
        self.assertEqual(exit_code, 0)
        self.assertIn("Description:", full)
        self.assertIn("3x5 min at 240-250 W", full)
        self.assertIn("Target: ~15min recovery, ~25min endurance", full)

    def test_workout_show_is_workout_list_vv(self):
        """`workout show 12` prints exactly what `workout list -vv 12` prints.

        The two commands are one handler with the detail flag pinned on, so the test
        compares the whole output rather than sampling it: that is what keeps the second
        parser from drifting away from the first."""
        today_str = datetime.now(timezone.utc).date().strftime("%Y-%m-%d")
        workout_id = save_workout(test_db,
            date=today_str, sport_type="running", title="Today Run",
            description="30 mins easy",
        )

        code_show, show_out, _ = self.run_cli(
            ["workout", "show", str(workout_id), "--no-pull"])
        code_list, list_out, _ = self.run_cli(
            ["workout", "list", "-vv", str(workout_id), "--no-pull"])
        self.assertEqual(code_show, 0)
        self.assertEqual(code_list, 0)
        self.assertIn("Description:", show_out)
        self.assertEqual(show_out, list_out)

        # The selectors and filters come with it: a date window details that window.
        code_span, span_out, _ = self.run_cli(
            ["workout", "show", "-d", f"{today_str}..{today_str}", "--no-pull"])
        self.assertEqual(code_span, 0)
        self.assertIn("Today Run", span_out)
        self.assertIn("30 mins easy", span_out)

    def test_workout_list_shows_repeat_adapt_count(self):
        """A session eased once reads [ADAPTED]; eased again reads [ADAPTED ×2].

        The count is walked over the lineage and only counts revisions that actually cut
        the load, so the fixture walks the session down for real
        (DESIGN_workout_revisions.md §7)."""
        today_str = datetime.now(timezone.utc).date().strftime("%Y-%m-%d")
        save_workout(test_db,
            date=today_str, sport_type="running", title="Tempo",
            description="orig", duration_minutes=60, tss=60,
        )
        save_workout(test_db,
            date=today_str, sport_type="running", title="Tempo",
            description="eased", duration_minutes=45, tss=45,
            adaptation_summary="mesocycle too hard", modification_reason="eased",
        )
        exit_code, stdout, _ = self.run_cli(["workout", "list"])
        self.assertEqual(exit_code, 0)
        self.assertIn("[ADAPTED]", stdout)
        self.assertNotIn("[ADAPTED ×", stdout)
        # The lifecycle line is verbose-only; the default listing is one line per workout.
        self.assertNotIn("Planned:", stdout)

        # Lifecycle line under -vv: creation stamp always shown, last-adapted stamp when eased.
        exit_code, stdout_v, _ = self.run_cli(["workout", "list", "-vv"])
        self.assertEqual(exit_code, 0)
        self.assertIn("Planned:", stdout_v)
        self.assertIn(f"Last adapted: {today_str}", stdout_v)

        # Second easing of the same session bumps the count.
        save_workout(test_db,
            date=today_str, sport_type="running", title="Tempo",
            description="easier", duration_minutes=30, tss=30,
            adaptation_summary="still fatigued", modification_reason="eased again",
        )
        exit_code, stdout, _ = self.run_cli(["workout", "list"])
        self.assertEqual(exit_code, 0)
        self.assertIn("[ADAPTED ×2]", stdout)

    def _adherence_fixture(self):
        """Days behind us and one ahead, with the activities that grade them."""
        today = datetime.now(timezone.utc).date()

        def day(n):
            return (today + timedelta(days=n)).strftime("%Y-%m-%d")

        save_workout(test_db,
            date=day(-3), sport_type="running", title="Skipped Run",
            description="40 mins", duration_minutes=40, rpe=5, tss=30,
        )
        save_workout(test_db,
            date=day(-2), sport_type="running", title="Easy Run",
            description="30 mins", duration_minutes=30, rpe=4, tss=20,
        )
        save_workout(test_db,
            date=day(-1), sport_type="running", title="Long Run",
            description="90 mins", duration_minutes=90, rpe=6, tss=100,
        )
        save_workout(test_db,
            date=day(-1), sport_type="rest", title="Rest", description="take it easy",
        )
        save_workout(test_db,
            date=day(0), sport_type="running", title="Tempo Run",
            description="45 mins", duration_minutes=45, rpe=7, tss=50,
        )
        save_workout(test_db,
            date=day(1), sport_type="cycling", title="Tomorrow Ride",
            description="60 mins", duration_minutes=60, tss=45,
        )
        # Matches the easy run exactly; the long run was cut well short of plan.
        test_db.save_completed_activity(
            activity_id="adh_1", date=day(-2), start_time=f"{day(-2)} 08:00:00",
            activity_name="Morning Run", activity_type="running", duration_sec=1800.0,
            distance_km=5.0, elevation_gain_m=50.0, avg_hr=140, max_hr=160,
            rpe=4, tss=20.0,
        )
        test_db.save_completed_activity(
            activity_id="adh_2", date=day(-1), start_time=f"{day(-1)} 08:00:00",
            activity_name="Cut Short", activity_type="running", duration_sec=3000.0,
            distance_km=9.0, elevation_gain_m=80.0, avg_hr=145, max_hr=165,
            rpe=6, tss=55.0,
        )
        return day

    def test_workout_list_shows_what_became_of_each_past_session(self):
        """Listing a day already behind us says whether it happened.

        Today is graded too, and an untrained session there reads [NOT YET] rather than
        as a miss — the day is not over (ARCHITECTURE.md §5, `pending_from`)."""
        day = self._adherence_fixture()
        exit_code, stdout, _ = self.run_cli([
            "workout", "list", "-d", f"{day(-3)}..{day(1)}", "--no-pull",
        ])
        self.assertEqual(exit_code, 0)
        self.assertIn("[MISSED]", _line_for(stdout, "Skipped Run"))
        self.assertIn("[DONE]", _line_for(stdout, "Easy Run"))
        self.assertIn("[PARTIAL]", _line_for(stdout, "Long Run"))
        self.assertIn("[REST OK]", _line_for(stdout, "Rest"))
        self.assertIn("[NOT YET]", _line_for(stdout, "Tempo Run"))
        # A day still ahead carries no verdict at all — nothing has become of it yet.
        ahead = _line_for(stdout, "Tomorrow Ride")
        for marker in ("[DONE]", "[MISSED]", "[PARTIAL]", "[NOT YET]", "[REST OK]"):
            self.assertNotIn(marker, ahead)

    def test_workout_list_vv_names_the_effort_and_the_difference(self):
        """The marker says a session came in off-plan; -vv says by how much, and against
        which activity it was graded."""
        day = self._adherence_fixture()
        exit_code, stdout, _ = self.run_cli([
            "workout", "list", "-d", f"{day(-2)}..{day(-1)}", "--no-pull", "-vv",
        ])
        self.assertEqual(exit_code, 0)
        self.assertIn("Actual: [running] Morning Run", stdout)
        self.assertIn("Actual: [running] Cut Short", stdout)
        self.assertIn("Discrepancy: duration mismatch", stdout)
        self.assertIn("Discrepancy: workload mismatch", stdout)
        # The rest of the detail lines are untouched.
        self.assertIn("Description:", stdout)

    def test_a_narrowed_listing_is_still_graded_against_the_whole_day(self):
        """A ride and a rest day on the same date: the ride takes the activity, so the
        rest day was kept — and it still reads [REST OK] when it is listed on its own.

        The pairing is fed every session in the window, never just the ones being shown.
        Handed only the rest row, the ride's activity would look unaccounted for and the
        rest day would read as broken."""
        yesterday = (
            datetime.now(timezone.utc).date() - timedelta(days=1)
        ).strftime("%Y-%m-%d")
        save_workout(test_db,
            date=yesterday, sport_type="cycling", title="Endurance Ride",
            description="60 mins", duration_minutes=60, rpe=4, tss=45,
        )
        rest_id = save_workout(test_db,
            date=yesterday, sport_type="rest", title="Rest", description="legs up",
        )
        test_db.save_completed_activity(
            activity_id="adh_ride", date=yesterday, start_time=f"{yesterday} 08:00:00",
            activity_name="Afternoon Ride", activity_type="cycling", duration_sec=3600.0,
            distance_km=30.0, elevation_gain_m=100.0, avg_hr=135, max_hr=160,
            rpe=4, tss=45.0,
        )
        exit_code, stdout, _ = self.run_cli(["workout", "list", str(rest_id), "--no-pull"])
        self.assertEqual(exit_code, 0)
        self.assertNotIn("Endurance Ride", stdout)
        self.assertIn("[REST OK]", _line_for(stdout, "Rest"))

    @patch("trainmate.runtime.garmin")
    def test_workout_list_freshens_only_what_it_has_to_grade(self, mock_garmin):
        """The listing reports on completed activities now, so it pulls like every other
        surface that reads them — over its past span only. A listing entirely ahead of us
        has nothing to grade and never reaches Garmin."""
        day = self._adherence_fixture()
        today = datetime.now(timezone.utc).date().strftime("%Y-%m-%d")

        exit_code, _, _ = self.run_cli(["workout", "list", "-d", f"{day(-2)}..{day(1)}"])
        self.assertEqual(exit_code, 0)
        mock_garmin.ensure_data.assert_called_once_with(day(-2), today, force=False)

        mock_garmin.reset_mock()
        exit_code, _, _ = self.run_cli(["workout", "list", "-d", f"{day(1)}..{day(1)}"])
        self.assertEqual(exit_code, 0)
        mock_garmin.ensure_data.assert_not_called()

        mock_garmin.reset_mock()
        exit_code, _, _ = self.run_cli([
            "workout", "list", "-d", f"{day(-2)}..{day(1)}", "--no-pull",
        ])
        self.assertEqual(exit_code, 0)
        mock_garmin.ensure_data.assert_not_called()

    def test_a_cancelled_session_is_not_graded(self):
        """A cancelled session is not a miss: it never reaches the pairing or the
        listing."""
        yesterday = (
            datetime.now(timezone.utc).date() - timedelta(days=1)
        ).strftime("%Y-%m-%d")
        save_workout(test_db,
            date=yesterday, sport_type="running", title="Called Off",
            description="40 mins", duration_minutes=40, rpe=5, tss=30,
            removed=True, removed_reason="travelling",
        )
        exit_code, stdout, _ = self.run_cli([
            "workout", "list", "-d", yesterday, "--no-pull",
        ])
        self.assertEqual(exit_code, 0)
        self.assertNotIn("Called Off", stdout)
        self.assertNotIn("[MISSED]", stdout)

    def test_workout_compare(self):
        today = datetime.now(timezone.utc).date()
        yesterday = today - timedelta(days=1)
        two_days_ago = today - timedelta(days=2)
        yesterday_str = yesterday.strftime("%Y-%m-%d")
        two_days_ago_str = two_days_ago.strftime("%Y-%m-%d")
        today_str = today.strftime("%Y-%m-%d")

        # A run two days ago never done (a real miss — that day is over), a run
        # yesterday that was (will be matched), and a run today not done YET, which
        # is pending rather than missed: the day has not finished.
        save_workout(test_db,
            date=two_days_ago_str, sport_type="running", title="Skipped Run",
            description="40 mins", duration_minutes=40, rpe=5, tss=30,
        )
        save_workout(test_db,
            date=yesterday_str, sport_type="running", title="Easy Run",
            description="30 mins", duration_minutes=30, rpe=4, tss=20,
        )
        save_workout(test_db,
            date=today_str, sport_type="running", title="Tempo Run",
            description="45 mins", duration_minutes=45, rpe=7, tss=50,
        )
        # Complete yesterday's run (matching load/duration — no discrepancy expected)
        test_db.save_completed_activity(
            activity_id="act_cmp_1",
            date=yesterday_str,
            start_time=f"{yesterday_str} 08:00:00",
            activity_name="Morning Run",
            activity_type="running",
            duration_sec=1800.0,
            distance_km=5.0,
            elevation_gain_m=50.0,
            avg_hr=140,
            max_hr=160,
            rpe=4,
            tss=20.0,
        )

        exit_code, stdout, stderr = self.run_cli(["workout", "compare", "-d", "3d"])
        self.assertEqual(exit_code, 0)
        self.assertIn("=== WORKOUT COMPARE ===", stdout)
        self.assertIn("Easy Run", stdout)
        self.assertIn("Morning Run", stdout)
        self.assertIn("Tempo Run", stdout)
        # The finished day reads as a miss; today's untrained session does not.
        self.assertIn("(none — missed)", stdout)
        self.assertIn("(not yet — still ahead today)", stdout)
        self.assertIn("=== DISCREPANCIES ===", stdout)
        self.assertIn("Complete Miss! Missed planned workout 'Skipped Run'", stdout)
        self.assertNotIn("Tempo Run' (running)", stdout)

        # Date range with no data → empty message
        exit_code, stdout, stderr = self.run_cli([
            "workout", "compare", "-d", "2020-01-01..2020-01-02"
        ])
        self.assertEqual(exit_code, 0)
        self.assertIn("No planned workouts or completed activities found", stdout)

    def test_workout_compare_in_companion_voice(self):
        """Simple mode reads the same pairing as glyph lines, and never the expert table
        (DESIGN_bot_simple_frontend.md §6)."""
        today = datetime.now(timezone.utc).date()
        yesterday_str = (today - timedelta(days=1)).strftime("%Y-%m-%d")
        two_days_ago_str = (today - timedelta(days=2)).strftime("%Y-%m-%d")
        save_workout(test_db,
            date=two_days_ago_str, sport_type="running", title="Skipped Run",
            description="40 mins", duration_minutes=40, rpe=5, tss=30,
        )
        save_workout(test_db,
            date=yesterday_str, sport_type="running", title="Easy Run",
            description="30 mins", duration_minutes=30, rpe=4, tss=20,
        )
        test_db.save_completed_activity(
            activity_id="act_cmp_simple",
            date=yesterday_str,
            start_time=f"{yesterday_str} 08:00:00",
            activity_name="Morning Run",
            activity_type="running",
            duration_sec=1800.0,
            distance_km=5.0,
            elevation_gain_m=50.0,
            avg_hr=140,
            max_hr=160,
            rpe=4,
            tss=20.0,
        )

        with patch.dict(os.environ, {"TRAINMATE_RENDER": "simple"}):
            exit_code, stdout, _ = self.run_cli(
                ["workout", "compare", "-d", "3d", "--no-pull", "--no-mark"]
            )
        self.assertEqual(exit_code, 0)
        self.assertIn("🔎 Looking back,", stdout)
        self.assertIn("❌ 🏃 Skipped Run — 40 min", stdout)
        self.assertIn("✅ 🏃 Easy Run — 30 min (you did 30 min)", stdout)
        self.assertIn("1 of 2 sessions done", stdout)
        self.assertNotIn("WORKOUT COMPARE", stdout)
        self.assertNotIn("DISCREPANCIES", stdout)
        self.assertNotIn(yesterday_str, stdout)

    # Colour on: `informational` holds activity dicts, so a raw gray(dict) only blows
    # up on a terminal — piped output short-circuits colorize and hides the bug.
    @patch("trainmate.text.is_color_enabled", return_value=True)
    def test_workout_compare_outside_any_plan(self, _color):
        """Activities on dates no mesocycle covers are rendered as formatted lines,
        not raw dicts."""
        yesterday_str = (
            datetime.now(timezone.utc).date() - timedelta(days=1)
        ).strftime("%Y-%m-%d")

        # No mesocycles saved -> no date is covered, and nothing is planned that day,
        # so this lands in the informational bucket.
        test_db.save_completed_activity(
            activity_id="act_cmp_info",
            date=yesterday_str,
            start_time=f"{yesterday_str} 08:00:00",
            activity_name="Off-Season Ride",
            activity_type="road_biking",
            duration_sec=3600.0,
            distance_km=30.0,
            elevation_gain_m=100.0,
            avg_hr=140,
            max_hr=170,
            rpe=None,
            tss=60.0,
        )

        exit_code, stdout, _ = self.run_cli(["workout", "compare", "-d", "2d"])
        self.assertEqual(exit_code, 0)
        self.assertIn("=== OUTSIDE ANY PLAN (informational) ===", stdout)
        self.assertIn(f"- {fmt_date(yesterday_str)}: [road_biking] Off-Season Ride", stdout)
        self.assertNotIn("'activity_id'", stdout)

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

    def _goal_with_plan(self, target_days_out: int, mesocycle_days_out: int = 20):
        today_date = datetime.now(timezone.utc).date()
        goal_id = test_db.add_objective(
            title="Autumn Marathon",
            target_date=(
                today_date + timedelta(days=target_days_out)
            ).strftime("%Y-%m-%d"),
            sport_type="running", status="active",
        )
        macro_id = test_db.save_macrocycle(
            objective_id=goal_id, strategy="Build", goals_hash="g", constraints_hash="c",
            mesocycles=[{
                "name": "Base",
                "start_date": today_date.strftime("%Y-%m-%d"),
                "end_date": (
                    today_date + timedelta(days=mesocycle_days_out)
                ).strftime("%Y-%m-%d"),
                "focus": "Aerobic",
            }],
        )
        return goal_id, macro_id

    @patch("trainmate.cli.workouts.generate.ensure_recent_data")
    @patch("trainmate.runtime.prompt")
    @patch("trainmate.runtime.coach_service")
    def test_generate_g_is_the_span_not_a_plan_selector(
        self, mock_coach, mock_prompt, _ensure
    ):
        """`-g` reads like it does everywhere else in the grammar: a goal's whole plan
        span, its plan start through its target date. It replaced `--until-goal`, and it
        no longer picks which plan applies — the dates do that (DESIGN_cli_selectors.md
        §8)."""
        mock_coach.workout_generate.return_value = _proposal()
        mock_coach.config_changed.return_value = None
        goal_id, _ = self._goal_with_plan(target_days_out=100)
        target_date = test_db.get_objective(goal_id)["target_date"]
        today = datetime.now(timezone.utc).date().strftime("%Y-%m-%d")

        exit_code, _, _ = self.run_cli(["workout", "generate", "-g", str(goal_id), "-f"])
        self.assertEqual(exit_code, 0)
        kwargs = mock_coach.workout_generate.call_args.kwargs
        self.assertEqual(kwargs["end_date"], target_date)
        # This plan starts today, so its span does too — and the START is now passed
        # through rather than assumed.
        self.assertEqual(kwargs["start_date"], today)

        # Bare -g is the active goal, the same shorthand every other command gives it.
        mock_coach.workout_generate.reset_mock()
        exit_code, _, _ = self.run_cli(["workout", "generate", "-g", "-f"])
        self.assertEqual(exit_code, 0)
        self.assertEqual(
            mock_coach.workout_generate.call_args.kwargs["end_date"], target_date
        )

        # The retired flag is gone rather than silently ignored.
        exit_code, _, stderr = self.run_cli(["workout", "generate", "--until-goal"])
        self.assertNotEqual(exit_code, 0)
        self.assertIn("unrecognized arguments", stderr)

    def _two_mesocycle_plan(self):
        """A plan whose second mesocycle starts three weeks out, so a `-m` span on it opens
        well after today."""
        today_date = datetime.now(timezone.utc).date()

        def out(n):
            return (today_date + timedelta(days=n)).strftime("%Y-%m-%d")

        goal_id = test_db.add_objective(
            title="Autumn Marathon", target_date=out(90), sport_type="running",
            status="active",
        )
        test_db.save_macrocycle(
            objective_id=goal_id, strategy="Build", goals_hash="g", constraints_hash="c",
            mesocycles=[
                {"name": "Base", "start_date": out(0), "end_date": out(20),
                 "focus": "Aerobic"},
                {"name": "Build", "start_date": out(21), "end_date": out(45),
                 "focus": "Threshold"},
            ],
        )
        mesocycles = test_db.get_mesocycles_for_macrocycle(
            test_db.get_macrocycle_for_objective(goal_id)["id"]
        )
        return {b["name"]: b for b in mesocycles}

    @patch("trainmate.cli.workouts.generate.ensure_recent_data")
    @patch("trainmate.runtime.prompt")
    @patch("trainmate.runtime.coach_service")
    def test_generate_m_writes_the_mesocycle_from_its_own_first_day(
        self, mock_coach, mock_prompt, _ensure
    ):
        """`-m 5` generates mesocycle 5 and nothing else — both ends come from the mesocycle,
        where the span used to reach back to today (DESIGN_cli_selectors.md §8)."""
        mock_coach.workout_generate.return_value = _proposal()
        mock_coach.config_changed.return_value = None
        mesocycles = self._two_mesocycle_plan()
        build = mesocycles["Build"]

        exit_code, _, _ = self.run_cli(
            ["workout", "generate", "-m", str(build["id"]), "-f"]
        )
        self.assertEqual(exit_code, 0)
        kwargs = mock_coach.workout_generate.call_args.kwargs
        self.assertEqual(kwargs["start_date"], build["start_date"])
        self.assertEqual(kwargs["end_date"], build["end_date"])

        # A plain date range is read the same way: both ends, not just the far one.
        mock_coach.workout_generate.reset_mock()
        exit_code, _, _ = self.run_cli(
            ["workout", "generate", "-d", f"{build['start_date']}..{build['end_date']}",
             "-f"]
        )
        self.assertEqual(exit_code, 0)
        kwargs = mock_coach.workout_generate.call_args.kwargs
        self.assertEqual(kwargs["start_date"], build["start_date"])
        self.assertEqual(kwargs["end_date"], build["end_date"])

    @patch("trainmate.cli.workouts.generate.ensure_recent_data")
    @patch("trainmate.runtime.prompt")
    @patch("trainmate.runtime.coach_service")
    def test_generate_warns_only_when_the_old_reading_would_differ(
        self, mock_coach, mock_prompt, _ensure
    ):
        """The span change is transitional, so the run says which days it no longer
        touches — and stays quiet when the two readings agree."""
        mock_coach.workout_generate.return_value = _proposal()
        mock_coach.config_changed.return_value = None
        mesocycles = self._two_mesocycle_plan()
        base, build = mesocycles["Base"], mesocycles["Build"]

        # The notice is wrapped for the terminal; compare on a single logical line.
        def _said(argv):
            exit_code, stdout, _ = self.run_cli(argv)
            self.assertEqual(exit_code, 0)
            return " ".join(stdout.split())

        # A span opening later than today: the days before it are no longer rebuilt.
        said = _said(["workout", "generate", "-m", str(build["id"]), "-f"])
        self.assertIn("now rebuilds a bounded span", said)
        self.assertIn(fmt_date(build["start_date"]), said)
        self.assertIn("keeps the sessions it already has", said)
        self.assertIn("to rebuild from today again", said)

        # A session past the span's end: it is no longer cancelled either.
        save_workout(test_db,
            date=build["end_date"], sport_type="running", title="Later",
            description="30 min",
        )
        said = _said(["workout", "generate", "-m", str(base["id"]), "-f"])
        self.assertIn("keep their place instead of being cancelled", said)

        # Nothing before the span and nothing after it — no warning to give.
        said = _said(["workout", "generate", "-g", "-f"])
        self.assertNotIn("now rebuilds a bounded span", said)

    @patch("trainmate.cli.workouts.generate.ensure_recent_data")
    @patch("trainmate.runtime.prompt")
    @patch("trainmate.runtime.coach_service")
    def test_generate_refuses_a_span_that_is_entirely_behind_us(
        self, mock_coach, mock_prompt, _ensure
    ):
        """A mesocycle that has already run is history. Now that a selector names both ends,
        naming a finished one has to be refused rather than quietly regenerating today."""
        mock_coach.config_changed.return_value = None
        today = datetime.now(timezone.utc).date()

        def out(n):
            return (today + timedelta(days=n)).strftime("%Y-%m-%d")

        goal_id = test_db.add_objective(
            title="Past 10k", target_date=out(-5), sport_type="running", status="active",
        )
        macro_id = test_db.save_macrocycle(
            objective_id=goal_id, strategy="Build", goals_hash="g", constraints_hash="c",
            mesocycles=[{"name": "Done", "start_date": out(-40), "end_date": out(-10),
                         "focus": "Aerobic"}],
        )
        done = test_db.get_mesocycles_for_macrocycle(macro_id)[0]

        exit_code, stdout, _ = self.run_cli(
            ["workout", "generate", "-m", str(done["id"]), "-f"]
        )
        self.assertEqual(exit_code, 0)
        self.assertIn("before today", " ".join(stdout.split()))
        mock_coach.workout_generate.assert_not_called()

    @patch("trainmate.cli.workouts.generate.ensure_recent_data")
    @patch("trainmate.runtime.prompt")
    @patch("trainmate.runtime.coach_service")
    def test_generate_passes_a_named_plan_through_as_the_tiebreaker(
        self, mock_coach, mock_prompt, _ensure
    ):
        """`-M ID` bounds the horizon *and* settles which plan to follow where two cover
        the same days; a bare -M names no single winner, so it does not."""
        mock_coach.workout_generate.return_value = _proposal()
        mock_coach.config_changed.return_value = None
        _, macro_id = self._goal_with_plan(target_days_out=100)

        exit_code, _, _ = self.run_cli(
            ["workout", "generate", "-M", str(macro_id), "-f"]
        )
        self.assertEqual(exit_code, 0)
        self.assertEqual(
            mock_coach.workout_generate.call_args.kwargs["prefer_macro_id"], macro_id
        )

        mock_coach.workout_generate.reset_mock()
        exit_code, _, _ = self.run_cli(["workout", "generate", "-M", "-f"])
        self.assertEqual(exit_code, 0)
        self.assertIsNone(
            mock_coach.workout_generate.call_args.kwargs["prefer_macro_id"]
        )

    @patch("trainmate.runtime.prompt")
    @patch("trainmate.runtime.coach_service")
    def test_the_ambiguous_match_question_carries_its_own_pairing(
        self, mock_coach, mock_prompt
    ):
        """The pairing must travel inside the question, not in a preceding aside.

        Asides are suppressed on the chat front-end, so a `step()` premise left Telegram
        asking "Was that the session, cut short?" about nothing the athlete could see
        (DESIGN_output_verbosity.md §3, ARCHITECTURE.md §15)."""
        from trainmate.cli.workouts.generate import _resolve_ambiguous_matches

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
