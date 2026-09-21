"""`stamind/output.py`: which tier a message belongs to, and who therefore sees it."""
import ast
import io
import os
import unittest
from unittest.mock import patch

from stamind import output as output_module
from stamind.output import Progress, Spinner
from stamind.text import visible_len


class TestProgress(unittest.TestCase):
    class _Tty(io.StringIO):
        def isatty(self) -> bool:
            return True

    def test_bar_draws_on_a_terminal_and_erases_itself(self):
        out = self._Tty()
        with patch("sys.stdout", out):
            with Progress(2) as bar:
                bar.step()
                bar.step()
        written = out.getvalue()
        self.assertIn("1/2", written)
        self.assertIn("2/2", written)
        # Nothing survives on the line: the summary above the bar is the only trace left.
        self.assertTrue(written.endswith("\r\033[K"))

    def test_silent_when_not_a_terminal_or_empty(self):
        out = io.StringIO()
        with patch("sys.stdout", out):
            with Progress(3) as bar:
                bar.step()
        self.assertEqual(out.getvalue(), "")

        tty = self._Tty()
        with patch("sys.stdout", tty):
            with Progress(0) as bar:
                bar.step()
        self.assertEqual(tty.getvalue(), "")


class TestSpinner(unittest.TestCase):
    """The LLM wait's clock (DESIGN_output_verbosity.md §8.5)."""

    class _Tty(io.StringIO):
        def isatty(self) -> bool:
            return True

    def test_ticks_minutes_and_seconds_on_a_terminal_and_erases_itself(self):
        import itertools
        import time
        out = self._Tty()
        with patch("sys.stdout", out), patch("stamind.output.time") as clock:
            # Started at t=1000, every later reading is 83 seconds on.
            clock.monotonic.side_effect = itertools.chain([1000.0], itertools.repeat(1083.0))
            with Spinner():
                deadline = time.monotonic() + 2
                while "1:23 elapsed" not in out.getvalue() and time.monotonic() < deadline:
                    time.sleep(0.01)
        written = out.getvalue()
        self.assertIn("1:23 elapsed", written)
        self.assertTrue(written.endswith("\r\033[K"))

    def test_silent_when_not_a_terminal(self):
        out = io.StringIO()
        with patch("sys.stdout", out):
            with Spinner():
                pass
        self.assertEqual(out.getvalue(), "")


class TestAsides(unittest.TestCase):
    """Side information prints on a terminal and not in chat
    (DESIGN_output_verbosity.md §3)."""

    def setUp(self):
        self._saved = {
            k: os.environ.pop(k, None) for k in ("STAMIND_VERBOSE", "STAMIND_FRONTEND")
        }
        from stamind import output, text
        self.text = text
        self.output = output

    def tearDown(self):
        for k, v in self._saved.items():
            if v is None:
                os.environ.pop(k, None)
            else:
                os.environ[k] = v

    def _emit(self) -> str:
        buf = io.StringIO()
        with patch("sys.stdout", buf):
            self.output.aside("side information")
        return buf.getvalue()

    def test_prints_on_a_terminal(self):
        self.assertTrue(self.text.asides_enabled())
        self.assertIn("side information", self._emit())

    def test_silent_under_the_chat_frontend(self):
        os.environ["STAMIND_FRONTEND"] = "json"
        self.assertFalse(self.text.asides_enabled())
        self.assertEqual(self._emit(), "")

    def test_env_forces_them_back_on_in_chat(self):
        os.environ["STAMIND_FRONTEND"] = "json"
        os.environ["STAMIND_VERBOSE"] = "1"
        self.assertIn("side information", self._emit())

    def test_env_forces_them_off_on_a_terminal(self):
        os.environ["STAMIND_VERBOSE"] = "0"
        self.assertEqual(self._emit(), "")


class TestWarningTierWraps(unittest.TestCase):
    """Every printer of the warning tier wraps to the client's width
    (DESIGN_output_verbosity.md §3.5) — the whole reason `notice` exists."""

    LONG = ("The plan runs out on 2026-09-30, before this horizon (2026-10-14) — "
            "sessions after it have no mesocycle to follow. Run 'plan generate' to extend "
            "the periodization first.")

    def setUp(self):
        self._saved = os.environ.pop("STAMIND_WRAP_WIDTH", None)
        os.environ["STAMIND_WRAP_WIDTH"] = "48"
        from stamind import output, text
        self.text = text
        self.output = output

    def tearDown(self):
        if self._saved is None:
            os.environ.pop("STAMIND_WRAP_WIDTH", None)
        else:
            os.environ["STAMIND_WRAP_WIDTH"] = self._saved

    def _emit(self, fn, *args) -> str:
        buf = io.StringIO()
        with patch("sys.stdout", buf):
            fn(*args)
        return self.text.strip_ansi(buf.getvalue())

    def _assert_fits(self, out: str) -> None:
        for line in out.splitlines():
            self.assertLessEqual(visible_len(line), 48, f"too wide: {line!r}")

    def test_notice_wraps(self):
        out = self._emit(self.output.notice, self.LONG)
        self._assert_fits(out)
        self.assertIn("The plan runs out on", out)

    def test_warn_wraps_its_prefix_along_with_the_text(self):
        # The prefix is part of the first line's budget, so it wraps with the text.
        out = self._emit(self.output.warn, self.LONG)
        self._assert_fits(out)
        self.assertTrue(out.startswith("Warning: "))

    def test_fail_wraps(self):
        out = self._emit(self.output.fail, self.LONG)
        self._assert_fits(out)
        self.assertTrue(out.startswith("Error: "))

    def test_hand_made_layout_survives_the_wrap(self):
        out = self._emit(self.output.notice, "Backfill from 2026-01-01:\n  data pull -d …")
        self._assert_fits(out)
        self.assertIn("\n  data pull", out)

    def test_no_warning_is_printed_by_hand(self):
        """The rule the wrap depends on: a whole yellow or red message goes through
        `notice`/`warn`/`fail`, never a bare print. Colour used as a *fragment* — a bold
        heading, one cell of a row, `red(x) + hint` — is untouched by this: it is not a
        message, and wrapping it would break the layout it sits in."""
        root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
        offenders = []
        for dirpath, dirnames, filenames in os.walk(os.path.join(root, "stamind")):
            dirnames[:] = [d for d in dirnames if d != "__pycache__"]
            for name in filenames:
                if not name.endswith(".py"):
                    continue
                path = os.path.join(dirpath, name)
                if os.path.samefile(path, output_module.__file__):
                    continue        # where `notice`, `warn` and `fail` are defined
                tree = ast.parse(open(path).read())
                for node in ast.walk(tree):
                    if not isinstance(node, ast.Call) or node.keywords:
                        continue
                    if getattr(node.func, "id", None) != "print" or len(node.args) != 1:
                        continue
                    arg = node.args[0]
                    if (isinstance(arg, ast.Call)
                            and getattr(arg.func, "id", None) in ("yellow", "red")):
                        offenders.append(f"{os.path.relpath(path, root)}:{node.lineno}")
        self.assertEqual(offenders, [], "use notice()/warn()/fail(): " + ", ".join(offenders))

    def test_no_message_spells_the_prefix_itself(self):
        """`warn` owns `Warning: `, and owning it is what puts the line in the journal
        at warn level. A message that spells the word itself is one that skipped it.

        `config.py` and `journal.py` say it by hand on purpose — config load runs before
        `output` can be imported, and the journal cannot journal its own write failure."""
        root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
        exempt = {os.path.basename(output_module.__file__), "config.py", "journal.py"}
        offenders = []

        def leading_text(node):
            while True:
                if isinstance(node, ast.BinOp) and isinstance(node.op, ast.Add):
                    node = node.left
                elif (isinstance(node, ast.Call) and node.args
                      and getattr(node.func, "id", None) in ("yellow", "red", "bold")):
                    node = node.args[0]
                else:
                    break
            if isinstance(node, ast.JoinedStr) and node.values:
                node = node.values[0]
            if isinstance(node, ast.Constant) and isinstance(node.value, str):
                return node.value.lstrip("\n")
            return ""

        for dirpath, dirnames, filenames in os.walk(os.path.join(root, "stamind")):
            dirnames[:] = [d for d in dirnames if d != "__pycache__"]
            for name in filenames:
                if not name.endswith(".py") or name in exempt:
                    continue
                path = os.path.join(dirpath, name)
                for node in ast.walk(ast.parse(open(path).read())):
                    if not isinstance(node, ast.Call) or not node.args:
                        continue
                    if getattr(node.func, "id", None) not in ("print", "notice"):
                        continue
                    if leading_text(node.args[0]).startswith("Warning:"):
                        offenders.append(f"{os.path.relpath(path, root)}:{node.lineno}")
        self.assertEqual(offenders, [], "use warn(): " + ", ".join(offenders))

    def test_the_journal_keeps_the_unwrapped_line(self):
        # A log is not read at 48 columns (DESIGN_logging.md §5.3).
        with patch("stamind.journal.note") as note:
            self._emit(self.output.warn, self.LONG)
        self.assertEqual(note.call_args.args[0], self.LONG)


if __name__ == "__main__":
    unittest.main()

if __name__ == "__main__":
    unittest.main()
