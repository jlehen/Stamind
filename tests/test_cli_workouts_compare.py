"""`workout compare`: what was planned beside what Garmin recorded, in both
voices, and on dates no mesocycle covers.
"""
import os
import unittest
from datetime import datetime, timedelta, timezone
from unittest.mock import patch

from tests.helpers import clear_all_tables, run_cli, rebind_test_db, save_workout
from stamind.clock import fmt_date
from tests import test_db_path

TEST_DB_PATH = test_db_path("test_cli_workouts_compare.db")

from stamind.db import Database

test_db = Database(db_path=TEST_DB_PATH)
rebind_test_db(test_db)


class TestCliWorkoutsCompare(unittest.TestCase):
    """Simple mode reads the same pairing as glyph lines and never the expert
    table, and activities outside any plan are rendered rather than dropped."""

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

        with patch.dict(os.environ, {"STAMIND_RENDER": "simple"}):
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
    @patch("stamind.text.is_color_enabled", return_value=True)
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
