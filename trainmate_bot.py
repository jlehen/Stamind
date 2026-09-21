"""TrainMate Telegram front-end.

A chat shim over the existing CLI: each incoming message is treated as a TrainMate
command line (the leading slash Telegram requires is optional) and run through
``trainmate_cli.py`` as a subprocess. Driving the real CLI keeps the bot in permanent
parity with every command/flag the CLI gains, and isolates each invocation.

Interactive commands work over chat because the CLI is launched with
``TRAINMATE_FRONTEND=json``: its prompt broker (``trainmate.prompt``) emits a
sentinel-framed JSON request instead of blocking on ``input()``, and the bot renders it
as an inline keyboard and writes the answer back to stdin. One in-flight command per
chat, state in ``_Session``, a per-prompt ``nonce`` against stale taps.

This file is the process: ``main`` and the closures that drive one command per chat.
What the process can be read without lives in ``trainmate/chat/`` — ``routing`` for what
a message means, ``keyboards`` for what the bot draws and how it reads a tap back, and
``scheduler`` for when the push and the nightly reflect are due. None of that imports
``python-telegram-bot``, so all of it is unit-testable; here the library is imported
lazily inside ``main``.

``telegram.ui: simple`` (the default) is the companion persona — reply keyboard, intent
router, morning scheduler, prose replies; ``expert`` is the raw CLI; ``/ui`` flips it per-process
(DESIGN_bot_simple_frontend.md). ``tm-bot`` supervises this process and relaunches it on
``RESTART_EXIT_CODE``, which is what ``/restart`` exits with. Polling runs from start to
shutdown, including while a command computes, which is what lets a ✋ Stop tap or
``/cancel`` reach a command waiting on the coach (DESIGN_bot_stop_button.md §5).

Run with: ``./tm-bot`` (or ``venv/bin/python trainmate_bot.py``). Configure the token +
allowlist under a ``telegram:`` section in config.yaml (see config_template.yaml).
"""
import asyncio
import datetime
import html
import json
import os
import secrets
import shlex
import signal
import sys
import time
from typing import Dict, List, Optional, Tuple

from trainmate import heads_up, journal
from trainmate.chat.keyboards import (
    BUSY_TAP, SIMPLE_KEYBOARD, STOP_ALREADY_DONE, STOP_DONE, STOP_LABEL, UI_STALE_TAP,
    decode_callback, decode_queue_callback, decode_stop_callback, decode_ui_callback,
    keyboard_action, prompt_buttons, queue_button_rows, queue_later_rows,
    resolve_ui_action, stale_keyboard_tap, stop_callback_data, tapped_label,
    ui_button_rows, ui_menu_rows,
)
from trainmate.chat.routing import (
    CAPTURE_PROMPT, CAPTURE_RESCUE_ECHO, ROUTER_CAPTURE_INTENTS, ROUTER_ECHO,
    ROUTER_FALLBACK, ROUTER_INTENT_ARGV, ROUTER_MESSAGE_ARGV, ROUTER_TIMEOUT_SECONDS,
    UI_EXPERT_ON, UI_SIMPLE_ON, UI_USAGE, parse_message_to_argv, parse_ui_switch,
)
from trainmate.chat.scheduler import scheduler_wake
from trainmate.config import config
from trainmate.sentinels import (
    BUTTONS_SENTINEL, FLUSH_SENTINEL, PHOTO_SENTINEL, PROMPT_SENTINEL, QUEUE_SENTINEL,
    SENTINEL_PREFIX, flush_wants_a_wait, parse_frame, prompt_answer,
)
from trainmate.athlete_queue import QUEUE_NOT_NOW
from trainmate.text import cmd, strip_ansi
from trainmate.output import warn

# Telegram caps a message at 4096 chars; we wrap replies in <pre>…</pre> (7 chars
# of overhead) and want headroom, so chunk the body well under the hard limit.
MAX_MESSAGE_CHARS = 3800

CLI_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "trainmate_cli.py")

# Exit code that tells the tm-bot supervisor to relaunch us (rather than exit for
# good). Arbitrary, borrowed from EX_TEMPFAIL in sysexits.h — just needs to not
# collide with Python's own exit code for uncaught exceptions (1). Must match the
# supervisor's RESTART_EXIT_CODE in tm-bot.
RESTART_EXIT_CODE = 75

# Bounds every blocking step of a /restart teardown (an open prompt's subprocess
# exiting cleanly, then the long-poll closing): nothing may keep us from reaching
# the exit code above. See DESIGN_bot_restart.md §5.2.
RESTART_GRACE_SECONDS = 2.0

WELCOME = (
    "TrainMate is connected. Send any CLI command — the leading slash is "
    "optional.\n\n"
    "Examples:\n"
    "  /status\n"
    "  /workout list --weeks 1\n"
    "  /workout adapt -m \"tired today\"\n"
    "  /plan show\n\n"
    "Send /help for the full command list, or /help <command> (e.g. "
    "/help workout) for a command's options.\n\n"
    "When a command needs a decision (apply a plan, confirm a wipe) I'll show "
    "buttons — tap one, or send /cancel to abort."
)

# Top-level command families surfaced in Telegram's command menu (set_my_commands).
# Kept in sync by hand with the CLI's subparsers; purely cosmetic (any command
# still works whether or not it's listed here).
MENU_COMMANDS = [
    ("status", "Athlete status, goals, recent metrics"),
    ("progress", "Training progress timeline (add --chart for a PNG)"),
    ("workout", "List/generate/adapt/tweak workouts"),
    ("plan", "Show/generate periodization plans"),
    ("goal", "Manage training goals"),
    ("data", "Pull/show Garmin metrics & activities"),
    ("signal", "Author daily signals"),
    ("learnings", "Inspect coach learnings"),
    ("constraint", "Manage directives the coach works around"),
    ("settings", "Show/change preferences (model, timezone, morning push)"),
    ("queue", "Questions and messages waiting for the athlete"),
    ("ui", "Switch simple/expert chat UI (until restart)"),
    ("cancel", "Abort the command awaiting your answer"),
    ("restart", "Restart the bot process (picks up new code)"),
    ("help", "Show command help"),
]

# --- Simple mode ("companion") cards — DESIGN_bot_simple_frontend.md §5 ---
# What /start and /help say, beside MENU_COMMANDS. They name the buttons
# `trainmate.chat.keyboards.SIMPLE_KEYBOARD` draws, so the two are edited together.

SIMPLE_WELCOME = (
    "Hi! I'm your training coach 🏃\n\n"
    "Use the buttons below:\n"
    "📅 Today — today's session\n"
    "🗓 My week — the days ahead\n"
    "✅ Done lately — how the last days went\n"
    "🎯 Goals — what you're training for\n"
    "🧭 My plan — the road to your goal\n"
    "📈 Progress — how your fitness is building\n"
    "💬 Talk to me — anything I should know (tired, busy, sore…)\n\n"
    "Or just type what you want, in your own words — it's the same thing."
)

# The two lanes, taught rather than discovered (§12.3). The surface has exactly two
# teachers — this card and the per-message router echoes — and both say the same thing:
# what you want remembered is recorded here, after a question; what is about how you are
# doing goes to the coach in your own words. No line promises verbatim delivery on a tap,
# because no tap delivers it.
SIMPLE_HELP = SIMPLE_WELCOME + (
    "\n\nWhen you write to me, one of two things happens:\n"
    "• Something to remember — a rule, a rough night, a new goal, a change of date — "
    "I write it down and ask you first.\n"
    "• Something about how you're doing, what's in the way, or a session you'd like "
    "changed — that goes to your coach in your own words, and your week comes back "
    "adjusted."
)

# Simple mode trims the Telegram command menu to what the athlete needs; every CLI
# command still works when typed with a leading slash.
SIMPLE_MENU_COMMANDS = [
    ("cancel", "Stop what's running"),
    ("help", "What can I ask?"),
]


def is_authorized(chat_id: int, allowed_ids: List[int]) -> bool:
    """True only when chat_id is on the allowlist. Empty allowlist authorizes no one."""
    return chat_id in allowed_ids


def format_prompt_message(req: dict) -> str:
    """The plain-text question shown above a prompt's buttons (ANSI stripped)."""
    return strip_ansi(req.get("message", "")).strip()


def chunk_text(text: str, limit: int = MAX_MESSAGE_CHARS) -> List[str]:
    """Splits text into <=limit-char chunks, preferring line boundaries.

    A single over-long line is hard-split. Always returns at least one chunk."""
    chunks: List[str] = []
    current = ""
    for line in text.split("\n"):
        while len(line) > limit:
            head, line = line[:limit], line[limit:]
            if current:
                chunks.append(current)
                current = ""
            chunks.append(head)
        candidate = line if not current else current + "\n" + line
        if len(candidate) > limit:
            chunks.append(current)
            current = line
        else:
            current = candidate
    chunks.append(current)
    return chunks


def format_reply(text: str, simple: bool = False) -> List[str]:
    """Renders CLI output as one or more Telegram HTML messages.

    Expert form wraps each chunk in <pre> so column alignment survives; simple mode
    sends plain escaped prose the client flows naturally
    (DESIGN_bot_simple_frontend.md §6)."""
    if simple:
        return [html.escape(chunk) for chunk in chunk_text(text)]
    return [f"<pre>{html.escape(chunk)}</pre>" for chunk in chunk_text(text)]


def _cli_env(
    wrap_width: Optional[int], simple: bool = False, source: str = "bot"
) -> Dict[str, str]:
    """Environment for a bot-driven CLI subprocess: structured prompts, no colour,
    unbuffered I/O (so prompt requests arrive before the child waits on stdin), and
    the narrow wrap width phones want. `simple` opts commands into the companion
    rendering (DESIGN_bot_simple_frontend.md §6).

    `source` is a parameter rather than a constant beside TRAINMATE_FRONTEND because
    this one function serves three callers with three different answers: a chat message
    is `bot`, the scheduler firing the push or a reminder is `push`, and the intent router is
    `route` (DESIGN_logging.md §3). The child also gets this process's run id as its
    parent, so the push and the subprocess it launched read as one story."""
    env = dict(os.environ)
    journal.child_env(env, source)
    env["TRAINMATE_FRONTEND"] = "json"
    env["NO_COLOR"] = "1"
    env["PYTHONUNBUFFERED"] = "1"
    if simple:
        env["TRAINMATE_RENDER"] = "simple"
    if wrap_width:
        env["TRAINMATE_WRAP_WIDTH"] = str(wrap_width)
    return env


class _Session:
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
        self.last_message_id: Optional[int] = None  # anchor for a TM-BUTTONS row
        # The message carrying this command's live ✋ Stop button, if any: one at a
        # time, retired when the next wait starts or the command ends
        # (DESIGN_bot_stop_button.md §7).
        self.stop_message_id: Optional[int] = None


async def _exited_within_grace(proc) -> bool:
    """True if proc exited on its own within RESTART_GRACE_SECONDS."""
    try:
        await asyncio.wait_for(proc.wait(), timeout=RESTART_GRACE_SECONDS)
        return True
    except asyncio.TimeoutError:
        return False


async def restart_teardown(session: Optional[_Session], stop_polling) -> None:
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


def main() -> None:
    """Starts the long-polling Telegram bot. Runs until interrupted."""
    token = config.telegram_bot_token
    if not token:
        sys.exit(
            "No Telegram bot token configured. Set TELEGRAM_BOT_TOKEN or add a "
            "telegram.bot_token to config.yaml (see config_template.yaml)."
        )
    allowed_ids = config.telegram_allowed_chat_ids
    if not allowed_ids:
        warn(
            "telegram.allowed_chat_ids is empty — the bot will refuse every message. "
            "Add your numeric chat id to authorize yourself."
        )
    prompt_timeout = config.telegram_prompt_timeout
    command_timeout = config.telegram_command_timeout
    # The persona starts from config but /ui may flip it live (§5.6, in-memory
    # only), so everything derived from it is computed at use time, never captured.
    simple_ui = config.telegram_ui == "simple"

    def _wrap_width() -> int:
        # Simple mode sends prose the client flows itself, so hard-wrapping at phone
        # width would only add ragged mid-sentence breaks — wrap far past any real
        # line instead (§6).
        return 900 if simple_ui else config.telegram_wrap_width

    try:
        from telegram import (
            BotCommand, InlineKeyboardButton, InlineKeyboardMarkup, KeyboardButton,
            ReplyKeyboardMarkup, ReplyKeyboardRemove, Update,
        )
        from telegram.constants import ParseMode
        from telegram.ext import (
            Application, CallbackQueryHandler, MessageHandler, filters,
        )
    except ImportError:
        sys.exit(
            "python-telegram-bot is not installed. Run: "
            + cmd("venv/bin/pip install -r requirements.txt", quote=False)
        )

    sessions: Dict[int, _Session] = {}
    # Simple-mode chat state: chats that just tapped "💬 Talk to me" (chat_id →
    # monotonic arm time, cleared after one message, /cancel or the prompt timeout);
    # the tap only keeps an unroutable message from bouncing (§5.2). Plus the live
    # TM-BUTTONS payload per chat (chat_id → (token, buttons), valid until replaced
    # by the next push, §4.4).
    armed: Dict[int, float] = {}
    ui_actions: Dict[int, Tuple[str, List[dict]]] = {}

    # The persistent §5.1 reply keyboard, two labels per row in table order — built
    # unconditionally, attached (and re-asserted on every message) only while the
    # persona is simple.
    reply_keyboard = ReplyKeyboardMarkup(
        [[KeyboardButton(label) for label, _ in SIMPLE_KEYBOARD[i:i + 2]]
         for i in range(0, len(SIMPLE_KEYBOARD), 2)],
        resize_keyboard=True, is_persistent=True,
    )

    def _keyboard():
        return reply_keyboard if simple_ui else None

    def _log(chat_id: int, direction: str, msg: str) -> None:
        """The bot's own timeline: printed live, and journalled (DESIGN_logging.md §8).

        Also journalled, not instead: an operator watching ./tm-bot in a terminal keeps
        the view they have today. Where that stdout goes depends entirely on how the
        supervisor was launched, which in practice means nowhere."""
        ts = datetime.datetime.now().strftime("%H:%M:%S")
        print(f"{ts} [{chat_id}] {direction} {msg}", flush=True)
        journal.record("bot.event", f"{direction} {msg}", chat=chat_id)

    application = Application.builder().token(token).post_init(_post_init).build()
    bot = application.bot
    updater = application.updater

    # Polling (getUpdates) runs from startup to shutdown, a command in flight or not:
    # a ✋ Stop tap and /cancel are only worth offering if the bot is listening while
    # the coach thinks (DESIGN_bot_stop_button.md §5). The one remaining stop is
    # /restart's, which closes the long-poll before the process exits
    # (DESIGN_bot_restart.md §5.2); the lock guards against a stop racing _serve's own.
    _polling_lock = asyncio.Lock()

    async def _pause_polling() -> None:
        async with _polling_lock:
            if updater.running:
                await updater.stop()

    async def _retire_stop(session: "_Session") -> None:
        """Drops the live Stop button, if there is one: the wait it belonged to is
        over (DESIGN_bot_stop_button.md §7)."""
        message_id, session.stop_message_id = session.stop_message_id, None
        if message_id is None:
            return
        try:
            await bot.edit_message_reply_markup(
                chat_id=session.chat_id, message_id=message_id, reply_markup=None
            )
        except Exception as exc:
            journal.debug("bot.event", f"stop button not dropped: {exc}")

    async def _flush_output(session: "_Session", buf: List[str]) -> bool:
        """Sends the buffered output; True when something went out, so the caller knows
        whether `session.last_message_id` is a fresh anchor to attach buttons to.

        Anything arriving is the end of a wait, so it also retires a live Stop button —
        the flush marker raises the next one (DESIGN_bot_stop_button.md §7)."""
        text = "\n".join(buf).strip()
        if not text:
            return False
        session.sent = True
        for part in format_reply(text, simple=simple_ui):
            sent = await bot.send_message(
                chat_id=session.chat_id, text=part, parse_mode=ParseMode.HTML,
                reply_markup=_keyboard(),
            )
            session.last_message_id = sent.message_id
        _log(session.chat_id, "<<", f"{text.count(chr(10)) + 1} line(s)")
        await _retire_stop(session)
        return True

    async def _offer_stop(session: "_Session") -> None:
        """Hangs a ✋ Stop button off the message the flush just sent — the "Working on
        it..." notice that precedes every coach call (DESIGN_bot_stop_button.md §4)."""
        stop = InlineKeyboardButton(
            STOP_LABEL, callback_data=stop_callback_data(session.nonce)
        )
        keyboard = InlineKeyboardMarkup([[stop]])
        try:
            await bot.edit_message_reply_markup(
                chat_id=session.chat_id, message_id=session.last_message_id,
                reply_markup=keyboard,
            )
        except Exception as exc:
            # The wait still happens; it just can't be tapped away (/cancel still can).
            journal.debug("bot.event", f"stop button not attached: {exc}")
            return
        session.stop_message_id = session.last_message_id
        _log(session.chat_id, "<<", "stop button")

    async def _send_ui_buttons(session: "_Session", req: dict) -> None:
        """Attaches a TM-BUTTONS row to the output just flushed (§4.4). Non-blocking:
        the CLI has already moved on; the payload is stored per chat and taps feed the
        canned utterance back through the normal pipeline. Falls back to its own
        message when there is nothing to anchor to."""
        buttons = [b for b in (req.get("buttons") or []) if isinstance(b, dict)]
        if not buttons:
            return
        token = secrets.token_hex(3)
        ui_actions[session.chat_id] = (token, buttons)
        keyboard = InlineKeyboardMarkup(
            [[InlineKeyboardButton(label, callback_data=data) for label, data in row]
             for row in ui_button_rows(buttons, token)]
        )
        session.sent = True
        if session.last_message_id is not None:
            try:
                await bot.edit_message_reply_markup(
                    chat_id=session.chat_id, message_id=session.last_message_id,
                    reply_markup=keyboard,
                )
                _log(session.chat_id, "<<", f"{len(buttons)} ui button(s)")
                return
            except Exception as exc:
                # Older client / edited race — degrade to a fresh message
                # (DESIGN_logging.md §5.5).
                journal.debug("bot.event", f"button attach failed: {exc}")
        await bot.send_message(
            chat_id=session.chat_id, text="👇", reply_markup=keyboard,
        )
        _log(session.chat_id, "<<", f"{len(buttons)} ui button(s)")

    async def _send_queue_item(session: "_Session", req: dict) -> None:
        """Sends a queued item as a message of its own (DESIGN_athlete_queue.md §6.2). Its
        buttons carry the item, so it neither replaces the chat's TM-BUTTONS row nor
        anchors to the output above it."""
        keyboard = InlineKeyboardMarkup(
            [[InlineKeyboardButton(label, callback_data=data) for label, data in row]
             for row in queue_button_rows(req)]
        )
        session.sent = True
        await bot.send_message(
            chat_id=session.chat_id, text=req.get("text") or "", reply_markup=keyboard,
        )
        _log(session.chat_id, "<<", f"queue item #{req.get('id')}")

    async def _send_photo(session: "_Session", req: dict) -> None:
        """Sends the chart PNG a `--chart` run pointed at, then unlinks the temp
        file regardless of send outcome (§7.2) — the CLI wrote it with
        `delete=False` specifically so the bot owns cleanup."""
        path = req.get("path")
        caption = req.get("caption")
        session.sent = True
        try:
            with open(path, "rb") as f:
                await bot.send_photo(chat_id=session.chat_id, photo=f, caption=caption)
            _log(session.chat_id, "<<", f"photo {path}")
        except Exception as e:
            await bot.send_message(chat_id=session.chat_id, text=f"Could not send chart: {e}")
        finally:
            try:
                os.unlink(path)
            except OSError:
                pass

    async def _present_prompt(session: "_Session", req: dict) -> dict:
        """Renders a prompt, parks until the athlete answers, returns the response
        dict to write back to the CLI's stdin. Idle timeout -> cancellation."""
        loop = asyncio.get_running_loop()
        session.awaiting = req
        session.answer_future = loop.create_future()
        session.sent = True
        message = format_prompt_message(req)
        rows = prompt_buttons(req, session.nonce)
        if rows:
            keyboard = InlineKeyboardMarkup(
                [[InlineKeyboardButton(label, callback_data=data) for label, data in row]
                 for row in rows]
            )
            await bot.send_message(chat_id=session.chat_id, text=message, reply_markup=keyboard)
            _log(session.chat_id, "??", f"{req.get('type')} prompt {req.get('id')}")
        else:  # text prompt: the next message is the answer
            await bot.send_message(
                chat_id=session.chat_id,
                text=message + "\n\n(send your reply, or /cancel)",
            )
            _log(session.chat_id, "??", f"text prompt {req.get('id')}")
        try:
            return await asyncio.wait_for(session.answer_future, timeout=prompt_timeout)
        except asyncio.TimeoutError:
            await bot.send_message(
                chat_id=session.chat_id, text="Prompt timed out — command cancelled."
            )
            return prompt_answer(req.get("id"), cancelled=True)
        finally:
            session.awaiting = None
            session.answer_future = None

    async def _drive(session: "_Session") -> None:
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
                        session.proc.stdout.readline(), timeout=command_timeout
                    )
                except asyncio.TimeoutError:
                    await _flush_output(session, buf)
                    await bot.send_message(
                        chat_id=session.chat_id,
                        text=f"Command timed out after {command_timeout}s.",
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
                    if await _flush_output(session, buf) and flush_wants_a_wait(payload):
                        await _offer_stop(session)
                    buf = []
                    continue
                # Every other frame renders something of its own, so whatever prose is
                # buffered is a message that ends here.
                await _flush_output(session, buf)
                buf = []
                if tag == PHOTO_SENTINEL:
                    await _send_photo(session, payload)
                elif tag == BUTTONS_SENTINEL:
                    await _send_ui_buttons(session, payload)
                elif tag == QUEUE_SENTINEL:
                    await _send_queue_item(session, payload)
                elif tag == PROMPT_SENTINEL:
                    response = await _present_prompt(session, payload)
                    try:
                        session.proc.stdin.write((json.dumps(response) + "\n").encode())
                        await session.proc.stdin.drain()
                    except (BrokenPipeError, ConnectionResetError):
                        break
            await _flush_output(session, buf)
            await session.proc.wait()
            # A scheduler-spawned run (`bot morning` already sent today) may
            # legitimately end silent; only interactive commands owe a reply.
            if not session.sent and not session.quiet:
                await bot.send_message(chat_id=session.chat_id, text="(no output)")
        except Exception as e:  # pragma: no cover - defensive
            _log(session.chat_id, "!!", f"drive error: {e}")
            await bot.send_message(chat_id=session.chat_id, text=f"Internal error: {e}")
        finally:
            sessions.pop(session.chat_id, None)
            if session.proc.returncode is None:
                try:
                    session.proc.kill()
                except ProcessLookupError:
                    pass
            # A command that ends without a last message — killed, or answered with a
            # photo — would otherwise leave a Stop button nothing can act on.
            await _retire_stop(session)

    async def _start_command(
        chat_id: int, argv: List[str], quiet: bool = False, source: str = "bot"
    ) -> "_Session":
        proc = await asyncio.create_subprocess_exec(
            sys.executable, "-u", CLI_PATH, *argv,
            stdin=asyncio.subprocess.PIPE,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.STDOUT,
            env=_cli_env(_wrap_width(), simple=simple_ui, source=source),
            cwd=os.path.dirname(CLI_PATH),
        )
        session = _Session(chat_id, proc, secrets.token_hex(4), quiet=quiet)
        sessions[chat_id] = session
        session.task = asyncio.create_task(_drive(session))
        return session

    async def _route_intent(text: str) -> str:
        """Runs `tm bot route` silently — output captured here, never streamed to the
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
                env=_cli_env(None, source="route"),
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

    async def _simple_route(
        chat_id: int, text: str, armed_tap: bool = False
    ) -> Optional[List[str]]:
        """Maps simple-mode free text onto argv via the intent router (§5.3).
        Replies itself (help text, gentle fallback) and returns None when nothing
        should run; otherwise echoes the routed action and returns the argv.

        `armed_tap` — she just tapped "💬 Talk to me". It never changes a message the
        router could read, so the tap has nothing to explain (§5.2)."""
        intent = await _route_intent(text)
        _log(chat_id, "  ", f"routed: {intent}")
        echo = ROUTER_ECHO.get(intent)
        # State and availability go to the coach in her own words; anything to be
        # remembered goes to the capture inbox, which asks before it stores and costs no
        # adaptation. A misroute across that line degrades gracefully both ways (§12.3).
        if intent in ROUTER_MESSAGE_ARGV:
            argv = [*ROUTER_MESSAGE_ARGV[intent], text]
        elif intent in ROUTER_CAPTURE_INTENTS:
            argv = ["bot", "capture", ROUTER_CAPTURE_INTENTS[intent], text]
        elif intent in ROUTER_INTENT_ARGV:
            argv = list(ROUTER_INTENT_ARGV[intent])
        elif intent == "help":
            await bot.send_message(
                chat_id=chat_id, text=SIMPLE_HELP, reply_markup=_keyboard()
            )
            return None
        else:
            if not armed_tap:
                await bot.send_message(
                    chat_id=chat_id, text=ROUTER_FALLBACK, reply_markup=_keyboard()
                )
                return None
            # A note the router cannot place is still a note (§5.2), and the capture
            # inbox is the one that asks before storing — and still offers the coach on
            # a miss (§12.3).
            _log(chat_id, "  ", "armed: unroutable text rides the capture inbox")
            argv = ["bot", "capture", "note", text]
            echo = CAPTURE_RESCUE_ECHO
        if echo:
            await bot.send_message(
                chat_id=chat_id, text=f"<i>→ {html.escape(echo)}</i>",
                parse_mode=ParseMode.HTML,
            )
        return argv

    def _capture_armed(chat_id: int) -> bool:
        """Consumes a chat's "💬 Talk to me" tap; a stale one (past the prompt
        timeout) reads as untapped, so a next-morning message isn't quietly taken as
        a note (§5.2)."""
        armed_at = armed.pop(chat_id, None)
        return armed_at is not None and (time.monotonic() - armed_at) <= prompt_timeout

    async def _cancel(chat_id: int) -> str:
        armed.pop(chat_id, None)  # /cancel also drops a "💬 Talk to me" tap (§5.2)
        session = sessions.get(chat_id)
        if session is None:
            return "Nothing to cancel."
        fut = session.answer_future
        if session.awaiting and fut is not None and not fut.done():
            fut.set_result(
                prompt_answer(session.awaiting.get("id"), cancelled=True)
            )
        else:  # mid-compute: kill the process; _drive cleans up
            try:
                session.proc.kill()
            except ProcessLookupError:
                pass
        return "Cancelling…"

    async def _set_ui(chat_id: int, target: bool, announce: bool = True) -> None:
        """Flips the persona in place (§5.6): swaps the command menu, then confirms —
        attaching the reply keyboard on the way into simple, removing it on the way
        out. `announce=False` skips the confirmation for a switch nobody asked for.
        In-memory only; config.telegram_ui rules again at the next restart."""
        nonlocal simple_ui
        simple_ui = target
        commands = SIMPLE_MENU_COMMANDS if target else MENU_COMMANDS
        try:
            await bot.set_my_commands([BotCommand(n, d) for n, d in commands])
        except Exception as exc:  # the menu is cosmetic — never let it stop the switch
            journal.debug("bot.event", f"command menu not updated: {exc}")
        if announce and target:
            await bot.send_message(
                chat_id=chat_id, text=UI_SIMPLE_ON, reply_markup=reply_keyboard
            )
        elif announce:
            await bot.send_message(
                chat_id=chat_id, text=UI_EXPERT_ON, reply_markup=ReplyKeyboardRemove()
            )
        _log(chat_id, "  ", f"ui: {'simple' if target else 'expert'}")

    async def _restart(chat_id: int) -> None:
        """Tears down, replies, then hard-exits with RESTART_EXIT_CODE for the tm-bot
        supervisor to relaunch us. See DESIGN_bot_restart.md §5.2."""
        await restart_teardown(sessions.get(chat_id), _pause_polling)
        await bot.send_message(chat_id=chat_id, text="Restarting…")
        os._exit(RESTART_EXIT_CODE)

    async def on_message(update: "Update", context) -> None:
        message = update.effective_message
        chat = update.effective_chat
        if message is None or chat is None or not message.text:
            return

        text = message.text.strip()
        _log(chat.id, ">>", repr(text))

        if not is_authorized(chat.id, allowed_ids):
            _log(chat.id, "--", "unauthorized")
            await message.reply_text(
                f"Not authorized. Your chat id is {chat.id}; add it to "
                "telegram.allowed_chat_ids to enable access."
            )
            return

        token_low = text.lstrip("/").lower()
        if token_low == "cancel":
            await message.reply_text(await _cancel(chat.id))
            return
        if token_low == "start":
            if simple_ui:
                await message.reply_text(SIMPLE_WELCOME, reply_markup=_keyboard())
            else:
                await message.reply_text(WELCOME)
            return
        if token_low == "help" and simple_ui:
            # Bare help gets the companion card; `/help <cmd>` still reaches the CLI
            # tree for the operator (§5.1).
            await message.reply_text(SIMPLE_HELP, reply_markup=_keyboard())
            return
        if token_low == "restart":
            await _restart(chat.id)
            return
        if token_low == "ui" or token_low.startswith("ui "):
            target = parse_ui_switch(token_low, simple_ui)
            if target is None:
                await message.reply_text(UI_USAGE)
                return
            await _set_ui(chat.id, target)
            return

        session = sessions.get(chat.id)
        if session is not None:
            awaiting = session.awaiting
            fut = session.answer_future
            if (awaiting and awaiting.get("type") == "text"
                    and fut is not None and not fut.done()):
                fut.set_result(prompt_answer(awaiting.get("id"), answer=text))
                _log(chat.id, "  ", "text answer")
                return
            await message.reply_text(
                "A command is still running. Use the buttons above, or /cancel."
            )
            return

        # About to act on the athlete's own message: what changed in their week goes first.
        await _tell_changes_first(chat.id)

        # A tap on the companion keyboard is the companion, whatever persona this
        # process last settled on: the keyboard sits on the phone until Telegram is
        # told to drop it, so a restart back into expert leaves it live (§5.6).
        if stale_keyboard_tap(text, simple_ui):
            # Silently: she tapped a button, not /ui — the answer to the tap is the
            # only feedback the switch earns (§5.6).
            await _set_ui(chat.id, True, announce=False)

        # Simple mode: non-slash text is the companion surface — keyboard labels,
        # then the free-text router for everything else (§5). A leading slash stays
        # the expert path, so the operator can still drive the instance from its chat.
        if simple_ui and not text.startswith("/"):
            action = keyboard_action(text)
            if action is not None and action[0] == "capture":
                armed[chat.id] = time.monotonic()
                await message.reply_text(CAPTURE_PROMPT, reply_markup=_keyboard())
                return
            if action is not None:
                argv = list(action[1])
            else:
                await context.bot.send_chat_action(chat_id=chat.id, action="typing")
                # Read the tap here so it is consumed once per message, routed or not.
                argv = await _simple_route(chat.id, text, _capture_armed(chat.id))
                if argv is None:
                    return
            _log(chat.id, "  ", f"run: {shlex.join(argv)}")
            await context.bot.send_chat_action(chat_id=chat.id, action="typing")
            await _start_command(chat.id, argv)
            return

        bot_username = context.bot.username if context.bot else None
        try:
            argv = parse_message_to_argv(text, bot_username)
        except ValueError:
            await message.reply_text("Couldn't parse that — check your quotes.")
            return
        if not argv:
            return

        _log(chat.id, "  ", f"run: {shlex.join(argv)}")
        await context.bot.send_chat_action(chat_id=chat.id, action="typing")
        await _start_command(chat.id, argv)

    async def _handle_ui_callback(query, chat_id: int, data: str) -> None:
        """A tap on a non-blocking TM-BUTTONS row (§4.4): a stale token drops the dead
        buttons; a `menu` button swaps the row for its sub-choices; `send` feeds the
        canned utterance through the normal command pipeline; `ack` just replies."""
        decoded = decode_ui_callback(data)
        current = ui_actions.get(chat_id)
        if decoded is None or current is None or decoded[0] != current[0]:
            try:  # replaced by a newer row: drop the dead buttons
                await query.edit_message_reply_markup(reply_markup=None)
            except Exception as exc:
                journal.debug("bot.event", f"stale buttons not dropped: {exc}")
            # One live row per chat, so any newer row — the morning push included —
            # retires this one. Saying so matters: the message behind a retired offer
            # was already consumed by the capture, so silence loses it twice (§12.3).
            await bot.send_message(chat_id=chat_id, text=UI_STALE_TAP)
            return
        token, path = decoded
        action = resolve_ui_action(current[1], path)
        if action is None:
            return
        menu = action.get("menu")
        if menu:
            rows = ui_menu_rows(menu, token, path)
            keyboard = InlineKeyboardMarkup(
                [[InlineKeyboardButton(label, callback_data=cb) for label, cb in row]
                 for row in rows]
            )
            try:
                await query.edit_message_reply_markup(reply_markup=keyboard)
            except Exception as exc:
                journal.debug("bot.event", f"sub-menu not swapped in: {exc}")
            return
        utterance = action.get("send")
        if utterance and sessions.get(chat_id) is not None:
            # Busy chat: leave the buttons alive so the tap can be retried.
            await bot.send_message(chat_id=chat_id, text=BUSY_TAP)
            return
        _log(chat_id, "  ", f"ui tap: {action.get('label')}")
        try:  # a decided row is spent: drop the buttons
            await query.edit_message_reply_markup(reply_markup=None)
        except Exception as exc:
            journal.debug("bot.event", f"spent buttons not dropped: {exc}")
        ui_actions.pop(chat_id, None)
        if not utterance:
            ack = action.get("ack")
            if ack:
                await bot.send_message(chat_id=chat_id, text=str(ack))
            return
        try:
            argv = parse_message_to_argv(str(utterance))
        except ValueError:
            argv = None
        if not argv:
            return
        _log(chat_id, "  ", f"run: {shlex.join(argv)}")
        await bot.send_chat_action(chat_id=chat_id, action="typing")
        await _start_command(chat_id, argv)

    async def _handle_queue_callback(query, chat_id: int, data: str) -> None:
        """A tap on a queued item's button (DESIGN_athlete_queue.md §6.2). "Not now" swaps
        in the three later choices; any other tap leaves the choice under the item's text
        and runs `bot queue`, which checks the item and sends the next one. The chat's live
        TM-BUTTONS row is not touched."""
        decoded = decode_queue_callback(data)
        if decoded is None:
            return
        item_id, action, since = decoded
        if action == QUEUE_NOT_NOW:
            keyboard = InlineKeyboardMarkup(
                [[InlineKeyboardButton(label, callback_data=cb) for label, cb in row]
                 for row in queue_later_rows(item_id, since)]
            )
            try:
                await query.edit_message_reply_markup(reply_markup=keyboard)
            except Exception as exc:
                journal.debug("bot.event", f"later choices not swapped in: {exc}")
            return
        if sessions.get(chat_id) is not None:
            await bot.send_message(chat_id=chat_id, text=BUSY_TAP)
            return
        message = query.message
        markup = getattr(message, "reply_markup", None)
        rows = [[(b.text, b.callback_data) for b in row]
                for row in (markup.inline_keyboard if markup else [])]
        label = tapped_label(rows, data)
        try:  # the message keeps its text, gains the choice and loses its buttons (§6.1)
            if label and getattr(message, "text", None):
                await query.edit_message_text(text=f"{message.text}\n\n→ {label}")
            else:
                await query.edit_message_reply_markup(reply_markup=None)
        except Exception as exc:
            journal.debug("bot.event", f"queue choice not echoed: {exc}")
        argv = ["bot", "queue", item_id, action, "--since", since]
        _log(chat_id, "  ", f"run: {shlex.join(argv)}")
        await _start_command(chat_id, argv, quiet=True)

    async def _handle_stop_callback(query, chat_id: int, data: str) -> None:
        """A tap on the §3 Stop button: ends the command it was raised for, the same
        kill /cancel does. A tap left over from a command that already finished says so
        rather than reaching whatever started since (DESIGN_bot_stop_button.md §7)."""
        nonce = decode_stop_callback(data)
        session = sessions.get(chat_id)
        if nonce is None or session is None or session.nonce != nonce:
            try:  # the command is over: drop the dead button
                await query.edit_message_reply_markup(reply_markup=None)
            except Exception as exc:
                journal.debug("bot.event", f"stale stop button not dropped: {exc}")
            await bot.send_message(chat_id=chat_id, text=STOP_ALREADY_DONE)
            return
        _log(chat_id, "  ", "stop tap")
        await _retire_stop(session)
        await _cancel(chat_id)  # its reply line is /cancel's wording; a tap gets §6's
        await bot.send_message(chat_id=chat_id, text=STOP_DONE, reply_markup=_keyboard())

    async def on_callback(update: "Update", context) -> None:
        query = update.callback_query
        chat = update.effective_chat
        if query is None or chat is None:
            return
        await query.answer()
        if not is_authorized(chat.id, allowed_ids):
            return
        data = query.data or ""
        # A tap on an offer is the athlete's own input: what changed in their week goes
        # first. A prompt answer or a Stop tap belongs to a command already running.
        if data.startswith(("q:", "ui:")):
            await _tell_changes_first(chat.id)
        if data.startswith("q:"):
            await _handle_queue_callback(query, chat.id, data)
            return
        if data.startswith("ui:"):
            await _handle_ui_callback(query, chat.id, data)
            return
        if data.startswith("stop:"):
            await _handle_stop_callback(query, chat.id, data)
            return
        decoded = decode_callback(query.data or "")
        if decoded is None:
            return
        nonce, pid, value = decoded
        session = sessions.get(chat.id)
        awaiting = session.awaiting if session else None
        fut = session.answer_future if session else None
        if (session is None or session.nonce != nonce or awaiting is None
                or awaiting.get("id") != pid or fut is None or fut.done()):
            try:  # stale tap (session replaced/expired): drop the dead buttons
                await query.edit_message_reply_markup(reply_markup=None)
            except Exception as exc:
                journal.debug("bot.event", f"expired prompt buttons not dropped: {exc}")
            return

        if awaiting.get("type") == "confirm":
            answer = value == "y"
            chosen = "Yes" if answer else "No"
            fut.set_result(prompt_answer(pid, answer=answer))
        else:
            chosen = next((c["label"] for c in awaiting.get("choices", [])
                           if c["value"] == value), value)
            fut.set_result(prompt_answer(pid, answer=value))
        _log(chat.id, "  ", f"answer: {chosen}")
        try:  # echo the choice in place of the buttons
            await query.edit_message_text(text=f"{format_prompt_message(awaiting)}\n\n→ {chosen}")
        except Exception as exc:
            journal.debug("bot.event", f"answer not echoed into the prompt: {exc}")

    # The morning push goes to the first allowlisted chat — the single-athlete
    # instance model makes that the athlete (§4.3).
    push_chat_id = allowed_ids[0] if allowed_ids else None

    async def _run_scheduled(argv: List[str], wait: bool) -> None:
        """Starts a scheduler-run command in the push chat; `wait` holds the wake until it
        has finished (DESIGN_athlete_queue.md §6.5)."""
        _log(push_chat_id, "**", shlex.join(argv))
        session = await _start_command(push_chat_id, argv, quiet=True, source="push")
        if wait:
            await session.task

    async def _tell_changes_first(chat_id: int) -> None:
        """Sends the changes to the athlete's week not told yet, before acting on their own
        tap or message, whatever the hour and however young the change
        (DESIGN_change_heads_up.md §4)."""
        if chat_id != push_chat_id or sessions.get(chat_id) is not None:
            return
        if not heads_up.waiting():
            return
        await _run_scheduled(["bot", "changes"], True)

    # Held until each ends: asyncio keeps only a weak reference to a running task.
    reflect_tasks: set = set()

    async def _reflect_outside_chat() -> None:
        """`data reflect --auto` as a process of its own, like the router: nothing is posted,
        the chat is not busy, and its output goes to the journal
        (DESIGN_learning_doubt_nudge.md §3.1)."""
        argv = ["data", "reflect", "--auto"]
        _log(push_chat_id, "**", shlex.join(argv))
        env = _cli_env(None, source="push")
        env.pop("TRAINMATE_FRONTEND")  # a terminal report for the journal, no chat sentinels
        try:
            proc = await asyncio.create_subprocess_exec(
                sys.executable, "-u", CLI_PATH, *argv,
                stdin=asyncio.subprocess.DEVNULL,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.STDOUT,
                env=env,
                cwd=os.path.dirname(CLI_PATH),
            )
            out, _ = await proc.communicate()
        except Exception as exc:
            journal.record("bot.reflect", f"did not run: {exc}", lvl="warn")
            return
        journal.record(
            "bot.reflect", strip_ansi(out.decode(errors="replace")).strip(),
            exit_code=proc.returncode,
        )

    def _start_reflect() -> None:
        task = asyncio.create_task(_reflect_outside_chat())
        reflect_tasks.add(task)
        task.add_done_callback(reflect_tasks.discard)

    async def _push_loop() -> None:
        """One `scheduler_wake` after another (§4.3). Real idempotency lives in the
        database marker `bot morning` checks; `last_run` only avoids re-spawning the
        subprocess every tick within one bot lifetime."""
        last_run: Dict[str, str] = {}
        while True:
            pause = await scheduler_wake(
                last_run, simple_ui, lambda: sessions.get(push_chat_id) is not None,
                _run_scheduled, _start_reflect,
            )
            if pause:
                await asyncio.sleep(pause)

    async def _serve() -> None:
        """Runs the bot until SIGINT/SIGTERM. Equivalent to Application.run_polling(),
        but with the Updater started and stopped explicitly instead of being wired to
        the Application's own lifetime: /restart has to close the long-poll from inside
        a handler, before its hard exit, and run_polling() doesn't expose that
        (DESIGN_bot_restart.md §5.2 and §7)."""
        stop_event = asyncio.Event()
        loop = asyncio.get_running_loop()
        for sig in (signal.SIGINT, signal.SIGTERM):
            loop.add_signal_handler(sig, stop_event.set)
        async with application:
            await application.start()
            await updater.start_polling(allowed_updates=Update.ALL_TYPES)
            # Started whenever there is a chat to push to: the persona and the `push`
            # setting are checked per tick inside the loop, so a /ui flip (§5.6) or a
            # `settings set push off` turns it on and off live (DESIGN_settings.md §5).
            push_task = (asyncio.create_task(_push_loop())
                         if push_chat_id is not None else None)
            await stop_event.wait()
            if push_task is not None:
                push_task.cancel()
            if updater.running:
                await updater.stop()
            await application.stop()

    # filters.TEXT catches commands too (a '/status' message is still text).
    application.add_handler(MessageHandler(filters.TEXT, on_message))
    application.add_handler(CallbackQueryHandler(on_callback))
    print("TrainMate Telegram bot started. Press Ctrl-C to stop.")
    # One long-lived run for the whole process, so the bot's own lifetime is a readable
    # timeline and every subprocess it spawns names it as their parent
    # (DESIGN_logging.md §8). It gets a `run.end` only on a clean shutdown: a /restart
    # hard-exits and a supervisor kill takes it with no warning, which is the normal way
    # it ends and the reason the `?` outcome exists (§3).
    journal.start_run(["tm-bot"], source="bot")
    asyncio.run(_serve())
    journal.end_run("ok")


async def _post_init(app) -> None:
    from telegram import BotCommand
    commands = (
        SIMPLE_MENU_COMMANDS if config.telegram_ui == "simple" else MENU_COMMANDS
    )
    await app.bot.set_my_commands([BotCommand(name, desc) for name, desc in commands])


if __name__ == "__main__":
    main()
