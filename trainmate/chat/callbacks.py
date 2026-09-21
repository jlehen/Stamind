"""What the bot does when the athlete taps a button.

Every inline button in the chat comes back through `on_callback`, which reads the
namespace the tap's callback data opens with and hands it on: `q:` is a queued item's
answer, `ui:` is a TM-BUTTONS offer, `stop:` ends the command being waited on, and a bare
`nonce:id:value` is the answer to the prompt a running command is parked on. The four
namespaces share one Telegram channel, so each decoder rejects the other three — a stale
tap must never turn into an action meant for something else (DESIGN_bot_stop_button.md §7,
DESIGN_athlete_queue.md §6.2, DESIGN_bot_simple_frontend.md §4.4).
"""
import shlex

from trainmate import journal
from trainmate.athlete_queue import QUEUE_NOT_NOW
from trainmate.chat import telegram_api
from trainmate.chat.keyboards import (
    BUSY_TAP, STOP_ALREADY_DONE, STOP_DONE, UI_STALE_TAP, decode_callback,
    decode_queue_callback, decode_stop_callback, decode_ui_callback, queue_later_rows,
    resolve_ui_action, tapped_label, ui_menu_rows,
)
from trainmate.chat.replies import format_prompt_message
from trainmate.chat.routing import parse_message_to_argv
from trainmate.sentinels import prompt_answer


class CallbacksMixin:
    """`ChatBot`'s half that answers a tap on one of the four button namespaces."""

    async def _handle_ui_callback(self, query, chat_id: int, data: str) -> None:
        """A tap on a non-blocking TM-BUTTONS row (§4.4): a stale token drops the dead
        buttons; a `menu` button swaps the row for its sub-choices; `send` feeds the
        canned utterance through the normal command pipeline; `ack` just replies."""
        decoded = decode_ui_callback(data)
        current = self.ui_actions.get(chat_id)
        if decoded is None or current is None or decoded[0] != current[0]:
            try:  # replaced by a newer row: drop the dead buttons
                await query.edit_message_reply_markup(reply_markup=None)
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
            keyboard = telegram_api.inline_keyboard(ui_menu_rows(menu, token, path))
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
        self._log(chat_id, "  ", f"ui tap: {action.get('label')}")
        try:  # a decided row is spent: drop the buttons
            await query.edit_message_reply_markup(reply_markup=None)
        except Exception as exc:
            journal.debug("bot.event", f"spent buttons not dropped: {exc}")
        self.ui_actions.pop(chat_id, None)
        if not utterance:
            ack = action.get("ack")
            if ack:
                await self.bot.send_message(chat_id=chat_id, text=str(ack))
            return
        try:
            argv = parse_message_to_argv(str(utterance))
        except ValueError:
            argv = None
        if not argv:
            return
        self._log(chat_id, "  ", f"run: {shlex.join(argv)}")
        await self.bot.send_chat_action(chat_id=chat_id, action="typing")
        await self._start_command(chat_id, argv)

    async def _handle_queue_callback(self, query, chat_id: int, data: str) -> None:
        """A tap on a queued item's button (DESIGN_athlete_queue.md §6.2). "Not now" swaps
        in the three later choices; any other tap leaves the choice under the item's text
        and runs `bot queue`, which checks the item and sends the next one. The chat's live
        TM-BUTTONS row is not touched."""
        decoded = decode_queue_callback(data)
        if decoded is None:
            return
        item_id, action, since = decoded
        if action == QUEUE_NOT_NOW:
            keyboard = telegram_api.inline_keyboard(queue_later_rows(item_id, since))
            try:
                await query.edit_message_reply_markup(reply_markup=keyboard)
            except Exception as exc:
                journal.debug("bot.event", f"later choices not swapped in: {exc}")
            return
        if self.sessions.get(chat_id) is not None:
            await self.bot.send_message(chat_id=chat_id, text=BUSY_TAP)
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
        self._log(chat_id, "  ", f"run: {shlex.join(argv)}")
        await self._start_command(chat_id, argv, quiet=True)

    async def _handle_stop_callback(self, query, chat_id: int, data: str) -> None:
        """A tap on the §3 Stop button: ends the command it was raised for, the same
        kill /cancel does. A tap left over from a command that already finished says so
        rather than reaching whatever started since (DESIGN_bot_stop_button.md §7)."""
        nonce = decode_stop_callback(data)
        session = self.sessions.get(chat_id)
        if nonce is None or session is None or session.nonce != nonce:
            try:  # the command is over: drop the dead button
                await query.edit_message_reply_markup(reply_markup=None)
            except Exception as exc:
                journal.debug("bot.event", f"stale stop button not dropped: {exc}")
            await self.bot.send_message(chat_id=chat_id, text=STOP_ALREADY_DONE)
            return
        self._log(chat_id, "  ", "stop tap")
        await self._retire_stop(session)
        await self._cancel(chat_id)  # its reply line is /cancel's wording; a tap gets §6's
        await self.bot.send_message(
            chat_id=chat_id, text=STOP_DONE, reply_markup=self._keyboard()
        )

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
        # first. A prompt answer or a Stop tap belongs to a command already running.
        if data.startswith(("q:", "ui:")):
            await self._tell_changes_first(chat.id)
        if data.startswith("q:"):
            await self._handle_queue_callback(query, chat.id, data)
            return
        if data.startswith("ui:"):
            await self._handle_ui_callback(query, chat.id, data)
            return
        if data.startswith("stop:"):
            await self._handle_stop_callback(query, chat.id, data)
            return
        decoded = decode_callback(query.data or "")
        if decoded is None:
            return
        nonce, pid, value = decoded
        session = self.sessions.get(chat.id)
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
        self._log(chat.id, "  ", f"answer: {chosen}")
        try:  # echo the choice in place of the buttons
            await query.edit_message_text(
                text=f"{format_prompt_message(awaiting)}\n\n→ {chosen}"
            )
        except Exception as exc:
            journal.debug("bot.event", f"answer not echoed into the prompt: {exc}")
