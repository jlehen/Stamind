"""The `pass_to_coach` kind of the athlete queue: "Shall I pass it to your coach?", asked when
a message read as a goal or constraint edit names a session (DESIGN_bot_simple_frontend.md
§12.4, DESIGN_long_runs_beside_chat.md §5).

The question is saved and sent, and the command that asked it ends. Its "Yes" starts
`workout adapt -m` with the athlete's own words, beside the chat (§6 there): the tap closes
the item, then goes on in `cli/queue_commands.py`. A module of its own because the list of
kinds imports it, and `bot capture`, which asks it, imports the queue's sender.
"""
from typing import Any, Dict, Optional

from stamind import clock, runtime
from stamind.chat.routing import COACH_RUN
from stamind.clock import today_str
from stamind.db.queue import queue_stamp
from stamind.queue_kind import QUESTION, Kind, queue

KIND = "pass_to_coach"

# It says which reading was dropped, so the router's echo a moment earlier ("sounds like a
# change to a goal") has its correction on screen, and what a "yes" sets in motion, because
# the help card is not on screen at that moment (DESIGN_bot_simple_frontend.md §12.4).
SESSION_HANDOFF_ASK = (
    "I don't see a {noun} for that — it sounds like {named}. Shall I pass it to your "
    "coach? They'll reread the coming days with it in mind and propose changes for you "
    "to confirm."
)
ANSWERS = ({"label": "✅ Yes"}, {"label": "✖️ No"})
YES = 0
LEFT_LINE = "Okay — I'll leave it."
CLOSED_LINE = (
    "That question is out of date, so I passed nothing on. Write to me again if you still "
    "want a change."
)


def _text(item: Dict[str, Any]) -> str:
    return item["payload"]["text"]


def _apply(item: Dict[str, Any], index: int, text: Optional[str]) -> Optional[str]:
    """"No" writes nothing. "Yes" says nothing here: the coach's run that follows speaks."""
    if index == YES:
        return None
    return LEFT_LINE


# Out of date once the day of the session it names is over (DESIGN_long_runs_beside_chat.md
# §5, choice 3a).
PASS_TO_COACH_KIND = Kind(
    name=KIND, shape=QUESTION,
    wording=_text, companion_wording=_text,
    is_stale=lambda item: item["payload"]["date"] < today_str(),
    apply=_apply, bare=True, confirmation=True,
    long_run=(YES, COACH_RUN), closed_line=CLOSED_LINE,
)


def queue_question(
    noun: str, named: str, session: Dict[str, Any], message: str
) -> Optional[Dict[str, Any]]:
    """Saves the question about `session`, which the athlete's `message` names, and returns
    its item. `noun` is the reading that was dropped, "goal" or "constraint"."""
    item_id = queue(KIND, queue_stamp(clock.now()), {
        "text": SESSION_HANDOFF_ASK.format(noun=noun, named=named),
        "answers": list(ANSWERS),
        "message": message,
        "date": session["date"],
    })
    return runtime.db.get_queue_item(item_id) if item_id else None
