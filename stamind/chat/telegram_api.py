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
import sys

from stamind.text import cmd


def build_application(token: str):
    """The Application the bot polls with.

    No `post_init` hook: python-telegram-bot runs that one only from `run_polling()`,
    which `ChatBot._serve` replaces, so the bot does its own opening work there.

    This is the first call into the library, so a missing install is reported at startup,
    with the line that fixes it, rather than on the first button the bot tries to draw."""
    try:
        from telegram.ext import Application
    except ImportError:
        sys.exit(
            "python-telegram-bot is not installed. Run: "
            + cmd("venv/bin/pip install -r requirements.txt", quote=False)
        )
    return Application.builder().token(token).build()


def register_handlers(application, on_message, on_callback, on_web_app_data) -> None:
    """Wires the three update kinds the bot answers: the Mini App's data message, a text
    message, and a button tap."""
    from telegram.ext import CallbackQueryHandler, MessageHandler, filters

    # First, so the page's message never falls to the text handler
    # (DESIGN_gym_logger.md §6).
    application.add_handler(
        MessageHandler(filters.StatusUpdate.WEB_APP_DATA, on_web_app_data)
    )
    # filters.TEXT catches commands too (a '/status' message is still text).
    application.add_handler(MessageHandler(filters.TEXT, on_message))
    application.add_handler(CallbackQueryHandler(on_callback))


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


def is_refusal(exc: BaseException) -> bool:
    """Whether Telegram answered the request with "Bad Request", so nothing was sent
    (DESIGN_calendar_miniapp.md §6)."""
    from telegram.error import BadRequest

    return isinstance(exc, BadRequest)


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
