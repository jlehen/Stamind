"""What the app says, and in which tier.

Four voices reach the screen (DESIGN_output_verbosity.md §3): `aside` and `step` are side
information a terminal shows and a chat front-end does not, `warn` and `fail` are
operational faults that always print and always land in the journal, and `notice` is the
athlete's own data reported back — always printed, never journalled. `Progress` and
`Spinner` are the two self-erasing lines a slow loop or a slow call draws.

How the text is coloured and wrapped is `text.py`; this module only decides who sees it.
"""
import sys
import threading
import time
from typing import Optional

from stamind import journal
from stamind.text import (
    asides_enabled, dim, red, strip_ansi, wrap_text, yellow,
)


def aside(text: str, color_fn=None) -> None:
    """Prints one piece of side information — progress, cache reuse, a next-step hint.
    The answer, warnings and errors use `print` and reach every front-end
    (DESIGN_output_verbosity.md §3)."""
    if not asides_enabled():
        return
    print((color_fn or dim)(text))


def step(text: str, color_fn=None) -> None:
    """Prints what the app is doing right now, and records it (DESIGN_logging.md §5.1).

    The trace half of the old aside tier: a decision or an action a post-mortem wants —
    "Auto-syncing Garmin...", "reusing the cached reconstruction", "no date given,
    adapting today". Prints through the same gate and the same dim styling `aside` uses,
    so nothing on screen moves; the difference is that it survives the screen."""
    aside(text, color_fn)
    journal.note(strip_ansi(text))


def warn(text: str) -> None:
    """An operational warning: something outside the app did not work, and it changes
    what the answer means (DESIGN_logging.md §5.3).

    Always prints, and folds in the colour, the `Warning: ` prefix and the wrap that used
    to be twenty independent decisions. A domain refusal — "no active plan", "nothing
    scheduled for Thursday" — is the app correctly reporting the athlete's own data, so
    it is an answer, and takes `notice` instead.

    The prefix is wrapped with the text so the first line fits the budget too; the
    journal keeps the unwrapped original, since a log is not read at 48 columns."""
    print(yellow(wrap_text("Warning: " + text)))
    journal.note(strip_ansi(text), lvl="warn")


def fail(text: str) -> None:
    """The command could not do its job, for a reason outside the app (§5.3). Prints in
    red with an `Error: ` prefix, wrapped like `warn`, and lands in the journal at
    `error`."""
    print(red(wrap_text("Error: " + text)))
    journal.note(strip_ansi(text), lvl="error")


def notice(text: str, color_fn=None) -> None:
    """The athlete's own data reported back: no plan yet, a version kept for rollback, a
    selector that matched nothing, a hint that the answer needs a follow-up command.

    Warning tier on screen (DESIGN_output_verbosity.md §3) — always printed, on every
    front-end — but not an operational fault, so unlike `warn` it takes no prefix and
    leaves no journal entry. It exists for the third thing they share, the wrap, which
    every yellow and red line used to decide for itself (§3.5). `red` for a refusal."""
    print((color_fn or yellow)(wrap_text(text)))


class Progress:
    """A single self-erasing '[####....] 7/28' line for a loop of slow network round-trips:
    the Calendar writes of generate/rollback, the days and activities of a Garmin pull.

    Silent unless stdout is a terminal, so piped output, the bot and the tests keep just
    the summary line that introduced it. Usable as a context manager, which erases the
    line on the way out."""

    BAR_WIDTH = 24

    def __init__(self, total: int) -> None:
        self.total = total
        self.done_count = 0
        self.active = total > 0 and sys.stdout.isatty()
        self._draw()

    def __enter__(self) -> "Progress":
        return self

    def __exit__(self, *exc) -> None:
        self.close()

    def step(self, n: int = 1) -> None:
        self.done_count = min(self.total, self.done_count + n)
        self._draw()

    def close(self) -> None:
        """Erases the bar, leaving the surrounding output as if it never drew."""
        if self.active:
            sys.stdout.write("\r\033[K")
            sys.stdout.flush()
            self.active = False

    def _draw(self) -> None:
        if not self.active:
            return
        filled = round(self.BAR_WIDTH * self.done_count / self.total)
        bar = "#" * filled + "." * (self.BAR_WIDTH - filled)
        sys.stdout.write(f"\r\033[K  [{bar}] {self.done_count}/{self.total}")
        sys.stdout.flush()


class Spinner:
    """A self-erasing '⠹ 1:23 elapsed' line that ticks while one blocking call runs: the
    LLM wait (DESIGN_output_verbosity.md §8.5).

    Silent unless stdout is a terminal, like `Progress`. A daemon thread redraws it, so a
    Ctrl-C in the wrapped call still exits; leaving the context erases the line."""

    FRAMES = "⠋⠙⠹⠸⠼⠴⠦⠧⠇⠏"
    INTERVAL = 0.1

    def __init__(self) -> None:
        self.active = sys.stdout.isatty()
        self._stop = threading.Event()
        self._thread: Optional[threading.Thread] = None
        self._started = 0.0

    def __enter__(self) -> "Spinner":
        if self.active:
            self._started = time.monotonic()
            self._thread = threading.Thread(target=self._run, daemon=True)
            self._thread.start()
        return self

    def __exit__(self, *exc) -> None:
        if not self.active:
            return
        self._stop.set()
        self._thread.join()
        sys.stdout.write("\r\033[K")
        sys.stdout.flush()

    def _run(self) -> None:
        frame = 0
        while not self._stop.is_set():
            elapsed = int(time.monotonic() - self._started)
            glyph = self.FRAMES[frame % len(self.FRAMES)]
            sys.stdout.write(f"\r\033[K  {glyph} {elapsed // 60}:{elapsed % 60:02d} elapsed")
            sys.stdout.flush()
            frame += 1
            self._stop.wait(self.INTERVAL)
