"""Everything the bot puts into the chat on behalf of a running command.

A CLI run reaches the athlete as one of five things: a block of prose, a chart photo, a
row of offer buttons, a queued item, or a question that parks the command until it is
answered. Each has a sender here, and `runner._drive` picks between them by the sentinel
tag it just read (DESIGN_output_verbosity.md §7, DESIGN_bot_simple_frontend.md §4.4,
DESIGN_athlete_queue.md §6.2).

The ✋ Stop button lives here too, because it is raised and retired by the same flushes:
one per chat at a time, hung off the "Working on it…" message that precedes a coach call
(DESIGN_bot_stop_button.md §4, §7).
"""
import asyncio
import html
import os
import secrets
from typing import List

from stamind import journal
from stamind.chat import telegram_api
from stamind.chat.keyboards import (
    STOP_LABEL, prompt_buttons, queue_button_rows, stop_callback_data, ui_button_rows,
)
from stamind.chat.runner import Session
from stamind.sentinels import prompt_answer
from stamind.text import strip_ansi

# Telegram caps a message at 4096 chars; we wrap replies in <pre>…</pre> (7 chars
# of overhead) and want headroom, so chunk the body well under the hard limit.
MAX_MESSAGE_CHARS = 3800


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


class RepliesMixin:
    """`ChatBot`'s half that sends a running command's output back to the chat."""

    async def _retire_stop(self, session: Session) -> None:
        """Drops the live Stop button, if there is one: the wait it belonged to is
        over (DESIGN_bot_stop_button.md §7)."""
        message_id, session.stop_message_id = session.stop_message_id, None
        if message_id is None:
            return
        try:
            await self.bot.edit_message_reply_markup(
                chat_id=session.chat_id, message_id=message_id, reply_markup=None
            )
        except Exception as exc:
            journal.debug("bot.event", f"stop button not dropped: {exc}")

    async def _flush_output(self, session: Session, buf: List[str]) -> bool:
        """Sends the buffered output; True when something went out, so the caller knows
        whether `session.last_message_id` is a fresh anchor to attach buttons to.

        Anything arriving is the end of a wait, so it also retires a live Stop button —
        the flush marker raises the next one (DESIGN_bot_stop_button.md §7)."""
        text = "\n".join(buf).strip()
        if not text:
            return False
        session.sent = True
        parse_mode = telegram_api.html_parse_mode()
        for part in format_reply(text, simple=self.simple_ui):
            sent = await self.bot.send_message(
                chat_id=session.chat_id, text=part, parse_mode=parse_mode,
                reply_markup=self._keyboard(),
            )
            session.last_message_id = sent.message_id
        self._log(session.chat_id, "<<", f"{text.count(chr(10)) + 1} line(s)")
        await self._retire_stop(session)
        return True

    async def _offer_stop(self, session: Session) -> None:
        """Hangs a ✋ Stop button off the message the flush just sent — the wait notice
        that precedes every coach call (DESIGN_bot_stop_button.md §4)."""
        keyboard = telegram_api.inline_keyboard(
            [[(STOP_LABEL, stop_callback_data(session.nonce))]]
        )
        try:
            await self.bot.edit_message_reply_markup(
                chat_id=session.chat_id, message_id=session.last_message_id,
                reply_markup=keyboard,
            )
        except Exception as exc:
            # The wait still happens; it just can't be tapped away (/cancel still can).
            journal.debug("bot.event", f"stop button not attached: {exc}")
            return
        session.stop_message_id = session.last_message_id
        self._log(session.chat_id, "<<", "stop button")

    async def _send_ui_buttons(self, session: Session, req: dict) -> None:
        """Attaches a TM-BUTTONS row to the output just flushed (§4.4). Non-blocking:
        the CLI has already moved on; the payload is stored per chat and taps feed the
        canned utterance back through the normal pipeline. Falls back to its own
        message when there is nothing to anchor to."""
        buttons = [b for b in (req.get("buttons") or []) if isinstance(b, dict)]
        if not buttons:
            return
        token = secrets.token_hex(3)
        self.ui_actions[session.chat_id] = (token, buttons)
        keyboard = telegram_api.inline_keyboard(ui_button_rows(buttons, token))
        session.sent = True
        if session.last_message_id is not None:
            try:
                await self.bot.edit_message_reply_markup(
                    chat_id=session.chat_id, message_id=session.last_message_id,
                    reply_markup=keyboard,
                )
                self._log(session.chat_id, "<<", f"{len(buttons)} ui button(s)")
                return
            except Exception as exc:
                # Older client / edited race — degrade to a fresh message
                # (DESIGN_logging.md §5.5).
                journal.debug("bot.event", f"button attach failed: {exc}")
        await self.bot.send_message(
            chat_id=session.chat_id, text="👇", reply_markup=keyboard,
        )
        self._log(session.chat_id, "<<", f"{len(buttons)} ui button(s)")

    async def _send_queue_item(self, session: Session, req: dict) -> None:
        """Sends a queued item as a message of its own (DESIGN_athlete_queue.md §6.2). Its
        buttons carry the item, so it neither replaces the chat's TM-BUTTONS row nor
        anchors to the output above it."""
        keyboard = telegram_api.inline_keyboard(queue_button_rows(req))
        session.sent = True
        await self.bot.send_message(
            chat_id=session.chat_id, text=req.get("text") or "", reply_markup=keyboard,
        )
        self._log(session.chat_id, "<<", f"queue item #{req.get('id')}")

    async def _send_photo(self, session: Session, req: dict) -> None:
        """Sends the chart PNG a `--chart` run pointed at, then unlinks the temp
        file regardless of send outcome (§7.2) — the CLI wrote it with
        `delete=False` specifically so the bot owns cleanup."""
        path = req.get("path")
        caption = req.get("caption")
        session.sent = True
        try:
            with open(path, "rb") as f:
                await self.bot.send_photo(
                    chat_id=session.chat_id, photo=f, caption=caption
                )
            self._log(session.chat_id, "<<", f"photo {path}")
        except Exception as e:
            await self.bot.send_message(
                chat_id=session.chat_id, text=f"Could not send chart: {e}"
            )
        finally:
            try:
                os.unlink(path)
            except OSError:
                pass

    async def _present_prompt(self, session: Session, req: dict) -> dict:
        """Renders a prompt, parks until the athlete answers, returns the response
        dict to write back to the CLI's stdin. Idle timeout -> cancellation."""
        loop = asyncio.get_running_loop()
        session.awaiting = req
        session.answer_future = loop.create_future()
        session.sent = True
        message = format_prompt_message(req)
        rows = prompt_buttons(req, session.nonce)
        if rows:
            keyboard = telegram_api.inline_keyboard(rows)
            await self.bot.send_message(
                chat_id=session.chat_id, text=message, reply_markup=keyboard
            )
            self._log(session.chat_id, "??", f"{req.get('type')} prompt {req.get('id')}")
        else:  # text prompt: the next message is the answer
            await self.bot.send_message(
                chat_id=session.chat_id,
                text=message + "\n\n(send your reply, or /cancel)",
            )
            self._log(session.chat_id, "??", f"text prompt {req.get('id')}")
        try:
            return await asyncio.wait_for(
                session.answer_future, timeout=self.prompt_timeout
            )
        except asyncio.TimeoutError:
            await self.bot.send_message(
                chat_id=session.chat_id, text="Prompt timed out — command cancelled."
            )
            return prompt_answer(req.get("id"), cancelled=True)
        finally:
            session.awaiting = None
            session.answer_future = None
