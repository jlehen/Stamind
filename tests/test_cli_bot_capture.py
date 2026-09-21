"""`bot capture <intent>` tests: the write path behind the free-text router.

One extraction per run, mocked; what the capture ASKED is read off a scripted prompt,
because for a capture the question is the preview (DESIGN_bot_simple_frontend.md §12.2).
The views and the router itself are in `test_cli_bot.py`.
"""
import os
import unittest
from unittest.mock import MagicMock, patch

from tests.helpers import clear_all_tables, run_cli, rebind_test_db, save_workout
from tests import test_db_path

TEST_DB_PATH = test_db_path("test_trainmate_cli_bot_capture.db")

from trainmate.db import Database
import trainmate_cli  # noqa: F401  (registers the bot parser)

from trainmate import runtime
from trainmate.config import config
from trainmate.sentinels import BUTTONS_SENTINEL
from trainmate.clock import today_str

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

    def __init__(self, answers=True):
        self.asked = []
        self._script = list(answers) if isinstance(answers, (list, tuple)) else None
        self._always = None if self._script is not None else bool(answers)

    def confirm(self, message, *, default=False, danger=False):
        self.asked.append(message)
        if self._script is None:
            return self._always
        return self._script.pop(0) if self._script else False

    def choose(self, message, choices, *, default=None):
        self.asked.append(message)
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
        patcher = patch.dict(os.environ, {"TRAINMATE_RENDER": "simple"})
        patcher.start()
        self.addCleanup(patcher.stop)

    def prompt(self, answers=True):
        prompt = _ScriptedPrompt(answers)
        runtime.prompt = prompt
        # An assignment on `runtime` shadows the accessor for the whole process.
        self.addCleanup(runtime.reset, "prompt")
        return prompt

    def capture(self, argv, extraction, answers=True):
        """Runs one `bot capture …`; returns (exit code, stdout, the prompt)."""
        prompt = self.prompt(answers)
        with patch(
            "trainmate.openrouter.OpenRouterClient.complete",
            **({"side_effect": extraction} if isinstance(extraction, Exception)
               else {"return_value": extraction}),
        ):
            code, out, _ = run_cli(argv)
        return code, out, prompt

    def future(self, days):
        from datetime import date, timedelta
        return (date.fromisoformat(today_str()) + timedelta(days=days)).isoformat()



class CaptureNoteTest(_CaptureCase):
    """`bot capture note` — §12.3: the note inbox that asks before storing, and offers
    the coach instead of riding it."""

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

    def _run(self, extraction, answers=True):
        return self.capture(["bot", "capture", "note", self.NOTE], extraction, answers)

    def _constraint(self):
        return {"new_constraints": [
            {"title": "no running", "start_date": today_str(),
             "end_date": today_str()},
        ]}

    def test_a_confirmed_constraint_is_stored_and_the_coach_is_offered(self):
        code, out, _ = self._run(self._constraint())
        self.assertEqual(code, 0)
        self.assertEqual(
            [c["title"] for c in test_db.get_constraints(today_str(), None)],
            ["no running"],
        )
        # The coach is an offer, not a toll: nothing here ran an adaptation.
        self.assertIn(BUTTONS_SENTINEL, out)
        self.assertIn("Adjust my week around it", out)
        self.assertIn("workout adapt", out)

    def test_a_confirmed_signal_gets_the_offer_too(self):
        """Amended 2026-09-02: the record points backward, but the athlete reporting one
        expects forward notice, so the gap is one visible tap wide (§12.3)."""
        code, out, _ = self._run({"new_signals": [
            {"metric": "disturbed_sleep", "date": today_str(), "end_date": today_str()},
        ]})
        self.assertEqual(code, 0)
        self.assertTrue(test_db.get_daily_signals(today_str(), today_str()))
        self.assertIn("Adjust my week around it", out)

    def test_nothing_found_offers_the_message_as_written(self):
        code, out, _ = self._run({"new_constraints": [], "new_signals": []})
        self.assertEqual(code, 0)
        self.assertIn("Send it to your coach as written", out)
        # The exact words ride along — that is the lane this button exists for.
        self.assertIn(self.NOTE, out)
        self.assertEqual(test_db.get_constraints(today_str(), None), [])

    def test_an_extraction_failure_lands_where_a_no_find_does(self):
        code, out, _ = self._run(ValueError("no api key"))
        self.assertEqual(code, 0)
        self.assertIn("Send it to your coach as written", out)

    def test_a_rule_for_good_is_handed_to_the_operator_not_stored(self):
        """2026-09-16: "never two workouts in a day" has no dates, so it is not a
        constraint. She is told whose it is, her words are quoted so she can forward the
        message, and today's half stays one tap away (§12.3)."""
        code, out, prompt = self._run({"new_constraints": [
            {"title": "never two workouts in a day", "start_date": None,
             "end_date": None, "open_ended": True},
        ]})
        self.assertEqual(code, 0)
        self.assertEqual(test_db.get_constraints(today_str(), None), [])
        self.assertNotIn("Shall I remember that?", prompt.text)
        # The reply is wrapped for the chat; compare on one logical line.
        said = " ".join(out.split())
        self.assertIn("not something for the next few days", said)
        self.assertIn(f"Ask {config.telegram_operator_name} to record this", said)
        self.assertIn("forward this message", said)
        self.assertIn(f"“{self.NOTE}”", said)
        self.assertIn("Send it to your coach as written", out)

    def test_a_dated_rule_beside_an_open_ended_one_is_still_stored(self):
        code, out, _ = self._run({"new_constraints": [
            {"title": "never two workouts in a day", "open_ended": True},
        ] + self._constraint()["new_constraints"]})
        self.assertEqual(code, 0)
        self.assertEqual(
            [c["title"] for c in test_db.get_constraints(today_str(), None)],
            ["no running"],
        )
        self.assertIn("forward this message", out)
        self.assertIn("Adjust my week around it", out)
        self.assertNotIn("Send it to your coach as written", out)

    def test_declining_stores_nothing_and_presses_no_further(self):
        code, out, _ = self._run(self._constraint(), answers=False)
        self.assertEqual(code, 0)
        self.assertEqual(test_db.get_constraints(today_str(), None), [])
        self.assertNotIn(BUTTONS_SENTINEL, out)

    def test_the_confirm_and_the_outcome_speak_the_companion_voice(self):
        """The shared helper (§12.10) asks the same question `workout adapt -m` asks,
        worded by the active renderer — here the companion one (§6: no IDs, no ISO)."""
        code, out, prompt = self._run(self._constraint())
        self.assertIn("Shall I remember that?", prompt.text)
        self.assertNotIn("Add constraint:", prompt.text)
        self.assertNotIn(today_str(), prompt.text)
        self.assertIn("Noted — I'll work around that", out)
        self.assertNotIn("Captured constraint [", out)


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
        code, out, _ = self._run({
            "title": "Base building", "target_date": self.future(120),
            "sports": ["running"], "date_type": "horizon",
        }, answers=False)
        self.assertEqual(code, 0)
        # 'by ~' is the horizon reading — a wrong guess is visible in the first line (§12.5).
        self.assertIn("by ~", out)
        self.assertEqual(test_db.get_objectives(), [])


class CaptureEditTest(_CaptureCase):
    """`bot capture edit_goal` / `edit_constraint` — §12.4: nomination, and the four
    ways it can land."""

    def _goal(self, title="Zurich Marathon", days=60):
        return test_db.add_objective(
            title=title, target_date=self.future(days), sport_type="running",
        )

    def _run(self, intent, extraction, text, answers=True, pinned=None):
        argv = ["bot", "capture", intent, text]
        if pinned is not None:
            argv += ["--id", str(pinned)]
        return self.capture(argv, extraction, answers)

    def test_a_clean_nomination_previews_the_real_row_then_writes(self):
        gid = self._goal()
        moved = self.future(90)
        code, out, prompt = self._run("edit_goal", {
            "kind": "goal", "id": gid, "changes": {"target_date": moved},
        }, "move my marathon to October 12")
        self.assertEqual(code, 0)
        # The preview is drawn from the stored row, not from what the model believes it
        # says — which is what makes a wrong nomination die visibly (§12.4).
        self.assertIn("Your goal", out)
        self.assertIn("Zurich Marathon", out)
        self.assertIn("Shall I make that change?", prompt.text)
        self.assertEqual(test_db.get_objective(gid)["target_date"], moved)

    def test_declining_writes_nothing_and_offers_the_other_rows(self):
        gid = self._goal()
        other = self._goal("Spring 10k", days=20)
        before = test_db.get_objective(gid)["target_date"]
        code, out, _ = self._run("edit_goal", {
            "kind": "goal", "id": gid, "changes": {"target_date": self.future(90)},
        }, "move it", answers=False)
        self.assertEqual(code, 0)
        self.assertEqual(test_db.get_objective(gid)["target_date"], before)
        self.assertIn("Spring 10k", out)
        self.assertIn(f"--id {other}", out)

    def test_several_candidates_become_a_picker_that_re_captures_pinned(self):
        first = self._goal("Spring 10k", days=20)
        second = self._goal("Autumn 10k", days=200)
        code, out, prompt = self._run("edit_goal", {
            "kind": "goal", "id": first, "candidate_ids": [first, second],
            "changes": {"title": "10k"},
        }, "rename the 10k")
        self.assertEqual(code, 0)
        self.assertIn(BUTTONS_SENTINEL, out)
        self.assertEqual(prompt.asked, [], "the athlete picks before anything is asked")
        # A leaf does not execute the edit: it re-enters the capture with the row pinned.
        self.assertIn(f"bot capture edit_goal --id {first}", out)
        self.assertIn(f"bot capture edit_goal --id {second}", out)
        self.assertEqual(test_db.get_objective(first)["title"], "Spring 10k")

    def test_a_pinned_re_capture_goes_straight_to_the_preview(self):
        gid = self._goal("Spring 10k", days=20)
        code, out, _ = self._run("edit_goal", {
            "kind": "goal", "id": gid, "changes": {"title": "Spring 10k (fast)"},
        }, "rename the 10k", pinned=gid)
        self.assertEqual(code, 0)
        self.assertNotIn(BUTTONS_SENTINEL, out)
        self.assertEqual(test_db.get_objective(gid)["title"], "Spring 10k (fast)")

    def test_a_session_shaped_ask_is_handed_to_the_coach_not_to_a_picker(self):
        self._goal()
        save_workout(test_db, self.future(3), "running", "Long run", duration_minutes=90)
        session = test_db.get_workouts(
            start_date=self.future(3), end_date=self.future(3)
        )[0]
        prompt = self.prompt(True)
        with patch(
            "trainmate.openrouter.OpenRouterClient.complete",
            return_value={"kind": "session", "id": session["id"]},
        ), patch("trainmate.cli.bot.edit._hand_off_to_coach") as handoff:
            code, out, _ = run_cli(
                ["bot", "capture", "edit_goal", "move my long run to Sunday"]
            )
        self.assertEqual(code, 0)
        # The wrong-domain picker — goals answering a question about a session — never
        # appears; the hand-off does (§12.4).
        self.assertIn("Long run", prompt.text)
        self.assertIn("pass it to your coach", prompt.text)
        # The dropped reading is named: the router's "sounds like a change to a goal"
        # echo is still on screen and this line is its correction — and the line says
        # what a "yes" sets in motion (§12.4).
        self.assertIn("I don't see a goal for that", prompt.text)
        self.assertIn("reread the coming days", prompt.text)
        self.assertNotIn(BUTTONS_SENTINEL, out)
        handoff.assert_called_once_with("move my long run to Sunday")

    def test_nothing_matching_falls_back_to_the_send_to_coach_offer(self):
        self._goal()
        code, out, _ = self._run(
            "edit_goal", {"kind": "none", "id": None}, "change the thing"
        )
        self.assertEqual(code, 0)
        self.assertIn("Send it to your coach as written", out)

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
        self.assertIn("Your rule", out + prompt.text)
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
        self.assertIn("Send it to your coach as written", out)


class CaptureSettingTest(_CaptureCase):
    """`bot capture change_setting` — §12.7: an allowlist, not a surface."""

    def _run(self, extraction, answers=True, text="can you message me at 7 instead?"):
        return self.capture(
            ["bot", "capture", "change_setting", text], extraction, answers
        )

    def test_an_allowlisted_key_is_written_and_read_back_as_its_effect(self):
        from trainmate import settings
        code, out, prompt = self._run({"key": "morning-time", "value": "07:00"})
        self.assertEqual(code, 0)
        self.assertEqual(settings.morning_time(), "07:00")
        # The confirm names what she will notice, not the key (§12.7).
        self.assertIn("open your day at 07:00", prompt.text)
        self.assertNotIn("morning-time", prompt.text)
        self.assertNotIn("morning-time set to", out)

    def test_an_off_list_key_is_refused_honestly_and_names_the_operator(self):
        from trainmate import settings
        code, out, prompt = self._run({"key": "coach-model", "value": "3"},
                                      text="use a smarter model")
        self.assertEqual(code, 0)
        self.assertIn("not me", out)
        # A boundary, not the §5.3 unclear fallback, and nothing asked or written.
        self.assertNotIn("didn't quite get that", out)
        self.assertEqual(prompt.asked, [])
        self.assertIsNone(settings.stored(settings.COACH_MODEL))

    def test_an_operator_shaped_key_does_not_widen_the_guardrail(self):
        from trainmate import settings
        code, out, _ = self._run({"key": "adapt-first", "value": "on"})
        self.assertEqual(code, 0)
        self.assertIsNone(settings.stored(settings.ADAPT_FIRST))
        self.assertIn("not me", out)

    def test_a_value_the_setting_cannot_read_asks_rather_than_writing(self):
        from trainmate import settings
        code, out, _ = self._run({"key": "morning-time", "value": "breakfast"})
        self.assertEqual(code, 0)
        self.assertIsNone(settings.stored(settings.MORNING_TIME))
        self.assertIn("didn't catch what to set it to", out)

    def test_declining_leaves_the_setting_alone(self):
        from trainmate import settings
        code, _, _ = self._run({"key": "push", "value": "off"}, answers=False)
        self.assertEqual(code, 0)
        self.assertIsNone(settings.stored(settings.PUSH))

    def test_the_learning_questions_switch_reads_back_as_its_effect(self):
        """"Stop asking me about that stuff" (DESIGN_learning_doubt_nudge.md §3.4)."""
        from trainmate import settings
        code, _, prompt = self._run({"key": "learning-questions", "value": "off"},
                                    text="stop asking me about that stuff")
        self.assertEqual(code, 0)
        self.assertFalse(settings.learning_questions())
        self.assertIn("I'll stop asking about what I've learned about you, and go by what I "
                      "see instead.", prompt.text)
        self._run({"key": "learning-questions", "value": "on"}, text="you can ask me again")
        self.assertTrue(settings.learning_questions())

    def test_the_terse_switch_reads_back_as_its_effect(self):
        """"Your messages are too long" (DESIGN_output_verbosity.md §9)."""
        from trainmate import settings
        code, _, prompt = self._run({"key": "terse", "value": "on"},
                                    text="your messages are too long, keep it short")
        self.assertEqual(code, 0)
        self.assertTrue(settings.terse())
        self.assertIn("When I change your week, I'll keep it short.", prompt.text)
        self.assertNotIn("terse", prompt.text)


