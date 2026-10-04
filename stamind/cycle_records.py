"""The retrospective records: which ones exist, when one is due, and how one reads
(DESIGN_cycle_retrospective.md §2, §3, §4).

The date check is a database lookup with no model call. It compares the records with the
plan versions that Stamind keeps, removes the records the current plan contradicts, then
creates the missing ones. Writing a record's lines is `coach/service/retrospective.py`.
"""
from datetime import datetime
from typing import Any, Dict, List, Optional, Tuple

from stamind import clock, retrospective_question
from stamind.analytics.zone_tables import PROMPT_WIDTH, fmt_duration
from stamind.benchmarks import format_value, label_for_kind
from stamind.db.objectives import ARCHIVED
from stamind.db.retrospectives import (
    CALLED_OFF, DUE_AFTER_DAYS, FINISHED, MESOCYCLE, PLAN, REPLACED,
)
from stamind.text import wrap_text

# A mesocycle cut short gets a record only when this many days of it were trained (§3).
MIN_TRAINED_DAYS = 7

ENDED_LABELS = {
    FINISHED: "finished",
    REPLACED: "cut short by a new plan",
    CALLED_OFF: "cut short, the goal was called off",
}


def is_due(record: Dict[str, Any], today: str) -> bool:
    """Whether the write step writes this record now. It reads the record alone: seven
    days after its end, or sooner when it holds the athlete's words (§4)."""
    if record['body'] is not None:
        return False
    if record['athlete_words']:
        return True
    return clock.days_between(record['end_date'], today) >= DUE_AFTER_DAYS


def _fitness(numbers: Dict[str, Any]) -> str:
    start, end = numbers.get('fitness_start'), numbers.get('fitness_end')
    if start is None or end is None:
        return "fitness not on record"
    return f"fitness {start:.0f} -> {end:.0f}"


def _tests(numbers: Dict[str, Any]) -> str:
    """'FTP 250 W -> 262 W' for each benchmark with a result in the record's days."""
    parts = []
    for test in numbers.get('benchmarks') or []:
        label = label_for_kind(test['kind'])
        after = format_value(test['kind'], test['after'])
        if test.get('before') is None:
            parts.append(f"{label} {after} (first on record)")
            continue
        parts.append(f"{label} {format_value(test['kind'], test['before'])} -> {after}")
    return ", ".join(parts) or "no test"


def numbers_line(numbers: Dict[str, Any]) -> str:
    """The first line of a record: its stored numbers, rounded for display (§2)."""
    return " · ".join([
        f"Sessions {numbers['sessions_done']} of {numbers['sessions_planned']}",
        f"load {numbers['load_done']:.0f} of {numbers['load_planned']:.0f} TSS",
        fmt_duration(numbers['duration_sec']),
        _fitness(numbers),
        _tests(numbers),
    ])


def record_name(record: Dict[str, Any]) -> str:
    """What a record is called where it is listed: the mesocycle's name, or the plan
    named after its goal."""
    if record['level'] == PLAN:
        return f"Plan toward \"{record['name']}\""
    return record['name']


def record_lines(record: Dict[str, Any]) -> List[str]:
    """What a written record holds: its numbers, its lines and the athlete's words (§2)."""
    lines = [numbers_line(record['numbers'])]
    lines += [line.strip() for line in record['body'].splitlines() if line.strip()]
    if record['athlete_words']:
        lines.append(f"Athlete: \"{' '.join(record['athlete_words'].split())}\"")
    return lines


def record_text(record: Dict[str, Any], width: int = PROMPT_WIDTH) -> str:
    """One written record, as a prompt prints it (§2)."""
    lines = [
        f"{record_name(record)} ({record['start_date']}..{record['end_date']}), "
        f"{ENDED_LABELS[record['ended_by']]}",
    ]
    lines += [f"  {line}" for line in record_lines(record)]
    return wrap_text("\n".join(lines), width)


def covered(dbh, plan: Dict[str, Any]) -> List[Dict[str, Any]]:
    """The mesocycle records that a record of a plan stands for: those of its goal that
    lie inside its days (§6)."""
    return [
        record for record in dbh.get_retrospectives(plan['objective_id'], MESOCYCLE)
        if plan['start_date'] <= record['start_date']
        and record['end_date'] <= plan['end_date']
    ]


def date_check(dbh, today: str, objective_id: Optional[int] = None) -> None:
    """Runs the check for every goal not called off, or for the one goal given."""
    if objective_id is not None:
        goal_ids = [objective_id]
    else:
        goal_ids = [g['id'] for g in dbh.get_objectives() if g.get('status') != ARCHIVED]
    for goal_id in goal_ids:
        current = dbh.get_macrocycle_for_objective(goal_id)
        if not current:
            continue
        mesocycles = dbh.get_mesocycles_for_macrocycle(current['id'])
        if not mesocycles:
            continue
        plan_end = max(m['end_date'] for m in mesocycles)
        # Removing first: a record removed here is never created again in the same run.
        _remove_contradicted(dbh, goal_id, mesocycles, plan_end, today)
        _record_finished(dbh, goal_id, mesocycles, plan_end, today)
        _record_replaced(dbh, goal_id, mesocycles)
        if plan_end >= today:
            continue
        plan_id = _record_plan(dbh, goal_id, current['strategy'], plan_end, FINISHED)
        _ask(dbh, plan_id, plan_end, today)


def _remove_contradicted(
    dbh, goal_id: int, mesocycles: List[Dict[str, Any]], plan_end: str, today: str
) -> None:
    """Removes each mesocycle record whose mesocycle is in the current plan again, with
    the same start date, and has not ended. Removes a "called off" record of the plan when
    that plan has not ended."""
    not_ended = {m['start_date'] for m in mesocycles if m['end_date'] >= today}
    for record in dbh.get_retrospectives(goal_id, MESOCYCLE):
        if record['start_date'] in not_ended:
            dbh.delete_retrospective(record['id'])
    if plan_end < today:
        return
    for record in dbh.get_retrospectives(goal_id, PLAN):
        if record['ended_by'] == CALLED_OFF:
            dbh.delete_retrospective(record['id'])


def _ask(dbh, record_id: Optional[int], end_date: str, today: str) -> None:
    """Queues the question about a record just created, when its end is less than seven
    days old (§4)."""
    if record_id is None:
        return
    if clock.days_between(end_date, today) < DUE_AFTER_DAYS:
        retrospective_question.ask_about(dbh.get_retrospective(record_id))


def _record_finished(
    dbh, goal_id: int, mesocycles: List[Dict[str, Any]], plan_end: str, today: str
) -> None:
    """Records each mesocycle of the current plan whose end date has passed, and asks the
    athlete about it. The last mesocycle of the plan gets no question of its own: the plan
    ends on the same day, and the one question is about the plan (§4)."""
    for m in mesocycles:
        if m['end_date'] >= today:
            continue
        record_id = dbh.add_retrospective(
            goal_id, MESOCYCLE, m['name'], m['start_date'], m['end_date'], FINISHED,
            m['focus'],
        )
        if m['end_date'] != plan_end:
            _ask(dbh, record_id, m['end_date'], today)


def _record_plan(
    dbh, goal_id: int, strategy: str, end_date: str, ended_by: str
) -> Optional[int]:
    """Records the goal's plan up to `end_date`. It covers the mesocycle records that end
    after the goal's previous record of a plan, and it starts where the earliest one
    starts. No record when there is none to cover (§6)."""
    previous = dbh.get_retrospectives(goal_id, PLAN)
    after = previous[-1]['end_date'] if previous else ""
    mesocycles = [
        record for record in dbh.get_retrospectives(goal_id, MESOCYCLE)
        if record['end_date'] > after
    ]
    if not mesocycles:
        return None
    return dbh.add_retrospective(
        goal_id, PLAN, dbh.get_objective(goal_id)['title'],
        min(record['start_date'] for record in mesocycles), end_date, ended_by, strategy,
    )


def _replaced_on(version: Dict[str, Any]) -> str:
    """The day a plan version was replaced, on the athlete's clock."""
    return clock.day_str(clock.to_local(datetime.fromisoformat(version['superseded_at'])))


def _record_replaced(dbh, goal_id: int, mesocycles: List[Dict[str, Any]]) -> None:
    """Records as cut short each mesocycle that a replaced plan version had under way on
    the day it was replaced, and that the current plan does not hold.

    When several replaced versions hold the mesocycle, the one replaced last decides. A
    mesocycle that had already ended inside that version gets no record (§10)."""
    replaced = sorted(
        (v for v in dbh.get_macrocycle_versions(goal_id) if v.get('superseded_at')),
        key=lambda v: datetime.fromisoformat(v['superseded_at']),
    )
    last: Dict[str, Tuple[str, Dict[str, Any]]] = {}
    for version in replaced:
        day = _replaced_on(version)
        for m in dbh.get_mesocycles_for_macrocycle(version['id']):
            if m['start_date'] < day:
                last[m['start_date']] = (day, m)

    kept = {m['start_date'] for m in mesocycles}
    for start, (day, m) in last.items():
        if start in kept or m['end_date'] < day:
            continue
        _record_cut_short(dbh, goal_id, m, day, REPLACED)


def _record_cut_short(
    dbh, goal_id: int, mesocycle: Dict[str, Any], cut_on: str, ended_by: str
) -> None:
    """Records a mesocycle up to the day before `cut_on`, when enough of it was trained."""
    if clock.days_between(mesocycle['start_date'], cut_on) < MIN_TRAINED_DAYS:
        return
    dbh.add_retrospective(
        goal_id, MESOCYCLE, mesocycle['name'], mesocycle['start_date'],
        clock.shift(cut_on, -1), ended_by, mesocycle['focus'],
    )


def record_call_off(dbh, objective_id: int, today: str) -> None:
    """What calling a goal off records: the date check for that goal one last time, then
    the mesocycle under way as cut short, then the plan as called off, ended the day
    before. The date check skips the goal from then on."""
    date_check(dbh, today, objective_id)
    current = dbh.get_macrocycle_for_objective(objective_id)
    if not current:
        return
    for m in dbh.get_mesocycles_for_macrocycle(current['id']):
        if m['start_date'] <= today <= m['end_date']:
            _record_cut_short(dbh, objective_id, m, today, CALLED_OFF)
    _record_plan(dbh, objective_id, current['strategy'], clock.shift(today, -1), CALLED_OFF)
