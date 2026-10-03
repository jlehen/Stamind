"""Restarting the bot: /restart from the chat, SIGHUP from a shell, and the `sm-bot`
supervisor that relaunches the worker either way (DESIGN_bot_restart.md).
"""
import asyncio
import os
import shutil
import signal
import subprocess
import sys
import tempfile
import time
import unittest
from unittest import mock

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from tests.chat_harness import _FakeProc, build_chat_bot
from stamind.chat import runner
from stamind.chat.app import ChatBot

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


class RestartTeardownTest(unittest.IsolatedAsyncioTestCase):
    """/restart's teardown (DESIGN_bot_restart.md §5.2): no orphaned subprocess and no
    long-poll left open when os._exit() fires."""

    def setUp(self):
        patcher = mock.patch.object(runner, "RESTART_GRACE_SECONDS", 0.02)
        patcher.start()
        self.addCleanup(patcher.stop)
        self.stops = []

    async def _stop_polling(self):
        self.stops.append(True)

    def _session(self, awaiting=None, proc=None):
        session = runner.Session(42, proc if proc is not None else _FakeProc(), "n0nce")
        if awaiting is not None:
            session.awaiting = awaiting
            session.answer_future = asyncio.get_running_loop().create_future()
        return session

    async def test_kills_a_silently_computing_session(self):
        # A single getUpdates batch can deliver a command and /restart together, so
        # /restart can land with a subprocess running and no prompt open.
        session = self._session()
        await runner.restart_teardown(session, self._stop_polling)
        self.assertTrue(session.proc.killed)

    async def test_open_prompt_is_answered_cancelled_not_killed(self):
        session = self._session(
            {"id": "p1", "type": "confirm"}, _FakeProc(exits_on_its_own=True)
        )
        await runner.restart_teardown(session, self._stop_polling)
        self.assertTrue(session.answer_future.result()["cancelled"])
        self.assertFalse(session.proc.killed)

    async def test_open_prompt_whose_process_lingers_is_killed_after_the_grace(self):
        session = self._session({"id": "p1", "type": "confirm"})
        await runner.restart_teardown(session, self._stop_polling)
        self.assertTrue(session.proc.killed)

    async def test_finished_process_is_left_alone(self):
        session = self._session()
        session.proc.returncode = 0
        await runner.restart_teardown(session, self._stop_polling)
        self.assertFalse(session.proc.killed)

    async def test_the_coachs_run_is_ended_too(self):
        """A chat has a second place, for the coach's run (DESIGN_waiting_proposal.md
        §6.1)."""
        own, coach = self._session(), self._session()
        await runner.restart_teardown(own, self._stop_polling, coach)
        self.assertTrue(own.proc.killed and coach.proc.killed)

    async def test_releases_the_long_poll(self):
        # Without this, the abandoned getUpdates never confirms its offset and the
        # relaunched worker is served the same /restart again (§7).
        await runner.restart_teardown(None, self._stop_polling)
        self.assertEqual(self.stops, [True])
        session = self._session()
        await runner.restart_teardown(session, self._stop_polling)
        self.assertEqual(len(self.stops), 2)

    async def test_a_wedged_stop_still_returns(self):
        async def _hangs():
            await asyncio.sleep(3600)

        await runner.restart_teardown(None, _hangs)  # must not hold up the hard exit

    async def test_a_failing_stop_still_returns(self):
        async def _raises():
            raise RuntimeError("This Updater is not running!")

        await runner.restart_teardown(None, _raises)


class HangupTest(unittest.IsolatedAsyncioTestCase):
    """SIGHUP stops the worker the way SIGTERM does, then asks `sm-bot` for a restart
    (DESIGN_bot_restart.md §5.3)."""

    async def _serve_until(self, sig) -> bool:
        chat_bot = build_chat_bot(self)
        chat_bot.push_chat_id = None
        # `_serve` installs its handlers before its first await, so the signal lands on them.
        asyncio.get_running_loop().call_soon(os.kill, os.getpid(), sig)
        with mock.patch.object(runner, "take_restart_note", return_value=None):
            restart = await chat_bot._serve()
        self.assertFalse(chat_bot.updater.running)
        return restart

    async def test_sighup_asks_for_a_restart(self):
        self.assertTrue(await self._serve_until(signal.SIGHUP))

    async def test_sigterm_only_stops(self):
        self.assertFalse(await self._serve_until(signal.SIGTERM))

    def test_a_restart_exits_with_the_code_sm_bot_relaunches_on(self):
        chat_bot = build_chat_bot(self)
        with mock.patch.object(ChatBot, "_serve", mock.AsyncMock(return_value=True)), \
                mock.patch("stamind.chat.app.journal"), \
                self.assertRaises(SystemExit) as caught:
            chat_bot.run()
        self.assertEqual(caught.exception.code, runner.RESTART_EXIT_CODE)


# Stands in for the Python worker `sm-bot` execs: it logs its start and its end, and on
# SIGHUP takes a moment to shut down before it exits with RESTART_EXIT_CODE, as the real one
# does.
STUB_WORKER = f"""#!/bin/sh
echo "start $$" >> "$STUB_LOG"
trap 'sleep 0.3; echo "end $$" >> "$STUB_LOG"; exit {runner.RESTART_EXIT_CODE}' HUP
trap 'echo "end $$" >> "$STUB_LOG"; exit 0' TERM
while :; do sleep 0.05; done
"""


class SupervisorTest(unittest.TestCase):
    """`sm-bot` relaunches the worker on a SIGHUP sent to either process, and only once the
    old worker has ended: two workers would poll Telegram at once (DESIGN_bot_restart.md
    §5.3)."""

    def setUp(self):
        tmp = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, tmp)
        shutil.copy(os.path.join(REPO, "sm-bot"), tmp)
        os.makedirs(os.path.join(tmp, "venv", "bin"))
        worker = os.path.join(tmp, "venv", "bin", "python")
        with open(worker, "w", encoding="utf-8") as f:
            f.write(STUB_WORKER)
        os.chmod(worker, 0o755)
        self.log = os.path.join(tmp, "log")
        env = {k: v for k, v in os.environ.items() if k != "SM_BOT_SUPERVISED"}
        env["STUB_LOG"] = self.log
        self.supervisor = subprocess.Popen(
            [os.path.join(tmp, "sm-bot")], env=env, stdout=subprocess.DEVNULL
        )
        self.addCleanup(self.supervisor.wait, 5)
        self.addCleanup(self.supervisor.terminate)

    def _log_once_it_has(self, count: int) -> list:
        deadline = time.monotonic() + 5
        while time.monotonic() < deadline:
            if os.path.exists(self.log):
                with open(self.log, encoding="utf-8") as f:
                    lines = f.read().split("\n")[:-1]
                if len(lines) >= count:
                    return lines
            time.sleep(0.02)
        self.fail(f"the log never reached {count} lines")

    def test_a_sighup_to_either_process_relaunches_the_worker(self):
        self._log_once_it_has(1)
        self.supervisor.send_signal(signal.SIGHUP)
        lines = self._log_once_it_has(3)
        self.assertEqual([line.split()[0] for line in lines], ["start", "end", "start"])
        os.kill(int(lines[2].split()[1]), signal.SIGHUP)
        lines = self._log_once_it_has(5)
        self.assertEqual([line.split()[0] for line in lines[3:]], ["end", "start"])
        self.assertIsNone(self.supervisor.poll())


if __name__ == "__main__":
    unittest.main()
