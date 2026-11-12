"""The Progress page's file and its address (DESIGN_progress_page.md §3, §4, §5): the days
and weeks `sm progress` draws, each ended week's grade, the records, and the chart's bands
and goals.

The words are the terminal's, built by the functions it prints them with and never wrapped
(choice 9, §4.1); the page formats only numbers. `timeline_rows` is imported inside
`progress_file`, as `cli/progress.py` does, so no command loads the Garmin package at start.
"""
from datetime import datetime
from typing import Any, Dict, List

from stamind.analytics.progression import week_plan_denom, week_plan_seconds
from stamind.analytics.written_week import (
    SESSIONS, SportGrade, changed_line, graded_weeks, percent, sport_line,
)
from stamind.cycle_records import ENDED_LABELS, record_lines, record_name
from stamind.cli.progress_weeks import records_newest_first
from stamind.cli.render.calendar_page import VERSION
from stamind.cli.render.session_lines import sport_emoji

# The page the Pages deploy publishes beside the calendar (§3).
PAGE_URL = "https://jlehen.github.io/Stamind/miniapp/progress.html"


def progress_url(storage: str) -> str:
    """The page's address: no snapshot, only the way to the file, which `storage` carries
    (§5). The bot draws the button only where the pages are published."""
    return f"{PAGE_URL}#{storage.lstrip('&')}"


def _sport(grade: SportGrade) -> Dict[str, Any]:
    """One sport of an ended week: what the Weeks tab's line and its opened lines show."""
    return {
        "sport": grade.sport, "icon": sport_emoji(grade.sport),
        "sessions": grade.measure == SESSIONS, "written": grade.written, "done": grade.done,
        "percent": percent(grade), "short": grade.short, "line": sport_line(grade),
        "changed": [changed_line(changed) for changed in grade.changed],
    }


def _week(week: Dict[str, Any], grade: List[SportGrade], today: str) -> Dict[str, Any]:
    """One week of the chart and of the Weeks tab: the planned figure is the one the
    terminal compares with (`week_plan_denom`), the grade only on a week that has ended."""
    row = {
        "monday": week["week_commencing"], "planned": week_plan_denom(week),
        "done": week["actual_load"], "hours_planned": week_plan_seconds(week),
        "hours_done": week["actual_seconds"], "meso": week["meso_label"],
        "under_way": week["in_progress"], "ahead": week["week_commencing"] > today,
    }
    if grade:
        row["grade"] = [_sport(sport) for sport in grade]
    return row


def _record(record: Dict[str, Any]) -> Dict[str, Any]:
    """One card of the Mesocycles tab; a record not written yet has no lines (§3.3)."""
    row = {"name": record_name(record), "start": record["start_date"],
           "end": record["end_date"], "ended": ENDED_LABELS[record["ended_by"]]}
    if record["body"] is None:
        return row
    first, *lines = record_lines(record)
    row.update(first=first, said=record["athlete_line"], lines=lines)
    if record["athlete_words"]:
        row["answer"] = row["lines"].pop()
    return row


def progress_file(dbh, today: str, at: datetime) -> Dict[str, Any]:
    """The file's content (§4.1): exact numbers, the terminal's words."""
    from stamind import timeline_rows
    payload = timeline_rows.build_timeline_payload(dbh)
    weeks = payload["weeks"]
    grades: Dict[str, List[SportGrade]] = {}
    if weeks:
        grades = dict(graded_weeks(dbh, weeks[0]["week_commencing"], today, today))
    return {
        "v": VERSION, "at": at.strftime("%Y-%m-%dT%H:%M"), "today": today,
        "days": payload["days"],
        "weeks": [_week(w, grades.get(w["week_commencing"], []), today) for w in weeks],
        "records": [_record(record) for record in records_newest_first(dbh)],
        "goals": [{"title": o["title"], "date": str(o["target_date"])}
                  for o in payload["objectives"]],
        "mesocycles": payload["meso_bands"],
    }
