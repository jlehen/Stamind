"""When the schedule runs out, as a fact the surfaces word themselves.

`plan_end` is the last day the sessions cover, `plan_gap` how far short of the next goal
the periodization stops, and `runway` the single end-of-schedule answer `sm status`,
`workout adapt` and the morning push all dispatch on (DESIGN_runway_nudge.md §2/§3).
The detector is here and every wording is in `cli/runway.py`, so two surfaces cannot
disagree about the morning the plan runs out.
"""
from typing import Any, Dict, List, Optional, Tuple

from stamind.clock import days_between, parse_date


def plan_dates(workouts: List[Dict[str, Any]]) -> List[str]:
    """Every date the schedule covers: the non-removed workouts, planned rest rows
    included (DESIGN_progress_timeline.md §3 'Plan end', DESIGN_runway_nudge.md §2).

    `plan_end`, `progression._series_start` and `timeline.assemble_timeline` each built
    this list themselves, so "covered" had three definitions that only happened to
    agree."""
    return [w["date"] for w in workouts if not w.get("removed")]


def plan_end(workouts: List[Dict[str, Any]]) -> Optional[str]:
    """The last date the schedule covers: the last non-removed workout, planned rest rows
    included (DESIGN_progress_timeline.md §3 'Plan end', DESIGN_runway_nudge.md §2). The
    projection runs exactly to here and stops — no zero-fill ghost line past it. None when
    there are no non-removed workouts at all.

    No margin and no guessing at a quiet tail: the coverage invariant of
    DESIGN_runway_nudge.md §2.1 makes every date of a generated span carry a row, so the
    last covered date is read straight off them."""
    dates = plan_dates(workouts)
    return max(dates) if dates else None


def plan_gap(
    objectives: List[Dict[str, Any]], plan_end_date: Optional[str]
) -> Optional[Tuple[Dict[str, Any], int]]:
    """The next active objective the plan doesn't yet reach, and how many whole weeks
    short of it the plan ends (§3), as `(objective, weeks_before)` — or None when there
    is no plan or every active objective is already reached.

    The single source of the plan-gap derivation: `assemble_timeline` puts it on the
    payload as the structured `plan_gap` field and each surface words it itself (§6.0).
    Computing it once here keeps the two surfaces from diverging on *when* the gap fires
    or *by how much* — the CODE_REVIEW #5 class of drift."""
    if plan_end_date is None:
        return None
    # Not-called-off is the only status question here: the `target_date > plan_end_date`
    # filter below already excludes everything behind the athlete (§12).
    live = sorted(
        (o for o in objectives if o.get("status") != "archived"),
        key=lambda o: str(o["target_date"]),
    )
    next_obj = next((o for o in live if o["target_date"] > plan_end_date), None)
    if next_obj is None:
        return None
    weeks_before = max(
        0, round((parse_date(next_obj["target_date"]) - parse_date(plan_end_date)).days / 7)
    )
    return next_obj, weeks_before


# --- End-of-runway detection (DESIGN_runway_nudge.md §2) ---
# The shapes the end of the schedule can take. Surfaces dispatch on these rather than on
# the wording, the same contract `_warning`'s `code` gives the payload banners.
RUNWAY_MESOCYCLE = "mesocycle"
RUNWAY_SPAN = "span"
RUNWAY_PLAN_END_NEXT_GOAL = "plan_end_next_goal"
RUNWAY_PLAN_END_NO_GOAL = "plan_end_no_goal"


def runway(
    workouts: List[Dict[str, Any]],
    mesocycles: List[Dict[str, Any]],
    objectives: List[Dict[str, Any]],
    today: str,
    warning_days: int,
) -> Optional[Dict[str, Any]]:
    """The end-of-schedule fact, or None when nothing fires (DESIGN_runway_nudge.md §2).

    Pure over rows the caller fetched, following `plan_gap`'s contract: every surface
    words the same structured answer itself, so `status`, `workout adapt` and the morning
    push cannot diverge on *when* the schedule runs out or on which command fixes it (§3).

    `mesocycles` belong to the plan the current workouts implement, whichever
    goal it was drawn for. `warning_days` is `config.runway_warning_days`; it bounds both
    the run-up and the passed-state window (§7).

    Returns `{last_covered_date, days_left, kind, plan_end}`, plus `next_mesocycle` on a
    mesocycle cliff and `objective`/`weeks_before` on a plan cliff with a goal beyond it.
    `days_left` is negative once the cliff is behind the athlete."""
    last_covered = plan_end(workouts)
    ends = [str(m["end_date"]) for m in mesocycles if m.get("end_date")]
    if last_covered is None or not ends:
        return None
    plan_end_date = max(ends)
    days_left = days_between(today, last_covered)

    # The run-up window, then the passed state — still worth saying for `warning_days`
    # after the plan's own end, which is the morning the wrap-up matters most (§2).
    if days_left > warning_days:
        return None
    if (days_left < 0
            and days_between(max(last_covered, plan_end_date), today) > warning_days):
        return None

    state: Dict[str, Any] = {
        "last_covered_date": last_covered,
        "days_left": days_left,
        "plan_end": plan_end_date,
    }

    # A periodization wholly behind today is a plan cliff whatever the sessions did:
    # there is nothing left to generate towards, which is the same judgement `workout
    # adapt` refuses on (§4). Otherwise the comparison is the exact one the coverage
    # invariant makes possible.
    if plan_end_date >= today and last_covered < plan_end_date:
        ordered = sorted(mesocycles, key=lambda m: str(m["start_date"]))
        next_mesocycle = next(
            (m for m in ordered if str(m["start_date"]) > last_covered), None
        )
        ends_a_mesocycle = any(str(m["end_date"]) == last_covered for m in mesocycles)
        if ends_a_mesocycle and next_mesocycle is not None:
            return {**state, "kind": RUNWAY_MESOCYCLE, "next_mesocycle": next_mesocycle}
        return {**state, "kind": RUNWAY_SPAN}

    # Fed the mesocycle-derived plan end, not `plan_end`: the question here is whether the
    # PERIODIZATION reaches a goal, so a span cliff cannot read as a goal gap (§2).
    gap = plan_gap(objectives, plan_end_date)
    if gap is None:
        return {**state, "kind": RUNWAY_PLAN_END_NO_GOAL}
    return {
        **state, "kind": RUNWAY_PLAN_END_NEXT_GOAL,
        "objective": gap[0], "weeks_before": gap[1],
    }
