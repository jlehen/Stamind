"""The Progress page's file and its address (DESIGN_progress_page.md §3, §4, §5): the days
and weeks `sm progress` draws, each ended week's grade, the records, the chart's bands and
goals, and each sport's time in zone by week and by mesocycle.

The words are the terminal's, built by the functions it prints them with and never wrapped
(choice 9, §4.1); the page formats only numbers. `timeline_rows` is imported inside
`progress_file`, as `cli/progress.py` does, so no command loads the Garmin package at start.
"""
from datetime import datetime
from typing import Any, Dict, List

from stamind.analytics.intensity import (
    PLANNING_COVERAGE_WEEKS, window_sport_stats, zone_rows, zone_weeks,
)
from stamind.analytics.mesocycle_report import counted_days, measured_window
from stamind.analytics.progression import week_plan_denom, week_plan_seconds
from stamind.analytics.timeline import select_weeks
from stamind.analytics.written_week import (
    SESSIONS, SportGrade, changed_line, graded_weeks, percent, sport_line,
)
from stamind.config import config
from stamind.cycle_records import ENDED_LABELS, record_lines, record_name
from stamind.sports import canonical_sport
from stamind.cli.progress_weeks import records_newest_first
from stamind.cli.progress_zones import reported_mesocycles
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


def _zone_sports(weeks: List[Dict[str, Any]]) -> List[str]:
    """Every sport of the profile with zone data in the history, in the profile's order; the
    terminal's tenth-of-the-window rule is not applied (§3.4, choice 16)."""
    stats = window_sport_stats(weeks)
    sports: List[str] = []
    for name in config.user_profile.get("sport_preferences") or []:
        sport = canonical_sport(name)
        agg = stats.get(sport)
        if sport in sports or not agg or not any(agg["zone_seconds"].values()):
            continue
        sports.append(sport)
    return sports


def _zones(dbh, weeks: List[Dict[str, Any]], today: str) -> List[Dict[str, Any]]:
    """Each sport's weeks as `/api/zones` gives them, over every week, its zones chosen over
    the 8 weeks either side of today (§3.4); then each reported mesocycle's average week in
    each zone over its completed weeks, as `sm progress intensity --mesocycles` reports it,
    from one read of the activities (§10)."""
    past, future, _hidden = select_weeks(weeks, PLANNING_COVERAGE_WEEKS, today)
    zones = zone_weeks(weeks, _zone_sports(weeks), today, choose_from=past + future)
    if not zones:
        return []
    activities = dbh.get_completed_activities()
    for zone in zones:
        zone["mesocycles"] = []
    for meso in reported_mesocycles(dbh):
        if counted_days(meso["start_date"], meso["end_date"], today) <= 0:
            continue
        start, end, count = measured_window(meso["start_date"], meso["end_date"], today)
        rows = {(row.sport, row.currency): row
                for row in zone_rows([a for a in activities if start <= a["date"] <= end])}
        for zone in zones:
            row = rows.get((zone["sport"], zone["currency"]))
            seconds = None
            if row is not None:
                # A mesocycle under a week old reads raw, as the terminal's does.
                seconds = [s / (count or 1) for s in row.seconds]
            zone["mesocycles"].append({
                "name": meso["name"], "start": meso["start_date"], "end": meso["end_date"],
                "focus": meso.get("focus") or "", "weeks": count, "seconds": seconds,
            })
    return zones


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
        "zones": _zones(dbh, weeks, today),
    }
