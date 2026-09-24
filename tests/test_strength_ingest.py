"""The gym logger's Python side (DESIGN_gym_logger.md): the session encoded into the
button's address (§3), the log the page sends back (§4), `strength ingest` (§5), and the
morning pull taking a day's sets from the log instead of from Garmin (§5)."""
import base64
import json
import os
import shutil
import tempfile
import unittest
from datetime import datetime
from unittest.mock import patch

from tests import test_db_path
from tests.helpers import clear_all_tables, rebind_test_db, run_cli, save_workout

TEST_DB_PATH = test_db_path("test_strength_ingest.db")

from stamind.db import Database
import stamind_cli  # noqa: F401 — the CLI binds its handles at import, before the rebind

from stamind import settings
from stamind.strength import logger, sets

if os.path.exists(TEST_DB_PATH):
    os.remove(TEST_DB_PATH)
test_db = Database(db_path=TEST_DB_PATH)
rebind_test_db(test_db)


def tearDownModule():
    try:
        os.remove(TEST_DB_PATH)
    except OSError:
        pass


# The gym day of the design's example, and the morning after it.
GYM_DAY = "2026-09-24"
NEXT_MORNING = datetime(2026, 9, 25, 8, 0).astimezone()

BELT_SQUAT = {"exercise": "belt squat", "sets": 3, "reps_low": 4, "reps_high": 6,
              "load_kg": 140.0}
PULL_UP = {"exercise": "pull up", "sets": 3, "reps_low": 6, "reps_high": 8,
           "load_kg": None}

# DESIGN_gym_logger.md §4, with "barbell curl" spelled the way the vocabulary spells it.
EXAMPLE_LOG = {
    "v": 1, "r": 727, "d": GYM_DAY, "st": "18:02", "en": "19:05",
    "x": [
        {"n": "belt squat", "p": 1, "sets": [[5, 120, 40], [6, 140, 210], [5, 140, 390]]},
        {"n": "leg press", "p": 2, "sets": [[8, 200, 600]],
         "note": "swapped, squat rack busy"},
        {"n": "barbell biceps curl", "sets": [[10, 30, 900], [10, 30, 990]]},
    ],
    "note": "left knee felt off on the squat",
}


def a_session(description="Heavy lower body.\n\nBelt squat 3×4–6 @ 140 kg",
              prescribed=(BELT_SQUAT,), day=GYM_DAY):
    """One strength session written by the strength planner, read back hydrated."""
    save_workout(
        test_db, date=day, sport_type="strength_training", title="Gym: lower body strength",
        description=description, prescribed_sets=list(prescribed),
    )
    return test_db.get_workout(day, "strength_training")


class PayloadTest(unittest.TestCase):
    """What the bot puts in the button's address (§3)."""

    def setUp(self):
        rebind_test_db(test_db)
        clear_all_tables(test_db)

    def test_the_payload_carries_the_prescribed_sets_in_position_order(self):
        workout = a_session(
            description=("Heavy lower body.\n\nBelt squat 3×4–6 @ 140 kg\n"
                         "Pull up 3×6–8\nAlternate the squat and the pull-ups."),
            prescribed=(BELT_SQUAT, PULL_UP),
        )
        payload = logger.session_payload(workout)
        self.assertEqual(payload["v"], 1)
        self.assertEqual(payload["r"], workout["revision_id"])
        self.assertEqual((payload["d"], payload["t"]),
                         (GYM_DAY, "Gym: lower body strength"))
        self.assertEqual(payload["x"], [
            {"n": "belt squat", "s": 3, "lo": 4, "hi": 6, "kg": 140.0},
            {"n": "pull up", "s": 3, "lo": 6, "hi": 8, "kg": None},
        ])

    def test_the_notes_are_what_sits_under_the_exercise_lines(self):
        """The brief above the seam is left out, and so are the exercise lines (§3)."""
        workout = a_session(
            description=("Heavy lower body.\n\nBelt squat 3×4–6 @ 140 kg\n"
                         "Alternate the squat and the pull-ups."),
        )
        self.assertEqual(logger.session_payload(workout)["notes"],
                         "Alternate the squat and the pull-ups.")

    def test_a_session_with_nothing_under_its_exercises_has_no_notes(self):
        self.assertEqual(logger.session_payload(a_session())["notes"], "")

    def test_long_notes_are_cut_to_three_hundred_characters(self):
        workout = a_session(
            description="Heavy lower body.\n\nBelt squat 3×4–6 @ 140 kg\n" + "x" * 400,
        )
        self.assertEqual(len(logger.session_payload(workout)["notes"]), 300)

    def test_the_url_carries_the_payload_in_its_hash_fragment(self):
        workout = a_session()
        url = logger.session_url(workout)
        head, _, packed = url.partition("#s=")
        self.assertEqual(head, logger.PAGE_URL)
        self.assertNotIn("=", packed)
        padded = packed + "=" * (-len(packed) % 4)
        decoded = json.loads(base64.urlsafe_b64decode(padded).decode("utf-8"))
        self.assertEqual(decoded, logger.session_payload(workout))


class ParseLogTest(unittest.TestCase):
    """The message the page sends when the athlete taps "Finish" (§4)."""

    def test_the_design_example_reads_back_whole(self):
        log = logger.parse_log(json.dumps(EXAMPLE_LOG))
        self.assertEqual((log.revision_id, log.date, log.start, log.end),
                         (727, GYM_DAY, "18:02", "19:05"))
        self.assertEqual(log.note, "left knee felt off on the squat")
        self.assertEqual([entry.name for entry in log.exercises],
                         ["belt squat", "leg press", "barbell biceps curl"])
        self.assertEqual([entry.position for entry in log.exercises], [1, 2, None])
        self.assertEqual(log.exercises[0].sets[1], logger.LoggedSet(6, 140.0, 210.0))
        self.assertEqual(log.exercises[1].note, "swapped, squat rack busy")

    def test_a_bodyweight_set_has_no_load(self):
        log = logger.parse_log(json.dumps(
            {**EXAMPLE_LOG, "x": [{"n": "pull up", "sets": [[8, None, 60]]}]}
        ))
        self.assertIsNone(log.exercises[0].sets[0].load_kg)

    def test_an_exercise_the_vocabulary_does_not_know_is_refused_by_name(self):
        payload = {**EXAMPLE_LOG, "x": [
            {"n": "belt squat", "sets": [[5, 120, 40]]},
            {"n": "moon press", "sets": [[5, 20, 90]]},
            {"n": "space row", "sets": [[5, 20, 180]]},
        ]}
        with self.assertRaises(logger.LogError) as refused:
            logger.parse_log(json.dumps(payload))
        self.assertIn("moon press", str(refused.exception))
        self.assertIn("space row", str(refused.exception))
        self.assertNotIn("belt squat", str(refused.exception))

    def test_a_log_of_another_version_is_refused(self):
        with self.assertRaises(logger.LogError):
            logger.parse_log(json.dumps({**EXAMPLE_LOG, "v": 2}))

    def test_a_broken_shape_is_refused(self):
        for payload in (
            "{not json",
            json.dumps([1, 2]),
            json.dumps({**EXAMPLE_LOG, "x": []}),
            json.dumps({**EXAMPLE_LOG, "d": "the 24th"}),
            json.dumps({**EXAMPLE_LOG, "st": "6pm"}),
            json.dumps({**EXAMPLE_LOG, "x": [{"n": "belt squat", "sets": []}]}),
            json.dumps({**EXAMPLE_LOG, "x": [{"n": "belt squat", "sets": [[5, 120]]}]}),
            json.dumps({**EXAMPLE_LOG, "x": [{"sets": [[5, 120, 40]]}]}),
        ):
            with self.assertRaises(logger.LogError, msg=payload):
                logger.parse_log(payload)


class _IngestCase(unittest.TestCase):
    """A log on disk, the way the bot writes one before running the command (§6)."""

    def setUp(self):
        rebind_test_db(test_db)
        clear_all_tables(test_db)
        self.now = NEXT_MORNING
        moving_clock = patch("stamind.clock.now", side_effect=lambda: self.now)
        moving_clock.start()
        self.addCleanup(moving_clock.stop)
        settings.write(settings.STRENGTH_SETS_SINCE, "2026-09-01")
        self.directory = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, self.directory, True)

    def ingest(self, payload):
        path = os.path.join(self.directory, "log.json")
        with open(path, "w", encoding="utf-8") as handle:
            json.dump(payload, handle)
        code, out, err = run_cli(["strength", "ingest", path])
        self.assertEqual(code, 0, err)
        return out

    def example_for(self, workout, **changes):
        """The design's log, pointed at a session this test wrote."""
        return {**EXAMPLE_LOG, "r": workout["revision_id"], **changes}


class IngestTest(_IngestCase):
    """`strength ingest FILE` (§5)."""

    def test_it_writes_the_placeholder_activity(self):
        self.ingest(self.example_for(a_session()))
        activity = test_db.get_completed_activity("log:" + GYM_DAY)
        self.assertEqual(activity["activity_type"], "strength_training")
        self.assertEqual(activity["activity_name"], "Logged gym session")
        self.assertEqual(activity["date"], GYM_DAY)
        self.assertEqual(activity["start_time"], f"{GYM_DAY} 18:02:00")
        self.assertEqual(activity["duration_sec"], 63 * 60)
        self.assertEqual(activity["discarded"], 0)
        self.assertTrue(activity["sets_read_at"] and activity["sets_final_at"])

    def test_every_logged_set_is_an_active_row_the_athlete_named(self):
        self.ingest(self.example_for(a_session()))
        rows = test_db.get_exercise_sets("log:" + GYM_DAY)
        active = [row for row in rows if row["set_type"] == "active"]
        self.assertEqual([row["seq"] for row in rows], list(range(1, len(rows) + 1)))
        self.assertEqual(
            [(row["exercise"], row["reps"], row["load_kg"]) for row in active],
            [("belt squat", 5, 120.0), ("belt squat", 6, 140.0), ("belt squat", 5, 140.0),
             ("leg press", 8, 200.0),
             ("barbell biceps curl", 10, 30.0), ("barbell biceps curl", 10, 30.0)],
        )
        self.assertEqual({row["named_by"] for row in active}, {"athlete"})
        self.assertEqual({row["garmin_name"] for row in active}, {None})

    def test_a_rest_row_holds_the_gap_between_two_sets(self):
        self.ingest(self.example_for(a_session()))
        rows = test_db.get_exercise_sets("log:" + GYM_DAY)
        rest = [row for row in rows if row["set_type"] == "rest"]
        self.assertEqual([row["duration_sec"] for row in rest],
                         [170.0, 180.0, 210.0, 300.0, 90.0])
        self.assertEqual({row["named_by"] for row in rest}, {None})

    def test_a_set_with_no_time_gets_no_rest_row_around_it(self):
        workout = a_session()
        self.ingest(self.example_for(workout, x=[
            {"n": "belt squat", "sets": [[5, 120, None], [5, 120, 300]]},
        ]))
        rows = test_db.get_exercise_sets("log:" + GYM_DAY)
        self.assertEqual([row["set_type"] for row in rows], ["active", "active"])

    def test_the_raw_log_is_kept_beside_the_sets(self):
        workout = a_session()
        self.ingest(self.example_for(workout))
        with test_db._get_connection() as conn:
            row = dict(conn.execute("SELECT * FROM gym_logs").fetchone())
        self.assertEqual(row["activity_id"], "log:" + GYM_DAY)
        self.assertEqual(row["revision_id"], workout["revision_id"])
        self.assertTrue(row["received_at"])
        self.assertEqual(json.loads(row["payload"])["note"],
                         "left knee felt off on the squat")

    def test_the_summary_says_what_was_done_against_what_was_written(self):
        workout = a_session(
            description=("Heavy lower body.\n\nBelt squat 3×4–6 @ 140 kg\nPull up 3×6–8"),
            prescribed=(BELT_SQUAT, PULL_UP),
        )
        out = self.ingest(self.example_for(workout))
        lines = [line for line in out.splitlines() if line.strip()]
        self.assertEqual(lines[0],
                         "Logged 2026-09-24 Thu, 18:02–19:05: 3 exercises, 6 sets.")
        self.assertEqual(lines[1],
                         "Belt squat 5 @ 120, 6 @ 140, 5 @ 140 (written 3×4–6 @ 140)")
        self.assertEqual(lines[2], "Leg press 8 @ 200 (instead of pull up, written 3×6–8)")
        self.assertEqual(lines[3], "Barbell biceps curl 10 @ 30, 10 @ 30 (not written)")

    def test_a_prescribed_exercise_nothing_stood_for_is_listed_as_not_done(self):
        workout = a_session(
            description=("Heavy lower body.\n\nBelt squat 3×4–6 @ 140 kg\nPull up 3×6–8"),
            prescribed=(BELT_SQUAT, PULL_UP),
        )
        out = self.ingest(self.example_for(workout, x=[
            {"n": "belt squat", "p": 1, "sets": [[5, 140, 60]]},
        ]))
        self.assertIn("Not done: pull up 3×6–8.", out)

    def test_a_log_whose_session_is_gone_is_still_ingested(self):
        out = self.ingest({**EXAMPLE_LOG, "r": 9999})
        self.assertIn("cannot", out)
        self.assertIn("Belt squat 5 @ 120, 6 @ 140, 5 @ 140", out)
        self.assertNotIn("not written", out)
        self.assertEqual(len(test_db.get_exercise_sets("log:" + GYM_DAY)), 11)

    def test_a_file_that_is_not_there_is_reported(self):
        missing = os.path.join(self.directory, "missing.json")
        code, out, err = run_cli(["strength", "ingest", missing])
        self.assertEqual(code, 0)
        self.assertIn("Could not read", out + err)

    def test_an_unknown_exercise_stores_nothing(self):
        path = os.path.join(self.directory, "bad.json")
        with open(path, "w", encoding="utf-8") as handle:
            json.dump({**EXAMPLE_LOG, "x": [{"n": "moon press", "sets": [[5, 20, 60]]}]},
                      handle)
        code, out, err = run_cli(["strength", "ingest", path])
        self.assertIn("moon press", out + err)
        self.assertIsNone(test_db.get_completed_activity("log:" + GYM_DAY))

    def test_ingesting_the_same_day_twice_replaces_the_first_log(self):
        workout = a_session()
        first = self.ingest(self.example_for(workout))
        self.assertIn("Logged 2026-09-24 Thu", first)
        second = self.ingest(self.example_for(workout, st="19:00", en="19:30", x=[
            {"n": "belt squat", "p": 1, "sets": [[5, 150, 60], [5, 150, 300]]},
        ]))
        self.assertIn("Updated the log of 2026-09-24 Thu, 19:00–19:30: 1 exercise, 2 sets.",
                      second)
        activity = test_db.get_completed_activity("log:" + GYM_DAY)
        self.assertEqual(activity["start_time"], f"{GYM_DAY} 19:00:00")
        self.assertEqual(activity["duration_sec"], 30 * 60)
        rows = test_db.get_exercise_sets("log:" + GYM_DAY)
        self.assertEqual([(row["set_type"], row["load_kg"]) for row in rows],
                         [("active", 150.0), ("rest", None), ("active", 150.0)])
        with test_db._get_connection() as conn:
            logs = conn.execute("SELECT payload FROM gym_logs").fetchall()
        self.assertEqual(len(logs), 1)
        self.assertEqual(len(json.loads(logs[0]["payload"])["x"]), 1)


class FakeGarmin:
    """The sets endpoint, answering per activity."""

    def __init__(self):
        self.payloads = {}
        self.calls = []

    def get_activity_exercise_sets(self, activity_id):
        self.calls.append(activity_id)
        return self.payloads.get(activity_id, {"exerciseSets": []})


class TakeoverTest(_IngestCase):
    """The morning pull hands the logged sets to Garmin's own activity (§5)."""

    def setUp(self):
        super().setUp()
        self.garmin = FakeGarmin()

    def activity(self, activity_id, duration_sec=3600.0, start="18:05:00", day=GYM_DAY):
        test_db.save_completed_activity(
            activity_id=activity_id, date=day, start_time=f"{day} {start}",
            activity_name="Strength", activity_type="strength_training",
            duration_sec=duration_sec, distance_km=0.0, elevation_gain_m=0.0,
            avg_hr=None, max_hr=None, rpe=6, tss=None,
        )

    def test_the_logged_sets_move_onto_the_garmin_activity(self):
        self.ingest(self.example_for(a_session()))
        self.activity("gym1")
        sets.read_new_activities(self.garmin)
        self.assertEqual(self.garmin.calls, [])
        self.assertIsNone(test_db.get_completed_activity("log:" + GYM_DAY))
        rows = test_db.get_exercise_sets("gym1")
        self.assertEqual(len([r for r in rows if r["set_type"] == "active"]), 6)
        self.assertEqual({r["named_by"] for r in rows if r["set_type"] == "active"},
                         {"athlete"})
        activity = test_db.get_completed_activity("gym1")
        self.assertTrue(activity["sets_read_at"] and activity["sets_final_at"])
        with test_db._get_connection() as conn:
            row = dict(conn.execute("SELECT * FROM gym_logs").fetchone())
        self.assertEqual(row["activity_id"], "gym1")

    def test_a_day_split_in_two_gives_the_log_to_the_longer_activity(self):
        self.ingest(self.example_for(a_session()))
        self.activity("gym_long", duration_sec=3600.0)
        self.activity("gym_short", duration_sec=900.0, start="20:00:00")
        sets.read_new_activities(self.garmin)
        self.assertEqual(self.garmin.calls, ["gym_short"])
        self.assertEqual(len(test_db.get_exercise_sets("gym_long")), 11)
        self.assertEqual(test_db.get_exercise_sets("gym_short"), [])

    def test_the_pull_reconcile_leaves_the_placeholder_standing(self):
        """Garmin never returns `log:<date>`, so the deletion reconcile would take the
        log away the same evening it was written."""
        self.ingest(self.example_for(a_session()))
        self.activity("gym1")
        self.assertEqual(test_db.prune_completed_activities(GYM_DAY, GYM_DAY, ["gym1"]), 0)
        self.assertIsNotNone(test_db.get_completed_activity("log:" + GYM_DAY))
        self.assertEqual(len(test_db.get_exercise_sets("log:" + GYM_DAY)), 11)

    def test_a_day_with_no_log_is_read_from_garmin_as_before(self):
        self.activity("gym1")
        sets.read_new_activities(self.garmin)
        self.assertEqual(self.garmin.calls, ["gym1"])

    def test_a_pull_covered_by_logs_never_logs_into_garmin(self):
        self.ingest(self.example_for(a_session()))
        self.activity("gym1")
        with patch("stamind.garmin.connect", side_effect=AssertionError("logged in")):
            sets.read_new_activities()


if __name__ == "__main__":
    unittest.main()
