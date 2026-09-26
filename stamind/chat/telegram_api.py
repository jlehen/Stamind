"""Every name this package takes from python-telegram-bot, in one file.

Each function imports the library when it is called, never at module scope. That is what
keeps every other module under `stamind/chat/` importable — and unit-testable — without
the library installed, and what keeps `sm bot route` from dragging a chat front-end onto a
command line. `tests/test_layering.py` holds the rule.

The inline-keyboard builder is also the one copy of an expression the front-end used to
write out five times, plus a sixth spelled slightly differently. A prompt's choices, a
SM-BUTTONS offer, a sub-menu, a queued item's answers, its "not now" choices and the
✋ Stop button are all rows of (label, callback_data).
"""
import asyncio
import sys
import time

from stamind import journal
from stamind.text import cmd

# The pause before each retry of a call Telegram failed to answer: doubling from a second
# and capped, until `telegram.send_retry_seconds` has passed (DESIGN_telegram_send_retry.md
# §2).
RETRY_FIRST_DELAY = 1.0
RETRY_MAX_DELAY = 15.0


def build_application(token: str, send_retry_seconds: float):
    """The Application the bot polls with.

    No `post_init` hook: python-telegram-bot runs that one only from `run_polling()`,
    which `ChatBot._serve` replaces, so the bot does its own opening work there.

    This is the first call into the library, so a missing install is reported at startup,
    with the line that fixes it, rather than on the first button the bot tries to draw.

    Only the calls the bot makes go through the retrying client: the library builds a
    client of its own for the poll (DESIGN_telegram_send_retry.md §2)."""
    try:
        from telegram.ext import Application
    except ImportError:
        sys.exit(
            "python-telegram-bot is not installed. Run: "
            + cmd("venv/bin/pip install -r requirements.txt", quote=False)
        )
    return (
        Application.builder()
        .token(token)
        .request(retrying_request(send_retry_seconds))
        .build()
    )


def retrying_request(window_seconds: float, sleep=None, clock=None):
    """The HTTP client every call but the poll goes through: a call Telegram fails to answer
    is tried again after a growing pause until `window_seconds` have passed, and then the
    last failure goes through as it came (DESIGN_telegram_send_retry.md §2).

    A 5xx comes back from the library's own `do_request` as a status code, a connection
    error or a timeout as a `NetworkError`; both are Telegram not answering. `sleep` and
    `clock` are for the tests."""
    from telegram.error import NetworkError
    from telegram.request import HTTPXRequest

    sleep = sleep or asyncio.sleep
    clock = clock or time.monotonic

    class RetryingRequest(HTTPXRequest):
        async def do_request(self, *args, **kwargs):
            deadline = clock() + window_seconds
            delay = RETRY_FIRST_DELAY
            while True:
                try:
                    code, payload = await super().do_request(*args, **kwargs)
                except NetworkError as exc:
                    if clock() + delay > deadline:
                        raise
                    reason = f"{type(exc).__name__}: {exc}"
                else:
                    if code < 500 or clock() + delay > deadline:
                        return code, payload
                    reason = f"HTTP {code}"
                journal.debug(
                    "bot.event", f"telegram did not answer ({reason}), retrying in {delay:g}s"
                )
                await sleep(delay)
                delay = min(delay * 2, RETRY_MAX_DELAY)

    return RetryingRequest()


def is_network_error(exc: BaseException) -> bool:
    """Whether `exc` is the library saying Telegram could not be reached, which is what the
    retrying client gives up with, and never one of our own failures
    (DESIGN_telegram_send_retry.md §2)."""
    try:
        from telegram.error import NetworkError
    except ImportError:
        return False
    return isinstance(exc, NetworkError)


def register_handlers(
    application, on_message, on_callback, on_web_app_data, on_error
) -> None:
    """Wires the three update kinds the bot answers, the Mini App's data message, a text
    message and a button tap, and the handler for the failure any of them ends in."""
    from telegram.ext import CallbackQueryHandler, MessageHandler, filters

    # First, so the page's message never falls to the text handler
    # (DESIGN_gym_logger.md §6).
    application.add_handler(
        MessageHandler(filters.StatusUpdate.WEB_APP_DATA, on_web_app_data)
    )
    # filters.TEXT catches commands too (a '/status' message is still text).
    application.add_handler(MessageHandler(filters.TEXT, on_message))
    application.add_handler(CallbackQueryHandler(on_callback))
    application.add_error_handler(on_error)


def all_update_types():
    """What `start_polling` asks Telegram to deliver."""
    from telegram import Update

    return Update.ALL_TYPES


def inline_keyboard(rows):
    """An inline keyboard from rows of (label, callback_data)."""
    from telegram import InlineKeyboardButton, InlineKeyboardMarkup

    return InlineKeyboardMarkup(
        [[InlineKeyboardButton(label, callback_data=data) for label, data in row]
         for row in rows]
    )


def reply_keyboard(rows):
    """The persistent reply keyboard, from rows of cells
    (DESIGN_bot_simple_frontend.md §5.1).

    A cell is a plain label, or a (label, url) pair — the gym button, which opens the
    Mini App at that address instead of sending its label as text
    (DESIGN_gym_logger.md §6)."""
    from telegram import KeyboardButton, ReplyKeyboardMarkup, WebAppInfo

    def cell(value):
        if not isinstance(value, tuple):
            return KeyboardButton(value)
        label, url = value
        return KeyboardButton(label, web_app=WebAppInfo(url=url))

    return ReplyKeyboardMarkup(
        [[cell(value) for value in row] for row in rows],
        resize_keyboard=True, is_persistent=True,
    )


def drop_reply_keyboard():
    """Tells the client to take the reply keyboard off the phone
    (DESIGN_bot_simple_frontend.md §5.6)."""
    from telegram import ReplyKeyboardRemove

    return ReplyKeyboardRemove()


def command_menu(commands):
    """Telegram's own command menu, from (name, description) pairs."""
    from telegram import BotCommand

    return [BotCommand(name, description) for name, description in commands]


def html_parse_mode():
    """The parse mode every reply is sent under: the bot writes HTML, not Markdown."""
    from telegram.constants import ParseMode

    return ParseMode.HTML
