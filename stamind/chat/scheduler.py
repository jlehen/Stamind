"""What the bot does without being asked, and when.

The top half is the arithmetic: how long to sleep before the next wake, whether the
nightly `data reflect` and `data backup` may start, and the wake itself — the changes to
the athlete's week, then the morning push, or else the next item of the athlete queue
(DESIGN_bot_simple_frontend.md §4.3, DESIGN_athlete_queue.md §13.2,
DESIGN_learning_doubt_nudge.md §3.1). It takes the callbacks
that run a command as arguments, so it decides everything and touches nothing.

The bottom half is `SchedulerMixin`, which is what `ChatBot` passes in: the push chat, one
wake after another, and the nightly reflect and backup as processes of their own.
`_tell_changes_first` is there too — not a wake, but the same rule arriving by the other
door, when the athlete writes or taps before the scheduler got to it
(DESIGN_change_heads_up.md §4).
"""
import asyncio
import datetime
import os
import shlex
import sys
from typing import Any, Awaitable, Callable, Coroutine, Dict, List, Optional, Tuple

from stamind import athlete_queue, heads_up, journal, runtime, settings
from stamind.chat import runner
from stamind.clock import now as athlete_now, reset_cache as forget_timezone
from stamind.config import config
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


# How long after the athlete's last message or tap a wake still counts them as in the chat.
# A wake comes every five minutes at most, and one that finds the chat busy leaves the queue
# to the next (DESIGN_athlete_queue.md §13.2 rule 4).
ATHLETE_HERE = datetime.timedelta(minutes=10)

# The nightly reflect reads the week that ended on Sunday from the night into Wednesday on,
# once late syncs and weekend edits have landed (DESIGN_learning_doubt_nudge.md §3.1).
REFLECT_FROM_WEEKDAY = 2  # Wednesday
REFLECT_FROM_HOUR = 3
# The nightly `data backup` runs every day from the same hour (README, "Backups").
BACKUP_FROM_HOUR = 3


def reflect_due(now: "datetime.datetime") -> bool:
    """Whether the nightly `data reflect` may start: Wednesday to Sunday, from 03:00 on the
    athlete's clock (DESIGN_learning_doubt_nudge.md §3.1)."""
    return now.weekday() >= REFLECT_FROM_WEEKDAY and now.hour >= REFLECT_FROM_HOUR


def garmin_poll_due(
    now: "datetime.datetime", last_poll: Optional[str], every_minutes: float,
    morning: str, evening: str,
) -> bool:
    """Whether to look for a new activity: between the morning and the evening time, and
    `every_minutes` after the last look. Zero minutes turns it off. An activity seen later
    is the morning push's (ARCHITECTURE.md §15)."""
    if every_minutes <= 0 or not morning <= now.strftime("%H:%M") < evening:
        return False
    if last_poll is None:
        return True
    elapsed = now - datetime.datetime.fromisoformat(last_poll)
    return elapsed >= datetime.timedelta(minutes=every_minutes)


async def scheduler_wake(
    last_run: Dict[str, str], busy: Callable[[], bool],
    run: Callable[[List[str], bool], Awaitable[None]], reflect: Callable[[], None],
    last_input: Optional["datetime.datetime"] = None,
    poll: Callable[[], None] = lambda: None,
    backup: Callable[[], None] = lambda: None,
) -> float:
    """One wake of the bot's scheduler. `last_run` holds when the push, the nightly reflect
    and backup, and the Garmin check last started, and the return is how long to sleep
    before the next wake: at most 5 minutes, so a laptop suspend (which stalls the monotonic
    clock asyncio sleeps on) can't oversleep the window.

    The changes to the athlete's week that are due go first, and `run` waits for them: a
    push due on the same wake would otherwise find the chat busy. The `push` switch does
    not stop them (DESIGN_change_heads_up.md §4). `reflect` starts `data reflect --auto`
    outside the chat once a day, and nothing waits for it (DESIGN_learning_doubt_nudge.md
    §3.1). `poll` starts `bot garmin-check` the same way when `garmin_poll_due` says so,
    and `backup` starts `data backup` once a day from 03:00 when a backup bucket is set. The
    push fires inside the [morning_time, deadline] window once per bot-day, and
    ends by sending from the athlete queue itself (DESIGN_bot_simple_frontend.md §4.3). On
    a wake with no push to run, the next item of the queue goes out when one is ready and
    none is out, whether or not the push is on. Past the evening time that needs
    `last_input`, the athlete's last message or tap, to be recent
    (DESIGN_athlete_queue.md §13.2 rule 4)."""
    # The athlete's wall clock, not the machine's: morning-time/morning-deadline are the
    # hours they wake up in (DESIGN_user_timezone.md §2). Every knob here is re-read each
    # wake — `settings set` runs in a CLI subprocess, so this long-lived process would
    # otherwise hold its first answer until a restart (DESIGN_settings.md §5).
    forget_timezone()
    if not busy() and heads_up.changes_due():
        await run(["bot", "changes"], True)
    now = athlete_now()
    today = now.date().isoformat()
    if reflect_due(now) and last_run.get("reflect") != today:
        last_run["reflect"] = today
        reflect()
    if (config.backup_bucket and now.hour >= BACKUP_FROM_HOUR
            and last_run.get("backup") != today):
        last_run["backup"] = today
        backup()
    if garmin_poll_due(now, last_run.get("poll"), config.garmin_poll_minutes,
                       settings.morning_time(), settings.evening_time()):
        last_run["poll"] = now.isoformat()
        poll()
    delay = next_push_delay(now, settings.morning_time(), settings.morning_deadline())
    pushed = last_run.get("push") == today
    if delay > 0 or not settings.push_enabled() or pushed:
        here = last_input is not None and now - last_input <= ATHLETE_HERE
        if not busy() and athlete_queue.next_due(here):
            await run(["bot", "queue", "--next"], True)
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
        (DESIGN_change_heads_up.md §4). It also notes the moment: the wakes that follow
        may send from the queue at night (DESIGN_athlete_queue.md §13.2 rule 4)."""
        if chat_id != self.push_chat_id:
            return
        self.last_input_at = datetime.datetime.now(datetime.timezone.utc)
        if self._runs(chat_id):
            return
        if not heads_up.waiting():
            return
        await self._run_scheduled(["bot", "changes"], True)

    async def _run_outside_chat(self, argv: List[str]) -> Tuple[int, str]:
        """A command as a process of its own, like the router: nothing is posted and the chat
        is not busy. Returns its exit code and its output, for the journal
        (DESIGN_learning_doubt_nudge.md §3.1). Raises when it could not start."""
        env = runner.cli_env(None, source="push")
        env.pop("STAMIND_FRONTEND")  # a terminal report for the journal, no chat sentinels
        proc = await asyncio.create_subprocess_exec(
            sys.executable, "-u", runner.CLI_PATH, *argv,
            stdin=asyncio.subprocess.DEVNULL,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.STDOUT,
            env=env,
            cwd=os.path.dirname(runner.CLI_PATH),
        )
        out, _ = await proc.communicate()
        return proc.returncode, strip_ansi(out.decode(errors="replace")).strip()

    async def _journalled_outside_chat(self, argv: List[str], ev: str) -> None:
        """A nightly command, `data reflect --auto` or `data backup`, with its output in the
        journal, as a warning when it failed."""
        self._log(self.push_chat_id, "**", shlex.join(argv))
        try:
            code, out = await self._run_outside_chat(argv)
        except Exception as exc:
            journal.record(ev, f"did not run: {exc}", lvl="warn")
            return
        journal.record(ev, out, lvl="warn" if code else "info", exit_code=code)

    async def _garmin_check_outside_chat(self) -> None:
        """`bot garmin-check`, journalled only at the first failure since the last success:
        it runs dozens of times a day, and the run that pulls journals itself
        (ARCHITECTURE.md §15)."""
        try:
            code, out = await self._run_outside_chat(["bot", "garmin-check"])
        except Exception as exc:
            code, out = 1, f"did not run: {exc}"
        failed_before = self.garmin_check_failing
        self.garmin_check_failing = code != 0
        if code != 0 and not failed_before:
            journal.record("bot.garmin_check", out, lvl="warn", exit_code=code)

    def _start_outside_chat(self, work: Coroutine[Any, Any, None]) -> None:
        task = asyncio.create_task(work)
        self.outside_tasks.add(task)
        task.add_done_callback(self.outside_tasks.discard)

    def _start_reflect(self) -> None:
        self._start_outside_chat(
            self._journalled_outside_chat(["data", "reflect", "--auto"], "bot.reflect"))

    def _start_backup(self) -> None:
        self._start_outside_chat(self._journalled_outside_chat(["data", "backup"], "bot.backup"))

    def _start_garmin_check(self) -> None:
        self._start_outside_chat(self._garmin_check_outside_chat())

    async def _push_loop(self) -> None:
        """One `scheduler_wake` after another (§4.3). Real idempotency lives in the
        database marker `bot morning` checks; `last_run` only avoids re-spawning the
        subprocess every tick within one bot lifetime."""
        last_run: Dict[str, str] = {}
        while True:
            try:
                # Busy too while a run outside the chat, such as a terminal's, looks at the
                # week (DESIGN_long_runs_beside_chat.md §3).
                pause = await scheduler_wake(
                    last_run,
                    lambda: bool(self._runs(self.push_chat_id)) or runtime.db.week_busy(),
                    self._run_scheduled, self._start_reflect, self.last_input_at,
                    self._start_garmin_check, self._start_backup,
                )
            except Exception as exc:
                # One wake's failure never ends the loop: the push is the one thing that
                # runs when nobody is looking (DESIGN_telegram_send_retry.md §2).
                self._log(self.push_chat_id, "!!", f"scheduler wake failed: {exc!r}",
                          lvl="error")
                pause = 60
            if pause:
                await asyncio.sleep(pause)
