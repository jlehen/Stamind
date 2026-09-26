"""`sm calendar`'s month grid, in expert marks (DESIGN_calendar_miniapp.md §7).

The terminal's words for the list of days the calendar page is also built on
(`stamind/calendar_days.py`); the cell's icon and label follow the page's rules (§3.1).
"""
import calendar as month_calendar
import unicodedata
from typing import List

from stamind import calendar_days
from stamind.analytics.adherence import MISSED, PARTIAL, REST_VIOLATION
from stamind.clock import day_str, fmt_date, parse_date
from stamind.text import bold, cyan, gray
from stamind.cli.render.calendar_page import icon, session_label

# Each column's width, in terminal columns (§7).
CELL = 11
WEEKDAYS = ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"]

# The grade in expert marks; a grade with no mark prints nothing (§7).
MARKS = {"done": "✓", PARTIAL: "½", MISSED: "✗", REST_VIOLATION: "✗"}
CONSTRAINT, SIGNAL = "◆", "•"


def columns(text: str) -> int:
    """How many terminal columns `text` takes: an emoji or a wide character takes two, an
    emoji variation selector widens the character before it, a joiner takes none.
    A terminal that draws an emoji one column wide shifts the row (§11)."""
    width = 0
    last = 0
    for ch in text:
        if ch == "️":
            width += 2 - last if last == 1 else 0
            last = 2
            continue
        if unicodedata.combining(ch) or ch == "‍":
            continue
        last = 2 if unicodedata.east_asian_width(ch) in ("W", "F") else 1
        width += last
    return width


def fit_cell(text: str, width: int = CELL) -> str:
    """`text` cut to `width` columns, then padded to it."""
    out = ""
    for ch in text:
        if columns(out + ch) > width:
            break
        out += ch
    return out + " " * (width - columns(out))


def cell_lines(day: calendar_days.Day) -> List[str]:
    """A day's two lines: the number with its markers, then its sessions (§7)."""
    number = f" {parse_date(day.date).day:>2} "
    if day.constraints:
        number += CONSTRAINT
    if day.signals:
        number += SIGNAL
    planned = [r["planned"] for r in day.results]
    icons = "".join(icon(w.get("sport_type")) for w in planned)
    marks = "".join(MARKS.get(r["status"], "") for r in day.results)
    extra = [f"+{icon(act.get('activity_type'))}" for act in day.worth_showing()]
    body = " " + " ".join(p for p in [icons, session_label(planned), marks, *extra] if p)
    if columns(body) > CELL:
        # No room for the label beside an activity nobody planned: the label goes first.
        body = " " + " ".join(p for p in [icons, marks, *extra] if p)
    return [fit_cell(number), fit_cell(body)]


def month_lines(cal: calendar_days.Calendar, year: int, month: int) -> List[str]:
    """The month's grid: a header with the nearest goal, the weekday names, then two lines
    per week and a line under a week in which a mesocycle starts (§7)."""
    lines = [bold(cyan(f"=== {month_calendar.month_name[month]} {year} ==="))]
    goal = calendar_days.next_goal(cal.goals, cal.today)
    if goal:
        lines.append(gray(f"Next goal: {goal['title']} ({fmt_date(str(goal['target_date']))})"))
    lines.append("".join(fit_cell(f" {name}") for name in WEEKDAYS).rstrip())
    by_date = {day.date: day for day in cal.days}
    for week in month_calendar.Calendar(firstweekday=0).monthdatescalendar(year, month):
        rows = ["", ""]
        for date in week:
            day = by_date.get(day_str(date)) if date.month == month else None
            cells = cell_lines(day) if day else [" " * CELL, " " * CELL]
            rows = [rows[0] + cells[0], rows[1] + cells[1]]
        lines.extend(row.rstrip() for row in rows)
        for meso in cal.mesocycles:
            start = parse_date(str(meso["start_date"]))
            if start in week and start.month == month:
                lines.append(gray(f"── {meso['name']} starts {start:%a} {start.day} "
                                  f"{start:%b}"))
    return lines
