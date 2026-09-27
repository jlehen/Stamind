"""The "Goals & plan" page's snapshot: the mesocycles and the goals in companion words,
packed into the button's address like the calendar's (DESIGN_calendar_miniapp.md §3.7).

`plan_url` is what the bot calls, with the same list of days the calendar is built from.
"""
import json
from datetime import datetime
from typing import Any, Dict, Optional

from stamind.calendar_days import Calendar
from stamind.cli.render.calendar_page import VERSION, pack
from stamind.cli.render.plan_lines import simple_goal_line
from stamind.db.objectives import GOAL_COMPLETED, goal_state

# The page the Pages deploy publishes beside the calendar (§3.7).
PAGE_URL = "https://jlehen.github.io/Stamind/miniapp/plan.html"

# How many packed bytes the address may carry: the whole keyboard shares Telegram's 9.9 KB
# with the calendar's 5 KB and the gym button (§8).
BUDGET_BYTES = 2 * 1024

# The key of the message the page's "💬 Why, in chat" sends back, with the plan's id (§3.7).
WHY_REQUEST = "plan_why"


def snapshot(cal: Calendar, at: datetime) -> Dict[str, Any]:
    """The mesocycles with their plan's id and summary, and the goals with their
    description; a completed goal is marked `k` (§3.7)."""
    meso = []
    for m in cal.mesocycles:
        row = {"n": m["name"], "s": str(m["start_date"]), "e": str(m["end_date"]),
               "p": m["macrocycle_id"]}
        if (m.get("summary") or "").strip():
            row["m"] = m["summary"].strip()
        meso.append(row)
    goals = []
    for g in cal.goals:
        row = {"t": simple_goal_line(g, cal.today), "d": str(g["target_date"])}
        if (g.get("description") or "").strip():
            row["x"] = g["description"].strip()
        if goal_state(g, cal.today) == GOAL_COMPLETED:
            row["k"] = 1
        goals.append(row)
    return {"v": VERSION, "at": at.strftime("%Y-%m-%dT%H:%M"), "today": cal.today,
            "meso": meso, "goals": goals}


def plan_url(cal: Calendar, at: datetime) -> str:
    """The page's address with the snapshot after `#c=`. Past the budget the summaries and
    descriptions go, and the page offers the chat for them (§3.7)."""
    payload = snapshot(cal, at)
    packed = pack(payload)
    if len(packed) > BUDGET_BYTES:
        for row in payload["meso"] + payload["goals"]:
            row.pop("m", None)
            row.pop("x", None)
        packed = pack(payload)
    return f"{PAGE_URL}#c={packed}"


def why_plan(data: str) -> Optional[int]:
    """The plan whose reasoning the page's "💬 Why, in chat" asks for, or None when `data`
    is some other page's message (§3.7)."""
    try:
        message = json.loads(data)
    except ValueError:
        return None
    if not isinstance(message, dict) or set(message) != {WHY_REQUEST}:
        return None
    plan = message[WHY_REQUEST]
    if isinstance(plan, bool) or not isinstance(plan, int):
        return None
    return plan
