"""The exercise table (DESIGN_exercise_table.md §3, §4).

`exercises.tsv` beside this module holds one class of exercises per line: the Garmin names
whose kilograms compare, the class's movement pattern, its muscles, the gear it needs, and the
Free Exercise DB entry whose photos show it. The first name of a line is the class's key, and
the key is what the database stores. The words a person reads are worked out from the key by
`words`. The table ships with the code and nobody configures it; a name Garmin adds later is
added to the file by hand.
"""
import os
from dataclasses import dataclass
from functools import lru_cache
from typing import Dict, List, Optional, Tuple

PATTERNS = (
    "squat", "hinge", "single_leg", "push_horizontal", "push_vertical", "pull_horizontal",
    "pull_vertical", "core_carry", "accessory",
)
# Isolation work: written into a session at what the athlete last lifted, never progressed
# by rule (DESIGN_strength_tracking.md §4, §10).
ACCESSORY = "accessory"

# The 46 gear words (§3.6). An exercise none of whose gear is a load is a bodyweight one.
NOT_LOADS = (
    "Nothing", "Bench", "Adjustable Bench", "Decline Bench", "Preacher Bench", "Roman Chair",
    "Box", "Mat", "Pull-up Bar", "Dip Device", "Parallettes", "Rings", "Suspension Trainer",
    "Anchor", "Squat Rack", "Blocks", "Swiss Ball", "Sliding Discs", "Foam Roller",
    "Balance Trainer", "Jump Rope", "Agility Ladder", "Ab Wheel", "Climbing Rope", "Pole",
    "Cable Attachment",
)
LOADS = (
    "Barbell", "EZ Bar", "Trap Bar", "Safety Squat Bar", "Body Bar", "Dumbbells",
    "Kettlebells", "Weight Plates", "Medicine Ball", "Sandbag", "Ruck", "Band",
    "Cable Machine", "Machine", "Smith Machine", "Landmine", "Sled", "Tire", "Sledge Hammer",
    "Battle Rope",
)
GEAR = NOT_LOADS + LOADS

# Above the 20–40 kg a strong athlete adds to dips and pull-ups (DESIGN_strength_tracking.md
# §6).
BODYWEIGHT_CEILING_KG = 50.0

# The mark on a line of the table whose exercise Garmin has no name for (§3.3).
ADDED_MARK = "+"

TABLE_PATH = os.path.join(os.path.dirname(__file__), "exercises.tsv")


@dataclass(frozen=True)
class Exercise:
    """One class of the table (§3.1). `names` are its Garmin names, the key first."""
    key: str
    names: Tuple[str, ...]
    # "" when the class has no pattern (§3.4).
    pattern: str
    # The main muscles, then the secondary ones (§3.5).
    muscles: Tuple[str, ...]
    secondary: Tuple[str, ...]
    gear: Tuple[str, ...]
    # Free Exercise DB id whose photos the gym logger shows (§3.7).
    photos: Optional[str] = None
    # An exercise Garmin has no name for (§3.3).
    added: bool = False

    @property
    def bodyweight(self) -> bool:
        """Whether its load is a weight added to the body: none of its gear is a load (§3.6)."""
        return not any(word in LOADS for word in self.gear)

    @property
    def words(self) -> str:
        return words(self.key)


def _listed(text: str, separator: str) -> Tuple[str, ...]:
    return tuple(item for item in text.split(separator) if item)


@lru_cache(maxsize=None)
def _table() -> Tuple[Dict[str, Exercise], Dict[str, str]]:
    """(classes by key, key by Garmin name), read once per process. A line may stop after its
    last filled column (§3.1)."""
    classes: Dict[str, Exercise] = {}
    keys: Dict[str, str] = {}
    with open(TABLE_PATH, encoding="utf-8") as table:
        for line in table:
            if not line.strip() or line.startswith("#"):
                continue
            fields = (line.rstrip("\n").split("\t") + [""] * 4)[:5]
            listed, pattern, muscles, gear, photos = fields
            names = tuple(listed.lstrip(ADDED_MARK).split())
            main, _, secondary = muscles.partition("|")
            exercise = Exercise(
                key=names[0], names=names, pattern=pattern, muscles=_listed(main, ","),
                secondary=_listed(secondary, ","), gear=_listed(gear, ", "),
                photos=photos or None, added=listed.startswith(ADDED_MARK),
            )
            classes[exercise.key] = exercise
            for name in names:
                keys[name] = exercise.key
    return classes, keys


def get(key: Optional[str]) -> Optional[Exercise]:
    """The class a key names, or None when the table has no such key."""
    return _table()[0].get(key) if key else None


def keys() -> List[str]:
    """Every key, in table order."""
    return list(_table()[0])


def all_exercises() -> List[Exercise]:
    """Every class the table holds, in table order."""
    return list(_table()[0].values())


def garmin_name(category: str, name: Optional[str]) -> str:
    """A Garmin name as the table and `exercise_sets.garmin_name` write it: CATEGORY/NAME, or
    the bare CATEGORY for a set tagged with a category and no exercise (§2)."""
    return f"{category}/{name}" if name else category


def key_of(name: Optional[str]) -> Optional[str]:
    """The key of the class holding a Garmin name, or None when the table lacks the name. A
    weighted twin gives the key of its class (§6, §7)."""
    return _table()[1].get(name) if name else None


def words(key: str) -> str:
    """A key as a person reads it (§4): 'SQUAT/BELT_SQUAT' is 'squat: belt squat'. A name equal
    to its category, and a bare category, show once."""
    parts = [part.lower().strip("_").replace("_", " ") for part in key.split("/", 1)]
    if len(parts) == 1 or parts[0] == parts[1]:
        return parts[0]
    return f"{parts[0]}: {parts[1]}"


def model_line(key: str) -> str:
    """A class as the strength planner is shown it (§7): 'SQUAT/BELT_SQUAT (squat; QUADS,
    GLUTES; Machine)'. A key the table lacks is the key alone."""
    known = get(key)
    if known is None:
        return key
    tags = [known.pattern, ", ".join(known.muscles), ", ".join(known.gear)]
    return f"{key} ({'; '.join(tag for tag in tags if tag)})"


def implausible(key: Optional[str], load_kg: Optional[float]) -> bool:
    """A bodyweight exercise at more added load than anyone adds to one
    (DESIGN_strength_tracking.md §6)."""
    known = get(key)
    return bool(
        known and known.bodyweight and load_kg is not None and load_kg > BODYWEIGHT_CEILING_KG
    )
