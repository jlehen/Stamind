"""What `workout list` says became of a session already behind us: whether it
happened, by how much it differed, and what is graded at all.
"""
import os
import unittest
from datetime import datetime, timedelta, timezone
from unittest.mock import patch

from tests.helpers import clear_all_tables, run_cli, rebind_test_db, save_workout
from tests import test_db_path

TEST_DB_PATH = test_db_path("test_cli_workouts_adherence.db")

from stamind.db import Database
from stamind.coach.proposals import GenerateProposal

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


class TestCliWorkoutsListingGrades(unittest.TestCase):
    """A narrowed listing is still graded against the whole day, the listing pulls
    only what it has to grade, and a cancelled session is not a miss."""

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

    def test_workout_list_glosses_only_the_markers_on_screen(self):
        """The footer says what each bracket marker means, for the markers printed.

        A legend naming [BENCHMARK] when no benchmark is listed is a paragraph the
        eye learns to skip (DESIGN_logging.md §7.2)."""
        day = self._adherence_fixture()
        exit_code, stdout, _ = self.run_cli([
            "workout", "list", "-d", f"{day(-2)}..{day(-1)}", "--no-pull",
        ])
        self.assertEqual(exit_code, 0)
        self.assertIn("DONE = ", stdout)
        self.assertIn("PARTIAL = ", stdout)
        self.assertIn("REST OK = ", stdout)
        # The skipped run sits a day earlier and no session here is a benchmark, so
        # neither word is glossed.
        self.assertNotIn("MISSED = ", stdout)
        self.assertNotIn("BENCHMARK = ", stdout)

    def test_workout_list_says_what_stale_is_about(self):
        """[STALE] names no subject on its own: the legend has to say Google Calendar,
        and name the command that fixes it."""
        from stamind.workout_state import calendar_signature
        wid = save_workout(test_db,
            date=PROPOSED_DATE, sport_type="running", title="Drifted Run",
            description="easy",
        )
        test_db.mark_workout_pushed(
            wid, "evt-drift", calendar_signature(test_db.get_workout_by_id(wid))
        )
        save_workout(test_db,
            date=PROPOSED_DATE, sport_type="running", title="Drifted Run",
            description="HARD",
        )
        exit_code, stdout, _ = self.run_cli([
            "workout", "list", "-d", PROPOSED_DATE, "--no-pull",
        ])
        self.assertEqual(exit_code, 0)
        self.assertIn("[STALE]", _line_for(stdout, "Drifted Run"))
        footer = " ".join(stdout.split())
        self.assertIn("STALE = its Google Calendar event is out of date", footer)
        self.assertIn("workout push", footer)

    def test_generate_preview_glosses_its_own_markers(self):
        """The preview draws the same lines as the listing, so it carries the same
        footer — and `[KEPT]`, the one marker only a preview prints, has to be in it."""
        import io
        from contextlib import redirect_stdout
        from stamind.cli.workouts.generate import print_generate_preview
        proposal = GenerateProposal(
            reasoning="Reasoning",
            workouts=(
                {
                    "date": PROPOSED_DATE, "sport_type": "running", "title": "Base Run",
                    "description": "45 min easy", "duration_minutes": 45, "tss": 40,
                    "rpe": 4,
                },
                {
                    "date": PROPOSED_DATE, "sport_type": "rest", "title": "Rest Day",
                    "description": "Complete rest.", "keep": True,
                },
            ),
            displaced=(),
            gen_start=PROPOSED_DATE, gen_end=PROPOSED_DATE,
        )
        out = io.StringIO()
        with redirect_stdout(out):
            self.assertTrue(print_generate_preview(proposal))
        stdout = out.getvalue()
        self.assertIn("[KEPT]", stdout)
        self.assertIn("KEPT = left as it stands", " ".join(stdout.split()))

    def test_every_marker_the_line_can_print_has_a_gloss(self):
        """A new adherence status or a new change kind must not reach the listing with
        no entry in the legend. Keyed on the two maps that produce the words, never on a
        copy of them."""
        from stamind.analytics.adherence import STATUS_LABELS
        from stamind.cli.workouts.session_line import _MARKER_GLOSS
        from stamind.workout_state import _KIND_MARKERS
        glossed = {word for word, _gloss in _MARKER_GLOSS}
        for label in STATUS_LABELS.values():
            self.assertIn(label.upper(), glossed)
        for word in _KIND_MARKERS.values():
            self.assertIn(word, glossed)

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

    @patch("stamind.runtime.garmin")
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
