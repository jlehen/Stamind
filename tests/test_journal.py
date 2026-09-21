"""The journal file itself: the writer, the reader, the sweep — and the three
structural tests DESIGN_logging.md §11 asks for, which read the app's source
rather than run it.

`JournalTestCase` below is the harness the whole family shares; the other
three modules import it. What one run records is `test_journal_run.py` and
`test_journal_records.py`; `tm journal` reading it back is
`test_journal_command.py`.
"""
import ast
import io
import json
import os
import shutil
import sys
import tempfile
import unittest
from datetime import date, datetime, timedelta, timezone
from unittest.mock import patch

from trainmate import journal
from trainmate.config import config
from tests.helpers import bind_test_db
from tests import test_db_path

TEST_DB_PATH = test_db_path("test_journal.db")


def setUpModule():
    """The writer never opens a database, but rendering a stamp back reads the athlete's
    zone, which is a settings row — so this module binds one of its own (§4)."""
    bind_test_db(TEST_DB_PATH)


class JournalTestCase(unittest.TestCase):
    """Points `logging.dir` at a scratch directory for the life of one test."""

    def setUp(self) -> None:
        self.log_dir = tempfile.mkdtemp(prefix="tm-journal-test-")
        self.addCleanup(shutil.rmtree, self.log_dir, True)
        logging_section = config.data.setdefault("logging", {})
        previous = dict(logging_section)
        self.addCleanup(lambda: (logging_section.clear(), logging_section.update(previous)))
        logging_section["dir"] = self.log_dir
        journal.reset()
        self.addCleanup(journal.reset)

    def lines(self):
        """Every raw line written today, in order."""
        path = journal.today_path()
        if not os.path.exists(path):
            return []
        with open(path, encoding="utf-8") as handle:
            return [line for line in handle.read().split("\n") if line]

    def records(self):
        return [json.loads(line) for line in self.lines()]

    def _seed_runs(self):
        """The two runs most of the listing tests read: one failed, one that called out."""
        journal.start_run(["plan", "generate", "-g", "2"], source="push")
        journal.name_run("plan", "generate")
        journal.llm_call(
            label="plan_generate", model="anthropic/claude-opus-5", ms=88400, ok=True,
            total_tokens=210412, path="logs/llm_exchanges/x_plan_generate.md",
        )
        journal.end_run("failed", exit_code=1, error="KeyError: 'mesocycles'",
                        traceback_text="Traceback (most recent call last):\n  boom")
        journal.start_run(["workout", "adapt", "-m", "legs heavy"], source="bot")
        journal.name_run("workout", "adapt")
        journal.llm_call(
            label="workout_adaptation", model="google/gemini-3.5-flash", ms=24118,
            ok=True, total_tokens=38104,
        )
        journal.end_run("ok")
        journal.reset()

    def _seed(self, argv, path=None, outcome="ok", lvl=None, source="cli",
              msg="the calendar did not answer"):
        """One finished run of `argv`, named as the dispatcher would name it."""
        journal.start_run(argv, source=source)
        if path:
            journal.name_run(*path.split(" "))
        if lvl:
            journal.note(msg, lvl=lvl)
        journal.end_run(outcome)
        journal.reset()


class TestWriter(JournalTestCase):
    """One record is one line, bounded, and never takes the command down (§4.3)."""

    def test_a_record_round_trips(self):
        journal.record("note", "Auto-syncing Garmin", lvl="warn", days=3)
        (rec,) = self.records()
        self.assertEqual(rec["ev"], "note")
        self.assertEqual(rec["msg"], "Auto-syncing Garmin")
        self.assertEqual(rec["lvl"], "warn")
        self.assertEqual(rec["d"], {"days": 3})
        self.assertEqual(rec["run"], journal.NO_RUN)
        self.assertTrue(rec["ts"].endswith("Z"))

    def test_a_none_valued_field_is_dropped_rather_than_written_as_null(self):
        journal.record("note", "x", days=None)
        self.assertNotIn("d", self.records()[0])

    def test_the_day_file_is_named_for_the_utc_day_not_the_athletes(self):
        # §4: naming the file from the athlete's zone would build and migrate the
        # database, on `tm help` and in the path that must survive it being unreachable.
        journal.record("note", "x")
        today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
        self.assertEqual(
            os.listdir(journal.runs_dir()), [f"{today}.jsonl"]
        )

    def test_a_multiline_message_is_still_one_line(self):
        journal.record("note", "first\nsecond\nthird")
        self.assertEqual(len(self.lines()), 1)
        self.assertEqual(self.records()[0]["msg"], "first\nsecond\nthird")

    def test_an_over_long_traceback_is_elided_in_the_middle(self):
        head, tail = "HEAD" + "a" * 4000, "b" * 4000 + "TAIL"
        journal.record("run.end", "failed", lvl="error", traceback=head + tail)
        line = self.lines()[0]
        self.assertLessEqual(len(line.encode("utf-8")), journal.MAX_RECORD_BYTES)
        trace = self.records()[0]["d"]["traceback"]
        self.assertTrue(trace.startswith("HEAD"))
        self.assertTrue(trace.endswith("TAIL"))
        self.assertIn("elided", trace)

    def test_an_over_long_message_is_cut_and_the_record_stays_parseable(self):
        journal.record("note", "x" * 40000)
        line = self.lines()[0]
        self.assertLessEqual(len(line.encode("utf-8")), journal.MAX_RECORD_BYTES)
        self.assertTrue(self.records()[0]["msg"].endswith("…[cut]"))

    def test_a_debug_record_is_dropped_at_the_default_level(self):
        journal.debug("internal", "swallowed")
        self.assertEqual(self.lines(), [])
        config.data["logging"]["level"] = "debug"
        journal.debug("internal", "swallowed")
        self.assertEqual(self.records()[0]["lvl"], "debug")

    def test_an_unwritable_directory_neither_raises_nor_repeats_itself(self):
        blocker = os.path.join(self.log_dir, "blocker")
        with open(blocker, "w") as handle:
            handle.write("not a directory")
        config.data["logging"]["dir"] = blocker
        buffer = io.StringIO()
        with patch.object(sys, "stderr", buffer):
            journal.record("note", "one")
            journal.record("note", "two")
            journal.record("note", "three")
        self.assertEqual(len(buffer.getvalue().strip().split("\n")), 1)

    def test_seq_counts_within_the_run_not_the_file(self):
        journal.start_run(["status"])
        journal.record("note", "a")
        journal.end_run("ok")
        journal.start_run(["help"])
        journal.end_run("ok")
        seqs = [(rec["run"], rec["seq"]) for rec in self.records()]
        first = seqs[0][0]
        self.assertEqual([s for r, s in seqs if r == first], [0, 1, 2])
        self.assertEqual([s for r, s in seqs if r != first], [0, 1])


class TestReader(JournalTestCase):
    """A line that is not valid JSON is skipped, not raised on (§4.3)."""

    def test_a_torn_line_is_skipped_and_its_neighbours_survive(self):
        journal.record("note", "before")
        with open(journal.today_path(), "a", encoding="utf-8") as handle:
            handle.write('{"ts":"2026-08-26T00:00:00.000Z","run":"aaaa\n')
            handle.write("not json at all\n")
            handle.write("[1, 2, 3]\n")
        journal.record("note", "after")
        msgs = [rec["msg"] for rec in journal.iter_records()]
        self.assertEqual(msgs, ["before", "after"])

    def test_the_window_opens_one_file_either_side_of_what_was_asked(self):
        # A local day straddles two UTC files, so the reader widens by a day (§4).
        for day in ("2026-08-01", "2026-08-02", "2026-08-03", "2026-08-04", "2026-08-05"):
            path = os.path.join(journal.runs_dir(), f"{day}.jsonl")
            os.makedirs(journal.runs_dir(), exist_ok=True)
            with open(path, "w", encoding="utf-8") as handle:
                handle.write(json.dumps({"ts": day, "ev": "note", "msg": day}) + "\n")
        opened = journal.day_paths(date(2026, 8, 3), date(2026, 8, 3))
        self.assertEqual(
            [os.path.basename(p) for p in opened],
            ["2026-08-02.jsonl", "2026-08-03.jsonl", "2026-08-04.jsonl"],
        )

    def test_a_file_that_is_not_a_day_is_never_opened(self):
        os.makedirs(journal.runs_dir(), exist_ok=True)
        with open(os.path.join(journal.runs_dir(), "notes.txt"), "w") as handle:
            handle.write("hand-written\n")
        self.assertEqual(journal.day_paths(), [])


class TestRetention(JournalTestCase):
    """The sweep deletes by name shape, and runs at most once a UTC day (§10)."""

    def _seed(self, runs=(), exchanges=()):
        os.makedirs(journal.runs_dir(), exist_ok=True)
        os.makedirs(config.llm_logs_dir, exist_ok=True)
        for name in runs:
            open(os.path.join(journal.runs_dir(), name), "w").close()
        for name in exchanges:
            open(os.path.join(config.llm_logs_dir, name), "w").close()

    def test_only_files_past_their_retention_and_of_the_right_shape_are_deleted(self):
        config.data["logging"]["retain_days"] = 5
        config.data["logging"]["retain_exchange_days"] = 5
        old = (datetime.now(timezone.utc).date() - timedelta(days=30))
        fresh = (datetime.now(timezone.utc).date() - timedelta(days=1))
        self._seed(
            runs=[f"{old}.jsonl", f"{fresh}.jsonl", "notes.txt"],
            exchanges=[
                f"{old:%Y%m%d}_120000_1_a1b2c3d4_plan.md",
                f"{fresh:%Y%m%d}_120000_1_plan.md",
                "hand-written.md",
            ],
        )
        self.assertEqual(journal.prune(), (1, 1))
        self.assertEqual(
            sorted(os.listdir(journal.runs_dir())), sorted([f"{fresh}.jsonl", "notes.txt"])
        )
        self.assertEqual(
            sorted(os.listdir(config.llm_logs_dir)),
            sorted([f"{fresh:%Y%m%d}_120000_1_plan.md", "hand-written.md"]),
        )

    def test_the_stamp_file_gates_the_sweep_to_once_a_day(self):
        config.data["logging"]["retain_days"] = 5
        old = datetime.now(timezone.utc).date() - timedelta(days=30)
        self._seed(runs=[f"{old}.jsonl"])
        journal.start_run(["probe"])
        journal.end_run("ok")                       # sweeps, and stamps the day
        self.assertFalse(os.path.exists(os.path.join(journal.runs_dir(), f"{old}.jsonl")))
        self._seed(runs=[f"{old}.jsonl"])
        journal.start_run(["probe"])
        journal.end_run("ok")                       # already stamped: no second sweep
        self.assertTrue(os.path.exists(os.path.join(journal.runs_dir(), f"{old}.jsonl")))

    def test_only_the_outermost_run_ending_considers_a_sweep(self):
        journal.start_run(["shell"])
        journal.start_run(["help"])
        journal.end_run("ok")
        stamp = os.path.join(journal.runs_dir(), journal.PRUNE_STAMP)
        self.assertFalse(os.path.exists(stamp))
        journal.end_run("ok")
        self.assertTrue(os.path.exists(stamp))


class TestEveryQuestionGoesThroughTheBroker(unittest.TestCase):
    """A question asked with a bare `input()` is a decision the journal never sees.

    The broker records every answer in one place (§5.6), which only holds while it is the
    only thing that asks. Keyed on the shape — a call to `input` anywhere under the
    command and coach trees — so a handler written tomorrow is covered tomorrow
    (AGENTS.md). The REPL's line reader and the Garmin MFA code sit outside both trees:
    neither is a question about the athlete's training."""

    ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

    def test_no_command_or_coach_module_calls_input_directly(self):
        root = os.path.join(self.ROOT, "trainmate")
        offenders = []
        for tree in ("cli", "coach"):
            for folder, _dirs, files in os.walk(os.path.join(root, tree)):
                for name in sorted(files):
                    if not name.endswith(".py"):
                        continue
                    path = os.path.join(folder, name)
                    with open(path, encoding="utf-8") as handle:
                        parsed = ast.parse(handle.read(), filename=path)
                    for node in ast.walk(parsed):
                        if not isinstance(node, ast.Call):
                            continue
                        if isinstance(node.func, ast.Name) and node.func.id == "input":
                            offenders.append(f"{os.path.relpath(path, root)}:{node.lineno}")
        self.assertFalse(
            offenders,
            "these ask the athlete a question the journal cannot record — go through "
            "runtime.prompt instead: " + ", ".join(offenders),
        )


class TestReadOnlyVerbs(unittest.TestCase):
    """Every verb the listing hides has to still name a command (DESIGN_logging.md §7.1).

    The set is what `journal` filters on, and it is read at display time against a name
    the parser produced — so a command renamed or retired here leaves an entry that
    silently matches nothing, and its runs quietly come back. Keyed on the real tree, so
    a `show` added under a new group tomorrow needs no edit here."""

    def test_every_read_only_verb_names_a_command_in_the_tree(self):
        import trainmate_cli
        from trainmate.cli.argparse_ext import _subparsers_action
        from trainmate.cli.journal.runs import READ_ONLY_VERBS

        parser, _named = trainmate_cli.build_parser()

        def names(level):
            action = _subparsers_action(level)
            if action is None:
                return set()
            found = set(action.canonical_names)
            for name in action.canonical_names:
                found |= names(action.choices[name])
            return found

        unknown = sorted(READ_ONLY_VERBS - names(parser))
        self.assertFalse(
            unknown,
            "these verbs no longer name a command, so the runs they used to hide are "
            "back in the listing: " + ", ".join(unknown),
        )


class TestNoSilentSwallows(unittest.TestCase):
    """A broad handler whose body is exactly `pass` is an accident, not a decision.

    Keyed on the shape rather than a list of names, so a file written tomorrow is covered
    tomorrow (AGENTS.md, DESIGN_logging.md §11). A handler that means to stay quiet says
    so with `journal.debug(...)`; a handler that names a narrow exception is exempt,
    because the type is the documentation of what was expected, and one whose body is a
    bare `return`/`continue` is exempt too, because the value it hands back is something
    the caller sees. `pass` is the only shape with no effect outside itself.
    """

    ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    ENTRY_POINTS = ("trainmate_cli.py", "trainmate_bot.py", "trainmate_web.py")

    def _sources(self):
        for name in self.ENTRY_POINTS:
            yield os.path.join(self.ROOT, name)
        package = os.path.join(self.ROOT, "trainmate")
        for dirpath, _dirs, files in os.walk(package):
            if "__pycache__" in dirpath:
                continue
            for name in files:
                if name.endswith(".py"):
                    yield os.path.join(dirpath, name)

    def test_no_broad_handler_swallows_an_exception_in_silence(self):
        offenders = []
        for path in self._sources():
            with open(path, encoding="utf-8") as handle:
                tree = ast.parse(handle.read())
            for node in ast.walk(tree):
                if not isinstance(node, ast.ExceptHandler):
                    continue
                caught = node.type
                broad = caught is None or (
                    isinstance(caught, ast.Name)
                    and caught.id in ("Exception", "BaseException")
                )
                if not broad:
                    continue
                if len(node.body) == 1 and isinstance(node.body[0], ast.Pass):
                    offenders.append(f"{os.path.relpath(path, self.ROOT)}:{node.lineno}")
        self.assertFalse(
            offenders,
            "these handlers swallow an exception with no record of it; say so with "
            "journal.debug(...) instead of `pass`: " + ", ".join(offenders),
        )


if __name__ == "__main__":
    unittest.main()
