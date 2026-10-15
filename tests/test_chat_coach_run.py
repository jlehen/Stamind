"""The long runs beside the chat (DESIGN_waiting_proposal.md §6,
DESIGN_long_runs_beside_chat.md).

A chat has two places: its own, which every command takes and which makes the chat busy,
and a second one for a long run: a `workout adapt` or a `workout tweak`, the morning run,
`workout generate --propose`. These cases drive a real `ChatBot` against the stand-ins in
`tests/chat_harness.py`, like `tests/test_chat_handlers.py`.
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
from stamind.chat import callbacks, keyboards, messages, replies, routing, runner, scheduler
from stamind.chat.routing import COACH_RUN, MORNING_RUN, PLANNING_RUN
from stamind.sentinels import PROMPT_SENTINEL

TIRED = ["workout", "adapt", "-m", "I'm tired"]


class LongRunTableTest(unittest.TestCase):
    """Which command lines are long runs, and so take the second place
    (DESIGN_long_runs_beside_chat.md §2)."""

    def test_the_long_runs_and_the_rest(self):
        cases = {
            ("bot", "morning"): MORNING_RUN,
            ("workout", "adapt", "-m", "I'm tired"): COACH_RUN,
            ("workout", "tweak", "move Saturday's ride"): COACH_RUN,
            ("workout", "generate", "--propose"): PLANNING_RUN,
            ("workout", "generate", "-m", "..7", "--propose"): PLANNING_RUN,
            ("workout", "generate"): None,
            ("workout", "list", "-d", "today"): None,
            ("bot", "queue", "7", "a1"): None,
        }
        for argv, run in cases.items():
            with self.subTest(argv=argv):
                self.assertEqual(routing.long_run(list(argv)), run)


class CoachRunTest(unittest.IsolatedAsyncioTestCase):
    """A long run works beside the chat, in a second place per chat
    (DESIGN_waiting_proposal.md §6, DESIGN_long_runs_beside_chat.md §2).

    It is Thursday 07:05 and the athlete has written "I'm tired": a `workout adapt` is
    alive in the second place of chat 42."""

    def thinking(self, chat_bot, awaiting=None, long=COACH_RUN):
        run = runner.Session(42, _FakeProc(), "c0ach", long=long)
        if awaiting is not None:
            run.awaiting = awaiting
            run.answer_future = asyncio.get_running_loop().create_future()
        chat_bot.long_runs[42] = run
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
            self.assertIs(chat_bot.long_runs[42], run)
            self.assertNotIn(42, chat_bot.sessions)
            await run.task
        self.assertEqual((chat_bot.long_runs, chat_bot.sessions), ({}, {}))

    async def test_show_my_week_answers_while_the_coach_thinks(self):
        chat_bot = build_chat_bot(self)
        started = record_commands(self, chat_bot)
        self.thinking(chat_bot)
        await self.say(chat_bot, "📅 Today")
        self.assertEqual(started, [(42, ["workout", "list", "-d", "today"], False, "bot")])

    async def test_the_next_message_to_the_coach_is_kept_while_it_thinks(self):
        """07:06 "move Saturday's ride to Sunday": no echo, one line, and it is kept
        (DESIGN_long_runs_beside_chat.md §7)."""
        chat_bot = build_chat_bot(self)
        started = record_commands(self, chat_bot)
        self.thinking(chat_bot)
        with routes_to(chat_bot, "tweak_session"):
            await self.say(chat_bot, "move Saturday's ride to Sunday")
        self.assertEqual(started, [])
        self.assertEqual(chat_bot.bot.texts(), [runner.KEPT_LINES[COACH_RUN]])
        self.assertEqual(chat_bot.kept[42], [
            (["workout", "tweak", "move Saturday's ride to Sunday"], False, COACH_RUN),
        ])

    async def test_it_is_not_kept_while_the_run_waits_on_a_question(self):
        chat_bot = build_chat_bot(self)
        started = record_commands(self, chat_bot)
        self.thinking(chat_bot, awaiting={"id": "p1", "type": "choose"})
        with routes_to(chat_bot, "coach_message"):
            await self.say(chat_bot, "and move Saturday's ride to Sunday")
        self.assertEqual(started, [])
        self.assertEqual(chat_bot.bot.texts(), [runner.COACH_ASKED])
        self.assertNotIn(42, chat_bot.kept)

    async def test_the_command_typed_with_a_slash_is_kept_the_same_way(self):
        chat_bot = build_chat_bot(self)
        started = record_commands(self, chat_bot)
        self.thinking(chat_bot)
        await self.say(chat_bot, "/workout adapt -m 'still tired'")
        self.assertEqual(started, [])
        self.assertEqual(chat_bot.bot.texts(), [runner.KEPT_LINES[COACH_RUN]])
        self.assertEqual(len(chat_bot.kept[42]), 1)

    async def test_a_button_that_sends_a_sentence_is_kept_and_spends_its_row(self):
        chat_bot = build_chat_bot(self)
        started = record_commands(self, chat_bot)
        self.thinking(chat_bot)
        buttons = [{"label": "😴 Feeling tired", "send": "workout adapt -m 'feeling tired'"}]
        chat_bot.ui_actions[42] = ("tok", buttons)
        query = _FakeQuery(keyboards.ui_callback_data("tok", "0"))
        await chat_bot.on_callback(callback_update(query), None)
        self.assertEqual(started, [])
        self.assertEqual(chat_bot.bot.texts(), [runner.KEPT_LINES[COACH_RUN]])
        self.assertEqual(query.markups, [None])
        self.assertNotIn(42, chat_bot.ui_actions)
        self.assertEqual(chat_bot.kept[42][0][0], ["workout", "adapt", "-m", "feeling tired"])

    async def test_a_button_is_refused_and_keeps_its_row_while_the_run_asks(self):
        chat_bot = build_chat_bot(self)
        record_commands(self, chat_bot)
        self.thinking(chat_bot, awaiting={"id": "p1", "type": "confirm"})
        buttons = [{"label": "😴 Feeling tired", "send": "workout adapt -m 'feeling tired'"}]
        chat_bot.ui_actions[42] = ("tok", buttons)
        query = _FakeQuery(keyboards.ui_callback_data("tok", "0"))
        await chat_bot.on_callback(callback_update(query), None)
        self.assertEqual(chat_bot.bot.texts(), [runner.COACH_ASKED])
        self.assertEqual(query.markups, [])
        self.assertIn(42, chat_bot.ui_actions)

    async def test_while_the_chat_is_busy_a_message_to_the_coach_gets_the_busy_line(self):
        """A command in the chat's own place, such as a gym log being read."""
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

    async def test_cancel_ends_the_command_in_both_places_and_drops_what_was_kept(self):
        chat_bot = build_chat_bot(self)
        run = self.thinking(chat_bot)
        own = runner.Session(42, _FakeProc(), "n0nce")
        chat_bot.sessions[42] = own
        chat_bot.kept[42] = [(TIRED, False, COACH_RUN)]
        replied = await self.say(chat_bot, "/cancel")
        self.assertEqual(replied[0][0], "Cancelling…")
        self.assertTrue(run.proc.killed and own.proc.killed)
        self.assertNotIn(42, chat_bot.kept)

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
        run = runner.Session(42, proc, "c0ach", long=COACH_RUN)
        chat_bot.long_runs[42] = run
        await chat_bot._drive(run)
        self.assertEqual(
            chat_bot.bot.texts(), ["Shall I remember it?", replies.PROMPT_TIMED_OUT]
        )
        self.assertEqual(chat_bot.long_runs, {})


class MorningRunTest(unittest.IsolatedAsyncioTestCase):
    """The morning run works beside the chat (DESIGN_long_runs_beside_chat.md §3, §7).

    It is Thursday 08:00. The bot starts `bot morning`, and the run asks the week planner
    before it writes the morning message."""

    def morning(self, chat_bot):
        run = runner.Session(42, _FakeProc(), "m0rn", quiet=True, long=MORNING_RUN)
        chat_bot.long_runs[42] = run
        return run

    async def say(self, chat_bot, text):
        update, replied = message_update(text=text)
        await chat_bot.on_message(update, SimpleNamespace(bot=chat_bot.bot))
        return replied

    async def test_a_keyboard_button_is_answered_at_once(self):
        """08:01 "✅ Done lately": the last days, at once."""
        chat_bot = build_chat_bot(self)
        started = record_commands(self, chat_bot)
        self.morning(chat_bot)
        await self.say(chat_bot, "✅ Done lately")
        self.assertEqual(
            started, [(42, ["workout", "compare", "-d", "7d", "--no-mark"], False, "bot")]
        )

    async def test_kept_messages_get_its_line_and_start_in_order_when_it_ends(self):
        """08:01 "I'm tired", 08:01:30 "and my knee hurts". At 08:02 the morning message is
        out, and the two messages start one after the other."""
        chat_bot = build_chat_bot(self)
        run = self.morning(chat_bot)
        with routes_to(chat_bot, "coach_message"):
            await self.say(chat_bot, "I'm tired")
            await self.say(chat_bot, "and my knee hurts")
        self.assertEqual(chat_bot.bot.texts(), [runner.KEPT_LINES[MORNING_RUN]] * 2)
        spawned = []

        async def spawn(*args, **_kwargs):
            spawned.append(args[-1])
            return _ScriptedProc(["Your coach says hello.\n"])

        run.proc = _ScriptedProc(["🏃 Today: Easy run — 40 min\n"])
        with mock.patch("asyncio.create_subprocess_exec", spawn):
            await chat_bot._drive(run)
            self.assertEqual(chat_bot.long_runs[42].long, COACH_RUN)
            await chat_bot.long_runs[42].task
        self.assertEqual(spawned, ["I'm tired", "and my knee hurts"])
        self.assertEqual((chat_bot.long_runs, chat_bot.kept), ({}, {}))

    async def test_plan_my_next_weeks_runs_beside_the_chat(self):
        chat_bot = build_chat_bot(self)
        buttons = [{"label": "📅 Plan my next weeks", "send": "workout generate --propose"}]
        chat_bot.ui_actions[42] = ("tok", buttons)

        async def spawn(*_args, **_kwargs):
            return _FakeProc()

        query = _FakeQuery(keyboards.ui_callback_data("tok", "0"))
        with mock.patch("asyncio.create_subprocess_exec", spawn), \
                mock.patch.object(chat_bot, "_drive", mock.AsyncMock()):
            await chat_bot.on_callback(callback_update(query), None)
        self.assertEqual(chat_bot.long_runs[42].long, PLANNING_RUN)
        self.assertNotIn(42, chat_bot.sessions)

    async def test_a_second_long_run_is_kept_while_the_weeks_are_planned(self):
        chat_bot = build_chat_bot(self)
        started = record_commands(self, chat_bot)
        chat_bot.long_runs[42] = runner.Session(42, _FakeProc(), "p1an", long=PLANNING_RUN)
        with routes_to(chat_bot, "coach_message"):
            await self.say(chat_bot, "I'm tired")
        self.assertEqual(started, [])
        self.assertEqual(chat_bot.bot.texts(), [runner.KEPT_LINES[PLANNING_RUN]])


class LongTapTest(unittest.IsolatedAsyncioTestCase):
    """A tap on a queued answer that starts a long run: "✅ Yes" under "Shall I pass it to
    your coach?" (DESIGN_long_runs_beside_chat.md §5, §6)."""

    DATA = keyboards.queue_callback_data(7, "a1")

    def tap(self, chat_bot):
        markup = SimpleNamespace(inline_keyboard=[[
            SimpleNamespace(text="✅ Yes", callback_data=self.DATA),
            SimpleNamespace(text="✖️ No", callback_data=keyboards.queue_callback_data(7, "a2")),
        ]])
        query = _FakeQuery(self.DATA, text="Shall I pass it to your coach?", markup=markup)
        return query, chat_bot.on_callback(callback_update(query), None)

    def starts_a_long_run(self):
        patcher = mock.patch.object(callbacks, "tap_long_run", return_value=COACH_RUN)
        patcher.start()
        self.addCleanup(patcher.stop)

    async def test_it_runs_beside_the_chat(self):
        chat_bot = build_chat_bot(self)
        self.starts_a_long_run()

        async def spawn(*_args, **_kwargs):
            return _FakeProc()

        query, tapped = self.tap(chat_bot)
        with mock.patch("asyncio.create_subprocess_exec", spawn), \
                mock.patch.object(chat_bot, "_drive", mock.AsyncMock()):
            await tapped
        run = chat_bot.long_runs[42]
        self.assertEqual((run.long, run.quiet), (COACH_RUN, True))
        self.assertNotIn(42, chat_bot.sessions)
        self.assertIn("→ ✅ Yes", query.edited_text)

    async def test_it_waits_like_any_tap_while_the_chat_is_busy(self):
        chat_bot = build_chat_bot(self)
        self.starts_a_long_run()
        started = record_commands(self, chat_bot)
        chat_bot.sessions[42] = runner.Session(42, _FakeProc(), "n0nce")
        query, tapped = self.tap(chat_bot)
        await tapped
        self.assertEqual(started, [])
        self.assertEqual(chat_bot.bot.texts(), [keyboards.BUSY_TAP])
        self.assertIsNone(query.edited_text)

    async def test_it_is_kept_while_the_morning_run_thinks(self):
        chat_bot = build_chat_bot(self)
        self.starts_a_long_run()
        started = record_commands(self, chat_bot)
        chat_bot.long_runs[42] = runner.Session(42, _FakeProc(), "m0rn", long=MORNING_RUN)
        query, tapped = self.tap(chat_bot)
        await tapped
        self.assertEqual(started, [])
        self.assertEqual(chat_bot.bot.texts(), [runner.KEPT_LINES[MORNING_RUN]])
        self.assertEqual(chat_bot.kept[42], [(["bot", "queue", "7", "a1"], True, COACH_RUN)])
        self.assertIn("→ ✅ Yes", query.edited_text)

    async def test_it_is_refused_and_keeps_its_buttons_while_the_run_alive_asks(self):
        chat_bot = build_chat_bot(self)
        self.starts_a_long_run()
        record_commands(self, chat_bot)
        alive = runner.Session(42, _FakeProc(), "c0ach", long=COACH_RUN)
        alive.awaiting = {"id": "p1", "type": "confirm"}
        chat_bot.long_runs[42] = alive
        query, tapped = self.tap(chat_bot)
        await tapped
        self.assertEqual(chat_bot.bot.texts(), [runner.COACH_ASKED])
        self.assertIsNone(query.edited_text)
        self.assertNotIn(42, chat_bot.kept)


if __name__ == "__main__":
    unittest.main()
