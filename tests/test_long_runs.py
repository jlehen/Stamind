"""The saved questions whose answer starts a long run (DESIGN_long_runs_beside_chat.md §4–§6),
and the confirmations' place and lifetime in the queue (DESIGN_chat_questions.md §2).

The chat's side, which place a tap runs in, is in `test_chat_coach_run.py`.
"""
import os
import unittest
from datetime import datetime, timedelta
from unittest.mock import MagicMock, patch

from tests.helpers import clear_all_tables, run_cli, rebind_test_db, save_workout, started_from
from tests import test_db_path

TEST_DB_PATH = test_db_path("test_stamind_long_runs.db")

from stamind.db import Database
import stamind_cli  # noqa: F401  (registers the parsers)

from stamind import athlete_queue, runtime
from stamind.cli.bot import hand_off

if os.path.exists(TEST_DB_PATH):
    os.remove(TEST_DB_PATH)
test_db = Database(db_path=TEST_DB_PATH)
rebind_test_db(test_db)


def tearDownModule():
    try:
        os.remove(TEST_DB_PATH)
    except OSError:
        pass


THURSDAY_8AM = datetime(2026, 10, 8, 8, 0).astimezone()
NEXT_THURSDAY = "2026-10-15"
WORDS = "make my long run shorter"


class _Case(unittest.TestCase):
    """Thursday 8 October, 08:30, in the athlete's chat."""

    def setUp(self):
        rebind_test_db(test_db)
        clear_all_tables(test_db)
        test_db.set_setting("push_morning_time", "08:00")
        self.now = THURSDAY_8AM.replace(minute=30)
        clock = patch("stamind.clock.now", side_effect=lambda: self.now)
        clock.start()
        self.addCleanup(clock.stop)
        started_from(self, "chat")
        renders = patch.dict(os.environ, {"STAMIND_RENDER": "simple"})
        renders.start()
        self.addCleanup(renders.stop)
        self.addCleanup(runtime.reset, "render", "prompt")
        runtime.reset("render")

    def at(self, days, hour=8, minute=0):
        self.now = THURSDAY_8AM.replace(hour=hour, minute=minute) + timedelta(days=days)

    def line_ids(self):
        return [item["id"] for item in athlete_queue.line()]


class HandOffTest(_Case):
    """"Shall I pass it to your coach?" is a saved question (§5). The athlete wrote "make my
    long run shorter", and the capture found next Thursday's run rather than a goal."""

    def ask(self, day=NEXT_THURSDAY):
        save_workout(test_db, day, "running", "Long run", duration_minutes=100)
        session = test_db.get_workouts(start_date=day, end_date=day)[0]
        return hand_off.queue_question("goal", "Thursday's long run", session, WORDS)

    def tap(self, item, action):
        with patch("stamind.cli.workouts.adapt.run_workout_adapt") as adapt:
            code, out, _ = run_cli(["bot", "queue", str(item["id"]), action])
        self.assertEqual(code, 0)
        return adapt, out

    def test_yes_passes_the_athletes_words_to_the_coach(self):
        item = self.ask()
        adapt, _out = self.tap(item, "a1")
        adapt.assert_called_once()
        self.assertEqual(adapt.call_args.args[0].message, WORDS)
        self.assertEqual(test_db.get_queue_item(item["id"])["outcome"], athlete_queue.ANSWERED)

    def test_no_writes_nothing(self):
        item = self.ask()
        adapt, out = self.tap(item, "a2")
        adapt.assert_not_called()
        self.assertIn(hand_off.LEFT_LINE, out)
        self.assertEqual(test_db.get_queue_item(item["id"])["outcome"], athlete_queue.ANSWERED)

    def test_yes_answered_on_a_terminal_passes_them_too(self):
        item = self.ask()
        started_from(self, "terminal")
        prompt = MagicMock()
        prompt.choose.return_value = "a1"
        with patch.object(runtime, "prompt", prompt, create=True), \
                patch("stamind.cli.workouts.adapt.run_workout_adapt") as adapt:
            code, _out, _ = run_cli(["queue", "answer", str(item["id"])])
        self.assertEqual(code, 0)
        self.assertEqual(adapt.call_args.args[0].message, WORDS)

    def test_a_tap_on_yes_starts_a_long_run_and_on_no_does_not(self):
        item = self.ask()
        self.assertEqual(athlete_queue.long_run_argv(item, "a1"), ("workout", "adapt", "-m"))
        self.assertIsNone(athlete_queue.long_run_argv(item, "a2"))

    def test_it_closes_once_the_day_of_the_session_is_over(self):
        item = self.ask(day="2026-10-09")
        self.at(days=1)
        self.assertEqual(self.line_ids(), [item["id"]])
        self.at(days=2)
        self.assertEqual(self.line_ids(), [])
        self.assertEqual(test_db.get_queue_item(item["id"])["outcome"], athlete_queue.STALE)


class ConfirmationTest(_Case):
    """A confirmation stands at the front of the line, and lives `confirmation-days`
    mornings after the day it was asked (DESIGN_chat_questions.md §2)."""

    def ask(self):
        save_workout(test_db, NEXT_THURSDAY, "running", "Long run", duration_minutes=100)
        session = test_db.get_workouts(start_date=NEXT_THURSDAY, end_date=NEXT_THURSDAY)[0]
        return hand_off.queue_question("goal", "Thursday's long run", session, WORDS)

    def test_it_comes_back_on_three_mornings_and_closes_on_the_fourth(self):
        """Asked Thursday 08:30: back on Friday, Saturday and Sunday mornings, closed on
        Monday's without a word."""
        item = self.ask()
        for days in (1, 2, 3):
            self.at(days=days)
            self.assertEqual(self.line_ids(), [item["id"]], f"morning {days}")
        self.at(days=3, hour=23)
        self.assertEqual(self.line_ids(), [item["id"]])
        self.at(days=4)
        self.assertEqual(self.line_ids(), [])
        self.assertEqual(test_db.get_queue_item(item["id"])["outcome"], athlete_queue.STALE)

    def test_the_number_of_mornings_is_a_setting(self):
        item = self.ask()
        test_db.set_setting("confirmation_days", "1")
        self.at(days=1)
        self.assertEqual(self.line_ids(), [item["id"]])
        self.at(days=2)
        self.assertEqual(self.line_ids(), [])

    def test_it_stands_in_front_of_an_older_question(self):
        self.at(days=0, hour=7)
        older = athlete_queue.tell("Your watch strap is in the post.")
        self.at(days=0, hour=8, minute=30)
        item = self.ask()
        self.at(days=1)
        self.assertEqual(self.line_ids(), [item["id"], older])


if __name__ == "__main__":
    unittest.main()
