"""`bot capture <intent>` tests: the write path behind the free-text router.

One extraction per run, mocked; what the capture ASKED is read off a scripted prompt,
because for a capture the question is the preview (DESIGN_bot_simple_frontend.md §12.2).
The views and the router itself are in `test_cli_bot.py`.
"""
import json
import os
import unittest
from unittest.mock import MagicMock, patch

from tests.helpers import (
    clear_all_tables, run_cli, rebind_test_db, save_workout, started_from,
)
from tests import test_db_path

TEST_DB_PATH = test_db_path("test_stamind_cli_bot_capture.db")

from stamind.db import Database
import stamind_cli  # noqa: F401  (registers the bot parser)

from stamind import athlete_queue, clock, runtime
from stamind.cli.bot import test_result
from stamind.cli.candidates import queue_candidates
from stamind.cli.queue import QUEUE_DONE_LINE, queue_chat_message
from stamind.config import config
from stamind.sentinels import BUTTONS_SENTINEL, QUEUE_SENTINEL
from stamind.clock import today_str

# One database for the whole module: the classes below share it and clear its tables per
# test, so its lifecycle is module-level, not per-class.
if os.path.exists(TEST_DB_PATH):
    os.remove(TEST_DB_PATH)
test_db = Database(db_path=TEST_DB_PATH)
rebind_test_db(test_db)


def tearDownModule():
    try:
        os.remove(TEST_DB_PATH)
    except OSError:
        pass




class _ScriptedPrompt:
    """Stands in for the prompt transport so a test can read what a capture ASKED.

    A confirm's text goes to `input()`, which `run_cli` mocks away, so the question never
    reaches the captured stdout — and for a capture the question IS the preview
    (DESIGN_bot_simple_frontend.md §12.2)."""

    def __init__(self, answers=True, choice=None):
        self.asked = []
        self._script = list(answers) if isinstance(answers, (list, tuple)) else None
        self._always = None if self._script is not None else bool(answers)
        self._choice = choice

    def confirm(self, message, *, default=False, danger=False):
        self.asked.append(message)
        if self._script is None:
            return self._always
        return self._script.pop(0) if self._script else False

    def choose(self, message, choices, *, default=None):
        self.asked.append("\n".join([message] + [choice.label for choice in choices]))
        if self._choice is not None:
            return self._choice
        return default if default is not None else choices[0].value

    def ask_text(self, message, *, secret=False, default=None):
        self.asked.append(message)
        return default or ""

    @property
    def text(self):
        return "\n".join(self.asked)


class _CaptureCase(unittest.TestCase):
    """Shared rig for the §12 capture commands: the companion voice, a scripted prompt,
    and one mocked extraction per run."""

    def setUp(self):
        rebind_test_db(test_db)
        clear_all_tables(test_db)
        patcher = patch.dict(os.environ, {"STAMIND_RENDER": "simple"})
        patcher.start()
        self.addCleanup(patcher.stop)

    def prompt(self, answers=True, choice=None):
        prompt = _ScriptedPrompt(answers, choice)
        runtime.prompt = prompt
        # An assignment on `runtime` shadows the accessor for the whole process.
        self.addCleanup(runtime.reset, "prompt")
        return prompt

    def capture(self, argv, extraction, answers=True, choice=None):
        """Runs one `bot capture …`; returns (exit code, stdout, the prompt)."""
        prompt = self.prompt(answers, choice)
        with patch(
            "stamind.openrouter.OpenRouterClient.complete",
            **({"side_effect": extraction} if isinstance(extraction, Exception)
               else {"return_value": extraction}),
        ):
            code, out, _ = run_cli(argv)
        return code, out, prompt

    def future(self, days):
        from datetime import date, timedelta
        return (date.fromisoformat(today_str()) + timedelta(days=days)).isoformat()



class _NoteCase(_CaptureCase):
    """`bot capture note` with a mesocycle under way for three more weeks: the days the
    coach can still change."""

    NOTE = "sore knee, no running for two weeks"

    def setUp(self):
        super().setUp()
        syncer = MagicMock()
        syncer.add_signal_event.side_effect = (
            lambda date, metric, value, text, existing=None:
            existing or f"evt-{date}-{metric}"
        )
        runtime.calendar_syncer = syncer
        self.addCleanup(runtime.reset, "calendar_syncer")
        goal = test_db.add_objective("Zurich Marathon", self.future(60), "running")
        test_db.save_macrocycle(goal, "Build.", "g", "c", [{
            "name": "Base", "start_date": self.future(-7), "end_date": self.future(21),
            "focus": "Endurance",
        }])

    def _run(self, extraction, answers=True):
        return self.capture(["bot", "capture", "note", self.NOTE], extraction, answers)

    def _constraint(self, days=0):
        return {"new_constraints": [
            {"title": "no running", "start_date": self.future(days),
             "end_date": self.future(days)},
        ]}


class CaptureNoteTest(_NoteCase):
    """`bot capture note` — §12.3: the note inbox that asks before storing. Typed in a
    terminal, it asks on the spot and offers nothing after: the operator runs `workout
    adapt` when they want it (DESIGN_chat_questions.md §2)."""

    def test_a_confirmed_constraint_and_signal_are_stored_and_nothing_is_offered(self):
        code, out, _ = self._run({**self._constraint(), "new_signals": [
            {"metric": "disturbed_sleep", "date": today_str(), "end_date": today_str()},
        ]})
        self.assertEqual(code, 0)
        self.assertEqual(
            [c["title"] for c in test_db.get_constraints(today_str(), None)],
            ["no running"],
        )
        self.assertTrue(test_db.get_daily_signals(today_str(), today_str()))
        self.assertNotIn(BUTTONS_SENTINEL, out)
        self.assertNotIn(QUEUE_SENTINEL, out)
        self.assertEqual(test_db.waiting_queue_items(), [])

    def test_nothing_found_says_so(self):
        code, out, _ = self._run({"new_constraints": [], "new_signals": []})
        self.assertEqual(code, 0)
        self.assertIn("I'm not sure what to do with that one", out)
        self.assertNotIn(BUTTONS_SENTINEL, out)
        self.assertEqual(test_db.get_constraints(today_str(), None), [])

    def test_an_extraction_failure_lands_where_a_no_find_does(self):
        code, out, _ = self._run(ValueError("no api key"))
        self.assertEqual(code, 0)
        self.assertIn("I'm not sure what to do with that one", out)

    def test_a_preference_for_good_is_handed_to_the_operator_not_stored(self):
        """2026-09-16: "never two workouts in a day" has no dates, so it is not a
        constraint. She is told whose it is, her words are quoted so she can forward the
        message, and today's half stays one tap away (§12.3)."""
        code, out, prompt = self._run({"new_constraints": [
            {"title": "never two workouts in a day", "start_date": None,
             "end_date": None, "open_ended": True},
        ]})
        self.assertEqual(code, 0)
        self.assertEqual(test_db.get_constraints(today_str(), None), [])
        self.assertNotIn("Shall I remember this constraint?", prompt.text)
        # The reply is wrapped for the chat; compare on one logical line.
        said = " ".join(out.split())
        self.assertIn("not something for the next few days", said)
        self.assertIn(f"Ask {config.telegram_operator_name} to record this", said)
        self.assertIn("forward this message", said)
        self.assertIn(f"“{self.NOTE}”", said)
        self.assertNotIn(BUTTONS_SENTINEL, out)

    def test_a_dated_constraint_beside_an_open_ended_one_is_still_stored(self):
        code, out, _ = self._run({"new_constraints": [
            {"title": "never two workouts in a day", "open_ended": True},
        ] + self._constraint()["new_constraints"]})
        self.assertEqual(code, 0)
        self.assertEqual(
            [c["title"] for c in test_db.get_constraints(today_str(), None)],
            ["no running"],
        )
        self.assertIn("forward this message", out)
        self.assertNotIn(BUTTONS_SENTINEL, out)

    def test_declining_stores_nothing_and_presses_no_further(self):
        code, out, _ = self._run(self._constraint(), answers=False)
        self.assertEqual(code, 0)
        self.assertEqual(test_db.get_constraints(today_str(), None), [])
        self.assertNotIn(BUTTONS_SENTINEL, out)

    def test_the_confirm_and_the_outcome_speak_the_companion_voice(self):
        """The shared helper (§12.10) asks the same question `workout adapt -m` asks,
        worded by the active renderer — here the companion one (§6: no IDs, no ISO)."""
        code, out, prompt = self._run(self._constraint())
        self.assertIn("Shall I remember this constraint?", prompt.text)
        self.assertNotIn("Add constraint:", prompt.text)
        self.assertNotIn(today_str(), prompt.text)
        self.assertIn("Noted — I'll work around that", out)
        self.assertNotIn("Captured constraint [", out)


class CaptureNoteFromChatTest(_NoteCase):
    """Started from the chat, `bot capture note` asks nothing on the spot: each question is
    queued, the first one is the reply, and a tap answers it
    (DESIGN_waiting_proposal.md §6.3)."""

    SIGNAL = {"metric": "disturbed_sleep", "date": today_str(), "end_date": today_str()}

    def setUp(self):
        super().setUp()
        started_from(self, "chat")

    def frames(self, out):
        """The queued questions a run sent, in order."""
        return [json.loads(line[len(QUEUE_SENTINEL):]) for line in out.split("\n")
                if line.startswith(QUEUE_SENTINEL)]

    def asked(self, extraction):
        """One capture: (the question it sent, the prompt nobody was asked through)."""
        code, out, prompt = self._run(extraction)
        self.assertEqual(code, 0)
        [question] = self.frames(out)
        return question, prompt

    def tap(self, question, action):
        _code, out, _err = run_cli(["bot", "queue", str(question["id"]), action])
        return out

    def test_the_question_is_queued_and_drawn_bare(self):
        question, prompt = self.asked(self._constraint())
        self.assertEqual(prompt.asked, [])
        self.assertEqual(
            question["text"], "Shall I remember this constraint? “no running” — today"
        )
        self.assertEqual([b["label"] for b in question["buttons"]], ["Yes", "No"])
        self.assertEqual(test_db.get_constraints(today_str(), None), [])
        # It is out, so the line waits for its answer. Unanswered, it stands in the line
        # like any queued question and comes back the next morning.
        self.assertTrue(athlete_queue.anything_out())
        self.assertEqual([item["id"] for item in athlete_queue.line()], [question["id"]])

    def test_yes_stores_it_and_asks_to_adjust_the_week(self):
        question, _prompt = self.asked(self._constraint())
        out = self.tap(question, "a1")
        self.assertEqual(
            [c["title"] for c in test_db.get_constraints(today_str(), None)],
            ["no running"],
        )
        self.assertIn("Noted — I'll work around that", out)
        [adjust] = self.frames(out)
        self.assertEqual(adjust["text"], "Shall I adjust your week around this constraint?")
        self.assertLess(out.index("Noted"), out.index(QUEUE_SENTINEL))
        self.assertNotIn(BUTTONS_SENTINEL, out)
        self.assertNotIn(QUEUE_DONE_LINE, out)

    def test_no_stores_nothing_and_offers_nothing(self):
        question, _prompt = self.asked(self._constraint())
        out = self.tap(question, "a2")
        self.assertIn("Okay — I won't note that one.", out)
        self.assertEqual(test_db.get_constraints(today_str(), None), [])
        self.assertNotIn(BUTTONS_SENTINEL, out)

    def test_a_constraint_the_coach_cannot_reach_brings_no_offer(self):
        question, _prompt = self.asked(self._constraint(days=40))
        out = self.tap(question, "a1")
        self.assertIn("Noted — I'll work around that", out)
        self.assertEqual(self.frames(out), [])

    def test_a_second_question_comes_when_the_first_is_answered(self):
        first, _prompt = self.asked({**self._constraint(), "new_signals": [self.SIGNAL]})
        self.assertIn("this constraint?", first["text"])
        [second] = self.frames(self.tap(first, "a2"))
        self.assertEqual(second["text"], "Shall I log this signal? “disturbed sleep” — today")
        out = self.tap(second, "a1")
        self.assertTrue(test_db.get_daily_signals(today_str(), today_str()))
        [adjust] = self.frames(out)
        self.assertEqual(adjust["text"], "Shall I adjust your week around this signal?")

    def test_a_category_close_to_one_in_use_is_offered_beside_it(self):
        """The terminal's ladder of two questions is one message with three answers
        (DESIGN_signal_extraction.md §6)."""
        question, _prompt = self.asked({"new_signals": [
            {"metric": "heatwave", "date": today_str(), "end_date": today_str(), "value": 38},
        ]})
        self.assertEqual(
            [b["label"] for b in question["buttons"]], ["Heat", "Heatwave (new)", "No"]
        )
        self.assertIn("“heat”, which I already use", question["text"])
        self.tap(question, "a1")
        [row] = test_db.get_daily_signals(today_str(), today_str())
        self.assertEqual(row["metric"], "heat")

    def test_a_question_past_its_dates_is_closed_without_being_asked(self):
        yesterday = self.future(-1)
        [item] = queue_candidates(
            [{"title": "no running", "start_date": yesterday, "end_date": yesterday}], [],
            yesterday, "", offer=True,
        )
        self.assertTrue(athlete_queue.settle_if_stale(item))
        self.assertEqual(test_db.get_queue_item(item["id"])["outcome"], athlete_queue.STALE)

    def test_a_preference_for_good_is_handed_to_the_operator_not_stored(self):
        code, out, _prompt = self._run({"new_constraints": [
            {"title": "never two workouts in a day", "open_ended": True},
        ]})
        self.assertEqual(code, 0)
        [question] = self.frames(out)
        # The sentence where a preference belongs opens the question (DESIGN_chat_questions.md
        # §4), so it is whole when it comes back the next morning.
        self.assertIn("forward this message", question["text"])
        self.assertTrue(question["text"].endswith("Shall I pass it to your coach?"))
        self.assertNotIn("forward this message", out.split(QUEUE_SENTINEL)[0])
        self.assertNotIn(BUTTONS_SENTINEL, out)


class CaptureAddGoalTest(_CaptureCase):
    """`bot capture add_goal` — §12.5: the goal row is captured, the plan for it is not."""

    def _run(self, extraction, answers=True, text="I want to run a half marathon"):
        return self.capture(["bot", "capture", "add_goal", text], extraction, answers)

    def test_a_confirmed_goal_is_created_and_the_plan_is_left_to_the_operator(self):
        target = self.future(120)
        code, out, _ = self._run({
            "title": "Half marathon", "target_date": target,
            "sports": ["running"], "date_type": "event",
        })
        self.assertEqual(code, 0)
        goals = test_db.get_objectives()
        self.assertEqual([g["title"] for g in goals], ["Half marathon"])
        self.assertEqual(goals[0]["target_date"], target)
        self.assertIn("from the computer", out)
        self.assertNotIn("plan generate", out)

    def test_a_missing_date_asks_instead_of_guessing_one(self):
        """Extraction transcribes; it never fills — a guessed date is exactly what a
        confirm-tap sails past (§12.2)."""
        code, out, prompt = self._run({
            "title": "Half marathon", "target_date": None, "sports": ["running"],
        })
        self.assertEqual(code, 0)
        self.assertIn("When is it?", out)
        self.assertEqual(prompt.asked, [], "a missing field asks, it does not confirm")
        self.assertEqual(test_db.get_objectives(), [])

    def test_an_off_enum_sport_is_dropped_rather_than_free_typed(self):
        code, out, _ = self._run({
            "title": "Half marathon", "target_date": self.future(120),
            "sports": ["jogging"],
        })
        self.assertEqual(code, 0)
        self.assertIn("Which sport", out)
        self.assertEqual(test_db.get_objectives(), [])

    def test_the_preview_shows_the_resolved_date_and_the_date_type_reading(self):
        code, out, prompt = self._run({
            "title": "Base building", "target_date": self.future(120),
            "sports": ["running"], "date_type": "horizon",
        }, answers=False)
        self.assertEqual(code, 0)
        # 'by ~' is the horizon reading — a wrong guess is visible in the first line (§12.5).
        [asked] = prompt.asked
        self.assertIn("by ~", asked)
        self.assertTrue(asked.endswith("Shall I set up this goal?"))
        self.assertEqual(test_db.get_objectives(), [])


class CaptureEditTest(_CaptureCase):
    """`bot capture edit_goal` / `edit_constraint` — §12.4: nomination, and the four
    ways it can land."""

    def _goal(self, title="Zurich Marathon", days=60):
        return test_db.add_objective(
            title=title, target_date=self.future(days), sport_type="running",
        )

    def _run(self, intent, extraction, text, answers=True, choice=None):
        return self.capture(["bot", "capture", intent, text], extraction, answers, choice)

    def test_a_clean_nomination_previews_the_real_row_then_writes(self):
        gid = self._goal()
        moved = self.future(90)
        code, out, prompt = self._run("edit_goal", {
            "kind": "goal", "id": gid, "changes": {"target_date": moved},
        }, "move my marathon to October 12")
        self.assertEqual(code, 0)
        # The question is drawn from the stored row, not from what the model believes it
        # says — which is what makes a wrong nomination die visibly (§12.4).
        self.assertIn("Your goal", prompt.text)
        self.assertIn("Zurich Marathon", prompt.text)
        self.assertIn("Shall I change this goal?", prompt.text)
        self.assertEqual(test_db.get_objective(gid)["target_date"], moved)

    def test_declining_writes_nothing_and_offers_the_other_rows(self):
        gid = self._goal()
        self._goal("Spring 10k", days=20)
        before = test_db.get_objective(gid)["target_date"]
        code, out, prompt = self._run("edit_goal", {
            "kind": "goal", "id": gid, "changes": {"target_date": self.future(90)},
        }, "move it", answers=False)
        self.assertEqual(code, 0)
        self.assertEqual(test_db.get_objective(gid)["target_date"], before)
        self.assertIn("Okay — nothing changed.", out)
        picker = prompt.asked[-1]
        self.assertTrue(picker.startswith("Which goal should I change?"))
        self.assertIn("Spring 10k", picker)
        self.assertNotIn("Zurich Marathon", picker)

    def test_several_candidates_become_a_picker_that_re_captures_pinned(self):
        first = self._goal("Spring 10k", days=20)
        second = self._goal("Autumn 10k", days=200)
        code, out, prompt = self._run("edit_goal", {
            "kind": "goal", "id": second, "candidate_ids": [first, second],
            "changes": {"title": "10k"},
        }, "rename the 10k", choice=str(first))
        self.assertEqual(code, 0)
        # The athlete picks first; the pick does not execute the edit, it re-enters the
        # capture with the row pinned and asks the question about that row.
        picker, question = prompt.asked
        self.assertTrue(picker.startswith("Which goal did you mean?"))
        self.assertIn("Autumn 10k", picker)
        self.assertIn("Spring 10k", question)
        self.assertEqual(test_db.get_objective(first)["title"], "10k")
        self.assertEqual(test_db.get_objective(second)["title"], "Autumn 10k")

    def test_a_session_shaped_ask_saves_the_hand_off_question_not_a_picker(self):
        """The question is saved and sent, and the capture ends: nothing waits on the
        athlete and nothing reaches the coach yet (DESIGN_long_runs_beside_chat.md §5)."""
        self._goal()
        save_workout(test_db, self.future(3), "running", "Long run", duration_minutes=90)
        session = test_db.get_workouts(
            start_date=self.future(3), end_date=self.future(3)
        )[0]
        prompt = self.prompt(True)
        started_from(self, "chat")
        with patch(
            "stamind.openrouter.OpenRouterClient.complete",
            return_value={"kind": "session", "id": session["id"]},
        ), patch("stamind.cli.workouts.adapt.run_workout_adapt") as adapt:
            code, out, _ = run_cli(
                ["bot", "capture", "edit_goal", "move my long run to Sunday"]
            )
        self.assertEqual(code, 0)
        self.assertEqual(prompt.asked, [])
        adapt.assert_not_called()
        [question] = [json.loads(line[len(QUEUE_SENTINEL):]) for line in out.split("\n")
                      if line.startswith(QUEUE_SENTINEL)]
        # The wrong-domain picker — goals answering a question about a session — never
        # appears; the hand-off does (§12.4).
        self.assertIn("Long run", question["text"])
        self.assertIn("pass it to your coach", question["text"])
        # The dropped reading is named: the router's "sounds like a change to a goal"
        # echo is still on screen and this line is its correction — and the line says
        # what a "yes" sets in motion (§12.4).
        self.assertIn("I don't see a goal for that", question["text"])
        self.assertIn("reread the coming days", question["text"])
        self.assertEqual([b["label"] for b in question["buttons"]], ["✅ Yes", "✖️ No"])
        self.assertNotIn(BUTTONS_SENTINEL, out)

    def test_nothing_matching_lands_where_a_no_find_does(self):
        self._goal()
        code, out, _ = self._run(
            "edit_goal", {"kind": "none", "id": None}, "change the thing"
        )
        self.assertEqual(code, 0)
        self.assertIn("I'm not sure what to do with that one", out)

    def test_a_constraint_edit_moves_its_window_and_names_no_command(self):
        cid = test_db.add_constraint(
            title="knee flare", start_date=today_str(), end_date=self.future(7),
            rest=0, description=None, replan=0, source="message",
        )
        moved = self.future(30)
        code, out, prompt = self._run("edit_constraint", {
            "kind": "constraint", "id": cid, "changes": {"end_date": moved},
        }, "the knee thing runs to the end of the month")
        self.assertEqual(code, 0)
        self.assertEqual(test_db.get_constraint(cid)["end_date"], moved)
        self.assertIn("Your constraint", out + prompt.text)
        self.assertNotIn("constraint edit", out)
        self.assertNotIn("plan generate", out)

    def test_a_tier_only_change_is_refused_the_way_a_no_match_is(self):
        """`--rest` and `--replan` stay expert vocabulary, so an extraction naming only
        those has nothing this surface may write (§12.4)."""
        cid = test_db.add_constraint(
            title="knee flare", start_date=today_str(), end_date=today_str(),
            rest=0, description=None, replan=0, source="message",
        )
        code, out, _ = self._run("edit_constraint", {
            "kind": "constraint", "id": cid, "changes": {"rest": True, "replan": True},
        }, "make it a proper rest week")
        self.assertEqual(code, 0)
        self.assertEqual(test_db.get_constraint(cid)["rest"], 0)
        self.assertEqual(test_db.get_constraint(cid)["replan"], 0)
        self.assertIn("I'm not sure what to do with that one", out)


class CaptureSettingTest(_CaptureCase):
    """`bot capture change_setting` — §12.7: an allowlist, not a surface."""

    def _run(self, extraction, answers=True, text="can you message me at 7 instead?"):
        return self.capture(
            ["bot", "capture", "change_setting", text], extraction, answers
        )

    def test_an_allowlisted_key_is_written_and_read_back_as_its_effect(self):
        from stamind import settings
        code, out, prompt = self._run({"key": "morning-time", "value": "07:00"})
        self.assertEqual(code, 0)
        self.assertEqual(settings.morning_time(), "07:00")
        # The confirm names what she will notice, not the key (§12.7).
        self.assertIn("open your day at 07:00", prompt.text)
        self.assertNotIn("morning-time", prompt.text)
        self.assertNotIn("morning-time set to", out)

    def test_an_off_list_key_is_refused_honestly_and_names_the_operator(self):
        from stamind import settings
        code, out, prompt = self._run({"key": "thinking-model", "value": "3"},
                                      text="use a smarter model")
        self.assertEqual(code, 0)
        self.assertIn("not me", out)
        # A boundary, not the §5.3 unclear fallback, and nothing asked or written.
        self.assertNotIn("didn't quite get that", out)
        self.assertEqual(prompt.asked, [])
        self.assertIsNone(settings.stored(settings.THINKING_MODEL))

    def test_an_operator_shaped_key_does_not_widen_the_guardrail(self):
        from stamind import settings
        code, out, _ = self._run({"key": "adapt-first", "value": "on"})
        self.assertEqual(code, 0)
        self.assertIsNone(settings.stored(settings.ADAPT_FIRST))
        self.assertIn("not me", out)

    def test_a_value_the_setting_cannot_read_asks_rather_than_writing(self):
        from stamind import settings
        code, out, _ = self._run({"key": "morning-time", "value": "breakfast"})
        self.assertEqual(code, 0)
        self.assertIsNone(settings.stored(settings.MORNING_TIME))
        self.assertIn("didn't catch what to set it to", out)

    def test_declining_leaves_the_setting_alone(self):
        from stamind import settings
        code, _, _ = self._run({"key": "push", "value": "off"}, answers=False)
        self.assertEqual(code, 0)
        self.assertIsNone(settings.stored(settings.PUSH))

    def test_the_evening_hour_reads_back_as_its_effect(self):
        """"Don't message me after 8pm" (DESIGN_athlete_queue.md §13.5, choice 17)."""
        from stamind import settings
        code, _, prompt = self._run({"key": "evening-time", "value": "20:00"},
                                    text="don't message me after 8pm")
        self.assertEqual(code, 0)
        self.assertEqual(settings.evening_time(), "20:00")
        self.assertIn("From 20:00 I'll stay quiet until the morning, unless you write to me "
                      "first. Shall I change this setting?", prompt.text)
        self.assertNotIn("evening-time", prompt.text)

    def test_the_learning_questions_switch_reads_back_as_its_effect(self):
        """"Stop asking me about that stuff" (DESIGN_learning_doubt_nudge.md §3.4)."""
        from stamind import settings
        code, _, prompt = self._run({"key": "learning-questions", "value": "off"},
                                    text="stop asking me about that stuff")
        self.assertEqual(code, 0)
        self.assertFalse(settings.learning_questions())
        self.assertIn("I'll stop asking about what I've learned about you, and go by what I "
                      "see instead.", prompt.text)
        self._run({"key": "learning-questions", "value": "on"}, text="you can ask me again")
        self.assertTrue(settings.learning_questions())

    def test_terse_is_no_setting_any_more(self):
        """Short proposals are the rule for everyone, so "your messages are too long" has
        nothing left to switch (DESIGN_short_messages.md §8)."""
        from stamind import runtime
        code, out, prompt = self._run({"key": "terse", "value": "on"},
                                      text="your messages are too long, keep it short")
        self.assertEqual(code, 0)
        self.assertIn("not me", out)
        self.assertEqual(prompt.asked, [])
        self.assertIsNone(runtime.db.get_setting("coach_terse"))


class CaptureTestResultTest(_CaptureCase):
    """`bot capture test_result` — DESIGN_benchmark_from_chat.md §3: the message is read
    into `benchmark record`, whose own confirm is the read-back."""

    def setUp(self):
        super().setUp()
        test_db.add_benchmark_result(
            date="2026-01-10", sport_type="cycling", anchor_kind="ftp", value=235.0,
            unit="W", source="test",
        )
        self.session = save_workout(
            test_db, today_str(), "cycling", "20-min FTP test", benchmark_type="ftp_20min",
        )

    def _run(self, extraction, answers=True, text="Did the ramp test instead, 250"):
        return self.capture(["bot", "capture", "test_result", text], extraction, answers)

    def _extraction(self, **fields):
        data = {"kind": "ftp", "value": "250", "sport": None, "date": None,
                "performed": True, "session_id": self.session,
                "note": "ramp test instead, legs were heavy"}
        data.update(fields)
        return data

    def test_a_confirmed_result_is_filed_under_the_listed_test(self):
        code, out, prompt = self._run(self._extraction())
        self.assertEqual(code, 0)
        row = test_db.get_latest_benchmark("ftp")
        self.assertEqual((row["value"], row["sport_type"], row["source"]),
                         (250.0, "cycling", "test"))
        self.assertEqual((row["workout_id"], row["date"]), (self.session, today_str()))
        self.assertEqual(row["note"], "ramp test instead, legs were heavy")
        self.assertEqual(prompt.asked, [
            "Your FTP from today's test, “20-min FTP test”: 250 W, up from 235 W (+6.4%). "
            "Note: “ramp test instead, legs were heavy”. Shall I write down this test result?"
        ])
        self.assertIn("Written down 💪", out)
        # 6.4% is past the 5% replan band: the operator's line, never the command (§3).
        self.assertIn(f"{config.telegram_operator_name} takes care of that", " ".join(out.split()))
        self.assertNotIn("plan generate", out)

    def test_declining_writes_nothing(self):
        code, out, _ = self._run(self._extraction(), answers=False)
        self.assertEqual(code, 0)
        self.assertEqual(test_db.get_latest_benchmark("ftp")["value"], 235.0)
        self.assertIn("nothing written down", out)

    def test_no_kind_asks_which_test_instead_of_guessing_one(self):
        code, out, prompt = self._run(self._extraction(kind=None), text="250")
        self.assertEqual(code, 0)
        self.assertIn("Which test was it", out)
        self.assertEqual(prompt.asked, [])

    def test_e1rm_is_not_offered_from_chat(self):
        _, out, _ = self._run(self._extraction(kind="e1rm", value="140"))
        self.assertIn("Which test was it", out)
        self.assertIsNone(test_db.get_latest_benchmark("e1rm"))

    def test_a_value_that_is_not_a_number_asks_for_it(self):
        _, out, prompt = self._run(self._extraction(value="quite a lot"))
        self.assertIn("in W?", out)
        self.assertEqual(prompt.asked, [])

    def test_a_kind_the_sport_is_not_tested_on_asks_again(self):
        _, out, prompt = self._run(self._extraction(sport="swimming", session_id=None))
        self.assertIn("isn't something swimming is tested on", out)
        self.assertEqual(prompt.asked, [])

    def test_a_number_stated_on_its_own_is_a_manual_row_dated_today(self):
        """No test named, none said to be done: the weaker default the CLI uses (§3)."""
        self._run(self._extraction(session_id=None, performed=False, note=None),
                  text="my FTP is 250")
        row = test_db.get_latest_benchmark("ftp")
        self.assertEqual((row["source"], row["workout_id"], row["note"]),
                         ("manual", None, None))
        self.assertEqual((row["date"], row["sport_type"]), (today_str(), "cycling"))

    def test_a_session_the_capture_was_not_shown_is_ignored(self):
        self._run(self._extraction(session_id=self.session + 999, performed=False))
        self.assertIsNone(test_db.get_latest_benchmark("ftp")["workout_id"])


class TestResultQuestionTest(_CaptureCase):
    """The `test_result` queue kind — DESIGN_benchmark_from_chat.md §4."""

    def setUp(self):
        super().setUp()
        env = patch.dict(os.environ, {"STAMIND_FRONTEND": "json"})
        env.start()
        self.addCleanup(env.stop)
        self.day = self.future(-1)
        self.session = save_workout(
            test_db, self.day, "cycling", "20-min FTP test", benchmark_type="ftp_20min",
        )
        test_result.ask_about(test_db.get_workout_by_id(self.session))
        [self.item] = test_db.waiting_queue_items()

    def _tap(self, answers=True, typed="250"):
        self.prompt(answers)
        extraction = {"kind": "ftp", "value": "250", "performed": False,
                      "session_id": None, "note": None}
        with patch("stamind.openrouter.OpenRouterClient.complete", return_value=extraction):
            code, out, _ = run_cli(["bot", "queue", str(self.item["id"]), "a1", "--text", typed])
        return code, out

    def test_the_companion_asks_with_the_three_buttons(self):
        text, buttons = queue_chat_message(self.item, 1)
        self.assertIn("“20-min FTP test” go? Tell me the number it gave you", text)
        self.assertEqual([b["label"] for b in buttons],
                         ["Tell me the number", "Nothing to record", "🕐 Not now"])

    def _confirmation(self, out):
        [frame] = [json.loads(line[len(QUEUE_SENTINEL):]) for line in out.split("\n")
                   if line.startswith(QUEUE_SENTINEL)]
        return frame

    def test_the_number_is_filed_under_the_pinned_session(self):
        code, out = self._tap()
        self.assertEqual(code, 0)
        confirmation = self._confirmation(out)
        self.assertIsNone(test_db.get_latest_benchmark("ftp"))
        _code, out, _ = run_cli(["bot", "queue", str(confirmation["id"]), "a1"])
        row = test_db.get_latest_benchmark("ftp")
        self.assertEqual((row["value"], row["workout_id"], row["date"], row["source"]),
                         (250.0, self.session, self.day, "test"))
        self.assertTrue(athlete_queue.settle_if_stale(test_db.get_queue_item(self.item["id"])))

    def test_a_no_on_the_confirmation_leaves_the_question_waiting(self):
        _, out = self._tap()
        confirmation = self._confirmation(out)
        _code, out, _ = run_cli(["bot", "queue", str(confirmation["id"]), "a2"])
        self.assertIn("Okay — nothing written down.", out)
        self.assertIsNone(test_db.get_latest_benchmark("ftp"))
        self.assertIsNone(test_db.get_queue_item(self.item["id"])["closed_at"])

    def test_a_failed_call_while_answering_asks_nothing_new(self):
        self.prompt(True)
        with patch("stamind.openrouter.OpenRouterClient.complete",
                   side_effect=ValueError("no api key")):
            _code, out, _ = run_cli(["bot", "queue", str(self.item["id"]), "a1", "--text", "236"])
        self.assertIn("Nothing recorded.", out)
        self.assertEqual(
            [item["kind"] for item in test_db.waiting_queue_items()], [test_result.KIND]
        )

    def test_a_number_the_chat_cannot_use_asks_again(self):
        extraction = {"kind": "ftp", "value": "fine", "performed": False,
                      "session_id": None, "note": None}
        self.prompt(True)
        with patch("stamind.openrouter.OpenRouterClient.complete", return_value=extraction):
            _code, out, _ = run_cli(
                ["bot", "queue", str(self.item["id"]), "a1", "--text", "it went fine"]
            )
        self.assertIn("Nothing recorded.", out)
        item = test_db.get_queue_item(self.item["id"])
        self.assertIsNone(item["closed_at"])
        self.assertEqual(item["ready_at"], self.item["ready_at"])

    def test_a_result_recorded_another_way_settles_the_question(self):
        test_db.add_benchmark_result(
            date=today_str(), sport_type="cycling", anchor_kind="ftp", value=250.0,
            unit="W", source="manual",
        )
        self.assertTrue(athlete_queue.settle_if_stale(self.item))

    def test_a_cancelled_test_settles_the_question(self):
        save_workout(test_db, self.day, "cycling", "20-min FTP test", removed=True)
        self.assertTrue(athlete_queue.settle_if_stale(self.item))


