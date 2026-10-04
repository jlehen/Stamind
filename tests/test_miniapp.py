"""The Mini App's copy of the exercise table (DESIGN_exercise_table.md §8).

`miniapp/exercises.json` is what the page shows and searches when the athlete swaps or adds
an exercise. It is generated from `stamind/strength/exercises.tsv`, so editing the table
without rebuilding it would leave the page offering keys the ingest then refuses. These
tests fail on that.
"""
import importlib.util
import json
import os
import unittest

from stamind.strength import vocabulary

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
MINIAPP_DIR = os.path.join(REPO_ROOT, "miniapp")
JSON_PATH = os.path.join(MINIAPP_DIR, "exercises.json")
BUILDER_PATH = os.path.join(MINIAPP_DIR, "build_exercises.py")

REBUILD = "Run: venv/bin/python miniapp/build_exercises.py"


def _builder():
    """`miniapp/build_exercises.py`, which is a script beside the page and not a package."""
    spec = importlib.util.spec_from_file_location("miniapp_build_exercises", BUILDER_PATH)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _rows():
    with open(JSON_PATH, encoding="utf-8") as handle:
        return json.load(handle)


class ExerciseCatalogTest(unittest.TestCase):

    def test_the_file_is_exactly_what_the_builder_writes(self):
        with open(JSON_PATH, encoding="utf-8") as handle:
            on_disk = handle.read()
        self.assertEqual(on_disk, _builder().text(), REBUILD)

    def test_every_class_is_in_the_page_catalog_under_its_key(self):
        self.assertEqual([row["k"] for row in _rows()], vocabulary.keys(), REBUILD)

    def test_each_row_carries_the_words_the_pattern_the_gear_and_bodyweight(self):
        rows = _rows()
        self.assertTrue(rows)
        for row in rows:
            self.assertLessEqual({"k", "w", "p", "g", "b"}, set(row))
            self.assertLessEqual(set(row), {"k", "w", "p", "g", "b", "f", "o"})
            known = vocabulary.get(row["k"])
            self.assertIs(row.get("o", False), known.per_side)
            self.assertEqual(row["w"], vocabulary.words(row["k"]))
            self.assertEqual(row["p"], known.pattern)
            self.assertEqual(row["g"], ", ".join(known.gear))
            self.assertIs(row["b"], known.bodyweight)

    def test_a_pull_up_is_one_entry_and_it_is_bodyweight(self):
        """One entry per class: the weighted twin is the same entry with a load (§7)."""
        rows = {row["k"]: row for row in _rows()}
        self.assertNotIn("PULL_UP/WEIGHTED_PULL_UP", rows)
        self.assertEqual(rows["PULL_UP/PULL_UP"]["w"], "pull up")
        self.assertTrue(rows["PULL_UP/PULL_UP"]["b"])
        self.assertFalse(rows["LEG_CURL/LEG_CURL"]["b"])

    def test_the_linked_exercises_carry_their_photos(self):
        rows = {row["k"]: row for row in _rows()}
        self.assertEqual(rows["SQUAT/BARBELL_BACK_SQUAT"]["f"], "Barbell_Squat")
        self.assertNotIn("f", rows["SQUAT/BELT_SQUAT"])
        # The id the sandbag squat was given through a name that had lost its implement
        # is dropped (§3.7).
        self.assertNotIn("f", rows["SANDBAG/BACK_SQUAT"])


if __name__ == "__main__":
    unittest.main()
