"""A week against its sessions as `workout generate` wrote them (DESIGN_week_as_written.md).

Each day is checked against the schedule as it stands now (`compare.py`). Each week that has
ended is checked here against its written week: its sessions as `workout generate` left them,
found slot by slot (§3), and graded per sport (§2). The functions that read are handed the
database handle, as `adherence_window` is, so the module stays pure of the storage layer.
"""
import math
from typing import Any, Dict, List, NamedTuple, Optional, Tuple

from stamind.analytics.adherence import adherence_tolerance
from stamind.analytics.load import activity_load, planned_load
from stamind.clock import fmt_day, local_day, shift, week_start
from stamind.config import config
from stamind.sports import STRENGTH_SPORTS, canonical_sport
from stamind.text import wrap_text

LOAD, SESSIONS = "load", "sessions"

# Recovery, not a shortfall (§2).
UNGRADED = frozenset({"yoga", "rest"})


class WrittenSession(NamedTuple):
    """One session of the written week (§3)."""
    written: Dict[str, Any]        # its written version, hydrated as `get_workouts` returns it
    now: Optional[Dict[str, Any]]  # its lineage's live version that is not a void, raw
    later: List[Dict[str, Any]]    # its lineage's versions dated in its week after the written one


class Changed(NamedTuple):
    """A session of a short sport that is no longer as written (§3, §5)."""
    written: Dict[str, Any]
    what: str               # "dropped", "replaced by …", "moved to …", "cut from …"
    day: Optional[str]      # the athlete's day of the change that did it
    reason: Optional[str]   # the reason stored with that change


class SportGrade(NamedTuple):
    """One sport of one ended week (§2)."""
    sport: str
    measure: str            # LOAD or SESSIONS
    written: float          # the load written, or the number of sessions
    done: float
    short: bool
    changed: List[Changed]  # filled under a short sport only (§2)


# ------------------------------------------------------------------ the written week (§3)

def _left_after(
    version: Dict[str, Any], left: Optional[Dict[str, Any]],
    left_by_version: Dict[int, Optional[Dict[str, Any]]],
) -> Optional[Dict[str, Any]]:
    """What `workout generate` left in a slot once `version` was written: §3's table."""
    if version["restored_from"] is not None:
        return left_by_version.get(version["restored_from"], left)
    if version["kind"] == "generate" and version["void"]:
        return None
    if version["kind"] == "generate":
        return version
    if version["void"] and version["kind"] in ("stand-down", "rollback"):
        return None
    return left


def _slot_ends(versions: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """The version each slot's walk ends on, slots holding nothing left out. Walked per slot
    because `workout rollback` undoes per slot (§3)."""
    slots: Dict[Tuple[str, str], List[Dict[str, Any]]] = {}
    for version in versions:
        slots.setdefault((version["date"], version["sport_canonical"]), []).append(version)
    ends = []
    for slot_versions in slots.values():
        left: Optional[Dict[str, Any]] = None
        left_by_version: Dict[int, Optional[Dict[str, Any]]] = {}
        for version in slot_versions:
            left = _left_after(version, left, left_by_version)
            left_by_version[version["id"]] = left
        if left is not None:
            ends.append(left)
    return ends


def _written_versions(versions: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """The written version of each session, in date order: when two slots of one week end
    on the same lineage, the newer version counts (§3)."""
    kept: Dict[Tuple[int, str], Dict[str, Any]] = {}
    for version in _slot_ends(versions):
        key = (version["lineage_id"], week_start(version["date"]))
        if key in kept and kept[key]["id"] > version["id"]:
            continue
        kept[key] = version
    return sorted(kept.values(), key=lambda v: (v["date"], v["id"]))


def written_week(
    dbh, start: Optional[str], end: Optional[str]
) -> List[WrittenSession]:
    """Each written session dated from `start` to `end`, every one when both are None, in
    date order, with its now and what its lineage did in its week afterwards (§3, §9)."""
    versions, now = dbh.get_slot_history(start, end)
    written = _written_versions(versions)
    hydrated = {
        w["revision_id"]: w for w in dbh.hydrate_revisions([v["id"] for v in written])
    }
    in_week: Dict[Tuple[int, str], List[Dict[str, Any]]] = {}
    for version in versions:
        in_week.setdefault((version["lineage_id"], week_start(version["date"])), []).append(
            version
        )
    sessions = []
    for version in written:
        lineage = in_week[(version["lineage_id"], week_start(version["date"]))]
        sessions.append(WrittenSession(
            hydrated[version["id"]], now.get(version["lineage_id"]),
            [later for later in lineage if later["id"] > version["id"]],
        ))
    return sessions


def graded_workouts(
    dbh, start: Optional[str], end: Optional[str], today: str
) -> List[Dict[str, Any]]:
    """What "planned" means for a span (§4): the written versions for the days before
    `today`'s Monday, and from that Monday on the live sessions, as `get_workouts` returns
    them. None leaves that end of the span open."""
    split = week_start(today)
    past: List[Dict[str, Any]] = []
    if start is None or start < split:
        past_end = shift(split, -1)
        if end is not None and end < split:
            past_end = end
        past = [session.written for session in written_week(dbh, start, past_end)]
    if end is not None and end < split:
        return past
    live_start = split
    if start is not None and start > split:
        live_start = start
    return past + dbh.get_workouts(start_date=live_start, end_date=end)


# ------------------------------------------------------------------ the grade (§2, §3)

def _load_by_sport(
    items: List[Dict[str, Any]], load_fn, sport_field: str
) -> Dict[str, float]:
    """Sums `load_fn(item)` per canonical sport. A completed activity's sport is in
    `activity_type`, a session's in `sport_type`."""
    by_sport: Dict[str, float] = {}
    for item in items:
        sport = canonical_sport(item.get(sport_field) or "unknown")
        by_sport[sport] = by_sport.get(sport, 0.0) + load_fn(item)
    return by_sport


def _sessions_done(activities: List[Dict[str, Any]], sport: str) -> int:
    """The activities of `sport` long enough to be a session, so a warm-up is not (§2)."""
    floor = config.min_activity_minutes * 60
    return sum(
        1 for a in activities
        if canonical_sport(a.get("activity_type") or "unknown") == sport
        and float(a.get("duration_sec") or 0.0) >= floor
    )


def _cut_words(written: Dict[str, Any], now: Dict[str, Any]) -> str:
    """'cut from 120 to 40 min', or in load when the length did not fall."""
    before, after = written.get("duration_minutes"), now.get("duration_minutes")
    if before and after and after < before:
        return f"cut from {before} to {after} min"
    return f"cut from load {planned_load(written):.0f} to {planned_load(now):.0f}"


def _what(session: WrittenSession, measure: str) -> Optional[str]:
    """What became of a session: dropped, moved out or cut, or None when none (§3)."""
    written, now = session.written, session.now
    if now is None:
        return "dropped"
    if canonical_sport(now["sport_type"]) != canonical_sport(written["sport_type"]):
        return f"replaced by {now['title']}"
    if week_start(now["date"]) != week_start(written["date"]):
        return f"moved to {fmt_day(now['date'])}"
    if measure == SESSIONS or planned_load(now) >= planned_load(written):
        return None
    what = _cut_words(written, now)
    if now["date"] != written["date"]:
        what += f", moved to {fmt_day(now['date'])}"
    return what


def _changes(version: Dict[str, Any], previous: Dict[str, Any]) -> bool:
    """Whether a version removed the session or changed its day, its sport or its load."""
    if version["void"]:
        return True
    return (
        version["date"] != previous["date"]
        or canonical_sport(version["sport_type"]) != canonical_sport(previous["sport_type"])
        or planned_load(version) != planned_load(previous)
    )


def _changed(session: WrittenSession, measure: str) -> Optional[Changed]:
    """A session no longer as written, with the newest version dated in its week that
    changed it; a version that only reworded it is skipped (§5)."""
    what = _what(session, measure)
    if what is None:
        return None
    found: Optional[Dict[str, Any]] = None
    previous = session.written
    for version in session.later:
        if _changes(version, previous):
            found = version
        previous = version
    if found is None:
        return Changed(session.written, what, None, None)
    reason = " ".join((found["reason"] or "").split()) or None
    return Changed(session.written, what, local_day(found["change_created_at"]), reason)


def week_grade(
    sessions: List[WrittenSession], activities: List[Dict[str, Any]]
) -> List[SportGrade]:
    """One ended week, per sport (§2): strength counted in sessions, yoga and rest not
    graded, every other sport added up by load over the week's activities, planned or not."""
    by_sport: Dict[str, List[WrittenSession]] = {}
    for session in sessions:
        sport = canonical_sport(session.written["sport_type"])
        if sport in UNGRADED:
            continue
        by_sport.setdefault(sport, []).append(session)
    written_load = _load_by_sport([s.written for s in sessions], planned_load, "sport_type")
    done_load = _load_by_sport(activities, activity_load, "activity_type")
    grades = []
    for sport in sorted(by_sport):
        own = by_sport[sport]
        if sport in STRENGTH_SPORTS:
            measure, written = SESSIONS, float(len(own))
            done = float(_sessions_done(activities, sport))
            short = done < written
        else:
            measure, written = LOAD, written_load[sport]
            done = done_load.get(sport, 0.0)
            short = bool(written) and (written - done) / written > adherence_tolerance(written)
        changed: List[Changed] = []
        if short:
            changed = [c for c in (_changed(s, measure) for s in own) if c]
        grades.append(SportGrade(sport, measure, written, done, short, changed))
    return grades


def graded_weeks(
    dbh, start: str, end: str, today: str
) -> List[Tuple[str, List[SportGrade]]]:
    """Each week that has ended and overlaps `start` to `end`, graded whole from Monday to
    Sunday, as `(its Monday, its grade)`; a week with nothing written to grade is left out.
    The week under way is never graded (§2)."""
    first = week_start(start)
    last = min(week_start(end), shift(week_start(today), -7))
    if last < first:
        return []
    sunday = shift(last, 6)
    sessions = written_week(dbh, first, sunday)
    activities = dbh.get_completed_activities(start_date=first, end_date=sunday)
    weeks = []
    monday = first
    while monday <= last:
        grade = week_grade(
            [s for s in sessions if week_start(s.written["date"]) == monday],
            [a for a in activities if week_start(a["date"]) == monday],
        )
        if grade:
            weeks.append((monday, grade))
        monday = shift(monday, 7)
    return weeks


# ------------------------------------------------------------------ the words (§5)

def percent(grade: SportGrade) -> Optional[int]:
    """The share done, rounded down so a week that is short never reads 85% (§2)."""
    if not grade.written:
        return None
    return math.floor(grade.done / grade.written * 100)


def changed_words(changed: Changed) -> str:
    """What became of a session and why, the words every surface shares (§5)."""
    if changed.day is None:
        return changed.what
    words = f"{changed.what}, changed {fmt_day(changed.day)}"
    if changed.reason:
        words += f': "{changed.reason}"'
    return words


def sport_line(grade: SportGrade) -> str:
    """'cycling: written 190, done 156 (82%), short'."""
    if grade.measure == SESSIONS:
        noun = "session" if grade.written == 1 else "sessions"
        line = f"{grade.sport}: written {grade.written:.0f} {noun}, done {grade.done:.0f}"
    else:
        line = f"{grade.sport}: written {grade.written:.0f}, done {grade.done:.0f}"
        share = percent(grade)
        if share is not None:
            line += f" ({share}%)"
    if grade.short:
        line += ", short"
    return line


def week_line(grade: List[SportGrade]) -> str:
    """One ended week on one line, as `sm progress weeks` lists it:
    'cycling 82%, short · strength_training 1 of 2, short' (DESIGN_progress_page.md §6)."""
    parts = []
    for sport in grade:
        share = percent(sport)
        if sport.measure == SESSIONS:
            part = f"{sport.sport} {sport.done:.0f} of {sport.written:.0f}"
        elif share is None:
            part = f"{sport.sport} done {sport.done:.0f}"
        else:
            part = f"{sport.sport} {share}%"
        if sport.short:
            part += ", short"
        parts.append(part)
    return " · ".join(parts)


def week_grade_lines(grade: List[SportGrade], indent: str) -> List[str]:
    """The lines the terminal and the prompts share: one per sport, and under a short sport
    each session no longer as written, its reason printed whole (§5)."""
    lines = []
    for sport in grade:
        lines.append(f"{indent}{sport_line(sport)}")
        for changed in sport.changed:
            written = changed.written
            lines.append(wrap_text(
                f"{indent}  {fmt_day(written['date'])} {written['title']}: "
                f"{changed_words(changed)}"
            ))
    return lines
