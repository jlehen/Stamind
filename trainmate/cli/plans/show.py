"""`plan show` and `plan keep`: the plan as it stands, and dismissing a staleness notice.

`print_plan` is what `ExpertRenderer.plan` delegates to (DESIGN_render_persona.md §7)."""
import argparse
from datetime import datetime
from typing import List

from trainmate import plan_versions, runtime
from trainmate.analytics.load import planned_load
from trainmate.text import (
    blue, bold, cmd, cyan, default_wrap_width, format_labeled_paragraph, gray, green, magenta, red,
    wrap_text, yellow,
)
from trainmate.output import notice
from trainmate.clock import fmt_date, today_date as _today_date
from trainmate.cli import staleness
from trainmate.cli.common import (
    print_feedback_notes, print_hanging, print_indented, print_segments,
)
from trainmate.cli.windows import resolve_goal


def _print_plan_feedback(macrocycle: dict, width: int) -> None:
    """The notes attached to the shown plan version (DESIGN_plan_feedback.md §8)."""
    notes = runtime.db.list_plan_feedback(macrocycle['id'])
    if not notes:
        return
    state = (
        "consumed by the successor version"
        if macrocycle.get('status') == 'superseded'
        else "pending — feeds the next " + cmd('plan generate')
    )
    print(bold("Athlete Feedback") + f" ({gray(state)}):")
    print_feedback_notes(notes, width, indent="  ")
    print()


def _print_constraint_entry(e: dict, width: int) -> None:
    """One constraint line under a "Constraints considered" heading.

    Snapshots are historical JSON, so tolerate three shapes: the current one (a `rest`
    flag), the pre-rev-6 constraint (binding/sport/type), and the original lifeevent
    (event_type/impact_description). Read whichever is present.
    """
    if 'rest' in e:
        enforcement = "no training" if e.get('rest') else "advisory"
    else:
        enforcement = e.get('binding') or ''
    label = e.get('type') or e.get('event_type') or ''
    sport = e.get('sport')
    tags = " ".join(
        t for t in (
            label,
            enforcement,
            (f"[{sport}]" if sport else ""),
        ) if t
    )
    pad = print_hanging(
        f"  - [Constraint ID: {e.get('id')}] ", e.get('title', ''), width, cyan
    )
    print_segments(
        pad,
        [
            tags,
            f"{cyan(fmt_date(e.get('start_date')))} -> "
            f"{cyan(fmt_date(e.get('end_date')))}",
        ],
        width,
    )
    detail = e.get('description') or e.get('impact_description')
    if detail:
        print_indented(detail, pad, width, gray)


def _print_considered_inputs(macrocycle: dict) -> None:
    """Prints the goals, constraints and threshold anchors the plan was generated from."""
    goals, events, all_events, thresholds = plan_versions.input_snapshots(macrocycle)
    if goals is None and events is None and thresholds is None:
        print(gray("Inputs considered: not recorded (plan predates input snapshots)."))
        print()
        return

    goals, events = goals or [], events or []
    width = default_wrap_width()

    print(bold("Goals considered:"))
    if goals:
        for g in goals:
            sport = (g.get('sport_type') or '').upper()
            pad = print_hanging(
                f"  - [Goal ID: {g.get('id')}] ", g.get('title', ''), width, cyan
            )
            print_segments(
                pad,
                [
                    magenta(sport),
                    cyan(fmt_date(g.get('target_date'))),
                ],
                width,
            )
            if g.get('description'):
                print_indented(g['description'], pad, width, gray)
    else:
        print(f"  {gray('None')}")

    # `events` is only the replan=1 subset; `all_events` is every constraint the prompt
    # actually saw. Split the latter so an active advisory one is never silently dropped
    # from the render just because it didn't trigger a replan (DESIGN_constraints.md §7).
    tactical = [e for e in all_events if not e.get('replan')] if all_events is not None else None

    print(bold("Constraints considered (plan-shaping):"))
    if events:
        for e in events:
            _print_constraint_entry(e, width)
    else:
        print(f"  {gray('None')}")

    if tactical is not None:
        print(bold("Also active (tactical — did not trigger replan):"))
        if tactical:
            for e in tactical:
                _print_constraint_entry(e, width)
        else:
            print(f"  {gray('None')}")

    # The effective threshold anchors the plan prescribed against; drift past
    # `coach.threshold_replan_pct` is what makes it stale (ARCHITECTURE §5, macrocycles).
    if thresholds is not None:
        print(bold("Thresholds considered:"))
        if thresholds:
            for key in sorted(thresholds):
                print(f"  - {key}: {cyan(f'{thresholds[key]:g}')}")
        else:
            print(f"  {gray('None recorded')}")
    print()


def _fmt_duration(minutes: float) -> str:
    """'8h20' / '45min' for the total duration of a mesocycle's workouts."""
    if minutes >= 60:
        return f"{int(minutes // 60)}h{int(minutes % 60):02d}"
    return f"{int(minutes)}min"


def _plan_workouts(macrocycle: dict) -> List[dict]:
    """Every revision the given plan version appended, live or since superseded.

    History rather than plan, so it reads the raw revisions instead of the live view: the
    question is what this version scheduled, including what a later one displaced
    (DESIGN_workout_revisions.md §5). Revisions carry the `macrocycle_id` of the version
    that created them; a database wholly predating that column has none, so its rows are
    matched on dates alone."""
    rows = runtime.db.get_plan_revisions()
    if any(w.get('macrocycle_id') is not None for w in rows):
        return [w for w in rows if w.get('macrocycle_id') == macrocycle['id']]
    return rows


def _print_mesocycle_workouts(
    meso: dict, workouts: List[dict], pad: str, width: int, detail: bool
) -> None:
    """Summarises (and with `detail`, lists) the workouts falling inside a mesocycle."""
    inside = [w for w in workouts if meso['start_date'] <= w['date'] <= meso['end_date']]
    if not inside:
        print(pad + gray("no workouts generated"))
        return
    minutes = sum(w.get('duration_minutes') or 0 for w in inside)
    load = sum(planned_load(w) for w in inside)
    print(pad + gray(
        f"{len(inside)} workouts · {_fmt_duration(minutes)} · load {load:.0f}"
    ))
    if not detail:
        return
    for w in inside:
        tail = [f"{w.get('duration_minutes') or 0:.0f}min", f"load {planned_load(w):.0f}"]
        if not w.get('live'):
            tail.append("superseded")
        elif w.get('void'):
            tail.append("cancelled")
        print_hanging(
            f"{pad}  {cyan(fmt_date(w['date']))} ",
            f"[{w['sport_type']}] {w.get('title') or ''} ({' · '.join(tail)})", width, gray,
        )


def run_plan_show(args: argparse.Namespace) -> None:
    """Displays the training macrocycle(s) and mesocycles periodization timeline."""
    # The empty state `plan show` alone owns. `resolve_goal` below would say the same
    # thing one line later, but it also serves `plan versions`, `plan diff`, `plan
    # rollback` and `plan feedback`, where the companion sentence is the wrong one
    # (DESIGN_render_persona.md §5).
    if (args.goal_id is None and not getattr(args, 'all', False)
            and not runtime.db.upcoming_objectives()):
        runtime.render.no_upcoming_goal()
        return
    if getattr(args, 'all', False):
        if args.goal_id is not None or getattr(args, 'macrocycle_id', None) is not None:
            notice("Error: --all cannot be combined with --goal or --macrocycle.", red)
            return
        goals = sorted(runtime.db.get_objectives(), key=lambda g: str(g['target_date']))
        planned = [(g, runtime.db.get_macrocycle_for_objective(g['id'])) for g in goals]
        planned = [(g, m) for g, m in planned if m]
        if not planned:
            notice("No goal has a periodization plan yet.")
            print(green(f"Run {cmd('plan generate')} to create one."))
            return
        for goal, macrocycle in planned:
            runtime.render.plan(goal, macrocycle, args)
        return

    next_goal = resolve_goal(args.goal_id)
    if not next_goal:
        return

    version_id = getattr(args, 'macrocycle_id', None)
    if version_id is not None:
        macrocycle = runtime.db.get_macrocycle(version_id)
        if not macrocycle or macrocycle.get('objective_id') != next_goal['id']:
            notice(
                f"Plan version {version_id} does not belong to goal '{next_goal['title']}'.", red,
            )
            print(green(f"Run {cmd('plan versions')} to list this goal's plan versions."))
            return
    else:
        macrocycle = runtime.db.get_macrocycle_for_objective(next_goal['id'])
    if not macrocycle:
        runtime.render.no_plan_yet(next_goal)
        return

    runtime.render.plan(next_goal, macrocycle, args)


def print_plan(next_goal: dict, macrocycle: dict, args: argparse.Namespace) -> None:
    """Renders one plan version: header, strategy, snapshotted inputs, mesocycle timeline.

    The companion form of this is CompanionRenderer.plan (DESIGN_render_persona.md §5)."""
    mesocycles = runtime.db.get_mesocycles_for_macrocycle(macrocycle['id'])
    show_workouts = getattr(args, 'workouts', False)
    workouts = _plan_workouts(macrocycle)

    is_superseded = macrocycle.get('status') == 'superseded'
    if is_superseded:
        superseded_on = str(macrocycle.get('superseded_at', ''))[:10]
        header = (
            f"=== SUPERSEDED MACROCYCLE STRATEGY [Macrocycle ID: {macrocycle['id']}]"
            + (f" superseded {fmt_date(superseded_on)}" if superseded_on else "")
            + " ==="
        )
        print(bold(yellow("\n" + header)))
        notice(
            "This is a past version, kept for rollback. Run "
            + cmd(f"plan rollback --macrocycle {macrocycle['id']}") + " to restore it.",
        )
    else:
        print(bold(cyan(
            f"\n=== ACTIVE MACROCYCLE STRATEGY [Macrocycle ID: {macrocycle['id']}] ==="
        )))
    width = default_wrap_width()
    sport_str = next_goal['sport_type'].upper()
    obj_pad = print_hanging(
        f"{bold('Planned for')} [Goal ID: {next_goal['id']}]: ",
        next_goal['title'], width, cyan,
    )
    print_segments(
        obj_pad,
        [magenta(sport_str), cyan(fmt_date(next_goal['target_date']))],
        width,
    )
    print(format_labeled_paragraph(f"{bold('Macrocycle Strategy')}:", macrocycle['strategy']))
    print()
    _print_plan_feedback(macrocycle, width)
    _print_considered_inputs(macrocycle)
    # Right under the inputs it contradicts, and only for the version in force: a
    # superseded one is out of date by definition (DESIGN_plan_staleness.md §9). Expert
    # only — the companion body is `simple_plan_lines`, and a replan is operator work.
    if not is_superseded:
        change_reason = staleness.reason(macrocycle)
        if change_reason:
            staleness.report(change_reason, macrocycle)
    print(bold("Mesocycle Timeline:"))
    
    today = _today_date()
    
    for m in mesocycles:
        start = datetime.strptime(m['start_date'], "%Y-%m-%d").date()
        end = datetime.strptime(m['end_date'], "%Y-%m-%d").date()
        
        total_days = (end - start).days + 1
        if total_days <= 0:
            total_days = 1
            
        # The bar shares its line with the day counter, so it has to shrink on a
        # narrow client rather than pushing the counter past the wrap width.
        bar_length = min(20, max(8, width - 30))
        is_active = start <= today <= end
        if end < today:
            status_str = gray("[DONE]  ")
            bar = gray("=" * bar_length)
            extra = ""
        elif is_active:
            status_str = green("[ACTIVE]")
            days_passed = (today - start).days + 1
            days_passed = max(1, min(days_passed, total_days))
            filled = round(bar_length * days_passed / total_days)
            filled = max(0, min(filled, bar_length))
            bar = green("=" * filled) + gray("." * (bar_length - filled))
            extra = green(f" Day {days_passed}/{total_days}")
        else:
            status_str = blue("[FUTURE]")
            bar = gray("." * bar_length)
            extra = ""

        if total_days >= 7:
            weeks = total_days / 7
            if weeks.is_integer():
                duration_desc = f"{int(weeks)} weeks"
            else:
                duration_desc = f"{weeks:.1f} weeks"
        else:
            duration_desc = f"{total_days} days"

        prefix = green("|->") if is_active else "|--"
        pad = print_hanging(
            f"{prefix} {status_str} ", m['name'], width, green if is_active else None
        )
        print_segments(
            pad,
            [
                f"[Mesocycle ID: {m['id']}]",
                f"{cyan(fmt_date(m['start_date']))} -> {cyan(fmt_date(m['end_date']))}",
                duration_desc,
                (f"phase {m['phase']}" if m.get('phase') else ""),
            ],
            width,
        )
        print(f"{pad}[{bar}]{extra}")
        _print_mesocycle_workouts(m, workouts, pad, width, show_workouts)
        print_indented(m['focus'], pad, width)
        print(pad + gray("-" * min(40, max(10, width - len(pad)))))


def run_plan_keep(args: argparse.Namespace) -> None:
    """Records the current inputs against the active plan, without regenerating it: the
    "that was a wording tweak" answer, reachable without a strategy call
    (DESIGN_plan_staleness.md §9)."""
    goal = resolve_goal(getattr(args, 'goal_id', None))
    if not goal:
        return

    macrocycle = runtime.db.get_macrocycle_for_objective(goal['id'])
    if not macrocycle:
        runtime.render.no_plan_yet(goal)
        return

    change_reason = staleness.reason(macrocycle)
    if not change_reason:
        notice("This plan already reflects your current inputs — nothing to keep.")
        return

    print(f"\n{bold('Changed since this plan was generated')}: {change_reason}")
    staleness.print_diff(macrocycle)
    print(green(wrap_text(staleness.kept_line())))
    runtime.coach_service.stamp(macrocycle)
    print(gray(wrap_text(
        f"Your next {cmd('workout generate')} still picks the change up."
    )))
