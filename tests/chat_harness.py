"""Stand-ins for python-telegram-bot, so a real `ChatBot` can be driven in a test.

Not a test module: `unittest discover` skips it, and the files that are import it.

`trainmate/chat/telegram_api.py` is the only module that names the library, so standing
the library in is patching eight functions. Each stand-in here returns what it was handed
— `inline_keyboard(rows)` gives back `rows` — so a test reads the rows the front-end
built rather than a library object it would have to take apart again.
"""
import asyncio
import os
from types import SimpleNamespace
from unittest import mock

from trainmate.chat import scheduler, telegram_api
from trainmate.chat.app import ChatBot
from trainmate.config import config


class _FakeBot:
    """Stands in for `telegram.Bot`: records every call instead of making one."""

    username = "trainmate_bot"

    def __init__(self) -> None:
        self.sent = []           # (chat_id, text, kwargs)
        self.edits = []          # (chat_id, message_id, reply_markup)
        self.photos = []         # (chat_id, caption)
        self.actions = []        # (chat_id, action)
        self.menus = []          # each set_my_commands payload
        self._next_id = 100

    async def send_message(self, chat_id=None, text="", **kw):
        self._next_id += 1
        self.sent.append((chat_id, text, kw))
        return SimpleNamespace(message_id=self._next_id)

    async def edit_message_reply_markup(self, chat_id=None, message_id=None,
                                        reply_markup=None):
        self.edits.append((chat_id, message_id, reply_markup))

    async def send_chat_action(self, chat_id=None, action=None):
        self.actions.append((chat_id, action))

    async def send_photo(self, chat_id=None, photo=None, caption=None):
        self.photos.append((chat_id, caption))

    async def set_my_commands(self, commands):
        self.menus.append(list(commands))

    def texts(self):
        return [text for _chat, text, _kw in self.sent]


class _FakeApplication:
    def __init__(self) -> None:
        self.bot = _FakeBot()
        self.updater = SimpleNamespace(running=False)


class _FakeProc:
    """Stand-in for the CLI subprocess: exits on its own only if told to."""

    def __init__(self, exits_on_its_own: bool = False) -> None:
        self.returncode = None
        self.killed = False
        self._exits_on_its_own = exits_on_its_own

    async def wait(self) -> int:
        if not self._exits_on_its_own:
            await asyncio.sleep(3600)
        self.returncode = 0
        return 0

    def kill(self) -> None:
        self.killed = True
        self.returncode = -9


class _FakeQuery:
    """Stands in for a `telegram.CallbackQuery`: one tap, and what the bot did to it."""

    def __init__(self, data: str, text: str = "", markup=None) -> None:
        self.data = data
        self.answered = False
        self.markups = []        # every reply_markup the bot swapped in (None = dropped)
        self.edited_text = None
        self.message = SimpleNamespace(text=text, reply_markup=markup)

    async def answer(self):
        self.answered = True

    async def edit_message_reply_markup(self, reply_markup=None):
        self.markups.append(reply_markup)

    async def edit_message_text(self, text=None):
        self.edited_text = text


def build_chat_bot(testcase, ui: str = "simple", allowed=(42,)) -> ChatBot:
    """A real `ChatBot` with python-telegram-bot stood in for.

    Every builder in `telegram_api` is replaced by one that returns what it was handed, so
    a test can read the rows the front-end built rather than a library object."""
    patchers = [
        mock.patch.dict(os.environ, {"TELEGRAM_BOT_TOKEN": "test-token"}),
        mock.patch.dict(
            config.data,
            {"telegram": {"allowed_chat_ids": list(allowed), "ui": ui, "wrap_width": 48}},
        ),
        mock.patch.object(telegram_api, "build_application",
                          lambda token: _FakeApplication()),
        mock.patch.object(telegram_api, "register_handlers", lambda *a, **k: None),
        mock.patch.object(telegram_api, "reply_keyboard",
                          lambda rows: ("reply-keyboard", rows)),
        mock.patch.object(telegram_api, "drop_reply_keyboard", lambda: "keyboard-removed"),
        mock.patch.object(telegram_api, "inline_keyboard", lambda rows: rows),
        mock.patch.object(telegram_api, "command_menu", lambda commands: list(commands)),
        mock.patch.object(telegram_api, "html_parse_mode", lambda: "HTML"),
        # The bot's own timeline goes to stdout; a suite does not need it.
        mock.patch("trainmate.chat.app.print", create=True),
        # `_tell_changes_first` reads the database before acting on the athlete's own
        # message; these cases are about the handler, not about what is waiting.
        mock.patch.object(scheduler.heads_up, "waiting", return_value=False),
    ]
    for patcher in patchers:
        patcher.start()
        testcase.addCleanup(patcher.stop)
    return ChatBot()


def message_update(chat_id: int = 42, text: str = "/status"):
    """A text update, and the list its `reply_text` answers land in."""
    replied = []

    async def reply_text(text, **kw):
        replied.append((text, kw))

    message = SimpleNamespace(text=text, reply_text=reply_text)
    update = SimpleNamespace(
        effective_message=message, effective_chat=SimpleNamespace(id=chat_id)
    )
    return update, replied


def callback_update(query: _FakeQuery, chat_id: int = 42):
    return SimpleNamespace(
        callback_query=query, effective_chat=SimpleNamespace(id=chat_id)
    )


def routes_to(chat_bot: ChatBot, intent: str):
    """Makes `tm bot route` answer `intent`, without running the CLI to ask it."""
    async def route(_text):
        return intent

    return mock.patch.object(chat_bot, "_route_intent", route)


def record_commands(testcase, chat_bot: ChatBot) -> list:
    """Replaces `_start_command` with a recorder; returns the list it fills."""
    started = []

    async def start(chat_id, argv, quiet=False, source="bot"):
        started.append((chat_id, list(argv), quiet, source))
        done = asyncio.get_running_loop().create_future()
        done.set_result(None)
        return SimpleNamespace(task=done)

    patcher = mock.patch.object(chat_bot, "_start_command", start)
    patcher.start()
    testcase.addCleanup(patcher.stop)
    return started
