"""What the bot does with a message the athlete sends.

Every text update lands in `on_message`. The allowlist comes first, then the handful of
words the bot answers itself — /cancel, /start, /help, /restart — then the answer to an
open text prompt. Everything past that is a command to run.

Which command depends on the leading slash. A message that starts with `/` is a CLI
command line, and `parse_message_to_argv` turns it into argv. Without the slash a keyboard
label runs its fixed argv, and anything else goes through the intent router: `_simple_route` asks
`sm bot route` what the message means and maps the answer onto either the coach lane,
which carries the athlete's own words, or the capture inbox, which asks before it stores
(DESIGN_bot_simple_frontend.md §5, §12.3).
"""
import html
import os
import shlex
import time
from typing import List, Optional

from stamind import clock
from stamind.chat import runner, telegram_api
from stamind.chat.keyboards import SIMPLE_HELP, SIMPLE_WELCOME, keyboard_action
from stamind.chat.routing import (
    CAPTURE_PROMPT, CAPTURE_RESCUE_ECHO, ROUTER_CAPTURE_INTENTS, ROUTER_ECHO,
    ROUTER_FALLBACK, ROUTER_INTENT_ARGV, ROUTER_MESSAGE_ARGV, parse_message_to_argv,
)
from stamind.cli.render import calendar_page, plan_page
from stamind.config import config
from stamind.sentinels import prompt_answer

# Told to anything arriving while a command is still going, whichever door it came in by:
# a typed message, or the Mini App's data message.
BUSY_NOTICE = "A command is still running. Use the buttons above, or /cancel."

# Where the page's message is kept, under the instance's logging.dir, so `strength ingest`
# reads a file like any other (DESIGN_gym_logger.md §6).
GYM_LOG_DIR = "gym_logs"


def unauthorized_notice(chat_id: int) -> str:
    """What an unlisted chat gets back, with the id the operator has to allowlist."""
    return (f"Not authorized. Your chat id is {chat_id}; add it to "
            "telegram.allowed_chat_ids to enable access.")


class MessagesMixin:
    """`ChatBot`'s half that answers a message the athlete typed or tapped a label for."""

    async def _simple_route(
        self, chat_id: int, text: str, armed_tap: bool = False
    ) -> Optional[List[str]]:
        """Maps free text onto argv via the intent router (§5.3).
        Replies itself (help text, gentle fallback) and returns None when nothing
        should run; otherwise echoes the routed action and returns the argv.

        `armed_tap` — she just tapped "💬 Talk to me". It never changes a message the
        router could read, so the tap has nothing to explain (§5.2)."""
        intent = await self._route_intent(text)
        self._log(chat_id, "  ", f"routed: {intent}")
        echo = ROUTER_ECHO.get(intent)
        # State and availability go to the coach in her own words; anything to be
        # remembered goes to the capture inbox, which asks before it stores and costs no
        # adaptation. A misroute across that line degrades gracefully both ways (§12.3).
        if intent in ROUTER_MESSAGE_ARGV:
            argv = [*ROUTER_MESSAGE_ARGV[intent], text]
            # Not taken while a run of the coach is alive, and it gets no echo.
            if await self._coach_busy(chat_id, argv):
                return None
        elif intent in ROUTER_CAPTURE_INTENTS:
            argv = ["bot", "capture", ROUTER_CAPTURE_INTENTS[intent], text]
        elif intent in ROUTER_INTENT_ARGV:
            argv = list(ROUTER_INTENT_ARGV[intent])
        elif intent == "help":
            await self._send_keyed(chat_id, SIMPLE_HELP)
            return None
        else:
            if not armed_tap:
                await self._send_keyed(chat_id, ROUTER_FALLBACK)
                return None
            # A note the router cannot place is still a note (§5.2), and the capture
            # inbox is the one that asks before storing — and still offers the coach on
            # a miss (§12.3).
            self._log(chat_id, "  ", "armed: unroutable text rides the capture inbox")
            argv = ["bot", "capture", "note", text]
            echo = CAPTURE_RESCUE_ECHO
        if echo:
            await self.bot.send_message(
                chat_id=chat_id, text=f"<i>→ {html.escape(echo)}</i>",
                parse_mode=telegram_api.html_parse_mode(),
            )
        return argv

    def _capture_armed(self, chat_id: int) -> bool:
        """Consumes a chat's "💬 Talk to me" tap; a stale one (past the prompt
        timeout) reads as untapped, so a next-morning message isn't quietly taken as
        a note (§5.2)."""
        armed_at = self.armed.pop(chat_id, None)
        return armed_at is not None and (time.monotonic() - armed_at) <= self.prompt_timeout

    @staticmethod
    def _end(session: runner.Session) -> None:
        """Ends one live command: the prompt it waits on is answered "cancelled", and a
        command that is computing is killed, which `_drive` cleans up after."""
        fut = session.answer_future
        if session.awaiting and fut is not None and not fut.done():
            fut.set_result(
                prompt_answer(session.awaiting.get("id"), cancelled=True)
            )
            return
        try:
            session.proc.kill()
        except ProcessLookupError:
            pass

    async def _cancel(self, chat_id: int) -> str:
        """/cancel: ends the command in both places of the chat."""
        self.armed.pop(chat_id, None)  # /cancel also drops a "💬 Talk to me" tap (§5.2)
        runs = self._runs(chat_id)
        if not runs:
            return "Nothing to cancel."
        for session in runs:
            self._end(session)
        return "Cancelling…"

    async def _restart(self, chat_id: int) -> None:
        """Tears down, replies, then hard-exits with RESTART_EXIT_CODE for the sm-bot
        supervisor to relaunch us. See DESIGN_bot_restart.md §5.2."""
        await runner.restart_teardown(
            self.sessions.get(chat_id), self._pause_polling, self.coach_runs.get(chat_id)
        )
        runner.leave_restart_note(chat_id)
        await self.bot.send_message(chat_id=chat_id, text="Restarting…")
        os._exit(runner.RESTART_EXIT_CODE)

    async def on_message(self, update, context) -> None:
        message = update.effective_message
        chat = update.effective_chat
        if message is None or chat is None or not message.text:
            return

        text = message.text.strip()
        self._log(chat.id, ">>", repr(text))

        if not self._authorized(chat.id):
            self._log(chat.id, "--", "unauthorized")
            await message.reply_text(unauthorized_notice(chat.id))
            return

        token_low = text.lstrip("/").lower()
        if token_low == "cancel":
            await message.reply_text(await self._cancel(chat.id))
            return
        if token_low == "start":
            await self._send_keyed(chat.id, SIMPLE_WELCOME, send=message.reply_text)
            return
        if token_low == "help":
            # Bare help gets the companion card; `/help <cmd>` still reaches the CLI
            # tree for the operator (§5.1).
            await self._send_keyed(chat.id, SIMPLE_HELP, send=message.reply_text)
            return
        if token_low == "restart":
            await self._restart(chat.id)
            return

        for session in self._runs(chat.id):
            awaiting = session.awaiting
            fut = session.answer_future
            if (awaiting and awaiting.get("type") == "text"
                    and fut is not None and not fut.done()):
                fut.set_result(prompt_answer(awaiting.get("id"), answer=text))
                self._log(chat.id, "  ", "text answer")
                return
        # Only the chat's own place makes it busy: the coach's run works beside it
        # (DESIGN_waiting_proposal.md §6.1).
        if self.sessions.get(chat.id) is not None:
            await message.reply_text(BUSY_NOTICE)
            return

        # A log the page could not send, copied from it and pasted (DESIGN_gym_logger.md §6).
        if text.startswith("{"):
            await self._ingest_gym_log(chat.id, text)
            return

        # About to act on the athlete's own message: what changed in their week goes first.
        await self._tell_changes_first(chat.id)

        # Non-slash text is a keyboard label, or free text for the router (§5). A leading
        # slash is a CLI command line, so the operator can drive the instance from its
        # chat.
        if not text.startswith("/"):
            action = keyboard_action(text)
            if action is not None and action[0] == "capture":
                self.armed[chat.id] = time.monotonic()
                await self._send_keyed(chat.id, CAPTURE_PROMPT, send=message.reply_text)
                return
            if action is not None:
                argv = list(action[1])
            else:
                await context.bot.send_chat_action(chat_id=chat.id, action="typing")
                # Read the tap here so it is consumed once per message, routed or not.
                argv = await self._simple_route(
                    chat.id, text, self._capture_armed(chat.id)
                )
                if argv is None:
                    return
            self._log(chat.id, "  ", f"run: {shlex.join(argv)}")
            await context.bot.send_chat_action(chat_id=chat.id, action="typing")
            await self._start_command(chat.id, argv)
            return

        bot_username = context.bot.username if context.bot else None
        try:
            argv = parse_message_to_argv(text, bot_username)
        except ValueError:
            await message.reply_text("Couldn't parse that — check your quotes.")
            return
        if not argv or await self._coach_busy(chat.id, argv):
            return

        self._log(chat.id, "  ", f"run: {shlex.join(argv)}")
        await context.bot.send_chat_action(chat_id=chat.id, action="typing")
        await self._start_command(chat.id, argv)

    def _write_gym_log(self, data: str) -> str:
        """Keeps the page's message as a file under `logs/gym_logs/`, named for the
        moment it arrived, and returns its path (DESIGN_gym_logger.md §6)."""
        folder = os.path.join(config.logging_dir, GYM_LOG_DIR)
        os.makedirs(folder, exist_ok=True)
        stamp = clock.now()
        path = os.path.join(
            folder, f"{clock.day_str(stamp.date())}-{stamp.strftime('%H%M%S')}.json"
        )
        with open(path, "w", encoding="utf-8") as handle:
            handle.write(data)
        return path

    async def on_web_app_data(self, update, context) -> None:
        """A message from one of the pages: the calendar asking for a day in full, the
        "Goals & plan" page asking why, or the gym logger's log when the athlete taps
        "Finish".

        The calendar's day runs `workout list -d <day>`, the command behind "📅 Today"
        (DESIGN_calendar_miniapp.md §6); the why runs `plan show` (§3.7). The log is written
        to a file and handed to `strength ingest`, whose summary streams back the way every
        command's output does. The bot never reads the log itself: every write goes through
        the CLI (DESIGN_gym_logger.md §6)."""
        message = update.effective_message
        chat = update.effective_chat
        if message is None or chat is None or message.web_app_data is None:
            return

        data = message.web_app_data.data or ""
        self._log(chat.id, ">>", f"web_app_data <{len(data.encode('utf-8'))} bytes>")

        if not self._authorized(chat.id):
            self._log(chat.id, "--", "unauthorized")
            await message.reply_text(unauthorized_notice(chat.id))
            return

        if self.sessions.get(chat.id) is not None:
            await self._send_keyed(chat.id, BUSY_NOTICE, send=message.reply_text)
            return

        day = calendar_page.requested_day(data)
        if day is not None:
            self._log(chat.id, "  ", f"calendar day: {day}")
            await self._start_command(chat.id, ["workout", "list", "-d", day])
            return
        plan = plan_page.why_plan(data)
        if plan is not None:
            self._log(chat.id, "  ", f"plan: why {plan}")
            await self._start_command(chat.id, ["plan", "show", "--macrocycle", str(plan)])
            return

        await self._ingest_gym_log(chat.id, data)

    async def _ingest_gym_log(self, chat_id: int, data: str) -> None:
        """The gym log, sent by the page or pasted in the chat, handed to `strength ingest`."""
        path = self._write_gym_log(data)
        self._log(chat_id, "  ", f"gym log: {path}")
        await self._start_command(chat_id, ["strength", "ingest", path])
