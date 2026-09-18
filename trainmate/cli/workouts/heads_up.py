"""What the terminal asks and says about the athlete's heads-up (DESIGN_change_heads_up.md).

On a companion instance a `workout generate` or `workout adapt` started in the terminal
changes the athlete's week out of their sight, and its line waits for the bot to send it.
This module holds the question asked before such a run when the previous attempt was never
sent (§5), the notice that says when the line goes out (§8), and `workout notify`, which
asks the bot to send what is waiting at once (§4). `workout generate` and `workout adapt`
share the first two.
"""
import argparse
import textwrap
from contextlib import contextmanager
from datetime import datetime
from typing import Any, Dict, Iterable, Iterator, Optional

from trainmate import clock, heads_up, runtime, settings
from trainmate.config import config
from trainmate.prompt import Choice, athlete_watching
from trainmate.util import (
    bold, cmd, default_wrap_width, green, notice, today_str, wrap_text,
)


def _when(change: Dict[str, Any]) -> str:
    """A change's time as the athlete's clock read it: 'Wed 22:00'."""
    return clock.to_local(datetime.fromisoformat(change["created_at"])).strftime("%a %H:%M")


def _is_waiting(change_id: int) -> bool:
    return any(c["id"] == change_id for c in heads_up.waiting())


def _newest_written() -> int:
    """The id of the newest change that wrote a session, 0 when none has."""
    newest = runtime.db.newest_change_with_sessions()
    return newest["id"] if newest else 0


def _replace_unsent() -> Optional[int]:
    """Asks the §5 question and undoes the newest change on "replace".

    Returns the newest change that wrote a session right after the undo, the mark a later
    change must pass to count as written, or None when nothing was undone."""
    if athlete_watching():
        return None
    newest = runtime.db.newest_change_with_sessions()
    if newest is None or not _is_waiting(newest["id"]):
        return None
    choice = runtime.prompt.choose(
        f"The newest change ({newest['kind']}, {_when(newest)}) has not been sent to the "
        "athlete yet.\nReplace it, or build on it? Replace undoes it now.",
        [Choice("build", "Build on it"), Choice("replace", "Replace it")],
        default="build",
    )
    if choice != "replace":
        return None
    # The bot may have sent it while the question waited (§5).
    if not _is_waiting(newest["id"]):
        notice("It reached the athlete while you answered, so this run builds on it.")
        return None
    runtime.coach_service.workout_rollback(change_id=newest["id"])
    print(green("Undid it: this run starts from the week the athlete knows."))
    return _newest_written()


@contextmanager
def replacing_unsent(skip: bool) -> Iterator[bool]:
    """Around a terminal `workout generate` or `workout adapt`: offers to undo the newest
    change when the athlete was never told about it, and yields whether it was undone (§5).

    `skip` is the run's -y/--auto/--force, which asks nothing and builds on top. The undo
    comes before the week planner is called, so a run that then writes nothing — cancelled,
    declined or failed — leaves it undone, and says so on the way out."""
    written_upto = None if skip else _replace_unsent()
    try:
        yield written_upto is not None
    finally:
        if written_upto is not None and _newest_written() <= written_upto:
            notice(
                "The earlier attempt stays undone. " + cmd("workout rollback")
                + " brings it back, and its message with it."
            )


def revision_dates(proposal) -> set:
    """The days a `workout adapt` proposal writes: its sessions, the days they move out of,
    and the sessions it drops."""
    dates = {w["date"] for w in proposal.workouts}
    dates |= {pair.original["date"] for pair in proposal.pairs if pair.original}
    dates |= {removed["date"] for removed in proposal.removals}
    return dates


def generate_dates(proposal) -> set:
    """The days a `workout generate` proposal writes: the sessions it does not keep as
    they are, and the slots it ends."""
    dates = {w["date"] for w in proposal.workouts if not w.get("keep")}
    dates |= {day for day, _sport, _reason in proposal.voids}
    return dates


def print_send_notice(dates: Iterable[str]) -> None:
    """Under the line a terminal run writes for the athlete: when it reaches them, by the
    rule the scheduler applies (§8). `dates` are the days the proposal writes.

    A change to today's sessions that would only reach them tomorrow says so first, since
    only `workout notify` gets it to them in time (§4)."""
    if athlete_watching():
        return
    now = clock.now()
    at = heads_up.sends_at(now, settings.morning_time())
    if at.date() == now.date():
        when = f"at {at.strftime('%H:%M')} today"
    else:
        when = f"at {at.strftime('%H:%M')} tomorrow"
    if today_str() in set(dates) and at.date() != now.date():
        notice(
            f"This changes today's session, and the athlete gets this line on Telegram "
            f"only {when}. Run {cmd('workout notify')} to send it now."
        )
        return
    notice(
        f"The athlete gets this line on Telegram {when}. {cmd('workout notify')} "
        "sends it now."
    )


def run_workout_notify(args: argparse.Namespace) -> None:
    """Asks the bot to send the changes waiting to be told on its next wake, whatever the
    hour and however young the change (§4)."""
    if config.telegram_ui != "simple":
        print(
            "This instance is not in companion mode: the athlete runs every change "
            "themselves, so nothing waits to be sent."
        )
        return
    waiting = heads_up.waiting()
    if not waiting:
        print("Nothing is waiting to be sent to the athlete.")
        return
    print(bold("Waiting to be sent to the athlete, oldest first:"))
    width = default_wrap_width() - 4
    for change in waiting:
        print(f"  {_when(change)} ({change['kind']})")
        print(textwrap.indent(wrap_text(heads_up.message(change), width), "    "))
    if not (getattr(args, "yes", False) or runtime.prompt.confirm("Send them now?")):
        print("Nothing sent. They go out at the usual time.")
        return
    # An id rather than a flag, so it cannot outlive the changes it was for (§4).
    runtime.db.set_setting(heads_up.NOTIFY_MARKER, str(waiting[-1]["id"]))
    print(green("The bot sends them within five minutes, once the athlete's chat is free."))
