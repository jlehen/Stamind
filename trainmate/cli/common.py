"""Shared helpers used across the CLI command modules.

The companion-voice line builders used to live here too; they moved to `cli/render.py`
with the rest of that voice (DESIGN_render_persona.md §7).
"""
from datetime import datetime, timedelta
from typing import Any, Dict, List, Optional
from trainmate.config import config
from trainmate.text import cmd, cyan, wrap_text, yellow
from trainmate.output import notice
from trainmate.clock import fmt_date, today_str as _today_str


def print_strength_notes(proposal) -> None:
    """What the strength planner could not do, under every preview that shows its work
    (DESIGN_strength_tracking.md §9).

    Two things: the exercises its output checks dropped, each naming the day and the name
    TrainMate does not know, and the one sentence for a morning it could not recheck the
    kilograms at all. Shared by `workout generate`'s preview, `workout adapt`'s and the
    companion's, which is why it lives here rather than in whichever one printed it first.
    """
    for line in getattr(proposal, 'strength_dropped', ()):
        notice(line)
    if getattr(proposal, 'strength_notice', None):
        print(wrap_text(proposal.strength_notice))


def ensure_recent_data(
    end_date: Optional[str] = None, no_pull: bool = False, force_pull: bool = False
) -> None:
    """Ensures Garmin data covering the recent metrics window is present and fresh,
    auto-pulling small/recent gaps and surfacing large backfills as a command. Warns
    if today's metrics are still unavailable afterward. `force_pull` bypasses the
    refresh-minutes throttle."""
    from trainmate import runtime
    if no_pull:
        return
    end_date = end_date or _today_str()
    history_days = config.metrics_lookback_days
    start_date = (
        datetime.strptime(end_date, "%Y-%m-%d").date() - timedelta(days=history_days - 1)
    ).strftime("%Y-%m-%d")
    runtime.garmin.ensure_data(start_date, end_date, force=force_pull)

    today = _today_str()
    if end_date == today:
        rows = runtime.db.get_metrics_cache(start_date=today, end_date=today)
        present = bool(rows) and not (
            rows[0].get('rhr') is None and rows[0].get('hrv') is None
            and rows[0].get('sleep_score') is None and rows[0].get('stress') is None
        )
        if not present:
            notice(
                f"Note: Garmin metrics for today ({fmt_date(today)}) are not available yet.",
            )


def constraint_line(c: Dict[str, Any], needs_a_pass: bool = False) -> str:
    """One-line rendering of a constraint, for `constraint list`/`show`/`add` and `status`.

    Here rather than in `cli/constraints.py` because `status` also draws it, and its own
    hand-rolled copy had already drifted (DESIGN_constraint_honoring.md §4).

    `needs_a_pass` is `coach/honoring.py`'s answer, passed in rather than re-derived: this
    stays a renderer, and the one place that decides which tier owns a directive stays the
    one place. Deciding it here is how the tag came to contradict the sweep (§8).
    """
    tags = ("no training" if c.get('rest') else "advisory") + (
        " · plan-shaping" if c.get('replan') else ""
    )
    if c.get('honored_at'):
        tags += " · honored"
    elif needs_a_pass:
        tags += " · not yet in the schedule"
    return (
        f"ID: {c['id']} | {yellow(c['title'])}: "
        f"{cyan(fmt_date(c['start_date']))} to {cyan(fmt_date(c['end_date']))} | {tags}"
    )


def report_unhonored(constraints: List[Dict[str, Any]]) -> None:
    """Names the constraints a rollback just un-honored (§8).

    The restored plan predates those honorings, so it cannot reflect them. Said after the
    fact, not before the `y`: the cost of the flag being cleared is one nudge and a cheap
    re-pass, which is not worth complicating a confirm over.
    """
    if not constraints:
        return
    names = ", ".join(f"[{c['id']}] {c['title']}" for c in constraints)
    notice(
        f"{len(constraints)} constraint(s) the restored plan predates are no longer "
        f"marked honored: {names}. Run " + cmd("workout generate") + " to build them "
        "back in.",
    )


def print_plan_cascade(objective_id: int) -> None:
    """The blast radius `goal rm --purge` and `plan rm` both print before asking — one
    renderer, so two copies cannot drift into disagreeing about one cascade
    (DESIGN_cli_noargs.md §b1)."""
    from trainmate import runtime
    versions = runtime.db.get_macrocycle_versions(objective_id)
    mesocycles = sum(
        len(runtime.db.get_mesocycles_for_macrocycle(m['id'])) for m in versions
    )
    notes = sum(len(runtime.db.list_plan_feedback(m['id'])) for m in versions)
    orphaned = runtime.db.count_future_workouts_for_macrocycles(
        [m['id'] for m in versions], _today_str()
    )
    print(f"  - {len(versions)} periodization plan version(s)")
    print(f"  - {mesocycles} mesocycle(s)")
    print(f"  - {notes} plan feedback note(s)")
    if orphaned:
        notice(
            f"  and leaves {orphaned} upcoming session(s) with no plan to explain "
            "them.",
        )
