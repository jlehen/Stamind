"""One list of days, the facts the calendar page and `sm calendar` both show
(DESIGN_calendar_miniapp.md §4).

`gather` reads the database for a range of dates and returns one `Day` per date, plus the
mesocycles and goals around them. It holds no text: each view words these facts in its own
voice (§5, §7). It writes nothing and never pulls from Garmin; a caller that wants fresh
grades pulls first, as `sm calendar` does. Each day is also held against what `workout
generate` wrote for it (DESIGN_calendar_as_written.md §2).
"""
from typing import Any, Dict, List, NamedTuple, Optional, Set, Tuple

from stamind.analytics.adherence import MINOR, MISSED, classify_adherence, unplanned_kind
from stamind.analytics.compare import adherence_window, compare_days
from stamind.analytics.runway import plan_end
from stamind.analytics.written_week import (
    UNGRADED, Changed, SportGrade, WrittenSession, calendar_change, departed, graded_weeks,
    written_week,
)
from stamind.clock import date_range, month_end, month_start, parse_date, shift, week_start
from stamind.config import config
from stamind.db.objectives import ARCHIVED
from stamind.sports import canonical_sport
from stamind.strength.comparison import carries_gym_log


class Day(NamedTuple):
    """One date's facts.

    `results` are the day's `analyze_adherence` rows (planned session, matched activity,
    `pending`), each with the `status` `classify_adherence` gives it, and its `fill`: a row
    of the same shape graded against what `workout generate` wrote, or None where the day
    gets no colour from it (DESIGN_calendar_as_written.md §2). `unplanned` pairs each
    activity that matched no session with its `unplanned_kind`, minor ones included, so each
    view decides what it leaves out. `dropped` are the sessions written for the day that
    count as dropped, `changes` what became of each one the coach changed (§3), and
    `changed` whether the coach changed the day at all, which earns it a corner (§2)."""
    date: str
    results: List[Dict[str, Any]]
    unplanned: List[Tuple[Dict[str, Any], str]]
    constraints: List[Dict[str, Any]]
    signals: List[Dict[str, Any]]
    dropped: List[Dict[str, Any]]
    changes: List[Changed]
    changed: bool

    def worth_showing(self) -> List[Dict[str, Any]]:
        """The unplanned activities the companion mentions: every kind but minor (§3.3)."""
        return [act for act, kind in self.unplanned if kind != MINOR]


class Calendar(NamedTuple):
    """The days of `[start, end]`, and what surrounds them.

    `mesocycles` are the plans' mesocycles from the first day of `start`'s month to the
    last day of `end`'s month or the last goal, whichever is later, in date order, so the
    plan view can run to the last goal (§5).
    `goals` are every goal not archived, in date order. `schedule_end` is the last day
    the written schedule covers, the date `workout list` marks as its end. `weeks` are
    `graded_weeks`' for the range: each ended week's Monday and its grade per sport
    (DESIGN_calendar_as_written.md §2)."""
    start: str
    end: str
    today: str
    days: List[Day]
    mesocycles: List[Dict[str, Any]]
    goals: List[Dict[str, Any]]
    schedule_end: Optional[str]
    weeks: List[Tuple[str, List[SportGrade]]]


def _covering(rows: List[Dict[str, Any]], day: str) -> List[Dict[str, Any]]:
    return [c for c in rows if str(c["start_date"]) <= day <= str(c["end_date"])]


def _fill(
    row: Dict[str, Any], session: Optional[WrittenSession], threshold: float
) -> Optional[Dict[str, Any]]:
    """A standing session's fill (DESIGN_calendar_as_written.md §2): a miss as it is, whatever
    it replaced (choice 12); graded against its written version; against the coach's ask when
    it was added, took a written rest or yoga's place, or its sets grade it; none for an added
    rest day, or for a session that replaced a written one of another sport, which counts as
    dropped."""
    if row["status"] == MISSED:
        return dict(row)
    sport = canonical_sport(row["planned"]["sport_type"])
    written = session.written if session is not None else None
    if written is not None and canonical_sport(written["sport_type"]) != sport:
        if canonical_sport(written["sport_type"]) not in UNGRADED:
            return None
        written = None
    if written is None:
        return None if sport == "rest" else dict(row)
    if carries_gym_log(row["completed"]):
        return dict(row)
    status = classify_adherence(
        written, row["completed"], threshold, pending=row.get("pending", False)
    )["status"]
    return {**row, "planned": written, "status": status}


def _dropped(session: WrittenSession, standing: Set[str]) -> bool:
    """A written training session removed, or replaced by another sport, unless a session of
    its sport stands on its day (§2, choice 5). Rest and yoga never count."""
    sport = canonical_sport(session.written["sport_type"])
    if sport in UNGRADED or sport in standing:
        return False
    return session.now is None or canonical_sport(session.now["sport_type"]) != sport


def gather(dbh, start: str, end: str, today: str) -> Calendar:
    """The facts for `[start, end]` as of `today`, read from `dbh`."""
    window = adherence_window(dbh, start, end, today)
    threshold = config.minor_activity_load_threshold
    walked = compare_days(parse_date(start), window.history_days, window.results,
                          window.activities, None)
    by_date = {day: (results, unplanned) for day, results, unplanned in walked}
    constraints = dbh.get_constraints(start, end)
    signals = dbh.get_daily_signals(start, end)
    # Whole weeks, so a session moved into the first days keeps its written version.
    written = written_week(dbh, week_start(start), shift(week_start(end), 6))
    by_now = {s.now["id"]: s for s in written if s.now is not None}
    written_on: Dict[str, List[WrittenSession]] = {}
    changed_days: Set[str] = set()
    for session in written:
        written_on.setdefault(session.written["date"], []).append(session)
        if not departed(session):
            continue
        changed_days.add(session.written["date"])
        if session.now is not None:
            changed_days.add(session.now["date"])

    days = []
    for day in date_range(start, end):
        results, unplanned = by_date.get(day, ([], []))
        graded = []
        for r in results:
            row = {**r, "status": classify_adherence(
                r["planned"], r["completed"], threshold, pending=r.get("pending", False)
            )["status"]}
            session = by_now.get(r["planned"]["revision_id"])
            if session is None:
                changed_days.add(day)
            row["fill"] = _fill(row, session, threshold)
            graded.append(row)
        kinds = [(act, unplanned_kind(act, day, window.covered_ranges, threshold))
                 for act in unplanned]
        standing = {canonical_sport(r["planned"]["sport_type"]) for r in results}
        own = written_on.get(day, [])
        days.append(Day(
            date=day, results=graded, unplanned=kinds,
            constraints=_covering(constraints, day),
            signals=[s for s in signals if s["date"] == day],
            dropped=[s.written for s in own if _dropped(s, standing)],
            changes=[c for c in map(calendar_change, own) if c is not None],
            changed=day in changed_days,
        ))

    goals = [g for g in dbh.get_objectives() if g.get("status") != ARCHIVED]
    last_goal = max([str(g["target_date"]) for g in goals], default=end)
    # Whole months, so the button's list and the files' list are one list
    # (DESIGN_miniapp_storage.md §4).
    mesocycles, _dropped_mesocycles = dbh.get_governing_mesocycles(
        month_start(start), max(month_end(end), last_goal)
    )
    return Calendar(
        start=start, end=end, today=today, days=days,
        mesocycles=sorted(mesocycles, key=lambda m: str(m["start_date"])),
        goals=sorted(goals, key=lambda g: str(g["target_date"])),
        schedule_end=plan_end(dbh.get_workouts()),
        weeks=graded_weeks(dbh, start, end, today),
    )


def next_goal(goals: List[Dict[str, Any]], today: str) -> Optional[Dict[str, Any]]:
    """The nearest goal still ahead of `today`, or None (§3.5)."""
    ahead = [g for g in goals if str(g["target_date"]) >= today]
    return ahead[0] if ahead else None
