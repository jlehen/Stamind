"""The exercise vocabulary (DESIGN_strength_tracking.md §4).

`exercises.tsv` beside this module gives every exercise one movement pattern and one
equipment class, and lists the Garmin names that mean it. It ships with the code and nobody
configures it; a name Garmin adds later is added to the file by hand.
"""
import os
from dataclasses import dataclass
from functools import lru_cache
from typing import Dict, List, Optional, Tuple

PATTERNS = (
    "squat", "hinge", "single_leg", "push_horizontal", "push_vertical", "pull_horizontal",
    "pull_vertical", "core_carry", "accessory",
)
EQUIPMENT = ("barbell", "dumbbell", "kettlebell", "cable", "machine", "bodyweight")
BODYWEIGHT = "bodyweight"
# Isolation work: written into a session at what the athlete last lifted, never progressed
# by rule (§4, §10).
ACCESSORY = "accessory"

# Above the 20–40 kg a strong athlete adds to dips and pull-ups (§6).
BODYWEIGHT_CEILING_KG = 50.0

TABLE_PATH = os.path.join(os.path.dirname(__file__), "exercises.tsv")


@dataclass(frozen=True)
class Exercise:
    name: str
    pattern: str
    equipment: str


@lru_cache(maxsize=None)
def _table() -> Tuple[Dict[str, Exercise], Dict[str, str]]:
    """(exercises by name, exercise name by Garmin name), read once per process."""
    exercises: Dict[str, Exercise] = {}
    garmin: Dict[str, str] = {}
    with open(TABLE_PATH, encoding="utf-8") as table:
        for line in table:
            if not line.strip() or line.startswith("#"):
                continue
            name, pattern, equipment, aliases = (line.rstrip("\n").split("\t") + [""])[:4]
            exercises[name] = Exercise(name, pattern, equipment)
            for alias in aliases.split():
                garmin[alias] = name
    return exercises, garmin


def get(name: Optional[str]) -> Optional[Exercise]:
    return _table()[0].get(name) if name else None


def names() -> List[str]:
    return list(_table()[0])


def garmin_key(category: str, name: Optional[str]) -> str:
    """A Garmin name as the table and `exercise_sets.garmin_name` write it: CATEGORY/NAME, or
    the bare CATEGORY for a set tagged with a category and no exercise."""
    return f"{category}/{name}" if name else category


def from_garmin(key: str) -> Optional[str]:
    """The exercise a Garmin name means, or None when the vocabulary lacks it."""
    return _table()[1].get(key)


def humanize(key: str) -> str:
    """A Garmin name in words: 'ROW/SEATED_CABLE_ROW' is 'seated cable row'."""
    return key.split("/")[-1].lower().strip("_").replace("_", " ")


def implausible(exercise: Optional[str], load_kg: Optional[float]) -> bool:
    """A bodyweight exercise at more added load than anyone adds to one (§6)."""
    known = get(exercise)
    return bool(
        known and known.equipment == BODYWEIGHT
        and load_kg is not None and load_kg > BODYWEIGHT_CEILING_KG
    )
