"""`bot capture <intent>`: the write path behind the free-text router (§12.2).

The intents this command answers, and the dispatch between them. `note` is the inbox for
a rule or a signal the athlete states (§12.3), `add_goal` sets up a new goal (§12.5), and
`change_setting` changes one of the chat knobs on the `ROUTABLE_SETTINGS` allowlist
(§12.7). The two edit intents are the long ones and live in `edit.py`.

Every path here previews what was read from real rows and asks before anything is stored,
and the command it then runs is argv this file assembled — never argv the model wrote
(§12.9).
"""
import argparse
from datetime import datetime, timedelta
from typing import Any, List, Optional

from trainmate import clock, runtime, settings, signals
from trainmate.cli.bot.edit import edit_capture
from trainmate.cli.bot.extraction import (
    CAPTURE_ROLE, NEVER_FILL_RULE, adjust_week_button, capture_call, dated_context,
    no_find, send_to_coach_button, valid_date,
)
from trainmate.cli.bot.route import use_router_model
from trainmate.cli.bot.views import MORNING_MARKER
from trainmate.cli.candidates import (
    confirm_new_constraints, confirm_new_signals, open_ended,
)
from trainmate.cli.goals import run_goal_add
from trainmate.cli.render.plan_lines import simple_goal_line
from trainmate.cli.settings import run_settings_set
from trainmate.config import config
from trainmate.sentinels import emit_buttons
from trainmate.sports import CANONICAL_SPORTS, canonical_sport
from trainmate.text import wrap_text
from trainmate.clock import today_str as _today_str

# `bot route` stays exactly as dumb as it is — one intent, no slots. A write intent then
# runs one of these: a second, domain-focused call that sees only the fields its intent
# can fill, previews what it read from REAL rows, and asks. Two small calls instead of one
# do-everything prompt, so the classifier's job does not get harder every time a domain is
# added and read intents keep paying for exactly one call.

CAPTURE_INTENTS = (
    "note", "add_goal", "edit_goal", "edit_constraint", "change_setting",
)


# --- capture: note (§12.3) ---

def _note_capture_prompt(today: str, earliest: str) -> str:
    """The `bot capture note` system prompt: the same two candidate vocabularies the
    `workout adapt -m` inbox uses, with the coaching half removed (§12.10)."""
    from trainmate.coach.engine.notes import (
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
        "and the app handles it. Do not stretch a passing remark into a rule.\n"
        + NEVER_FILL_RULE
        + constraint_extraction_task("This is one half of the job.")
        + signal_extraction_task(vocabulary, earliest)
        + "\n## RESPONSE FORMAT\n\n"
        "You MUST respond with a JSON object containing:\n{\n"
        + NEW_CONSTRAINTS_SCHEMA + ",\n" + NEW_SIGNALS_SCHEMA + "\n}\n"
    )


def run_bot_capture_note(text: str) -> None:
    """The note inbox (§12.3): one extraction, the shared confirms, then the offer.

    Recording becomes instant and cheap and the coach becomes an offer — she is heard
    immediately, and invoking the coach is her call, not a toll. The trust boundary does
    not move: the candidates are the same shapes `workout adapt -m` yields and they are
    persisted through the same confirmed-candidate service paths."""
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

    captured = confirm_new_constraints(constraints, today, text)
    logged = confirm_new_signals(signal_rows, today)
    if not captured and not logged:
        # A rule for good was handed to the operator and nothing else was stored: today's
        # half of it is still the coach's, one tap away (§12.3, 2026-09-16).
        if any(open_ended(c) for c in constraints):
            emit_buttons([send_to_coach_button(text)])
        # Otherwise she said no to everything the note offered. Nothing was stored and
        # nothing is owed: a second offer would read as pressing her on an answer she gave.
        return
    # Signals get the offer too (amended 2026-09-02): the record points backward and
    # adapts nothing, but the athlete REPORTING one expects forward notice, and a row
    # filed behind a cheerful confirm otherwise reads as heard-and-acted-on while
    # nothing about today changes. The offer makes that gap one visible tap wide.
    emit_buttons([adjust_week_button()])


# --- capture: add_goal (§12.5) ---

_SPORT_LIST = ", ".join(CANONICAL_SPORTS)

ADD_GOAL_PROMPT = (
    CAPTURE_ROLE
    + "## TASK\n\n"
    "{dated}\n\n"
    "The athlete says what they want to train for. Fill the fields below from what the\n"
    "message states.\n"
    + NEVER_FILL_RULE
    + '"sports" must be chosen from this list, spelled EXACTLY as shown, never free-typed:\n'
    "{sports}\n"
    'Infer them from the event where the message makes it plain ("half marathon" is\n'
    'running, "triathlon" is several); return [] when it does not.\n'
    '"date_type" is "event" when something happens ON that day — a race, a hike, a trip —\n'
    'and "horizon" when the date only says how far ahead the athlete wants to train.\n\n'
    "## RESPONSE FORMAT\n\n"
    "You MUST respond with a JSON object containing:\n"
    "{{\n"
    '  "title": "the goal named short, as the athlete would say it (or null)",\n'
    '  "target_date": "YYYY-MM-DD (or null when the message states no date)",\n'
    '  "sports": ["one or more from the list above, or [] when the message does not say"],\n'
    '  "date_type": "event" | "horizon",\n'
    '  "description": "anything else the message says about it, or null"\n'
    "}}\n"
)


# One line per required field the extraction may have to leave empty: the reply asks for
# the one missing thing and stops (§12.2).
GOAL_MISSING_ASKS = {
    "target_date": "When is it? Tell me again with the date and I'll set it up 🎯",
    "title": "What should I call it? Tell me again and I'll set it up 🎯",
    "sports": "Which sport is that? Tell me again and I'll set it up 🎯",
}


def _clean_sports(raw: Any) -> List[str]:
    """The sports the extraction named, mapped into `CANONICAL_SPORTS` and de-duplicated.
    Anything the enum does not know is dropped rather than free-typed into it (§12.5)."""
    if isinstance(raw, str):
        raw = [raw]
    out: List[str] = []
    for token in raw or []:
        sport = canonical_sport(str(token))
        if sport in CANONICAL_SPORTS and sport not in out:
            out.append(sport)
    return out


def run_bot_capture_add_goal(text: str) -> None:
    """"I want to run a half marathon on May 10" (§12.5).

    Previewed in the goal view's own on/"by ~" wording, so a wrong `date_type` guess is
    visible in the preview's first line. What it does NOT do is shape the plan: a goal row
    is cheap and editable, the periodization built on it is neither."""
    today = _today_str()
    data = capture_call(
        ADD_GOAL_PROMPT.format(dated=dated_context(today), sports=_SPORT_LIST),
        text, "bot_capture_add_goal",
    )
    if data is None:
        no_find(text)
        return

    title = str(data.get("title") or "").strip()
    target_date = valid_date(data.get("target_date"))
    sports = _clean_sports(data.get("sports"))
    date_type = "horizon" if str(data.get("date_type")) == "horizon" else "event"
    description = str(data.get("description") or "").strip()

    for field, value in (("title", title), ("target_date", target_date),
                         ("sports", sports)):
        if not value:
            print(wrap_text(GOAL_MISSING_ASKS[field]))
            return

    proposed = {"title": title, "target_date": target_date, "date_type": date_type,
                "sport_type": ",".join(sports)}
    print("Here's what I've got:")
    print(simple_goal_line(proposed, today))
    if description:
        print(wrap_text(description))
    if not runtime.prompt.confirm("Shall I set that up?"):
        print("Okay — nothing set up.")
        return

    run_goal_add(argparse.Namespace(
        title=title, date=target_date, sport=sports, desc=description,
        date_type=date_type,
    ))


# --- capture: change_setting (§12.7) ---

CHANGE_SETTING_PROMPT = (
    CAPTURE_ROLE
    + "## TASK\n\n"
    "{dated}\n\n"
    "The athlete asks to change something about how the app behaves in this chat. Return\n"
    "the setting they mean and the value they asked for.\n\n"
    "These are the ONLY settings you may return, spelled exactly:\n"
    "{allowlist}\n\n"
    "If the message asks for anything else — a different model, a plan, a preference not\n"
    'listed above — put what they named in "key" anyway, in their own words. The app\n'
    "answers those itself; you must not map them onto a setting above.\n"
    + NEVER_FILL_RULE
    + "\n## RESPONSE FORMAT\n\n"
    "You MUST respond with a JSON object containing:\n"
    "{{\n"
    '  "key": "one of the names above, or what the athlete named (or null)",\n'
    '  "value": "the value they asked for (or null)"\n'
    "}}\n"
)

SETTING_DESCRIPTIONS = {
    settings.MORNING_TIME: "the local time the app opens the day, as HH:MM",
    settings.MORNING_DEADLINE: (
        "the local time after which a missed morning message is skipped rather than "
        "caught up, as HH:MM"
    ),
    settings.PUSH: 'whether the app opens the day at all — "on" or "off"',
    settings.LEARNING_QUESTIONS: (
        "whether the app asks before it leans less on something it has learned about "
        'the athlete — "on" or "off"'
    ),
}


# The settings a chat message may change (DESIGN_bot_simple_frontend.md §12.7): the knobs
# that shape the athlete's own experience of the chat, and nothing else. An explicit
# allowlist, so a knob added to the `settings` registry is not routable until someone
# deliberately puts it on this list. Anything operator- or cost-shaped — a model role,
# adapt-first — is off it by construction.
ROUTABLE_SETTINGS = (
    settings.MORNING_TIME, settings.MORNING_DEADLINE, settings.PUSH,
    settings.LEARNING_QUESTIONS,
)


def routable_setting(name: str) -> "settings.Setting | None":
    """The setting a captured key names, or None when the key is off the allowlist.

    Exact names only: the prefix matching `settings.get` allows is a convenience for a
    human at a keyboard, and widening a guardrail by abbreviation is not one."""
    token = (name or "").strip().lower()
    if token not in ROUTABLE_SETTINGS:
        return None
    return settings.get(token)


def _setting_refusal() -> str:
    """The §12.7 boundary, spoken honestly rather than disguised as incomprehension: a
    miss should be visible, and a boundary dressed as "I didn't understand" teaches
    nothing. Names the operator, per the render-persona naming rule."""
    return f"That one's for {config.telegram_operator_name} to change, not me."


def _push_lands_today(new_deadline: Optional[str] = None) -> bool:
    """Whether a morning-push change takes effect today. The scheduler re-reads every
    tick (§4.3), so a change made before today's push lands today — and the preview only
    claims tomorrow when today's is already past (§12.7)."""
    today = _today_str()
    if runtime.db.get_setting(MORNING_MARKER) == today:
        return False
    deadline = new_deadline or settings.morning_deadline()
    return clock.now().strftime("%H:%M") <= deadline


def _setting_effect(key: str, value: str) -> str:
    """The change read back as its effect, not as a key: the confirm echoes what she will
    notice tomorrow morning, which is the only form of it she can check (§12.7)."""
    if key == settings.MORNING_TIME:
        when = "" if _push_lands_today() else " from tomorrow"
        return f"I'll open your day at {value}{when}."
    if key == settings.MORNING_DEADLINE:
        return f"If I miss the morning, I'll still catch you up until {value}."
    if key == settings.LEARNING_QUESTIONS:
        if value == "on":
            return "I'll ask you again before I lean less on something I've learned about you."
        return ("I'll stop asking about what I've learned about you, and go by what I see "
                "instead.")
    if value == "on":
        return "I'll start opening your day again in the morning."
    return "I'll stop opening the day — you can always ask me here whenever you like."


def run_bot_capture_change_setting(text: str) -> None:
    """"Can you message me at 7 instead?" (§12.7).

    The allowlist is context given to the extraction AND enforced after it, so "use a
    smarter model" cannot become a settings write no matter what the extraction says."""
    allowlist = "\n".join(
        f"- {name}: {SETTING_DESCRIPTIONS[name]}" for name in ROUTABLE_SETTINGS
    )
    data = capture_call(
        CHANGE_SETTING_PROMPT.format(
            dated=dated_context(_today_str()), allowlist=allowlist
        ),
        text, "bot_capture_change_setting",
    )
    if data is None:
        no_find(text)
        return

    setting = routable_setting(str(data.get("key") or ""))
    if setting is None:
        print(wrap_text(_setting_refusal()))
        return
    try:
        value = setting.parse(data.get("value"))
    except ValueError:
        print(wrap_text(
            "I didn't catch what to set it to — tell me again, like “message me at 07:00”."
        ))
        return

    if not runtime.prompt.confirm(f"{_setting_effect(setting.name, value)} OK?"):
        print("Okay — I've left it as it was.")
        return
    run_settings_set(argparse.Namespace(name=setting.name, value=value))


def run_bot_capture(args: argparse.Namespace) -> None:
    """Dispatches one capture intent (§12.2). Runs as an ordinary routed command: its
    questions are TM-PROMPT confirms, its offers are TM-BUTTONS rows, its output is
    simple-rendered — nothing new crosses the CLI↔bot channel."""
    use_router_model(args)
    text = args.text or ""
    if args.intent == "note":
        run_bot_capture_note(text)
    elif args.intent == "add_goal":
        run_bot_capture_add_goal(text)
    elif args.intent == "edit_goal":
        edit_capture("goal", text, args.pinned_id)
    elif args.intent == "edit_constraint":
        edit_capture("constraint", text, args.pinned_id)
    else:
        run_bot_capture_change_setting(text)
