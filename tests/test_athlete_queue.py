"""The athlete queue (DESIGN_athlete_queue.md): what is queued, the line, the actions,
what is out, and the terminal and chat surfaces that show them."""
import json
import os
import unittest
from datetime import datetime, timedelta
from unittest.mock import MagicMock, patch
from zoneinfo import ZoneInfo

from tests import test_db_path
from tests.helpers import clear_all_tables, rebind_test_db, run_cli, save_workout

TEST_DB_PATH = test_db_path("test_athlete_queue.db")

from stamind.db import Database
import stamind_cli  # noqa: F401 — the CLI binds its handles at import, before the rebind

from stamind import athlete_queue, clock, runtime
from stamind.cli import queue as queue_cli
from stamind.coach.proposals import RevisionProposal
from stamind.sentinels import BUTTONS_SENTINEL, QUEUE_SENTINEL
from stamind.athlete_queue import QUEUE_LATER_BACK, QUEUE_LATER_DAY, QUEUE_LATER_HOUR
from stamind.clock import today_str
from stamind import cycle_records, retrospective_question

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


def queue_lines(out):
    """The SM-QUEUE payloads a run wrote, in order. Split on newlines only:
    `str.splitlines` also breaks on the sentinel's own \\x1e."""
    return [json.loads(line[len(QUEUE_SENTINEL):]) for line in out.split("\n")
            if line.startswith(QUEUE_SENTINEL)]


def ids(items):
    return [item["id"] for item in items]


class _Prompt:
    """Stands in for the prompt transport: picks what the script says, types `typed`."""

    def __init__(self, picks=(), typed=""):
        self.picks = list(picks)
        self.typed = typed
        self.shown = []

    def choose(self, message, choices, *, default=None):
        self.shown.append((message, [c.label for c in choices], default))
        return self.picks.pop(0) if self.picks else default

    def ask_text(self, message, *, secret=False, default=None):
        return self.typed

    def confirm(self, message, *, default=False, danger=False):
        return default


class _QueueCase(unittest.TestCase):
    """A clean queue, a clock the test moves, and a question kind of its own: `message` is
    the only kind this change ships, and the queue must not care which kind it holds (§8)."""

    def setUp(self):
        rebind_test_db(test_db)
        clear_all_tables(test_db)
        test_db.set_setting("push_morning_time", "08:00")
        self.now = WEDNESDAY_8AM
        moving_clock = patch("stamind.clock.now", side_effect=lambda: self.now)
        moving_clock.start()
        self.addCleanup(moving_clock.stop)
        self.stale = set()
        self.refused = set()
        self.applied = []
        kinds = patch.dict(athlete_queue.KINDS, {"sets": athlete_queue.Kind(
            name="sets", shape=athlete_queue.QUESTION,
            wording=lambda item: f"{item['subject']}: what was it?",
            companion_wording=lambda item: f"Your {item['subject']} — what was it?",
            is_stale=lambda item: item["subject"] in self.stale,
            apply=self._apply, drop_label="leave it unnamed",
        )})
        kinds.start()
        self.addCleanup(kinds.stop)
        self.addCleanup(runtime.reset, "prompt")

    def _apply(self, item, index, text):
        if item["subject"] in self.refused:
            raise athlete_queue.NotApplied("Couldn't reach Garmin.")
        self.applied.append((item["id"], index, text))
        name = text or item["payload"]["answers"][index]["label"]
        return f"Named {item['subject']}: {name}."

    def at(self, hour, minute=0, days=0):
        self.now = WEDNESDAY_8AM.replace(hour=hour, minute=minute) + timedelta(days=days)
        return self.now

    def ask(self, subject, answers=("belt squat", "leg press")):
        offered = [{"label": label} for label in answers]
        offered.append({"label": "something else…", "ask": "What was it?"})
        return athlete_queue.queue("sets", subject, {"answers": offered})

    def item(self, item_id):
        return test_db.get_queue_item(item_id)


class WhatIsQueuedTest(_QueueCase):
    def test_a_subject_is_queued_once_even_after_a_drop(self):
        first = self.ask("block 1")
        self.assertIsNotNone(first)
        self.assertIsNone(self.ask("block 1"))
        athlete_queue.act(self.item(first), athlete_queue.DROP)
        self.assertEqual(self.item(first)["outcome"], athlete_queue.DROPPED)
        self.assertIsNone(self.ask("block 1"), "a drop is remembered")
        self.assertIsNotNone(self.ask("block 2"))

    def test_the_same_words_told_twice_are_two_messages(self):
        first = athlete_queue.tell("Charge your watch.")
        self.at(8, 1)
        second = athlete_queue.tell("Charge your watch.")
        self.assertIsNotNone(second)
        self.assertNotEqual(first, second)
        self.assertEqual(athlete_queue.waiting_counts(), (0, 2))

    def test_answers_are_fixed_when_the_item_is_queued(self):
        """A button tapped later means what it meant when it was shown (§3): the item keeps
        the answers it was queued with, whatever order a later question offers."""
        first = self.ask("block 1", answers=("belt squat", "leg press"))
        self.ask("block 2", answers=("leg press", "belt squat"))
        _, buttons = queue_cli.queue_chat_message(self.item(first), left=2)
        self.assertEqual([b["label"] for b in buttons[:2]], ["Belt squat", "Leg press"])
        athlete_queue.act(self.item(first), "a2")
        self.assertEqual(self.applied, [(first, 1, None)])
        self.assertEqual(self.item(first)["outcome"], athlete_queue.ANSWERED)

    def test_an_action_the_item_was_not_queued_with_writes_nothing(self):
        """A button can only run one of the answers its item was queued with (§9)."""
        question, message = self.ask("block 1"), athlete_queue.tell("Charge your watch.")
        for action in ("a9", "a0", "a", "x"):
            athlete_queue.act(self.item(question), action)
        athlete_queue.act(self.item(message), athlete_queue.DROP)
        self.assertEqual(self.applied, [])
        self.assertEqual(ids(test_db.waiting_queue_items()), [question, message])


class LineTest(_QueueCase):
    """The line is the waiting items whose ready time has passed, the earliest first
    (§13.2 rules 1 and 2)."""

    def test_a_new_item_is_ready_from_the_moment_it_is_queued(self):
        item = self.item(self.ask("A"))
        self.assertEqual(item["ready_at"], item["queued_at"])
        self.assertEqual(ids(athlete_queue.line()), [item["id"]])

    def test_the_order_is_the_order_things_became_ready(self):
        a, b, c = self.ask("A"), self.ask("B"), self.ask("C")
        self.assertEqual(ids(athlete_queue.line()), [a, b, c])

    def test_an_item_put_off_stands_behind_what_became_ready_before_its_time(self):
        """08:05 "In 1 hour" on A. B is queued at 08:30. At 09:05 A is ready again, and
        it does not take its old place back."""
        a = self.ask("A")
        self.at(8, 5)
        athlete_queue.act(self.item(a), QUEUE_LATER_HOUR)
        self.at(8, 30)
        b = self.ask("B")
        self.at(9, 4)
        self.assertEqual(ids(athlete_queue.line()), [b])
        self.at(9, 5)
        self.assertEqual(ids(athlete_queue.line()), [b, a])

    def test_a_later_choice_never_rewrites_the_time_an_item_was_queued(self):
        a = self.ask("A")
        queued = self.item(a)["queued_at"]
        self.at(8, 5)
        for action in (QUEUE_LATER_HOUR, QUEUE_LATER_DAY, QUEUE_LATER_BACK):
            athlete_queue.act(self.item(a), action)
            self.assertEqual(self.item(a)["queued_at"], queued, action)
            self.assertNotEqual(self.item(a)["ready_at"], queued, action)

    def test_after_the_others_puts_an_item_last_in_the_line(self):
        a, b, c = self.ask("A"), self.ask("B"), self.ask("C")
        self.at(8, 5)
        athlete_queue.act(self.item(a), QUEUE_LATER_BACK)
        self.assertEqual(ids(athlete_queue.line()), [b, c, a])

    def test_what_a_command_queues_is_ready_when_the_command_ends(self):
        """The push queues its questions while it runs and sends from the line at its end:
        they are dated by the command's start (§3)."""
        clock.start_command()
        self.addCleanup(clock.end_command)
        self.at(8, 1)
        item_id = self.ask("queued by the push")
        self.assertEqual(ids(athlete_queue.line()), [item_id])

    def test_an_expired_item_is_closed_without_being_shown(self):
        gone, kept = self.ask("gone"), self.ask("kept")
        self.stale.add("gone")
        self.assertEqual(ids(athlete_queue.line()), [kept])
        self.assertEqual(self.item(gone)["outcome"], athlete_queue.STALE)


class LaterTest(_QueueCase):
    def ready(self, item_id):
        return clock.to_local(
            datetime.fromisoformat(self.item(item_id)["ready_at"])
        ).strftime("%a %H:%M")

    def test_tomorrow_is_the_next_days_morning_time_whatever_the_hour_of_the_tap(self):
        """Wednesday 08:01 and Wednesday 21:30 both mean Thursday 08:00. A tap at 00:30 on
        Thursday means Friday (§13.5)."""
        early, late, night = self.ask("early"), self.ask("late"), self.ask("night")
        self.at(8, 1)
        athlete_queue.act(self.item(early), QUEUE_LATER_DAY)
        self.at(21, 30)
        athlete_queue.act(self.item(late), QUEUE_LATER_DAY)
        self.at(0, 30, days=1)
        athlete_queue.act(self.item(night), QUEUE_LATER_DAY)
        self.assertEqual(
            [self.ready(item_id) for item_id in (early, late, night)],
            ["Thu 08:00", "Thu 08:00", "Fri 08:00"],
        )

    def test_tomorrow_follows_the_athletes_own_morning_time(self):
        test_db.set_setting("push_morning_time", "06:30")
        item_id = self.ask("A")
        athlete_queue.act(self.item(item_id), QUEUE_LATER_DAY)
        self.assertEqual(self.ready(item_id), "Thu 06:30")

    def test_an_item_put_off_is_hidden_until_its_ready_time(self):
        item_id = self.ask("block 5")
        self.at(8, 5)
        athlete_queue.act(self.item(item_id), QUEUE_LATER_HOUR)
        self.at(9, 0)
        self.assertEqual(athlete_queue.line(), [])
        self.assertEqual(athlete_queue.waiting_counts(), (0, 0))
        self.assertFalse(athlete_queue.next_due())
        self.at(9, 5)
        self.assertTrue(athlete_queue.next_due())
        self.assertEqual(athlete_queue.waiting_counts(), (1, 0))

    def test_an_answer_that_could_not_be_applied_waits_for_the_next_morning(self):
        item_id = self.ask("A")
        self.refused.add("A")
        self.assertEqual(athlete_queue.act(self.item(item_id), "a1"), "Couldn't reach Garmin.")
        self.assertIsNone(self.item(item_id)["closed_at"])
        self.assertEqual(self.ready(item_id), "Thu 08:00")


class OutTest(_QueueCase):
    """One item at a time: an item is out from its send to its tap, and at the latest until
    the next morning time. A wake of the scheduler sends in the daytime only (§13.2 rules
    3, 4 and 5)."""

    def test_an_item_is_out_from_its_send_to_its_tap(self):
        a = self.ask("A")
        self.assertFalse(athlete_queue.anything_out())
        athlete_queue.sent(self.item(a))
        self.assertTrue(athlete_queue.anything_out())
        athlete_queue.act(self.item(a), "a1")
        self.assertFalse(athlete_queue.anything_out())

    def test_putting_an_item_off_ends_its_turn(self):
        a = self.ask("A")
        athlete_queue.sent(self.item(a))
        athlete_queue.act(self.item(a), QUEUE_LATER_HOUR)
        self.assertFalse(athlete_queue.anything_out())

    def test_nothing_counts_as_out_at_the_next_morning_time(self):
        a = self.ask("A")
        self.at(8, 5)
        athlete_queue.sent(self.item(a))
        for hour, minute, days, out in ((23, 0, 0, True), (7, 59, 1, True), (8, 0, 1, False)):
            self.at(hour, minute, days)
            self.assertEqual(athlete_queue.anything_out(), out, (hour, minute, days))

    def test_a_wake_sends_between_the_morning_time_and_the_evening_only(self):
        """A question the nightly reflect queues at 03:00 waits for 08:00, and nothing
        goes out on its own from 21:00 on."""
        self.at(3)
        self.ask("A")
        for hour, minute, due in (
            (3, 0, False), (7, 59, False), (8, 0, True), (20, 59, True), (21, 0, False),
        ):
            self.at(hour, minute)
            self.assertEqual(athlete_queue.next_due(), due, (hour, minute))

    def test_a_wake_sends_nothing_while_an_item_is_out(self):
        a = self.ask("A")
        self.ask("B")
        self.at(9)
        athlete_queue.sent(self.item(a))
        self.assertFalse(athlete_queue.next_due())
        athlete_queue.act(self.item(a), "a1")
        self.assertTrue(athlete_queue.next_due())

    def test_a_wake_with_nothing_ready_sends_nothing(self):
        self.at(9)
        self.assertFalse(athlete_queue.next_due())


class ChatTest(_QueueCase):
    """Under the bot every item goes out as a SM-QUEUE line, and a tap runs `bot queue`."""

    def setUp(self):
        super().setUp()
        env = patch.dict(os.environ, {"STAMIND_FRONTEND": "json"})
        env.start()
        self.addCleanup(env.stop)

    def tap(self, item_id, action):
        return run_cli(["bot", "queue", str(item_id), action])

    def step(self):
        """What a wake of the bot's scheduler runs when the line has something to send."""
        _code, out, _err = run_cli(["bot", "queue", "--next"])
        return out

    def test_one_item_goes_out_at_a_time_and_the_last_tap_gets_the_thanks(self):
        a, b = self.ask("A"), self.ask("B")
        [first] = queue_lines(self.step())
        self.assertEqual(first["id"], a)
        self.assertIn("(2 left)", first["text"])
        self.assertEqual(sorted(first), ["buttons", "id", "text"])
        # A is out: a second wake sends nothing.
        self.assertEqual(queue_lines(self.step()), [])
        _, out, _ = self.tap(a, "a1")
        self.assertIn("Named A: belt squat.", out)
        [second] = queue_lines(out)
        self.assertEqual(second["id"], b)
        self.assertIn("(1 left)", second["text"])
        _, out, _ = self.tap(b, athlete_queue.DROP)
        self.assertEqual(queue_lines(out), [])
        self.assertIn(queue_cli.QUEUE_DONE_LINE, out)

    def test_a_step_that_finds_nothing_sends_nothing(self):
        out = self.step()
        self.assertEqual(queue_lines(out), [])
        self.assertNotIn(queue_cli.QUEUE_DONE_LINE, out)

    def test_typed_in_the_chat_queue_answer_sends_the_first_item_whatever_is_out(self):
        _, out, _ = run_cli(["queue", "answer"])
        self.assertIn(queue_cli.NOTHING_WAITING_LINE, out)
        a = self.ask("A")
        self.ask("B")
        self.step()
        _, out, _ = run_cli(["queue", "answer"])
        self.assertEqual(ids(queue_lines(out)), [a])

    def test_a_tap_on_a_settled_item_says_so_and_moves_on(self):
        a, b = self.ask("A"), self.ask("B")
        athlete_queue.act(self.item(a), "a1")  # another copy was tapped first
        _, out, _ = self.tap(a, "a2")
        self.assertIn(queue_cli.QUEUE_SETTLED_LINE, out)
        self.assertEqual(len(self.applied), 1)
        self.assertEqual(ids(queue_lines(out)), [b])

    def test_an_expired_item_is_closed_on_its_tap(self):
        a = self.ask("A")
        self.step()
        self.stale.add("A")
        _, out, _ = self.tap(a, "a1")
        self.assertIn(queue_cli.QUEUE_SETTLED_LINE, out)
        self.assertEqual(self.applied, [])
        self.assertEqual(self.item(a)["outcome"], athlete_queue.STALE)

    def test_in_1_hour_means_at_least_one_hour(self):
        """08:05 the first question is put off for an hour and the second arrives at once.
        At 09:05 the first is ready again, behind the second, which is out. It is sent
        when the second is answered, and its tap empties the line (§13.2 rule 3)."""
        a, b = self.ask("A"), self.ask("B")
        self.step()
        self.at(8, 5)
        _, out, _ = self.tap(a, QUEUE_LATER_HOUR)
        self.assertEqual(ids(queue_lines(out)), [b])
        self.at(9, 5)
        self.assertFalse(athlete_queue.next_due())
        self.assertEqual(queue_lines(self.step()), [])
        self.at(18, 30)
        _, out, _ = self.tap(b, "a1")
        [back] = queue_lines(out)
        self.assertEqual(back["id"], a)
        self.assertTrue(back["text"].startswith("⏰ You asked me to come back to this:"))
        _, out, _ = self.tap(a, "a1")
        self.assertEqual(queue_lines(out), [])
        self.assertIn(queue_cli.QUEUE_DONE_LINE, out)

    def test_a_tap_at_night_brings_the_next_item_at_once(self):
        a, b = self.ask("A"), self.ask("B")
        self.step()
        self.at(23, 30)
        self.assertFalse(athlete_queue.next_due())
        _, out, _ = self.tap(a, "a1")
        self.assertEqual(ids(queue_lines(out)), [b])

    def test_an_unanswered_item_comes_back_the_next_morning_and_not_before(self):
        a = self.ask("A")
        self.ask("B")
        self.step()
        self.at(20)
        self.assertEqual(queue_lines(self.step()), [])
        self.at(8, days=1)
        [again] = queue_lines(self.step())
        self.assertEqual(again["id"], a)
        self.assertIn("(2 left)", again["text"])

    def test_an_answer_that_could_not_be_applied_lets_the_next_one_go(self):
        a, b = self.ask("A"), self.ask("B")
        self.refused.add("A")
        self.step()
        _, out, _ = self.tap(a, "a1")
        self.assertIn("Couldn't reach Garmin.", out)
        self.assertEqual(ids(queue_lines(out)), [b])

    def test_a_chat_message_has_no_skip(self):
        """Skip and "after the others" differ in a way she cannot see (§6.4)."""
        self.ask("A")
        [sent] = queue_lines(self.step())
        self.assertEqual([b["action"] for b in sent["buttons"]], ["a1", "a2", "a3", "d", "n"])
        self.assertEqual(sent["text"], "🙋 Quick question (1 left)\nYour A — what was it?")
        self.assertEqual([b["label"] for b in sent["buttons"]][3:],
                         ["Leave it unnamed", "🕐 Not now"])

    def test_a_typed_answer_asks_for_its_text(self):
        item_id = self.ask("A")
        runtime.prompt = _Prompt(typed="cable row")
        _, out, _ = self.tap(item_id, "a3")
        self.assertEqual(self.applied, [(item_id, 2, "cable row")])
        self.assertIn("Named A: cable row.", out)

    def test_an_empty_typed_answer_leaves_the_item_waiting(self):
        item_id = self.ask("A")
        runtime.prompt = _Prompt(typed="")
        self.tap(item_id, "a3")
        self.assertEqual(self.applied, [])
        self.assertIsNone(self.item(item_id)["closed_at"])


class MorningTest(_QueueCase):
    """`bot morning` ends by sending the first item of the line (§13.2 rule 4)."""

    def setUp(self):
        super().setUp()
        garmin = patch.object(runtime, "garmin", MagicMock(), create=True)
        garmin.start()
        self.addCleanup(garmin.stop)
        env = patch.dict(os.environ, {"STAMIND_FRONTEND": "json", "STAMIND_RENDER": "simple"})
        env.start()
        self.addCleanup(env.stop)
        test_db.set_setting("push_adapt_first", "off")

    def test_the_first_item_follows_the_briefing_and_its_buttons(self):
        save_workout(test_db, today_str(), "running", "Easy run", description="40 min.",
                     duration_minutes=40)
        athlete_queue.tell("Charge your watch tonight.")
        code, out, _ = run_cli(["bot", "morning"])
        self.assertEqual(code, 0)
        lines = out.split("\n")
        buttons = next(i for i, line in enumerate(lines) if line.startswith(BUTTONS_SENTINEL))
        queued = next(i for i, line in enumerate(lines) if line.startswith(QUEUE_SENTINEL))
        self.assertLess(buttons, queued)
        [item] = queue_lines(out)
        self.assertEqual(item["text"], "📬 Charge your watch tonight.")
        self.assertEqual([b["label"] for b in item["buttons"]], ["👍 Got it", "🕐 Not now"])

    def test_what_was_left_unanswered_follows_the_next_mornings_briefing(self):
        for day in (0, 1):
            save_workout(test_db, clock.shift(today_str(), day), "running", "Easy run",
                         duration_minutes=40)
        athlete_queue.tell("Charge your watch tonight.")
        _, out, _ = run_cli(["bot", "morning"])
        self.assertEqual(len(queue_lines(out)), 1)
        self.at(8, days=1)
        _, out, _ = run_cli(["bot", "morning"])
        [again] = queue_lines(out)
        self.assertEqual(again["text"], "📬 Charge your watch tonight.")

    def test_a_test_done_without_a_result_is_asked_about_once(self):
        """The morning after a planned test graded done, with no result in the logbook
        (DESIGN_benchmark_from_chat.md §4). A missed test and one with a result are not."""
        save_workout(test_db, today_str(), "running", "Easy run", duration_minutes=40)
        done = save_workout(test_db, "2026-09-15", "cycling", "20-min FTP test",
                            benchmark_type="ftp_20min")
        missed = save_workout(test_db, "2026-09-14", "running", "30-min threshold test",
                              benchmark_type="run_threshold_30min")
        recorded = save_workout(test_db, "2026-09-13", "swimming", "CSS test",
                                benchmark_type="css_400_200")
        test_db.add_benchmark_result(date="2026-09-13", sport_type="swimming",
                                     anchor_kind="css", value=105.0, unit="sec/100m")
        verdicts = {done: {"status": "done"}, missed: {"status": "missed"},
                    recorded: {"status": "done"}}
        with patch("stamind.cli.bot.views.adherence_verdicts", return_value=verdicts):
            _, out, _ = run_cli(["bot", "morning"])
            run_cli(["bot", "morning", "--force"])
        [item] = test_db.waiting_queue_items()
        self.assertEqual((item["kind"], item["subject"]), ("test_result", str(done)))
        [sent] = queue_lines(out)
        self.assertIn("How did Tuesday's “20-min FTP test” go?", sent["text"])

    def test_a_push_with_nothing_queued_sends_the_briefing_alone(self):
        code, out, _ = run_cli(["bot", "morning"])
        self.assertEqual(code, 0)
        self.assertEqual(queue_lines(out), [])
        self.assertNotIn(queue_cli.QUEUE_DONE_LINE, out)


class TerminalTest(_QueueCase):
    def setUp(self):
        super().setUp()
        env = patch.dict(os.environ, {})
        env.start()
        self.addCleanup(env.stop)
        os.environ.pop("STAMIND_FRONTEND", None)
        os.environ.pop("STAMIND_RENDER", None)
        runtime.reset("prompt")

    def test_a_bare_queue_lists_the_waiting_items_then_the_hidden_ones(self):
        later = self.ask("block 5")
        athlete_queue.tell("Charge your watch tonight.")
        athlete_queue.act(self.item(later), QUEUE_LATER_HOUR)
        code, out, _ = run_cli(["queue"])
        self.assertEqual(code, 0)
        self.assertIn("=== QUEUE ===", out)
        lines = out.split("\n")
        watch = next(i for i, line in enumerate(lines) if "Charge your watch" in line)
        row = next(i for i, line in enumerate(lines) if "block 5: what was it?" in line)
        self.assertLess(watch, row)
        self.assertIn("hidden until 09:00", lines[row])
        self.assertIn("1 waiting, 1 hidden.", out)

    def test_closed_lists_what_closed_in_the_order_it_closed(self):
        dropped, waiting, stale = self.ask("A"), self.ask("B"), self.ask("C")
        message = athlete_queue.tell("Charge your watch tonight.")
        self.at(9)
        athlete_queue.act(self.item(message), "a1")
        self.at(10)
        athlete_queue.act(self.item(dropped), athlete_queue.DROP)
        self.stale.add("C")
        self.at(11)
        athlete_queue.settle_if_stale(self.item(stale))
        code, out, _ = run_cli(["queue", "list", "--closed"])
        self.assertEqual(code, 0)
        self.assertIn("=== QUEUE · CLOSED 2026-09-10 Thu .. 2026-09-16 Wed ===", out)
        lines = out.split("\n")
        rows = [
            next(line for line in lines if f"#{item_id} " in line)
            for item_id in (message, dropped, stale)
        ]
        positions = [lines.index(row) for row in rows]
        self.assertEqual(positions, sorted(positions))
        self.assertIn("09:00  Charge your watch tonight.  · answered", rows[0])
        self.assertIn("10:00  A: what was it?  · dropped", rows[1])
        self.assertIn("· stale", rows[2])
        self.assertNotIn("B: what was it?", out)
        self.assertIn("3 closed: 1 answered, 1 dropped, 1 stale.", out)

    def test_a_date_range_keeps_the_items_closed_on_the_athletes_own_days(self):
        """00:30 in Paris is the evening before in UTC: the day is the athlete's."""
        paris = ZoneInfo("Europe/Paris")
        zone = patch("stamind.clock.active_zone", return_value=paris)
        zone.start()
        self.addCleanup(zone.stop)
        self.now = datetime(2026, 9, 14, 8, 0, tzinfo=paris)
        monday, tuesday, wednesday = self.ask("A"), self.ask("B"), self.ask("C")
        for item_id, moment in (
            (monday, datetime(2026, 9, 14, 12, 0, tzinfo=paris)),
            (tuesday, datetime(2026, 9, 15, 23, 30, tzinfo=paris)),
            (wednesday, datetime(2026, 9, 16, 0, 30, tzinfo=paris)),
        ):
            self.now = moment
            athlete_queue.act(self.item(item_id), athlete_queue.DROP)
        self.now = datetime(2026, 9, 16, 9, 0, tzinfo=paris)
        _, today, _ = run_cli(["queue", "list", "--closed", "-d", "today"])
        self.assertIn("C: what was it?", today)
        self.assertNotIn("B: what was it?", today)
        self.assertIn("1 closed: 1 dropped.", today)
        _, before, _ = run_cli(["queue", "list", "--closed", "-d", "..-1d"])
        self.assertIn("A: what was it?", before)
        self.assertIn("B: what was it?", before)
        self.assertNotIn("C: what was it?", before)

    def test_a_date_range_without_closed_says_it_needs_it(self):
        self.ask("A")
        code, out, _ = run_cli(["queue", "list", "-d", "7d"])
        self.assertEqual(code, 0)
        self.assertIn("-d picks closed items by the day they closed, so it needs --closed.", out)
        self.assertNotIn("A: what was it?", out)

    def test_queue_answer_goes_through_the_line_with_the_chooser(self):
        """The terminal keeps the three later choices, "after the others" among them
        (§13.4)."""
        question, message = self.ask("A"), athlete_queue.tell("Charge your watch.")
        prompt = _Prompt(picks=["a2", QUEUE_LATER_BACK])
        runtime.prompt = prompt
        code, out, _ = run_cli(["queue", "answer"])
        self.assertEqual(code, 0)
        self.assertIn(f"Question 1 of 2 · #{question} · queued", out)
        self.assertIn("Named A: leg press.", out)
        self.assertIn(f"Message 2 of 2 · #{message} · queued", out)
        self.assertIn(f"#{message} moved behind the others.", out)
        self.assertTrue(out.rstrip().endswith(queue_cli.QUEUE_DONE_LINE))
        _, question_labels, default = prompt.shown[0]
        self.assertEqual(default, athlete_queue.SKIP)
        self.assertEqual(question_labels[-3:], [
            "later — in 1 hour (09:00)", "later — tomorrow (Thu 08:00)",
            "later — after the others",
        ])
        _, message_labels, _ = prompt.shown[1]
        self.assertEqual(message_labels[:2], ["got it", "tell me again next time"])
        self.assertEqual(message_labels[-2:], [
            "remind me tomorrow (Thu 08:00)", "remind me after the others",
        ])

    def test_after_the_others_asks_about_each_item_once(self):
        """Put behind the others, an item is ready again at once. The command still shows it
        once: otherwise an item alone in the line would come straight back, forever."""
        self.ask("A")
        self.ask("B")
        prompt = _Prompt(picks=[QUEUE_LATER_BACK, QUEUE_LATER_BACK])
        runtime.prompt = prompt
        _, out, _ = run_cli(["queue", "answer"])
        self.assertEqual(len(prompt.shown), 2)
        self.assertIn("Question 2 of 2", out)

    def test_enter_skips_and_writes_nothing(self):
        item_id = self.ask("A")
        run_cli(["queue", "answer"], input_value="")
        self.assertEqual(self.applied, [])
        self.assertEqual(ids(athlete_queue.line()), [item_id])

    def test_an_item_shown_in_a_terminal_is_not_sent_the_same_day(self):
        """Shown here counts as sent (§13.4): the bot leaves it alone until the next
        morning."""
        item_id = self.ask("A")
        run_cli(["queue", "answer"], input_value="")
        self.at(9)
        self.assertFalse(athlete_queue.next_due())
        with patch.dict(os.environ, {"STAMIND_FRONTEND": "json"}):
            _, out, _ = run_cli(["bot", "queue", "--next"])
            self.assertEqual(queue_lines(out), [])
            self.at(8, days=1)
            _, out, _ = run_cli(["bot", "queue", "--next"])
        self.assertEqual(ids(queue_lines(out)), [item_id])

    def test_tell_queues_the_whole_message_and_says_when_it_goes_out(self):
        code, out, _ = run_cli(["queue", "tell", "Charge", "your", "watch."])
        self.assertEqual(code, 0)
        self.assertIn("Queued #", out)
        self.assertIn("within minutes between 08:00 and 21:00, and at 08:00 otherwise.",
                      " ".join(out.split()))
        [item] = test_db.waiting_queue_items()
        self.assertEqual(item["payload"], {"text": "Charge your watch."})

    def test_the_hint_stands_in_for_the_item_on_a_terminal(self):
        """A raw sentinel never reaches a terminal (§6.2)."""
        a = self.ask("A")
        self.ask("B")
        _, out, _ = run_cli(["bot", "queue", str(a), "a1"])
        self.assertIn("Named A: belt squat.", out)
        self.assertNotIn("\x1e", out)
        self.assertIn("1 question is waiting for you.", out)


class HintTest(_QueueCase):
    """`status` and `workout adapt` say what waits; the companion says nothing (§5.2)."""

    def setUp(self):
        super().setUp()
        env = patch.dict(os.environ, {})
        env.start()
        self.addCleanup(env.stop)
        os.environ.pop("STAMIND_RENDER", None)
        for target in ("stamind.cli.status.ensure_recent_data",
                       "stamind.cli.workouts.adapt.ensure_recent_data"):
            pull = patch(target)
            pull.start()
            self.addCleanup(pull.stop)
        coach = patch("stamind.runtime.coach_service")
        coach.start().workout_adapt.return_value = RevisionProposal(
            reason="Metrics are green", workouts=[], new_constraints=[],
            range_start="2026-09-16", range_end="2026-09-30",
        )
        self.addCleanup(coach.stop)

    def test_status_and_adapt_print_the_hint(self):
        self.ask("A")
        athlete_queue.tell("Charge your watch.")
        self.ask("B")
        for argv in (["status"], ["workout", "adapt"]):
            _, out, _ = run_cli(argv)
            self.assertIn("2 questions and 1 message are waiting for you.", out, argv)
            self.assertIn("Go through them with 'queue answer'.", out, argv)

    def test_a_hidden_item_is_not_counted(self):
        item_id = self.ask("A")
        athlete_queue.act(self.item(item_id), QUEUE_LATER_HOUR)
        _, out, _ = run_cli(["status"])
        self.assertNotIn("waiting for you", out)

    def test_the_companion_prints_no_hint(self):
        athlete_queue.tell("Charge your watch.")
        with patch.dict(os.environ, {"STAMIND_RENDER": "simple"}):
            for argv in (["status"], ["workout", "adapt"]):
                _, out, _ = run_cli(argv)
                self.assertNotIn("waiting for you", out, argv)


class RetrospectiveQuestionTest(_QueueCase):
    """How did it go? One question per mesocycle that reached its end
    (DESIGN_cycle_retrospective.md §4). The clock stands on Wednesday 16 September, and the
    mesocycle ended on Sunday 13."""

    WRITTEN = {
        "record": "For: easy volume.\nHappened: on target.\nCame out: fitness rose.",
        "athlete_line": "You kept your training steady these three weeks.",
    }

    def setUp(self):
        super().setUp()
        self.goal = test_db.add_objective("Alpe du Zwift", "2026-12-22", "cycling")
        self.first = self._plan(
            ("Aerobic base 2", "2026-08-24", "2026-09-13"), ("Build", "2026-09-14", "2026-10-04")
        )
        garmin = patch("stamind.runtime.garmin")
        garmin.start()
        self.addCleanup(garmin.stop)

    def _plan(self, *mesocycles):
        return test_db.save_macrocycle(self.goal, "strategy", "g", "c", [
            {"name": name, "start_date": start, "end_date": end, "focus": "easy volume"}
            for name, start, end in mesocycles
        ])

    def _question(self):
        cycle_records.date_check(test_db, today_str())
        [item] = test_db.waiting_queue_items()
        return item

    def _record(self):
        [record] = test_db.get_retrospectives(self.goal)
        return record

    def test_the_terminal_and_the_chat_each_have_their_wording(self):
        item = self._question()
        self.assertEqual((item["kind"], item["subject"]),
                         ("retrospective", str(self._record()["id"])))
        self.assertEqual(
            athlete_queue.wording(item),
            "How did “Aerobic base 2” (Aug 24 to Sep 13) go for you?",
        )
        self.assertEqual(
            athlete_queue.wording(item, companion=True),
            "Your last three weeks of training are done. How did they go for you?",
        )
        self.assertEqual([a["label"] for a in athlete_queue.answers(item)], ["tell me"])
        self.assertEqual(athlete_queue.drop_label(item), "nothing to say")

    @patch("stamind.coach.engine.openrouter_client")
    def test_the_answer_stores_the_words_and_returns_the_sentence(self, client):
        client.complete.return_value = dict(self.WRITTEN)
        item = self._question()
        line = athlete_queue.act(item, "a1", text="felt fresh all the way")
        self.assertEqual(line, self.WRITTEN["athlete_line"])
        record = self._record()
        self.assertEqual(record["athlete_words"], "felt fresh all the way")
        self.assertEqual(record["body"], self.WRITTEN["record"])
        self.assertIn("felt fresh all the way", client.complete.call_args[0][1])
        self.assertEqual(self.item(item["id"])["outcome"], athlete_queue.ANSWERED)

    @patch("stamind.coach.engine.openrouter_client")
    def test_a_failed_write_keeps_the_words_and_thanks_the_athlete(self, client):
        client.complete.side_effect = ValueError("no answer")
        item = self._question()
        line = athlete_queue.act(item, "a1", text="felt fresh")
        self.assertEqual(line, retrospective_question.THANKS_LINE)
        record = self._record()
        self.assertEqual((record["athlete_words"], record["body"]), ("felt fresh", None))
        self.assertTrue(cycle_records.is_due(record, today_str()))

    def test_nothing_to_say_leaves_the_record_to_wait_its_seven_days(self):
        item = self._question()
        athlete_queue.act(item, athlete_queue.DROP)
        self.assertEqual(self.item(item["id"])["outcome"], athlete_queue.DROPPED)
        self.assertFalse(cycle_records.is_due(self._record(), today_str()))
        self.assertTrue(cycle_records.is_due(self._record(), "2026-09-20"))

    def test_the_question_goes_stale_seven_days_after_the_end_of_its_record(self):
        item = self._question()
        self.at(8, days=3)
        self.assertEqual(ids(athlete_queue.line()), [item["id"]])
        self.at(8, days=4)
        self.assertEqual(athlete_queue.line(), [])
        self.assertEqual(self.item(item["id"])["outcome"], athlete_queue.STALE)

    def test_the_question_goes_stale_when_its_record_is_removed(self):
        item = self._question()
        test_db.delete_retrospective(self._record()["id"])
        self.assertEqual(athlete_queue.line(), [])

    def test_a_plan_is_asked_about_in_its_own_words(self):
        """One question at the end of a plan, about the plan."""
        test_db.wipe_plans()
        self._plan(("Aerobic base 2", "2026-08-24", "2026-09-13"))
        item = self._question()
        self.assertEqual(test_db.get_retrospective(int(item["subject"]))["level"], "plan")
        self.assertEqual(
            athlete_queue.wording(item),
            "Your plan toward “Alpe du Zwift” ended on Sep 13. How did it go?",
        )
        self.assertEqual(
            athlete_queue.wording(item, companion=True),
            "Your plan toward “Alpe du Zwift” is finished. How did it go for you?",
        )

    def test_the_chat_offers_tell_me_nothing_to_say_and_not_now(self):
        self._question()
        with patch.dict(os.environ, {"STAMIND_FRONTEND": "json"}):
            _, out, _ = run_cli(["queue", "answer"])
        [sent] = queue_lines(out)
        self.assertIn("Your last three weeks of training are done.", sent["text"])
        self.assertEqual([b["label"] for b in sent["buttons"]],
                         ["Tell me", "Nothing to say", "🕐 Not now"])

    def test_a_record_cut_short_queues_no_question(self):
        """On Wednesday 23 September `plan generate` drops the mesocycle under way, nine
        days into it. The only question is the one about the mesocycle that ended."""
        asked = self._question()
        self._plan(("Rebuild", "2026-09-23", "2026-10-11"))
        with test_db._get_connection() as conn:
            conn.execute(
                "UPDATE macrocycles SET superseded_at = '2026-09-23T06:00:00+00:00' "
                "WHERE id = ?", (self.first,),
            )
            conn.commit()
        self.at(8, days=8)
        cycle_records.date_check(test_db, today_str())
        self.assertEqual(
            [(r["name"], r["end_date"], r["ended_by"])
             for r in test_db.get_retrospectives(self.goal)],
            [("Aerobic base 2", "2026-09-13", "finished"),
             ("Build", "2026-09-22", "replaced")],
        )
        self.assertEqual(ids(test_db.waiting_queue_items()), [asked["id"]])

    def test_a_mesocycle_that_ended_a_week_ago_queues_no_question(self):
        self.at(8, days=4)
        cycle_records.date_check(test_db, today_str())
        self.assertEqual(len(test_db.get_retrospectives(self.goal)), 1)
        self.assertEqual(test_db.waiting_queue_items(), [])


if __name__ == "__main__":
    unittest.main()
