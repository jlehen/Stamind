"""`workout list` and `workout show`: which sessions a listing picks, and how
much of each one it draws at -v and -vv.

What the listing says became of a day already behind us is
`test_cli_workouts_adherence.py`.
"""
import os
import unittest
from datetime import datetime, timedelta, timezone

from tests.helpers import clear_all_tables, run_cli, rebind_test_db, save_workout
from tests import test_db_path

TEST_DB_PATH = test_db_path("test_cli_workouts_listing.db")

from stamind.db import Database

test_db = Database(db_path=TEST_DB_PATH)
rebind_test_db(test_db)


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


class TestCliWorkoutsListing(unittest.TestCase):
    """The filters, the short form -v draws under each session, `show` as
    `list -vv` over the same rows, and the repeat-adaptation tag."""

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
