"""Write `miniapp/exercises.json` from the exercise vocabulary (DESIGN_gym_logger.md §2).

The page searches the vocabulary to swap or add an exercise, so it needs the same names the
CLI knows. Run it from the repository root after editing `stamind/strength/exercises.tsv`:

    venv/bin/python miniapp/build_exercises.py

`tests/test_miniapp.py` fails when the file and the vocabulary disagree.
"""
import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from stamind.strength import vocabulary  # noqa: E402 — after the repository root is on the path

OUT_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "exercises.json")


def rows():
    """Every vocabulary exercise as the page reads it: name, pattern, equipment."""
    return [
        {"n": exercise.name, "p": exercise.pattern, "e": exercise.equipment}
        for exercise in vocabulary.all_exercises()
    ]


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
