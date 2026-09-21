"""What a running command puts in the journal: the output verbs print where
they always did and record what they printed (DESIGN_logging.md §5.1), and
the athlete's answer is filed against the run that asked for it (§5.6).
"""
import io
import json
import sys
import unittest
from unittest.mock import patch

from stamind import journal
from stamind.prompt import PromptCancelled
from tests.helpers import bind_test_db
from tests import test_db_path
from tests.test_journal import JournalTestCase

TEST_DB_PATH = test_db_path("test_journal_records.db")


def setUpModule():
    """The writer never opens a database, but rendering a stamp back reads the athlete's
    zone, which is a settings row — so this module binds one of its own (§4)."""
    bind_test_db(TEST_DB_PATH)


class TestOutputVerbs(JournalTestCase):
    """step/warn/fail print where they always did, and record what they printed (§5.1)."""

    def test_step_prints_like_an_aside_and_journals_it(self):
        from stamind.output import step
        buffer = io.StringIO()
        with patch.object(sys, "stdout", buffer):
            step("Auto-syncing Garmin 2026-08-22..2026-08-24...")
        self.assertIn("Auto-syncing Garmin", buffer.getvalue())
        (rec,) = self.records()
        self.assertEqual(rec["ev"], "note")
        self.assertEqual(rec["lvl"], "info")

    def test_warn_and_fail_carry_their_prefix_and_level(self):
        from stamind.output import fail, warn
        buffer = io.StringIO()
        with patch.object(sys, "stdout", buffer):
            warn("Garmin sync failed. Continuing with cached data.")
            fail("Google Calendar event delete failed: boom")
        printed = buffer.getvalue()
        self.assertIn("Warning: Garmin sync failed.", printed)
        self.assertIn("Error: Google Calendar event delete failed", printed)
        self.assertEqual([rec["lvl"] for rec in self.records()], ["warn", "error"])

    def test_a_journalled_message_carries_no_colour_codes(self):
        from stamind.text import cmd
        from stamind.output import warn
        with patch("stamind.text.is_color_enabled", return_value=True):
            with patch.object(sys, "stdout", io.StringIO()):
                warn("run " + cmd("data pull") + " in a terminal")
        self.assertEqual(self.records()[0]["msg"], "run 'data pull' in a terminal")


class TestPromptAnswers(JournalTestCase):
    """What the athlete answered, on the run that asked (DESIGN_logging.md §5.6).

    A declined `workout generate` finishes normally, so `run.end` says `ok` exactly as an
    applied one does; these records are the only thing that tells the two apart."""

    def setUp(self) -> None:
        super().setUp()
        from stamind.prompt import TtyPrompt
        self.prompt = TtyPrompt()

    def _answers(self):
        return [rec for rec in self.records() if rec["ev"] == "note"]

    def test_a_declined_question_is_recorded_on_the_run_that_asked_it(self):
        run_id = journal.start_run(["workout", "generate"], source="cli")
        with patch("builtins.input", return_value="n"):
            answered = self.prompt.confirm("Schedule these 7 workout(s)?")
        journal.end_run("ok")
        self.assertFalse(answered)
        (rec,) = self._answers()
        self.assertEqual(rec["run"], run_id)
        self.assertEqual(rec["lvl"], "info")
        self.assertEqual(rec["msg"], "Schedule these 7 workout(s)? → no")
        self.assertIs(rec["d"]["answer"], False)

    def test_declining_leaves_the_outcome_ok_so_the_note_is_the_only_signal(self):
        journal.start_run(["workout", "generate"], source="cli")
        with patch("builtins.input", return_value="n"):
            self.prompt.confirm("Regenerate?")
        journal.end_run("ok")
        end = [rec for rec in self.records() if rec["ev"] == "run.end"][0]
        self.assertEqual(end["d"]["outcome"], "ok")
        self.assertEqual(end["d"]["warns"], 0)
        self.assertIs(self._answers()[0]["d"]["answer"], False)

    def test_no_input_is_marked_defaulted_and_not_read_as_a_decision(self):
        """EOF is cron or a pipe, not an athlete saying no (`TtyPrompt.confirm`)."""
        journal.start_run(["workout", "generate"], source="push")
        with patch("builtins.input", side_effect=EOFError):
            self.prompt.confirm("Regenerate?", default=False)
        journal.end_run("ok")
        (rec,) = self._answers()
        self.assertIs(rec["d"]["answer"], False)
        self.assertIs(rec["d"]["defaulted"], True)

    def test_an_answered_question_carries_no_defaulted_field_at_all(self):
        journal.start_run(["workout", "generate"], source="cli")
        with patch("builtins.input", return_value="y"):
            self.prompt.confirm("Regenerate?")
        journal.end_run("ok")
        self.assertNotIn("defaulted", self._answers()[0]["d"])

    def test_the_question_is_flattened_to_one_line_and_stripped_of_colour(self):
        from stamind.text import yellow
        journal.start_run(["workout", "generate"], source="cli")
        with patch("stamind.text.is_color_enabled", return_value=True):
            with patch("builtins.input", return_value="y"):
                self.prompt.confirm(yellow("Proceed anyway?\nThis rebuilds  the week."))
        journal.end_run("ok")
        self.assertEqual(
            self._answers()[0]["msg"], "Proceed anyway? This rebuilds the week. → yes"
        )

    def test_a_choice_records_the_value_it_resolved_to(self):
        from stamind.prompt import Choice
        choices = [Choice("demote", "Demote it"), Choice("keep", "Keep it")]
        journal.start_run(["data", "reflect"], source="cli")
        with patch.object(sys, "stdout", io.StringIO()):
            with patch("builtins.input", return_value="2"):
                chosen = self.prompt.choose("Apply the demotion?", choices, default="skip")
        journal.end_run("ok")
        self.assertEqual(chosen, "keep")
        self.assertEqual(self._answers()[0]["d"]["answer"], "keep")

    def test_a_cancelled_prompt_names_the_question_that_was_still_open(self):
        """`cancelled` says a run stopped; this says what it stopped on (§5.6)."""
        from stamind.prompt import JsonPrompt, PromptCancelled
        answer = json.dumps({"v": 1, "id": "p1", "cancelled": True}) + "\n"
        prompt = JsonPrompt(out=io.StringIO(), inp=io.StringIO(answer))
        journal.start_run(["plan", "generate"], source="bot")
        with self.assertRaises(PromptCancelled):
            prompt.confirm("Apply this new periodization strategy?")
        journal.end_run("cancelled", exit_code=130)
        (rec,) = self._answers()
        self.assertEqual(rec["msg"], "Apply this new periodization strategy? → cancelled")
        self.assertIs(rec["d"]["cancelled"], True)
        self.assertNotIn("answer", rec["d"])

    def test_a_front_end_that_sends_no_answer_is_defaulted_not_a_no(self):
        from stamind.prompt import JsonPrompt
        answer = json.dumps({"v": 1, "id": "p1"}) + "\n"
        prompt = JsonPrompt(out=io.StringIO(), inp=io.StringIO(answer))
        journal.start_run(["plan", "generate"], source="bot")
        prompt.confirm("Apply this new periodization strategy?", default=False)
        journal.end_run("ok")
        self.assertIs(self._answers()[0]["d"]["defaulted"], True)

    def test_the_answer_lands_on_the_innermost_run_not_the_shell_around_it(self):
        """A decision belongs to the command that asked, not to `sm shell` (§3)."""
        journal.start_run(["shell"], source="cli")
        inner = journal.start_run(["plan", "generate"], source="shell")
        with patch("builtins.input", return_value="y"):
            self.prompt.confirm("Apply this new periodization strategy?")
        journal.end_run("ok")
        journal.end_run("ok")
        self.assertEqual(self._answers()[0]["run"], inner)

    def test_free_text_answers_are_never_journalled(self):
        """§4.4 keeps the athlete's own words out of the log; only argv carries them."""
        journal.start_run(["data", "pull"], source="cli")
        with patch("builtins.input", return_value="hungover from the wedding"):
            self.prompt.ask_text("How did it go")
        journal.end_run("ok")
        self.assertEqual(self._answers(), [])


if __name__ == "__main__":
    unittest.main()
