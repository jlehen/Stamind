"""Workout CLI: `workout generate --strength-only`, the strength planner alone over a span
(DESIGN_strength_tracking.md §9)."""
import argparse
from typing import Optional, Tuple

from trainmate import runtime
from trainmate.cli.runway import schedule_coverage
from trainmate.cli.selectors import resolve_window
from trainmate.cli.workouts.heads_up import print_send_notice, revision_dates
from trainmate.sports import canonical_sport
from trainmate.util import cmd, fmt_date, green, notice, red, step, today_str, wrap_text

STRENGTH = canonical_sport("strength_training")


def _span(args: argparse.Namespace) -> Optional[Tuple[str, str]]:
    """The days the selectors name, from today at the earliest. An end left open is the last
    scheduled day, since the days after it hold no session to write again."""
    today = today_str()
    start, end = resolve_window(args)
    start = max(start or today, today)
    end = end or schedule_coverage()[0]
    if not end or end < start:
        notice("There is no scheduled day ahead in that selection.", red)
        return None
    return start, end


def generate_strength_only(args: argparse.Namespace, force: bool, unchanged: str) -> None:
    """Writes every strength session of the span again, and nothing else. The question
    before the call counts the strength sessions only, since no other session can change."""
    span = _span(args)
    if span is None:
        return
    start, end = span
    sessions = [
        w for w in runtime.db.get_workouts(start_date=start, end_date=end)
        if canonical_sport(w['sport_type']) == STRENGTH
    ]
    if not sessions:
        notice(f"No strength session between {fmt_date(start)} and {fmt_date(end)}.")
        return
    if not force and not runtime.prompt.confirm(wrap_text(
        f"You have {len(sessions)} strength session(s) between {fmt_date(start)} and "
        f"{fmt_date(end)}. Writing them again costs one LLM call; no other session "
        f"changes, you see the result before anything is written, and "
        f"{cmd('workout rollback')} undoes it. Write them again?"
    )):
        notice(f"Workout generation cancelled{unchanged}")
        return

    step("Asking the strength planner to write the strength sessions again...")
    proposal = runtime.coach_service.workout_generate_strength(start, end)
    runtime.render.adapt_reason(proposal.reason)
    if not proposal.workouts:
        # It still weighed them, so the next `workout adapt` does not ask again (§9).
        runtime.coach_service.workout_revision_record_no_change(proposal)
        return
    print_send_notice(revision_dates(proposal))
    runtime.render.revision_preview(proposal, "Strength sessions written again")
    if not (force or runtime.prompt.confirm("Apply these changes?")):
        notice(f"Workouts discarded{unchanged}")
        return
    runtime.coach_service.workout_revision_apply(proposal)
    print(green(
        f"\nWrote {len(proposal.workouts)} strength session(s) again. Run "
        f"{cmd('workout rollback')} to undo it."
    ))
