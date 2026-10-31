"""A typed reply is an answer (DESIGN_athlete_queue.md §14): what `bot route` is shown and
returns, what `bot queue --text` does with the words, and what the bot does with a pick."""
import json
import os
import unittest
from datetime import datetime, timedelta
from types import SimpleNamespace
from unittest import mock
from unittest.mock import MagicMock, patch

from tests import test_db_path
from tests.chat_harness import (
    build_chat_bot, callback_update, message_update, record_commands, routes_to, _FakeQuery,
)
from tests.helpers import clear_all_tables, rebind_test_db, run_cli, started_from

TEST_DB_PATH = test_db_path("test_typed_replies.db")

from stamind.db import Database
import stamind_cli  # noqa: F401 — the CLI binds its handles at import, before the rebind

from stamind import athlete_queue, cycle_records, retrospective_question, runtime
from stamind.chat import callbacks, keyboards, routing, runner, telegram_api
from stamind.clock import today_str
from stamind.db.retrospectives import FINISHED, MESOCYCLE

if os.path.exists(TEST_DB_PATH):
    os.remove(TEST_DB_PATH)
test_db = Database(db_path=TEST_DB_PATH)
rebind_test_db(test_db)


def tearDownModule():
    try:
        os.remove(TEST_DB_PATH)
    except OSError:
        pass


WEDNESDAY_8AM = datetime(2026, 9, 16, 8, 0).astimezone()


class _Case(unittest.TestCase):
    """A clean queue in the athlete's chat, a clock the test moves, and two kinds of its own:
    `sets` has a "Not now" and an answer that asks for words, `bare` has neither."""

    def setUp(self):
        rebind_test_db(test_db)
        clear_all_tables(test_db)
        test_db.set_setting("push_morning_time", "08:00")
        test_db.set_setting("push_evening_time", "21:00")
        self.now = WEDNESDAY_8AM
        moving_clock = patch("stamind.clock.now", side_effect=lambda: self.now)
        moving_clock.start()
        self.addCleanup(moving_clock.stop)
        self.stale = set()
        self.applied = []
        kinds = patch.dict(athlete_queue.KINDS, {
            "sets": athlete_queue.Kind(
                name="sets", shape=athlete_queue.QUESTION,
                wording=lambda item: f"{item['subject']}: what was it?",
                companion_wording=lambda item: f"Your {item['subject']}: what was it?",
                is_stale=lambda item: item["subject"] in self.stale,
                apply=self._apply, drop_label="leave it unnamed",
            ),
            "bare": athlete_queue.Kind(
                name="bare", shape=athlete_queue.QUESTION,
                wording=lambda item: "Shall I?", companion_wording=lambda item: "Shall I?",
                is_stale=lambda item: False, apply=self._apply, bare=True,
            ),
        })
        kinds.start()
        self.addCleanup(kinds.stop)
        started_from(self, "chat")
        self.addCleanup(runtime.reset, "prompt")

    def _apply(self, item, index, text):
        self.applied.append((item["id"], index, text))
        return f"Done with {item['subject']}."

    def ask(self, subject, sent=True):
        item_id = athlete_queue.queue("sets", subject, {"answers": [
            {"label": "belt squat"}, {"label": "something else…", "ask": "What was it?"},
        ]})
        if sent:
            test_db.mark_queue_sent(item_id, self.now)
        return item_id

    def ask_bare(self):
        item_id = athlete_queue.queue("bare", "one", {"answers": [{"label": "✅ Yes"}]})
        test_db.mark_queue_sent(item_id, self.now)
        return item_id

    def item(self, item_id):
        return test_db.get_queue_item(item_id)


class RouterTest(_Case):
    """`bot route`: which questions it shows, and what it does with the model's pick."""

    def route(self, reply, text="ok"):
        with patch(
            "stamind.openrouter.OpenRouterClient.complete", return_value=reply
        ) as complete:
            _, out, _ = run_cli(["bot", "route", text])
        return json.loads(out.strip().splitlines()[-1]), complete.call_args.args[1]

    def test_it_is_shown_a_live_question_with_its_buttons_and_the_later_choices(self):
        item_id = self.ask("A")
        _route, shown = self.route({"intent": "unclear"})
        self.assertIn(f"Question {item_id}:\nYour A: what was it?\n", shown)
        self.assertIn("- a1: Belt squat\n", shown)
        self.assertIn(
            "- a2: Something else… (asks for the athlete's words: What was it?)\n", shown
        )
        self.assertIn("- d: Leave it unnamed\n", shown)
        self.assertIn("- h: ⏰ In 1 hour\n- t: ⏰ Ask me tomorrow\n", shown)
        self.assertNotIn("Not now", shown)

    def test_it_is_not_shown_what_was_not_sent_put_off_or_stale_and_closes_nothing(self):
        unsent = self.ask("unsent", sent=False)
        put_off = self.ask("put off")
        test_db.set_queue_ready(put_off, self.now + timedelta(hours=1))
        stale = self.ask("stale")
        self.stale.add("stale")
        _route, shown = self.route({"intent": "unclear"})
        self.assertNotIn("Question", shown)
        self.assertIn("(none)", shown)
        for item_id in (unsent, put_off, stale):
            self.assertIsNone(self.item(item_id)["closed_at"], item_id)

    def test_the_newest_send_comes_first(self):
        first = self.ask("first")
        self.now += timedelta(minutes=5)
        second = self.ask("second")
        _route, shown = self.route({"intent": "unclear"})
        self.assertLess(shown.index(f"Question {second}:"), shown.index(f"Question {first}:"))

    def test_a_pick_outside_the_list_it_showed_is_no_answer(self):
        item_id = self.ask("A")
        unsent = self.ask("B", sent=False)
        for pick in (
            {"item": item_id + 100, "action": "a1"},
            {"item": unsent, "action": "a1"},
            {"item": item_id, "action": "a9"},
            {"item": item_id, "action": athlete_queue.QUEUE_NOT_NOW},
            "a1",
        ):
            route, _shown = self.route({"intent": "coach_message", "answer": pick})
            self.assertEqual(route, {"intent": "coach_message", "answer": None}, pick)

    def test_the_intent_answer_with_nothing_picked_is_unclear(self):
        route, _shown = self.route({"intent": "answer", "answer": None})
        self.assertEqual(route, {"intent": "unclear", "answer": None})

    def test_a_button_answer_comes_with_the_intent_answer(self):
        item_id = self.ask("A")
        route, _shown = self.route(
            {"intent": "coach_message", "answer": {"item": item_id, "action": "a1"}}
        )
        self.assertEqual(route, {"intent": "answer", "answer": {"item": item_id, "action": "a1"}})

    def test_a_words_answer_keeps_a_message_to_the_coach(self):
        item_id = self.ask("A")
        for intent in routing.ROUTER_MESSAGE_ARGV:
            route, _shown = self.route(
                {"intent": intent, "answer": {"item": item_id, "action": "a2"}}
            )
            self.assertEqual(route["intent"], intent)
            self.assertEqual(route["answer"], {"item": item_id, "action": "a2"})

    def test_any_other_intent_beside_a_words_answer_is_set_aside(self):
        """A `record_test` beside "Tell me the number" would run the capture a second time."""
        item_id = self.ask("A")
        route, _shown = self.route(
            {"intent": "record_test", "answer": {"item": item_id, "action": "a2"}}
        )
        self.assertEqual(route["intent"], "answer")

    def test_a_typed_drop_and_a_typed_tomorrow_are_buttons_like_the_rest(self):
        dropped, later = self.ask("dropped"), self.ask("later")
        for item_id, action in ((dropped, "d"), (later, "t")):
            route, _shown = self.route(
                {"intent": "unclear", "answer": {"item": item_id, "action": action}}
            )
            self.assertEqual(route, {"intent": "answer",
                                     "answer": {"item": item_id, "action": action}})
            run_cli(["bot", "queue", str(item_id), action])
        self.assertEqual(self.item(dropped)["outcome"], athlete_queue.DROPPED)
        self.assertIsNone(self.item(later)["sent_at"], "a put-off question is not live")
        self.assertEqual(athlete_queue.live_items(), [])

    def test_later_under_a_bare_question_answers_nothing(self):
        """No tap can put it off, so no message can."""
        item_id = self.ask_bare()
        route, shown = self.route(
            {"intent": "unclear", "answer": {"item": item_id, "action": "t"}}
        )
        self.assertEqual(route, {"intent": "unclear", "answer": None})
        self.assertNotIn("Ask me tomorrow", shown)


class BotQueueTextTest(_Case):
    """`bot queue <id> <action> --text`, and the tap on an answer that asks for words."""

    def setUp(self):
        super().setUp()
        runtime.prompt = MagicMock()

    def test_a_given_text_asks_nothing_and_is_stripped(self):
        item_id = self.ask("A")
        _, out, _ = run_cli(["bot", "queue", str(item_id), "a2", "--text", "  cable row "])
        runtime.prompt.ask_text.assert_not_called()
        self.assertEqual(self.applied, [(item_id, 1, "cable row")])
        self.assertIn("Done with A.", out)
        self.assertEqual(self.item(item_id)["outcome"], athlete_queue.ANSWERED)

    def test_a_message_that_opens_with_a_dash_stays_the_text(self):
        item_id = self.ask("A")
        run_cli(["bot", "queue", str(item_id), "a2", "--text=- cable row"])
        self.assertEqual(self.applied, [(item_id, 1, "- cable row")])

    def test_a_button_answer_ignores_the_text(self):
        item_id = self.ask("A")
        run_cli(["bot", "queue", str(item_id), "a1", "--text", "yes that one"])
        self.assertEqual(self.applied, [(item_id, 0, None)])

    def test_in_the_chat_a_tap_prints_the_question_and_ends(self):
        """07:05, the athlete taps "Something else…". The item stays out, so the line waits
        for the words, and the next message is routed like any other."""
        item_id = self.ask("A")
        other = self.ask("B", sent=False)
        self.now += timedelta(minutes=5)
        _, out, _ = run_cli(["bot", "queue", str(item_id), "a2"])
        runtime.prompt.ask_text.assert_not_called()
        self.assertEqual(out.strip(), "What was it?")
        self.assertEqual(self.applied, [])
        item = self.item(item_id)
        self.assertIsNone(item["closed_at"])
        self.assertTrue(athlete_queue.is_out(item, self.now))
        self.assertIsNone(self.item(other)["sent_at"], "the line waits for the words")
        self.assertEqual([i["id"] for i in athlete_queue.live_items()], [item_id])

    def test_a_terminal_keeps_its_prompt(self):
        started_from(self, "terminal")
        item_id = self.ask("A")
        runtime.prompt.choose.return_value = "a2"
        runtime.prompt.ask_text.return_value = "cable row"
        run_cli(["queue", "answer", str(item_id)])
        self.assertEqual(self.applied, [(item_id, 1, "cable row")])

    def test_an_empty_text_on_a_terminal_leaves_the_item_waiting(self):
        started_from(self, "terminal")
        item_id = self.ask("A")
        runtime.prompt.choose.return_value = "a2"
        runtime.prompt.ask_text.return_value = ""
        run_cli(["queue", "answer", str(item_id)])
        self.assertEqual(self.applied, [])
        self.assertIsNone(self.item(item_id)["closed_at"])


class RetrospectiveAnswerTest(_Case):
    """The athlete's words reach the record once, with the coach's run started beside the
    answer."""

    def setUp(self):
        super().setUp()
        goal = test_db.add_objective(
            title="Alpe", target_date="2026-12-01", sport_type="cycling", status="active",
        )
        self.record_id = test_db.add_retrospective(
            goal, MESOCYCLE, "Base", "2026-08-24", "2026-09-13", FINISHED, "aerobic base",
        )
        retrospective_question.ask_about(test_db.get_retrospective(self.record_id))
        [self.question] = test_db.waiting_queue_items()
        service = patch.object(runtime, "coach_service", MagicMock(), create=True)
        self.writer = service.start().write_retrospective
        self.addCleanup(service.stop)

    def _record(self):
        return test_db.get_retrospective(self.record_id)

    def _answer(self):
        return athlete_queue.act(self.question, "a1", "A bit too much.")

    def test_a_run_beside_the_writer_does_not_find_the_record_due(self):
        seen = {}

        def write(record, _wait_notice):
            seen["words in hand"] = record["athlete_words"]
            seen["due beside it"] = cycle_records.is_due(self._record(), today_str())
            test_db.write_retrospective(self.record_id, {}, "For: the lines.", "Thanks.")
            return "Thanks."

        self.writer.side_effect = write
        self.assertEqual(self._answer(), "Thanks.")
        self.assertEqual(
            seen, {"words in hand": "A bit too much.", "due beside it": False}
        )
        self.writer.assert_called_once()
        record = self._record()
        self.assertEqual(record["athlete_words"], "A bit too much.")
        self.assertFalse(cycle_records.is_due(record, today_str()))

    def test_a_failed_writer_leaves_the_words_alone_so_the_next_run_tries_again(self):
        self.writer.side_effect = ValueError("no api key")
        self.assertEqual(self._answer(), retrospective_question.THANKS_LINE)
        record = self._record()
        self.assertEqual(record["athlete_words"], "A bit too much.")
        self.assertTrue(cycle_records.is_due(record, today_str()))


class TypedAnswerInTheChatTest(unittest.IsolatedAsyncioTestCase):
    """What the bot does with a pick: the tap's path, then the coach lane for a words answer."""

    TEXT = "Honestly it is a bit too much."
    PAGE = telegram_api.PAGE_CELL + "https://example.org/details"

    def setUp(self):
        self.bot = build_chat_bot(self)
        self.started = record_commands(self, self.bot)

    async def _type(self, intent, item=12, action="a1", text=None):
        with routes_to(self.bot, intent, {"item": item, "action": action}):
            update, _replied = message_update(text=text or self.TEXT)
            await self.bot.on_message(update, SimpleNamespace(bot=self.bot.bot))

    async def _send_question(self, item=12, offer=None, page=None):
        await self.bot._send_queue_item(runner.Session(42, MagicMock(), "n0nce"), {
            "id": item, "text": "How did they go for you?",
            "buttons": [{"label": "Tell me", "action": "a1"},
                        {"label": "🕐 Not now", "action": "n"}],
            "offer": offer, "page": page,
        })
        return self.bot.bot.sent[-1]

    async def test_a_words_answer_runs_bot_queue_and_then_the_coach_lane(self):
        await self._type("coach_message")
        self.assertEqual(self.started, [
            (42, ["bot", "queue", "12", "a1", f"--text={self.TEXT}"], True, "bot"),
            (42, ["workout", "adapt", "-m", self.TEXT], False, "bot"),
        ])
        self.assertIn("passing that on to your coach", self.bot.bot.texts()[-1])

    async def test_a_button_answer_runs_bot_queue_alone(self):
        await self._type("answer", text="ok")
        self.assertEqual(
            self.started, [(42, ["bot", "queue", "12", "a1", "--text=ok"], True, "bot")]
        )
        self.assertEqual(self.bot.bot.texts(), [])

    async def test_no_answer_named_routes_as_before(self):
        with routes_to(self.bot, "coach_message"):
            update, _replied = message_update(text=self.TEXT)
            await self.bot.on_message(update, SimpleNamespace(bot=self.bot.bot))
        self.assertEqual(self.started, [(42, ["workout", "adapt", "-m", self.TEXT], False, "bot")])

    async def test_a_busy_chat_refuses_the_answer_and_the_coach_hears_nothing(self):
        """The chat was free when the message arrived, and something took its place while
        the router read it."""
        async def route(_text):
            self.bot.sessions[42] = object()
            return {"intent": "coach_message", "answer": {"item": 12, "action": "a1"}}

        with mock.patch.object(self.bot, "_route_intent", route):
            update, _replied = message_update(text=self.TEXT)
            await self.bot.on_message(update, SimpleNamespace(bot=self.bot.bot))
        self.assertEqual(self.started, [])
        self.assertEqual(self.bot.bot.texts(), [keyboards.BUSY_TAP])

    async def test_a_typed_answer_that_starts_a_long_run_takes_the_taps_path(self):
        with patch.object(callbacks, "tap_long_run", return_value=routing.COACH_RUN), \
                patch.object(self.bot, "_keep_behind", wraps=self.bot._keep_behind) as keep:
            await self._type("answer", text="yes")
        keep.assert_called_once()
        self.assertEqual(keep.call_args.kwargs, {"quiet": True, "run": routing.COACH_RUN})
        self.assertEqual(len(self.started), 1)

    async def test_the_answered_message_is_edited_as_after_a_tap(self):
        await self._send_question(page={"label": "🔎 Tell me more",
                                        "url": "https://example.org/details"})
        await self._type("answer")
        [(chat, message_id, text, markup)] = self.bot.bot.text_edits
        self.assertEqual((chat, message_id), (42, 101))
        self.assertEqual(text, "How did they go for you?\n\n→ Tell me")
        self.assertEqual(markup, [[("🔎 Tell me more", self.PAGE)]], "the page button stays")

    async def test_the_morning_offer_goes_with_the_answers(self):
        await self._send_question(offer=[{"label": "😴 Feeling tired", "send": "x"}])
        await self._type("answer")
        [(_chat, _message_id, _text, markup)] = self.bot.bot.text_edits
        self.assertIsNone(markup)

    async def test_a_typed_later_leaves_the_label_of_its_choice(self):
        await self._send_question()
        await self._type("answer", action="t")
        [(_chat, _message_id, text, _markup)] = self.bot.bot.text_edits
        self.assertEqual(text, "How did they go for you?\n\n→ ⏰ Ask me tomorrow")

    async def test_after_a_restart_nothing_is_remembered_and_the_answer_still_runs(self):
        await self._type("answer")
        self.assertEqual(self.bot.bot.text_edits, [])
        self.assertEqual(len(self.started), 1)

    async def test_a_tap_forgets_the_message_so_the_words_after_it_edit_nothing(self):
        """07:05 the athlete taps "Tell me", 07:09 they type their words: the message already
        shows "→ Tell me"."""
        await self._send_question()
        data = keyboards.queue_callback_data(12, "a1")
        markup = SimpleNamespace(inline_keyboard=[
            [SimpleNamespace(text="Tell me", callback_data=data)],
        ])
        query = _FakeQuery(data, text="How did they go for you?", markup=markup)
        await self.bot.on_callback(callback_update(query), None)
        self.assertEqual(query.edited_text, "How did they go for you?\n\n→ Tell me")
        await self._type("answer")
        self.assertEqual(self.bot.bot.text_edits, [])
        self.assertEqual(len(self.started), 2)


class RouteIntentTest(unittest.IsolatedAsyncioTestCase):
    """`_route_intent` hands back the whole object of `bot route`'s last JSON line."""

    def setUp(self):
        self.bot = build_chat_bot(self)

    async def _route(self, out):
        proc = MagicMock()
        proc.communicate = mock.AsyncMock(return_value=(out, b""))
        with patch("asyncio.create_subprocess_exec", mock.AsyncMock(return_value=proc)):
            return await self.bot._route_intent("ok")

    async def test_the_whole_object_comes_back(self):
        out = b'stray\n{"intent": "answer", "answer": {"item": 3, "action": "a1"}}\n'
        self.assertEqual(await self._route(out),
                         {"intent": "answer", "answer": {"item": 3, "action": "a1"}})

    async def test_nothing_readable_is_unclear(self):
        self.assertEqual(await self._route(b"stray\n"), {"intent": "unclear", "answer": None})


if __name__ == "__main__":
    unittest.main()
