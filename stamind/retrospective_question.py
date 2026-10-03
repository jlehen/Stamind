"""The question a finished mesocycle or plan puts to the athlete: how did it go?
(DESIGN_cycle_retrospective.md §4).

The date check queues it, in `stamind/cycle_records.py`. The answer is stored with the
record as typed, the retrospective writer runs at once, and its sentence is the reply.
"""
from datetime import date
from typing import Any, Dict, Optional

from stamind import clock, runtime
from stamind.db.retrospectives import DUE_AFTER_DAYS, PLAN
from stamind.output import step
from stamind.queue_kind import QUESTION, Kind, queue

KIND = "retrospective"

TELL_ME = {"label": "tell me", "ask": "How did it go, in your own words?"}

# What the athlete reads when their answer is stored and the writer failed (§5).
THANKS_LINE = "Thank you, I have noted it."

WAIT_NOTICE = "Writing down how it went"

_COUNTS = ("two", "three", "four", "five", "six", "seven", "eight", "nine", "ten")


def _day(iso: str) -> str:
    """'Oct 5'."""
    day = date.fromisoformat(iso)
    return f"{day:%b} {day.day}"


def _wording(item: Dict[str, Any]) -> str:
    payload = item["payload"]
    if payload["level"] == PLAN:
        return (f"Your plan toward “{payload['name']}” ended on "
                f"{_day(payload['end_date'])}. How did it go?")
    return (f"How did “{payload['name']}” ({_day(payload['start_date'])} to "
            f"{_day(payload['end_date'])}) go for you?")


def _companion_wording(item: Dict[str, Any]) -> str:
    payload = item["payload"]
    if payload["level"] == PLAN:
        return f"Your plan toward “{payload['name']}” is finished. How did it go for you?"
    days = clock.days_between(payload["start_date"], payload["end_date"]) + 1
    weeks = round(days / 7)
    if weeks < 2:
        return "Your last week of training is done. How did it go for you?"
    count = _COUNTS[weeks - 2] if weeks - 2 < len(_COUNTS) else str(weeks)
    return f"Your last {count} weeks of training are done. How did they go for you?"


def _is_stale(item: Dict[str, Any]) -> bool:
    """Stale once its record is removed, and seven days after the end of its record."""
    record = runtime.db.get_retrospective(item["payload"]["record_id"])
    if record is None:
        return True
    return clock.days_between(record["end_date"], clock.today_str()) >= DUE_AFTER_DAYS


def _apply(item: Dict[str, Any], index: int, text: Optional[str]) -> str:
    """Stores the athlete's words, then has the record written with them in hand. The
    stored words make the record due, so the next run of the write step tries a failed
    write again."""
    record_id = item["payload"]["record_id"]
    runtime.db.set_retrospective_words(record_id, (text or "").strip())
    record = runtime.db.get_retrospective(record_id)
    try:
        return runtime.coach_service.write_retrospective(record, WAIT_NOTICE) or THANKS_LINE
    except Exception as e:
        step(f"The retrospective was not written, the next run tries again: {e}")
        return THANKS_LINE


RETROSPECTIVE_KIND = Kind(
    name=KIND, shape=QUESTION,
    wording=_wording, companion_wording=_companion_wording,
    is_stale=_is_stale, apply=_apply, drop_label="nothing to say",
)


def ask_about(record: Dict[str, Any]) -> None:
    """Queues the question about one record. Its subject is the record's id, so a record
    that was removed and created again can be asked about."""
    queue(KIND, str(record["id"]), {
        "record_id": record["id"],
        "level": record["level"],
        "name": record["name"],
        "start_date": record["start_date"],
        "end_date": record["end_date"],
        "answers": [dict(TELL_ME)],
    })
