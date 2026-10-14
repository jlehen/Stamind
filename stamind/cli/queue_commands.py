"""`queue`, the questions and messages waiting for the athlete (DESIGN_athlete_queue.md §5),
and `bot queue`, the hidden command a tap on one of them runs (§6.2).

`stamind/athlete_queue.py` holds the kinds, the line and the actions, and `cli/queue.py`
shows and sends them. This file is the commands. On a terminal `queue answer` asks through
the blocking chooser, one item at a time. In chat nothing waits: one item at a time goes out
as a message of its own, its buttons run `bot queue`, and the tap sends the next (§13.2).

An answer can start a long run, which goes on in the same command once its item is closed
(DESIGN_long_runs_beside_chat.md §6). The commands it runs import the queue, so the list of
kinds cannot reach them: they are reached from here.
"""
import argparse
from datetime import datetime
from typing import Any, Dict, List, Optional

from stamind import athlete_queue, clock, runtime, settings
from stamind.athlete_queue import (
    ANSWERED, DROP, MESSAGE, QUEUE_LATER_CHOICES, SKIP,
)
from stamind.cli.bot import hand_off
from stamind.cli.common import ensure_recent_data
from stamind.cli.queue import (
    NOTHING_WAITING_LINE, QUEUE_DONE_LINE, send_alone, send_item, send_next, settled_line,
    short_when,
)
from stamind.cli.selectors import add_selector_args
from stamind.cli.windows import has_selector, resolve_window
from stamind.prompt import Choice
from stamind.sentinels import is_json_frontend
from stamind.text import bold, cmd, red, wrap_text
from stamind.output import notice
from stamind.clock import fmt_timestamp
from stamind.cli.workouts import proposal as saved
import stamind.cli.workouts.adapt as _adapt
import stamind.cli.workouts.generate as _generate

STAYS_OPEN_LABEL = "skip — it stays open"


def _hand_off_to_coach(item: Dict[str, Any]) -> None:
    """"Yes" to the hand-off: runs `workout adapt -m` with the athlete's original words, in
    this process. The coach reads what they wrote, which is the whole point of this lane
    (DESIGN_bot_simple_frontend.md §12.3, DESIGN_long_runs_beside_chat.md §5)."""
    _adapt.run_workout_adapt(argparse.Namespace(
        date=None, no_pull=False, force_pull=False, auto=False,
        message=item["payload"]["message"], lookback=None,
    ))


def _plan_them(item: Dict[str, Any]) -> None:
    """"Plan them": the same `workout generate --propose` for the same days, with the question
    answered (DESIGN_long_runs_beside_chat.md §4)."""
    payload = item["payload"]
    ensure_recent_data()
    _generate.propose_weeks(
        (payload["start"], payload["end"]), payload["prefer_macro_id"], payload["fresh"],
        asked=True,
    )


# What the answer that starts a long run goes on to do, by the item's kind (§6 there).
GOES_ON = {
    hand_off.KIND: _hand_off_to_coach,
    saved.REPLACE_SESSIONS: _plan_them,
}


def _closed_day(item: Dict[str, Any]) -> str:
    """The athlete's local day an item closed on, as YYYY-MM-DD."""
    return clock.to_local(datetime.fromisoformat(item["closed_at"])).strftime("%Y-%m-%d")


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
    §6.3). An empty text leaves the item as it was. An answer that starts a long run goes
    on to it once the item is closed (DESIGN_long_runs_beside_chat.md §6)."""
    text = None
    index = athlete_queue.answer_index(item, action)
    ask = athlete_queue.answers(item)[index].get("ask") if index is not None else None
    if ask:
        text = runtime.prompt.ask_text(ask).strip()
        if not text:
            return
    line = athlete_queue.act(item, action, text)
    after = runtime.db.get_queue_item(item["id"])
    runtime.render.queue_acted(after, action, line)
    if after["outcome"] == ANSWERED and athlete_queue.long_run_argv(item, action):
        GOES_ON[item["kind"]](item)


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
        f"{morning} and {settings.evening_time()}, and at {morning} otherwise."
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
