"""`queue`: the questions and messages waiting for the athlete (DESIGN_athlete_queue.md §5),
and `bot queue`, the hidden command a tap on one of them runs (§6.2).

`stamind/athlete_queue.py` holds the kinds, the line and the actions; this file shows
them. On a terminal `queue answer` asks through the blocking chooser, one item at a time. In
chat nothing waits: one item at a time goes out as a message of its own, its buttons run
`bot queue`, and the tap sends the next (§13.2).
"""
import argparse
from datetime import datetime
from typing import Any, Dict, List, Optional, Sequence, Tuple

from stamind import athlete_queue, clock, heads_up, runtime, settings
from stamind.athlete_queue import ANSWERED, DROP, DROPPED, MESSAGE, SKIP, STALE
from stamind.cli.selectors import add_selector_args
from stamind.cli.windows import has_selector, resolve_window
from stamind.prompt import Choice
from stamind.sentinels import emit_queue_item, is_json_frontend
from stamind.athlete_queue import QUEUE_LATER_BACK, QUEUE_LATER_CHOICES, QUEUE_NOT_NOW
from stamind.text import bold, capitalized, cmd, cyan, gray, red, wrap_text
from stamind.output import notice
from stamind.clock import fmt_span, fmt_timestamp

QUEUE_DONE_LINE = "That's all for now — thanks!"
QUEUE_SETTLED_LINE = "Already settled — thanks!"
STAYS_OPEN_LABEL = "skip — it stays open"
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


def _closed_day(item: Dict[str, Any]) -> str:
    """The athlete's local day an item closed on, as YYYY-MM-DD."""
    return clock.to_local(datetime.fromisoformat(item["closed_at"])).strftime("%Y-%m-%d")


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
    counts the line from this item on. An item the athlete put off says so (§13.3)."""
    text = athlete_queue.wording(item, companion=True)
    buttons = queue_buttons(item)
    if athlete_queue.kind_of(item).stands_alone:
        return text, buttons
    if athlete_queue.was_put_off(item):
        return f"⏰ You asked me to come back to this:\n{text}", buttons
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
    `offer` is the morning message's buttons, drawn under the answers (§5). On a terminal
    the text is followed by the command that answers it."""
    print(athlete_queue.wording(item))
    if not is_json_frontend():
        notice(f"Saved as #{item['id']}. Answer it with "
               + cmd(f"queue answer {item['id']}") + ".")
        return
    text, buttons = queue_chat_message(item, 1)
    emit_queue_item(item["id"], text, buttons, offer=offer)
    athlete_queue.sent(item)


def settled_line(item: Optional[Dict[str, Any]]) -> str:
    """What a tap on a closed item is told: its kind's own line when it has one."""
    if item is None:
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


def send_own_questions(items: Sequence[Dict[str, Any]]) -> None:
    """Sends the first of the questions this command just queued, whatever is out: a reply
    does not wait in the line. The next goes out when it is answered (§13.2 rule 6,
    DESIGN_waiting_proposal.md §6.3)."""
    if items:
        send_item(items[0], len(items))


def terminal_choices(item: Dict[str, Any]) -> List[Choice]:
    """The chooser's options for one item; the later ones name the time they mean (§5.1,
    §13.4)."""
    now = clock.now()
    kind = athlete_queue.kind_of(item)
    choices = [
        Choice(f"a{number}", answer["label"])
        for number, answer in enumerate(athlete_queue.answers(item), 1)
    ]
    if kind.stands_alone:
        return choices + [Choice(SKIP, STAYS_OPEN_LABEL)]
    if kind.shape == MESSAGE:
        choices.append(Choice(SKIP, "tell me again next time"))
        lead = "remind me"
    else:
        dropped = athlete_queue.drop_label(item)
        if dropped:
            choices.append(Choice(DROP, f"{dropped} — drop, never asked again"))
        choices.append(Choice(SKIP, "skip — first in line next time"))
        lead = "later —"
    for code, words, _button in QUEUE_LATER_CHOICES:
        when = athlete_queue.later_time(code, now)
        suffix = f" ({short_when(when, now)})" if when else ""
        choices.append(Choice(code, f"{lead} {words}{suffix}"))
    return choices


def _apply(item: Dict[str, Any], action: str) -> None:
    """Acts on a waiting item, asking for the text first when the answer is typed (§5.1,
    §6.3). An empty text leaves the item as it was."""
    text = None
    index = athlete_queue.answer_index(item, action)
    ask = athlete_queue.answers(item)[index].get("ask") if index is not None else None
    if ask:
        text = runtime.prompt.ask_text(ask).strip()
        if not text:
            return
    line = athlete_queue.act(item, action, text)
    runtime.render.queue_acted(runtime.db.get_queue_item(item["id"]), action, line)


def _ask_on_terminal(item: Dict[str, Any], position: Optional[str]) -> None:
    """Shows one item with the blocking chooser and applies the choice (§5.1). Shown here
    counts as sent, so the bot does not send it again the same day (§13.4)."""
    athlete_queue.sent(item)
    shape = athlete_queue.kind_of(item).shape.capitalize()
    lead = f"{shape} {position}" if position else shape
    print()
    print(bold(f"{lead} · #{item['id']} · queued {fmt_timestamp(item['queued_at'])}"))
    action = runtime.prompt.choose(
        wrap_text(athlete_queue.wording(item)), terminal_choices(item), default=SKIP,
    )
    _apply(item, action)


def run_queue_list(args: argparse.Namespace) -> None:
    """Lists the waiting items, and the hidden ones with when they come back; with
    `--closed`, the items that closed on the days `-d` picks (§5.1)."""
    if getattr(args, "closed", False):
        start, end = resolve_window(args)
        items = [
            item for item in runtime.db.closed_queue_items()
            if start <= _closed_day(item) <= end
        ]
        runtime.render.queue_closed_list(items, start, end)
        return
    if has_selector(args):
        notice("-d picks closed items by the day they closed, so it needs --closed.", red)
        return
    runtime.render.queue_list(runtime.db.waiting_queue_items(), clock.now())


def run_queue_answer(args: argparse.Namespace) -> None:
    """Goes through the line with the chooser, each item once, or item ID alone (§5.1,
    §13.4). In chat it sends the first item of the line with its buttons, whatever is out,
    instead of waiting on a chooser."""
    if args.id is not None:
        _answer_one(args.id)
        return
    if is_json_frontend():
        items = athlete_queue.line()
        if not items:
            print(NOTHING_WAITING_LINE)
            return
        send_item(items[0], len(items))
        return
    # "After the others" makes an item ready again at once, so each is asked about once.
    asked = set()
    while True:
        items = [item for item in athlete_queue.line() if item["id"] not in asked]
        if not items:
            break
        asked.add(items[0]["id"])
        _ask_on_terminal(items[0], f"{len(asked)} of {len(asked) + len(items) - 1}")
    if not asked:
        print(NOTHING_WAITING_LINE)
        return
    print()
    print(QUEUE_DONE_LINE)


def _answer_one(item_id: int) -> None:
    """`queue answer <id>`: that item alone, whatever its place."""
    item = runtime.db.get_queue_item(item_id)
    if item is None:
        notice(f"Nothing in the queue has id #{item_id} — " + cmd("queue") + " lists them.",
               red)
        return
    if item["closed_at"] or athlete_queue.settle_if_stale(item):
        print(settled_line(item))
        return
    if is_json_frontend() and athlete_queue.kind_of(item).stands_alone:
        send_alone(item)
        return
    if is_json_frontend():
        send_item(item, 1)
        return
    _ask_on_terminal(item, None)


def run_queue_tell(args: argparse.Namespace) -> None:
    """Leaves the athlete a message (§5.1)."""
    text = " ".join(args.text).strip()
    if not text:
        notice("Write the message after " + cmd("queue tell") + ".", red)
        return
    item_id = athlete_queue.tell(text)
    morning = settings.morning_time()
    print(wrap_text(
        f"Queued #{item_id}. It goes out when its turn comes: within minutes between "
        f"{morning} and {heads_up.EVENING}, and at {morning} otherwise."
    ))


def run_bot_queue(args: argparse.Namespace) -> None:
    """A tap on a queued item's button, or `--next` from the bot's scheduler (§6.2,
    §13.2). Spawned by the bot, never typed."""
    if args.next:
        send_next()
        return
    if args.item_id is None or args.action is None:
        notice("Give an item id and an action, or --next.", red)
        return
    item = runtime.db.get_queue_item(args.item_id)
    if item is None or item["closed_at"] or athlete_queue.settle_if_stale(item):
        print(settled_line(item))
    else:
        _apply(item, args.action)
    if item is None:
        return
    # A reply is followed by the next question of its own run, whatever is out. Any other
    # tap, and the last reply of a run, is followed by the step (§13.2 rule 6).
    kind = athlete_queue.kind_of(item)
    behind = athlete_queue.run_questions(item) if kind.stands_alone or kind.bare else []
    if behind:
        send_item(behind[0], len(behind))
        return
    send_next(after=item)


def add_queue_parser(subparsers):
    # queue command & subparsers — what waits for the athlete (DESIGN_athlete_queue.md §5).
    queue_parser = subparsers.add_parser(
        "queue",
        help="List, answer or leave the questions and messages waiting for the athlete",
        description=(
            "Questions and messages Stamind holds until the athlete is there to answer. "
            "In Telegram the bot sends them one at a time; here 'queue answer' goes "
            "through them, and 'queue tell' leaves the athlete a message."
        ),
    )
    # Read-only at the top level, so a bare `queue` lists (DESIGN_cli_noargs.md §a3).
    queue_parser.set_defaults(func=run_queue_list)
    queue_subparsers = queue_parser.add_subparsers(
        dest="subcommand", help="Queue sub-commands"
    )

    q_list = queue_subparsers.add_parser(
        "list",
        help="List what is waiting, and what is put off until later",
        description=(
            "Every waiting item in queue order, then the items put off until a later "
            "time, with when they come back. Same as a bare 'queue'. With --closed, the "
            "items already closed instead, in the order they closed, each with its "
            "outcome: answered, dropped, or stale (no longer worth asking). -d picks the "
            "days they closed on."
        ),
    )
    q_list.add_argument(
        "--closed", action="store_true",
        help="List the closed items instead, from the last 7 days unless -d picks the days",
    )
    add_selector_args(q_list, direction="backward", default="7d")
    q_list.set_defaults(func=run_queue_list)

    q_answer = queue_subparsers.add_parser(
        "answer",
        help="Go through the waiting items one at a time, or one item by its id",
        description=(
            "Show each waiting item with its answers and the choices to drop it, skip it, "
            "or put it off: in 1 hour, until tomorrow, or after the others. Enter skips, "
            "and "
            "every answer given is written at once. With an ID, show that item alone."
        ),
    )
    q_answer.add_argument(
        "id", metavar="ID", type=int, nargs="?",
        help="The item to answer, as 'queue' lists it; omit to go through them all",
    )
    q_answer.set_defaults(func=run_queue_answer)

    q_tell = queue_subparsers.add_parser(
        "tell",
        help="Leave the athlete a message",
        description=(
            "Queue a message for the athlete. In Telegram it goes out when its turn "
            "comes, within minutes in the daytime; here 'queue answer' shows it."
        ),
    )
    q_tell.add_argument("text", metavar="TEXT", nargs="+", help="The message")
    q_tell.set_defaults(func=run_queue_tell)
    return queue_parser
