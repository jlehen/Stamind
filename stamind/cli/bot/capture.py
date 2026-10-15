"""`bot capture <intent>`: the write path behind the free-text router (§12.2).

The intents this command answers, and the dispatch between them. `note` is the inbox for
a constraint or a signal the athlete states (§12.3). `add_goal` lives in `goal.py` (§12.5),
`change_setting` in `setting.py` (§12.7), the two edit intents in `edit.py` (§12.4), and
`test_result` in `test_result.py` (DESIGN_benchmark_from_chat.md), each with the queue kind
of the question it asks.

Every path previews what was read from real rows and asks before anything is stored, and
the command it then runs is argv the app assembled — never argv the model wrote (§12.9). A
terminal asks on the spot. In the chat each path saves its question, and this command sends
the first one at its end (DESIGN_chat_questions.md §2).
"""
import argparse
from datetime import datetime, timedelta

from stamind import runtime, signals
from stamind.cli.bot import hand_off
from stamind.cli.bot.edit import edit_capture
from stamind.cli.bot.extraction import (
    CAPTURE_ROLE, NEVER_FILL_RULE, capture_call, dated_context, no_find,
)
from stamind.cli.bot.route import use_fast_model
from stamind.cli.bot.test_result import capture_test_result
from stamind.cli.candidates import (
    confirm_new_constraints, confirm_new_signals, open_ended, queue_candidates,
    tell_open_ended,
)
from stamind.cli.queue import send_own_questions
from stamind.cli.render.plan_lines import simple_preference_words
from stamind.config import config
from stamind.prompt import athlete_watching
from stamind.clock import today_str as _today_str
import stamind.cli.bot.goal as _goal
import stamind.cli.bot.setting as _setting

# `bot route` stays exactly as dumb as it is — one intent, no slots. A write intent then
# runs one of these: a second, domain-focused call that sees only the fields its intent
# can fill, previews what it read from REAL rows, and asks. Two small calls instead of one
# do-everything prompt, so the classifier's job does not get harder every time a domain is
# added and read intents keep paying for exactly one call.

CAPTURE_INTENTS = (
    "note", "add_goal", "edit_goal", "edit_constraint", "change_setting", "test_result",
)


# --- capture: note (§12.3) ---

def _note_capture_prompt(today: str, earliest: str) -> str:
    """The `bot capture note` system prompt: the same two candidate vocabularies the
    `workout adapt -m` inbox uses, with the coaching half removed (§12.10)."""
    from stamind.coach.engine.notes import (
        NEW_CONSTRAINTS_SCHEMA, NEW_SIGNALS_SCHEMA, constraint_extraction_task,
        signal_extraction_task,
    )
    vocabulary = signals.format_vocabulary(
        signals.signal_metrics(), runtime.db.list_signal_metrics()
    )
    return (
        CAPTURE_ROLE
        + "## TASK\n\n"
        + dated_context(today) + "\n\n"
        + "Write down the durable records this message states, and nothing else. A message\n"
        "that states no durable record leaves BOTH lists empty — that is a correct answer\n"
        "and the app handles it. Do not stretch a passing remark into a constraint.\n"
        + NEVER_FILL_RULE
        + constraint_extraction_task("This is one half of the job.")
        + signal_extraction_task(vocabulary, earliest)
        + "\n## RESPONSE FORMAT\n\n"
        "You MUST respond with a JSON object containing:\n{\n"
        + NEW_CONSTRAINTS_SCHEMA + ",\n" + NEW_SIGNALS_SCHEMA + "\n}\n"
    )


def run_bot_capture_note(text: str) -> None:
    """The note inbox (§12.3): one extraction, then the shared questions.

    Recording becomes instant and cheap and the coach becomes a question — she is heard
    immediately, and invoking the coach is her call, not a toll. The trust boundary does
    not move: the candidates are the same shapes `workout adapt -m` yields and they are
    persisted through the same confirmed-candidate service paths.

    Started from the chat, the questions are queued and the first one is the reply. A
    "Yes" brings the question whether to adjust the week, and a preference alone the
    question whether to pass the message to the coach (DESIGN_waiting_proposal.md §6.3,
    DESIGN_chat_questions.md §4)."""
    today = _today_str()
    earliest = (datetime.strptime(today, "%Y-%m-%d")
                - timedelta(days=max(config.metrics_lookback_days, 1) - 1)
                ).strftime("%Y-%m-%d")
    data = capture_call(
        _note_capture_prompt(today, earliest), text, "bot_capture_note"
    ) or {}
    constraints = [c for c in (data.get("new_constraints") or []) if isinstance(c, dict)]
    signal_rows = [s for s in (data.get("new_signals") or []) if isinstance(s, dict)]
    if not constraints and not signal_rows:
        no_find(text)
        return

    if athlete_watching():
        questions = queue_candidates(constraints, signal_rows, today, text, offer=True)
        if not questions and any(open_ended(c) for c in constraints):
            # A preference alone: the sentence where it belongs opens the question whether
            # to pass the message to the coach, so it is whole when it comes back the next
            # morning (DESIGN_chat_questions.md §2, §4).
            hand_off.queue_hand_off(
                f"{simple_preference_words(text)}\n\n{hand_off.PASS_IT_ASK}", text
            )
            return
        tell_open_ended(constraints, text)
        return
    # A terminal asks on the spot and offers nothing after: the operator runs `workout
    # adapt` when they want it (DESIGN_chat_questions.md §2).
    confirm_new_constraints(constraints, today, text)
    confirm_new_signals(signal_rows, today)


def run_bot_capture(args: argparse.Namespace) -> None:
    """Dispatches one capture intent (§12.2), then sends the first question it saved: a
    reply to what the athlete just wrote (DESIGN_athlete_queue.md §13.2 rule 6)."""
    use_fast_model(args)
    text = args.text or ""
    if args.intent == "note":
        run_bot_capture_note(text)
    elif args.intent == "add_goal":
        _goal.run_bot_capture_add_goal(text)
    elif args.intent == "edit_goal":
        edit_capture("goal", text)
    elif args.intent == "edit_constraint":
        edit_capture("constraint", text)
    elif args.intent == "test_result":
        capture_test_result(text)
    else:
        _setting.run_bot_capture_change_setting(text)
    send_own_questions()
