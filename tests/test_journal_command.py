"""`tm journal` reads the files back in the athlete's terms
(DESIGN_logging.md §7): what the default listing leaves out and what the
footer says about it (§7.1), and why a row that is not `ok` says so on the
same screen (§7.3).
"""
import unittest
from unittest.mock import patch

from stamind import journal
from stamind.text import default_wrap_width, visible_len
from tests.helpers import bind_test_db, run_cli
from tests import test_db_path
from tests.test_journal import JournalTestCase

TEST_DB_PATH = test_db_path("test_journal_command.db")


def setUpModule():
    """The writer never opens a database, but rendering a stamp back reads the athlete's
    zone, which is a settings row — so this module binds one of its own (§4)."""
    bind_test_db(TEST_DB_PATH)


class TestJournalCommand(JournalTestCase):
    """`tm journal` reads the files back in the athlete's terms (§7)."""

    def test_the_listing_shows_one_row_per_run_with_its_outcome(self):
        self._seed_runs()
        _code, out, _err = run_cli(["journal", "-v"])
        self.assertIn("plan generate -g 2", out)
        self.assertIn("FAILED", out)
        self.assertIn("workout adapt", out)
        self.assertIn("1 · 210k", out)

    def test_a_run_with_no_end_reads_as_a_question_mark(self):
        journal.start_run(["plan", "generate"], source="bot")
        journal.reset()          # killed before it could write a run.end
        _code, out, _err = run_cli(["journal"])
        self.assertIn("?", out)

    def test_an_id_prefix_opens_the_detail_view(self):
        self._seed_runs()
        run_id = [
            rec["run"] for rec in journal.iter_records()
            if rec["ev"] == "run.start" and rec["msg"].startswith("plan")
        ][0]
        _code, out, _err = run_cli(["journal", run_id[:4]])
        self.assertIn(f"run {run_id}", out)
        self.assertIn("llm.call", out)
        self.assertIn("x_plan_generate.md", out)
        self.assertIn("Traceback (most recent call last):", out)

    def test_an_ambiguous_prefix_lists_what_it_matched_rather_than_guessing(self):
        with patch("stamind.journal.secrets.token_hex",
                   side_effect=["ab121234", "ab125678"]):
            for argv in (["status"], ["help"]):
                journal.start_run(argv)
                journal.end_run("ok")
        journal.reset()
        _code, out, _err = run_cli(["journal", "ab12"])
        self.assertIn("matches 2 runs", out)
        self.assertIn("ab121234", out)
        self.assertIn("ab125678", out)

    def test_prune_is_a_sub_command_and_not_read_as_a_run_id(self):
        self._seed_runs()
        _code, out, _err = run_cli(["journal", "prune"])
        self.assertIn("Pruned", out)

    def test_the_cost_rollup_groups_by_model_and_by_command(self):
        self._seed_runs()
        _code, out, _err = run_cli(["journal", "--cost"])
        self.assertIn("anthropic/claude-opus-5", out)
        self.assertIn("210,412", out)
        self.assertIn("plan generate", out)
        self.assertIn("248,516", out)          # the total row

    def test_the_filters_narrow_to_one_source_and_to_trouble(self):
        self._seed_runs()
        _code, out, _err = run_cli(["journal", "-v", "--source", "bot"])
        self.assertIn("workout adapt", out)
        self.assertNotIn("plan generate", out)
        _code, out, _err = run_cli(["journal", "-v", "--failed"])
        self.assertIn("plan generate", out)
        self.assertNotIn("workout adapt", out)


class TestJournalListing(JournalTestCase):
    """What the default listing leaves out, and what the footer says about it (§7.1)."""

    def test_a_run_that_only_looked_is_left_out_until_a_asks_for_it(self):
        self._seed(["workout", "list"], "workout list")
        self._seed(["wo", "a"], "workout adapt")
        _code, out, _err = run_cli(["journal"])
        self.assertIn("wo a", out)                       # the line as it was typed
        self.assertNotIn("workout list", out)
        self.assertIn("1 read-only run(s) hidden", out)
        _code, out, _err = run_cli(["journal", "-a"])
        self.assertIn("workout list", out)

    def test_a_view_that_went_wrong_is_never_hidden(self):
        self._seed(["workout", "list"], "workout list", lvl="warn")
        _code, out, _err = run_cli(["journal"])
        self.assertIn("workout list", out)
        self.assertIn("warn", out)
        self.assertIn("the calendar did not answer", out)

    def test_a_help_run_is_left_out_whatever_it_asked_about(self):
        # `-h` exits inside argparse, so the run is never named: the argv is the tell.
        self._seed(["workout", "adapt", "-h"])
        _code, out, _err = run_cli(["journal"])
        self.assertNotIn("workout adapt", out)
        self.assertIn("1 read-only run(s) hidden", out)

    def test_naming_a_command_lists_it_views_included(self):
        self._seed(["wo", "li"], "workout list")
        _code, out, _err = run_cli(["journal", "--command", "workout list"])
        self.assertIn("wo li", out)
        self.assertNotIn("hidden", out)

    def test_the_command_column_is_clipped_to_the_screen_unless_v_asks(self):
        note = "the intervals ran long and the second round was short, " * 4
        self._seed(["workout", "adapt", "-m", note], "workout adapt")
        _code, out, _err = run_cli(["journal"])
        self.assertNotIn(note, out)
        self.assertIn("…", out)
        self.assertIn("command lines clipped", out)
        for line in out.split("\n"):
            self.assertLessEqual(visible_len(line), default_wrap_width())
        _code, out, _err = run_cli(["journal", "-v"])
        self.assertIn(note, out)
        self.assertNotIn("command lines clipped", out)

    def test_the_legend_glosses_the_outcomes_on_screen_and_no_others(self):
        self._seed_runs()
        _code, out, _err = run_cli(["journal"])
        self.assertIn("END  ok = finished", out)
        self.assertIn("FAILED = raised", out)
        self.assertNotIn("stopped with Ctrl-C", out)     # nothing was cancelled
        self.assertIn("LLM  model calls · tokens", out)


class TestJournalReasons(JournalTestCase):
    """A row that is not `ok` says why, on the same screen (§7.3)."""

    def test_a_run_that_warned_says_what_it_warned_about(self):
        self._seed(["data", "pull"], "data pull", lvl="warn",
                   msg="Garmin sync failed, continuing with cached data")
        _code, out, _err = run_cli(["journal"])
        self.assertIn("Garmin sync failed, continuing with cached data", out)

    def test_the_first_warning_is_the_one_shown(self):
        journal.start_run(["data", "pull"])
        journal.name_run("data", "pull")
        journal.note("the calendar did not answer", lvl="warn")
        journal.note("and neither did Garmin", lvl="warn")
        journal.end_run("ok")
        journal.reset()
        _code, out, _err = run_cli(["journal"])
        self.assertIn("the calendar did not answer", out)
        self.assertNotIn("and neither did Garmin", out)

    def test_a_failed_run_names_the_exception_and_not_a_warning_on_the_way(self):
        journal.start_run(["plan", "generate"])
        journal.name_run("plan", "generate")
        journal.note("the calendar did not answer", lvl="warn")
        journal.end_run("failed", exit_code=1, error="KeyError: 'mesocycles'")
        journal.reset()
        _code, out, _err = run_cli(["journal"])
        self.assertIn("KeyError: 'mesocycles'", out)
        self.assertNotIn("the calendar did not answer", out)

    def test_a_quiet_listing_prints_no_reasons_at_all(self):
        self._seed(["data", "pull"], "data pull")
        _code, out, _err = run_cli(["journal"])
        self.assertNotIn("warnings clipped", out)
        self.assertEqual(out.count("data pull"), 1)     # the row, and no line under it

    def test_a_long_warning_is_clipped_to_the_screen_until_v_asks(self):
        self._seed(["data", "pull"], "data pull", lvl="warn", msg=(
            "2 activities had low HR-zone coverage and no RPE; their load is an "
            "underestimate:\n    - 2026-08-27 Warm-up\n    - 2026-08-26 Evening Ride"
        ))
        _code, out, _err = run_cli(["journal"])
        self.assertIn("warnings clipped (-v for the full text)", out)
        self.assertNotIn("Evening Ride", out)
        for line in out.split("\n"):
            self.assertLessEqual(visible_len(line), default_wrap_width())
        _code, out, _err = run_cli(["journal", "-v"])
        self.assertIn("- 2026-08-26 Evening Ride", out)  # the list keeps its own shape
        self.assertNotIn("warnings clipped", out)
        for line in out.split("\n"):
            self.assertLessEqual(visible_len(line), default_wrap_width())


if __name__ == "__main__":
    unittest.main()
