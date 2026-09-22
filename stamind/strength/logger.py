"""The two payloads the gym logger moves (DESIGN_gym_logger.md §3, §4).

`session_payload` and `session_url` encode today's session into the address the Mini App
button carries; `parse_log` reads back the one message the page sends when the athlete taps
"Finish". Pure functions: nothing here touches the database.
"""
import base64
import json
from datetime import date as date_type
from typing import Any, Dict, List, NamedTuple, Optional

from stamind.strength import prescription, vocabulary
from stamind.types import Workout

# The payload version both sides write and check (§3, §4).
VERSION = 1

# How much of the session's notes the button's address carries (§3).
NOTES_LIMIT = 300


class LogError(ValueError):
    """A log the page should never have sent: the wrong shape, or an exercise the
    vocabulary does not know (§5)."""


class LoggedSet(NamedTuple):
    """One set as it was done. `seconds` is the time since the session started (§4)."""
    reps: int
    load_kg: Optional[float]
    seconds: Optional[float]


class Entry(NamedTuple):
    """One exercise of a log. `position` is the prescribed row it stands for, and None for
    an exercise the session did not ask for (§4)."""
    name: str
    position: Optional[int]
    sets: List[LoggedSet]
    note: str


class Log(NamedTuple):
    """A whole log: when the session ran, what was done, and the revision the page was
    given (§4). `revision_id` is None when the page had no session to show."""
    revision_id: Optional[int]
    date: str
    start: str
    end: str
    note: str
    exercises: List[Entry]


def _notes(workout: Workout) -> str:
    """The text under the exercise lines of the description, cut to 300 characters (§3).

    `prescription.render_description` writes the exercise lines first and the notes after
    them, so the lines it would write again are dropped off the front of the body."""
    body = prescription.body_of(workout.get("description")).splitlines()
    written = prescription.exercise_lines(workout.get("prescribed_sets") or [])
    while body and written and body[0] == written[0]:
        body.pop(0)
        written.pop(0)
    return "\n".join(body).strip()[:NOTES_LIMIT]


def session_payload(workout: Workout) -> Dict[str, Any]:
    """Today's session as the page reads it (§3): the revision id, the day, the title, the
    prescribed exercises in position order, and the notes under them."""
    exercises = [
        {"n": row["exercise"], "s": row["sets"], "lo": row["reps_low"],
         "hi": row["reps_high"], "kg": row.get("load_kg")}
        for row in workout.get("prescribed_sets") or []
    ]
    return {
        "v": VERSION,
        "r": workout.get("revision_id"),
        "d": workout["date"],
        "t": workout["title"],
        "x": exercises,
        "notes": _notes(workout),
    }


def session_url(base_url: str, workout: Workout) -> str:
    """The page's address with the session in its hash fragment, which a browser never
    sends to the host serving the page (§3)."""
    blob = json.dumps(session_payload(workout), separators=(",", ":"), ensure_ascii=False)
    packed = base64.urlsafe_b64encode(blob.encode("utf-8")).decode("ascii").rstrip("=")
    return f"{base_url}#s={packed}"


def parse_log(text: str) -> Log:
    """The page's message as a `Log`, or `LogError` (§4, §5).

    Strict on purpose: the page builds the shape itself and offers vocabulary names only,
    so anything else is a bug on that side rather than an athlete's typo."""
    try:
        payload = json.loads(text)
    except ValueError as broken:
        raise LogError(f"The log is not JSON: {broken}") from None
    if not isinstance(payload, dict):
        raise LogError("The log is not a JSON object.")
    if payload.get("v") != VERSION:
        raise LogError(f"The log says version {payload.get('v')!r}, and this is version "
                       f"{VERSION}.")
    listed = payload.get("x")
    if not isinstance(listed, list) or not listed:
        raise LogError("The log has no exercises.")
    exercises = [_entry(entry, place) for place, entry in enumerate(listed, 1)]
    unknown: List[str] = []
    for entry in exercises:
        if vocabulary.get(entry.name) is None and entry.name not in unknown:
            unknown.append(entry.name)
    if unknown:
        raise LogError("The log names exercises Stamind does not know: "
                       + ", ".join(unknown) + ".")
    return Log(
        revision_id=_revision(payload.get("r")),
        date=_day(payload.get("d")),
        start=_clock(payload.get("st"), "st"),
        end=_clock(payload.get("en"), "en"),
        note=_text(payload.get("note"), "the log's note"),
        exercises=exercises,
    )


def _revision(value: Any) -> Optional[int]:
    if value is None:
        return None
    if isinstance(value, bool) or not isinstance(value, int):
        raise LogError(f"The log's revision id is {value!r}, not a number.")
    return value


def _day(value: Any) -> str:
    try:
        return date_type.fromisoformat(str(value)).isoformat()
    except (TypeError, ValueError):
        raise LogError(f"The log's date is {value!r}, not a YYYY-MM-DD day.") from None


def _clock(value: Any, field: str) -> str:
    """'18:02' as the page writes it: a local clock time, with no date and no seconds."""
    parts = str(value).split(":")
    if len(parts) != 2 or not all(part.isdigit() for part in parts):
        raise LogError(f"The log's '{field}' is {value!r}, not a HH:MM time.")
    hours, minutes = int(parts[0]), int(parts[1])
    if hours > 23 or minutes > 59:
        raise LogError(f"The log's '{field}' is {value!r}, not a HH:MM time.")
    return f"{hours:02d}:{minutes:02d}"


def _text(value: Any, what: str) -> str:
    if value is None:
        return ""
    if not isinstance(value, str):
        raise LogError(f"{what} is {value!r}, not text.")
    return value.strip()


def _entry(entry: Any, place: int) -> Entry:
    if not isinstance(entry, dict):
        raise LogError(f"Exercise {place} of the log is {entry!r}, not an object.")
    name = entry.get("n")
    if not isinstance(name, str) or not name.strip():
        raise LogError(f"Exercise {place} of the log has no name.")
    name = name.strip()
    done = entry.get("sets")
    if not isinstance(done, list) or not done:
        raise LogError(f"'{name}' has no sets.")
    return Entry(
        name=name,
        position=_position(entry.get("p"), name),
        sets=[_set(one, name) for one in done],
        note=_text(entry.get("note"), f"the note on '{name}'"),
    )


def _position(value: Any, name: str) -> Optional[int]:
    if value is None:
        return None
    if isinstance(value, bool) or not isinstance(value, int) or value < 1:
        raise LogError(f"'{name}' stands for prescribed row {value!r}, which is not a "
                       "position.")
    return value


def _set(one: Any, name: str) -> LoggedSet:
    """One set as `[reps, kg, seconds]`, `kg` null on a bodyweight exercise (§4)."""
    if not isinstance(one, list) or len(one) != 3:
        raise LogError(f"A set of '{name}' is {one!r}, not [reps, kg, seconds].")
    reps, load_kg, seconds = one
    if isinstance(reps, bool) or not isinstance(reps, int) or reps < 0:
        raise LogError(f"A set of '{name}' says {reps!r} reps.")
    return LoggedSet(reps, _number(load_kg, name, "weight"), _number(seconds, name, "time"))


def _number(value: Any, name: str, what: str) -> Optional[float]:
    if value is None:
        return None
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise LogError(f"A set of '{name}' has {value!r} for its {what}.")
    return float(value)
