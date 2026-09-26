"""What the bot does with what the athlete sends: a message, a tap, the gym logger's
page, or nothing at all.

A real `ChatBot` is built against the stand-ins in `tests/chat_harness.py` and driven
through `on_message`, `on_callback` and `on_web_app_data`. That is what these cases are
for: the persona, the allowlist, the live sessions, the armed chats and the row of buttons
a chat was last offered are attributes on one object, and a handler reading the wrong one
would still pass every test of the pure modules in `tests/test_bot.py`.
"""
import asyncio
import json
import os
import shutil
import sys
import tempfile
import unittest
from types import SimpleNamespace
from unittest import mock

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from tests.chat_harness import (
    _FakeProc, _FakeQuery, build_chat_bot, callback_update, message_update,
    record_commands, routes_to, web_app_update,
)
from stamind import clock
from stamind.chat import keyboards, messages, runner, scheduler
from stamind.config import config


class MessageHandlerTest(unittest.IsolatedAsyncioTestCase):
    """What `on_message` does with what the athlete typed."""

    async def test_an_unlisted_chat_is_refused_and_nothing_runs(self):
        chat_bot = build_chat_bot(self, allowed=(42,))
        started = record_commands(self, chat_bot)
        update, replied = message_update(chat_id=99, text="/status")
        await chat_bot.on_message(update, SimpleNamespace(bot=chat_bot.bot))
        self.assertEqual(started, [])
        self.assertIn("Not authorized", replied[0][0])
        self.assertIn("99", replied[0][0])

    async def test_start_answers_with_the_personas_own_card(self):
        for ui, card in (("simple", keyboards.SIMPLE_WELCOME), ("expert", keyboards.WELCOME)):
            chat_bot = build_chat_bot(self, ui=ui)
            record_commands(self, chat_bot)
            update, replied = message_update(text="/start")
            await chat_bot.on_message(update, SimpleNamespace(bot=chat_bot.bot))
            self.assertEqual(replied[0][0], card, ui)

    async def test_a_keyboard_label_runs_its_fixed_argv(self):
        chat_bot = build_chat_bot(self, ui="simple")
        started = record_commands(self, chat_bot)
        update, _replied = message_update(text="📅 Today")
        await chat_bot.on_message(update, SimpleNamespace(bot=chat_bot.bot))
        self.assertEqual(
            started, [(42, ["workout", "list", "-d", "today"], False, "bot")]
        )

    async def test_an_expert_message_is_a_command_line(self):
        chat_bot = build_chat_bot(self, ui="expert")
        started = record_commands(self, chat_bot)
        update, _replied = message_update(text='/workout adapt -m "tired today"')
        await chat_bot.on_message(update, SimpleNamespace(bot=chat_bot.bot))
        self.assertEqual(
            started, [(42, ["workout", "adapt", "-m", "tired today"], False, "bot")]
        )

    async def test_free_text_rides_the_router_and_says_where_it_went(self):
        chat_bot = build_chat_bot(self, ui="simple")
        started = record_commands(self, chat_bot)
        with routes_to(chat_bot, "show_progress"):
            update, _replied = message_update(text="how's it going")
            await chat_bot.on_message(update, SimpleNamespace(bot=chat_bot.bot))
        self.assertEqual(started, [(42, ["progress", "--chart"], False, "bot")])
        self.assertTrue(chat_bot.bot.texts()[0].startswith("<i>→ "))

    async def test_the_talk_to_me_tap_arms_the_chat_for_one_message(self):
        """§5.2: the tap only keeps an unroutable message from bouncing, and it is spent
        by the next message whether the router placed it or not."""
        chat_bot = build_chat_bot(self, ui="simple")
        started = record_commands(self, chat_bot)
        update, replied = message_update(text="💬 Talk to me")
        await chat_bot.on_message(update, SimpleNamespace(bot=chat_bot.bot))
        self.assertEqual(started, [])
        self.assertIn(42, chat_bot.armed)
        with routes_to(chat_bot, "unclear"):
            update, _replied = message_update(text="the boiler broke")
            await chat_bot.on_message(update, SimpleNamespace(bot=chat_bot.bot))
        self.assertEqual(
            started, [(42, ["bot", "capture", "note", "the boiler broke"], False, "bot")]
        )
        self.assertNotIn(42, chat_bot.armed)

    async def test_an_unroutable_message_without_the_tap_is_turned_away_gently(self):
        chat_bot = build_chat_bot(self, ui="simple")
        started = record_commands(self, chat_bot)
        with routes_to(chat_bot, "unclear"):
            update, _replied = message_update(text="the boiler broke")
            await chat_bot.on_message(update, SimpleNamespace(bot=chat_bot.bot))
        self.assertEqual(started, [])

    async def test_a_waiting_change_is_told_before_the_message_is_acted_on(self):
        """DESIGN_change_heads_up.md §4: it is the wiring that matters here — the helper
        has to be called from `on_message`, ahead of anything the message would start."""
        chat_bot = build_chat_bot(self, ui="expert")
        started = record_commands(self, chat_bot)
        with mock.patch.object(scheduler.heads_up, "waiting", return_value=True):
            update, _replied = message_update(text="/status")
            await chat_bot.on_message(update, SimpleNamespace(bot=chat_bot.bot))
        self.assertEqual(started, [
            (42, ["bot", "changes"], True, "push"), (42, ["status"], False, "bot"),
        ])

    async def test_a_second_command_is_refused_while_one_runs(self):
        chat_bot = build_chat_bot(self, ui="expert")
        chat_bot.sessions[42] = runner.Session(42, _FakeProc(), "n0nce")
        update, replied = message_update(text="/status")
        await chat_bot.on_message(update, SimpleNamespace(bot=chat_bot.bot))
        self.assertIn("still running", replied[0][0])

    async def test_cancel_with_nothing_running_says_so(self):
        chat_bot = build_chat_bot(self, ui="expert")
        update, replied = message_update(text="/cancel")
        await chat_bot.on_message(update, SimpleNamespace(bot=chat_bot.bot))
        self.assertEqual(replied[0][0], "Nothing to cancel.")

    async def test_cancel_kills_a_command_that_is_computing(self):
        chat_bot = build_chat_bot(self, ui="expert")
        session = runner.Session(42, _FakeProc(), "n0nce")
        chat_bot.sessions[42] = session
        update, replied = message_update(text="/cancel")
        await chat_bot.on_message(update, SimpleNamespace(bot=chat_bot.bot))
        self.assertEqual(replied[0][0], "Cancelling…")
        self.assertTrue(session.proc.killed)

    async def test_a_message_answers_an_open_text_prompt(self):
        chat_bot = build_chat_bot(self, ui="expert")
        session = runner.Session(42, _FakeProc(), "n0nce")
        session.awaiting = {"id": "p1", "type": "text"}
        session.answer_future = asyncio.get_running_loop().create_future()
        chat_bot.sessions[42] = session
        update, _replied = message_update(text="five sets of eight")
        await chat_bot.on_message(update, SimpleNamespace(bot=chat_bot.bot))
        self.assertEqual(session.answer_future.result()["answer"], "five sets of eight")


class PersonaSwitchTest(unittest.IsolatedAsyncioTestCase):
    """`/ui` flips the persona for the life of the process (§5.6), and every reader of it
    reads it again each time rather than holding the value it started with."""

    async def test_ui_expert_changes_what_the_next_message_gets(self):
        chat_bot = build_chat_bot(self, ui="simple")
        record_commands(self, chat_bot)
        update, _replied = message_update(text="/ui expert")
        await chat_bot.on_message(update, SimpleNamespace(bot=chat_bot.bot))
        self.assertFalse(chat_bot.simple_ui)
        self.assertEqual(chat_bot.bot.menus[-1], keyboards.MENU_COMMANDS)
        self.assertEqual(chat_bot.bot.sent[-1][2]["reply_markup"], "keyboard-removed")
        self.assertEqual(chat_bot._wrap_width(), 48)
        update, replied = message_update(text="/start")
        await chat_bot.on_message(update, SimpleNamespace(bot=chat_bot.bot))
        self.assertEqual(replied[0][0], keyboards.WELCOME)

    async def test_a_keyboard_tap_after_a_restart_into_expert_flips_back_silently(self):
        """§5.6: the keyboard lives on the phone and outlives the process that drew it,
        so the tap is the companion whatever persona this process started in."""
        chat_bot = build_chat_bot(self, ui="expert")
        started = record_commands(self, chat_bot)
        update, _replied = message_update(text="📅 Today")
        await chat_bot.on_message(update, SimpleNamespace(bot=chat_bot.bot))
        self.assertTrue(chat_bot.simple_ui)
        self.assertEqual(started, [(42, ["workout", "list", "-d", "today"], False, "bot")])
        # Silently: the answer to the tap is the only feedback the switch earns.
        self.assertEqual(chat_bot.bot.texts(), [])


class GymLogHandlerTest(unittest.IsolatedAsyncioTestCase):
    """The one message the gym logger's page sends (DESIGN_gym_logger.md §6).

    It is Thursday, 19:05, and the athlete has just tapped "Finish" in the gym. The bot
    keeps the message as a file and hands it to `strength ingest`; it never reads it
    itself, because every write goes through the CLI."""

    LOG = json.dumps({
        "v": 1, "r": 727, "d": "2026-09-24", "st": "18:02", "en": "19:05",
        "x": [{"n": "belt squat", "p": 1, "sets": [[5, 120, 40], [6, 140, 210]]}],
    })

    def setUp(self):
        self.data_dir = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, self.data_dir, True)
        patcher = mock.patch.dict(config.data, {"data_dir": self.data_dir})
        patcher.start()
        self.addCleanup(patcher.stop)

    def gym_logs(self):
        return os.path.join(self.data_dir, "gym_logs")

    async def test_the_log_is_written_to_a_file_the_ingest_is_then_given(self):
        chat_bot = build_chat_bot(self, ui="simple")
        started = record_commands(self, chat_bot)
        update, _replied = web_app_update(data=self.LOG)
        await chat_bot.on_web_app_data(update, SimpleNamespace(bot=chat_bot.bot))
        self.assertEqual(len(started), 1)
        chat_id, argv, quiet, source = started[0]
        self.assertEqual((chat_id, quiet, source), (42, False, "bot"))
        self.assertEqual(argv[:2], ["strength", "ingest"])
        self.assertEqual(os.path.dirname(argv[2]), self.gym_logs())
        self.assertTrue(argv[2].endswith(".json"), argv[2])
        self.assertTrue(os.path.basename(argv[2]).startswith(clock.today_str()), argv[2])
        with open(argv[2], encoding="utf-8") as handle:
            self.assertEqual(handle.read(), self.LOG)

    async def test_an_unlisted_chat_is_refused_and_nothing_is_written(self):
        chat_bot = build_chat_bot(self, allowed=(42,))
        started = record_commands(self, chat_bot)
        update, replied = web_app_update(chat_id=99, data=self.LOG)
        await chat_bot.on_web_app_data(update, SimpleNamespace(bot=chat_bot.bot))
        self.assertEqual(started, [])
        self.assertIn("Not authorized", replied[0][0])
        self.assertFalse(os.path.exists(self.gym_logs()))

    async def test_a_log_arriving_while_a_command_runs_is_told_to_wait(self):
        chat_bot = build_chat_bot(self, ui="simple")
        started = record_commands(self, chat_bot)
        chat_bot.sessions[42] = runner.Session(42, _FakeProc(), "n0nce")
        update, replied = web_app_update(data=self.LOG)
        await chat_bot.on_web_app_data(update, SimpleNamespace(bot=chat_bot.bot))
        self.assertEqual(started, [])
        self.assertEqual(replied[0][0], messages.BUSY_NOTICE)
        self.assertIsNotNone(replied[0][1]["reply_markup"])
        self.assertFalse(os.path.exists(self.gym_logs()))

    async def test_the_calendar_asks_for_a_day_and_writes_no_log(self):
        """Wednesday: the athlete taps Saturday in the calendar, then "💬 Full day in chat".
        The bot posts Saturday the way "📅 Today" writes a day
        (DESIGN_calendar_miniapp.md §6)."""
        chat_bot = build_chat_bot(self, ui="simple")
        started = record_commands(self, chat_bot)
        update, _replied = web_app_update(data='{"calendar_day": "2026-09-26"}')
        await chat_bot.on_web_app_data(update, SimpleNamespace(bot=chat_bot.bot))
        self.assertEqual([s[1] for s in started], [["workout", "list", "-d", "2026-09-26"]])
        self.assertFalse(os.path.exists(self.gym_logs()))


class CallbackHandlerTest(unittest.IsolatedAsyncioTestCase):
    """What `on_callback` does with a tap on each of the four button namespaces."""

    async def test_an_unlisted_chat_taps_and_nothing_happens(self):
        """The tap, not the message, is the one that reaches a command: an offer row
        survives on the phone, so the allowlist has to be checked on this path too."""
        chat_bot = build_chat_bot(self, allowed=(42,))
        started = record_commands(self, chat_bot)
        chat_bot.ui_actions[99] = ("tok", [{"label": "x", "send": "status"}])
        query = _FakeQuery(keyboards.ui_callback_data("tok", "0"))
        await chat_bot.on_callback(callback_update(query, chat_id=99), None)
        self.assertEqual(started, [])
        self.assertEqual(chat_bot.bot.sent, [])
        self.assertEqual(query.markups, [])

    async def test_a_prompt_answer_resolves_the_future_the_command_is_parked_on(self):
        chat_bot = build_chat_bot(self, ui="expert")
        session = runner.Session(42, _FakeProc(), "n0nce")
        session.awaiting = {"id": "p1", "type": "confirm", "message": "Proceed?"}
        session.answer_future = asyncio.get_running_loop().create_future()
        chat_bot.sessions[42] = session
        query = _FakeQuery("n0nce:p1:y")
        await chat_bot.on_callback(callback_update(query), None)
        self.assertTrue(session.answer_future.result()["answer"])
        self.assertEqual(query.edited_text, "Proceed?\n\n→ Yes")

    async def test_a_tap_from_a_replaced_session_is_dropped_not_answered(self):
        chat_bot = build_chat_bot(self, ui="expert")
        session = runner.Session(42, _FakeProc(), "newer")
        session.awaiting = {"id": "p1", "type": "confirm"}
        session.answer_future = asyncio.get_running_loop().create_future()
        chat_bot.sessions[42] = session
        query = _FakeQuery("stale:p1:y")
        await chat_bot.on_callback(callback_update(query), None)
        self.assertFalse(session.answer_future.done())
        self.assertEqual(query.markups, [None])

    async def test_a_stop_tap_ends_the_command_it_was_raised_for(self):
        chat_bot = build_chat_bot(self, ui="simple")
        session = runner.Session(42, _FakeProc(), "n0nce")
        chat_bot.sessions[42] = session
        query = _FakeQuery(keyboards.stop_callback_data("n0nce"))
        await chat_bot.on_callback(callback_update(query), None)
        self.assertTrue(session.proc.killed)
        self.assertIn(keyboards.STOP_DONE, chat_bot.bot.texts())

    async def test_a_stop_tap_left_over_from_a_finished_command_says_so(self):
        chat_bot = build_chat_bot(self, ui="simple")
        query = _FakeQuery(keyboards.stop_callback_data("gone"))
        await chat_bot.on_callback(callback_update(query), None)
        self.assertEqual(chat_bot.bot.texts(), [keyboards.STOP_ALREADY_DONE])

    async def test_an_offer_tap_runs_its_utterance_through_the_normal_pipeline(self):
        chat_bot = build_chat_bot(self, ui="simple")
        started = record_commands(self, chat_bot)
        buttons = [{"label": "Too tired", "send": "workout adapt -m 'too tired'"}]
        chat_bot.ui_actions[42] = ("tok", buttons)
        query = _FakeQuery(keyboards.ui_callback_data("tok", "0"))
        await chat_bot.on_callback(callback_update(query), None)
        self.assertEqual(
            started, [(42, ["workout", "adapt", "-m", "too tired"], False, "bot")]
        )
        self.assertNotIn(42, chat_bot.ui_actions)

    async def test_a_tap_on_a_row_a_newer_one_replaced_says_the_offer_expired(self):
        """§12.3: the message behind a retired offer was already consumed, so silence
        would lose it twice."""
        chat_bot = build_chat_bot(self, ui="simple")
        started = record_commands(self, chat_bot)
        chat_bot.ui_actions[42] = ("newer", [{"label": "x", "send": "status"}])
        query = _FakeQuery(keyboards.ui_callback_data("older", "0"))
        await chat_bot.on_callback(callback_update(query), None)
        self.assertEqual(started, [])
        self.assertEqual(chat_bot.bot.texts(), [keyboards.UI_STALE_TAP])

    async def test_a_queue_tap_runs_bot_queue_quietly_and_echoes_the_choice(self):
        chat_bot = build_chat_bot(self, ui="simple")
        started = record_commands(self, chat_bot)
        data = keyboards.queue_callback_data(12, "a2", "1789538400")
        markup = SimpleNamespace(inline_keyboard=[[
            SimpleNamespace(text="Leg press", callback_data=data),
        ]])
        query = _FakeQuery(data, text="🙋 What was it?", markup=markup)
        await chat_bot.on_callback(callback_update(query), None)
        self.assertEqual(started, [
            (42, ["bot", "queue", "12", "a2", "--since", "1789538400"], True, "bot"),
        ])
        self.assertEqual(query.edited_text, "🙋 What was it?\n\n→ Leg press")


class SchedulerDriverTest(unittest.IsolatedAsyncioTestCase):
    """What the scheduler's callbacks do once `ChatBot` supplies them."""

    async def test_a_scheduled_run_goes_to_the_push_chat_and_says_it_is_a_push(self):
        chat_bot = build_chat_bot(self, ui="simple", allowed=(77,))
        started = record_commands(self, chat_bot)
        await chat_bot._run_scheduled(["bot", "morning"], False)
        self.assertEqual(started, [(77, ["bot", "morning"], True, "push")])

    async def test_changes_waiting_are_told_before_the_athletes_own_message(self):
        """DESIGN_change_heads_up.md §4: whatever the hour, and however young the change."""
        chat_bot = build_chat_bot(self, ui="simple")
        started = record_commands(self, chat_bot)
        with mock.patch.object(scheduler.heads_up, "waiting", return_value=True):
            await chat_bot._tell_changes_first(42)
        self.assertEqual(started, [(42, ["bot", "changes"], True, "push")])

    async def test_a_chat_that_is_not_the_push_chat_is_told_nothing(self):
        chat_bot = build_chat_bot(self, ui="simple", allowed=(77,))
        started = record_commands(self, chat_bot)
        with mock.patch.object(scheduler.heads_up, "waiting", return_value=True):
            await chat_bot._tell_changes_first(42)
        self.assertEqual(started, [])

    async def test_a_busy_chat_keeps_its_place_in_the_queue(self):
        chat_bot = build_chat_bot(self, ui="simple")
        started = record_commands(self, chat_bot)
        chat_bot.sessions[42] = runner.Session(42, _FakeProc(), "n0nce")
        with mock.patch.object(scheduler.heads_up, "waiting", return_value=True):
            await chat_bot._tell_changes_first(42)
        self.assertEqual(started, [])

if __name__ == "__main__":
    unittest.main()
