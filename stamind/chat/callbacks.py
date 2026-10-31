"""What the bot does when the athlete taps a button.

Every inline button in the chat comes back through `on_callback`, which reads the
namespace the tap's callback data opens with and hands it on: `q:` is a queued item's
answer, `ui:` is a SM-BUTTONS offer, and a bare `nonce:id:answer` is the answer to the
prompt a running command is parked on. The three namespaces share one Telegram channel, so
each decoder rejects the other two — a stale tap must never turn into an action meant for
something else (DESIGN_bot_stop_button.md §7, DESIGN_athlete_queue.md §6.2,
DESIGN_bot_simple_frontend.md §4.4).
"""
import functools
import shlex
from typing import Callable, NamedTuple, Optional

from stamind import athlete_queue, journal, runtime
from stamind.athlete_queue import QUEUE_NOT_NOW
from stamind.chat import telegram_api
from stamind.chat.keyboards import (
    BUSY_TAP, UI_STALE_TAP, answers_kept, decode_callback, decode_queue_callback,
    decode_ui_callback, pages_kept, queue_callback_data, queue_later_rows, resolve_ui_action,
    tapped_choice, tapped_label, ui_menu_rows,
)
from stamind.chat.replies import format_prompt_message
from stamind.chat.routing import parse_message_to_argv
from stamind.chat.runner import COACH_ASKED
from stamind.sentinels import prompt_answer


def _keyboard_rows(message) -> list:
    """The tapped message's inline keyboard, as rows of (label, callback data); a page button
    reads as its page cell (DESIGN_short_messages.md §5)."""
    markup = getattr(message, "reply_markup", None)
    return [[(b.text, _cell_data(b)) for b in row]
            for row in (markup.inline_keyboard if markup else [])]


def _cell_data(button) -> str:
    web_app = getattr(button, "web_app", None)
    if web_app is not None:
        return telegram_api.PAGE_CELL + web_app.url
    return button.callback_data


def _keyboard_or_none(rows: list):
    """An inline keyboard of `rows`, or None, which drops the message's keyboard."""
    if not rows:
        return None
    return telegram_api.inline_keyboard(rows)


def tap_long_run(item_id: str, action: str) -> Optional[str]:
    """Which long run a tap on a queued item's answer starts, or None: the item's kind
    names the answer that starts one (DESIGN_long_runs_beside_chat.md §6)."""
    item = runtime.db.get_queue_item(int(item_id))
    if item is None or item["closed_at"]:
        return None
    return athlete_queue.long_run_name(item, action)


class AnsweredMessage(NamedTuple):
    """The message a queued item's answer is left under: its text, its keyboard's rows, the
    label of the chosen button, and the two calls that edit it."""
    text: Optional[str]
    rows: list
    label: Optional[str]
    edit_text: Callable
    edit_markup: Callable


async def _leave_choice(message: AnsweredMessage) -> None:
    """The message keeps its text, gains the choice and loses its buttons (§6.1), but for a
    page button, which stays (DESIGN_short_messages.md §5)."""
    pages = _keyboard_or_none(pages_kept(message.rows))
    try:
        if message.label and message.text:
            await message.edit_text(
                text=f"{message.text}\n\n→ {message.label}", reply_markup=pages
            )
        else:
            await message.edit_markup(reply_markup=pages)
    except Exception as exc:
        journal.debug("bot.event", f"queue choice not echoed: {exc}")


class CallbacksMixin:
    """`ChatBot`'s half that answers a tap on one of the three button namespaces."""

    async def _handle_ui_callback(self, query, chat_id: int, data: str) -> None:
        """A tap on a non-blocking SM-BUTTONS row (§4.4): a stale token drops the dead
        buttons; a `menu` button swaps the row for its sub-choices; `send` feeds the
        canned utterance through the normal command pipeline; `ack` just replies."""
        decoded = decode_ui_callback(data)
        current = self.ui_actions.get(chat_id)
        # The answers of a queued item the offer was sent under: they stay whatever
        # becomes of the offer (DESIGN_waiting_proposal.md §5).
        answers = answers_kept(_keyboard_rows(query.message))
        if decoded is None or current is None or decoded[0] != current[0]:
            try:  # replaced by a newer row: drop the dead buttons
                await query.edit_message_reply_markup(reply_markup=_keyboard_or_none(answers))
            except Exception as exc:
                journal.debug("bot.event", f"stale buttons not dropped: {exc}")
            # One live row per chat, so any newer row — the morning push included —
            # retires this one. Saying so matters: the message behind a retired offer
            # was already consumed by the capture, so silence loses it twice (§12.3).
            await self.bot.send_message(chat_id=chat_id, text=UI_STALE_TAP)
            return
        token, path = decoded
        action = resolve_ui_action(current[1], path)
        if action is None:
            return
        menu = action.get("menu")
        if menu:
            keyboard = telegram_api.inline_keyboard(
                answers + ui_menu_rows(menu, token, path)
            )
            try:
                await query.edit_message_reply_markup(reply_markup=keyboard)
            except Exception as exc:
                journal.debug("bot.event", f"sub-menu not swapped in: {exc}")
            return
        utterance = action.get("send")
        if utterance and self.sessions.get(chat_id) is not None:
            # Busy chat: leave the buttons alive so the tap can be retried.
            await self.bot.send_message(chat_id=chat_id, text=BUSY_TAP)
            return
        argv = None
        if utterance:
            try:
                argv = parse_message_to_argv(str(utterance))
            except ValueError:
                argv = None
        # A fixed sentence for the coach is kept like a typed one. While the long run alive
        # waits on a question of its own it is refused, before its row goes, so it can be
        # tapped again (DESIGN_long_runs_beside_chat.md §7).
        held = await self._keep_behind(chat_id, argv) if argv else None
        if held == COACH_ASKED:
            return
        self._log(chat_id, "  ", f"ui tap: {action.get('label')}")
        try:  # a decided row is spent: drop the buttons
            await query.edit_message_reply_markup(reply_markup=_keyboard_or_none(answers))
        except Exception as exc:
            journal.debug("bot.event", f"spent buttons not dropped: {exc}")
        self.ui_actions.pop(chat_id, None)
        if not utterance:
            ack = action.get("ack")
            if ack:
                await self.bot.send_message(chat_id=chat_id, text=str(ack))
            return
        if not argv or held:
            return
        self._log(chat_id, "  ", f"run: {shlex.join(argv)}")
        await self.bot.send_chat_action(chat_id=chat_id, action="typing")
        await self._start_command(chat_id, argv)

    async def _handle_queue_callback(self, query, chat_id: int, data: str) -> None:
        """A tap on a queued item's button (DESIGN_athlete_queue.md §6.2). "Not now" swaps
        in the two later choices; any other tap leaves the choice under the item's text
        and runs `bot queue`, which checks the item and sends the next one. The chat's live
        SM-BUTTONS row is not touched, unless it was sent under this item: then it goes
        with the item's buttons (DESIGN_waiting_proposal.md §5).

        A tap on an answer that starts a long run runs beside the chat, and is kept while
        another long run is alive (DESIGN_long_runs_beside_chat.md §6, §7). A typed answer
        takes the same path, from `_answer_typed` (§14.2)."""
        decoded = decode_queue_callback(data)
        if decoded is None:
            return
        item_id, action = decoded
        if action == QUEUE_NOT_NOW:
            keyboard = telegram_api.inline_keyboard(queue_later_rows(item_id))
            try:
                await query.edit_message_reply_markup(reply_markup=keyboard)
            except Exception as exc:
                journal.debug("bot.event", f"later choices not swapped in: {exc}")
            return
        rows = _keyboard_rows(query.message)
        await self._run_queue_answer(chat_id, item_id, action, AnsweredMessage(
            getattr(query.message, "text", None), rows, tapped_label(rows, data),
            query.edit_message_text, query.edit_message_reply_markup,
        ))

    def _remembered_message(self, chat_id: int, item_id: str, action: str):
        """The message a typed answer is left under, from what the bot remembers, or None.
        The chosen button is among its rows, or among the two later choices "Not now" swaps
        in (DESIGN_athlete_queue.md §14.3)."""
        sent = self.sent_questions.get(chat_id, {}).get(item_id)
        if sent is None:
            return None
        edited = {"chat_id": chat_id, "message_id": sent.message_id}
        return AnsweredMessage(
            sent.text, sent.rows,
            tapped_label(
                sent.rows + queue_later_rows(item_id), queue_callback_data(item_id, action)
            ),
            functools.partial(self.bot.edit_message_text, **edited),
            functools.partial(self.bot.edit_message_reply_markup, **edited),
        )

    async def _answer_typed(self, chat_id: int, item_id: str, action: str, text: str) -> bool:
        """A typed message that answers a queued item runs what a tap on that button runs,
        with the athlete's words (DESIGN_athlete_queue.md §14.2). False when it was refused."""
        message = self._remembered_message(chat_id, item_id, action)
        return await self._run_queue_answer(chat_id, item_id, action, message, text)

    async def _run_queue_answer(
        self, chat_id: int, item_id: str, action: str, message: Optional[AnsweredMessage],
        text: Optional[str] = None,
    ) -> bool:
        """Runs `bot queue` for one answer, tapped or typed, and leaves the choice under its
        message when there is one. False when the answer was refused: the chat is busy, or
        the long run alive asks. Refused before the buttons go, so it can be given again
        (DESIGN_long_runs_beside_chat.md §7)."""
        if self.sessions.get(chat_id) is not None:
            await self.bot.send_message(chat_id=chat_id, text=BUSY_TAP)
            return False
        run = tap_long_run(item_id, action)
        argv = ["bot", "queue", item_id, action]
        if text:
            # One word with its flag, so a message that opens with a dash stays the value.
            argv.append(f"--text={text}")
        held = await self._keep_behind(chat_id, argv, quiet=True, run=run) if run else None
        if held == COACH_ASKED:
            return False
        self.sent_questions.get(chat_id, {}).pop(item_id, None)
        if message is not None:
            await _leave_choice(message)
        if held:
            return True
        self._log(chat_id, "  ", f"run: {shlex.join(argv)}")
        await self._start_command(chat_id, argv, quiet=True, run=run)
        return True

    async def on_callback(self, update, context) -> None:
        query = update.callback_query
        chat = update.effective_chat
        if query is None or chat is None:
            return
        await query.answer()
        if not self._authorized(chat.id):
            return
        data = query.data or ""
        # A tap on an offer is the athlete's own input: what changed in their week goes
        # first. A prompt answer belongs to a command already running.
        if data.startswith(("q:", "ui:")):
            await self._tell_changes_first(chat.id)
        if data.startswith("q:"):
            await self._handle_queue_callback(query, chat.id, data)
            return
        if data.startswith("ui:"):
            await self._handle_ui_callback(query, chat.id, data)
            return
        decoded = decode_callback(query.data or "")
        if decoded is None:
            return
        nonce, pid, value = decoded
        # Found by the run that raised it: a long run asks from the second place.
        session = self._run_by_nonce(chat.id, nonce)
        awaiting = session.awaiting if session else None
        fut = session.answer_future if session else None
        if (session is None or awaiting is None
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
            choice = tapped_choice(awaiting, value)
            if choice is None:
                return
            chosen = choice["label"]
            fut.set_result(prompt_answer(pid, answer=choice["value"]))
        self._log(chat.id, "  ", f"answer: {chosen}")
        try:  # echo the choice in place of the buttons
            await query.edit_message_text(
                text=f"{format_prompt_message(awaiting)}\n\n→ {chosen}"
            )
        except Exception as exc:
            journal.debug("bot.event", f"answer not echoed into the prompt: {exc}")
