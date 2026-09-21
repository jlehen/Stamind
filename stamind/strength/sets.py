"""A strength activity's sets (DESIGN_strength_tracking.md §6, §7): read from Garmin once, the
morning after the activity, then frozen, with questions queued for what the watch could not
name. Also the lines that show the sets under the activity.
"""
import time
from dataclasses import dataclass
from datetime import date, timedelta
from typing import Any, Dict, List, NamedTuple, Optional, Sequence, Tuple

from stamind import clock, runtime, settings
from stamind.config import config
from stamind.db.queue import queue_stamp
from stamind.db.strength import ACTIVE, GARMIN, REST, STRENGTH_TYPE, WATCH
from stamind.queue_kind import queue
from stamind.strength import vocabulary
from stamind.output import Progress, step, warn
from stamind.clock import today_str

# The two queue kinds (§7). Their wording, check and answers are in strength/questions.py.
SETS_FINAL = "sets_final"
SET_NAMES = "set_names"


# An activity older than this when its sets are first read is frozen as read (§6).
ASK_WITHIN_DAYS = 7
# The naming question offers at most this many of the exercises of the recent strength
# days, whose number is `strength.recent_days` (§7, §8).
MAX_ANSWERS = 9

YES_FINAL = {"label": "yes, final"}
SOMETHING_ELSE = {"label": "something else…", "ask": "What was it? Type the exercise"}
SETS_NOT_READ = "sets not read yet"


class SetsRead(NamedTuple):
    """What a reading pass has to report: why it stopped early, and the Garmin names the
    vocabulary lacks."""
    failure: Optional[str]
    unknown_names: List[str]


@dataclass
class Group:
    """Consecutive active sets that are one thing: the same exercise, or unnamed at one load
    (§7). `first` is the position of its first set among the activity's active sets."""
    exercise: Optional[str]
    sets: List[Dict[str, Any]]
    first: int

    @property
    def last(self) -> int:
        return self.first + len(self.sets) - 1

    @property
    def seqs(self) -> List[int]:
        return [s["seq"] for s in self.sets]

    @property
    def reps(self) -> List[Optional[int]]:
        return [s["reps"] for s in self.sets]

    @property
    def load_kg(self) -> Optional[float]:
        return self.sets[0]["load_kg"]


def parse_sets(payload: Dict[str, Any]) -> Tuple[List[Dict[str, Any]], List[str]]:
    """Garmin's `exerciseSets` as rows to store, and the Garmin names the vocabulary lacks.

    The weight comes in grams; a negative or missing one means nothing was entered. The
    watch's guess of a bodyweight exercise at a heavy load is stored unnamed, its Garmin
    name kept (§6)."""
    rows: List[Dict[str, Any]] = []
    unknown: List[str] = []
    for seq, entry in enumerate((payload or {}).get("exerciseSets") or [], 1):
        row: Dict[str, Any] = {
            "seq": seq, "set_type": REST, "exercise": None, "garmin_name": None,
            "reps": None, "load_kg": None, "duration_sec": entry.get("duration"),
            "named_by": None,
        }
        rows.append(row)
        if entry.get("setType") != "ACTIVE":
            continue
        weight = entry.get("weight")
        row.update(
            set_type=ACTIVE, reps=entry.get("repetitionCount"),
            load_kg=weight / 1000.0 if weight is not None and weight >= 0 else None,
        )
        top = (entry.get("exercises") or [{}])[0]
        category = top.get("category")
        if not category:
            continue
        key = vocabulary.garmin_key(category, top.get("name"))
        row["garmin_name"] = key
        if category == "UNKNOWN":
            continue
        exercise = vocabulary.from_garmin(key)
        if exercise is None:
            exercise = vocabulary.humanize(key)
            if key not in unknown:
                unknown.append(key)
        named_by = GARMIN if (top.get("probability") or 0) >= 100 else WATCH
        if named_by == WATCH and vocabulary.implausible(exercise, row["load_kg"]):
            continue
        row.update(exercise=exercise, named_by=named_by)
    return rows, unknown


def groups(sets: Sequence[Dict[str, Any]]) -> List[Group]:
    """An activity's active sets as groups: consecutive sets with the same name, or unnamed
    at the same load, reps ignored (§7)."""
    found: List[Group] = []
    position = 0
    for s in sets:
        if s["set_type"] != ACTIVE:
            continue
        position += 1
        last = found[-1] if found else None
        if last and last.exercise == s["exercise"] and (
            s["exercise"] is not None or last.load_kg == s["load_kg"]
        ):
            last.sets.append(s)
            continue
        found.append(Group(s["exercise"], [s], position))
    return found


def unnamed_groups(sets: Sequence[Dict[str, Any]]) -> List[Group]:
    return [group for group in groups(sets) if group.exercise is None]


def watch_guesses(sets: Sequence[Dict[str, Any]]) -> List[str]:
    """The exercises the watch named on its own, in the order they came, each once (§6).
    Until the athlete says the sets are final these count for nothing (§8)."""
    guessed: List[str] = []
    for s in sets:
        if s["named_by"] == WATCH and s["exercise"] not in guessed:
            guessed.append(s["exercise"])
    return guessed


def fmt_kg(load_kg: float) -> str:
    """A load as the athlete writes it: '60', '62.5'."""
    return f"{round(load_kg, 2):g}"


def positions(first: int, last: int) -> str:
    return str(first) if first == last else f"{first}–{last}"


def set_span(first: int, last: int) -> str:
    """'set 5' or 'sets 5–8': positions among the activity's active sets."""
    return f"set {first}" if first == last else f"sets {first}–{last}"


def reps_and_load(
    reps: Sequence[Optional[int]], load_kg: Optional[float], companion: bool = False
) -> str:
    """'10, 10, 8, 8 reps @ 60 kg', or 'at 60 kg' in the companion's words. A group at 0 kg
    says so, and a group with no weight entered says that (§7)."""
    counts = ", ".join("?" if r is None else str(r) for r in reps)
    unit = "rep" if list(reps) == [1] else "reps"
    if load_kg is None:
        return f"{counts} {unit}, no weight entered"
    return f"{counts} {unit} {'at' if companion else '@'} {fmt_kg(load_kg)} kg"


def set_chunks(sets: Sequence[Dict[str, Any]]) -> str:
    """'1×5 @ 40, 4×4 @ 80': the sets as they were done, consecutive equal ones collapsed.
    A set with no reps is a timed one and shows its seconds (§7, §8)."""
    chunks: List[List[Any]] = []
    for s in sets:
        key = (s["reps"], s["load_kg"],
               None if s["reps"] is not None else s.get("duration_sec"))
        if chunks and chunks[-1][0] == key:
            chunks[-1][1] += 1
            continue
        chunks.append([key, 1])
    parts = []
    for (reps, load_kg, duration), count in chunks:
        amount = str(reps) if reps is not None else f"{round(duration or 0)}s"
        weight = f" @ {fmt_kg(load_kg)}" if load_kg else ""
        parts.append(f"{count}×{amount}{weight}")
    return ", ".join(parts)


def watch_mark(sets: Sequence[Dict[str, Any]]) -> str:
    """The mark on a name only the watch guessed (§7)."""
    return " (watch)" if any(s["named_by"] == WATCH for s in sets) else ""


def named_line(group: Group) -> str:
    """'deadlift 1×5 @ 40, 4×4 @ 80 (watch)': what was lifted, with a mark on a name only
    the watch guessed (§7)."""
    return f"{group.exercise} {set_chunks(group.sets)}{watch_mark(group.sets)}"


def position_list(numbers: Sequence[int]) -> str:
    """'set 5', 'sets 1, 3, 7–9': positions among the activity's active sets, runs joined."""
    runs: List[List[int]] = []
    for number in numbers:
        if runs and runs[-1][1] == number - 1:
            runs[-1][1] = number
            continue
        runs.append([number, number])
    word = "set" if len(numbers) == 1 else "sets"
    return f"{word} " + ", ".join(positions(first, last) for first, last in runs)


def activity_lines(activity: Dict[str, Any]) -> List[str]:
    """What was lifted, for under the activity line (§7): one line per exercise, in the order
    the exercises first came, so alternating two exercises still reads as two lines; then
    the unnamed sets. An activity whose sets are still to be read says so; an activity whose
    sets are never read, or that returned none, gets no line."""
    if activity.get("activity_type") != STRENGTH_TYPE:
        return []
    since = settings.strength_sets_since()
    if not since or activity["date"] < since:
        return []
    if not activity.get("sets_read_at"):
        return [SETS_NOT_READ]
    by_exercise: Dict[str, Group] = {}
    unnamed: List[int] = []
    for group in groups(runtime.db.get_exercise_sets(activity["activity_id"])):
        if group.exercise is None:
            unnamed.extend(range(group.first, group.last + 1))
            continue
        if group.exercise in by_exercise:
            by_exercise[group.exercise].sets.extend(group.sets)
            continue
        by_exercise[group.exercise] = Group(group.exercise, list(group.sets), group.first)
    lines = [named_line(group) for group in by_exercise.values()]
    if unnamed:
        lines.append(f"{position_list(unnamed)} unnamed")
    if lines and activity.get("discarded"):
        lines.append("discarded: counts as training, not for planning weights")
    return lines


def activity_ref(activity: Dict[str, Any]) -> Dict[str, Any]:
    """The part of a question's payload that names the activity: its day and start time, so a
    day with two strength activities tells them apart however late the second came in (§7)."""
    start = (activity.get("start_time") or "")[11:16] or None
    return {"activity_id": activity["activity_id"], "date": activity["date"], "time": start}


def recent_exercises() -> List[str]:
    """The exercises named in the recent strength days, discarded activities skipped, the
    ones done on the most days first (§7). How many days is `strength.recent_days` (§8)."""
    days: List[str] = []
    done_on: Dict[str, set] = {}
    last_seen: Dict[str, int] = {}
    for row in runtime.db.activity_exercises_by_day():
        if row["date"] not in days:
            if len(days) == config.strength_recent_days:
                break
            days.append(row["date"])
        if not row["exercise"]:
            continue
        done_on.setdefault(row["exercise"], set()).add(row["date"])
        last_seen.setdefault(row["exercise"], len(days))
    ranked = sorted(done_on, key=lambda name: (-len(done_on[name]), last_seen[name], name))
    return ranked[:MAX_ANSWERS]


class Logged(NamedTuple):
    """One lift on one day: the day, and that day's sets in words."""
    date: str
    sets: str


def logbook() -> Dict[str, List[Logged]]:
    """Every lift on record, with the days it was done oldest first (§7). A day with two
    lifting activities is one session (§3); discarded sessions and unnamed sets are not on
    record."""
    by_day: Dict[str, Dict[str, List[Dict[str, Any]]]] = {}
    for row in runtime.db.exercise_history():
        by_day.setdefault(row["exercise"], {}).setdefault(row["date"], []).append(row)
    return {
        exercise: [Logged(day, set_chunks(rows) + watch_mark(rows))
                   for day, rows in days.items()]
        for exercise, days in by_day.items()
    }


def read_new_activities(client: Any = None) -> SetsRead:
    """Reads the sets of every strength activity from `strength-sets-since` on, dated before
    today and never read, and freezes each or asks whether it is final (§6). Logs into
    Garmin only when there is something to read."""
    since = settings.strength_sets_since()
    if not since:
        return SetsRead(None, [])
    today = today_str()
    pending = runtime.db.strength_activities(since, before=today, unread=True)
    if not pending:
        return SetsRead(None, [])
    client = client or runtime.garmin.connect()
    count = len(pending)
    step(f"Reading the sets of {count} strength activit{'y' if count == 1 else 'ies'}...")
    unknown: List[str] = []
    with Progress(count) as bar:
        for activity in pending:
            try:
                payload = client.get_activity_exercise_sets(activity["activity_id"])
            except Exception as e:
                return SetsRead(f"{activity['date']}: {e}", unknown)
            rows, new_names = parse_sets(payload)
            unknown.extend(name for name in new_names if name not in unknown)
            _first_read(activity, rows, today)
            bar.step()
            if config.garmin_throttle_seconds:
                time.sleep(config.garmin_throttle_seconds)
    return SetsRead(None, unknown)


def report(result: SetsRead) -> None:
    """What `data pull` says about a reading pass (§4, §6)."""
    if result.failure:
        warn(f"Could not read the strength sets of {result.failure}. "
             "The rest are read on the next pull.")
    if result.unknown_names:
        warn("Garmin exercise names not in the vocabulary, stored as they came: "
             + ", ".join(result.unknown_names)
             + ". Add them to stamind/strength/exercises.tsv.")


def _first_read(activity: Dict[str, Any], rows: List[Dict[str, Any]], today: str) -> None:
    """Stores a first read and freezes it, unless the watch guessed a name or left sets
    unnamed and the activity is recent enough for the athlete to fix it in Connect: then it
    asks whether the sets are final (§6)."""
    activity_id = activity["activity_id"]
    now = clock.now()
    if not any(row["set_type"] == ACTIVE for row in rows):
        runtime.db.store_exercise_sets(activity_id, [], now, now)
        return
    unnamed = unnamed_groups(rows)
    guessed = watch_guesses(rows)
    asked_from = (date.fromisoformat(today) - timedelta(days=ASK_WITHIN_DAYS)).isoformat()
    if (not unnamed and not guessed) or activity["date"] < asked_from:
        runtime.db.store_exercise_sets(activity_id, rows, now, now)
        return
    runtime.db.store_exercise_sets(activity_id, rows, now, None)
    queue(SETS_FINAL, activity_id, {
        **activity_ref(activity),
        "groups": [[group.first, group.last] for group in unnamed],
        "guesses": guessed,
        "answers": [YES_FINAL],
    })


def read_again(activity: Dict[str, Any], client: Any) -> List[Group]:
    """Reads an activity's sets again, replacing the rows and the answers on them, freezes them
    and queues a naming question per group still unnamed; returns every group (§6, §7).

    The watch's guesses still standing become the athlete's, because this runs when the
    athlete has just said the names in Garmin are right (§6). Garmin's errors propagate,
    and then nothing has changed."""
    payload = client.get_activity_exercise_sets(activity["activity_id"])
    rows, _ = parse_sets(payload)
    now = clock.now()
    runtime.db.store_exercise_sets(activity["activity_id"], rows, now, now)
    runtime.db.confirm_watch_names(activity["activity_id"])
    found = groups(rows)
    ask_names(activity, queue_stamp(now), [group for group in found if group.exercise is None])
    return found


def ask_names(activity: Dict[str, Any], final_at: str, unnamed: Sequence[Group]) -> None:
    """Queues one naming question per group, all offering the same answers (§7)."""
    if not unnamed:
        return
    answers = [{"label": name} for name in recent_exercises()] + [SOMETHING_ELSE]
    named = activity_ref(activity)
    for group in unnamed:
        subject = f"{activity['activity_id']}:{final_at}:{group.first}-{group.last}"
        queue(SET_NAMES, subject, {
            **named, "final_at": final_at, "first": group.first, "last": group.last,
            "seqs": group.seqs, "reps": group.reps, "load_kg": group.load_kg,
            "answers": answers,
        })
