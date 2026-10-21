"""`bot capture change_setting`, "Can you message me at 7 instead?"
(DESIGN_bot_simple_frontend.md §12.7), and the `change_setting` kind of the athlete queue:
the question that confirms the change before it is stored (DESIGN_chat_questions.md §4).

A terminal asks on the spot. In the chat the question is saved, and `bot capture` sends it.
"""
import argparse
from typing import Any, Dict, Optional

from stamind import clock, runtime, settings
from stamind.cli.bot.extraction import (
    CAPTURE_ROLE, NEVER_FILL_RULE, capture_call, dated_context, no_find,
)
from stamind.clock import today_str as _today_str
from stamind.config import config
from stamind.prompt import athlete_watching
from stamind.queue_kind import QUESTION, YES, YES_NO, Kind, queue_replacing
from stamind.text import wrap_text
import stamind.cli.settings as _settings

KIND = "change_setting"
CHANGE_ASK = "Shall I change this setting?"
LEFT_AS_IT_WAS_LINE = "Okay — I've left it as it was."

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
    settings.EVENING_TIME: (
        "the local time in the evening after which the app does not message the athlete "
        "first, until the morning, as HH:MM"
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
    settings.MORNING_TIME, settings.MORNING_DEADLINE, settings.EVENING_TIME, settings.PUSH,
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


def _push_lands_today() -> bool:
    """Whether a morning-push change takes effect today. The scheduler re-reads every
    tick (§4.3), so a change made before today's push lands today — and the preview only
    claims tomorrow when today's is already past (§12.7)."""
    today = _today_str()
    if runtime.db.get_setting(settings.MORNING_MARKER) == today:
        return False
    deadline = settings.morning_deadline()
    return clock.now().strftime("%H:%M") <= deadline


def _setting_effect(key: str, value: str) -> str:
    """The change read back as its effect, not as a key: the confirm echoes what she will
    notice tomorrow morning, which is the only form of it she can check (§12.7)."""
    if key == settings.MORNING_TIME:
        when = "" if _push_lands_today() else " from tomorrow"
        return f"I'll open your day at {value}{when}."
    if key == settings.MORNING_DEADLINE:
        return f"If I miss the morning, I'll still catch you up until {value}."
    if key == settings.EVENING_TIME:
        return (f"From {value} I'll stay quiet until the morning, unless you write to me "
                "first.")
    if key == settings.LEARNING_QUESTIONS:
        if value == "on":
            return "I'll ask you again before I lean less on something I've learned about you."
        return ("I'll stop asking about what I've learned about you, and go by what I see "
                "instead.")
    if value == "on":
        return "I'll start opening your day again in the morning."
    return "I'll stop opening the day — you can always ask me here whenever you like."


def _question(name: str, value: str) -> str:
    """The change read back as its effect, worded when it is asked, so "from tomorrow" is
    true on the morning it comes back (DESIGN_chat_questions.md §4)."""
    return f"{_setting_effect(name, value)} {CHANGE_ASK}"


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

    if athlete_watching():
        queue_replacing(KIND, {
            "name": setting.name, "value": value, "answers": list(YES_NO),
        }, about=setting.name)
        return
    if not runtime.prompt.confirm(_question(setting.name, value)):
        print(LEFT_AS_IT_WAS_LINE)
        return
    _settings.run_settings_set(argparse.Namespace(name=setting.name, value=value))


def _wording(item: Dict[str, Any]) -> str:
    return _question(item["payload"]["name"], item["payload"]["value"])


def _already_set(item: Dict[str, Any]) -> bool:
    """The setting already has the value asked for."""
    payload = item["payload"]
    return settings.resolve(payload["name"]).value == payload["value"]


def _apply(item: Dict[str, Any], index: int, text: Optional[str]) -> Optional[str]:
    """"Yes" stores the value; "No" leaves the setting as it was."""
    if index != YES:
        return LEFT_AS_IT_WAS_LINE
    payload = item["payload"]
    _settings.run_settings_set(argparse.Namespace(name=payload["name"], value=payload["value"]))
    return None


# A confirmation drawn bare (DESIGN_chat_questions.md §2).
CHANGE_SETTING_KIND = Kind(
    name=KIND, shape=QUESTION, wording=_wording, companion_wording=_wording,
    is_stale=_already_set, apply=_apply, bare=True, confirmation=True,
)
