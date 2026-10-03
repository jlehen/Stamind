"""The date check: which retrospective records exist (DESIGN_cycle_retrospective.md §3).

A database lookup with no model call. It compares the records with the plan versions that
Stamind keeps, removes the records the current plan contradicts, then creates the missing
ones. Writing a record's lines is `coach/service/retrospective.py`.
"""
from datetime import datetime
from typing import Any, Dict, List, Optional, Tuple

from stamind import clock
from stamind.db.objectives import ARCHIVED
from stamind.db.retrospectives import CALLED_OFF, FINISHED, MESOCYCLE, REPLACED

# A mesocycle cut short gets a record only when this many days of it were trained (§3).
MIN_TRAINED_DAYS = 7


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
        # Removing first: a record removed here is never created again in the same run.
        _remove_contradicted(dbh, goal_id, mesocycles, today)
        _record_finished(dbh, goal_id, mesocycles, today)
        _record_replaced(dbh, goal_id, mesocycles)


def _remove_contradicted(
    dbh, goal_id: int, mesocycles: List[Dict[str, Any]], today: str
) -> None:
    """Removes each mesocycle record whose mesocycle is in the current plan again, with
    the same start date, and has not ended."""
    not_ended = {m['start_date'] for m in mesocycles if m['end_date'] >= today}
    for record in dbh.get_retrospectives(goal_id, MESOCYCLE):
        if record['start_date'] in not_ended:
            dbh.delete_retrospective(record['id'])


def _record_finished(
    dbh, goal_id: int, mesocycles: List[Dict[str, Any]], today: str
) -> None:
    """Records each mesocycle of the current plan whose end date has passed."""
    for m in mesocycles:
        if m['end_date'] >= today:
            continue
        dbh.add_retrospective(
            goal_id, MESOCYCLE, m['name'], m['start_date'], m['end_date'], FINISHED,
            m['focus'],
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
    the mesocycle under way as cut short. The date check skips the goal from then on."""
    date_check(dbh, today, objective_id)
    current = dbh.get_macrocycle_for_objective(objective_id)
    if not current:
        return
    for m in dbh.get_mesocycles_for_macrocycle(current['id']):
        if m['start_date'] <= today <= m['end_date']:
            _record_cut_short(dbh, objective_id, m, today, CALLED_OFF)
