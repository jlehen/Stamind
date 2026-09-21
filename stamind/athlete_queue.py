"""The queue of things Stamind wants to tell or ask the athlete (DESIGN_athlete_queue.md).

The list of kinds, the walk and the actions. The queue knows nothing about what an item
asks: each kind brings its wording, its check and what its answers do (§8). `message`, the
operator's note from `tm queue tell`, is the first kind and the smallest one.
"""
from datetime import datetime, timedelta
from typing import Any, Dict, List, Optional, Tuple

from stamind import clock, runtime
from stamind.db.queue import queue_stamp
# Re-exported: what a feature needs lives in queue_kind, so a feature can queue items
# without importing the list of kinds that imports it.
from stamind.text import capitalized
from stamind.queue_kind import (  # noqa: F401
    ANSWERED, DROPPED, MESSAGE, QUESTION, STALE, Kind, NotApplied, queue,
)
from stamind.learning_doubts import LEARNING_KIND
from stamind.strength.questions import SET_NAMES_KIND, SETS_FINAL_KIND

# The action codes a chooser returns and a button carries (§6.2). An answer is `a<n>`, the
# n-th answer stored with the item.
DROP = "d"
SKIP = "s"

# The "later" choices of a queued item: action code, words, and the emoji a chat button
# adds. One definition for the terminal's chooser and the bot's "Not now" row, which the bot
# swaps in from the tap itself (DESIGN_athlete_queue.md §6.4).
QUEUE_LATER_HOUR = "h"
QUEUE_LATER_DAY = "t"
QUEUE_LATER_BACK = "b"
QUEUE_NOT_NOW = "n"
QUEUE_LATER_CHOICES = (
    (QUEUE_LATER_HOUR, "in 1 hour", "⏰"),
    (QUEUE_LATER_DAY, "in 1 day", "⏰"),
    (QUEUE_LATER_BACK, "after the others", "↩️"),
)


def queue_later_label(words: str, emoji: str) -> str:
    """A "later" choice as a chat button: '⏰ In 1 hour'."""
    return f"{emoji} {capitalized(words)}"


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
# learning kind whether a doubted learning still fits (DESIGN_learning_doubt_nudge.md §5).
KINDS: Dict[str, Kind] = {
    kind.name: kind
    for kind in (MESSAGE_KIND, SETS_FINAL_KIND, SET_NAMES_KIND, LEARNING_KIND)
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
    """Whether an item is put off until a time that has not come yet (§4)."""
    return bool(item.get("remind_at")) and item["remind_at"] > queue_stamp(now)


def settle_if_stale(item: Dict[str, Any]) -> bool:
    """Closes an item its kind no longer finds worth asking. True when it did (§3)."""
    if not kind_of(item).is_stale(item):
        return False
    runtime.db.close_queue_item(item["id"], STALE, clock.now())
    return True


def walk(since: datetime, after: Optional[Dict[str, Any]] = None) -> List[Dict[str, Any]]:
    """The items the walk that started at `since` still has to show after `after`, the
    next one first. Stale items met on the way are closed without being shown (§4)."""
    items = runtime.db.queue_walk(since, clock.now(), after)
    while items and settle_if_stale(items[0]):
        items.pop(0)
    return items


def shown(item: Dict[str, Any]) -> None:
    """Records that a walk showed an item: one whose reminder time has passed is not
    reminded as well (§4)."""
    if item.get("remind_at"):
        runtime.db.set_queue_reminder(item["id"], None)


def later_time(action: str, now: datetime, since: datetime) -> Optional[datetime]:
    """When a "later" action brings an item back; None for any other action (§4)."""
    if action == QUEUE_LATER_HOUR:
        return now + timedelta(hours=1)
    if action == QUEUE_LATER_DAY:
        # On the walk's wall clock, so what the push put off comes back ahead of the next push.
        return clock.to_local(since) + timedelta(days=1, minutes=-2)
    return None


def act(
    item: Dict[str, Any], action: str, since: datetime, text: Optional[str] = None
) -> Optional[str]:
    """Applies one action to a waiting item and returns the kind's line for an answer (§4).
    An action the item was not queued with writes nothing (§9), and an answer its kind could
    not apply leaves the item waiting, with the kind's line saying why."""
    now = clock.now()
    kind = kind_of(item)
    # A question kind without a drop label refuses one (§4).
    if action == DROP and kind.shape == QUESTION and kind.drop_label:
        if kind.on_drop:
            kind.on_drop(item)
        runtime.db.close_queue_item(item["id"], DROPPED, now)
        return None
    if action == QUEUE_LATER_BACK:
        runtime.db.requeue_queue_item(item["id"], now)
        return None
    remind_at = later_time(action, now, since)
    if remind_at is not None:
        runtime.db.set_queue_reminder(item["id"], remind_at)
        return None
    index = answer_index(item, action)
    if index is None:
        return None
    try:
        line = kind.apply(item, index, text)
    except NotApplied as not_applied:
        return str(not_applied)
    runtime.db.close_queue_item(item["id"], ANSWERED, now)
    return line


def waiting_counts() -> Tuple[int, int]:
    """(questions, messages) waiting and not hidden: what the terminal hint counts (§5.2)."""
    now = clock.now()
    questions = messages = 0
    for item in runtime.db.waiting_queue_items():
        if is_hidden(item, now):
            continue
        if kind_of(item).shape == MESSAGE:
            messages += 1
        else:
            questions += 1
    return questions, messages


def reminders_due() -> bool:
    """Whether any item's reminder time has passed: the bot's scheduler asks on every wake,
    so no command runs unless one has (§6.5)."""
    return bool(runtime.db.due_queue_items(clock.now()))


def due_reminders() -> List[Dict[str, Any]]:
    """The items to send as reminders now. Stale ones are closed, and the others have their
    reminder time cleared, so each reminder is sent once (§6.5)."""
    items = []
    for item in runtime.db.due_queue_items(clock.now()):
        if settle_if_stale(item):
            continue
        runtime.db.set_queue_reminder(item["id"], None)
        items.append(item)
    return items
