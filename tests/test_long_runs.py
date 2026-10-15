"""The saved questions whose answer starts a long run (DESIGN_long_runs_beside_chat.md §4–§6),
and the confirmations' place and lifetime in the queue (DESIGN_chat_questions.md §2).

The chat's side, which place a tap runs in, is in `test_chat_coach_run.py`.
"""
import dataclasses
import json
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
from stamind.chat.callbacks import tap_long_run
from stamind.chat.routing import COACH_RUN, PLANNING_RUN
from stamind.cli.bot import hand_off
from stamind.cli.runway import runway_argv
from stamind.cli.workouts import proposal as saved
from stamind.coach.proposals import GenerateProposal, RevisionProposal
from stamind.queue_kind import queue
from stamind.sentinels import QUEUE_SENTINEL

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
THURSDAY, FRIDAY, SATURDAY, MONDAY = "2026-10-08", "2026-10-09", "2026-10-10", "2026-10-12"
NEXT_THURSDAY = "2026-10-15"
WORDS = "make my long run shorter"


def queue_lines(out):
    """The SM-QUEUE payloads a run wrote, in order."""
    return [json.loads(line[len(QUEUE_SENTINEL):]) for line in out.split("\n")
            if line.startswith(QUEUE_SENTINEL)]


def weeks(*days, title="Easy run"):
    """What the week planner would write: one easy run on each of `days`."""
    return GenerateProposal(
        reasoning="Two easy runs to start the block.",
        workouts=tuple({
            "date": day, "sport_type": "running", "title": title,
            "description": f"[{title}]\n40 easy minutes.", "duration_minutes": 40,
            "rpe": 3, "tss": 30,
        } for day in days),
        gen_start=days[0], gen_end=NEXT_THURSDAY,
    )


class _Case(unittest.TestCase):
    """Thursday 8 October, 08:30, in the athlete's chat."""

    def setUp(self):
        rebind_test_db(test_db)
        clear_all_tables(test_db)
        test_db.set_setting("push_morning_time", "08:00")
        test_db.set_setting("confirmation_days", "3")
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

    def test_the_bot_runs_a_yes_as_the_coachs_run_and_a_no_in_the_chats_place(self):
        item = self.ask()
        self.assertEqual(tap_long_run(str(item["id"]), "a1"), COACH_RUN)
        self.assertIsNone(tap_long_run(str(item["id"]), "a2"))

    def test_once_the_day_of_the_session_is_over_it_closes_and_a_yes_says_so(self):
        """The run named is Friday's. On Friday it is still asked; on Saturday it is out of
        date, and a tap on "Yes" passes nothing on."""
        item = self.ask(day="2026-10-09")
        self.at(days=1)
        self.assertEqual(self.line_ids(), [item["id"]])
        self.at(days=2)
        adapt, out = self.tap(item, "a1")
        adapt.assert_not_called()
        self.assertIn(hand_off.CLOSED_LINE, out)
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


class ProposeTest(_Case):
    """`workout generate --propose`, the run the button "📅 Plan my next weeks" sends
    (DESIGN_long_runs_beside_chat.md §4). The schedule ran out yesterday."""

    def setUp(self):
        super().setUp()
        self.coach = MagicMock()
        self.coach.workout_generate.return_value = weeks(FRIDAY, SATURDAY)
        self.prompt = MagicMock()
        self.stale_plans = []
        self.garmin = MagicMock()
        for patcher in (
            patch.object(runtime, "coach_service", self.coach, create=True),
            patch.object(runtime, "prompt", self.prompt, create=True),
            patch.object(runtime, "garmin", self.garmin, create=True),
            patch("stamind.runtime.calendar_syncer"),
            patch("stamind.cli.workouts.generate.ensure_recent_data"),
            patch("stamind.cli.queue_commands.ensure_recent_data"),
            patch("stamind.cli.workouts.generate._out_of_date_plans",
                  side_effect=lambda *_a: self.stale_plans),
        ):
            patcher.start()
            self.addCleanup(patcher.stop)

    def propose(self, *extra):
        code, out, _ = run_cli(["workout", "generate", "--propose", *extra])
        self.assertEqual(code, 0)
        return out

    def tap(self, item, action="a1"):
        code, out, _ = run_cli(["bot", "queue", str(item["id"]), action])
        self.assertEqual(code, 0)
        return out

    def waiting(self, kind):
        return [item for item in test_db.waiting_queue_items() if item["kind"] == kind]

    def test_it_writes_nothing_and_ends_with_the_weeks_sent(self):
        out = self.propose()
        self.coach.workout_generate_apply.assert_not_called()
        self.prompt.confirm.assert_not_called()
        [question] = queue_lines(out)
        self.assertEqual(question["text"], "Shall I schedule these 2 sessions?")
        self.assertEqual([b["label"] for b in question["buttons"]],
                         ["✅ Schedule them", "✖️ Leave it"])
        self.assertIn("Easy run", out[:out.index(QUEUE_SENTINEL)])
        [item] = self.waiting(saved.SCHEDULE)
        self.assertTrue(item["sent_at"])

    def test_the_question_names_the_sessions_the_weeks_replace(self):
        self.coach.workout_generate.return_value = dataclasses.replace(
            weeks(FRIDAY, SATURDAY), displaced=({"date": FRIDAY}, {"date": SATURDAY}),
        )
        [question] = queue_lines(self.propose())
        self.assertEqual(
            question["text"],
            "Shall I schedule these 2 sessions? They replace the 2 sessions planned from "
            "Fri Oct 09 to Thu Oct 15.",
        )

    def test_schedule_them_writes_what_was_saved_not_what_asking_again_would_return(self):
        self.propose()
        [item] = self.waiting(saved.SCHEDULE)
        self.coach.workout_generate.return_value = weeks(FRIDAY, title="Long ride")
        out = self.tap(item)
        self.assertIn(saved.SCHEDULED_LINE, out)
        self.coach.workout_generate.assert_called_once()
        written = self.coach.workout_generate_apply.call_args.args[0]
        self.assertEqual(written.workouts, weeks(FRIDAY, SATURDAY).workouts)
        self.assertEqual((written.gen_start, written.gen_end), (FRIDAY, NEXT_THURSDAY))

    def test_leave_it_writes_nothing(self):
        self.propose()
        [item] = self.waiting(saved.SCHEDULE)
        out = self.tap(item, "a2")
        self.assertIn(saved.KEPT_LINE, out)
        self.coach.workout_generate_apply.assert_not_called()

    def test_a_session_written_on_its_days_puts_it_out_of_date(self):
        """10:00, the knee: the coach moves Saturday's run. 11:00, "Schedule them"."""
        self.propose()
        [item] = self.waiting(saved.SCHEDULE)
        save_workout(test_db, SATURDAY, "running", "Shorter run", duration_minutes=30)
        out = self.tap(item)
        self.assertIn(saved.OUT_OF_DATE_LINE, out)
        self.coach.workout_generate_apply.assert_not_called()

    def test_a_session_written_outside_its_days_leaves_it_open(self):
        """Today's ride is eased: no day of the weeks changed (choice 2b)."""
        self.propose()
        [item] = self.waiting(saved.SCHEDULE)
        save_workout(test_db, THURSDAY, "cycling", "Easy ride", duration_minutes=30)
        save_workout(test_db, MONDAY, "cycling", "Easy ride", duration_minutes=30)
        self.tap(item)
        self.coach.workout_generate_apply.assert_called_once()

    def test_its_first_day_over_puts_it_out_of_date(self):
        self.propose()
        [item] = self.waiting(saved.SCHEDULE)
        self.at(days=2)
        out = self.tap(item)
        self.assertIn(saved.OUT_OF_DATE_LINE, out)
        self.coach.workout_generate_apply.assert_not_called()

    def test_writing_today_after_an_activity_of_today_puts_it_out_of_date(self):
        self.coach.workout_generate.return_value = weeks(THURSDAY, FRIDAY)
        self.propose()
        [item] = self.waiting(saved.SCHEDULE)
        test_db.save_completed_activity(
            activity_id="a-run", date=THURSDAY, start_time=f"{THURSDAY} 09:00:00",
            activity_name="Run", activity_type="running", duration_sec=2400,
            distance_km=8.0, elevation_gain_m=0.0, avg_hr=140, max_hr=160, rpe=None,
            tss=40.0,
        )
        self.at(days=0, hour=11)
        out = self.tap(item)
        self.assertIn(saved.OUT_OF_DATE_LINE, out)
        self.coach.workout_generate_apply.assert_not_called()

    def test_a_session_written_while_it_thought_saves_nothing(self):
        def think(**_kwargs):
            save_workout(test_db, SATURDAY, "running", "Shorter run", duration_minutes=30)
            return weeks(FRIDAY, SATURDAY)

        self.coach.workout_generate.side_effect = think
        out = self.propose()
        self.assertIn("Your week changed while I was thinking.", out)
        self.assertEqual(self.waiting(saved.SCHEDULE), [])

    def test_saving_weeks_leaves_a_waiting_proposal_open_and_the_other_way_round(self):
        earlier = queue("proposal", "2026-10-08T05:00:00", {
            "text": "Ease today.", "answers": [], "proposal": {}, "dates": [THURSDAY],
            "written_upto": 0, "sleep_seen": False,
        })
        self.propose()
        [weeks_item] = self.waiting(saved.SCHEDULE)
        self.assertIsNone(test_db.get_queue_item(earlier)["closed_at"])
        saved.save(RevisionProposal(reason="Easier.", workouts=[], range_start=THURSDAY,
                                    range_end=THURSDAY), 0)
        self.assertIsNone(test_db.get_queue_item(weeks_item["id"])["closed_at"])

    def test_a_second_run_closes_the_weeks_of_the_first(self):
        self.propose()
        [first] = self.waiting(saved.SCHEDULE)
        self.at(days=0, hour=9)
        self.propose()
        self.assertEqual(test_db.get_queue_item(first["id"])["outcome"], athlete_queue.STALE)
        self.assertEqual(len(self.waiting(saved.SCHEDULE)), 1)

    def test_with_sessions_in_its_days_it_asks_first_and_calls_no_planner(self):
        save_workout(test_db, THURSDAY, "running", "Easy run", duration_minutes=40)
        out = self.propose("-d", f"{THURSDAY}..{NEXT_THURSDAY}")
        self.coach.workout_generate.assert_not_called()
        [question] = queue_lines(out)
        self.assertIn("You already have 1 session planned", question["text"])
        self.assertIn("Shall I plan these weeks?", question["text"])
        self.assertEqual([b["label"] for b in question["buttons"]],
                         ["✅ Plan them", "✖️ Leave it"])

    def test_plan_them_starts_the_planning_for_the_same_days(self):
        save_workout(test_db, THURSDAY, "running", "Easy run", duration_minutes=40)
        self.propose("-d", f"{THURSDAY}..{NEXT_THURSDAY}")
        [item] = self.waiting(saved.REPLACE_SESSIONS)
        self.assertEqual(tap_long_run(str(item["id"]), "a1"), PLANNING_RUN)
        out = self.tap(item)
        self.coach.workout_generate.assert_called_once()
        self.assertEqual(self.coach.workout_generate.call_args.kwargs["start_date"], THURSDAY)
        self.assertEqual(self.coach.workout_generate.call_args.kwargs["end_date"], NEXT_THURSDAY)
        [question] = queue_lines(out)
        self.assertEqual(question["text"], "Shall I schedule these 2 sessions?")

    def test_leave_it_on_the_question_plans_nothing(self):
        save_workout(test_db, THURSDAY, "running", "Easy run", duration_minutes=40)
        self.propose("-d", f"{THURSDAY}..{NEXT_THURSDAY}")
        [item] = self.waiting(saved.REPLACE_SESSIONS)
        out = self.tap(item, "a2")
        self.assertIn(saved.KEPT_LINE, out)
        self.coach.workout_generate.assert_not_called()

    def test_a_session_written_on_its_days_leaves_the_question_open(self):
        """Sunday 09:00 the question is saved; 10:00 "Change it" on the knee proposal writes
        one of its days; 11:00 "Plan them" plans from the week as it now stands."""
        save_workout(test_db, THURSDAY, "running", "Easy run", duration_minutes=40)
        self.propose("-d", f"{THURSDAY}..{NEXT_THURSDAY}")
        [item] = self.waiting(saved.REPLACE_SESSIONS)
        save_workout(test_db, THURSDAY, "running", "Shorter run", duration_minutes=30)
        self.tap(item)
        self.coach.workout_generate.assert_called_once()

    def test_plan_them_once_its_first_day_is_over_says_so_and_plans_nothing(self):
        save_workout(test_db, THURSDAY, "running", "Easy run", duration_minutes=40)
        self.propose("-d", f"{THURSDAY}..{NEXT_THURSDAY}")
        [item] = self.waiting(saved.REPLACE_SESSIONS)
        self.at(days=1)
        out = self.tap(item)
        self.assertIn(saved.REPLACE_CLOSED_LINE, out)
        self.coach.workout_generate.assert_not_called()

    def test_the_question_closes_after_its_mornings(self):
        save_workout(test_db, NEXT_THURSDAY, "running", "Easy run", duration_minutes=40)
        self.propose("-d", f"{MONDAY}..{NEXT_THURSDAY}")
        [item] = self.waiting(saved.REPLACE_SESSIONS)
        self.at(days=3)
        self.assertEqual(self.line_ids(), [item["id"]])
        self.at(days=4)
        self.assertEqual(self.line_ids(), [])

    def test_on_an_out_of_date_plan_it_calls_no_planner_and_says_so(self):
        self.stale_plans = [({"id": 1}, "the goal moved")]
        out = self.propose()
        self.assertIn("I can't plan your next weeks yet", out)
        self.coach.workout_generate.assert_not_called()
        self.assertEqual(test_db.waiting_queue_items(), [])

    def test_typed_without_the_flag_it_still_asks(self):
        self.prompt.confirm.return_value = False
        code, _out, _ = run_cli(["workout", "generate"])
        self.assertEqual(code, 0)
        self.prompt.confirm.assert_called_once()
        self.assertEqual(test_db.waiting_queue_items(), [])

    def test_the_button_sends_the_flag(self):
        self.assertEqual(runway_argv({"kind": "span"}), "workout generate --propose")
        self.assertEqual(
            runway_argv({"kind": "mesocycle", "next_mesocycle": {"id": 7}}),
            "workout generate -m ..7 --propose",
        )


if __name__ == "__main__":
    unittest.main()
