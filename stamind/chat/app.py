"""The Telegram process: the bot object, its lifetime, and the state its parts share.

`ChatBot` is what `stamind_bot.py` builds and runs. It reads the `telegram:` section of
config.yaml, builds the client, wires the two update handlers, and then runs until a
signal stops it. The five mixins it is assembled from — running a CLI subprocess, sending
its output back, answering a message, answering a tap, and firing the scheduler — reach
each other and their shared state through `self`: the live sessions, the current persona,
the allowlist, and the client itself.

Polling runs from start to shutdown, a command in flight or not, which is what lets a
✋ Stop tap or /cancel reach a command that is waiting on the coach
(DESIGN_bot_stop_button.md §5). `_serve` therefore drives the Application and the Updater
by hand rather than through `run_polling()`: /restart has to close the long-poll from
inside a handler, before its hard exit, and `run_polling()` does not expose that
(DESIGN_bot_restart.md §5.2).
"""
import asyncio
import datetime
import signal
import sys
from typing import Dict, List, Optional, Tuple

from stamind import clock, journal, runtime
from stamind.chat import telegram_api
from stamind.chat.callbacks import CallbacksMixin
from stamind.chat.keyboards import (
    GYM_SPORT, MENU_COMMANDS, SIMPLE_MENU_COMMANDS, gym_button, gym_window_end,
    simple_keyboard_rows,
)
from stamind.chat.messages import MessagesMixin
from stamind.chat.replies import RepliesMixin
from stamind.chat.runner import RunnerMixin, Session
from stamind.chat.scheduler import SchedulerMixin
from stamind.config import config
from stamind.output import warn
from stamind.strength import logger


class ChatBot(RunnerMixin, RepliesMixin, MessagesMixin, CallbacksMixin, SchedulerMixin):
    """One long-polling Telegram front-end over the CLI. Build it, then call `run`."""

    def __init__(self) -> None:
        token = config.telegram_bot_token
        if not token:
            sys.exit(
                "No Telegram bot token configured. Set TELEGRAM_BOT_TOKEN or add a "
                "telegram.bot_token to config.yaml (see config_template.yaml)."
            )
        self.allowed_ids: List[int] = config.telegram_allowed_chat_ids
        if not self.allowed_ids:
            warn(
                "telegram.allowed_chat_ids is empty — the bot will refuse every message. "
                "Add your numeric chat id to authorize yourself."
            )
        self.prompt_timeout = config.telegram_prompt_timeout
        self.command_timeout = config.telegram_command_timeout
        # The persona starts from config but /ui may flip it live (§5.6, in-memory
        # only), so everything derived from it is computed at use time, never captured.
        self.simple_ui = config.telegram_ui == "simple"

        # First call into python-telegram-bot, and deliberately before anything else that
        # needs it: a missing install is answered with the line that fixes it, not with a
        # traceback out of whichever builder happened to run first.
        self.application = telegram_api.build_application(token)
        self.bot = self.application.bot
        self.updater = self.application.updater
        telegram_api.register_handlers(
            self.application, self.on_message, self.on_callback, self.on_web_app_data
        )

        self.sessions: Dict[int, Session] = {}
        # Simple-mode chat state: chats that just tapped "💬 Talk to me" (chat_id →
        # monotonic arm time, cleared after one message, /cancel or the prompt timeout);
        # the tap only keeps an unroutable message from bouncing (§5.2). Plus the live
        # SM-BUTTONS payload per chat (chat_id → (token, buttons), valid until replaced
        # by the next push, §4.4).
        self.armed: Dict[int, float] = {}
        self.ui_actions: Dict[int, Tuple[str, List[dict]]] = {}
        # Held until each ends: asyncio keeps only a weak reference to a running task.
        self.reflect_tasks: set = set()

        # The one remaining stop on the long-poll is /restart's, which closes it before
        # the process exits (DESIGN_bot_restart.md §5.2); the lock guards against that
        # stop racing _serve's own.
        self.polling_lock = asyncio.Lock()

        # The morning push goes to the first allowlisted chat — the single-athlete
        # instance model makes that the athlete (§4.3).
        self.push_chat_id: Optional[int] = self.allowed_ids[0] if self.allowed_ids else None

    def _authorized(self, chat_id: int) -> bool:
        """True only when chat_id is on the allowlist. An empty allowlist authorizes
        no one, which is what an unconfigured instance gets."""
        return chat_id in self.allowed_ids

    def _wrap_width(self) -> int:
        # Simple mode sends prose the client flows itself, so hard-wrapping at phone
        # width would only add ragged mid-sentence breaks — wrap far past any real
        # line instead (§6).
        return 900 if self.simple_ui else config.telegram_wrap_width

    def _gym_button(self) -> Optional[Tuple[str, str]]:
        """The gym button's label and the address it opens, or None when no Mini App is
        configured or no gym session is coming (DESIGN_gym_logger.md §6)."""
        base_url = config.telegram_miniapp_url
        if not base_url:
            return None
        today = clock.today_str()
        workouts = runtime.db.get_workouts(
            today, gym_window_end(today), sport_type=GYM_SPORT
        )
        found = gym_button(workouts, today)
        if found is None:
            return None
        label, workout = found
        return label, logger.session_url(base_url, workout)

    def _keyboard(self):
        """The §5.1 reply keyboard the companion attaches, rebuilt on every send so the
        gym button follows the week (DESIGN_gym_logger.md §6). Expert mode has none."""
        if not self.simple_ui:
            return None
        return telegram_api.reply_keyboard(simple_keyboard_rows(self._gym_button()))

    def _log(self, chat_id: int, direction: str, msg: str) -> None:
        """The bot's own timeline: printed live, and journalled (DESIGN_logging.md §8).

        Also journalled, not instead: an operator watching ./sm-bot in a terminal keeps
        the view they have today. Where that stdout goes depends entirely on how the
        supervisor was launched, which in practice means nowhere."""
        ts = datetime.datetime.now().strftime("%H:%M:%S")
        print(f"{ts} [{chat_id}] {direction} {msg}", flush=True)
        journal.record("bot.event", f"{direction} {msg}", chat=chat_id)

    async def _pause_polling(self) -> None:
        async with self.polling_lock:
            if self.updater.running:
                await self.updater.stop()

    async def _set_command_menu(self, simple: bool) -> None:
        """Swaps the list of commands Telegram offers in its own menu.

        Purely cosmetic — every command works whether or not it is listed — so a failure
        is journalled and never stops the caller."""
        commands = SIMPLE_MENU_COMMANDS if simple else MENU_COMMANDS
        try:
            await self.bot.set_my_commands(telegram_api.command_menu(commands))
        except Exception as exc:
            journal.debug("bot.event", f"command menu not updated: {exc}")

    async def _serve(self) -> None:
        """Runs the bot until SIGINT/SIGTERM."""
        stop_event = asyncio.Event()
        loop = asyncio.get_running_loop()
        for sig in (signal.SIGINT, signal.SIGTERM):
            loop.add_signal_handler(sig, stop_event.set)
        async with self.application:
            # The opening work python-telegram-bot would have done through `post_init`,
            # which it runs only from `run_polling()` — the call this method replaces.
            await self._set_command_menu(self.simple_ui)
            await self.application.start()
            await self.updater.start_polling(
                allowed_updates=telegram_api.all_update_types()
            )
            # Started whenever there is a chat to push to: the persona and the `push`
            # setting are checked per tick inside the loop, so a /ui flip (§5.6) or a
            # `settings set push off` turns it on and off live (DESIGN_settings.md §5).
            push_task = (asyncio.create_task(self._push_loop())
                         if self.push_chat_id is not None else None)
            await stop_event.wait()
            if push_task is not None:
                push_task.cancel()
            if self.updater.running:
                await self.updater.stop()
            await self.application.stop()

    def run(self) -> None:
        """Polls Telegram until interrupted."""
        print("Stamind Telegram bot started. Press Ctrl-C to stop.")
        # One long-lived run for the whole process, so the bot's own lifetime is a readable
        # timeline and every subprocess it spawns names it as their parent
        # (DESIGN_logging.md §8). It gets a `run.end` only on a clean shutdown: a /restart
        # hard-exits and a supervisor kill takes it with no warning, which is the normal way
        # it ends and the reason the `?` outcome exists (§3).
        journal.start_run(["sm-bot"], source="bot")
        asyncio.run(self._serve())
        journal.end_run("ok")
