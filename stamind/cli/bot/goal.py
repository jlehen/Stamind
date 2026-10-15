"""`bot capture add_goal`, "I want to run a half marathon on May 10"
(DESIGN_bot_simple_frontend.md §12.5), and the `new_goal` kind of the athlete queue: the
question that confirms it before anything is stored (DESIGN_chat_questions.md §4).

A terminal asks on the spot. In the chat the question is saved, and `bot capture` sends it.
"""
import argparse
from typing import Any, Dict, List, Optional

from stamind import clock, runtime
from stamind.cli.bot.extraction import (
    CAPTURE_ROLE, NEVER_FILL_RULE, capture_call, dated_context, no_find, valid_date,
)
from stamind.cli.render.plan_lines import simple_goal_line
from stamind.clock import today_str as _today_str
from stamind.db.queue import queue_stamp
from stamind.prompt import athlete_watching
from stamind.queue_kind import QUESTION, YES, YES_NO, Kind, queue
from stamind.sports import CANONICAL_SPORTS, canonical_sport
from stamind.text import wrap_text
import stamind.cli.goals as _goals

KIND = "new_goal"
SET_UP_ASK = "Shall I set up this goal?"
NOTHING_SET_UP_LINE = "Okay — nothing set up."

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


def _question(goal: Dict[str, Any], today: str) -> str:
    """The goal read back in the goal view's own on/"by ~" wording, so a wrong `date_type`
    guess is visible in the first line (§12.5), then the question."""
    lines = ["Here's what I've got:", simple_goal_line(goal, today)]
    if goal["description"]:
        lines.append(goal["description"])
    return "\n".join(lines + [SET_UP_ASK])


def run_bot_capture_add_goal(text: str) -> None:
    """"I want to run a half marathon on May 10" (§12.5).

    What it does NOT do is shape the plan: a goal row is cheap and editable, the
    periodization built on it is neither."""
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

    goal = {"title": title, "target_date": target_date, "date_type": date_type,
            "sport_type": ",".join(sports), "description": description}
    if athlete_watching():
        queue(KIND, queue_stamp(clock.command_start()), {
            "goal": goal, "answers": list(YES_NO),
        })
        return
    if not runtime.prompt.confirm(wrap_text(_question(goal, today))):
        print(NOTHING_SET_UP_LINE)
        return
    _set_up(goal)


def _set_up(goal: Dict[str, Any]) -> None:
    _goals.run_goal_add(argparse.Namespace(
        title=goal["title"], date=goal["target_date"], sport=goal["sport_type"].split(","),
        desc=goal["description"], date_type=goal["date_type"],
    ))


def _wording(item: Dict[str, Any]) -> str:
    return _question(item["payload"]["goal"], _today_str())


def _apply(item: Dict[str, Any], index: int, text: Optional[str]) -> Optional[str]:
    """"Yes" adds the goal; "No" stores nothing."""
    if index != YES:
        return NOTHING_SET_UP_LINE
    _set_up(item["payload"]["goal"])
    return None


# A confirmation drawn bare, closed by its mornings alone (DESIGN_chat_questions.md §2).
NEW_GOAL_KIND = Kind(
    name=KIND, shape=QUESTION,
    wording=_wording, companion_wording=_wording,
    is_stale=lambda item: False, apply=_apply, bare=True, confirmation=True,
)
