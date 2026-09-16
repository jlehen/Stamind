"""The athlete queue (DESIGN_athlete_queue.md): what is queued, the walk, the actions, the
reminders, and the terminal and chat surfaces that show them."""
import json
import os
import unittest
from datetime import datetime, timedelta
from unittest.mock import MagicMock, patch

from tests import test_db_path
from tests.helpers import clear_all_tables, rebind_test_db, run_cli, save_workout

TEST_DB_PATH = test_db_path("test_athlete_queue.db")

from trainmate.db import Database
import trainmate_cli  # noqa: F401 — the CLI binds its handles at import, before the rebind

from trainmate import athlete_queue, clock, runtime
from trainmate.cli import queue as queue_cli
from trainmate.coach.proposals import RevisionProposal
from trainmate.prompt import (
    BUTTONS_SENTINEL, QUEUE_LATER_BACK, QUEUE_LATER_DAY, QUEUE_LATER_HOUR, QUEUE_SENTINEL,
)
from trainmate.util import today_str

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
    """The TM-QUEUE payloads a run wrote, in order. Split on newlines only:
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
        self.now = WEDNESDAY_8AM
        moving_clock = patch("trainmate.clock.now", side_effect=lambda: self.now)
        moving_clock.start()
        self.addCleanup(moving_clock.stop)
        self.stale = set()
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
        athlete_queue.act(self.item(first), athlete_queue.DROP, self.now)
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
        athlete_queue.act(self.item(first), "a2", self.now)
        self.assertEqual(self.applied, [(first, 1, None)])
        self.assertEqual(self.item(first)["outcome"], athlete_queue.ANSWERED)

    def test_an_action_the_item_was_not_queued_with_writes_nothing(self):
        """A button can only run one of the answers its item was queued with (§9)."""
        question, message = self.ask("block 1"), athlete_queue.tell("Charge your watch.")
        for action in ("a9", "a0", "a", "x"):
            athlete_queue.act(self.item(question), action, self.now)
        athlete_queue.act(self.item(message), athlete_queue.DROP, self.now)
        self.assertEqual(self.applied, [])
        self.assertEqual(ids(test_db.waiting_queue_items()), [question, message])


class WalkTest(_QueueCase):
    def test_the_order_is_the_order_things_were_queued(self):
        a, b, c = self.ask("A"), self.ask("B"), self.ask("C")
        self.assertEqual(ids(athlete_queue.walk(self.now)), [a, b, c])

    def test_after_the_others_moves_an_item_to_the_back(self):
        a, b, c = self.ask("A"), self.ask("B"), self.ask("C")
        self.at(8, 5)
        athlete_queue.act(self.item(a), QUEUE_LATER_BACK, WEDNESDAY_8AM)
        self.assertEqual(ids(test_db.waiting_queue_items()), [b, c, a])

    def test_a_walk_shows_each_item_once(self):
        """Put behind the others, an item waits for the next walk: otherwise an item alone
        in the queue would come straight back, forever (§4)."""
        a, b = self.ask("A"), self.ask("B")
        since = self.now
        self.at(8, 5)
        walk = athlete_queue.walk(since)
        athlete_queue.act(walk[0], QUEUE_LATER_BACK, since)
        walk = athlete_queue.walk(since, after=walk[0])
        self.assertEqual(ids(walk), [b])
        athlete_queue.act(walk[0], QUEUE_LATER_BACK, since)
        self.assertEqual(athlete_queue.walk(since, after=walk[0]), [])
        self.at(9)
        self.assertEqual(ids(athlete_queue.walk(self.now)), [a, b])

    def test_a_walk_leaves_out_hidden_items_and_items_queued_during_it(self):
        hidden, first = self.ask("hidden"), self.ask("first")
        athlete_queue.act(self.item(hidden), QUEUE_LATER_HOUR, self.now)
        since = self.at(8, 1)
        walk = athlete_queue.walk(since)
        self.assertEqual(ids(walk), [first])
        self.at(8, 10)
        self.ask("queued during the walk")
        self.assertEqual(athlete_queue.walk(since, after=walk[0]), [])

    def test_what_a_command_queues_belongs_to_the_walk_it_opens(self):
        """The push queues its questions while it runs and opens its walk at its end: both
        are dated by the command's start (§4)."""
        clock.start_command()
        self.addCleanup(clock.end_command)
        self.at(8, 1)
        item_id = self.ask("queued by the push")
        self.assertEqual(ids(athlete_queue.walk(clock.command_start())), [item_id])

    def test_a_stale_item_is_closed_without_being_shown(self):
        gone, kept = self.ask("gone"), self.ask("kept")
        self.stale.add("gone")
        self.assertEqual(ids(athlete_queue.walk(self.now)), [kept])
        self.assertEqual(self.item(gone)["outcome"], athlete_queue.STALE)


class LaterTest(_QueueCase):
    def test_in_1_day_comes_back_before_the_walk_started_whenever_the_tap_came(self):
        """The push's walk starts at 08:00, and what it puts off comes back at 07:58 the next
        day, whether she tapped at once or in the evening (§4)."""
        early, late = self.ask("early"), self.ask("late")
        self.at(8, 1)
        athlete_queue.act(self.item(early), QUEUE_LATER_DAY, WEDNESDAY_8AM)
        self.at(21, 30)
        athlete_queue.act(self.item(late), QUEUE_LATER_DAY, WEDNESDAY_8AM)
        for item_id in (early, late):
            back = clock.to_local(datetime.fromisoformat(self.item(item_id)["remind_at"]))
            self.assertEqual(back.strftime("%a %H:%M"), "Thu 07:58")

    def test_an_item_put_off_is_hidden_until_its_reminder_time(self):
        item_id = self.ask("block 5")
        self.at(8, 5)
        athlete_queue.act(self.item(item_id), QUEUE_LATER_HOUR, WEDNESDAY_8AM)
        self.at(9, 0)
        self.assertEqual(athlete_queue.walk(self.now), [])
        self.assertEqual(athlete_queue.waiting_counts(), (0, 0))
        self.assertFalse(athlete_queue.reminders_due())
        self.at(9, 5)
        self.assertTrue(athlete_queue.reminders_due())
        self.assertEqual(athlete_queue.waiting_counts(), (1, 0))


class ReminderTest(_QueueCase):
    def put_off(self, subject):
        item_id = self.ask(subject)
        athlete_queue.act(self.item(item_id), QUEUE_LATER_HOUR, self.now)
        return item_id

    def test_a_reminder_is_sent_once(self):
        item_id = self.put_off("block 5")
        self.at(9, 1)
        self.assertEqual(ids(athlete_queue.due_reminders()), [item_id])
        self.assertEqual(athlete_queue.due_reminders(), [])
        self.assertIsNone(self.item(item_id)["closed_at"], "a reminder closes nothing")

    def test_a_stale_reminder_is_closed_and_not_sent(self):
        item_id = self.put_off("block 6")
        self.stale.add("block 6")
        self.at(9, 1)
        self.assertEqual(athlete_queue.due_reminders(), [])
        self.assertEqual(self.item(item_id)["outcome"], athlete_queue.STALE)

    def test_no_reminder_follows_once_a_walk_has_shown_the_item(self):
        """The bot was down when the time came, and the next walk reached the item first."""
        item_id = self.put_off("block 5")
        self.at(9, 30)
        walk = athlete_queue.walk(self.now)
        self.assertEqual(ids(walk), [item_id])
        athlete_queue.shown(walk[0])
        self.assertFalse(athlete_queue.reminders_due())


class ChatTest(_QueueCase):
    """Under the bot every item goes out as a TM-QUEUE line, and a tap runs `bot queue`."""

    def setUp(self):
        super().setUp()
        env = patch.dict(os.environ, {"TRAINMATE_FRONTEND": "json"})
        env.start()
        self.addCleanup(env.stop)

    def tap(self, item_id, action, since):
        return run_cli(["bot", "queue", str(item_id), action, "--since", since])

    def test_a_walk_sends_one_item_at_a_time_and_ends_with_thanks(self):
        a, b = self.ask("A"), self.ask("B")
        code, out, _ = run_cli(["queue", "answer"])
        self.assertEqual(code, 0)
        [first] = queue_lines(out)
        self.assertEqual(first["id"], a)
        self.assertIn("(2 left)", first["text"])
        _, out, _ = self.tap(a, "a1", first["since"])
        self.assertIn("Named A: belt squat.", out)
        [second] = queue_lines(out)
        self.assertEqual((second["id"], second["since"]), (b, first["since"]))
        _, out, _ = self.tap(b, athlete_queue.DROP, first["since"])
        self.assertEqual(queue_lines(out), [])
        self.assertIn(queue_cli.QUEUE_DONE_LINE, out)

    def test_a_walk_that_finds_nothing_sends_nothing(self):
        _, out, _ = run_cli(["queue", "answer"])
        self.assertEqual(queue_lines(out), [])
        self.assertNotIn(queue_cli.QUEUE_DONE_LINE, out)

    def test_a_tap_on_a_settled_item_says_so_and_moves_on(self):
        a, b = self.ask("A"), self.ask("B")
        athlete_queue.act(self.item(a), "a1", self.now)  # another copy was tapped first
        _, out, _ = self.tap(a, "a2", queue_cli.since_token(self.now))
        self.assertIn(queue_cli.QUEUE_SETTLED_LINE, out)
        self.assertEqual(len(self.applied), 1)
        self.assertEqual(ids(queue_lines(out)), [b])

    def test_a_reminder_ends_where_it_is_acted_on(self):
        a = self.ask("A")
        self.ask("B")
        athlete_queue.act(self.item(a), QUEUE_LATER_HOUR, self.now)
        self.at(9, 1)
        _, out, _ = run_cli(["bot", "queue", "--remind"])
        [reminder] = queue_lines(out)
        self.assertEqual(reminder["id"], a)
        self.assertTrue(reminder["since"].startswith(queue_cli.WALK_OF_ONE))
        self.assertIn("come back to", reminder["text"])
        _, out, _ = self.tap(a, "a1", reminder["since"])
        self.assertIn("Named A: belt squat.", out)
        self.assertEqual(queue_lines(out), [])
        self.assertNotIn(queue_cli.QUEUE_DONE_LINE, out)
        _, out, _ = run_cli(["bot", "queue", "--remind"])
        self.assertEqual(queue_lines(out), [])

    def test_the_companion_has_no_skip_and_the_expert_does(self):
        """Skip and "after the others" differ in a way she cannot see (§6.4)."""
        self.ask("A")
        with patch.dict(os.environ, {"TRAINMATE_RENDER": "simple"}):
            _, out, _ = run_cli(["queue", "answer"])
        [companion] = queue_lines(out)
        _, out, _ = run_cli(["queue", "answer"])
        [expert] = queue_lines(out)
        self.assertEqual([b["action"] for b in companion["buttons"]],
                         ["a1", "a2", "a3", "d", "n"])
        self.assertEqual([b["action"] for b in expert["buttons"]],
                         ["a1", "a2", "a3", "d", "s", "n"])
        self.assertEqual(companion["text"], "🙋 Quick question (1 left)\nYour A — what was it?")
        self.assertEqual([b["label"] for b in companion["buttons"]][3:],
                         ["Leave it unnamed", "🕐 Not now"])

    def test_a_typed_answer_asks_for_its_text(self):
        item_id = self.ask("A")
        runtime.prompt = _Prompt(typed="cable row")
        _, out, _ = self.tap(item_id, "a3", queue_cli.since_token(self.now))
        self.assertEqual(self.applied, [(item_id, 2, "cable row")])
        self.assertIn("Named A: cable row.", out)

    def test_an_empty_typed_answer_leaves_the_item_waiting(self):
        item_id = self.ask("A")
        runtime.prompt = _Prompt(typed="")
        self.tap(item_id, "a3", queue_cli.since_token(self.now))
        self.assertEqual(self.applied, [])
        self.assertIsNone(self.item(item_id)["closed_at"])


class MorningWalkTest(_QueueCase):
    """`bot morning` ends with the first item of the queue (§6.1)."""

    def setUp(self):
        super().setUp()
        garmin = patch.object(runtime, "garmin", MagicMock(), create=True)
        garmin.start()
        self.addCleanup(garmin.stop)
        env = patch.dict(os.environ, {"TRAINMATE_FRONTEND": "json", "TRAINMATE_RENDER": "simple"})
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
        os.environ.pop("TRAINMATE_FRONTEND", None)
        os.environ.pop("TRAINMATE_RENDER", None)
        runtime.reset("prompt")

    def test_a_bare_queue_lists_the_waiting_items_then_the_hidden_ones(self):
        later = self.ask("block 5")
        athlete_queue.tell("Charge your watch tonight.")
        athlete_queue.act(self.item(later), QUEUE_LATER_HOUR, self.now)
        code, out, _ = run_cli(["queue"])
        self.assertEqual(code, 0)
        self.assertIn("=== QUEUE ===", out)
        lines = out.split("\n")
        watch = next(i for i, line in enumerate(lines) if "Charge your watch" in line)
        row = next(i for i, line in enumerate(lines) if "block 5: what was it?" in line)
        self.assertLess(watch, row)
        self.assertIn("hidden until 09:00", lines[row])
        self.assertIn("1 waiting, 1 hidden.", out)

    def test_a_walk_goes_through_the_items_with_the_chooser(self):
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
            "later — in 1 hour (09:00)", "later — in 1 day (Thu 07:58)",
            "later — after the others",
        ])
        _, message_labels, _ = prompt.shown[1]
        self.assertEqual(message_labels[:2], ["got it", "tell me again next time"])

    def test_enter_skips_and_writes_nothing(self):
        item_id = self.ask("A")
        run_cli(["queue", "answer"], input_value="")
        self.assertEqual(self.applied, [])
        self.assertEqual(ids(athlete_queue.walk(self.now)), [item_id])

    def test_tell_queues_the_whole_message(self):
        code, out, _ = run_cli(["queue", "tell", "Charge", "your", "watch."])
        self.assertEqual(code, 0)
        self.assertIn("Queued #", out)
        [item] = test_db.waiting_queue_items()
        self.assertEqual(item["payload"], {"text": "Charge your watch."})

    def test_the_hint_stands_in_for_the_item_on_a_terminal(self):
        """A raw sentinel never reaches a terminal (§6.2)."""
        a = self.ask("A")
        self.ask("B")
        _, out, _ = run_cli(
            ["bot", "queue", str(a), "a1", "--since", queue_cli.since_token(self.now)]
        )
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
        os.environ.pop("TRAINMATE_RENDER", None)
        for target in ("trainmate.cli.status.ensure_recent_data",
                       "trainmate.cli.workouts.generate.ensure_recent_data"):
            pull = patch(target)
            pull.start()
            self.addCleanup(pull.stop)
        coach = patch("trainmate.runtime.coach_service")
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
        athlete_queue.act(self.item(item_id), QUEUE_LATER_HOUR, self.now)
        _, out, _ = run_cli(["status"])
        self.assertNotIn("waiting for you", out)

    def test_the_companion_prints_no_hint(self):
        athlete_queue.tell("Charge your watch.")
        with patch.dict(os.environ, {"TRAINMATE_RENDER": "simple"}):
            for argv in (["status"], ["workout", "adapt"]):
                _, out, _ = run_cli(argv)
                self.assertNotIn("waiting for you", out, argv)


if __name__ == "__main__":
    unittest.main()
