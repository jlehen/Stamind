"""`queue`: the questions and messages waiting for the athlete (DESIGN_athlete_queue.md §5),
and `bot queue`, the hidden command a tap on one of them runs (§6.2).

`trainmate/athlete_queue.py` holds the kinds, the walk and the actions; this file shows
them. On a terminal a walk asks through the blocking chooser, one item at a time. In chat
nothing waits: each item goes out as a message of its own, and its buttons run `bot queue`.
"""
import argparse
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional, Tuple

from trainmate import athlete_queue, clock, runtime
from trainmate.athlete_queue import ANSWERED, DROP, DROPPED, MESSAGE, SKIP, STALE
from trainmate.cli.selectors import add_selector_args
from trainmate.cli.windows import has_selector, resolve_window
from trainmate.prompt import Choice
from trainmate.sentinels import emit_queue_item, is_json_frontend
from trainmate.athlete_queue import (
    QUEUE_LATER_BACK, QUEUE_LATER_CHOICES, QUEUE_LATER_DAY, QUEUE_LATER_HOUR, QUEUE_NOT_NOW,
)
from trainmate.text import bold, capitalized, cmd, cyan, gray, red, wrap_text
from trainmate.output import notice
from trainmate.clock import fmt_span, fmt_timestamp

QUEUE_DONE_LINE = "That's all for now — thanks!"
QUEUE_SETTLED_LINE = "Already settled — thanks!"
NOTHING_WAITING_LINE = "Nothing is waiting."
NOT_NOW_LABEL = "🕐 Not now"

# A walk of one, a reminder or `queue answer <id>` in chat, carries its start with this
# mark, and acting on its item ends there (§4).
WALK_OF_ONE = "r"


def since_token(since: datetime, single: bool = False) -> str:
    """A walk's start as its buttons carry it: epoch seconds, marked for a walk of one."""
    return (WALK_OF_ONE if single else "") + str(int(since.timestamp()))


def parse_since(token: str) -> Tuple[datetime, bool]:
    """(the walk's start, whether it is a walk of one) from a button's `--since`."""
    single = token.startswith(WALK_OF_ONE)
    digits = token[1:] if single else token
    if not digits.isdigit():
        raise ValueError(f"'{token}' is not the start of a walk")
    return datetime.fromtimestamp(int(digits), timezone.utc), single


def short_when(moment: datetime, now: datetime) -> str:
    """'22:12' today and 'Thu 07:58' on another day: when a put-off item comes back."""
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
    """The whole queue: the waiting items in order, then the hidden ones with the time they
    come back (§5.1)."""
    print(bold(cyan("=== QUEUE ===")))
    print()
    if not items:
        print(NOTHING_WAITING_LINE)
        return
    waiting = [item for item in items if not athlete_queue.is_hidden(item, now)]
    hidden = sorted(
        (item for item in items if athlete_queue.is_hidden(item, now)),
        key=lambda item: item["remind_at"],
    )
    id_width = max(len(f"#{item['id']}") for item in items)
    for item in waiting + hidden:
        line = _list_row(item, id_width, item["queued_at"])
        if athlete_queue.is_hidden(item, now):
            back = datetime.fromisoformat(item["remind_at"])
            line += gray(f"  · hidden until {short_when(back, now)}")
        print(line)
    summary = f"{len(waiting)} waiting" + (f", {len(hidden)} hidden" if hidden else "") + "."
    if waiting:
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


def queue_buttons(item: Dict[str, Any], skip: bool) -> List[dict]:
    """An item's chat buttons: its answers, its drop when its kind has one, skip when
    `skip`, and "Not now", which the bot turns into the three later choices (§6.2, §6.4)."""
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
    if skip:
        buttons.append({"label": "⏭ Skip", "action": SKIP})
    buttons.append({"label": NOT_NOW_LABEL, "action": QUEUE_NOT_NOW})
    return buttons


def queue_chat_message(item: Dict[str, Any], left: Optional[int]) -> Tuple[str, List[dict]]:
    """One item as the expert's chat message, skip included (§6.4). `left` counts the walk
    from this item on, and None marks a reminder (§6.5)."""
    text = athlete_queue.wording(item)
    if left is None:
        return f"⏰ You asked me to come back to #{item['id']}:\n{text}", queue_buttons(
            item, skip=True
        )
    shape = athlete_queue.kind_of(item).shape
    emoji = "📬" if shape == MESSAGE else "🙋"
    head = f"{emoji} {shape.capitalize()} #{item['id']} ({left} left)"
    return f"{head}\n{text}", queue_buttons(item, skip=True)


def print_queue_acted(item: Dict[str, Any], action: str, line: Optional[str]) -> None:
    """What one action did, in the expert's words (§5.1). `item` is the row after it."""
    if line:
        print(wrap_text(line))
    elif action == DROP and item["outcome"] == athlete_queue.DROPPED:
        print(f"#{item['id']} dropped — it won't be asked again.")
    elif action == QUEUE_LATER_BACK:
        print(f"#{item['id']} moved behind the others.")
    elif action in (QUEUE_LATER_HOUR, QUEUE_LATER_DAY) and item["remind_at"]:
        back = datetime.fromisoformat(item["remind_at"])
        print(f"#{item['id']} comes back at {short_when(back, clock.now())}.")


def send_item(item: Dict[str, Any], since: str, left: Optional[int]) -> None:
    """Sends one item to chat as a message of its own (§6.2). On a terminal it prints the
    hint of §5.2 in its place, so a raw sentinel never reaches one."""
    if not is_json_frontend():
        runtime.render.queue_hint(*athlete_queue.waiting_counts())
        return
    athlete_queue.shown(item)
    text, buttons = runtime.render.queue_message(item, left)
    emit_queue_item(item["id"], text, buttons, since)


def send_walk_step(since: datetime, after: Optional[Dict[str, Any]] = None) -> bool:
    """Sends the next item of the walk that started at `since`, or the closing line once a
    walk that has shown something runs out; a walk that finds nothing sends nothing (§4).
    True when an item went out."""
    items = athlete_queue.walk(since, after)
    if items:
        send_item(items[0], since_token(since), len(items))
        return True
    if after is not None:
        print(QUEUE_DONE_LINE)
    return False


def terminal_choices(item: Dict[str, Any], since: datetime) -> List[Choice]:
    """The chooser's options for one item; the later ones name the time they mean (§5.1)."""
    now = clock.now()
    kind = athlete_queue.kind_of(item)
    choices = [
        Choice(f"a{number}", answer["label"])
        for number, answer in enumerate(athlete_queue.answers(item), 1)
    ]
    if kind.shape == MESSAGE:
        choices.append(Choice(SKIP, "tell me again next time"))
        lead = "remind me"
    else:
        dropped = athlete_queue.drop_label(item)
        if dropped:
            choices.append(Choice(DROP, f"{dropped} — drop, never asked again"))
        choices.append(Choice(SKIP, "skip — first in line next time"))
        lead = "later —"
    for code, words, _emoji in QUEUE_LATER_CHOICES:
        when = athlete_queue.later_time(code, now, since)
        suffix = f" ({short_when(when, now)})" if when else ""
        choices.append(Choice(code, f"{lead} {words}{suffix}"))
    return choices


def _apply(item: Dict[str, Any], action: str, since: datetime) -> None:
    """Acts on a waiting item, asking for the text first when the answer is typed (§5.1,
    §6.3). An empty text leaves the item as it was."""
    text = None
    index = athlete_queue.answer_index(item, action)
    ask = athlete_queue.answers(item)[index].get("ask") if index is not None else None
    if ask:
        text = runtime.prompt.ask_text(ask).strip()
        if not text:
            return
    line = athlete_queue.act(item, action, since, text)
    runtime.render.queue_acted(runtime.db.get_queue_item(item["id"]), action, line)


def _ask_on_terminal(item: Dict[str, Any], since: datetime, position: Optional[str]) -> None:
    """Shows one item with the blocking chooser and applies the choice (§5.1)."""
    athlete_queue.shown(item)
    shape = athlete_queue.kind_of(item).shape.capitalize()
    lead = f"{shape} {position}" if position else shape
    print()
    print(bold(f"{lead} · #{item['id']} · queued {fmt_timestamp(item['queued_at'])}"))
    action = runtime.prompt.choose(
        wrap_text(athlete_queue.wording(item)), terminal_choices(item, since), default=SKIP,
    )
    _apply(item, action, since)


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
    """Goes through the waiting items with the chooser, or item ID alone (§5.1). In chat it
    sends the first item with its buttons instead of waiting on a chooser."""
    since = clock.command_start()
    if args.id is not None:
        _answer_one(args.id, since)
        return
    if is_json_frontend():
        if not send_walk_step(since):
            print(NOTHING_WAITING_LINE)
        return
    shown = 0
    after = None
    while True:
        items = athlete_queue.walk(since, after)
        if not items:
            break
        shown += 1
        _ask_on_terminal(items[0], since, f"{shown} of {shown + len(items) - 1}")
        after = items[0]
    if not shown:
        print(NOTHING_WAITING_LINE)
        return
    print()
    print(QUEUE_DONE_LINE)


def _answer_one(item_id: int, since: datetime) -> None:
    """`queue answer <id>`: that item alone, whatever its place, and nothing after it."""
    item = runtime.db.get_queue_item(item_id)
    if item is None:
        notice(f"Nothing in the queue has id #{item_id} — " + cmd("queue") + " lists them.",
               red)
        return
    if item["closed_at"] or athlete_queue.settle_if_stale(item):
        print(QUEUE_SETTLED_LINE)
        return
    if is_json_frontend():
        send_item(item, since_token(since, single=True), 1)
        return
    _ask_on_terminal(item, since, None)


def run_queue_tell(args: argparse.Namespace) -> None:
    """Leaves the athlete a message (§5.1)."""
    text = " ".join(args.text).strip()
    if not text:
        notice("Write the message after " + cmd("queue tell") + ".", red)
        return
    item_id = athlete_queue.tell(text)
    print(f"Queued #{item_id}. It goes out with the next morning message, or with "
          + cmd("queue answer") + ".")


def run_bot_queue(args: argparse.Namespace) -> None:
    """A tap on a queued item's button, or `--remind` from the bot's scheduler (§6.2,
    §6.5). Spawned by the bot, never typed."""
    if args.remind:
        _send_reminders()
        return
    if args.item_id is None or args.action is None or args.since is None:
        notice("Give an item id, an action and --since, or --remind.", red)
        return
    since, single = parse_since(args.since)
    item = runtime.db.get_queue_item(args.item_id)
    if item is None or item["closed_at"] or athlete_queue.settle_if_stale(item):
        print(QUEUE_SETTLED_LINE)
    else:
        _apply(item, args.action, since)
    if single or item is None:
        return
    send_walk_step(since, after=item)


def _send_reminders() -> None:
    """Sends each item whose reminder time has passed, as a walk of one that starts now
    (§4, §6.5)."""
    if not is_json_frontend():
        runtime.render.queue_hint(*athlete_queue.waiting_counts())
        return
    sent_at = since_token(clock.now(), single=True)
    for item in athlete_queue.due_reminders():
        send_item(item, sent_at, None)


def add_queue_parser(subparsers):
    # queue command & subparsers — what waits for the athlete (DESIGN_athlete_queue.md §5).
    queue_parser = subparsers.add_parser(
        "queue",
        help="List, answer or leave the questions and messages waiting for the athlete",
        description=(
            "Questions and messages TrainMate holds until the athlete is there to answer. "
            "In Telegram the morning message sends them; here 'queue answer' goes through "
            "them, and 'queue tell' leaves the athlete a message."
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
            "or put it off: in 1 hour, in 1 day, or after the others. Enter skips, and "
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
            "Queue a message for the athlete. It goes out with the next morning message "
            "in Telegram, or with 'queue answer'."
        ),
    )
    q_tell.add_argument("text", metavar="TEXT", nargs="+", help="The message")
    q_tell.set_defaults(func=run_queue_tell)
    return queue_parser
