"""The exercise table and the words worked out from a key (DESIGN_exercise_table.md §3, §4,
§11): the five checks on the table as written, the words rule, and what the vocabulary module
gives for a key and for a Garmin name."""
import unittest
from collections import Counter

from stamind.strength import prescription, sets, vocabulary


def table_lines():
    """The table's lines as written, the `+` mark dropped: (names, pattern, muscles, gear)."""
    lines = []
    with open(vocabulary.TABLE_PATH, encoding="utf-8") as table:
        for line in table:
            if line.startswith("#") or not line.strip():
                continue
            names, pattern, muscles, gear = (line.rstrip("\n").split("\t") + [""] * 3)[:4]
            names = [name.lstrip(vocabulary.ADDED_MARK) for name in names.split()]
            lines.append((names, pattern, muscles, gear))
    return lines


class TableTest(unittest.TestCase):
    """The five checks of §11, read from the file itself: the loader would let a name on two
    lines pass, the second line winning."""

    def test_a_garmin_name_is_on_one_line_only(self):
        counts = Counter(name for names, *_ in table_lines() for name in names)
        self.assertEqual([name for name, count in counts.items() if count > 1], [])

    def test_the_names_of_a_line_share_one_category(self):
        mixed = [names for names, *_ in table_lines()
                 if len({name.split("/")[0] for name in names}) > 1]
        self.assertEqual(mixed, [])

    def test_every_gear_word_is_one_of_the_46(self):
        self.assertEqual(len(set(vocabulary.GEAR)), 46)
        for names, _pattern, _muscles, gear in table_lines():
            self.assertTrue(gear, f"{names[0]} has no gear")
            for word in gear.split(", "):
                self.assertIn(word, vocabulary.GEAR, names[0])

    def test_no_two_classes_show_the_same_words(self):
        """Nor does a name people use read like another class (§3.2)."""
        counts = Counter(vocabulary.words(name) for one in vocabulary.all_exercises()
                         for name in (one.key,) + one.also)
        self.assertEqual([words for words, count in counts.items() if count > 1], [])

    def test_a_weighted_twin_sits_on_the_line_of_its_exercise(self):
        """§3.2: `C/WEIGHTED_X` shares the line of `C/X`, or of `C/_X`, since Garmin drops a
        leading underscore after `WEIGHTED_`. A weighted name whose exercise the table lacks
        keeps a line of its own."""
        line_of = {name: index for index, (names, *_) in enumerate(table_lines())
                   for name in names}
        apart = []
        for name, index in line_of.items():
            category, _, exercise = name.partition("/")
            if not exercise.startswith("WEIGHTED_"):
                continue
            rest = exercise[len("WEIGHTED_"):]
            for plain in (f"{category}/{rest}", f"{category}/_{rest}"):
                if line_of.get(plain, index) != index:
                    apart.append((name, plain))
        self.assertEqual(apart, [])

    def test_a_pattern_is_one_of_the_nine_or_empty(self):
        for names, pattern, _muscles, _gear in table_lines():
            self.assertIn(pattern, vocabulary.PATTERNS + ("",), names[0])


class WordsTest(unittest.TestCase):
    """The words rule of §4."""

    def test_the_category_a_colon_and_the_name(self):
        self.assertEqual(vocabulary.words("SQUAT/BELT_SQUAT"), "squat: belt squat")
        self.assertEqual(vocabulary.words("PULL_UP/LAT_PULLDOWN"), "pull up: lat pulldown")

    def test_a_name_equal_to_its_category_shows_once(self):
        self.assertEqual(vocabulary.words("DEADLIFT/DEADLIFT"), "deadlift")
        self.assertEqual(vocabulary.words("LEG_CURL/LEG_CURL"), "leg curl")

    def test_a_bare_category_shows_once(self):
        self.assertEqual(vocabulary.words("ROW"), "row")
        self.assertEqual(vocabulary.words("TRICEPS_EXTENSION"), "triceps extension")

    def test_a_leading_underscore_is_dropped(self):
        self.assertEqual(vocabulary.words("PULL_UP/_30_DEGREE_LAT_PULLDOWN"),
                         "pull up: 30 degree lat pulldown")

    def test_an_added_exercise_reads_like_any_other(self):
        self.assertEqual(vocabulary.words("SQUAT/STEP_DOWN"), "squat: step down")

    def test_a_key_the_table_lacks_has_words_too(self):
        self.assertEqual(vocabulary.words("SQUAT/MOON_SQUAT"), "squat: moon squat")


class ClassTest(unittest.TestCase):
    """What the module gives for a key, and for any Garmin name (§11)."""

    def test_a_key_gives_its_class(self):
        pull_up = vocabulary.get("PULL_UP/PULL_UP")
        self.assertEqual(pull_up.names,
                         ("PULL_UP/PULL_UP", "PULL_UP/WEIGHTED_PULL_UP", "PULL_UP"))
        self.assertEqual(pull_up.pattern, "pull_vertical")
        self.assertEqual(pull_up.muscles, ("LATS", "TRAPS"))
        self.assertEqual(pull_up.secondary, ("BICEPS", "FOREARM", "SHOULDERS"))
        self.assertEqual(pull_up.gear, ("Pull-up Bar",))
        self.assertEqual(pull_up.photos, "Pullups")
        self.assertEqual(pull_up.words, "pull up")
        self.assertFalse(pull_up.added)

    def test_a_garmin_name_gives_the_key_of_its_class(self):
        """A key, a weighted twin, a bare category, and a name the table lacks."""
        self.assertEqual(vocabulary.key_of("SQUAT/BELT_SQUAT"), "SQUAT/BELT_SQUAT")
        self.assertEqual(vocabulary.key_of("PULL_UP/WEIGHTED_PULL_UP"), "PULL_UP/PULL_UP")
        self.assertEqual(vocabulary.key_of("ROW"), "ROW/ROW")
        self.assertIsNone(vocabulary.key_of("SQUAT/MOON_SQUAT"))
        # Only a key names a class: the twin is found through `key_of`.
        self.assertIsNone(vocabulary.get("PULL_UP/WEIGHTED_PULL_UP"))

    def test_an_implement_is_a_class_of_its_own(self):
        """The barbell squat and the sandbag squat no longer share a line (§1)."""
        self.assertEqual(vocabulary.get("SANDBAG/BACK_SQUAT").gear, ("Sandbag",))
        self.assertEqual(vocabulary.get("SQUAT/BARBELL_BACK_SQUAT").gear,
                         ("Barbell", "Squat Rack"))

    def test_a_class_can_have_no_pattern_and_no_muscles(self):
        wheel = vocabulary.get("POSE/WHEEL")
        self.assertEqual((wheel.pattern, wheel.muscles, wheel.secondary), ("", (), ()))
        self.assertEqual(wheel.gear, ("Nothing",))

    def test_an_added_exercise_is_marked_and_its_key_has_no_mark(self):
        step_down = vocabulary.get("SQUAT/STEP_DOWN")
        self.assertTrue(step_down.added)
        self.assertEqual(vocabulary.key_of("SQUAT/STEP_DOWN"), "SQUAT/STEP_DOWN")
        self.assertIsNone(vocabulary.get("+SQUAT/STEP_DOWN"))
        self.assertEqual(sum(1 for one in vocabulary.all_exercises() if one.added), 36)

    def test_a_name_people_use_finds_its_class_and_is_never_a_key(self):
        """§3.2: Garmin's cable core press is what people call the Pallof press."""
        press = vocabulary.get("CORE/CABLE_CORE_PRESS")
        self.assertEqual(press.also, ("CORE/PALLOF_PRESS",))
        self.assertEqual(press.also_words, ("pallof press",))
        self.assertFalse(press.added)
        self.assertEqual(press.words, "core: cable core press")
        self.assertEqual(vocabulary.key_of("CORE/PALLOF_PRESS"), "CORE/CABLE_CORE_PRESS")
        self.assertIsNone(vocabulary.get("CORE/PALLOF_PRESS"))
        self.assertEqual(vocabulary.searched("CORE/CABLE_CORE_PRESS"),
                         "core: cable core press pallof press")
        # A class with no such name, and a key the table lacks, are matched on their words.
        self.assertEqual(vocabulary.searched("SQUAT/BELT_SQUAT"), "squat: belt squat")
        self.assertEqual(vocabulary.searched("SQUAT/MOON_SQUAT"), "squat: moon squat")

    def test_an_exercise_is_bodyweight_when_none_of_its_gear_is_a_load(self):
        """§3.6: a pull-up bar is not a load, a machine is."""
        self.assertTrue(vocabulary.get("PULL_UP/PULL_UP").bodyweight)
        self.assertTrue(vocabulary.get("CALF_RAISE/CALF_RAISE").bodyweight)
        self.assertTrue(vocabulary.get("CURL/DEAD_HANG_BICEPS_CURL").bodyweight)
        self.assertFalse(vocabulary.get("LEG_CURL/LEG_CURL").bodyweight)
        self.assertFalse(vocabulary.get("SQUAT/BARBELL_BACK_SQUAT").bodyweight)

    def test_a_heavy_load_on_a_bodyweight_exercise_is_implausible(self):
        self.assertTrue(vocabulary.implausible("SIT_UP/SIT_UP", 100.0))
        self.assertFalse(vocabulary.implausible("SIT_UP/SIT_UP", 20.0))
        self.assertFalse(vocabulary.implausible("SIT_UP/SIT_UP", None))
        self.assertFalse(vocabulary.implausible("LEG_CURL/LEG_CURL", 100.0))
        self.assertFalse(vocabulary.implausible("SQUAT/MOON_SQUAT", 100.0))

    def test_the_line_the_strength_planner_is_shown(self):
        """§7: the key, then the pattern, the main muscles and the gear, then "per side" on
        an exercise done one side at a time."""
        self.assertEqual(vocabulary.model_line("SQUAT/BARBELL_BACK_SQUAT"),
                         "SQUAT/BARBELL_BACK_SQUAT (squat; QUADS, GLUTES; Barbell, Squat Rack)")
        self.assertEqual(vocabulary.model_line("POSE/WHEEL"), "POSE/WHEEL (Nothing)")
        self.assertEqual(vocabulary.model_line("SQUAT/MOON_SQUAT"), "SQUAT/MOON_SQUAT")
        self.assertEqual(
            vocabulary.model_line("ROW/ONE_ARM_BENT_OVER_ROW"),
            "ROW/ONE_ARM_BENT_OVER_ROW (pull_horizontal; LATS, TRAPS; Dumbbells; per side)")


class PerSideTest(unittest.TestCase):
    """The reps column (§3.8) and the mark it puts after the reps
    (DESIGN_strength_tracking.md §4)."""

    def test_the_reps_column_is_per_side_or_empty(self):
        with open(vocabulary.TABLE_PATH, encoding="utf-8") as table:
            for line in table:
                if line.startswith("#") or not line.strip():
                    continue
                fields = line.rstrip("\n").split("\t")
                self.assertLessEqual(len(fields), 6, fields[0])
                if len(fields) == 6:
                    self.assertIn(fields[5], ("", vocabulary.PER_SIDE), fields[0])

    def test_one_side_at_a_time_is_marked_whether_the_sides_take_turns_or_not(self):
        for key in ("ROW/ONE_ARM_BENT_OVER_ROW", "LUNGE/DUMBBELL_BULGARIAN_SPLIT_SQUAT",
                    "LUNGE/WALKING_LUNGE", "CURL/ALTERNATING_DUMBBELL_BICEPS_CURL",
                    "PLANK/SIDE_PLANK"):
            self.assertTrue(vocabulary.get(key).per_side, key)
        for key in ("SQUAT/BARBELL_BACK_SQUAT", "PULL_UP/PULL_UP", "ROW/DUMBBELL_ROW",
                    "CALF_RAISE/CALF_RAISE"):
            self.assertFalse(vocabulary.get(key).per_side, key)

    def test_the_mark_follows_the_reps_wherever_they_are_printed(self):
        row = "ROW/ONE_ARM_BENT_OVER_ROW"
        self.assertEqual(vocabulary.side_mark(row), "/side")
        self.assertEqual(vocabulary.side_mark("SQUAT/BARBELL_BACK_SQUAT"), "")
        self.assertEqual(vocabulary.side_mark("SQUAT/MOON_SQUAT"), "")
        self.assertEqual(vocabulary.side_mark(None), "")
        planned = [
            {"exercise": row, "sets": 1, "reps_low": 8, "reps_high": 8, "load_kg": 20.0},
            {"exercise": row, "sets": 3, "reps_low": 8, "reps_high": 10, "load_kg": 30.0},
        ]
        self.assertEqual(prescription.spec(planned), "1×8/side @ 20, 3×8–10/side @ 30")
        done = [{"exercise": row, "reps": 9, "load_kg": 30.0, "duration_sec": 40.0}] * 3
        self.assertEqual(sets.set_chunks(done), "3×9/side @ 30")
        held = [{"exercise": "PLANK/SIDE_PLANK", "reps": None, "load_kg": None,
                 "duration_sec": 30.0}] * 2
        self.assertEqual(sets.set_chunks(held), "2×30s/side")
        squat = [{"exercise": "SQUAT/BARBELL_BACK_SQUAT", "reps": 5, "load_kg": 100.0,
                  "duration_sec": 20.0}]
        self.assertEqual(sets.set_chunks(squat), "1×5 @ 100")


class SimilarTest(unittest.TestCase):
    """The exercises like a key (DESIGN_strength_tracking.md §7)."""

    def test_the_names_sharing_the_most_words_come_first(self):
        self.assertEqual(vocabulary.similar("OLYMPIC_LIFT/CLEAN_AND_PRESS", set(), 9)[:2], [
            "OLYMPIC_LIFT/DUMBBELL_POWER_CLEAN_AND_PUSH_PRESS",
            "OLYMPIC_LIFT/DUMBBELL_POWER_CLEAN_AND_STRICT_PRESS",
        ])

    def test_the_athletes_own_come_first_and_only_from_the_same_category(self):
        own = {"SQUAT/LEG_PRESS", "ROW/RENEGADE_ROW"}
        self.assertEqual(vocabulary.similar("SQUAT/GOBLET_SQUAT", own, 9),
                         ["SQUAT/LEG_PRESS", "SQUAT/WIDE_STANCE_GOBLET_SQUAT"])

    def test_a_word_the_category_already_says_makes_nothing_alike(self):
        """Every squat has SQUAT in its name, so a bare squat is like the athlete's own only."""
        self.assertEqual(vocabulary.similar("SQUAT/SQUAT", set(), 9), [])
        self.assertEqual(vocabulary.similar("SQUAT/SQUAT", {"SQUAT/BELT_SQUAT"}, 9),
                         ["SQUAT/BELT_SQUAT"])

    def test_a_category_that_fits_is_offered_whole(self):
        """The hip swings are five, so a one arm swing is offered the four others, the plain
        hip swing among them, though the only word they share is the category's own."""
        self.assertEqual(vocabulary.similar("HIP_SWING/ONE_ARM_SWING", set(), 9), [
            "HIP_SWING/SINGLE_ARM_DUMBBELL_SWING", "HIP_SWING/SINGLE_ARM_KETTLEBELL_SWING",
            "HIP_SWING/HIP_SWING", "HIP_SWING/STEP_OUT_SWING",
        ])

    def test_no_more_than_asked_for(self):
        self.assertEqual(len(vocabulary.similar("OLYMPIC_LIFT/CLEAN_AND_PRESS", set(), 3)), 3)

    def test_a_link_word_makes_nothing_alike(self):
        alike = vocabulary.similar("OLYMPIC_LIFT/CLEAN_AND_PRESS", set(), 9)
        self.assertNotIn("OLYMPIC_LIFT/SNATCH", alike)
        self.assertEqual([key for key in alike if "CLEAN" not in key and "PRESS" not in key], [])

    def test_a_key_the_table_lacks_is_like_nothing(self):
        self.assertEqual(vocabulary.similar("SQUAT/MOON_SQUAT", set(), 9), [])


if __name__ == "__main__":
    unittest.main()
