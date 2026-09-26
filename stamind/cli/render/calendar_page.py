"""The calendar page's snapshot: the list of days in companion words, packed into the
button's address (DESIGN_calendar_miniapp.md §3, §5).

`calendar_url` is what the bot calls. Every line of a day's sheet comes from a companion
line builder the chat already uses; nothing here writes new wording (§5). The marks the
grid draws — icon, label, glyph — are facts, and the page draws them itself.
"""
import base64
import json
import zlib
from datetime import datetime, timedelta
from typing import Any, Dict, List, Optional, Tuple

from stamind.analytics.adherence import MISSED, REST_VIOLATION
from stamind.calendar_days import Calendar, Day, next_goal
from stamind.clock import day_str, parse_date, shift
from stamind.sports import canonical_sport
from stamind.cli.render.plan_lines import simple_goal_line, simple_metric_words
from stamind.cli.render.session_lines import (
    SIMPLE_DONE_STATUSES, simple_compare_lines, simple_day_lines, sport_emoji,
)

# The page the Pages deploy publishes beside the gym logger (§6).
PAGE_URL = "https://jlehen.github.io/Stamind/miniapp/calendar.html"

# The payload version the page checks (§5).
VERSION = 1

# The window: four weeks back and six weeks ahead of today (§5).
DAYS_BACK = 28
DAYS_AHEAD = 42

# How many packed bytes the address may carry. Telegram refuses a whole reply keyboard past
# about 9.9 KB (measured 2026-09-26), and the gym button and the labels share it (§8).
BUDGET_BYTES = 6 * 1024

# A description is sent unwrapped: the page lets the browser wrap it (§5).
UNWRAPPED = 1_000_000

# The sheet's three headings (§1).
PLANNED, DONE, NOTES = "Planned", "Done", "Signals and constraints"

# The glyph a session gets, from the grade "✅ Done lately" would give it (§3.2).
OK, MISS, AHEAD = "ok", "miss", "ahead"


def window(today: str) -> Tuple[str, str]:
    """The snapshot's first and last day (§5)."""
    return shift(today, -DAYS_BACK), shift(today, DAYS_AHEAD)


def glyph(result: Dict[str, Any], day: str, today: str) -> str:
    """Green for ✅, red for ❌, none for a day still ahead (§3.2).

    A kept rest day is only kept once the day is over; a rest day trained through is red at
    once, like the ❌ line "✅ Done lately" writes for it."""
    status = result["status"]
    if status in SIMPLE_DONE_STATUSES:
        return OK
    if status in (MISSED, REST_VIOLATION):
        return MISS
    if status == "rest_ok" and day < today:
        return OK
    return AHEAD


def length_label(minutes: Optional[int]) -> Optional[str]:
    """A session's planned length as the cell shows it: "90′" under 100 minutes, "1h40"
    or "2h" from there (§3.1)."""
    if not minutes:
        return None
    if minutes < 100:
        return f"{minutes}′"
    hours, rest = divmod(int(minutes), 60)
    return f"{hours}h{rest:02d}" if rest else f"{hours}h"


def session_label(workouts: List[Dict[str, Any]]) -> Optional[str]:
    """The label under the day's icon: the short name, else the planned length, else none.
    A rest day and a day with two sessions have none (§3.1)."""
    if len(workouts) != 1:
        return None
    w = workouts[0]
    if canonical_sport(w.get("sport_type")) == "rest":
        return None
    return w.get("short_name") or length_label(w.get("duration_minutes"))


def icon(sport_type: Optional[str]) -> str:
    return sport_emoji(canonical_sport(sport_type))


def _marks(day: Day, today: str) -> Dict[str, Any]:
    """The cell: sessions, faded icons, and whether a constraint or a signal covers it."""
    planned = [r["planned"] for r in day.results]
    label = session_label(planned)
    sessions = []
    for r in day.results:
        mark = {"i": icon(r["planned"].get("sport_type")), "g": glyph(r, day.date, today)}
        if label:
            mark["l"] = label
        sessions.append(mark)
    return {
        "x": sessions,
        "u": [icon(act.get("activity_type")) for act in day.worth_showing()],
        "c": int(bool(day.constraints)),
        "s": int(bool(day.signals)),
    }


def _done_lines(day: Day, today: str) -> List[str]:
    """That day's lines from "✅ Done lately", without its heading, its tally and the day
    word each line opens with (§5). A session still ahead has none."""
    behind = [r for r in day.results if glyph(r, day.date, today) != AHEAD]
    extra = day.worth_showing()
    if not behind and not extra:
        return []
    lines = simple_compare_lines([(day.date, behind, extra)], day.date, day.date, today)
    lead = datetime.strptime(day.date, "%Y-%m-%d").strftime("%a %d") + " · "
    return [line[len(lead):] if line.startswith(lead) else line
            for line in lines[1:] if not line.startswith("\n")]


def _note_lines(day: Day) -> List[str]:
    """Each signal as its words, value and text; each constraint as title and description."""
    lines = []
    for s in day.signals:
        line = simple_metric_words(s["metric"])
        if s.get("value") is not None:
            line += f": {s['value']:g}"
        if s.get("text"):
            line += f" — {s['text']}"
        lines.append(line)
    for c in day.constraints:
        line = c["title"]
        if c.get("description"):
            line += f" — {c['description']}"
        lines.append(line)
    return lines


def _in_schedule(cal: Calendar, day: str) -> bool:
    """Whether the written schedule covers `day`: inside a mesocycle, and not past the
    schedule's last day. An empty day there is a rest day, as the chat says (§5)."""
    if cal.schedule_end is None or day > cal.schedule_end:
        return False
    return any(str(m["start_date"]) <= day <= str(m["end_date"]) for m in cal.mesocycles)


def sheet(cal: Calendar, day: Day) -> List[Any]:
    """The day's sheet as [heading, lines] pairs; empty when there is nothing to say."""
    parts: List[Any] = []
    planned = [r["planned"] for r in day.results]
    if planned or _in_schedule(cal, day.date):
        parts.append([PLANNED, simple_day_lines(planned, day.date, width=UNWRAPPED)])
    done = _done_lines(day, cal.today)
    if done:
        parts.append([DONE, done])
    notes = _note_lines(day)
    if notes:
        parts.append([NOTES, notes])
    return parts


def snapshot(cal: Calendar, at: datetime) -> Tuple[Dict[str, Any], Dict[str, list]]:
    """The payload without its sheets, and the sheets by date (§5)."""
    goal = next_goal(cal.goals, cal.today)
    payload: Dict[str, Any] = {
        "v": VERSION,
        "at": at.strftime("%Y-%m-%dT%H:%M"),
        "today": cal.today,
        "from": cal.start,
        "to": cal.end,
        "goal": simple_goal_line(goal, cal.today) if goal else None,
        "goals": [{"t": simple_goal_line(g, cal.today), "d": str(g["target_date"])}
                  for g in cal.goals],
        "meso": [{"n": m["name"], "s": str(m["start_date"]), "e": str(m["end_date"])}
                 for m in cal.mesocycles],
        "days": {},
    }
    if cal.schedule_end and cal.start <= cal.schedule_end <= cal.end:
        payload["end"] = cal.schedule_end
    sheets: Dict[str, list] = {}
    for day in cal.days:
        marks = _marks(day, cal.today)
        if marks["x"] or marks["u"] or marks["c"] or marks["s"]:
            payload["days"][day.date] = marks
        parts = sheet(cal, day)
        if parts:
            sheets[day.date] = parts
    return payload, sheets


def pack(payload: Dict[str, Any]) -> str:
    """The payload as the address carries it: zlib, then base64url without padding (§5)."""
    blob = json.dumps(payload, separators=(",", ":"), ensure_ascii=False).encode("utf-8")
    packed = base64.urlsafe_b64encode(zlib.compress(blob, 9)).decode("ascii")
    return packed.rstrip("=")


def unpack(packed: str) -> Dict[str, Any]:
    """`pack`, undone."""
    padded = packed + "=" * (-len(packed) % 4)
    return json.loads(zlib.decompress(base64.urlsafe_b64decode(padded)).decode("utf-8"))


def outward(today: str, start: str, end: str) -> List[str]:
    """The window's days from today outward: today, tomorrow, yesterday, the day after,
    two days ago… (§5)."""
    order = []
    first, last = parse_date(start), parse_date(end)
    centre = parse_date(today)
    reach = max((centre - first).days, (last - centre).days)
    for step in range(reach + 1):
        for sign in ((1,) if step == 0 else (1, -1)):
            day = centre + timedelta(days=sign * step)
            if first <= day <= last:
                order.append(day_str(day))
    return order


def fit(payload: Dict[str, Any], sheets: Dict[str, list], budget: int = BUDGET_BYTES) -> str:
    """The packed payload with as many sheets as fit in `budget`, nearest today first (§5).

    `fit` names the days whose sheets all went in, so the page can tell a day that has
    nothing to say from one whose details did not fit. It is null when not even today's
    sheet fits."""
    walked: List[str] = []
    packed = pack({**payload, "fit": None})
    for day in outward(payload["today"], payload["from"], payload["to"]):
        if day in sheets:
            payload["days"].setdefault(day, {"x": [], "u": [], "c": 0, "s": 0})
            payload["days"][day]["sheet"] = sheets[day]
        span = sorted(walked + [day])
        trial = pack({**payload, "fit": [span[0], span[-1]]})
        if len(trial) > budget:
            _drop_sheet(payload, day)
            break
        walked.append(day)
        packed = trial
    return packed


def _drop_sheet(payload: Dict[str, Any], day: str) -> None:
    marks = payload["days"].get(day)
    if marks is None:
        return
    marks.pop("sheet", None)
    if not (marks["x"] or marks["u"] or marks["c"] or marks["s"]):
        del payload["days"][day]


def calendar_url(cal: Calendar, at: datetime) -> str:
    """The page's address with the snapshot after `#c=`, a part of the address a browser
    never sends to the host serving the page (§5)."""
    payload, sheets = snapshot(cal, at)
    return f"{PAGE_URL}#c={fit(payload, sheets)}"

