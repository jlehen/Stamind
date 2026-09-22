"""`workout generate`: the week planner writes the sessions for a span of days.

The span, the two confirmations that gate the model call and the write, and the preview the
athlete reads before accepting it. `--strength-only` is its own flow, in `strength_only.py`.
"""
import argparse
from typing import Optional, Tuple
from stamind import runtime, settings
from stamind.config import config
from stamind.text import (
    bold, cmd, cyan, gray, green, keep_whole, pad_visible, red, wrap_text, yellow,
)
from stamind.output import notice
from stamind.clock import fmt_date, shift, today_str as _today_str
from stamind.coach.proposals import GenerateProposal
from stamind.cli import staleness
from stamind.cli.common import ensure_recent_data, print_strength_notes
from stamind.cli.runway import schedule_coverage
from stamind.cli.windows import has_selector as _has_selector, resolve_window
from stamind.cli.workouts.heads_up import (
    generate_dates, print_send_notice, replacing_unsent,
)
from stamind.cli.workouts.session_line import (
    line_markers, prescription_lines, print_marker_legend, workout_line,
)
from stamind.cli.workouts.strength_only import generate_strength_only, strength_span


def _confirm_regeneration(span_start: str, span_end: str, fresh: bool) -> bool:
    """Gates the LLM call: a regen ultimately replaces the plan across the span, so name
    what is at stake before spending it (README §"Steering the plan"). Nothing is archived
    here — the proposal is shown first and `_confirm_apply` owns the write.

    Returns True when there is nothing live to lose or the athlete confirmed."""
    live = runtime.db.get_workouts(start_date=span_start, end_date=span_end)
    if not live:
        return True

    # The week planner has to account for the near days one by one, so a rewrite of them is not
    # the blanket archive the rest of the span is (DESIGN_plan_change_continuity.md §4).
    # `--fresh` drops that hold, and a span that opens after the held days has none in it.
    # Ask where the window ends rather than deriving that from its length a second time.
    days = 0 if fresh else settings.commitment_days()
    window_end = None if fresh else settings.commitment_end(_today_str())
    if window_end is None or span_start > window_end:
        days = 0
    committed = (
        f" The next {days} day(s) are yours: the coach must answer for each session "
        f"standing in them, and you see what it did before anything is written."
        if days else ""
    )
    return runtime.prompt.confirm(
        wrap_text(
            f"You already have {len(live)} workout(s) planned in this span "
            f"({fmt_date(live[0]['date'])} → {fmt_date(live[-1]['date'])}). "
            f"Regenerating rebuilds {fmt_date(span_start)} → {fmt_date(span_end)} at the "
            f"cost of one LLM call, and archives them if you accept the result; "
            f"{cmd('workout rollback')} restores them.{committed} Regenerate?"
        ),
        danger=True,
    )


def _confirm_apply(proposal: GenerateProposal) -> bool:
    """Gates the write, once the athlete has read the proposed sessions."""
    # A kept session is already live and is not rewritten, so it is not among what this
    # archives. Every kept slot is in `displaced` by construction, so subtracting is
    # exact — and the danger prompt must not overstate the loss.
    kept = sum(1 for w in proposal.workouts if w.get('keep'))
    held = (
        f" {kept} session(s) you were already told about are kept exactly as they are."
        if kept else ""
    )
    displaced = len(proposal.displaced) - kept
    if displaced <= 0:
        return runtime.prompt.confirm(
            wrap_text(
                f"Schedule these {len(proposal.workouts)} workout(s) and push them to "
                f"Google Calendar?{held}"
            )
        )
    return runtime.prompt.confirm(
        wrap_text(
            f"Schedule these {len(proposal.workouts)} workout(s) and push them to Google "
            f"Calendar? This archives the {displaced} session(s) currently planned from "
            f"{fmt_date(proposal.gen_start)} to {fmt_date(proposal.gen_end)} and deletes "
            f"their Calendar events; {cmd('workout rollback')} restores them.{held}"
        ),
        danger=True,
    )


def _preferred_macro_id(args: argparse.Namespace) -> Optional[int]:
    """The plan `-M` names, when it names exactly one — the tiebreaker for two plans
    covering the same days. A bare `-M` (the active plan) and a range name no single
    winner, so both leave the choice to the newest-plan rule."""
    rng = getattr(args, 'macro_range', None)
    if rng is None or rng.current:
        return None
    return rng.start if rng.start is not None and rng.start == rng.end else None


def _confirm_out_of_date_plans(
    start_date: str, end_date: str, prefer_macro_id: Optional[int], force: bool
) -> bool:
    """Warns when a plan governing this horizon was generated from inputs that have since
    changed. Read off the dates, like the generation itself, so a horizon long enough to
    cross from one goal's plan into the next checks both. Returns False to stop."""
    mesocycles, _ = runtime.db.get_governing_mesocycles(
        start_date, end_date, prefer_macro_id=prefer_macro_id
    )
    for macro_id in dict.fromkeys(b['macrocycle_id'] for b in mesocycles):
        macro = runtime.db.get_macrocycle(macro_id)
        if not macro:
            continue
        change_reason = staleness.reason(macro)
        if not change_reason:
            continue
        warning = (
            "Generating workouts using the out-of-date plan might result in incorrect "
            "training targets. It is highly recommended to run "
            + cmd("plan generate") + " first."
        )
        if force:
            notice(
                f"Caution: a plan-shaping input has changed since the active "
                f"periodization plan was generated ({change_reason}). {warning} "
                "Proceeding anyway (--force)."
            )
            continue
        # Same prompt as `plan generate` asks with, so the two questions cannot drift
        # (DESIGN_plan_staleness.md §10). Proceeding is the "keep" answer here, so the
        # default follows the verdict call's read the other way round.
        reshaping = staleness.explain(change_reason, macro)
        if not runtime.prompt.confirm(
            yellow(warning + " Proceed anyway?"), default=reshaping is False,
        ):
            notice(
                "Workout generation cancelled. Please run "
                + cmd("plan generate") + " first.",
            )
            return False
        else:
            # Confirming accepts the out-of-date plan, so stamp the current config;
            # --force only skips the question and leaves the warning live for next run.
            print(wrap_text(
                "Proceeding with the out-of-date plan. It is now recorded against your "
                "current profile and thresholds, so this warning won't repeat."
            ))
            runtime.coach_service.stamp(macro)
    return True


def _resolve_span(args: argparse.Namespace) -> Optional[tuple[str, str]]:
    """The days this run rebuilds: both ends of whatever `-d`/`-m`/`-M`/`-g` selected.

    An unselected start is the day after the schedule stops (today once it has run out)
    and an unselected end is the config horizon, so the span is always bounded
    (DESIGN_cli_selectors.md §8). None when the selection is entirely behind us — a mesocycle
    that has already run is history, and silently regenerating today instead is not what
    was asked for — or when the plan is already covered to its last day."""
    today = _today_str()
    start_date, end_date = resolve_window(args)
    if end_date and end_date < today:
        notice(
            f"That selection ends on {fmt_date(end_date)}, before today — there is "
            f"nothing ahead of it to generate.", red,
        )
        return None
    # With nothing selected, generation carries the schedule on from where it stops
    # rather than rewriting the days it already covers (§8). Only this case: every
    # selector fills its own start, forward-direction, before this runs.
    if start_date is None:
        covered, plan_end = schedule_coverage()
        if covered and covered >= today:
            if plan_end and covered >= plan_end:
                notice(
                    f"The schedule already covers your plan through its last day "
                    f"({fmt_date(plan_end)}) — there is nothing further to generate.",
                    red,
                )
                return None
            start_date = shift(covered, 1)
    span_start = max(start_date or today, today)
    span_end = end_date or shift(
        span_start, config.workout_generation_span_days - 1
    )
    return span_start, span_end


def _warn_span_change(span_start: str, span_end: str) -> None:
    """Names the days this run no longer touches, now that the selectors bound BOTH ends
    of the span instead of only its end (DESIGN_cli_selectors.md §8).

    Transitional, and only for a selected span: it fires when the old reading and the new
    one differ. An unselected run opens after the covered days by rule, so its caller does
    not ask."""
    today = _today_str()
    tail = runtime.db.get_workouts(start_date=shift(span_end, 1))
    if span_start <= today and not tail:
        return

    lead = (
        "Note: generation now rebuilds a bounded span and leaves every day outside it "
        "alone — -d/-m/-M/-g name both of its ends. "
    )
    if span_start > today:
        lead += (
            f"This run rebuilds {fmt_date(span_start)} → {fmt_date(span_end)}; before, it "
            f"rebuilt today → {fmt_date(span_end)} and cancelled every session after that."
        )
    else:
        lead += (
            f"This run rebuilds today → {fmt_date(span_end)} and stops there; before, it "
            "also cancelled every session after that."
        )
    notice(lead)
    if span_start > today:
        notice(
            f"  - {fmt_date(today)} → {fmt_date(shift(span_start, -1))} keeps the "
            f"sessions it already has.",
        )
    if tail:
        notice(
            f"  - The {len(tail)} session(s) after {fmt_date(span_end)} keep their place "
            f"instead of being cancelled.",
        )
    if span_start > today:
        notice(
            "  Pass " + cmd(keep_whole(f"-d today..{span_end}"), quote=False)
            + " to rebuild from today again.",
        )
    print()


def standing_outcome_words(line) -> str:
    """What this run does to a session the athlete was already told about (§4.5).

    A move names the day it went to, a revision the form it takes, and a removal says so;
    a session the week planner never named says that too, because its being kept is the
    app's doing and not a decision the week planner made."""
    if line.outcome == 'kept':
        return "kept" if line.mentioned else "kept (not mentioned by the coach)"
    if line.outcome == 'moved':
        return f"→ {fmt_date(line.becomes)}"
    if line.outcome == 'cancelled':
        return "→ cancelled"
    return f"→ {line.becomes}"


def print_standing_report(proposal) -> None:
    """The sessions the athlete was already told about, and what this run writes to each
    (DESIGN_plan_change_continuity.md §4.5). Silent when the run touches none of them —
    a bare `workout generate` extends into empty days."""
    if not proposal.standing:
        return
    if proposal.athlete_note:
        print(f"{bold('Your coach')}: {wrap_text(proposal.athlete_note)}")
        print_send_notice(generate_dates(proposal))
        print()
    window = (
        f" (through {fmt_date(proposal.commitment_end)})"
        if proposal.commitment_end else ""
    )
    print(bold(f"Sessions you were already told about{window}:"))
    rows = [
        (
            fmt_date(line.date),
            line.title,
            f"{line.duration_minutes}m" if line.duration_minutes else "",
            standing_outcome_words(line),
            line.reason,
        )
        for line in proposal.standing
    ]
    widths = [max(len(r[i]) for r in rows) for i in range(4)]
    for row in rows:
        cells = "  ".join(pad_visible(row[i], widths[i]) for i in range(4))
        line = f"  {cells}"
        if row[4]:
            line += f"  {gray(row[4])}"
        print(line.rstrip())
    print()


def print_generate_preview(proposal) -> bool:
    """The expert `workout generate` preview: the reasoning, then the proposed sessions.

    Returns False when the week planner proposed nothing, so the caller stops before the apply
    question. The companion form of this is CompanionRenderer.workout_generate_preview
    (DESIGN_render_persona.md §5)."""
    print(bold(cyan("\n=== WORKOUTS PROPOSED BY COACH ===")))
    print(f"{bold('Reasoning')}:\n{wrap_text(proposal.reasoning)}\n")
    if not proposal.workouts:
        notice("The coach proposed no sessions — nothing to apply.")
        return False

    print_standing_report(proposal)
    # The same one-line rendering as `workout list`, so the plan the athlete is asked
    # to accept reads exactly like the plan they will be living with.
    markers: set = set()
    for w in proposal.workouts:
        head = workout_line(w)
        markers |= line_markers(head)
        print(head)
        # What the one-line form leaves out: the kilograms of a gym day, the zones of any
        # other session. The same lines `workout list -v` draws.
        for line in prescription_lines(w):
            print(f"      {gray(line)}")
    print_strength_notes(proposal)
    print_marker_legend(markers)
    print()
    return True


def run_workout_generate(args: argparse.Namespace) -> None:
    """Executes the AI workout generation command based on active strategy.

    The span comes first because the replace question needs it: it is only worth asking
    when this run writes over days the unsent change wrote (DESIGN_change_heads_up.md §5)."""
    force = getattr(args, 'force', False)
    ensure_recent_data(
        no_pull=args.no_pull, force_pull=getattr(args, 'force_pull', False)
    )
    strength_only = getattr(args, 'strength_only', False)
    span = strength_span(args) if strength_only else _resolve_span(args)
    if span is None:
        return
    with replacing_unsent(skip=force, window=span) as replaced:
        # Untrue once a Replace has undone the earlier attempt; the way out says so
        # instead (§5).
        unchanged = "." if replaced else " — your schedule is unchanged."
        if strength_only:
            generate_strength_only(args, force, unchanged, span)
            return
        _generate(args, force, unchanged, span)


def _generate(
    args: argparse.Namespace, force: bool, unchanged: str, span: Tuple[str, str]
) -> None:
    span_start, span_end = span
    prefer_macro_id = _preferred_macro_id(args)
    # Only for a span the athlete bounded: the transitional notice is about selectors
    # naming both ends, and the default opening after the covered days is now the rule
    # rather than a deviation worth a note on every run (§8).
    if _has_selector(args):
        _warn_span_change(span_start, span_end)

    # The staleness check looks over the days about to be written.
    if not _confirm_out_of_date_plans(span_start, span_end, prefer_macro_id, force):
        return

    fresh = getattr(args, 'fresh', False)
    if not force and not _confirm_regeneration(span_start, span_end, fresh):
        notice(f"Workout generation cancelled{unchanged}")
        return

    proposal = runtime.coach_service.workout_generate(
        start_date=span_start, end_date=span_end, prefer_macro_id=prefer_macro_id,
        fresh=fresh,
    )
    if not runtime.render.workout_generate_preview(proposal):
        return

    if not force and not _confirm_apply(proposal):
        notice(f"Workouts discarded{unchanged}")
        return

    saved = runtime.coach_service.workout_generate_apply(
        proposal, verbose=getattr(args, 'verbose', False)
    )
    print(green(
        f"\nScheduled {len(saved)} workout(s) from {fmt_date(proposal.gen_start)} to "
        f"{fmt_date(proposal.gen_end)}."
    ))
    print(green(
        f"Run {cmd('workout rollback')} to undo this regeneration, or "
        f"{cmd('plan rollback')} to step the strategy back with it."
    ))
