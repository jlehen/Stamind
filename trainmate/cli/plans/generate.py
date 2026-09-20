"""`plan generate`: one strategy call per goal named, previewed, then applied on a `y`.

The preview printing is here rather than in the coach service, so the service returns a
proposal and the CLI says it out loud (DESIGN_render_persona.md §7)."""
import argparse
import sys
from typing import Any, Dict, List, Optional, Tuple

from trainmate import runtime
from trainmate.text import (
    bold, cmd, cyan, default_wrap_width, format_labeled_paragraph, green, red, wrap_text,
)
from trainmate.output import aside, notice, step, warn
from trainmate.clock import fmt_date
from trainmate.cli import staleness
from trainmate.cli.common import add_feedback_note, ensure_recent_data
from trainmate.cli.windows import goal_span_start, resolve_goal


def _goals_in_range(rng) -> Optional[list]:
    """Every upcoming goal a `-g` range covers, chronologically.

    The range runs over the goal TIMELINE rather than over row IDs, so `..2` is every goal
    falling on or before goal 2's target date (DESIGN_cli_selectors.md §9). None when an
    ID does not resolve — the reason is printed here."""
    bounds = []
    for goal_id in (rng.start, rng.end):
        if goal_id is None:
            bounds.append(None)
            continue
        goal = runtime.db.get_objective(goal_id)
        if not goal:
            notice(f"Goal with ID {goal_id} not found.", red)
            return None
        bounds.append(str(goal['target_date']))
    start, end = bounds
    goals = [
        g for g in runtime.db.upcoming_objectives()
        if (start is None or str(g['target_date']) >= start)
        and (end is None or str(g['target_date']) <= end)
    ]
    goals.sort(key=lambda g: (str(g['target_date']), g['id']))
    return goals


def _plan_targets(args: argparse.Namespace) -> Optional[list]:
    """The goals `plan generate` plans for, chronologically, each paired with the day its
    own plan window opens.

    `-g` reads as the shared range grammar does (DESIGN_cli_selectors.md §9): one goal
    named plans that goal alone, a range plans every goal it covers — `-g ..2` is
    "everything through goal 2", which is one strategy call per goal falling in it. The
    no-flag default is `(None, None)`: the service picks the next goal itself. None when
    the selection resolves to nothing, with the reason already printed."""
    rng = getattr(args, "goal_range", None)
    if rng is None:
        return [(None, None)]
    if rng.current:
        goal = runtime.db.get_active_objective()
        return [((goal['id'] if goal else None), goal_span_start(goal))]
    if rng.start is not None and rng.start == rng.end:
        # One ID reaches any non-archived goal, a past one included, as it always did —
        # only a range is restricted to what is still ahead.
        goal = runtime.db.get_objective(rng.start)
        if not goal:
            notice(f"Goal with ID {rng.start} not found.", red)
            return None
        return [(goal['id'], goal_span_start(goal))]
    goals = _goals_in_range(rng)
    if goals is None:
        return None
    if not goals:
        notice("No upcoming goal falls in that range — nothing to plan.")
        return None
    return [(g['id'], goal_span_start(g)) for g in goals]


def _announce_targets(targets: list) -> None:
    """Names the goals a range resolved to, and their order, before the first strategy
    call is spent (DESIGN_cli_selectors.md §9)."""
    named = []
    for goal_id, _ in targets:
        goal = runtime.db.get_objective(goal_id) if goal_id is not None else None
        if goal:
            named.append(f"{goal['title']} ({fmt_date(goal['target_date'])})")
    step(wrap_text(
        f"Planning {len(targets)} goals in date order, one strategy call each: "
        + "; ".join(named) + "."
    ))


def _file_generate_feedback(text: str, targets: list) -> bool:
    """`plan generate --feedback`: files the note exactly as `plan feedback "TEXT"` would, so
    the strategy call reads it with the rest of the pending log (DESIGN_plan_feedback.md §4).
    False, with the reason printed, when there is no single plan to file it to."""
    if not text.strip():
        notice("Error: the note is empty; nothing was saved.", red)
        return False
    if len(targets) != 1:
        notice("Error: a note goes to one plan. Name one goal with -g, not a range.", red)
        return False
    goal = resolve_goal(targets[0][0])
    if not goal:
        return False
    macro = runtime.db.get_macrocycle_for_objective(goal['id'])
    if not macro:
        edit = cmd(f"goal edit {goal['id']} --desc \"…\"")
        notice(
            f"Error: '{goal['title']}' has no plan yet, so there is no plan to give "
            f"feedback on. What you want from the first plan goes in the goal's "
            f"description: {edit}.", red
        )
        return False
    add_feedback_note(macro, text.strip())
    return True


def _plan_banner(title: str, width: int) -> Tuple[str, str]:
    """The '=== TITLE ===' head line and its matching closing rule, kept inside the
    wrap width so a narrow client doesn't fold the rule onto a second line."""
    head = f"=== {title} ===" if len(title) + 8 <= width else wrap_text(title, width)
    return head, "=" * min(width, max(len(line) for line in head.split("\n")))


def print_prior_training_review(text: str, width: int) -> None:
    """Shows the planned-vs-actual review that goes to the model as prompt context.

    Printed verbatim: the review now carries column-aligned zone tables already wrapped
    to their own width, and re-wrapping would shred the alignment
    (DESIGN_intensity_distribution.md §6)."""
    head, rule = _plan_banner("PRIOR TRAINING REVIEW (planned vs actual)", width)
    print(cyan(bold(f"\n{head}")))
    print(text)
    print(cyan(bold(f"{rule}\n")))


def print_new_strategy(
    strategy: str, mesocycles: List[Dict[str, Any]], width: int
) -> None:
    """Shows the freshly generated plan for the apply/discard decision.

    Each mesocycle is a head line plus its focus indented underneath, matching
    `plan show`, rather than one long line the terminal breaks where it likes."""
    head, rule = _plan_banner("NEW PERIODIZATION STRATEGY (MACROCYCLE)", width)
    print(cyan(bold(f"\n{head}")))
    print(format_labeled_paragraph(bold("Overall Strategy:"), strategy, width))
    print()
    print(bold("Mesocycles:"))
    for m in mesocycles:
        mesocycle_head = wrap_text(
            f"- {m['name']} ({m['start_date']} to {m['end_date']})", width
        )
        print(format_labeled_paragraph(bold(mesocycle_head), m['focus'], width))
    print(cyan(bold(f"{rule}\n")))


def print_plan_generate_preview(proposal: dict) -> None:
    """The expert `plan generate` preview: the review the coach was shown, when the
    athlete asked to see it, then the strategy they are being asked to apply.

    It used to print from inside the coach service, which left the one command whose
    whole output is a preview with no persona seam — `workout generate`'s preview has
    gone through the renderer since DESIGN_render_persona.md §5."""
    width = default_wrap_width()
    if proposal.get('prior_training_review'):
        print_prior_training_review(proposal['prior_training_review'], width)
    elif proposal.get('has_prior_training'):
        aside(wrap_text(
            "A planned-vs-actual review of your past plans is feeding this "
            f"strategy. Pass {cmd('--show-llm-context')} to read what the coach "
            "is being shown."
        ))
    print_new_strategy(proposal['strategy'], proposal['mesocycles'], width)


def run_plan_generate(args: argparse.Namespace) -> None:
    """Executes the AI periodization strategy plan generation command."""
    # A clean slate is a regeneration by definition, so the staleness question below —
    # "an input changed, regenerate?" — is already answered.
    if args.fresh:
        args.force = True

    # Resolved before the Garmin pull, so an unknown goal ID fails without one.
    targets = _plan_targets(args)
    if targets is None:
        return
    feedback = getattr(args, 'feedback', None)
    if feedback is not None and not _file_generate_feedback(feedback, targets):
        sys.exit(1)

    # Make sure we have latest metrics cached
    ensure_recent_data(no_pull=args.no_pull, force_pull=getattr(args, 'force_pull', False))
    metrics = runtime.db.get_metrics_cache()
    if not metrics:
        warn("metrics cache is empty. Proceeding without Garmin metrics.")
        
    # First-run nudge: no reflect watermark means `data bootstrap` has never run, so
    # there are no history-derived coach learnings to inform the plan. Offer to seed
    # them before generating (skipped in non-interactive --auto mode).
    if runtime.db.get_sync_state("reflect") is None and not getattr(args, 'auto', False):
        if runtime.prompt.confirm(wrap_text(
            f"No training-history analysis found. Run {cmd('data bootstrap')} first "
            "to reconstruct past cycles and seed coach learnings?"
        )):
            runtime.coach_service.data_bootstrap(
                no_pull=args.no_pull, force_pull=getattr(args, 'force_pull', False)
            )

    if len(targets) == 1:
        _generate_one_plan(args, *targets[0])
        return

    # Each goal is its own strategy, its own preview and its own decision: declining one
    # does not stop the next, whose window is bounded by the goal dates either way (§9).
    _announce_targets(targets)
    for index, (goal_id, span_start) in enumerate(targets, start=1):
        goal = runtime.db.get_objective(goal_id) if goal_id is not None else None
        title = goal['title'] if goal else f"goal {goal_id}"
        print(bold(cyan(f"\n=== PLANNING {index}/{len(targets)}: {title} ===")))
        _generate_one_plan(args, goal_id, span_start)


def _generate_one_plan(
    args: argparse.Namespace, goal_id: Optional[int], span_start: Optional[str]
) -> None:
    """One goal's strategy: the staleness gate, the LLM call, the preview and the save.

    `force` is a local because the staleness gate raises it, and in a range that answer
    belongs to the goal it was asked about, not to the ones planned after it."""
    force = bool(args.force)

    # Bound before the branch: with no upcoming objectives the accept path below
    # still reads it, and an unbound name surfaced only as a NameError string.
    next_goal = None
    objectives = runtime.db.upcoming_objectives()
    if objectives:
        if goal_id is not None:
            target_goals = [o for o in objectives if o['id'] == goal_id]
            next_goal = target_goals[0] if target_goals else None
        else:
            objectives.sort(key=lambda x: str(x['target_date']))
            next_goal = objectives[0]
            # Name the defaulted goal so a bare `plan generate` isn't silent
            # about which objective it planned for (DESIGN_cli_noargs.md §b).
            step(wrap_text(
                f"No goal given — planning for your next goal: "
                f"{next_goal.get('title', '')} on {fmt_date(next_goal['target_date'])}."
            ))

        if next_goal:
            macro = runtime.db.get_macrocycle_for_objective(next_goal['id'])
            # Pending notes regenerate the plan whatever the answer, so the question would
            # be moot (DESIGN_plan_feedback.md §7).
            if macro and not runtime.db.list_plan_feedback(macro['id']):
                change_reason = staleness.reason(macro)
                if change_reason and not force:
                    if staleness.confirm_regenerate(change_reason, macro):
                        force = True
                    else:
                        print(wrap_text(staleness.kept_line()))
                        runtime.coach_service.stamp(macro)

    plan_kwargs = {'auto_apply': False}
    if goal_id is not None:
        plan_kwargs['objective_id'] = goal_id
    if span_start is not None:
        plan_kwargs['start_date'] = span_start
    proposal = runtime.coach_service.plan_generate(
        force=force, fresh=bool(args.fresh),
        show_context=getattr(args, 'show_llm_context', False), **plan_kwargs
    )
    mesocycles = proposal['mesocycles']

    if proposal['reused']:
        print(green(f"\nActive plan is up to date ({len(mesocycles)} mesocycles)."))
        return

    if proposal['goal'] is None and not mesocycles:
        # The service found nothing to plan for, and put the reason where a strategy
        # would go. Say it plainly: under a NEW PERIODIZATION STRATEGY banner it reads
        # as though the coach had written one. Both halves are needed — a proposal
        # that names no goal but does carry mesocycles is a real plan with nothing to
        # attach it to, which the apply step below reports in its own words.
        notice(proposal['strategy'])
        return

    runtime.render.plan_generate_preview(proposal)

    if getattr(args, 'auto', False):
        apply = True
    else:
        apply = runtime.prompt.confirm("Apply this new periodization strategy?")

    if apply:
        goal = proposal['goal'] or next_goal
        # plan_apply already no-ops on a missing goal, so let it own that decision
        # rather than re-deciding here, and report what it actually saved.
        # Pass the fingerprints taken when the strategy was generated: the athlete
        # may have edited a goal while reading the proposal, and recording that edit
        # as part of this plan would mark a stale plan current.
        saved_id = runtime.coach_service.plan_apply(
            goal['id'] if goal else None, proposal['strategy'], mesocycles,
            fingerprints=proposal.get('fingerprints'),
        )
        if saved_id is None:
            notice("\nNo goal to attach this plan to — nothing was saved.")
            return
        print(green(f"\nGenerated {len(mesocycles)} mesocycles. Save complete."))
        print(green(f"Run {cmd('workout generate')} to schedule workouts "
                    "based on this plan."))
    else:
        notice("\nPlan discarded.")
