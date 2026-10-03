"""Write `miniapp/exercises.json` from the exercise table (DESIGN_exercise_table.md §8).

The page shows and searches an exercise's words and sends its key, so it needs both for every
class the CLI knows. Run it from the repository root after editing
`stamind/strength/exercises.tsv`:

    venv/bin/python miniapp/build_exercises.py

`tests/test_miniapp.py` fails when the file and the table disagree.
"""
import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from stamind.strength import vocabulary  # noqa: E402 — after the repository root is on the path

OUT_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "exercises.json")


def rows():
    """Every class as the page reads it: its key, its words, its pattern, its gear, whether
    it is bodyweight, and the Free Exercise DB id of its photos when it has one."""
    listed = []
    for exercise in vocabulary.all_exercises():
        row = {
            "k": exercise.key, "w": exercise.words, "p": exercise.pattern,
            "g": ", ".join(exercise.gear), "b": exercise.bodyweight,
        }
        if exercise.photos:
            row["f"] = exercise.photos
        listed.append(row)
    return listed


def text() -> str:
    """The file's exact contents, so the test can compare without rewriting it."""
    return json.dumps(rows(), ensure_ascii=False, separators=(",", ":")) + "\n"


def main():
    written = text()
    with open(OUT_PATH, "w", encoding="utf-8") as out:
        out.write(written)
    print(f"{OUT_PATH}: {len(rows())} exercises, {len(written.encode('utf-8'))} bytes")


if __name__ == "__main__":
    main()
