"""The one-off conversion of the stored exercise names to keys (DESIGN_exercise_table.md §9).

The fixture is a small database holding the old names in the three places the script
rewrites: sets read from Garmin and from the page, a planned session, and the page's log
kept as sent.
"""
import contextlib
import importlib.util
import io
import json
import os
import shutil
import sqlite3
import tempfile
import unittest
from datetime import datetime, timezone
from unittest import mock

from stamind.db import Database
from stamind.strength import vocabulary

_SCRIPT = os.path.join(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
    "scripts", "migrate_exercise_names.py",
)
_spec = importlib.util.spec_from_file_location("migrate_exercise_names", _SCRIPT)
migrate = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(migrate)

DAY = "2026-10-02"
NOW = datetime(2026, 10, 3, 8, 0, tzinfo=timezone.utc)

# The page's log of that Friday, as an old page sent it.
OLD_LOG = {
    "v": 1, "r": 1, "d": DAY, "st": "18:02", "en": "19:05",
    "x": [
        {"n": "back squat", "p": 1, "sets": [[5, 55, 40], [5, 70, 200]]},
        {"n": "belt squat", "sets": [[6, 140, 400]]},
    ],
}


def lifted(seq, exercise, garmin_name=None, load_kg=None):
    return {"seq": seq, "set_type": "active", "exercise": exercise,
            "garmin_name": garmin_name, "reps": 5, "load_kg": load_kg, "named_by": "garmin"}


def planned(exercise, load_kg=None):
    return {"exercise": exercise, "sets": 3, "reps_low": 4, "reps_high": 6, "load_kg": load_kg}


class _ConversionCase(unittest.TestCase):
    def setUp(self):
        self.dir = tempfile.mkdtemp(prefix="stamind-exercise-names-test-")
        self.addCleanup(shutil.rmtree, self.dir, True)
        self.path = os.path.join(self.dir, "athlete.db")
        self.db = Database(db_path=self.path)
        self.db.save_completed_activity(
            activity_id="gym", date=DAY, start_time=f"{DAY} 18:02:00",
            activity_name="Strength", activity_type="strength_training", duration_sec=3600.0,
            distance_km=0.0, elevation_gain_m=0.0, avg_hr=None, max_hr=None, rpe=6, tss=None,
        )

    def store(self, *rows):
        self.db.store_exercise_sets("gym", list(rows), NOW, NOW)

    def plan(self, *rows):
        with self.db.workout_change(kind="generate") as change:
            change.append(
                date="2026-10-05", sport_type="strength_training", title="Gym",
                description="[Gym]\nHeavy.\n\nBack squat 3×4–6 @ 70 kg", duration_minutes=60,
                prescribed_sets=list(rows),
            )

    def log(self, payload=OLD_LOG):
        self.db.save_gym_log("gym", 1, json.dumps(payload, separators=(",", ":")))

    def convert(self, *renames, yes=True):
        """Runs the script on the fixture. Returns its exit code and what it printed."""
        printed = io.StringIO()
        with contextlib.redirect_stdout(printed):
            code = migrate.convert(self.path, migrate.parse_renames(list(renames)), yes)
        return code, printed.getvalue()

    def stored(self):
        """What the three places hold now."""
        conn = sqlite3.connect(self.path)
        try:
            lifted_now = [row[0] for row in conn.execute(
                "SELECT exercise FROM exercise_sets ORDER BY seq")]
            planned_now = [row[0] for row in conn.execute(
                "SELECT exercise FROM prescribed_sets ORDER BY id")]
            logs = [json.loads(row[0]) for row in conn.execute("SELECT payload FROM gym_logs")]
            logged_now = [entry["n"] for log in logs for entry in log["x"]]
            return lifted_now, planned_now, logged_now
        finally:
            conn.close()


class RulesTest(_ConversionCase):
    """The five rules, in order."""

    def test_a_name_whose_line_was_merged_takes_the_key_of_its_line(self):
        """§3.2: the farmer's walk is the farmer's carry, and its line is gone."""
        self.store(lifted(1, "CARRY/FARMERS_WALK", "CARRY/FARMERS_WALK", 40.0),
                   lifted(2, "CARRY/FARMERS_CARRY", None, 40.0))
        self.plan(planned("CARRY/FARMERS_WALK", 40.0))
        self.log({**OLD_LOG, "x": [{"n": "CARRY/FARMERS_WALK", "sets": [[20, 40, 60]]}]})
        code, out = self.convert()
        self.assertEqual(code, 0, out)
        self.assertEqual(self.stored(), (["CARRY/FARMERS_CARRY"] * 2,
                                         ["CARRY/FARMERS_CARRY"], ["CARRY/FARMERS_CARRY"]))
        self.assertIn("CARRY/FARMERS_WALK  →  CARRY/FARMERS_CARRY   (1 set, 1 planned line, "
                      "1 log entry; 40 kg)", out)
        self.assertEqual(self.convert()[1], "No old name is stored. Nothing to convert.\n")

    def test_a_name_with_one_key_in_the_list_takes_it_in_all_three_places(self):
        self.store(lifted(1, "belt squat", "SQUAT/BELT_SQUAT", 140.0))
        self.plan(planned("belt squat", 140.0))
        self.log({**OLD_LOG, "x": [{"n": "belt squat", "sets": [[6, 140, 400]]}]})
        code, out = self.convert()
        self.assertEqual(code, 0, out)
        self.assertEqual(self.stored(), (["SQUAT/BELT_SQUAT"],) * 3)
        self.assertIn("belt squat  →  SQUAT/BELT_SQUAT   (1 set, 1 planned line, "
                      "1 log entry; 140 kg)", out)

    def test_a_split_line_goes_to_the_class_of_the_sets_own_garmin_name(self):
        """`clean` was the barbell clean and the sandbag clean on one line. A set Garmin
        tagged `SANDBAG/CLEAN` goes to the sandbag clean."""
        self.store(lifted(1, "clean", "SANDBAG/CLEAN", 20.0),
                   lifted(2, "clean", "OLYMPIC_LIFT/CLEAN", 60.0))
        code, out = self.convert()
        self.assertEqual(code, 0, out)
        self.assertEqual(self.stored()[0], ["SANDBAG/CLEAN", "OLYMPIC_LIFT/CLEAN"])
        self.assertIn("clean  →  OLYMPIC_LIFT/CLEAN   (1 set; 60 kg)", out)
        self.assertIn("clean  →  SANDBAG/CLEAN   (1 set; 20 kg)", out)

    def test_a_split_line_with_no_garmin_name_is_not_settled_and_nothing_is_written(self):
        """The planned line has no Garmin name, so `clean` is not settled, although its set
        alone would be. The script never picks one of several classes itself."""
        self.store(lifted(1, "clean", "SANDBAG/CLEAN", 20.0),
                   lifted(2, "belt squat", "SQUAT/BELT_SQUAT", 140.0))
        self.plan(planned("clean", 20.0))
        before = self.stored()
        code, out = self.convert()
        self.assertEqual(code, 1)
        self.assertEqual(self.stored(), before)
        self.assertIn("clean  →  NOT SETTLED   (1 set, 1 planned line; 20 kg)", out)
        self.assertIn("one of: OLYMPIC_LIFT/CLEAN, SANDBAG/CLEAN", out)
        self.assertIn('--rename "clean=KEY"', out)
        self.assertNotIn("clean  →  SANDBAG/CLEAN", out)

    def test_a_rename_wins_in_all_three_places(self):
        """`back squat` was the sandbag squat's only name. The athlete squats with a
        barbell, and says so."""
        self.store(lifted(1, "back squat", "SANDBAG/BACK_SQUAT", 70.0))
        self.plan(planned("back squat", 70.0))
        self.log()
        code, out = self.convert("back squat=SQUAT/BARBELL_BACK_SQUAT")
        self.assertEqual(code, 0, out)
        self.assertEqual(self.stored(), (
            ["SQUAT/BARBELL_BACK_SQUAT"], ["SQUAT/BARBELL_BACK_SQUAT"],
            ["SQUAT/BARBELL_BACK_SQUAT", "SQUAT/BELT_SQUAT"],
        ))

    def test_a_name_the_list_lacks_is_not_settled_until_it_is_renamed(self):
        self.store(lifted(1, "moon squat", "SQUAT/MOON_SQUAT", 20.0))
        code, out = self.convert()
        self.assertEqual(code, 1)
        self.assertIn("moon squat  →  NOT SETTLED", out)
        code, _ = self.convert("moon squat=SQUAT/AIR_SQUAT")
        self.assertEqual(code, 0)
        self.assertEqual(self.stored()[0], ["SQUAT/AIR_SQUAT"])

    def test_a_renames_key_must_be_a_key_of_the_table(self):
        """A weighted twin is a Garmin name of the table and not a key."""
        for key in ("SQUAT/MOON_SQUAT", "PULL_UP/WEIGHTED_PULL_UP", "pull up"):
            with self.assertRaises(SystemExit, msg=key):
                migrate.parse_renames([f"pull up={key}"])
        self.assertEqual(migrate.parse_renames(["pull up = PULL_UP/PULL_UP"]),
                         {"pull up": "PULL_UP/PULL_UP"})


class RunTest(_ConversionCase):
    def setUp(self):
        super().setUp()
        self.store(lifted(1, "belt squat", "SQUAT/BELT_SQUAT", 140.0),
                   lifted(2, None), lifted(3, "SQUAT/GOBLET_SQUAT", "SQUAT/GOBLET_SQUAT"))
        self.plan(planned("belt squat", 140.0))
        self.log({**OLD_LOG, "x": [{"n": "belt squat", "sets": [[6, 140, 400]]}]})

    def test_a_second_run_changes_nothing(self):
        self.assertEqual(self.convert()[0], 0)
        with open(self.path, "rb") as handle:
            converted = handle.read()
        code, out = self.convert()
        self.assertEqual(code, 0)
        self.assertIn("No old name is stored.", out)
        with open(self.path, "rb") as handle:
            self.assertEqual(handle.read(), converted)

    def test_only_a_value_still_an_old_name_is_changed(self):
        """An unnamed set stays unnamed and a key stays as it is."""
        self.convert()
        self.assertEqual(self.stored()[0], ["SQUAT/BELT_SQUAT", None, "SQUAT/GOBLET_SQUAT"])

    def test_the_log_keeps_everything_but_its_names(self):
        self.convert()
        conn = sqlite3.connect(self.path)
        try:
            payload = conn.execute("SELECT payload FROM gym_logs").fetchone()[0]
        finally:
            conn.close()
        self.assertEqual(json.loads(payload), {
            **OLD_LOG, "x": [{"n": "SQUAT/BELT_SQUAT", "sets": [[6, 140, 400]]}],
        })

    def test_the_description_is_left_alone(self):
        self.convert()
        description = Database(db_path=self.path).get_workouts()[0]["description"]
        self.assertIn("Back squat 3×4–6 @ 70 kg", description)

    def test_it_writes_only_after_a_yes(self):
        before = self.stored()
        for answer, code_wanted in (("", 1), ("n", 1), ("y", 0)):
            with mock.patch("builtins.input", return_value=answer):
                code, _ = self.convert(yes=False)
            self.assertEqual(code, code_wanted, answer)
            if code_wanted:
                self.assertEqual(self.stored(), before)
        self.assertEqual(self.stored()[1], ["SQUAT/BELT_SQUAT"])

    def test_a_waiting_what_was_this_question_stops_it_before_anything(self):
        item_id = self.db.queue_item("set_names", "gym:x:2-2", {"answers": []}, NOW)
        before = self.stored()
        code, out = self.convert()
        self.assertEqual(code, 1)
        self.assertEqual(self.stored(), before)
        self.assertIn(f"id {item_id}  set_names", out)
        self.assertNotIn("belt squat", out)

    def test_a_waiting_proposal_stops_it_and_a_closed_one_does_not(self):
        item_id = self.db.queue_item("proposal", "2026-10-03T08:00:00", {"text": "x"}, NOW)
        code, out = self.convert()
        self.assertEqual(code, 1)
        self.assertIn(f"id {item_id}  proposal", out)
        self.db.close_queue_item(item_id, "answered", NOW)
        self.assertEqual(self.convert()[0], 0)

    def test_a_waiting_are_the_sets_final_question_is_left_alone(self):
        """Its names are only shown, and "yes, final" reads the sets from Garmin again."""
        self.db.queue_item("sets_final", "gym", {"guesses": ["belt squat"]}, NOW)
        self.assertEqual(self.convert()[0], 0)


class ListTest(unittest.TestCase):
    """`scripts/exercise_name_migration.tsv`, the list the script reads."""

    def setUp(self):
        self.listed = migrate.read_migration()

    def test_every_key_of_the_list_is_a_key_of_the_table(self):
        for old, keys in self.listed.items():
            self.assertTrue(keys, old)
            for key in keys:
                self.assertIsNotNone(vocabulary.get(key), f"{old}: {key}")

    def test_every_old_name_is_lower_case_so_a_key_is_never_read_as_one(self):
        for old in self.listed:
            self.assertTrue(migrate.is_old(old), old)
        for key in vocabulary.keys():
            self.assertFalse(migrate.is_old(key), key)

    def test_a_split_line_lists_the_classes_it_became(self):
        self.assertEqual(self.listed["clean and press"],
                         ["OLYMPIC_LIFT/CLEAN_AND_PRESS", "SANDBAG/CLEAN_AND_PRESS"])
        self.assertEqual(self.listed["plank"], [
            "PLANK/PLANK", "POSE/PLANK", "BANDED_EXERCISES/PLANK", "SUSPENSION/PLANK",
        ])

    def test_the_leg_extension_has_the_band_exercise_and_the_added_machine(self):
        self.assertEqual(self.listed["leg extension"],
                         ["BANDED_EXERCISES/LEG_EXTENSION", "SQUAT/LEG_EXTENSION"])

    def test_an_old_machine_name_maps_to_its_added_key(self):
        self.assertEqual(self.listed["pec deck"], ["FLYE/PEC_DECK"])
        self.assertEqual(self.listed["machine chest press"],
                         ["BENCH_PRESS/MACHINE_CHEST_PRESS"])


if __name__ == "__main__":
    unittest.main()
