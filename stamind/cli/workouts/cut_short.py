""""Was that the session, cut short?", asked when the only activity paired with a session is
far shorter than it (ARCHITECTURE.md §15, DESIGN_chat_questions.md §3).

The data cannot tell a session cut short from a warm-up, so the athlete is asked, and the
answer is stored once per activity and sport. A terminal asks on the spot, before the week
planner is called. Every other run queues the question and goes on with the app's own
pairing: the activity counts as the session, partly done.
"""
from typing import Any, Dict, List, Optional

from stamind import runtime
from stamind.analytics.compare import format_actual
from stamind.cli.workouts.session_line import workout_line
from stamind.output import warn
from stamind.queue_kind import QUESTION, YES, YES_NO, Kind, queue
from stamind.text import gray

KIND = "cut_short"
COUNTED_LINE = "Counted as that session, partially performed."
DISCARDED_LINE = "Discarded — the session reads as not done."


def _question(match: Dict[str, Any]) -> str:
    """The pairing travels inside the question: an aside is suppressed in the chat
    (DESIGN_output_verbosity.md §3.4). Each side is drawn by its own formatter, so both
    read in minutes."""
    return (
        f"Planned: {workout_line(match['planned'])}\n"
        f"Only matching activity: {format_actual(match['completed'])} — far short of it.\n"
        "Was that the session, cut short? (No = it was something else, "
        "e.g. a warm-up to discard)"
    )


def _pending(date_str: Optional[str] = None) -> Optional[List[Dict[str, Any]]]:
    """The pairings still to rule on, or None when the check fails: the question is a
    refinement, never a gate."""
    try:
        return runtime.coach_service.pending_match_questions(date_str)
    except Exception as e:
        warn(f"could not check activity matching: {e}")
        return None


def ask_on_the_spot(date_str: str) -> None:
    """A terminal with someone there: asks about each pairing before the week planner is
    told a session was performed, and stores each answer."""
    for match in _pending(date_str) or []:
        accepted = runtime.prompt.confirm("\n" + _question(match), default=False)
        runtime.coach_service.record_match_decision(
            match["activity_id"], match["sport"], accepted
        )
        print(gray("  " + (COUNTED_LINE if accepted else DISCARDED_LINE)))


def queue_questions(date_str: Optional[str] = None) -> None:
    """Queues the question about each pairing, once per activity and sport, even after it
    closed (DESIGN_chat_questions.md §3)."""
    for match in _pending(date_str) or []:
        queue(KIND, f"{match['activity_id']}:{match['sport']}", {
            "text": _question(match),
            "activity_id": match["activity_id"],
            "sport": match["sport"],
            "answers": list(YES_NO),
        })


def _wording(item: Dict[str, Any]) -> str:
    return item["payload"]["text"]


def _is_stale(item: Dict[str, Any]) -> bool:
    """No longer open: answered in a terminal, the session removed, or its day out of the
    look back. The check is the one that finds the question; when it fails, the question
    stays."""
    pending = _pending()
    if pending is None:
        return False
    payload = item["payload"]
    return not any(
        match["activity_id"] == payload["activity_id"] and match["sport"] == payload["sport"]
        for match in pending
    )


def _apply(item: Dict[str, Any], index: int, text: Optional[str]) -> str:
    payload = item["payload"]
    accepted = index == YES
    runtime.coach_service.record_match_decision(
        payload["activity_id"], payload["sport"], accepted
    )
    return COUNTED_LINE if accepted else DISCARDED_LINE


# Not a confirmation in kind, but it takes a confirmation's place at the front of the line
# and closes after the same mornings (DESIGN_chat_questions.md §8, choice 18).
CUT_SHORT_KIND = Kind(
    name=KIND, shape=QUESTION,
    wording=_wording, companion_wording=_wording,
    is_stale=_is_stale, apply=_apply, confirmation=True,
)
