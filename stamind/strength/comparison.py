"""A past strength session, planned against done (DESIGN_strength_planned_vs_done.md).

One pure function, `compare`, takes the planned lines (`prescribed_sets` rows) and the
lifted sets, and says which sets counted, exercise by exercise (§3). The verdict of a logged
session is built from its totals (§6). Nothing here reads the database or draws a screen.

A lifted set is a dict with `exercise` (None while unnamed), `reps`, `load_kg`,
`duration_sec`, `named_by`, and `card`: the position of the planned line its card on the
logger page stood for, or None.
"""
from dataclasses import dataclass
from typing import Any, Dict, List, Optional, Sequence

# A set counts when it is no more than this share under its line's load (§3).
NEAR = 0.10
# A logged session is done when at least this share of its planned sets counted (§6).
DONE_SHARE = 0.80

# One exercise's mark (§2).
DONE = "done"
SWAPPED = "swapped"
LIGHTER = "lighter"
SHORT = "short"
NOT_DONE = "not done"
NOT_PLANNED = "not planned"


@dataclass
class Row:
    """One exercise: its planned lines (none when it was not planned), the sets lifted for
    it in the order they were lifted, and how many of them counted."""
    exercise: str
    lines: List[Dict[str, Any]]
    sets: List[Dict[str, Any]]
    counted: int = 0
    swapped: bool = False

    @property
    def planned(self) -> int:
        return sum(line["sets"] for line in self.lines)

    @property
    def mark(self) -> str:
        if not self.lines:
            return NOT_PLANNED
        if self.swapped:
            return SWAPPED
        if self.counted >= self.planned:
            return DONE
        if not self.sets:
            return NOT_DONE
        if len(self.sets) >= self.planned:
            return LIGHTER
        return SHORT


@dataclass
class Comparison:
    """The planned exercises in the session's order, then the ones not planned; the
    positions among the lifted sets of those no one named; and how many were lifted."""
    rows: List[Row]
    unnamed: List[int]
    lifted: int

    @property
    def planned_rows(self) -> List[Row]:
        return [row for row in self.rows if row.lines]

    @property
    def counted(self) -> int:
        return sum(row.counted for row in self.planned_rows)

    @property
    def planned(self) -> int:
        return sum(row.planned for row in self.planned_rows)

    @property
    def share(self) -> float:
        return self.counted / self.planned if self.planned else 1.0


def near(lifted: Dict[str, Any], line: Dict[str, Any]) -> bool:
    """Whether a set is near a planned line: no more than 10% under its load. A line with
    no load, and a set with no load recorded, are near anything (§3)."""
    if line.get("load_kg") is None or lifted.get("load_kg") is None:
        return True
    return lifted["load_kg"] >= round(line["load_kg"] * (1 - NEAR), 6)


def _heaviest_first(lifted: Dict[str, Any]) -> tuple:
    """Known loads heaviest first, then the sets with no load recorded."""
    load = lifted.get("load_kg")
    return (load is None, -(load or 0.0))


def compare(
    lines: Sequence[Dict[str, Any]], lifted: Sequence[Dict[str, Any]]
) -> Comparison:
    """Which lifted sets counted against which planned lines (§3).

    A set with a card counts on its card's line: near its load, or with no load check when
    the athlete swapped another exercise onto the card. Every other set counts by name, the
    heaviest first, on the heaviest line of the same exercise that it is near and that still
    has room. A set that fits no line is an extra: shown, never counted."""
    rows: Dict[str, Row] = {}
    for line in lines:
        rows.setdefault(line["exercise"], Row(line["exercise"], [], [])).lines.append(line)
    by_position = {line["position"]: line for line in lines}
    room = {line["position"]: line["sets"] for line in lines}
    not_planned: Dict[str, Row] = {}
    by_name: Dict[str, List[Dict[str, Any]]] = {}
    unnamed: List[int] = []
    for number, one in enumerate(lifted, 1):
        line = by_position.get(one.get("card"))
        if line is not None:
            row = rows[line["exercise"]]
            row.sets.append(one)
            swap = one["exercise"] != line["exercise"]
            row.swapped |= swap
            if room[line["position"]] and (swap or near(one, line)):
                room[line["position"]] -= 1
                row.counted += 1
            continue
        if one["exercise"] is None:
            unnamed.append(number)
            continue
        if one["exercise"] not in rows:
            not_planned.setdefault(one["exercise"], Row(one["exercise"], [], [])).sets.append(one)
            continue
        rows[one["exercise"]].sets.append(one)
        by_name.setdefault(one["exercise"], []).append(one)
    for name, loose in by_name.items():
        row = rows[name]
        for one in sorted(loose, key=_heaviest_first):
            fits = [line for line in row.lines if room[line["position"]] and near(one, line)]
            if not fits:
                continue
            best = max(fits, key=lambda line: line.get("load_kg") or 0.0)
            room[best["position"]] -= 1
            row.counted += 1
    return Comparison(list(rows.values()) + list(not_planned.values()), unnamed, len(lifted))


def compare_session(
    w: Dict[str, Any], act: Optional[Dict[str, Any]]
) -> Optional[Comparison]:
    """A planned session against the activity it paired with, or None when the session has
    no planned lines or the activity's sets are not read. The cards count only when the log
    was written against this very revision; otherwise every set counts by name (§3)."""
    lines = w.get("prescribed_sets")
    lifted = (act or {}).get("lifted")
    if not lines or lifted is None:
        return None
    log = act.get("gym_log")
    if log is None or log.get("revision_id") != w.get("revision_id"):
        lifted = [dict(one, card=None) for one in lifted]
    return compare(lines, lifted)


def carries_gym_log(act: Optional[Dict[str, Any]]) -> bool:
    """Whether the activity carries a gym log, so its sets grade the session (§6)."""
    return bool(act) and act.get("gym_log") is not None


def totals_line(comparison: Comparison, by_sets: bool) -> str:
    """'15 of 17 planned sets · 6 of 7 exercises', and the note on a session the watch
    recorded alone, whose verdict the sets do not decide (§2)."""
    planned = comparison.planned_rows
    exercises = sum(1 for row in planned if row.counted)
    line = (f"{comparison.counted} of {comparison.planned} planned sets · "
            f"{exercises} of {len(planned)} exercises")
    return line if by_sets else line + " · graded by time and load"


def reasons(comparison: Comparison) -> List[str]:
    """The one reason a logged session is partial, or none when it is done (§6)."""
    if comparison.share >= DONE_SHARE:
        return []
    return [
        f"sets: {comparison.counted} of {comparison.planned} planned sets near their load "
        f"({comparison.share * 100:.0f}%, below {DONE_SHARE * 100:.0f}%); "
        f"{comparison.lifted} lifted"
    ]
