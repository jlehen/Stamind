"""The queue of things Stamind wants to tell or ask the athlete (DESIGN_athlete_queue.md).

The list of kinds, the line and the actions. The queue knows nothing about what an item
asks: each kind brings its wording, its check and what its answers do (§8). `message`, the
operator's note from `sm queue tell`, is the first kind and the smallest one.

Every waiting item has a ready time. The line is the waiting items whose ready time has
passed, the earliest first, and one item is out at a time (§13.2).
"""
from datetime import datetime, timedelta
from typing import Any, Dict, List, Optional, Tuple

from stamind import clock, heads_up, runtime, settings
from stamind.db.queue import queue_stamp
# Re-exported: what a feature needs lives in queue_kind, so a feature can queue items
# without importing the list of kinds that imports it.
from stamind.queue_kind import (  # noqa: F401
    ANSWERED, DROPPED, MESSAGE, QUESTION, STALE, Kind, NotApplied, queue,
)
from stamind.cli.bot.test_result import TEST_RESULT_KIND
from stamind.cli.candidates import CONSTRAINT_KIND, NOTE_KIND, SIGNAL_KIND
from stamind.cli.workouts.proposal import PROPOSAL_KIND
from stamind.learning_doubts import LEARNING_KIND
from stamind.retrospective_question import RETROSPECTIVE_KIND
from stamind.strength.questions import SET_NAMES_KIND, SETS_FINAL_KIND

# The action codes a chooser returns and a button carries (§6.2). An answer is `a<n>`, the
# n-th answer stored with the item.
DROP = "d"
SKIP = "s"

# The "later" choices of a queued item: action code, the terminal chooser's words, and the
# chat button "Not now" swaps in, which the bot builds from the tap itself. "After the
# others" has no button: in the chat both others already put the item behind the rest
# (§13.4, §13.5).
QUEUE_LATER_HOUR = "h"
QUEUE_LATER_DAY = "t"
QUEUE_LATER_BACK = "b"
QUEUE_NOT_NOW = "n"
QUEUE_LATER_CHOICES = (
    (QUEUE_LATER_HOUR, "in 1 hour", "⏰ In 1 hour"),
    (QUEUE_LATER_DAY, "tomorrow", "⏰ Ask me tomorrow"),
    (QUEUE_LATER_BACK, "after the others", None),
)


# A message is a question whose only answer is "got it", and it has no drop (§4).
MESSAGE_ANSWERS = ({"label": "got it"},)


def _message_text(item: Dict[str, Any]) -> str:
    return item["payload"]["text"]


# The operator's note (§5.1): never stale, and acknowledging it changes nothing else.
MESSAGE_KIND = Kind(
    name="message", shape=MESSAGE,
    wording=_message_text, companion_wording=_message_text,
    is_stale=lambda item: False, apply=lambda item, index, text: None,
)

# The strength kinds ask for a session's sets (DESIGN_strength_tracking.md §7), and the
# learning kind whether a doubted learning still fits (DESIGN_learning_doubt_nudge.md §5),
# the test-result kind what a test done yesterday gave (DESIGN_benchmark_from_chat.md §4),
# and the retrospective kind how a finished mesocycle went (DESIGN_cycle_retrospective.md §4).
# The proposal kind holds what the week planner would change (DESIGN_waiting_proposal.md §3).
# The constraint and signal kinds ask whether to store what a message stated (§6.3 there),
# and the session-note kind which session the message is about (DESIGN_session_notes.md §3).
KINDS: Dict[str, Kind] = {
    kind.name: kind
    for kind in (
        MESSAGE_KIND, SETS_FINAL_KIND, SET_NAMES_KIND, LEARNING_KIND, TEST_RESULT_KIND,
        RETROSPECTIVE_KIND, PROPOSAL_KIND, NOTE_KIND, CONSTRAINT_KIND, SIGNAL_KIND,
    )
}


def kind_of(item: Dict[str, Any]) -> Kind:
    return KINDS[item["kind"]]


def wording(item: Dict[str, Any], companion: bool = False) -> str:
    kind = kind_of(item)
    return kind.companion_wording(item) if companion else kind.wording(item)


def drop_label(item: Dict[str, Any]) -> Optional[str]:
    """What this item's drop button says, or None when its kind offers no drop (§4)."""
    label = kind_of(item).drop_label
    return label(item) if callable(label) else label


def answers(item: Dict[str, Any]) -> List[Dict[str, Any]]:
    """The answers an item offers, fixed when it was queued (§3)."""
    if kind_of(item).shape == MESSAGE:
        return list(MESSAGE_ANSWERS)
    return list(item["payload"]["answers"])


def answer_index(item: Dict[str, Any], action: str) -> Optional[int]:
    """The position an `a<n>` action names among the item's answers, or None when the
    action is not one of them."""
    if not action.startswith("a") or not action[1:].isdigit():
        return None
    index = int(action[1:]) - 1
    return index if 0 <= index < len(answers(item)) else None


def tell(text: str) -> Optional[int]:
    """Queues the operator's message (§5.1). Its subject is the instant it was queued, so
    the same words told twice are two messages."""
    return queue(MESSAGE_KIND.name, queue_stamp(clock.now()), {"text": text})


def is_hidden(item: Dict[str, Any], now: datetime) -> bool:
    """Whether an item's ready time is still ahead (§13.2)."""
    return item["ready_at"] > queue_stamp(now)


def was_put_off(item: Dict[str, Any]) -> bool:
    """Whether a later choice moved the item's ready time: it then comes back under "You
    asked me to come back to this" (§13.3)."""
    return item["ready_at"] != item["queued_at"]


def morning_of(now: datetime) -> datetime:
    """The athlete's morning time on `now`'s day."""
    return heads_up.at_time(now, settings.morning_time())


def is_out(item: Dict[str, Any], now: datetime) -> bool:
    """Whether a waiting item was sent and not tapped since. At the athlete's morning time
    nothing counts as out any more (§13.2, rules 3 and 5)."""
    morning = morning_of(now)
    if now < morning:
        morning -= timedelta(days=1)
    return bool(item["sent_at"]) and item["sent_at"] >= queue_stamp(morning)


def anything_out() -> bool:
    """Whether an item is out, a stand-alone one included: the line waits for it (§13.2)."""
    now = clock.now()
    return any(is_out(item, now) for item in runtime.db.waiting_queue_items())


def settle_if_stale(item: Dict[str, Any]) -> bool:
    """Closes an item its kind no longer finds worth asking. True when it did (§3)."""
    if not kind_of(item).is_stale(item):
        return False
    runtime.db.close_queue_item(item["id"], STALE, clock.now())
    return True


def _ready(now: datetime) -> List[Dict[str, Any]]:
    """The waiting items whose ready time has passed, the earliest first. A stand-alone
    item is in no line (§13.2 rule 2, DESIGN_waiting_proposal.md §3)."""
    return [
        item for item in runtime.db.waiting_queue_items()
        if not is_hidden(item, now) and not kind_of(item).stands_alone
    ]


def line() -> List[Dict[str, Any]]:
    """The line, the next item first. Items no longer worth asking are closed on the way
    and not shown (§13.2 rules 2 and 7)."""
    return [item for item in _ready(clock.now()) if not settle_if_stale(item)]


def run_questions(item: Dict[str, Any]) -> List[Dict[str, Any]]:
    """The questions about what the athlete wrote that the run which queued `item` has
    not asked yet: its bare items that wait and are not out. They follow a tap on a reply
    of that run (§13.2 rule 6)."""
    now = clock.now()
    return [
        other for other in _ready(now)
        if other["queued_at"] == item["queued_at"] and other["id"] != item["id"]
        and kind_of(other).bare and not is_out(other, now) and not settle_if_stale(other)
    ]


def sent(item: Dict[str, Any]) -> None:
    """Records that an item was put in front of the athlete: it is out (§13.2 rule 3)."""
    runtime.db.mark_queue_sent(item["id"], clock.now())


def later_time(action: str, now: datetime) -> Optional[datetime]:
    """The ready time "in 1 hour" or "tomorrow" gives an item; None for any other action.
    Tomorrow is the athlete's morning time on the next day, whatever the hour (§13.2)."""
    if action == QUEUE_LATER_HOUR:
        return now + timedelta(hours=1)
    if action == QUEUE_LATER_DAY:
        return morning_of(now) + timedelta(days=1)
    return None


def act(item: Dict[str, Any], action: str, text: Optional[str] = None) -> Optional[str]:
    """Applies one action to a waiting item and returns the kind's line for an answer (§4).
    An action the item was not queued with writes nothing (§9). An answer its kind could
    not apply puts the item off until the next morning, with the kind's line saying why
    (§13.5, choice 14)."""
    now = clock.now()
    kind = kind_of(item)
    # A question kind without a drop label refuses one (§4).
    if action == DROP and kind.shape == QUESTION and kind.drop_label:
        if kind.on_drop:
            kind.on_drop(item)
        runtime.db.close_queue_item(item["id"], DROPPED, now)
        return None
    ready_at = now if action == QUEUE_LATER_BACK else later_time(action, now)
    if ready_at is not None:
        runtime.db.set_queue_ready(item["id"], ready_at)
        return None
    index = answer_index(item, action)
    if index is None:
        return None
    try:
        line_said = kind.apply(item, index, text)
    except NotApplied as not_applied:
        runtime.db.set_queue_ready(item["id"], later_time(QUEUE_LATER_DAY, now))
        return str(not_applied)
    runtime.db.close_queue_item(item["id"], ANSWERED, now)
    return line_said


def waiting_counts() -> Tuple[int, int]:
    """(questions, messages) waiting and not hidden: what the terminal hint counts (§5.2).
    A stand-alone item is not counted (DESIGN_waiting_proposal.md §3)."""
    now = clock.now()
    questions = messages = 0
    for item in runtime.db.waiting_queue_items():
        if is_hidden(item, now) or kind_of(item).stands_alone:
            continue
        if kind_of(item).shape == MESSAGE:
            messages += 1
        else:
            questions += 1
    return questions, messages


def next_due() -> bool:
    """Whether a wake of the bot's scheduler sends from the line: between the athlete's
    morning time and the evening, with an item ready and none out. It reads the rows and
    runs no kind's check, so no command starts unless something can be sent (§13.2 rule 4,
    §13.6)."""
    now = clock.now()
    if not morning_of(now) <= now < heads_up.at_time(now, heads_up.EVENING):
        return False
    return bool(_ready(now)) and not anything_out()
