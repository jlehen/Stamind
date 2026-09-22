"""What the terminal confirm reads as an answer (DESIGN_output_verbosity.md §8.5).

A Left-arrow pressed during a three-minute LLM wait reached `input()` glued to the `y`
typed five minutes later, and the confirm read that line as No: the plan the athlete had
just approved was discarded."""
import io
import unittest
from unittest.mock import patch

from stamind.prompt import TtyPrompt


class _Tty(io.StringIO):
    def isatty(self) -> bool:
        return True


class TestTtyConfirm(unittest.TestCase):
    def setUp(self) -> None:
        self.prompt = TtyPrompt()
        # The journal record is covered by test_journal_records.TestPromptAnswers.
        patcher = patch("stamind.prompt._record_answer")
        patcher.start()
        self.addCleanup(patcher.stop)

    def _confirm(self, *answers: str, default: bool = False):
        out = io.StringIO()
        with patch("builtins.input", side_effect=list(answers)) as fake_input, \
                patch("sys.stdout", out):
            answer = self.prompt.confirm("Apply this new periodization strategy?",
                                         default=default)
        return answer, fake_input.call_count, out.getvalue()

    def test_a_stray_key_before_the_y_asks_again_instead_of_discarding(self):
        answer, asked, printed = self._confirm("\x1b[Dy", "y")
        self.assertIs(answer, True)
        self.assertEqual(asked, 2)
        self.assertIn("Please answer y or n.", printed)

    def test_the_four_words_and_a_blank_line_answer_at_once(self):
        for typed, default, expected in [
            ("y", False, True), ("YES", False, True), ("n", True, False),
            ("no", True, False), ("", True, True), ("", False, False),
        ]:
            with self.subTest(typed=typed, default=default):
                answer, asked, _ = self._confirm(typed, default=default)
                self.assertIs(answer, expected)
                self.assertEqual(asked, 1)


class TestTypeahead(unittest.TestCase):
    """Keys pressed before the question was printed are dropped, on a terminal only."""

    def test_pending_keys_are_flushed_before_the_question_on_a_terminal(self):
        import termios
        with patch("sys.stdin", _Tty()), patch("termios.tcflush") as flush, \
                patch("builtins.input", return_value="y"), \
                patch("stamind.prompt._record_answer"):
            TtyPrompt().confirm("Apply?")
        flush.assert_called_once()
        self.assertEqual(flush.call_args.args[1], termios.TCIFLUSH)

    def test_piped_answers_are_left_alone(self):
        with patch("sys.stdin", io.StringIO("y\n")), patch("termios.tcflush") as flush, \
                patch("builtins.input", return_value="y"), \
                patch("stamind.prompt._record_answer"):
            TtyPrompt().confirm("Apply?")
        flush.assert_not_called()


if __name__ == "__main__":
    unittest.main()
