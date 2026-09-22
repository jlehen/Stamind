"""Which days a selector covers (DESIGN_cli_selectors.md).

`cli/selectors.py` parses `-d/-m/-M/-g` into ranges without touching anything. This file
turns those ranges into one (start_date, end_date) pair, which needs the database: a
mesocycle ID, a macrocycle ID and a goal ID each have to be looked up to learn the days
they span. `resolve_goal`, `goal_span_start` and `goal_range_for_window` answer the same
question from the goal side — which goal, and where its own span opens.

Each command declares its own default window and direction when it registers the flags,
so no handler re-implements "no filter means the last N days".
"""
import argparse
import sys
from datetime import datetime, timedelta
from typing import Optional

from stamind import runtime
from stamind.text import red
from stamind.output import notice
from stamind.clock import today_date as _today_date, today_str as _today_str
from stamind.cli.selectors import (
    DateRange, IdRange, OFFSET_RE, offset_days, parse_date_range,
)


def _fail(message: str) -> None:
    notice(f"Error: {message}", red)
    sys.exit(1)


def _meso_bounds(meso_id: int) -> tuple[str, str]:
    meso = runtime.db.get_mesocycle(meso_id)
    if not meso:
        _fail(f"Mesocycle with ID {meso_id} not found.")
    return meso['start_date'], meso['end_date']


def _current_meso_bounds() -> tuple[str, str]:
    meso = runtime.db.get_active_mesocycle(_today_str())
    if not meso:
        _fail("No active mesocycle found.")
    return meso['start_date'], meso['end_date']


def _macro_bounds(macro_id: int) -> tuple[str, str]:
    macro = runtime.db.get_macrocycle(macro_id)
    if not macro:
        _fail(f"Macrocycle with ID {macro_id} not found. Run 'plan versions' to list them.")
    mesos = runtime.db.get_mesocycles_for_macrocycle(macro_id)
    if not mesos:
        _fail(f"Macrocycle {macro_id} has no mesocycles.")
    return min(m['start_date'] for m in mesos), max(m['end_date'] for m in mesos)


def _goal_bounds(goal_id: int) -> tuple[str, str]:
    """A goal's span: from the start of its plan to the goal's own target date — which is
    past the last mesocycle when the plan doesn't reach the event yet."""
    goal = runtime.db.get_objective(goal_id)
    if not goal:
        _fail(f"Goal with ID {goal_id} not found.")
    return _macro_bounds(_goal_macro_id(goal_id))[0], goal['target_date']


def _goal_macro_id(goal_id: int) -> int:
    macro = runtime.db.get_macrocycle_for_objective(goal_id)
    if not macro:
        _fail(f"No plan exists for goal ID {goal_id}.")
    return macro['id']


def _active_goal_id() -> int:
    goal = runtime.db.get_active_objective()
    if not goal:
        _fail("No active goal found.")
    return goal['id']


def _active_macro_id() -> int:
    return _goal_macro_id(_active_goal_id())


def _id_window(rng: IdRange, bounds, current) -> tuple[Optional[str], Optional[str]]:
    """Turns an ID range into a date window: the start of the first, the end of the last."""
    if rng.current:
        return current()
    start = bounds(rng.start)[0] if rng.start is not None else None
    end = bounds(rng.end)[1] if rng.end is not None else None
    return start, end


def _date_window(
    rng: DateRange, direction: str, today: str
) -> tuple[Optional[str], Optional[str]]:
    if rng.span is None:
        return rng.start, rng.end
    match = OFFSET_RE.match(rng.span)
    days = max(1, offset_days("", match.group(2), match.group(3)))
    if direction == "forward":
        return today, (_today_date() + timedelta(days=days - 1)).strftime("%Y-%m-%d")
    return (_today_date() - timedelta(days=days - 1)).strftime("%Y-%m-%d"), today


def _span_before(end: str, span_days: int) -> str:
    return (
        datetime.strptime(end, "%Y-%m-%d").date() - timedelta(days=span_days - 1)
    ).strftime("%Y-%m-%d")


def resolve_window(args: argparse.Namespace) -> tuple[Optional[str], Optional[str]]:
    """Intersects every selector the athlete gave into one (start_date, end_date).

    Whichever side no selector bounds is filled by the command's own policy — that is the
    only place a command-specific default lives (DESIGN_cli_selectors.md §3)."""
    direction, default, span_days = getattr(
        args, "_selector_policy", ("backward", None, 7)
    )
    today = _today_str()
    windows = []

    date_range = getattr(args, "date_range", None)
    if date_range is not None:
        windows.append(_date_window(date_range, direction, today))
    meso_range = getattr(args, "meso_range", None)
    if meso_range is not None:
        windows.append(_id_window(meso_range, _meso_bounds, _current_meso_bounds))
    macro_range = getattr(args, "macro_range", None)
    if macro_range is not None:
        windows.append(_id_window(
            macro_range, _macro_bounds, lambda: _macro_bounds(_active_macro_id())
        ))
    goal_range = getattr(args, "goal_range", None)
    if goal_range is not None:
        windows.append(_id_window(
            goal_range, _goal_bounds, lambda: _goal_bounds(_active_goal_id())
        ))
    for extra in getattr(args, "_extra_windows", ()):  # positional date targets
        windows.append(extra)

    if not windows:
        if default is None:
            return None, None
        windows.append(_date_window(parse_date_range(default), direction, today))

    starts = [w[0] for w in windows if w[0]]
    ends = [w[1] for w in windows if w[1]]
    start = max(starts) if starts else None
    end = min(ends) if ends else None

    if direction == "forward" and start is None:
        start = today
    elif direction == "backward":
        end = end or today
        if start is None:
            start = _span_before(end, span_days)

    if start and end and start > end:
        _fail(f"The filters do not overlap: {start} is after {end}.")
    return start, end


def has_selector(args: argparse.Namespace) -> bool:
    """True when the athlete bounded the window themselves, rather than taking the default."""
    return any(
        getattr(args, name, None) is not None
        for name in ("date_range", "meso_range", "macro_range", "goal_range")
    )


def split_targets(targets) -> tuple[list, list]:
    """Splits parsed positional targets into (row IDs, date windows)."""
    ids = [value for kind, value in targets or () if kind == "id"]
    ranges = [value for kind, value in targets or () if kind == "date"]
    return ids, ranges


def resolve_goal(goal_id: Optional[int]) -> Optional[dict]:
    """The goal a plan command targets: the given ID (whatever its status, so archived
    and completed goals stay reachable), else the next active goal by target date.
    Prints the reason and returns None when there is none."""
    if goal_id is not None:
        goal = runtime.db.get_objective(goal_id)
        if not goal:
            notice(f"Goal with ID {goal_id} not found.", red)
        return goal
    objectives = runtime.db.upcoming_objectives()
    if not objectives:
        notice("No active goals found. Stamind needs at least one goal.")
        return None
    objectives.sort(key=lambda x: str(x['target_date']))
    return objectives[0]


def goal_span_start(goal: Optional[dict]) -> Optional[str]:
    """The first day of a goal's OWN span: the day after the goal before it, never
    earlier than today (DESIGN_cli_selectors.md §9)."""
    if not goal:
        return None
    today = _today_date().strftime("%Y-%m-%d")
    preceding = runtime.db.get_preceding_objectives(goal['target_date'])
    if not preceding:
        return today
    day_after = (
        datetime.strptime(preceding[0]['target_date'], "%Y-%m-%d").date()
        + timedelta(days=1)
    ).strftime("%Y-%m-%d")
    return max(day_after, today)


def goal_range_for_window(start: str, end: str) -> Optional[IdRange]:
    """The `-g` selector naming every upcoming goal whose own span overlaps [start, end].

    What a constraint-triggered replan targets: the plans that actually cover the
    disrupted days, never the next goal on the calendar (DESIGN_constraints.md §7).
    None when no goal's span holds any of them — a window wholly behind us, or one
    dated past the last goal — where there is no plan to reshape.

    Goals partition the timeline, so the overlap is contiguous and an IdRange over its
    two ends re-derives exactly this set through the shared grammar (§9).
    """
    overlapping = [
        g for g in runtime.db.upcoming_objectives()
        if str(g['target_date']) >= start and str(goal_span_start(g)) <= end
    ]
    if not overlapping:
        return None
    overlapping.sort(key=lambda g: (str(g['target_date']), g['id']))
    return IdRange(start=overlapping[0]['id'], end=overlapping[-1]['id'])
