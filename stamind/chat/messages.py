"""What the bot does with a message the athlete sends.

Every text update lands in `on_message`. The allowlist comes first, then the handful of
words the bot answers itself — /cancel, /start, /help, /restart, /ui — then the answer to
an open text prompt. Everything past that is a command to run.

Which command depends on the persona. In expert mode the message is a CLI command line
and `parse_message_to_argv` turns it into argv. In companion mode a keyboard label runs
its fixed argv, and anything else goes through the intent router: `_simple_route` asks
`tm bot route` what the message means and maps the answer onto either the coach lane,
which carries the athlete's own words, or the capture inbox, which asks before it stores
(DESIGN_bot_simple_frontend.md §5, §12.3).
"""
import html
import os
import shlex
import time
from typing import List, Optional

from stamind.chat import runner, telegram_api
from stamind.chat.keyboards import (
    SIMPLE_HELP, SIMPLE_WELCOME, WELCOME, keyboard_action, stale_keyboard_tap,
)
from stamind.chat.routing import (
    CAPTURE_PROMPT, CAPTURE_RESCUE_ECHO, ROUTER_CAPTURE_INTENTS, ROUTER_ECHO,
    ROUTER_FALLBACK, ROUTER_INTENT_ARGV, ROUTER_MESSAGE_ARGV, UI_EXPERT_ON, UI_SIMPLE_ON,
    UI_USAGE, parse_message_to_argv, parse_ui_switch,
)
from stamind.sentinels import prompt_answer


class MessagesMixin:
    """`ChatBot`'s half that answers a message the athlete typed or tapped a label for."""

    async def _simple_route(
        self, chat_id: int, text: str, armed_tap: bool = False
    ) -> Optional[List[str]]:
        """Maps simple-mode free text onto argv via the intent router (§5.3).
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
        elif intent in ROUTER_CAPTURE_INTENTS:
            argv = ["bot", "capture", ROUTER_CAPTURE_INTENTS[intent], text]
        elif intent in ROUTER_INTENT_ARGV:
            argv = list(ROUTER_INTENT_ARGV[intent])
        elif intent == "help":
            await self.bot.send_message(
                chat_id=chat_id, text=SIMPLE_HELP, reply_markup=self._keyboard()
            )
            return None
        else:
            if not armed_tap:
                await self.bot.send_message(
                    chat_id=chat_id, text=ROUTER_FALLBACK, reply_markup=self._keyboard()
                )
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

    async def _cancel(self, chat_id: int) -> str:
        self.armed.pop(chat_id, None)  # /cancel also drops a "💬 Talk to me" tap (§5.2)
        session = self.sessions.get(chat_id)
        if session is None:
            return "Nothing to cancel."
        fut = session.answer_future
        if session.awaiting and fut is not None and not fut.done():
            fut.set_result(
                prompt_answer(session.awaiting.get("id"), cancelled=True)
            )
        else:  # mid-compute: kill the process; _drive cleans up
            try:
                session.proc.kill()
            except ProcessLookupError:
                pass
        return "Cancelling…"

    async def _set_ui(self, chat_id: int, target: bool, announce: bool = True) -> None:
        """Flips the persona in place (§5.6): swaps the command menu, then confirms —
        attaching the reply keyboard on the way into simple, removing it on the way
        out. `announce=False` skips the confirmation for a switch nobody asked for.
        In-memory only; config.telegram_ui rules again at the next restart."""
        self.simple_ui = target
        await self._set_command_menu(target)
        if announce and target:
            await self.bot.send_message(
                chat_id=chat_id, text=UI_SIMPLE_ON, reply_markup=self.reply_keyboard
            )
        elif announce:
            await self.bot.send_message(
                chat_id=chat_id, text=UI_EXPERT_ON,
                reply_markup=telegram_api.drop_reply_keyboard(),
            )
        self._log(chat_id, "  ", f"ui: {'simple' if target else 'expert'}")

    async def _restart(self, chat_id: int) -> None:
        """Tears down, replies, then hard-exits with RESTART_EXIT_CODE for the tm-bot
        supervisor to relaunch us. See DESIGN_bot_restart.md §5.2."""
        await runner.restart_teardown(self.sessions.get(chat_id), self._pause_polling)
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
            await message.reply_text(
                f"Not authorized. Your chat id is {chat.id}; add it to "
                "telegram.allowed_chat_ids to enable access."
            )
            return

        token_low = text.lstrip("/").lower()
        if token_low == "cancel":
            await message.reply_text(await self._cancel(chat.id))
            return
        if token_low == "start":
            if self.simple_ui:
                await message.reply_text(SIMPLE_WELCOME, reply_markup=self._keyboard())
            else:
                await message.reply_text(WELCOME)
            return
        if token_low == "help" and self.simple_ui:
            # Bare help gets the companion card; `/help <cmd>` still reaches the CLI
            # tree for the operator (§5.1).
            await message.reply_text(SIMPLE_HELP, reply_markup=self._keyboard())
            return
        if token_low == "restart":
            await self._restart(chat.id)
            return
        if token_low == "ui" or token_low.startswith("ui "):
            target = parse_ui_switch(token_low, self.simple_ui)
            if target is None:
                await message.reply_text(UI_USAGE)
                return
            await self._set_ui(chat.id, target)
            return

        session = self.sessions.get(chat.id)
        if session is not None:
            awaiting = session.awaiting
            fut = session.answer_future
            if (awaiting and awaiting.get("type") == "text"
                    and fut is not None and not fut.done()):
                fut.set_result(prompt_answer(awaiting.get("id"), answer=text))
                self._log(chat.id, "  ", "text answer")
                return
            await message.reply_text(
                "A command is still running. Use the buttons above, or /cancel."
            )
            return

        # About to act on the athlete's own message: what changed in their week goes first.
        await self._tell_changes_first(chat.id)

        # A tap on the companion keyboard is the companion, whatever persona this
        # process last settled on: the keyboard sits on the phone until Telegram is
        # told to drop it, so a restart back into expert leaves it live (§5.6).
        if stale_keyboard_tap(text, self.simple_ui):
            # Silently: she tapped a button, not /ui — the answer to the tap is the
            # only feedback the switch earns (§5.6).
            await self._set_ui(chat.id, True, announce=False)

        # Simple mode: non-slash text is the companion surface — keyboard labels,
        # then the free-text router for everything else (§5). A leading slash stays
        # the expert path, so the operator can still drive the instance from its chat.
        if self.simple_ui and not text.startswith("/"):
            action = keyboard_action(text)
            if action is not None and action[0] == "capture":
                self.armed[chat.id] = time.monotonic()
                await message.reply_text(CAPTURE_PROMPT, reply_markup=self._keyboard())
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
        if not argv:
            return

        self._log(chat.id, "  ", f"run: {shlex.join(argv)}")
        await context.bot.send_chat_action(chat_id=chat.id, action="typing")
        await self._start_command(chat.id, argv)
