"""The two questions whose "Yes" starts the coach beside the chat
(DESIGN_long_runs_beside_chat.md §5, §6; DESIGN_chat_questions.md §4).

`pass_to_coach`, "Shall I pass it to your coach?", is asked when a message read as a goal or
constraint edit names a session, when the chat could not store a message, and after a
preference with no end date. Its "Yes" starts `workout adapt -m` with the athlete's own
words. `adjust_week`, "Shall I adjust your week around this constraint?", follows a "Yes" that
stored a constraint or a signal. Its "Yes" starts `workout adapt` with no message.

The questions are saved, and the command that asked them sends them and ends. The tap closes
the item, then goes on in `cli/queue_commands.py`.
"""
from datetime import datetime
from typing import Any, Dict, Optional

from stamind import clock, runtime
from stamind.chat.routing import COACH_RUN
from stamind.clock import today_str
from stamind.cli.workouts.proposal import KIND as PROPOSAL
from stamind.db.queue import queue_stamp
from stamind.queue_kind import QUESTION, YES, YES_NO, Kind, queue

KIND = "pass_to_coach"
ADJUST_WEEK = "adjust_week"

PASS_IT_ASK = "Shall I pass it to your coach?"
# It says which reading was dropped, so the router's echo a moment earlier ("sounds like a
# change to a goal") has its correction on screen, and what a "yes" sets in motion, because
# the help card is not on screen at that moment (DESIGN_bot_simple_frontend.md §12.4).
SESSION_HANDOFF_ASK = (
    "I don't see a {noun} for that — it sounds like {named}. " + PASS_IT_ASK + " They'll "
    "reread the coming days with it in mind and propose changes for you to confirm."
)
LEFT_LINE = "Okay — I'll leave it."
CLOSED_LINE = (
    "That question is out of date, so I passed nothing on. Write to me again if you still "
    "want a change."
)
ADJUST_WEEK_ASK = "Shall I adjust your week around this {noun}?"
LEAVE_WEEK_LINE = "Okay — I'll leave your week as it is."


def _text(item: Dict[str, Any]) -> str:
    return item["payload"]["text"]


def _session_over(item: Dict[str, Any]) -> bool:
    """Out of date once the day of the session it names is over. A question that names no
    session waits for its mornings alone (DESIGN_long_runs_beside_chat.md §5, choice 3a)."""
    day = item["payload"]["date"]
    return day is not None and day < today_str()


def _apply(item: Dict[str, Any], index: int, text: Optional[str]) -> Optional[str]:
    """"No" writes nothing. "Yes" says nothing here: the coach's run that follows speaks."""
    if index == YES:
        return None
    return LEFT_LINE


PASS_TO_COACH_KIND = Kind(
    name=KIND, shape=QUESTION,
    wording=_text, companion_wording=_text,
    is_stale=_session_over, apply=_apply, bare=True, confirmation=True,
    long_run=(YES, COACH_RUN), closed_line=CLOSED_LINE,
)


def queue_hand_off(
    text: str, message: str, day: Optional[str] = None
) -> Optional[Dict[str, Any]]:
    """Saves "Shall I pass it to your coach?", `text` being the whole question, for the
    athlete's `message`, and returns its item. `day` is the day of the session it names, if
    it names one."""
    item_id = queue(KIND, queue_stamp(clock.now()), {
        "text": text, "answers": list(YES_NO), "message": message, "date": day,
    })
    return runtime.db.get_queue_item(item_id) if item_id else None


def queue_question(
    noun: str, named: str, session: Dict[str, Any], message: str
) -> Optional[Dict[str, Any]]:
    """Saves the question about `session`, which the athlete's `message` names, and returns
    its item. `noun` is the reading that was dropped, "goal" or "constraint"."""
    return queue_hand_off(
        SESSION_HANDOFF_ASK.format(noun=noun, named=named), message, session["date"]
    )


def _coach_looked(item: Dict[str, Any]) -> bool:
    """Whether the week planner read the week after the question was asked, in the morning
    run or for a message to the coach: an `adapt` pass held or applied, or a proposal saved
    (DESIGN_chat_questions.md §4)."""
    asked = datetime.fromisoformat(item["queued_at"])
    change = runtime.db.newest_adapt()
    if change and datetime.fromisoformat(change["created_at"]) > asked:
        return True
    return any(
        proposal["queued_at"] > item["queued_at"]
        for proposal in runtime.db.queue_items_since(PROPOSAL, asked)
    )


def _apply_adjust_week(item: Dict[str, Any], index: int, text: Optional[str]) -> Optional[str]:
    """"No" leaves the week. "Yes" says nothing here: the coach's run that follows speaks."""
    if index == YES:
        return None
    return LEAVE_WEEK_LINE


ADJUST_WEEK_KIND = Kind(
    name=ADJUST_WEEK, shape=QUESTION,
    wording=_text, companion_wording=_text,
    is_stale=_coach_looked, apply=_apply_adjust_week, bare=True, confirmation=True,
    long_run=(YES, COACH_RUN),
)


def ask_to_adjust_week(noun: str, run: str) -> None:
    """Saves "Shall I adjust your week around this {noun}?" after a "Yes" that stored a
    constraint or a signal. `run` is when the run that asked about it started: one such
    question per message, whatever its "Yes"es."""
    queue(ADJUST_WEEK, run, {
        "text": ADJUST_WEEK_ASK.format(noun=noun), "answers": list(YES_NO),
    })
