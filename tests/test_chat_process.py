"""The Telegram process: `ChatBot`, the state its parts share, and what it sends.

`tests/test_bot.py` covers the front-end's pure modules — what a message means, what the
bot draws, when the scheduler fires. This file covers the object that uses them: how it
reads its own configuration, how a command's output reaches the chat, and how /restart
tears a live command down. `tests/test_chat_handlers.py` covers what arrives from the
athlete. The stand-ins all three use are in `tests/chat_harness.py`.
"""
import ast
import asyncio
import glob
import os
import pathlib
import sys
import tempfile
import unittest
from types import SimpleNamespace
from unittest import mock

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from tests import test_db_path
from tests.chat_harness import _FakeProc, build_chat_bot
from tests.helpers import bind_test_db, save_workout
from stamind import clock, settings
from stamind.chat import keyboards, replies, runner, telegram_api
from stamind.chat.app import ChatBot
from stamind.config import config
from stamind.strength import logger

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


class AuthTest(unittest.TestCase):
    """The chat-id allowlist. `_authorized` reads `self.allowed_ids` and nothing else."""

    def _bot(self, allowed):
        return SimpleNamespace(allowed_ids=allowed)

    def test_allowlisted_id_passes(self):
        self.assertTrue(ChatBot._authorized(self._bot([1, 42, 3]), 42))

    def test_unlisted_id_rejected(self):
        self.assertFalse(ChatBot._authorized(self._bot([1, 42, 3]), 99))

    def test_empty_allowlist_rejects_everyone(self):
        self.assertFalse(ChatBot._authorized(self._bot([]), 42))


class ChunkTest(unittest.TestCase):
    def test_short_text_single_chunk(self):
        self.assertEqual(replies.chunk_text("hello"), ["hello"])

    def test_splits_on_line_boundaries(self):
        text = "\n".join(["x" * 90] * 5)
        chunks = replies.chunk_text(text, limit=200)
        self.assertGreater(len(chunks), 1)
        for chunk in chunks:
            self.assertLessEqual(len(chunk), 200)
        self.assertEqual("\n".join(chunks), text)

    def test_hard_splits_overlong_single_line(self):
        chunks = replies.chunk_text("y" * 250, limit=100)
        self.assertEqual(len(chunks), 3)
        self.assertEqual("".join(chunks), "y" * 250)


class FormatReplyTest(unittest.TestCase):
    def test_wraps_in_pre_and_escapes_html(self):
        parts = replies.format_reply("a < b & c > d")
        self.assertEqual(len(parts), 1)
        self.assertTrue(parts[0].startswith("<pre>"))
        self.assertTrue(parts[0].endswith("</pre>"))
        self.assertIn("&lt;", parts[0])
        self.assertIn("&amp;", parts[0])

    def test_the_companion_sends_plain_prose(self):
        """§6: the client flows it, so no <pre> and no column alignment to protect."""
        parts = replies.format_reply("a < b", simple=True)
        self.assertEqual(parts, ["a &lt; b"])


class RestartTeardownTest(unittest.IsolatedAsyncioTestCase):
    """/restart's teardown (DESIGN_bot_restart.md §5.2): no orphaned subprocess and no
    long-poll left open when os._exit() fires."""

    def setUp(self):
        patcher = mock.patch.object(runner, "RESTART_GRACE_SECONDS", 0.02)
        patcher.start()
        self.addCleanup(patcher.stop)
        self.stops = []

    async def _stop_polling(self):
        self.stops.append(True)

    def _session(self, awaiting=None, proc=None):
        session = runner.Session(42, proc if proc is not None else _FakeProc(), "n0nce")
        if awaiting is not None:
            session.awaiting = awaiting
            session.answer_future = asyncio.get_running_loop().create_future()
        return session

    async def test_kills_a_silently_computing_session(self):
        # A single getUpdates batch can deliver a command and /restart together, so
        # /restart can land with a subprocess running and no prompt open.
        session = self._session()
        await runner.restart_teardown(session, self._stop_polling)
        self.assertTrue(session.proc.killed)

    async def test_open_prompt_is_answered_cancelled_not_killed(self):
        session = self._session(
            {"id": "p1", "type": "confirm"}, _FakeProc(exits_on_its_own=True)
        )
        await runner.restart_teardown(session, self._stop_polling)
        self.assertTrue(session.answer_future.result()["cancelled"])
        self.assertFalse(session.proc.killed)

    async def test_open_prompt_whose_process_lingers_is_killed_after_the_grace(self):
        session = self._session({"id": "p1", "type": "confirm"})
        await runner.restart_teardown(session, self._stop_polling)
        self.assertTrue(session.proc.killed)

    async def test_finished_process_is_left_alone(self):
        session = self._session()
        session.proc.returncode = 0
        await runner.restart_teardown(session, self._stop_polling)
        self.assertFalse(session.proc.killed)

    async def test_releases_the_long_poll(self):
        # Without this, the abandoned getUpdates never confirms its offset and the
        # relaunched worker is served the same /restart again (§7).
        await runner.restart_teardown(None, self._stop_polling)
        self.assertEqual(self.stops, [True])
        session = self._session()
        await runner.restart_teardown(session, self._stop_polling)
        self.assertEqual(len(self.stops), 2)

    async def test_a_wedged_stop_still_returns(self):
        async def _hangs():
            await asyncio.sleep(3600)

        await runner.restart_teardown(None, _hangs)  # must not hold up the hard exit

    async def test_a_failing_stop_still_returns(self):
        async def _raises():
            raise RuntimeError("This Updater is not running!")

        await runner.restart_teardown(None, _raises)


class CliPathTest(unittest.TestCase):
    """Where the bot looks for the CLI it runs.

    `runner.py` sits two packages deep, so the path walks three directories up. Nothing
    else would notice it being wrong: the bot would spawn a child that exits immediately
    and the chat would answer "(no output)"."""

    def test_it_names_the_cli_beside_the_launcher(self):
        self.assertEqual(
            runner.CLI_PATH, os.path.join(REPO, "stamind_cli.py")
        )
        self.assertTrue(os.path.isfile(runner.CLI_PATH))

    def test_the_child_runs_from_the_repo_root(self):
        # `stamind_cli.py` resolves config.yaml and the database relative to itself, so
        # the working directory the child inherits has to be the repo, not the bot's.
        self.assertEqual(os.path.dirname(runner.CLI_PATH), REPO)


class StartupTest(unittest.TestCase):
    """What a half-configured instance is told, and in which order.

    Three things are checked before the bot can exist: the token, the allowlist, and
    whether python-telegram-bot is installed. The library check has to come before
    anything that draws a keyboard, or a missing install answers with a traceback out of
    whichever builder ran first instead of the line that fixes it."""

    def _configured(self, telegram: dict):
        return (
            mock.patch.dict(os.environ, {"TELEGRAM_BOT_TOKEN": "test-token"}),
            mock.patch.dict(config.data, {"telegram": telegram}),
        )

    def test_a_missing_token_is_the_first_thing_said(self):
        with mock.patch.dict(config.data, {"telegram": {}}), \
                mock.patch.dict(os.environ, {}, clear=False):
            os.environ.pop("TELEGRAM_BOT_TOKEN", None)
            with self.assertRaises(SystemExit) as caught:
                ChatBot()
        self.assertIn("No Telegram bot token configured", str(caught.exception))

    def test_a_missing_library_is_answered_with_the_line_that_fixes_it(self):
        # `None` in sys.modules is what makes an import of that name fail, so this hides
        # the library from a process that has it installed.
        hidden = dict.fromkeys(("telegram", "telegram.ext", "telegram.constants"))
        env, data = self._configured({"allowed_chat_ids": [42]})
        with env, data, mock.patch.dict(sys.modules, hidden):
            with self.assertRaises(SystemExit) as caught:
                ChatBot()
        self.assertIn("pip install -r requirements.txt", str(caught.exception))


class CommandMenuTest(unittest.IsolatedAsyncioTestCase):
    """Telegram's own command menu: set when the connection opens, swapped by `/ui`.

    python-telegram-bot fires a builder's `post_init` only from `run_polling()`, and
    `_serve` replaces that call (DESIGN_bot_restart.md §5.2), so the opening set has to be
    made by hand — a hook passed to the builder would never run."""

    def test_the_menu_is_set_when_the_connection_opens(self):
        self.assertIn("_set_command_menu", front_end_functions()["_serve"])

    async def test_each_persona_offers_its_own_list(self):
        chat_bot = build_chat_bot(self, ui="simple")
        await chat_bot._set_command_menu(True)
        await chat_bot._set_command_menu(False)
        self.assertEqual(
            chat_bot.bot.menus,
            [keyboards.SIMPLE_MENU_COMMANDS, keyboards.MENU_COMMANDS],
        )

    async def test_a_menu_that_will_not_update_is_not_an_error(self):
        """Cosmetic: every command works whether or not it is listed, so a failed swap
        must not take the persona switch down with it."""
        chat_bot = build_chat_bot(self, ui="simple")
        with mock.patch.object(chat_bot.bot, "set_my_commands",
                               side_effect=RuntimeError("flood wait")):
            await chat_bot._set_command_menu(True)


class SharedStateTest(unittest.TestCase):
    """What the process reads off itself, where a closure used to read a local name."""

    def test_the_push_chat_is_the_first_allowlisted_chat(self):
        """§4.3: the single-athlete instance model makes the first id the athlete."""
        chat_bot = build_chat_bot(self, allowed=(77, 42))
        self.assertEqual(chat_bot.push_chat_id, 77)

    def test_no_allowlist_means_no_push_chat(self):
        chat_bot = build_chat_bot(self, allowed=())
        self.assertIsNone(chat_bot.push_chat_id)

    def test_the_companion_wraps_far_past_any_real_line(self):
        """§6: the client flows the prose, so a phone-width wrap only adds ragged breaks."""
        self.assertEqual(build_chat_bot(self, ui="simple")._wrap_width(), 900)
        self.assertEqual(build_chat_bot(self, ui="expert")._wrap_width(), 48)

    def test_only_the_companion_attaches_the_reply_keyboard(self):
        self.assertIsNotNone(build_chat_bot(self, ui="simple")._keyboard())
        self.assertIsNone(build_chat_bot(self, ui="expert")._keyboard())


class GymKeyboardTest(unittest.TestCase):
    """The companion keyboard is built per send, so the gym button follows the week
    (DESIGN_gym_logger.md §6).

    Today is a gym day here, so the first row is the button that opens the page with
    today's session packed into its address."""

    BELT_SQUAT = {"exercise": "belt squat", "sets": 3, "reps_low": 4, "reps_high": 6,
                  "load_kg": 140.0}

    def setUp(self):
        self.db = bind_test_db(test_db_path("test_chat_process.db"))

    def a_gym_day(self, day):
        save_workout(
            self.db, date=day, sport_type="strength_training",
            title="Gym: lower body strength",
            description="Heavy lower body.\n\nBelt squat 3×4–6 @ 140 kg",
            prescribed_sets=[self.BELT_SQUAT],
        )

    def test_a_gym_day_puts_the_button_above_the_usual_labels(self):
        self.a_gym_day(clock.today_str())
        _kind, rows = build_chat_bot(self, ui="simple")._keyboard()
        label, url = rows[0][0]
        self.assertEqual(label, "🏋️ Log today's gym")
        self.assertTrue(url.startswith(logger.PAGE_URL + "#s="), url)
        self.assertEqual(rows[1:], keyboards.simple_keyboard_rows())

    def test_a_week_with_no_gym_day_keeps_the_plain_keyboard(self):
        _kind, rows = build_chat_bot(self, ui="simple")._keyboard()
        self.assertEqual(rows, keyboards.simple_keyboard_rows())

    def test_with_the_setting_off_there_is_no_button_and_no_database_read(self):
        self.a_gym_day(clock.today_str())
        settings.write(settings.STRENGTH_LOGGER, "off")
        chat_bot = build_chat_bot(self, ui="simple")
        with mock.patch.object(self.db, "get_workouts") as never:
            _kind, rows = chat_bot._keyboard()
        self.assertEqual(rows, keyboards.simple_keyboard_rows())
        never.assert_not_called()


class WebAppButtonTest(unittest.TestCase):
    """The gym button is the one reply-keyboard cell carrying an address, so it is drawn
    as a web-app button rather than a plain label (DESIGN_gym_logger.md §6)."""

    def test_a_label_and_url_pair_becomes_a_web_app_button(self):
        try:
            import telegram  # noqa: F401 -- only to skip where it is not installed
        except ImportError:
            self.skipTest("python-telegram-bot is not installed")
        markup = telegram_api.reply_keyboard(
            [[("🏋️ Log today's gym", "https://jlehen.github.io/Stamind/#s=e30")],
             ["📅 Today", "🗓 My week"]]
        )
        gym, plain = markup.keyboard[0][0], markup.keyboard[1][0]
        self.assertEqual(gym.text, "🏋️ Log today's gym")
        self.assertEqual(gym.web_app.url, "https://jlehen.github.io/Stamind/#s=e30")
        self.assertEqual(plain.text, "📅 Today")
        self.assertIsNone(plain.web_app)


class SendingTest(unittest.IsolatedAsyncioTestCase):
    """What `replies.py` puts into the chat for a running command."""

    def setUp(self):
        self.chat_bot = build_chat_bot(self, ui="expert")
        self.session = runner.Session(42, _FakeProc(), "n0nce")

    async def test_a_flush_sends_the_buffer_and_notes_the_anchor(self):
        sent = await self.chat_bot._flush_output(self.session, ["one", "two"])
        self.assertTrue(sent)
        self.assertEqual(self.chat_bot.bot.texts(), ["<pre>one\ntwo</pre>"])
        self.assertEqual(self.session.last_message_id, 101)
        self.assertTrue(self.session.sent)

    async def test_an_empty_buffer_sends_nothing(self):
        self.assertFalse(await self.chat_bot._flush_output(self.session, ["", "  "]))
        self.assertEqual(self.chat_bot.bot.sent, [])

    async def test_the_stop_button_is_hung_off_the_wait_notice_and_retired_by_the_next(self):
        """DESIGN_bot_stop_button.md §7: one live button per command, dropped as soon as
        anything arrives — the flush marker raises the next one."""
        await self.chat_bot._flush_output(self.session, ["Working on it…"])
        await self.chat_bot._offer_stop(self.session)
        self.assertEqual(self.session.stop_message_id, 101)
        rows = self.chat_bot.bot.edits[-1][2]
        self.assertEqual(rows[0][0][0], keyboards.STOP_LABEL)
        await self.chat_bot._flush_output(self.session, ["done"])
        self.assertIsNone(self.session.stop_message_id)
        self.assertIsNone(self.chat_bot.bot.edits[-1][2])

    async def test_an_offer_is_remembered_per_chat_and_attached_to_the_last_message(self):
        await self.chat_bot._flush_output(self.session, ["your week"])
        await self.chat_bot._send_ui_buttons(
            self.session, {"buttons": [{"label": "Too tired", "send": "status"}]}
        )
        token, buttons = self.chat_bot.ui_actions[42]
        self.assertEqual(buttons[0]["label"], "Too tired")
        self.assertEqual(self.chat_bot.bot.edits[-1][1], 101)
        self.assertEqual(self.chat_bot.bot.edits[-1][2][0][0][1],
                         keyboards.ui_callback_data(token, "0"))

    async def test_the_chart_is_sent_and_its_temp_file_unlinked(self):
        """§7.2: the CLI writes it with delete=False precisely so the bot owns cleanup."""
        handle = tempfile.NamedTemporaryFile(suffix=".png", delete=False)
        handle.write(b"png")
        handle.close()
        self.addCleanup(lambda: os.path.exists(handle.name) and os.unlink(handle.name))
        await self.chat_bot._send_photo(
            self.session, {"path": handle.name, "caption": "Fitness"}
        )
        self.assertEqual(self.chat_bot.bot.photos, [(42, "Fitness")])
        self.assertFalse(os.path.exists(handle.name))


def front_end_functions() -> dict:
    """Every function the Telegram front-end defines, name → source text.

    Keyed on the directory rather than a list of files, so a module written into
    `stamind/chat/` tomorrow is read tomorrow. Some invariants about the command loop
    are read from the source because reaching them needs a live Telegram connection."""
    paths = sorted(glob.glob(os.path.join(REPO, "stamind", "chat", "*.py")))
    paths.append(os.path.join(REPO, "stamind_bot.py"))
    found = {}
    for path in paths:
        source = pathlib.Path(path).read_text()
        for node in ast.walk(ast.parse(source)):
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                found[node.name] = ast.get_source_segment(source, node)
    return found


class PollingModelTest(unittest.TestCase):
    """Polling stays live while a command computes — the condition for a Stop tap or
    /cancel to reach a command waiting on the coach (DESIGN_bot_stop_button.md §5)."""

    def test_the_command_loop_never_stops_polling(self):
        self.assertNotIn("_pause_polling", front_end_functions()["_drive"])

    def test_only_the_restart_handler_stops_polling(self):
        """The long-poll is closed for exactly one reason: /restart is about to exit the
        process (DESIGN_bot_restart.md §5.2). Anything else that stops it strands the
        chat with a bot that has gone deaf."""
        callers = sorted(
            name for name, source in front_end_functions().items()
            if "_pause_polling" in source and name != "_pause_polling"
        )
        self.assertEqual(callers, ["_restart"])

    def test_the_re_arm_is_silent_and_only_the_re_arm_is(self):
        """§5.6: the tap's own answer is the feedback; a typed /ui still confirms. Read
        from the source so every call site is covered, not just the two driven above."""
        rearm, announced = [], []
        for source in front_end_functions().values():
            for node in ast.walk(ast.parse(source)):
                if not isinstance(node, ast.If):
                    continue
                stale = any(
                    _called_name(call) == "stale_keyboard_tap"
                    for call in ast.walk(node.test) if isinstance(call, ast.Call)
                )
                for call in ast.walk(node):
                    if not isinstance(call, ast.Call) or _called_name(call) != "_set_ui":
                        continue
                    silent = any(
                        kw.arg == "announce" and kw.value.value is False
                        for kw in call.keywords
                    )
                    (rearm if stale else announced).append(silent)
        self.assertEqual(rearm, [True])
        self.assertEqual(announced, [False])

    def test_a_failed_poll_is_reported_by_our_own_callback(self):
        self.assertIn("error_callback=self._on_polling_error", front_end_functions()["_serve"])

    def test_a_failed_poll_is_one_line_not_a_traceback(self):
        """A 502 from Telegram is retried by the library, so it is logged as one line."""
        class NetworkError(Exception):
            """Stands in for python-telegram-bot's, which the tests never import."""

        chat_bot = build_chat_bot(self)
        with mock.patch("stamind.chat.app.journal.record") as record, \
                mock.patch("stamind.chat.app.print", create=True) as printed:
            chat_bot._on_polling_error(NetworkError("Bad Gateway"))
        line = printed.call_args.args[0]
        self.assertIn("polling failed, retrying: NetworkError: Bad Gateway", line)
        self.assertEqual(printed.call_count, 1)
        record.assert_called_once()
        self.assertEqual(record.call_args.kwargs["lvl"], "warn")


def _called_name(call: ast.Call):
    """The name a call names, whether it is `f()` or `self.f()`."""
    func = call.func
    if isinstance(func, ast.Attribute):
        return func.attr
    return getattr(func, "id", None)



if __name__ == "__main__":
    unittest.main()
