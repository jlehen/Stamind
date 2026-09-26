"""One CLI subprocess per chat, from launch to exit.

A chat message is a Stamind command line, and the bot answers it by running
`stamind_cli.py` as a child process. `Session` is that child plus the state needed to
route a pending prompt's answer back into its stdin; `_drive` reads its stdout line by
line, hands the sentinel frames to the senders in `replies.py` and sends the rest as prose.

The child is launched with `STAMIND_FRONTEND=json`, so a `confirm`/`choose`/`text`
prompt arrives as a framed request line instead of blocking on `input()`
(DESIGN_output_verbosity.md §7). `restart_teardown` is the other end of a session's life:
what `/restart` does before it hard-exits (DESIGN_bot_restart.md §5.2).
"""
import asyncio
import json
import os
import secrets
import sys
from typing import Dict, List, Optional

from stamind import journal
from stamind.chat import telegram_api
from stamind.chat.routing import ROUTER_TIMEOUT_SECONDS
from stamind.sentinels import (
    BUTTONS_SENTINEL, FLUSH_SENTINEL, PHOTO_SENTINEL, PROMPT_SENTINEL, QUEUE_SENTINEL,
    SENTINEL_PREFIX, flush_wants_a_wait, parse_frame, prompt_answer,
)
from stamind.text import strip_ansi

# The bot runs the CLI beside it, from the repo root two directories above this file.
CLI_PATH = os.path.join(
    os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))),
    "stamind_cli.py",
)

# Exit code that tells the sm-bot supervisor to relaunch us (rather than exit for
# good). Arbitrary, borrowed from EX_TEMPFAIL in sysexits.h — just needs to not
# collide with Python's own exit code for uncaught exceptions (1). Must match the
# supervisor's RESTART_EXIT_CODE in sm-bot.
RESTART_EXIT_CODE = 75

# Bounds every blocking step of a /restart teardown (an open prompt's subprocess
# exiting cleanly, then the long-poll closing): nothing may keep us from reaching
# the exit code above. See DESIGN_bot_restart.md §5.2.
RESTART_GRACE_SECONDS = 2.0


class Session:
    """One in-flight command for a chat: the live CLI subprocess plus the state
    needed to route a pending prompt's answer back to it."""

    def __init__(self, chat_id: int, proc, nonce: str, quiet: bool = False) -> None:
        self.chat_id = chat_id
        self.proc = proc
        self.nonce = nonce
        self.awaiting: Optional[dict] = None      # the prompt request awaiting an answer
        self.answer_future: Optional["asyncio.Future"] = None
        self.task: Optional["asyncio.Task"] = None
        self.sent = False                         # whether anything was sent to the chat
        self.quiet = quiet                        # scheduler-run: silence "(no output)"
        self.last_message_id: Optional[int] = None  # anchor for a SM-BUTTONS row
        # The message carrying this command's live ✋ Stop button, if any: one at a
        # time, retired when the next wait starts or the command ends
        # (DESIGN_bot_stop_button.md §7).
        self.stop_message_id: Optional[int] = None


def cli_env(
    wrap_width: Optional[int], simple: bool = False, source: str = "bot"
) -> Dict[str, str]:
    """Environment for a bot-driven CLI subprocess: structured prompts, no colour,
    unbuffered I/O (so prompt requests arrive before the child waits on stdin), and
    the narrow wrap width phones want. `simple` opts commands into the companion
    rendering (DESIGN_bot_simple_frontend.md §6).

    `source` is a parameter rather than a constant beside STAMIND_FRONTEND because
    this one function serves three callers with three different answers: a chat message
    is `bot`, the scheduler firing the push or a reminder is `push`, and the intent router is
    `route` (DESIGN_logging.md §3). The child also gets this process's run id as its
    parent, so the push and the subprocess it launched read as one story."""
    env = dict(os.environ)
    journal.child_env(env, source)
    env["STAMIND_FRONTEND"] = "json"
    env["NO_COLOR"] = "1"
    env["PYTHONUNBUFFERED"] = "1"
    if simple:
        env["STAMIND_RENDER"] = "simple"
    if wrap_width:
        env["STAMIND_WRAP_WIDTH"] = str(wrap_width)
    return env


async def _exited_within_grace(proc) -> bool:
    """True if proc exited on its own within RESTART_GRACE_SECONDS."""
    try:
        await asyncio.wait_for(proc.wait(), timeout=RESTART_GRACE_SECONDS)
        return True
    except asyncio.TimeoutError:
        return False


async def restart_teardown(session: Optional[Session], stop_polling) -> None:
    """Ends any live command and closes the Telegram long-poll, so /restart's hard exit
    strands neither an orphaned subprocess nor an unconfirmed getUpdates offset.

    Both halves are bounded and failure-tolerant: reaching os._exit(RESTART_EXIT_CODE)
    matters more than a tidy teardown. See DESIGN_bot_restart.md §5.2."""
    if session is not None and session.proc.returncode is None:
        fut = session.answer_future
        answered = session.awaiting is not None and fut is not None and not fut.done()
        if answered:
            fut.set_result(
                prompt_answer(session.awaiting.get("id"), cancelled=True)
            )
        if not answered or not await _exited_within_grace(session.proc):
            try:
                session.proc.kill()
            except ProcessLookupError:
                pass
    try:
        await asyncio.wait_for(stop_polling(), timeout=RESTART_GRACE_SECONDS)
    except Exception as e:
        print(f"restart: could not stop polling cleanly: {e!r}", flush=True)


class RunnerMixin:
    """`ChatBot`'s half that starts a CLI subprocess and reads it to the end."""

    async def _drive(self, session: Session) -> None:
        """Reads the CLI's stdout, streaming prose to the chat and handling each
        prompt request inline, until the process exits.

        Polling stays live throughout, so a ✋ Stop tap, /cancel or /restart reaches the
        bot while the subprocess is computing (DESIGN_bot_stop_button.md §5)."""
        buf: List[str] = []
        try:
            while True:
                # Inactivity watchdog over the compute phase: a command that goes
                # silent for command_timeout is killed. A legitimately-awaited prompt
                # is handled below and has its own (longer) prompt_timeout.
                try:
                    line = await asyncio.wait_for(
                        session.proc.stdout.readline(), timeout=self.command_timeout
                    )
                except asyncio.TimeoutError:
                    await self._flush_output(session, buf)
                    await self.bot.send_message(
                        chat_id=session.chat_id,
                        text=f"Command timed out after {self.command_timeout}s.",
                    )
                    break
                if not line:
                    break
                raw = line.decode("utf-8", "replace")
                frame = parse_frame(raw)
                if frame is None:
                    if raw.rstrip("\n").startswith(SENTINEL_PREFIX):
                        # Recognised framing but a tag this build does not know (a newer
                        # CLI), or a payload that does not parse. Dropped rather than
                        # forwarded as chat text.
                        continue
                    buf.append(strip_ansi(raw).rstrip("\n"))
                    continue
                tag, payload = frame
                if tag == FLUSH_SENTINEL:
                    # Nothing to render: the marker's whole job is to end the message
                    # here, before the CLI goes quiet for an LLM call (§7). That message
                    # is the wait notice, and it carries the Stop button
                    # (DESIGN_bot_stop_button.md §4) — no message, nothing to hang it on.
                    if await self._flush_output(session, buf) and flush_wants_a_wait(payload):
                        await self._offer_stop(session)
                    buf = []
                    continue
                # Every other frame renders something of its own, so whatever prose is
                # buffered is a message that ends here.
                await self._flush_output(session, buf)
                buf = []
                if tag == PHOTO_SENTINEL:
                    await self._send_photo(session, payload)
                elif tag == BUTTONS_SENTINEL:
                    await self._send_ui_buttons(session, payload)
                elif tag == QUEUE_SENTINEL:
                    await self._send_queue_item(session, payload)
                elif tag == PROMPT_SENTINEL:
                    response = await self._present_prompt(session, payload)
                    try:
                        session.proc.stdin.write((json.dumps(response) + "\n").encode())
                        await session.proc.stdin.drain()
                    except (BrokenPipeError, ConnectionResetError):
                        break
            await self._flush_output(session, buf)
            await session.proc.wait()
            # A scheduler-spawned run (`bot morning` already sent today) may
            # legitimately end silent; only interactive commands owe a reply.
            if not session.sent and not session.quiet:
                await self.bot.send_message(chat_id=session.chat_id, text="(no output)")
        except Exception as e:  # pragma: no cover - defensive
            await self._report_drive_failure(session, e)
        finally:
            self.sessions.pop(session.chat_id, None)
            if session.proc.returncode is None:
                try:
                    session.proc.kill()
                except ProcessLookupError:
                    pass
            # A command that ends without a last message — killed, or answered with a
            # photo — would otherwise leave a Stop button nothing can act on.
            await self._retire_stop(session)

    async def _report_drive_failure(self, session: Session, exc: Exception) -> None:
        """Tells the athlete their command died, unless Telegram itself is what died: then
        the channel is gone and the journal line is the record. The fallback is guarded
        too, so nothing escapes the task the push loop waits on
        (DESIGN_telegram_send_retry.md §2)."""
        summary = f"{type(exc).__name__}: {exc}"
        if telegram_api.is_network_error(exc):
            self._log(
                session.chat_id, "!!", f"telegram unreachable, gave up: {summary}", lvl="warn"
            )
            return
        self._log(session.chat_id, "!!", f"drive error: {summary}", lvl="error")
        try:
            await self.bot.send_message(
                chat_id=session.chat_id, text=f"Internal error: {exc}"
            )
        except Exception as send_exc:
            self._log(
                session.chat_id, "!!", f"internal error not told: {send_exc}", lvl="warn"
            )

    async def _start_command(
        self, chat_id: int, argv: List[str], quiet: bool = False, source: str = "bot"
    ) -> Session:
        proc = await asyncio.create_subprocess_exec(
            sys.executable, "-u", CLI_PATH, *argv,
            stdin=asyncio.subprocess.PIPE,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.STDOUT,
            env=cli_env(self._wrap_width(), simple=self.simple_ui, source=source),
            cwd=os.path.dirname(CLI_PATH),
        )
        session = Session(chat_id, proc, secrets.token_hex(4), quiet=quiet)
        self.sessions[chat_id] = session
        session.task = asyncio.create_task(self._drive(session))
        return session

    async def _route_intent(self, text: str) -> str:
        """Runs `sm bot route` silently — output captured here, never streamed to the
        chat — and returns the intent, 'unclear' on any failure or timeout (§5.3)."""
        proc = None
        try:
            proc = await asyncio.create_subprocess_exec(
                sys.executable, "-u", CLI_PATH, "bot", "route", text,
                stdin=asyncio.subprocess.DEVNULL,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.DEVNULL,
                # `route` keeps its own source: it runs once per free-text message and
                # is pure noise in every other view (DESIGN_logging.md §3).
                env=cli_env(None, source="route"),
                cwd=os.path.dirname(CLI_PATH),
            )
            out, _ = await asyncio.wait_for(
                proc.communicate(), timeout=ROUTER_TIMEOUT_SECONDS
            )
        except asyncio.TimeoutError:
            try:
                proc.kill()
            except ProcessLookupError:
                pass
            return "unclear"
        except Exception:
            return "unclear"
        # The intent is the last JSON line; anything above it is stray CLI prose.
        for line in reversed(out.decode("utf-8", "replace").splitlines()):
            line = line.strip()
            if not line.startswith("{"):
                continue
            try:
                return str(json.loads(line).get("intent") or "unclear")
            except json.JSONDecodeError:
                continue
        return "unclear"
