"""The strength history (DESIGN_strength_tracking.md §8): what the athlete recently lifted,
written out for the strength planner and for nothing else.

Built on read from `exercise_sets` and `prescribed_sets`. Nothing is stored for it and it
holds no computed number: it lists what was prescribed beside what was done, and the
progression in `progression.md` is what turns that into the next session's kilograms.
"""
from dataclasses import dataclass, field
from datetime import date, timedelta
from typing import Any, Dict, List, Optional, Sequence, Set

from trainmate import runtime, settings
from trainmate.db.strength import STRENGTH_TYPE
from trainmate.strength import prescription, sets, vocabulary

# How many strength days decide which exercises appear, and how many of its own days each
# exercise then shows (§8, §12: both are a first guess).
RECENT_DAYS = 8
DAYS_PER_EXERCISE = 3

# A prompt section of its own, so the heading is a section name and the caveat its first
# line (DESIGN_prompt_structure.md §2).
HEADING = (
    "## STRENGTH HISTORY\n"
    "The exercises a person named in the last 8 strength days. Loads are in kg as recorded,\n"
    "per exercise: they are not comparable across exercises, and the smaller number is often\n"
    "the harder lift."
)
NOT_DONE_HEADING = "NOT DONE"
SETS_NOT_READ = sets.SETS_NOT_READ


@dataclass
class _Activity:
    """One strength activity of a day: when it started, how hard it was, what was lifted."""
    activity_id: str
    start: str
    rpe: Optional[float]
    rows: List[Dict[str, Any]] = field(default_factory=list)

    def of(self, exercise: str) -> List[Dict[str, Any]]:
        return [row for row in self.rows if row["exercise"] == exercise]


@dataclass
class _Prescription:
    """What a planned strength session asked of one day (§9)."""
    title: str
    light: bool
    by_exercise: Dict[str, List[Dict[str, Any]]]


def _day_words(day: str) -> str:
    """'Mon Sep 7', the way the entries head a line."""
    as_date = date.fromisoformat(day)
    return f"{as_date:%a %b} {as_date.day}"


def _activities_by_day(since: str) -> Dict[str, List[_Activity]]:
    """Every strength activity from `since` on that was not discarded, by day, each with
    the sets a person named in it."""
    by_day: Dict[str, List[_Activity]] = {}
    by_id: Dict[str, _Activity] = {}
    for row in runtime.db.strength_set_rows(since):
        activity = by_id.get(row["activity_id"])
        if activity is None:
            activity = _Activity(
                activity_id=row["activity_id"],
                start=(row["start_time"] or "")[11:16],
                rpe=row["rpe"],
            )
            by_id[row["activity_id"]] = activity
            by_day.setdefault(row["date"], []).append(activity)
        if row["exercise"]:
            activity.rows.append(row)
    return by_day


def _prescriptions(since: str, until: str) -> Dict[str, _Prescription]:
    """Per date, the live strength session's prescribed exercises. A session with no
    prescribed sets — one written before phase 2, or the athlete's own — has no entry."""
    workouts = runtime.db.get_workouts(
        start_date=since, end_date=until, sport_type=STRENGTH_TYPE
    )
    rows_by_revision = runtime.db.prescribed_sets_for_revisions(
        [w["revision_id"] for w in workouts]
    )
    found: Dict[str, _Prescription] = {}
    for workout in workouts:
        rows = rows_by_revision.get(workout["revision_id"], [])
        if not rows:
            continue
        by_exercise: Dict[str, List[Dict[str, Any]]] = {}
        for row in rows:
            by_exercise.setdefault(row["exercise"], []).append(row)
        found[workout["date"]] = _Prescription(
            title=workout["title"],
            light=any(row["light"] for row in rows),
            by_exercise=by_exercise,
        )
    return found


def _days_to_show(
    exercise: str, days: Sequence[str], by_day: Dict[str, List[_Activity]],
    prescriptions: Dict[str, _Prescription],
) -> List[str]:
    """An exercise's last three days that were not light, plus every light day since the
    oldest of them (§8).

    A light week is not a step, so the week after resumes from the day before it: an athlete
    who lifts three times a week would otherwise open the next Monday with three light days
    and nothing before them.
    """
    shown: List[str] = []
    counted = 0
    for day in days:
        if not any(activity.of(exercise) for activity in by_day.get(day, [])):
            continue
        light = day in prescriptions and prescriptions[day].light
        if not light:
            counted += 1
        shown.append(day)
        if counted == DAYS_PER_EXERCISE:
            break
    return shown


def _day_lines(
    exercise: str, day: str, activities: Sequence[_Activity],
    prescribed: Optional[_Prescription],
) -> List[str]:
    """One day of one exercise: what was prescribed on the day, then what was done. A day
    the watch split into two activities shows each on its own line, with its start time and
    its own RPE, because merging them reads as the morning's work fading (§8)."""
    head = _day_words(day)
    if prescribed is not None and exercise in prescribed.by_exercise:
        entries = prescription.spec(prescribed.by_exercise[exercise])
        head += f", prescribed {entries}" + (" (light)" if prescribed.light else "")
    lifted = [(a, a.of(exercise)) for a in activities]
    lifted = [(a, rows) for a, rows in lifted if rows]
    if len(lifted) == 1:
        activity, rows = lifted[0]
        return [f"    {head}: {sets.collapsed(rows)}{_rpe(activity)}"]
    lines = [f"    {head}:"]
    for activity, rows in lifted:
        lines.append(f"      {activity.start}: {sets.collapsed(rows)}{_rpe(activity)}")
    return lines


def _rpe(activity: _Activity) -> str:
    return f" | RPE {activity.rpe:g}" if activity.rpe is not None else ""


def _not_done_lines(
    oldest_shown: Optional[str], by_day: Dict[str, List[_Activity]],
    prescriptions: Dict[str, _Prescription], since: str, today: str,
) -> List[str]:
    """What was prescribed and not done, one line per day (§8).

    An entry above shows an exercise only when the athlete did it, so chin-ups prescribed
    every Monday and never lifted would appear nowhere and be written again blind. The walk
    covers every day from the oldest the entries show through yesterday — the same span, so
    the two sections are read together — and stops there: a session planned for today can
    still be done, whatever the hour.
    """
    if oldest_shown is None:
        return []
    unread = _days_with_unread_sets(since, today)
    lines: List[str] = []
    day = date.fromisoformat(today) - timedelta(days=1)
    oldest = date.fromisoformat(oldest_shown)
    while day >= oldest:
        this_day, day = day.isoformat(), day - timedelta(days=1)
        prescribed = prescriptions.get(this_day)
        if prescribed is None:
            continue
        if this_day in unread:
            lines.append(f"  {_day_words(this_day)}: {SETS_NOT_READ}")
            continue
        activities = by_day.get(this_day, [])
        whole = ", ".join(
            f"{name} {prescription.spec(rows)}"
            for name, rows in prescribed.by_exercise.items()
        )
        if not activities:
            lines.append(f"  {_day_words(this_day)}: no strength activity ({whole})")
            continue
        missed = [
            f"{name} {prescription.spec(rows)}"
            for name, rows in prescribed.by_exercise.items()
            if not any(activity.of(name) for activity in activities)
        ]
        if missed:
            lines.append(f"  {_day_words(this_day)}: {', '.join(missed)}")
    return lines


def _days_with_unread_sets(since: str, today: str) -> set:
    """The days holding a strength activity whose sets are not read yet (§6). Such a day is
    not a day the athlete skipped: TrainMate simply does not know yet."""
    return {
        activity["date"]
        for activity in runtime.db.strength_activities(since, before=today)
        if not activity["sets_read_at"] and not activity["discarded"]
    }


@dataclass(frozen=True)
class History:
    """What the strength planner is shown of the athlete's lifting, and every exercise a
    person named on record — the second is what the prompt's vocabulary adds its accessories
    from (§9), and both come from the one pass over the sets."""
    text: str
    exercises: Set[str]


def build(today: str) -> History:
    """The whole history (§8). Its text is "" when no sets are read."""
    since = settings.strength_sets_since()
    if not since:
        return History("", set())
    by_day = _activities_by_day(since)
    days = sorted(by_day, reverse=True)
    on_record = {
        row["exercise"]
        for activities in by_day.values() for activity in activities
        for row in activity.rows
    }
    if not days:
        return History("", on_record)
    prescriptions = _prescriptions(since, today)
    recent = days[:RECENT_DAYS]

    # Which exercises appear: the ones a person named in the recent days, in the order they
    # are met walking those days from the newest. The eight days decide which exercises
    # appear, not how much of each is shown (§8).
    listed: List[str] = []
    for day in recent:
        for activity in by_day[day]:
            for row in activity.rows:
                if row["exercise"] not in listed:
                    listed.append(row["exercise"])

    lines = [HEADING]
    shown: List[str] = []
    for exercise in listed:
        known = vocabulary.get(exercise)
        tags = f" ({known.pattern}, {known.equipment})" if known else ""
        lines.append(f"  {exercise}{tags}")
        for day in _days_to_show(exercise, days, by_day, prescriptions):
            shown.append(day)
            lines.extend(_day_lines(exercise, day, by_day[day], prescriptions.get(day)))

    not_done = _not_done_lines(
        min(shown) if shown else None, by_day, prescriptions, since, today
    )
    if not_done:
        lines.append("")
        lines.append(NOT_DONE_HEADING)
        lines.extend(not_done)
    return History("\n".join(lines), on_record)
