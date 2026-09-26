"""One list of days, the facts the calendar page and `sm calendar` both show
(DESIGN_calendar_miniapp.md §4).

`gather` reads the database for a range of dates and returns one `Day` per date, plus the
mesocycles and goals around them. It holds no text: each view words these facts in its own
voice (§5, §7). It writes nothing and never pulls from Garmin; a caller that wants fresh
grades pulls first, as `sm calendar` does.
"""
from typing import Any, Dict, List, NamedTuple, Optional, Tuple

from stamind.analytics.adherence import MINOR, classify_adherence, unplanned_kind
from stamind.analytics.compare import adherence_window, compare_days
from stamind.analytics.runway import plan_end
from stamind.clock import date_range, parse_date
from stamind.config import config
from stamind.db.objectives import ARCHIVED


class Day(NamedTuple):
    """One date's facts.

    `results` are the day's `analyze_adherence` rows (planned session, matched activity,
    `pending`), each with the `status` `classify_adherence` gives it. `unplanned` pairs
    each activity that matched no session with its `unplanned_kind`, minor ones included,
    so each view decides what it leaves out."""
    date: str
    results: List[Dict[str, Any]]
    unplanned: List[Tuple[Dict[str, Any], str]]
    constraints: List[Dict[str, Any]]
    signals: List[Dict[str, Any]]

    def worth_showing(self) -> List[Dict[str, Any]]:
        """The unplanned activities the companion mentions: every kind but minor (§3.3)."""
        return [act for act, kind in self.unplanned if kind != MINOR]


class Calendar(NamedTuple):
    """The days of `[start, end]`, and what surrounds them.

    `mesocycles` are the plans' mesocycles from `start` to `end` or the last goal,
    whichever is later, in date order, so the plan view can run to the last goal (§5).
    `goals` are every goal not archived, in date order. `schedule_end` is the last day
    the written schedule covers, the date `workout list` marks as its end."""
    start: str
    end: str
    today: str
    days: List[Day]
    mesocycles: List[Dict[str, Any]]
    goals: List[Dict[str, Any]]
    schedule_end: Optional[str]


def _covering(rows: List[Dict[str, Any]], day: str) -> List[Dict[str, Any]]:
    return [c for c in rows if str(c["start_date"]) <= day <= str(c["end_date"])]


def gather(dbh, start: str, end: str, today: str) -> Calendar:
    """The facts for `[start, end]` as of `today`, read from `dbh`."""
    window = adherence_window(dbh, start, end, today)
    threshold = config.minor_activity_load_threshold
    walked = compare_days(parse_date(start), window.history_days, window.results,
                          window.activities, None)
    by_date = {day: (results, unplanned) for day, results, unplanned in walked}
    constraints = dbh.get_constraints(start, end)
    signals = dbh.get_daily_signals(start, end)

    days = []
    for day in date_range(start, end):
        results, unplanned = by_date.get(day, ([], []))
        graded = [
            {**r, "status": classify_adherence(
                r["planned"], r["completed"], threshold, pending=r.get("pending", False)
            )["status"]}
            for r in results
        ]
        kinds = [(act, unplanned_kind(act, day, window.covered_ranges, threshold))
                 for act in unplanned]
        days.append(Day(
            date=day, results=graded, unplanned=kinds,
            constraints=_covering(constraints, day),
            signals=[s for s in signals if s["date"] == day],
        ))

    goals = [g for g in dbh.get_objectives() if g.get("status") != ARCHIVED]
    last_goal = max([str(g["target_date"]) for g in goals], default=end)
    mesocycles, _dropped = dbh.get_governing_mesocycles(start, max(end, last_goal))
    return Calendar(
        start=start, end=end, today=today, days=days,
        mesocycles=sorted(mesocycles, key=lambda m: str(m["start_date"])),
        goals=sorted(goals, key=lambda g: str(g["target_date"])),
        schedule_end=plan_end(dbh.get_workouts()),
    )


def next_goal(goals: List[Dict[str, Any]], today: str) -> Optional[Dict[str, Any]]:
    """The nearest goal still ahead of `today`, or None (§3.5)."""
    ahead = [g for g in goals if str(g["target_date"]) >= today]
    return ahead[0] if ahead else None
