"""The questions the chat asked on the spot until October 2026, now saved in the athlete
queue (DESIGN_chat_questions.md): the cut-short question (§3), the confirmations of a new
goal, an edit and a setting, and the two offers that became questions (§4), the picker
(§5) and the confirmation of a test result typed unasked (§6).

The note inbox's own questions and the question the morning after a test are in
`test_cli_bot_capture.py`; the hand-off after a message about a session, and the
confirmations' mornings, in `test_long_runs.py`.
"""
import json
import os
import unittest
from contextlib import nullcontext
from datetime import datetime, timedelta
from unittest.mock import MagicMock, patch

from tests.helpers import clear_all_tables, run_cli, rebind_test_db, save_workout, started_from
from tests import test_db_path

TEST_DB_PATH = test_db_path("test_stamind_chat_questions.db")

from stamind.db import Database
import stamind_cli  # noqa: F401  (registers the parsers)

from stamind import athlete_queue, runtime, settings
from stamind.cli.bot import edit, hand_off
from stamind.cli.candidates import queue_candidates
from stamind.cli.workouts import cut_short, proposal as saved
from stamind.coach.proposals import RevisionProposal
from stamind.config import config
from stamind.queue_kind import queue
from stamind.sentinels import BUTTONS_SENTINEL, QUEUE_SENTINEL

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
TODAY, YESTERDAY = "2026-10-08", "2026-10-07"


def sent(out):
    """The SM-QUEUE payloads a run wrote, in order."""
    return [json.loads(line[len(QUEUE_SENTINEL):]) for line in out.split("\n")
            if line.startswith(QUEUE_SENTINEL)]


class _Case(unittest.TestCase):
    """Thursday 8 October 2026, 08:30, in the athlete's chat."""

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
        self.prompt = MagicMock()
        prompt = patch.object(runtime, "prompt", self.prompt, create=True)
        prompt.start()
        self.addCleanup(prompt.stop)

    def at(self, days, hour=8, minute=0):
        self.now = THURSDAY_8AM.replace(hour=hour, minute=minute) + timedelta(days=days)

    def later(self):
        """A minute on: the next command starts at an instant of its own."""
        self.now += timedelta(minutes=1)

    def tap(self, item_id, action):
        self.later()
        code, out, _ = run_cli(["bot", "queue", str(item_id), action])
        self.assertEqual(code, 0)
        return out

    def capture(self, intent, text, extraction):
        self.later()
        with patch("stamind.openrouter.OpenRouterClient.complete", return_value=extraction):
            code, out, _ = run_cli(["bot", "capture", intent, text])
        self.assertEqual(code, 0)
        return out

    def line_ids(self):
        return [item["id"] for item in athlete_queue.line()]

    def outcome(self, item_id):
        return test_db.get_queue_item(item_id)["outcome"]


# --- "Was that the session, cut short?" (§3) ---

PLANNED = {
    "date": YESTERDAY, "sport_type": "cycling", "title": "Endurance Ride",
    "description": "90 mins", "duration_minutes": 90, "rpe": 4, "tss": 60,
}
RIDE = {"activity_name": "Zwift ride", "activity_type": "virtual_ride",
        "duration_sec": 1200.0, "tss": 14.0}


class CutShortTest(_Case):
    """Thursday's 90-minute ride was planned, and Garmin recorded 20 minutes."""

    def setUp(self):
        super().setUp()
        self.decided = {}
        self.coach = MagicMock()
        self.coach.pending_match_questions.side_effect = lambda *_a: [
            {"activity_id": "zwift", "sport": "cycling", "date": YESTERDAY,
             "planned": PLANNED, "completed": RIDE}
        ] if ("zwift", "cycling") not in self.decided else []
        self.coach.record_match_decision.side_effect = (
            lambda activity, sport, accepted: self.decided.update({(activity, sport): accepted})
        )
        self.coach.workout_adapt.return_value = RevisionProposal(
            reason="Holding the week.", workouts=[], new_constraints=[],
            range_start=TODAY, range_end=TODAY,
        )
        for patcher in (
            patch.object(runtime, "coach_service", self.coach, create=True),
            patch("stamind.cli.workouts.adapt.ensure_recent_data"),
            patch("stamind.cli.workouts.adapt.plan_is_behind", return_value=False),
            patch("stamind.cli.workouts.adapt.current_runway", return_value=None),
            patch("stamind.cli.workouts.adapt.replacing_unsent",
                  side_effect=lambda **_kw: nullcontext()),
        ):
            patcher.start()
            self.addCleanup(patcher.stop)

    def adapt(self, *argv):
        self.later()
        code, out, _ = run_cli(["workout", "adapt", *argv])
        self.assertEqual(code, 0)
        return out

    def waiting(self):
        return [item for item in test_db.waiting_queue_items() if item["kind"] == cut_short.KIND]

    def test_a_chat_run_calls_the_week_planner_and_asks_after_its_answer(self):
        """12:15 "I'm tired": the coach answers at once, on the app's own pairing, and the
        question follows its answer."""
        out = self.adapt("-m", "I'm tired, can we go easier this weekend?")
        self.coach.workout_adapt.assert_called_once()
        self.prompt.confirm.assert_not_called()
        [question] = sent(out)
        self.assertTrue(question["text"].startswith("🙋 Quick question"))
        self.assertIn("Planned: ", question["text"])
        self.assertIn("Endurance Ride", question["text"])
        self.assertIn("Was that the session, cut short?", question["text"])
        self.assertEqual([b["label"] for b in question["buttons"]],
                         ["✅ Yes", "✖️ No", "🕐 Not now"])
        self.assertLess(out.index("Holding the week."), out.index(QUEUE_SENTINEL))

    def test_a_terminal_asks_on_the_spot_before_the_week_planner(self):
        started_from(self, "terminal")
        self.prompt.confirm.return_value = False
        self.adapt()
        self.assertIn("Was that the session, cut short?", self.prompt.confirm.call_args[0][0])
        self.assertEqual(self.decided, {("zwift", "cycling"): False})
        self.assertEqual(self.waiting(), [])

    def test_a_terminal_run_with_y_queues_it(self):
        started_from(self, "terminal")
        self.adapt("-y")
        self.prompt.confirm.assert_not_called()
        self.assertEqual(len(self.waiting()), 1)

    def test_the_morning_run_queues_it_and_it_follows_the_briefing(self):
        garmin = patch.object(runtime, "garmin", MagicMock(), create=True)
        garmin.start()
        self.addCleanup(garmin.stop)
        telegram = {k: v for k, v in (config.data.get("telegram") or {}).items() if k != "push"}
        with patch.dict(config.data, {"telegram": telegram}), \
                patch("stamind.cli.bot.views.read_new_activities"):
            code, out, _ = run_cli(["bot", "morning", "--force"])
        self.assertEqual(code, 0)
        [question] = sent(out)
        self.assertIn("Was that the session, cut short?", question["text"])

    def test_it_stands_before_an_older_question_and_closes_on_the_fourth_morning(self):
        """Friday to Monday it comes first, Tuesday it is closed and not asked again."""
        self.at(days=-1, hour=9)
        older = athlete_queue.tell("Your watch strap is in the post.")
        self.at(days=0, hour=8, minute=30)
        cut_short.queue_questions(TODAY)
        [item] = self.waiting()
        for days in (1, 2, 3):
            self.at(days=days)
            self.assertEqual(self.line_ids(), [item["id"], older], f"morning {days}")
        self.at(days=4)
        self.assertEqual(self.line_ids(), [older])
        self.assertEqual(self.outcome(item["id"]), athlete_queue.STALE)
        cut_short.queue_questions(TODAY)
        self.assertEqual(self.waiting(), [])
        self.assertEqual(self.decided, {})

    def test_yes_and_no_store_the_answer(self):
        cut_short.queue_questions(TODAY)
        [item] = self.waiting()
        out = self.tap(item["id"], "a1")
        self.assertIn(cut_short.COUNTED_LINE, out)
        self.assertEqual(self.decided, {("zwift", "cycling"): True})
        self.decided.clear()
        test_db.queue_item(cut_short.KIND, "again", item["payload"], self.now)
        [again] = self.waiting()
        out = self.tap(again["id"], "a2")
        self.assertIn(cut_short.DISCARDED_LINE, out)
        self.assertEqual(self.decided, {("zwift", "cycling"): False})

    def test_an_answer_given_in_a_terminal_closes_it(self):
        cut_short.queue_questions(TODAY)
        [item] = self.waiting()
        self.decided[("zwift", "cycling")] = True
        self.assertEqual(self.line_ids(), [])
        self.assertEqual(self.outcome(item["id"]), athlete_queue.STALE)

    def test_a_check_that_fails_leaves_it_open(self):
        cut_short.queue_questions(TODAY)
        [item] = self.waiting()
        self.coach.pending_match_questions.side_effect = OSError("database is locked")
        self.assertFalse(athlete_queue.settle_if_stale(item))


# --- a new goal, a setting (§4) ---

class NewGoalTest(_Case):
    GOAL = {"title": "Half marathon", "target_date": "2027-05-10", "sports": ["running"],
            "date_type": "event"}

    def ask(self):
        [question] = sent(self.capture("add_goal", "I want to run a half marathon", self.GOAL))
        return question

    def test_the_question_reads_the_goal_back_and_names_it(self):
        question = self.ask()
        self.prompt.confirm.assert_not_called()
        lines = question["text"].split("\n")
        self.assertEqual(lines[0], "Here's what I've got:")
        self.assertIn("Half marathon — on Mon May 10", lines[1])
        self.assertEqual(lines[-1], "Shall I set up this goal?")
        self.assertEqual([b["label"] for b in question["buttons"]], ["✅ Yes", "✖️ No"])
        self.assertEqual(test_db.get_objectives(), [])

    def test_yes_sets_it_up_and_no_sets_up_nothing(self):
        question = self.ask()
        self.assertIn("Okay — nothing set up.", self.tap(question["id"], "a2"))
        self.assertEqual(test_db.get_objectives(), [])
        question = self.ask()
        self.tap(question["id"], "a1")
        self.assertEqual([g["title"] for g in test_db.get_objectives()], ["Half marathon"])


class SettingTest(_Case):
    def ask(self, value="07:00"):
        [question] = sent(self.capture(
            "change_setting", "message me at 7 instead", {"key": "morning-time", "value": value}
        ))
        return question

    def test_yes_changes_it_and_no_leaves_it(self):
        question = self.ask()
        self.assertTrue(question["text"].startswith("I'll open your day at 07:00"))
        self.assertTrue(question["text"].endswith("Shall I change this setting?"))
        self.assertIn("Okay — I've left it as it was.", self.tap(question["id"], "a2"))
        self.assertEqual(settings.morning_time(), "08:00")
        question = self.ask()
        self.assertIn("Done", self.tap(question["id"], "a1"))
        self.assertEqual(settings.morning_time(), "07:00")

    def test_it_closes_when_the_setting_already_has_that_value(self):
        question = self.ask()
        test_db.set_setting("push_morning_time", "07:00")
        self.assertTrue(athlete_queue.settle_if_stale(test_db.get_queue_item(question["id"])))

    def test_a_newer_question_about_the_same_setting_closes_the_older(self):
        first = self.ask("07:00")
        second = self.ask("06:30")
        self.assertEqual(self.outcome(first["id"]), athlete_queue.STALE)
        self.assertIsNone(self.outcome(second["id"]))


# --- an edit, and the picker (§4, §5) ---

class EditTest(_Case):
    """"Away for work" runs Monday 26 to Wednesday 28 October, "Family visit" the 31st
    to 1 November."""

    def setUp(self):
        super().setUp()
        self.work = test_db.add_constraint(
            title="Away for work", start_date="2026-10-26", end_date="2026-10-28",
            rest=0, description=None, replan=0, source="message",
        )
        self.family = test_db.add_constraint(
            title="Family visit", start_date="2026-10-31", end_date="2026-11-01",
            rest=0, description=None, replan=0, source="message",
        )

    def ask(self, changes, row=None, text="the work trip moved to the 27th", **extra):
        extraction = {"kind": "constraint", "id": row or self.work, "changes": changes, **extra}
        return sent(self.capture("edit_constraint", text, extraction))

    MOVE = {"start_date": "2026-10-27", "end_date": "2026-10-29"}

    def test_the_question_shows_the_constraint_as_it_is_when_sent(self):
        [question] = self.ask(self.MOVE)
        self.assertEqual(question["text"].split("\n")[0],
                         "Your constraint “Away for work” — Mon Oct 26 to Wed Oct 28")
        self.assertTrue(question["text"].endswith("Shall I change this constraint?"))
        test_db.update_constraint(self.work, title="Berlin trip")
        item = test_db.get_queue_item(question["id"])
        self.assertIn("“Berlin trip”", athlete_queue.wording(item, companion=True))

    def test_yes_makes_the_change(self):
        [question] = self.ask(self.MOVE)
        self.tap(question["id"], "a1")
        row = test_db.get_constraint(self.work)
        self.assertEqual((row["start_date"], row["end_date"]), ("2026-10-27", "2026-10-29"))

    def test_no_changes_nothing_and_asks_which_constraint_to_change(self):
        [question] = self.ask(self.MOVE)
        out = self.tap(question["id"], "a2")
        self.assertIn(edit.NOTHING_CHANGED_LINE, out)
        [picker] = sent(out)
        self.assertEqual(picker["text"].split("\n"), [
            "Which constraint should I change?", "• Family visit — Sat Oct 31",
        ])
        self.assertEqual(test_db.get_constraint(self.work)["start_date"], "2026-10-26")

    def test_it_closes_when_the_constraint_is_gone_or_reads_as_asked(self):
        [question] = self.ask(self.MOVE)
        item = test_db.get_queue_item(question["id"])
        test_db.update_constraint(self.work, start_date="2026-10-27", end_date="2026-10-29")
        self.assertTrue(athlete_queue.settle_if_stale(item))
        [question] = self.ask({"title": "Berlin trip"})
        test_db.delete_constraint(self.work)
        self.assertTrue(athlete_queue.settle_if_stale(test_db.get_queue_item(question["id"])))

    def test_a_newer_question_closes_an_older_one_only_about_the_same_parts(self):
        """The rule of §4: the newer one must change every part the older one would."""
        [dates] = self.ask({"start_date": "2026-10-27"})
        [both] = self.ask({"start_date": "2026-10-27", "end_date": "2026-10-29"})
        self.assertEqual(self.outcome(dates["id"]), athlete_queue.STALE)
        [name] = self.ask({"title": "Berlin trip"})
        [family] = self.ask({"title": "Family trip"}, row=self.family)
        [dates_and_name] = self.ask({"start_date": "2026-10-28", "title": "Work"})
        self.assertEqual(self.outcome(both["id"]), athlete_queue.STALE)
        self.assertEqual(self.outcome(name["id"]), athlete_queue.STALE)
        [name_alone] = self.ask({"title": "Berlin"})
        for item in (family, dates_and_name, name_alone):
            self.assertIsNone(self.outcome(item["id"]))

    def test_several_close_candidates_become_a_picker_and_a_tap_asks_the_edit(self):
        [picker] = self.ask(self.MOVE, text="push my trip back a day",
                            candidate_ids=[self.work, self.family])
        self.assertEqual(picker["text"].split("\n"), [
            "Which constraint did you mean?", "• Away for work — Mon Oct 26",
            "• Family visit — Sat Oct 31",
        ])
        self.assertEqual([b["label"] for b in picker["buttons"]],
                         ["✏️ Away for work", "✏️ Family visit", "✖️ None of these"])
        self.later()
        with patch("stamind.openrouter.OpenRouterClient.complete", return_value={
            "kind": "constraint", "id": self.work, "changes": self.MOVE,
        }):
            [question] = sent(run_cli(["bot", "queue", str(picker["id"]), "a1"])[1])
        self.assertIn("“Away for work”", question["text"])
        self.assertEqual(test_db.get_constraint(self.work)["start_date"], "2026-10-26")

    def test_none_of_these_writes_nothing(self):
        [picker] = self.ask(self.MOVE, candidate_ids=[self.work, self.family])
        out = self.tap(picker["id"], "a3")
        self.assertIn(edit.NONE_LINE, out)
        self.assertEqual(sent(out), [])

    def test_the_picker_closes_when_none_of_its_rows_is_left(self):
        [picker] = self.ask(self.MOVE, candidate_ids=[self.work, self.family])
        test_db.delete_constraint(self.work)
        item = test_db.get_queue_item(picker["id"])
        self.assertFalse(athlete_queue.settle_if_stale(item))
        test_db.delete_constraint(self.family)
        self.assertTrue(athlete_queue.settle_if_stale(item))


# --- a test result written unasked (§6) ---

class TestResultTest(_Case):
    def test_it_gets_the_same_confirmation_as_a_reply(self):
        test_db.add_benchmark_result(
            date="2026-09-10", sport_type="cycling", anchor_kind="ftp", value=235.0,
            unit="W", source="test",
        )
        [question] = sent(self.capture("test_result", "the FTP test gave 236 W", {
            "kind": "ftp", "value": "236", "sport": "cycling", "date": None,
            "performed": True, "session_id": None, "note": None,
        }))
        self.prompt.confirm.assert_not_called()
        self.assertEqual(
            question["text"],
            "Your FTP from today: 236 W, up from 235 W (+0.4%). Shall I write down this test "
            "result?",
        )
        # It compares with the latest result when it is sent.
        test_db.add_benchmark_result(
            date="2026-10-01", sport_type="cycling", anchor_kind="ftp", value=230.0,
            unit="W", source="test",
        )
        item = test_db.get_queue_item(question["id"])
        self.assertIn("up from 230 W", athlete_queue.wording(item, companion=True))
        self.assertIn("Written down", self.tap(question["id"], "a1"))
        self.assertEqual(test_db.get_latest_benchmark("ftp")["value"], 236.0)

    def test_a_typed_number_puts_the_first_question_off_until_the_next_morning(self):
        """Thursday: "How did Wednesday's FTP test go?" is answered "236". Its confirmation
        is asked; the first question waits for Friday, and comes back there after a
        "No"."""
        from stamind.cli.bot import test_result
        session = save_workout(test_db, YESTERDAY, "cycling", "FTP Test",
                               benchmark_type="ftp_20min")
        test_result.ask_about(test_db.get_workout_by_id(session))
        [first] = test_db.waiting_queue_items()
        self.prompt.ask_text.return_value = "236"
        self.later()
        with patch("stamind.openrouter.OpenRouterClient.complete", return_value={
            "kind": "ftp", "value": "236", "performed": True, "session_id": session,
            "note": None,
        }):
            [confirmation] = sent(run_cli(["bot", "queue", str(first["id"]), "a1"])[1])
        self.assertIn("Shall I write down this test result?", confirmation["text"])
        self.assertEqual(self.line_ids(), [confirmation["id"]])
        self.tap(confirmation["id"], "a2")
        self.at(days=1)
        self.assertEqual(self.line_ids(), [first["id"]])
        self.assertTrue(athlete_queue.was_put_off(test_db.get_queue_item(first["id"])))


# --- the confirmations' place and life, the constraint question included (§2) ---

class LifeTest(_Case):
    def test_the_constraint_question_stands_first_and_closes_on_the_fourth_morning(self):
        """On 7 October the athlete writes "No training on November 12th" and never
        taps."""
        self.at(days=-1, hour=9)
        older = athlete_queue.tell("Your watch strap is in the post.")
        self.at(days=-1, hour=9, minute=30)
        [item] = queue_candidates(
            [{"title": "no training", "start_date": "2026-11-12", "end_date": "2026-11-12"}],
            [], YESTERDAY, "No training on November 12th", offer=True,
        )
        for days in (0, 1, 2):
            self.at(days=days)
            self.assertEqual(self.line_ids(), [item["id"], older], f"morning {days}")
        self.at(days=3)
        self.assertEqual(self.line_ids(), [older])
        self.assertEqual(test_db.get_constraints(TODAY, None), [])


# --- the two offers that became questions (§4) ---

class AdjustWeekTest(_Case):
    """A mesocycle runs until 31 October: the coach can reach a constraint before it."""

    def setUp(self):
        super().setUp()
        goal = test_db.add_objective("Zurich Marathon", "2027-04-01", "running")
        test_db.save_macrocycle(goal, "Build.", "g", "c", [{
            "name": "Base", "start_date": "2026-10-01", "end_date": "2026-10-31",
            "focus": "Endurance",
        }])
        runtime.calendar_syncer = MagicMock()
        self.addCleanup(runtime.reset, "calendar_syncer")

    def ask(self):
        [constraint] = sent(self.capture("note", "I can't train on the 24th", {
            "new_constraints": [
                {"title": "no training", "start_date": "2026-10-24", "end_date": "2026-10-24"},
            ],
        }))
        [question] = sent(self.tap(constraint["id"], "a1"))
        return question

    def test_its_yes_starts_the_coach_with_no_message(self):
        question = self.ask()
        self.assertEqual([b["label"] for b in question["buttons"]], ["✅ Yes", "✖️ No"])
        with patch("stamind.cli.workouts.adapt.run_workout_adapt") as adapt:
            self.tap(question["id"], "a1")
        self.assertIsNone(adapt.call_args.args[0].message)

    def test_no_leaves_the_week(self):
        question = self.ask()
        with patch("stamind.cli.workouts.adapt.run_workout_adapt") as adapt:
            out = self.tap(question["id"], "a2")
        adapt.assert_not_called()
        self.assertIn(hand_off.LEAVE_WEEK_LINE, out)

    def test_it_closes_once_the_coach_has_looked_at_the_week(self):
        question = self.ask()
        item = test_db.get_queue_item(question["id"])
        self.assertFalse(athlete_queue.settle_if_stale(item))
        self.later()
        queue(saved.KIND, "later", {"text": "", "answers": []})
        self.assertTrue(athlete_queue.settle_if_stale(item))


class HandOffAfterAMissTest(_Case):
    def test_a_miss_asks_to_pass_it_on_and_lives_its_mornings(self):
        out = self.capture("note", "the thing about the stuff",
                           {"new_constraints": [], "new_signals": []})
        self.assertNotIn(BUTTONS_SENTINEL, out)
        [question] = sent(out)
        self.assertEqual(
            question["text"],
            "I'm not sure what to do with that one 🤔 — but I don't want to lose it. Shall I "
            "pass it to your coach?",
        )
        for days in (1, 2, 3):
            self.at(days=days)
            self.assertEqual(self.line_ids(), [question["id"]], f"morning {days}")
        self.at(days=4)
        self.assertEqual(self.line_ids(), [])
        with patch("stamind.cli.workouts.adapt.run_workout_adapt") as adapt:
            self.at(days=0, hour=9)
            test_db.queue_item(hand_off.KIND, "again", test_db.get_queue_item(
                question["id"])["payload"], self.now)
            [again] = [item for item in test_db.waiting_queue_items()]
            self.tap(again["id"], "a1")
        self.assertEqual(adapt.call_args.args[0].message, "the thing about the stuff")
