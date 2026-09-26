"""What the bot does without being asked, and when.

The top half is the arithmetic: how long to sleep before the next wake, whether the
nightly `data reflect` may start, and the wake itself — reminders that are due, then the
changes to the athlete's week, then the morning push (DESIGN_bot_simple_frontend.md §4.3,
DESIGN_athlete_queue.md §6.5, DESIGN_learning_doubt_nudge.md §3.1). It takes the callbacks
that run a command as arguments, so it decides everything and touches nothing.

The bottom half is `SchedulerMixin`, which is what `ChatBot` passes in: the push chat, one
wake after another, and the nightly reflect as a process of its own. `_tell_changes_first`
is there too — not a wake, but the same rule arriving by the other door, when the athlete
writes or taps before the scheduler got to it (DESIGN_change_heads_up.md §4).
"""
import asyncio
import datetime
import os
import shlex
import sys
from typing import Awaitable, Callable, Dict, List, Tuple

from stamind import athlete_queue, heads_up, journal, settings
from stamind.chat import runner
from stamind.clock import now as athlete_now, reset_cache as forget_timezone
from stamind.text import strip_ansi


def next_push_delay(
    now: "datetime.datetime", morning: str = "08:00", deadline: str = "15:00"
) -> float:
    """Seconds until `bot morning` should next run: 0 inside today's
    [morning, deadline] window, else the wait to the window's next opening
    (DESIGN_bot_simple_frontend.md §4.3). Unparseable times fall back to the
    defaults; a deadline before the send time means no catch-up window."""
    def _parse(raw: str, fallback: Tuple[int, int]) -> Tuple[int, int]:
        try:
            hours, minutes = settings.parse_hhmm(raw).split(":")
        except ValueError:
            return fallback
        return int(hours), int(minutes)

    send_h, send_m = _parse(morning, (8, 0))
    dead_h, dead_m = _parse(deadline, (15, 0))
    start = now.replace(hour=send_h, minute=send_m, second=0, microsecond=0)
    end = now.replace(hour=dead_h, minute=dead_m, second=0, microsecond=0)
    if end < start:
        end = start
    if now < start:
        return (start - now).total_seconds()
    if now <= end:
        return 0.0
    return (start + datetime.timedelta(days=1) - now).total_seconds()


# The nightly reflect reads the week that ended on Sunday from the night into Wednesday on,
# once late syncs and weekend edits have landed (DESIGN_learning_doubt_nudge.md §3.1).
REFLECT_FROM_WEEKDAY = 2  # Wednesday
REFLECT_FROM_HOUR = 3


def reflect_due(now: "datetime.datetime") -> bool:
    """Whether the nightly `data reflect` may start: Wednesday to Sunday, from 03:00 on the
    athlete's clock (DESIGN_learning_doubt_nudge.md §3.1)."""
    return now.weekday() >= REFLECT_FROM_WEEKDAY and now.hour >= REFLECT_FROM_HOUR


async def scheduler_wake(
    last_run: Dict[str, str], simple: bool, busy: Callable[[], bool],
    run: Callable[[List[str], bool], Awaitable[None]], reflect: Callable[[], None],
) -> float:
    """One wake of the bot's scheduler. `last_run` holds the day the push and the nightly
    reflect last started, and the return is how long to sleep before the next wake: at most
    5 minutes, so a laptop suspend (which stalls the monotonic clock asyncio sleeps on) can't
    oversleep the window.

    Reminders that are due go first, and `run` waits for them: a push due on the same wake
    would otherwise find the chat busy. They go out whatever the persona and whether or not
    the push is on (DESIGN_athlete_queue.md §6.5). The changes to the athlete's week that
    are due go next, waited for too, so they come before the push; the config file's
    persona decides, and the `push` switch does not (DESIGN_change_heads_up.md §4). In
    companion mode `reflect` starts `data reflect --auto` outside the chat once a day, and
    nothing waits for it (DESIGN_learning_doubt_nudge.md §3.1). The push fires inside the
    [morning_time, deadline] window once per bot-day (DESIGN_bot_simple_frontend.md §4.3)."""
    # The athlete's wall clock, not the machine's: morning-time/morning-deadline are the
    # hours they wake up in (DESIGN_user_timezone.md §2). Every knob here is re-read each
    # wake — `settings set` runs in a CLI subprocess, so this long-lived process would
    # otherwise hold its first answer until a restart (DESIGN_settings.md §5).
    forget_timezone()
    if not busy() and athlete_queue.reminders_due():
        await run(["bot", "queue", "--remind"], True)
    if not busy() and heads_up.changes_due():
        await run(["bot", "changes"], True)
    now = athlete_now()
    today = now.date().isoformat()
    if simple and reflect_due(now) and last_run.get("reflect") != today:
        last_run["reflect"] = today
        reflect()
    delay = next_push_delay(now, settings.morning_time(), settings.morning_deadline())
    pushed = last_run.get("push") == today
    if delay > 0 or not simple or not settings.push_enabled() or pushed:
        return min(max(delay, 60), 300)
    if busy():
        # §4.3: never collide with an in-flight command — retry shortly.
        return 180
    await run(["bot", "morning"], False)
    last_run["push"] = today
    return 0


class SchedulerMixin:
    """`ChatBot`'s half that drives the wakes above, and the changes told out of turn."""

    async def _run_scheduled(self, argv: List[str], wait: bool) -> None:
        """Starts a scheduler-run command in the push chat; `wait` holds the wake until it
        has finished (DESIGN_athlete_queue.md §6.5)."""
        self._log(self.push_chat_id, "**", shlex.join(argv))
        session = await self._start_command(
            self.push_chat_id, argv, quiet=True, source="push"
        )
        if wait:
            await session.task

    async def _tell_changes_first(self, chat_id: int) -> None:
        """Sends the changes to the athlete's week not told yet, before acting on their own
        tap or message, whatever the hour and however young the change
        (DESIGN_change_heads_up.md §4)."""
        if chat_id != self.push_chat_id or self.sessions.get(chat_id) is not None:
            return
        if not heads_up.waiting():
            return
        await self._run_scheduled(["bot", "changes"], True)

    async def _reflect_outside_chat(self) -> None:
        """`data reflect --auto` as a process of its own, like the router: nothing is posted,
        the chat is not busy, and its output goes to the journal
        (DESIGN_learning_doubt_nudge.md §3.1)."""
        argv = ["data", "reflect", "--auto"]
        self._log(self.push_chat_id, "**", shlex.join(argv))
        env = runner.cli_env(None, source="push")
        env.pop("STAMIND_FRONTEND")  # a terminal report for the journal, no chat sentinels
        try:
            proc = await asyncio.create_subprocess_exec(
                sys.executable, "-u", runner.CLI_PATH, *argv,
                stdin=asyncio.subprocess.DEVNULL,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.STDOUT,
                env=env,
                cwd=os.path.dirname(runner.CLI_PATH),
            )
            out, _ = await proc.communicate()
        except Exception as exc:
            journal.record("bot.reflect", f"did not run: {exc}", lvl="warn")
            return
        journal.record(
            "bot.reflect", strip_ansi(out.decode(errors="replace")).strip(),
            exit_code=proc.returncode,
        )

    def _start_reflect(self) -> None:
        task = asyncio.create_task(self._reflect_outside_chat())
        self.reflect_tasks.add(task)
        task.add_done_callback(self.reflect_tasks.discard)

    async def _push_loop(self) -> None:
        """One `scheduler_wake` after another (§4.3). Real idempotency lives in the
        database marker `bot morning` checks; `last_run` only avoids re-spawning the
        subprocess every tick within one bot lifetime."""
        last_run: Dict[str, str] = {}
        while True:
            try:
                pause = await scheduler_wake(
                    last_run, self.simple_ui,
                    lambda: self.sessions.get(self.push_chat_id) is not None,
                    self._run_scheduled, self._start_reflect,
                )
            except Exception as exc:
                # One wake's failure never ends the loop: the push is the one thing that
                # runs when nobody is looking (DESIGN_telegram_send_retry.md §2).
                self._log(self.push_chat_id, "!!", f"scheduler wake failed: {exc!r}",
                          lvl="error")
                pause = 60
            if pause:
                await asyncio.sleep(pause)
