"""The coach's run beside the chat (DESIGN_waiting_proposal.md §6).

A chat has two places: its own, which every command takes and which makes the chat busy,
and a second one for the coach's run, a `workout adapt` or a `workout tweak`. These cases
drive a real `ChatBot` against the stand-ins in `tests/chat_harness.py`, like
`tests/test_chat_handlers.py`.
"""
import asyncio
import json
import os
import sys
import unittest
from types import SimpleNamespace
from unittest import mock

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from tests.chat_harness import (
    _FakeProc, _FakeQuery, _ScriptedProc, build_chat_bot, callback_update, message_update,
    record_commands, routes_to,
)
from stamind.chat import keyboards, messages, replies, runner, scheduler
from stamind.sentinels import PROMPT_SENTINEL


class CoachRunTest(unittest.IsolatedAsyncioTestCase):
    """The coach's run works beside the chat, in a second place per chat
    (DESIGN_waiting_proposal.md §6).

    It is Thursday 07:05 and the athlete has written "I'm tired": a `workout adapt` is
    alive in the second place of chat 42."""

    def thinking(self, chat_bot, awaiting=None):
        run = runner.Session(42, _FakeProc(), "c0ach", coach=True)
        if awaiting is not None:
            run.awaiting = awaiting
            run.answer_future = asyncio.get_running_loop().create_future()
        chat_bot.coach_runs[42] = run
        return run

    async def say(self, chat_bot, text):
        update, replied = message_update(text=text)
        await chat_bot.on_message(update, SimpleNamespace(bot=chat_bot.bot))
        return replied

    async def test_a_message_to_the_coach_takes_the_second_place_and_frees_it(self):
        chat_bot = build_chat_bot(self)

        async def spawn(*_args, **_kwargs):
            return _ScriptedProc(["Your coach says hello.\n"])

        with mock.patch("asyncio.create_subprocess_exec", spawn):
            run = await chat_bot._start_command(42, ["workout", "adapt", "-m", "tired"])
            self.assertIs(chat_bot.coach_runs[42], run)
            self.assertNotIn(42, chat_bot.sessions)
            await run.task
        self.assertEqual((chat_bot.coach_runs, chat_bot.sessions), ({}, {}))

    async def test_show_my_week_answers_while_the_coach_thinks(self):
        chat_bot = build_chat_bot(self)
        started = record_commands(self, chat_bot)
        self.thinking(chat_bot)
        await self.say(chat_bot, "📅 Today")
        self.assertEqual(started, [(42, ["workout", "list", "-d", "today"], False, "bot")])

    async def test_the_next_message_to_the_coach_is_not_taken_while_it_thinks(self):
        """07:06 "move Saturday's ride to Sunday": no echo, one line, nothing starts."""
        chat_bot = build_chat_bot(self)
        started = record_commands(self, chat_bot)
        self.thinking(chat_bot)
        with routes_to(chat_bot, "tweak_session"):
            await self.say(chat_bot, "move Saturday's ride to Sunday")
        self.assertEqual(started, [])
        self.assertEqual(chat_bot.bot.texts(), [runner.COACH_THINKING])

    async def test_it_is_not_taken_either_while_the_run_waits_on_a_question(self):
        chat_bot = build_chat_bot(self)
        started = record_commands(self, chat_bot)
        self.thinking(chat_bot, awaiting={"id": "p1", "type": "choose"})
        with routes_to(chat_bot, "coach_message"):
            await self.say(chat_bot, "and move Saturday's ride to Sunday")
        self.assertEqual(started, [])
        self.assertEqual(chat_bot.bot.texts(), [runner.COACH_ASKED])

    async def test_the_command_typed_with_a_slash_is_refused_the_same_way(self):
        chat_bot = build_chat_bot(self)
        started = record_commands(self, chat_bot)
        self.thinking(chat_bot)
        await self.say(chat_bot, "/workout adapt -m 'still tired'")
        self.assertEqual(started, [])
        self.assertEqual(chat_bot.bot.texts(), [runner.COACH_THINKING])

    async def test_a_button_that_sends_a_sentence_is_refused_and_keeps_its_row(self):
        chat_bot = build_chat_bot(self)
        started = record_commands(self, chat_bot)
        self.thinking(chat_bot)
        buttons = [{"label": "😴 Feeling tired", "send": "workout adapt -m 'feeling tired'"}]
        chat_bot.ui_actions[42] = ("tok", buttons)
        query = _FakeQuery(keyboards.ui_callback_data("tok", "0"))
        await chat_bot.on_callback(callback_update(query), None)
        self.assertEqual(started, [])
        self.assertEqual(chat_bot.bot.texts(), [runner.COACH_THINKING])
        self.assertEqual(query.markups, [])
        self.assertIn(42, chat_bot.ui_actions)

    async def test_while_the_chat_is_busy_a_message_to_the_coach_gets_the_busy_line(self):
        """The morning push runs in the chat's own place."""
        chat_bot = build_chat_bot(self)
        started = record_commands(self, chat_bot)
        chat_bot.sessions[42] = runner.Session(42, _FakeProc(), "n0nce")
        replied = await self.say(chat_bot, "I'm tired")
        self.assertEqual(started, [])
        self.assertEqual(replied[0][0], messages.BUSY_NOTICE)

    async def test_a_tap_answers_the_question_the_coachs_run_asked(self):
        chat_bot = build_chat_bot(self)
        run = self.thinking(
            chat_bot, awaiting={"id": "p1", "type": "confirm", "message": "Cut short?"},
        )
        await chat_bot.on_callback(callback_update(_FakeQuery("c0ach:p1:y")), None)
        self.assertTrue(run.answer_future.result()["answer"])

    async def test_stop_ends_the_coachs_run_and_nothing_else(self):
        chat_bot = build_chat_bot(self)
        run = self.thinking(chat_bot)
        own = runner.Session(42, _FakeProc(), "n0nce")
        chat_bot.sessions[42] = own
        query = _FakeQuery(keyboards.stop_callback_data("c0ach"))
        await chat_bot.on_callback(callback_update(query), None)
        self.assertTrue(run.proc.killed)
        self.assertFalse(own.proc.killed)

    async def test_cancel_ends_the_command_in_both_places(self):
        chat_bot = build_chat_bot(self)
        run = self.thinking(chat_bot)
        own = runner.Session(42, _FakeProc(), "n0nce")
        chat_bot.sessions[42] = own
        replied = await self.say(chat_bot, "/cancel")
        self.assertEqual(replied[0][0], "Cancelling…")
        self.assertTrue(run.proc.killed and own.proc.killed)

    async def test_a_heads_up_waits_while_the_coachs_run_is_alive(self):
        chat_bot = build_chat_bot(self)
        started = record_commands(self, chat_bot)
        self.thinking(chat_bot)
        with mock.patch.object(scheduler.heads_up, "waiting", return_value=True):
            await chat_bot._tell_changes_first(42)
        self.assertEqual(started, [])

    async def test_an_unanswered_question_ends_the_run_with_one_line(self):
        """Five minutes without an answer: the bot says its line, and the command's own
        "Cancelled." is not sent after it."""
        chat_bot = build_chat_bot(self)
        chat_bot.prompt_timeout = 0.01
        question = {"v": 1, "id": "p1", "type": "confirm", "message": "Shall I remember it?"}
        proc = _ScriptedProc([PROMPT_SENTINEL + json.dumps(question) + "\n", "Cancelled.\n"])
        run = runner.Session(42, proc, "c0ach", coach=True)
        chat_bot.coach_runs[42] = run
        await chat_bot._drive(run)
        self.assertEqual(
            chat_bot.bot.texts(), ["Shall I remember it?", replies.PROMPT_TIMED_OUT]
        )
        self.assertEqual(chat_bot.coach_runs, {})


if __name__ == "__main__":
    unittest.main()
