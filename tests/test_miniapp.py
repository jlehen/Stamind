"""The Mini App's copy of the exercise vocabulary (DESIGN_gym_logger.md §2).

`miniapp/exercises.json` is what the page searches when the athlete swaps or adds an
exercise. It is generated from `stamind/strength/exercises.tsv`, so editing the vocabulary
without rebuilding it would leave the page offering names the ingest then refuses. These
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


class ExerciseCatalogTest(unittest.TestCase):

    def test_the_file_is_exactly_what_the_builder_writes(self):
        with open(JSON_PATH, encoding="utf-8") as handle:
            on_disk = handle.read()
        self.assertEqual(on_disk, _builder().text(), REBUILD)

    def test_every_vocabulary_exercise_is_in_the_page_catalog(self):
        with open(JSON_PATH, encoding="utf-8") as handle:
            rows = json.load(handle)
        self.assertEqual([row["n"] for row in rows], [x.name for x in vocabulary.all_exercises()],
                         REBUILD)

    def test_each_row_carries_a_known_pattern_and_equipment(self):
        with open(JSON_PATH, encoding="utf-8") as handle:
            rows = json.load(handle)
        self.assertTrue(rows)
        for row in rows:
            self.assertEqual(set(row), {"n", "p", "e"})
            self.assertIn(row["p"], vocabulary.PATTERNS)
            self.assertIn(row["e"], vocabulary.EQUIPMENT)


if __name__ == "__main__":
    unittest.main()
