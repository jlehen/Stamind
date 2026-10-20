"""The week lock: one look at the athlete's week at a time, across every process
(DESIGN_long_runs_beside_chat.md §3).

It is Monday 08:00. The morning run holds the week while the week planner thinks. The other
process here stands for it, or for a run started in a terminal.
"""
import contextlib
import io
import subprocess
import sys
import time
import unittest

from tests.helpers import bind_test_db, rebind_test_db
from tests import test_db_path

test_db = bind_test_db(test_db_path("test_week_lock.db"))

from stamind.db.base import WEEK_WAIT_LINE  # noqa: E402

# Another process: takes the lock, says so, and keeps it for argv[2] seconds.
HOLDER = (
    "import fcntl, sys, time\n"
    "lock_file = open(sys.argv[1], 'a')\n"
    "fcntl.flock(lock_file, fcntl.LOCK_EX)\n"
    "print('held', flush=True)\n"
    "time.sleep(float(sys.argv[2]))\n"
)


class WeekLockTest(unittest.TestCase):

    def setUp(self):
        rebind_test_db(test_db)

    def held_elsewhere(self, seconds):
        proc = subprocess.Popen(
            [sys.executable, "-c", HOLDER, test_db._week_lock_path(), str(seconds)],
            stdout=subprocess.PIPE, text=True,
        )
        self.addCleanup(proc.wait)
        self.addCleanup(proc.stdout.close)
        self.assertEqual(proc.stdout.readline().strip(), "held")
        return proc

    def test_a_run_waits_for_the_other_and_says_so(self):
        """08:00:02, a tap on "Change it": it waits for the morning run."""
        self.held_elsewhere(0.5)
        out = io.StringIO()
        start = time.monotonic()
        with contextlib.redirect_stdout(out), test_db.week_lock():
            waited = time.monotonic() - start
        self.assertGreater(waited, 0.3)
        self.assertIn(WEEK_WAIT_LINE, out.getvalue())

    def test_the_morning_run_waits_without_a_word(self):
        self.held_elsewhere(0.2)
        out = io.StringIO()
        with contextlib.redirect_stdout(out), test_db.week_lock(waiting=None):
            pass
        self.assertEqual(out.getvalue(), "")

    def test_a_write_of_the_week_waits_too(self):
        self.held_elsewhere(0.5)
        start = time.monotonic()
        with contextlib.redirect_stdout(io.StringIO()), \
                test_db.workout_change(kind="adapt", summary="held"):
            pass
        self.assertGreater(time.monotonic() - start, 0.3)

    def test_a_hold_inside_a_hold_joins_it(self):
        """A chat run holds the week and then writes: the write must not wait for itself."""
        with test_db.week_lock():
            with test_db.week_lock():
                pass
            self.assertTrue(test_db.week_busy())
        self.assertFalse(test_db.week_busy())

    def test_release_lets_go_before_the_with_ends(self):
        """A terminal lets go before it asks "Apply?", and takes the lock again to write."""
        with test_db.week_lock() as week:
            week.release()
            self.assertFalse(test_db.week_busy())
            with test_db.week_lock():
                self.assertTrue(test_db.week_busy())
            self.assertFalse(test_db.week_busy())
        self.assertFalse(test_db.week_busy())

    def test_busy_only_while_another_process_holds_it(self):
        proc = self.held_elsewhere(0.3)
        self.assertTrue(test_db.week_busy())
        proc.wait()
        self.assertFalse(test_db.week_busy())


if __name__ == "__main__":
    unittest.main()
