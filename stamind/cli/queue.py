"""How the queue's items are shown and sent (DESIGN_athlete_queue.md §5, §6.2, §13.2).

`stamind/athlete_queue.py` holds the kinds, the line and the actions; this file shows them:
the terminal's lists, and an item as a chat message with its buttons, sent one at a time.
Every command that queues a question sends it from here. The `queue` and `bot queue`
commands are in `cli/queue_commands.py`.
"""
from datetime import datetime
from typing import Any, Dict, List, Optional, Sequence, Tuple

from stamind import athlete_queue, clock, runtime
from stamind.athlete_queue import (
    ANSWERED, DROP, DROPPED, MESSAGE, QUEUE_LATER_BACK, QUEUE_NOT_NOW, STALE,
)
from stamind.db.queue import queue_stamp
from stamind.page_files import sync as page_files
from stamind.sentinels import emit_queue_item, is_json_frontend
from stamind.text import bold, capitalized, cmd, cyan, gray, wrap_text
from stamind.output import notice
from stamind.clock import fmt_span, fmt_timestamp

QUEUE_DONE_LINE = "That's all for now — thanks!"
QUEUE_SETTLED_LINE = "Already settled — thanks!"
QUEUE_BACK_LINE = "⏰ Back to this one:"
NOTHING_WAITING_LINE = "Nothing is waiting."
NOT_NOW_LABEL = "🕐 Not now"


def short_when(moment: datetime, now: datetime) -> str:
    """'22:12' today and 'Thu 08:00' on another day: when a put-off item is ready again."""
    local = clock.to_local(moment)
    if local.date() == clock.to_local(now).date():
        return local.strftime("%H:%M")
    return local.strftime("%a %H:%M")


def queue_hint_lines(questions: int, messages: int) -> List[str]:
    """The two lines `status` and `workout adapt` print while something waits (§5.2)."""
    total = questions + messages
    if not total:
        return []
    counts = [
        f"{count} {noun}{'s' if count != 1 else ''}"
        for count, noun in ((questions, "question"), (messages, "message")) if count
    ]
    return [
        f"{' and '.join(counts)} {'is' if total == 1 else 'are'} waiting for you.",
        f"Go through {'it' if total == 1 else 'them'} with " + cmd("queue answer") + ".",
    ]


def print_queue_list(items: List[Dict[str, Any]], now: datetime) -> None:
    """The whole queue: the waiting items in order, then the hidden ones, whose ready time
    is still ahead, with that time (§5.1, §13.4)."""
    print(bold(cyan("=== QUEUE ===")))
    print()
    if not items:
        print(NOTHING_WAITING_LINE)
        return
    waiting = [item for item in items if not athlete_queue.is_hidden(item, now)]
    hidden = [item for item in items if athlete_queue.is_hidden(item, now)]
    id_width = max(len(f"#{item['id']}") for item in items)
    for item in waiting + hidden:
        line = _list_row(item, id_width, item["queued_at"])
        if athlete_queue.is_hidden(item, now):
            back = datetime.fromisoformat(item["ready_at"])
            line += gray(f"  · hidden until {short_when(back, now)}")
        print(line)
    summary = f"{len(waiting)} waiting" + (f", {len(hidden)} hidden" if hidden else "") + "."
    # A stand-alone item is in no line, so it is answered by its id.
    if any(not athlete_queue.kind_of(item).stands_alone for item in waiting):
        summary += (" Go through them with " + cmd("queue answer") + ", or one with "
                    + cmd("queue answer <id>") + ".")
    else:
        summary += " Answer one now with " + cmd("queue answer <id>") + "."
    print()
    print(wrap_text(summary))


def print_closed_queue_list(items: List[Dict[str, Any]], start: str, end: str) -> None:
    """The items that closed from `start` to `end`, in the order they closed, each with its
    outcome (§5.1)."""
    print(bold(cyan(f"=== QUEUE · CLOSED {fmt_span(start, end, sep=' .. ')} ===")))
    print()
    if not items:
        print("Nothing closed on those days.")
        return
    id_width = max(len(f"#{item['id']}") for item in items)
    for item in items:
        print(_list_row(item, id_width, item["closed_at"]) + gray(f"  · {item['outcome']}"))
    outcomes = [item["outcome"] for item in items]
    counts = ", ".join(
        f"{outcomes.count(outcome)} {outcome}"
        for outcome in (ANSWERED, DROPPED, STALE) if outcome in outcomes
    )
    print()
    print(f"{len(items)} closed: {counts}.")


def _list_row(item: Dict[str, Any], id_width: int, stamp: str) -> str:
    """One item as `queue list` shows it: its id, its shape, a time and its first line."""
    number = f"#{item['id']}".ljust(id_width)
    shape = athlete_queue.kind_of(item).shape.ljust(len(athlete_queue.QUESTION))
    text = (athlete_queue.wording(item).splitlines() or [""])[0]
    return f"  {number}  {shape}  {fmt_timestamp(stamp)}  {text}"


def _button_label(text: str) -> str:
    """An answer as it reads on a chat button."""
    return capitalized(text)


def queue_buttons(item: Dict[str, Any]) -> List[dict]:
    """An item's chat buttons: its answers, its drop when its kind has one, and "Not now",
    which the bot turns into the two later choices (§6.2, §6.4). A stand-alone item has
    no "Not now" (DESIGN_waiting_proposal.md §3)."""
    kind = athlete_queue.kind_of(item)
    buttons = [
        {"label": _button_label(answer["label"]), "action": f"a{number}"}
        for number, answer in enumerate(athlete_queue.answers(item), 1)
    ]
    if kind.shape == MESSAGE:
        buttons[0]["label"] = "👍 " + buttons[0]["label"]
    else:
        dropped = athlete_queue.drop_label(item)
        if dropped:
            buttons.append({"label": _button_label(dropped), "action": DROP})
    if not (kind.stands_alone or kind.bare):
        buttons.append({"label": NOT_NOW_LABEL, "action": QUEUE_NOT_NOW})
    return buttons


def queue_chat_message(item: Dict[str, Any], left: int) -> Tuple[str, List[dict]]:
    """One item as a chat message, in the companion's words and without skip (§6.4). `left`
    counts the line from this item on. An item whose time was moved says it is back,
    and not who moved it (§13.3, §13.5)."""
    text = athlete_queue.wording(item, companion=True)
    buttons = queue_buttons(item)
    if athlete_queue.kind_of(item).stands_alone:
        return text, buttons
    if athlete_queue.was_put_off(item):
        return f"{QUEUE_BACK_LINE}\n{text}", buttons
    if athlete_queue.kind_of(item).shape == MESSAGE:
        return f"📬 {text}", buttons
    if athlete_queue.kind_of(item).bare:
        return text, buttons
    return f"🙋 Quick question ({left} left)\n{text}", buttons


def print_queue_acted(item: Dict[str, Any], action: str, line: Optional[str]) -> None:
    """What one action did, in the expert's words (§5.1). `item` is the row after it."""
    if line:
        print(wrap_text(line))
    elif action == DROP and item["outcome"] == athlete_queue.DROPPED:
        print(f"#{item['id']} dropped — it won't be asked again.")
    elif action == QUEUE_LATER_BACK:
        print(f"#{item['id']} moved behind the others.")
    elif athlete_queue.later_time(action, clock.now()):
        back = datetime.fromisoformat(item["ready_at"])
        print(f"#{item['id']} comes back at {short_when(back, clock.now())}.")


def send_item(item: Dict[str, Any], left: int) -> None:
    """Sends one item to chat as a message of its own and records the send (§6.2, §13.2).
    On a terminal it prints the hint of §5.2 in its place, so a raw sentinel never reaches
    one."""
    if not is_json_frontend():
        runtime.render.queue_hint(*athlete_queue.waiting_counts())
        return
    text, buttons = queue_chat_message(item, left)
    emit_queue_item(item["id"], text, buttons)
    athlete_queue.sent(item)


def send_alone(item: Dict[str, Any], offer: Sequence[dict] = ()) -> None:
    """Sends a stand-alone item and records the send: its wording as ordinary text, then a
    message of its own that asks and carries the answers (DESIGN_waiting_proposal.md §3).
    A proposal with a page is one message instead, its short text above the question and
    "Tell me more" under its answers (DESIGN_short_messages.md §3, §5). `offer` is the
    morning message's buttons, drawn under the answers (§5). On a terminal the text is
    followed by the command that answers it."""
    if not is_json_frontend():
        print(athlete_queue.wording(item))
        notice(f"Saved as #{item['id']}. Answer it with "
               + cmd(f"queue answer {item['id']}") + ".")
        return
    page = page_files.page_button(runtime.db, item)
    if page is None:
        print(athlete_queue.wording(item))
    text, buttons = queue_chat_message(item, 1)
    emit_queue_item(item["id"], text, buttons, offer=offer, page=page)
    athlete_queue.sent(item)


def settled_line(item: Optional[Dict[str, Any]]) -> str:
    """What a tap on a closed item is told. An item answered or dropped is settled; only
    one its check closed gets its kind's own line. The check that has just closed it left
    the row `item` was read from unmarked (§14.3)."""
    if item is None or item["outcome"] in (ANSWERED, DROPPED):
        return QUEUE_SETTLED_LINE
    return athlete_queue.kind_of(item).closed_line or QUEUE_SETTLED_LINE


def send_next(after: Optional[Dict[str, Any]] = None) -> bool:
    """The one step that sends from the line: if nothing is out, the first item of the line
    goes out (§13.2 rules 3 and 4). After a tap on `after`, a line that has run out gets the
    closing line, unless `after` is a reply to what the athlete wrote. True when an item
    went out."""
    if athlete_queue.anything_out():
        return False
    items = athlete_queue.line()
    if items:
        send_item(items[0], len(items))
        return True
    if after is None:
        return False
    kind = athlete_queue.kind_of(after)
    if not (kind.bare or kind.stands_alone):
        print(QUEUE_DONE_LINE)
    return False


def send_own_questions(queued_at: Optional[str] = None) -> bool:
    """Sends the first question a run queued and has not asked, whatever else is out: a
    reply does not wait in the line. The run is this command's unless `queued_at` names
    another. Nothing goes out while that run has an item out, and the next goes out when it
    is answered (§13.2 rules 3 and 6, DESIGN_waiting_proposal.md §6.3). True when that run
    has a question out."""
    stamp = queued_at or queue_stamp(clock.command_start())
    now = clock.now()
    if any(item["queued_at"] == stamp and athlete_queue.is_out(item, now)
           for item in runtime.db.waiting_queue_items()):
        return True
    items = athlete_queue.run_questions(stamp)
    if not items:
        return False
    send_item(items[0], len(items))
    return True
