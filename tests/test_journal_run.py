"""The run bracket: every command opens and closes a run and says how it ended
(DESIGN_logging.md §3, §5.4), and the model calls made inside one are what
the wait estimate is drawn from (DESIGN_output_verbosity.md §8).
"""
import io
import json
import os
import sys
import unittest
from datetime import datetime, timedelta, timezone
from unittest.mock import patch

from stamind import journal
from stamind.prompt import PromptCancelled
from tests.helpers import bind_test_db, run_cli
from tests import test_db_path
from tests.test_journal import JournalTestCase

TEST_DB_PATH = test_db_path("test_journal_run.db")


def setUpModule():
    """The writer never opens a database, but rendering a stamp back reads the athlete's
    zone, which is a settings row — so this module binds one of its own (§4)."""
    bind_test_db(TEST_DB_PATH)


class TestLlmDurations(JournalTestCase):
    """The wait estimate's data source (DESIGN_output_verbosity.md §8.3)."""

    def _write_day(self, day: str, calls, cmd: str = "workout adapt",
                   ended: bool = True) -> None:
        """Appends `calls` as `(label, model, ms, ok)` tuples to one day file, each call in
        its own run of `cmd`, closed by a ``run.end`` unless `ended` is False."""
        os.makedirs(journal.runs_dir(), exist_ok=True)
        path = os.path.join(journal.runs_dir(), f"{day}.jsonl")
        with open(path, "a", encoding="utf-8") as handle:
            for label, model, ms, ok in calls:
                self._runs = getattr(self, "_runs", 0) + 1
                run = f"run{self._runs}"
                handle.write(json.dumps({
                    "ts": f"{day}T09:00:00.000Z", "run": run, "ev": "llm.call",
                    "msg": label,
                    "d": {"label": label, "model": model, "ms": ms, "ok": ok},
                }) + "\n")
                if not ended:
                    continue
                handle.write(json.dumps({
                    "ts": f"{day}T09:01:00.000Z", "run": run, "ev": "run.end",
                    "msg": "ok", "d": {"outcome": "ok", "cmd": cmd},
                }) + "\n")

    def _days_ago(self, count: int) -> str:
        return (datetime.now(timezone.utc).date() - timedelta(days=count)).isoformat()

    def test_only_this_label_and_model_count(self):
        self._write_day(self._days_ago(1), [
            ("workout_adapt", "m1", 40000, True),
            ("workout_adapt", "m2", 90000, True),   # another model
            ("strength_planner", "m1", 99000, True),   # another call
        ])
        self.assertEqual(
            journal.llm_durations("workout_adapt", "workout adapt", "m1"), [40000]
        )

    def test_a_call_counts_only_for_the_command_that_made_it(self):
        # The strength planner writes four sessions in `workout generate` and checks one
        # in `workout adapt`; the first must not set the number the second announces.
        day = self._days_ago(1)
        self._write_day(day, [("strength_planner", "m1", 250000, True)],
                        cmd="workout generate")
        self._write_day(day, [("strength_planner", "m1", 35000, True)])
        self.assertEqual(
            journal.llm_durations("strength_planner", "workout adapt", "m1"), [35000]
        )

    def test_a_run_still_open_is_not_a_sample(self):
        # Its command is not on disk until its `run.end`.
        self._write_day(self._days_ago(1), [("workout_adapt", "m1", 40000, True)],
                        ended=False)
        self.assertEqual(
            journal.llm_durations("workout_adapt", "workout adapt", "m1"), []
        )

    def test_a_failed_call_is_not_a_sample(self):
        # A call that died on a timeout says nothing about how long a working one takes.
        self._write_day(self._days_ago(1), [
            ("workout_adapt", "m1", 40000, True),
            ("workout_adapt", "m1", 600000, False),
        ])
        self.assertEqual(
            journal.llm_durations("workout_adapt", "workout adapt", "m1"), [40000]
        )

    def test_newest_first_across_days_and_within_one(self):
        self._write_day(self._days_ago(2), [("workout_adapt", "m1", 10000, True)])
        self._write_day(self._days_ago(1), [
            ("workout_adapt", "m1", 20000, True),
            ("workout_adapt", "m1", 30000, True),
        ])
        self.assertEqual(
            journal.llm_durations("workout_adapt", "workout adapt", "m1"),
            [30000, 20000, 10000],
        )

    def test_the_scan_stops_at_the_limit(self):
        for age in range(1, 6):
            self._write_day(self._days_ago(age), [("workout_adapt", "m1", age, True)])
        self.assertEqual(
            journal.llm_durations("workout_adapt", "workout adapt", "m1", limit=2), [1, 2]
        )

    def test_a_day_outside_the_window_is_not_read(self):
        self._write_day(self._days_ago(40), [("workout_adapt", "m1", 40000, True)])
        self.assertEqual(
            journal.llm_durations("workout_adapt", "workout adapt", "m1", days=30), []
        )

    def test_no_model_given_takes_every_model(self):
        self._write_day(self._days_ago(1), [
            ("workout_adapt", "m1", 40000, True),
            ("workout_adapt", "m2", 90000, True),
        ])
        self.assertEqual(
            sorted(journal.llm_durations("workout_adapt", "workout adapt")),
            [40000, 90000],
        )

    def test_a_torn_line_costs_only_itself(self):
        os.makedirs(journal.runs_dir(), exist_ok=True)
        day = self._days_ago(1)
        self._write_day(day, [("workout_adapt", "m1", 40000, True)])
        with open(os.path.join(journal.runs_dir(), f"{day}.jsonl"), "a") as handle:
            handle.write("{not json\n")
        self.assertEqual(
            journal.llm_durations("workout_adapt", "workout adapt", "m1"), [40000]
        )


class TestRunBracket(JournalTestCase):
    """Every command opens and closes a run, and says how it ended (§3, §5.4)."""

    def _ends(self):
        return [rec for rec in journal.iter_records() if rec["ev"] == "run.end"]

    def test_every_start_has_an_end(self):
        run_cli(["help"])
        run_cli(["journal", "-n", "1"])
        starts = [r for r in journal.iter_records() if r["ev"] == "run.start"]
        ends = self._ends()
        self.assertEqual(len(starts), 2)
        self.assertEqual({r["run"] for r in starts}, {r["run"] for r in ends})

    def test_run_start_names_the_command_without_touching_the_database(self):
        run_cli(["help"])
        (start,) = [r for r in journal.iter_records() if r["ev"] == "run.start"]
        self.assertEqual(start["msg"], "help")
        self.assertEqual(start["d"]["argv"], ["help"])
        self.assertEqual(start["d"]["source"], "test")
        self.assertIn("pid", start["d"])
        # The model is deliberately absent: resolving it would build the database (§3).
        self.assertNotIn("model", start["d"])

    def test_run_end_names_the_canonical_command_whatever_prefix_was_typed(self):
        run_cli(["j", "-n", "1"])          # `j` is an unambiguous prefix of `journal`
        (end,) = self._ends()
        self.assertEqual(end["d"]["cmd"], "journal")

    def test_a_command_that_raises_records_its_traceback_and_fails(self):
        import stamind_cli
        with patch.object(stamind_cli, "_dispatch", side_effect=KeyError("mesocycles")):
            run_cli(["status"])
        (end,) = self._ends()
        self.assertEqual(end["d"]["outcome"], "failed")
        self.assertEqual(end["lvl"], "error")
        self.assertEqual(end["d"]["error"], "KeyError: 'mesocycles'")
        self.assertIn("KeyError", end["d"]["traceback"])

    def test_a_cancelled_command_is_cancelled_and_not_failed(self):
        import stamind_cli
        with patch.object(stamind_cli, "_dispatch", side_effect=PromptCancelled()):
            run_cli(["status"])
        (end,) = self._ends()
        self.assertEqual(end["d"]["outcome"], "cancelled")
        self.assertEqual(end["d"]["exit"], 130)

    def test_a_domain_refusal_reads_as_ok(self):
        # A handler that says no exits 1. That is an answer about the athlete's own data,
        # not a failure (§3).
        import stamind_cli
        with patch.object(stamind_cli, "_dispatch", side_effect=SystemExit(1)):
            run_cli(["status"])
        (end,) = self._ends()
        self.assertEqual(end["d"]["outcome"], "ok")
        self.assertEqual(end["d"]["exit"], 1)

    def test_a_line_that_only_printed_help_is_not_a_run(self):
        # Nothing happened but the help now on screen, so there is nothing to record —
        # and the parse never named these, so the listing could not classify them either
        # (§3, §7.1).
        for argv in (
            ["benchmark", "record"],   # a required argument missing: argparse exits 2
            ["b"],                     # an ambiguous prefix: exits 2
            ["goal"],                  # a command group invoked bare: exits 1
            [],                        # no command at all: exits 1
            ["progress", "-h"],        # help asked for by name: exits 0
        ):
            with self.subTest(argv=argv):
                run_cli(argv)
        self.assertEqual(list(journal.iter_records()), [])

    def test_a_named_run_is_on_disk_before_it_does_anything(self):
        # Deferring the bracket must not cost §3's `?` row: the parse writes `run.start`,
        # so a run killed anywhere it could actually be killed still left one behind.
        journal.start_run(["plan", "generate"], defer=True)
        self.assertEqual(self.records(), [])
        journal.name_run("plan", "generate")
        (start,) = self.records()
        self.assertEqual(start["ev"], "run.start")

    def test_a_deferred_start_still_opens_the_bracket_it_belongs_to(self):
        journal.start_run(["plan", "generate"], defer=True)
        journal.note("Querying OpenRouter...")
        self.assertEqual([r["ev"] for r in self.records()], ["run.start", "note"])
        self.assertEqual([r["seq"] for r in self.records()], [0, 1])

    def test_dropping_a_run_that_already_spoke_closes_it_instead(self):
        # A `run.start` with no `run.end` reads as a run that was killed (§3), so a drop
        # that arrives too late has to end the run rather than abandon it.
        journal.start_run(["plan", "generate"], defer=True)
        journal.note("Querying OpenRouter...")
        journal.drop_run()
        self.assertEqual(
            [r["ev"] for r in self.records()], ["run.start", "note", "run.end"]
        )

    def test_three_lines_in_a_shell_make_four_runs_with_one_parent(self):
        import stamind_cli
        typed = iter(["help", "help", "help"])

        def _input(_prompt=""):
            try:
                return next(typed)
            except StopIteration:
                raise EOFError

        # main() directly rather than helpers.run_cli: that helper pins input() to one
        # constant answer, which the REPL would read as the same line forever.
        with patch("builtins.input", _input), patch.object(sys, "stdout", io.StringIO()):
            stamind_cli.main(["shell"])
        starts = [r for r in journal.iter_records() if r["ev"] == "run.start"]
        self.assertEqual(len(starts), 4)
        (shell,) = [s for s in starts if s["msg"] == "shell"]
        children = [s for s in starts if s["msg"] == "help"]
        self.assertEqual(len(children), 3)
        for child in children:
            self.assertEqual(child["d"]["parent"], shell["run"])
            self.assertEqual(child["d"]["source"], "repl")

    def test_a_mistyped_line_in_a_shell_leaves_the_shell_run_alone(self):
        # The drop pops one run off a stack that has the shell under it (§3): the shell
        # keeps its own bracket, and the lines that never parsed leave nothing.
        import stamind_cli
        typed = iter(["benchmark record", "goal", "help"])

        def _input(_prompt=""):
            try:
                return next(typed)
            except StopIteration:
                raise EOFError

        with patch("builtins.input", _input), patch.object(sys, "stdout", io.StringIO()), \
                patch.object(sys, "stderr", io.StringIO()):
            stamind_cli.main(["shell"])
        starts = [r["msg"] for r in journal.iter_records() if r["ev"] == "run.start"]
        self.assertEqual(sorted(starts), ["help", "shell"])
        self.assertEqual(journal.current(), None)

    def test_a_spawned_process_inherits_the_parent_run_and_its_own_source(self):
        journal.start_run(["sm-bot"], source="bot")
        env = journal.child_env({"STAMIND_PARENT_RUN": "stale"}, "push")
        self.assertEqual(env["STAMIND_PARENT_RUN"], journal.current_id())
        self.assertEqual(env["STAMIND_SOURCE"], "push")
        journal.end_run("ok")
        # With no run open, an inherited parent is dropped rather than passed on.
        self.assertNotIn("STAMIND_PARENT_RUN", journal.child_env(dict(env), "cli"))

    def test_the_rollup_counts_what_the_run_wrote(self):
        journal.start_run(["plan", "generate"])
        journal.note("careful", lvl="warn")
        journal.llm_call(
            label="plan_generate", model="m", ms=10, ok=True, total_tokens=1200
        )
        journal.end_run("ok")
        (end,) = self._ends()
        self.assertEqual(end["d"]["warns"], 1)
        self.assertEqual(end["d"]["llm_calls"], 1)
        self.assertEqual(end["d"]["tokens"], 1200)


if __name__ == "__main__":
    unittest.main()
