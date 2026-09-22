"""The version history of a plan: `plan versions`, `plan diff`, `plan rollback`,
`plan rm` and `plan wipe`.

A new plan supersedes its predecessor rather than overwriting it, so each of these reads
the lineage `stamind/plan_versions.py` builds (DESIGN_plan_rollback.md §6)."""
import argparse

from stamind import plan_versions, runtime
from stamind.text import (
    bold, cmd, cyan, default_wrap_width, gray, green, magenta, pad_visible, red, yellow,
)
from stamind.output import aside, notice
from stamind.clock import fmt_date, fmt_span
from stamind.cli.common import print_hanging, print_plan_cascade, print_segments, report_unhonored
from stamind.cli.windows import resolve_goal


def run_plan_versions(args: argparse.Namespace) -> None:
    """Lists every periodization plan version (active + superseded) for a goal."""
    goal = resolve_goal(getattr(args, 'goal_id', None))
    if not goal:
        return

    versions = runtime.db.get_macrocycle_versions(goal['id'])
    if not versions:
        notice(f"No periodization plan exists for goal '{goal['title']}'.")
        print(green(f"Run {cmd('plan generate')} to create one."))
        return

    sport_str = goal['sport_type'].upper()
    goal_tag = bold(f"[Goal ID: {goal['id']}]")
    print(bold(cyan("\n=== PLAN VERSIONS ===")))
    print(
        f"{goal_tag}: "
        f"{cyan(goal['title'])} ({magenta(sport_str)}) "
        f"on {cyan(fmt_date(goal['target_date']))}\n"
    )
    for v in versions:
        active = v.get('status') != 'superseded'
        created = str(v.get('created_at', ''))[:10]
        excerpt = " ".join((v.get('strategy') or "").split())
        if len(excerpt) > 70:
            excerpt = excerpt[:69] + "…"
        marker = green("●") if active else " "
        id_str = (green if active else str)(f"Macrocycle {v['id']}")
        if active:
            status = green("active")
        else:
            superseded = str(v.get('superseded_at', ''))[:10]
            status = gray("superseded" + (f" {fmt_date(superseded)}" if superseded else ""))
        gen = f"generated {fmt_date(created)}" if created else ""
        print(
            f"{marker} {pad_visible(id_str, 16)} {pad_visible(status, 28)} {gray(gen)}"
        )
        if excerpt:
            print(f"    {gray(excerpt)}")
    print()
    aside(
        "Restore a version with " + cmd("plan rollback --macrocycle <ID>")
        + ", inspect one with " + cmd("plan show --macrocycle <ID>")
        + ", or compare two with " + cmd("plan diff <ID> <ID>") + ".",
        color_fn=gray,
    )


def _print_change(marker: str, text: str, width: int, color_fn, indent: str = "  ") -> None:
    """One '+'/'-'/'~' diff line, wrapped with its continuation aligned past the marker."""
    print_hanging(f"{indent}{color_fn(marker)} ", text, width, color_fn)


def _print_prose_diff(
    prose: dict, width: int, full: bool, indent: str = "  "
) -> None:
    """Renders a `plan_versions.diff_prose` result. A strategy `plan generate` rewrote wholesale
    collapses to a one-line note unless `full` — the sentence lists would otherwise just
    reprint both versions in their entirety."""
    if not prose['changed']:
        print(f"{indent}{gray('unchanged')}")
        return
    if prose['rewritten'] and not full:
        _print_change(
            "~", f"rewritten ({prose['old_count']} sentences -> {prose['new_count']}); "
            f"pass --full for the sentence-level diff", width, yellow, indent=indent,
        )
        return
    for group in prose['groups']:
        for s in group['removed']:
            _print_change("-", s, width, red, indent=indent)
        for s in group['added']:
            _print_change("+", s, width, green, indent=indent)


def _print_mesocycles_diff(entries: list, width: int, full: bool) -> None:
    """Renders a `plan_versions.diff_mesocycles` result, skipping untouched mesocycles."""
    changed = [e for e in entries if e['change'] != 'unchanged']
    if not changed:
        print(f"  {gray('unchanged')}")
        return
    for e in changed:
        if e['change'] in ('added', 'removed'):
            added = e['change'] == 'added'
            label = (
                f"{e['name']} "
                f"({fmt_span(e['dates']['start'], e['dates']['end'], sep=' -> ')})"
            )
            _print_change("+" if added else "-", label, width, green if added else red)
            continue
        header = f"{e['from_name']}  =>  {e['name']}" if e['renamed'] else e['name']
        _print_change("~", header, width, yellow)
        if e['dates']:
            frm, to = e['dates']['from'], e['dates']['to']
            print(f"      dates {cyan(fmt_date(frm['start']))} -> {cyan(fmt_date(frm['end']))}"
                  f"\n         =>  {cyan(fmt_date(to['start']))} -> {cyan(fmt_date(to['end']))}")
        for f in e['fields']:
            print(f"      {f['field']}: {f['from'] or '—'}  =>  {f['to'] or '—'}")
        if e['focus']:
            print(f"      {gray('focus:')}")
            _print_prose_diff(e['focus'], width, full, indent="        ")


def _print_feedback_diff(entry: dict, width: int) -> None:
    """Renders a `plan_versions.diff_feedback` result: each version's own notes. Append-only
    logs are not prose-diffed — for adjacent versions, A's notes are what drove B (§8)."""
    for tag, notes in (("A", entry['from']), ("B", entry['to'])):
        print(f"  {bold(tag)}:")
        if not notes:
            print(f"    {gray('none')}")
            continue
        for n in notes:
            print_hanging(
                f"    {gray('[' + str(n['id']) + ']')} {cyan(fmt_date(n['date']))} "
                f"· {magenta(n['filing'] or 'plan-level')} · ",
                n['text'], width,
            )


def _print_missing_snapshot(missing: str) -> None:
    """Says which side lacks the snapshot, so a plan predating the column is never read
    as everything having been added or removed."""
    if missing == "both":
        print(f"  {gray('not recorded on either version')}")
        return
    side = "A" if missing == "old" else "B"
    print(f"  {gray(f'not recorded on {side} — that plan predates the snapshot')}")


def _print_records_diff(diff: dict, width: int, kind: str) -> None:
    """Renders a `plan_versions.diff_records` result (snapshotted goals or constraints).

    `kind` names the entity in each ID tag — both kinds share one screen."""
    if diff['missing']:
        _print_missing_snapshot(diff['missing'])
        return
    if not (diff['added'] or diff['removed'] or diff['changed']):
        print(f"  {gray('unchanged')}")
        return
    for rec in diff['removed']:
        _print_change(
            "-", f"[{kind} ID: {rec.get('id')}] {rec.get('title', '')}", width, red
        )
    for rec in diff['added']:
        _print_change(
            "+", f"[{kind} ID: {rec.get('id')}] {rec.get('title', '')}", width, green
        )
    for rec in diff['changed']:
        _print_change("~", f"[{kind} ID: {rec['id']}] {rec['title']}", width, yellow)
        for f in rec['fields']:
            print(f"      {f['field']}: {f['from']!r}  =>  {f['to']!r}")


def _print_thresholds_diff(diff: dict, width: int) -> None:
    """Renders a `plan_versions.diff_thresholds` result."""
    if diff['missing']:
        _print_missing_snapshot(diff['missing'])
        return
    if not (diff['added'] or diff['removed'] or diff['changed']):
        print(f"  {gray('unchanged')}")
        return
    for t in diff['removed']:
        _print_change("-", f"{t['key']}: {t['value']:g}", width, red)
    for t in diff['added']:
        _print_change("+", f"{t['key']}: {t['value']:g}", width, green)
    for t in diff['changed']:
        pct = f" ({t['pct']:+.1f}%)" if t['pct'] is not None else ""
        _print_change("~", f"{t['key']}: {t['from']:g}  =>  {t['to']:g}{pct}", width, yellow)


def _version_line(tag: str, macro: dict) -> str:
    """'A  Macrocycle 12  generated 2026-07-29 Wed  superseded 2026-07-31 Fri', for a
    diff header."""
    created = str(macro.get('created_at', ''))[:10]
    if macro.get('status') == 'superseded':
        superseded = str(macro.get('superseded_at', ''))[:10]
        state = gray("superseded" + (f" {fmt_date(superseded)}" if superseded else ""))
    else:
        state = green("active")
    gen = f"generated {fmt_date(created)}" if created else ""
    label = pad_visible('Macrocycle ' + str(macro['id']), 16)
    return f"  {bold(tag)}  {label} {gray(gen)}  {state}"


# The command that gets the athlete unstuck, per failure the version resolver reports.
_DIFF_ERROR_HINTS = {
    "no_active_plan": ("plan generate", "to create one."),
    "not_found": ("plan versions", "to list this goal's plan versions."),
}


def run_plan_diff(args: argparse.Namespace) -> None:
    """Compares two periodization plan versions field by field."""
    goal = resolve_goal(getattr(args, 'goal_id', None))
    if not goal:
        return
    old, new, error = plan_versions.resolve_versions(
        runtime.db, goal, args.version_a, args.version_b
    )
    if error:
        code, message = error
        print(red(message) if code in ("same_version", "not_found") else yellow(message))
        hint = _DIFF_ERROR_HINTS.get(code)
        if hint:
            print(green(f"Run {cmd(hint[0])} {hint[1]}"))
        return

    width = default_wrap_width()
    print(bold(cyan("\n=== PLAN DIFF ===")))
    goal_tag = bold(f"[Goal ID: {goal['id']}]")
    obj_pad = print_hanging(
        f"{goal_tag}: ", goal['title'], width, cyan,
    )
    print_segments(
        obj_pad,
        [magenta(goal['sport_type'].upper()), cyan(fmt_date(goal['target_date']))],
        width,
    )
    print(_version_line("A", old))
    print(_version_line("B", new))

    diff = plan_versions.diff_plans(
        old, new,
        runtime.db.get_mesocycles_for_macrocycle(old['id']),
        runtime.db.get_mesocycles_for_macrocycle(new['id']),
        runtime.db.list_plan_feedback(old['id']),
        runtime.db.list_plan_feedback(new['id']),
    )
    full = getattr(args, 'full', False)
    print(bold("\nStrategy:"))
    _print_prose_diff(diff['strategy'], width, full)
    print(bold("\nAthlete feedback:"))
    _print_feedback_diff(diff['feedback'], width)
    print(bold("\nMesocycles:"))
    _print_mesocycles_diff(diff['mesocycles'], width, full)
    print(bold("\nGoals considered:"))
    _print_records_diff(diff['goals'], width, "Goal")
    print(bold("\nConstraints considered:"))
    _print_records_diff(diff['constraints'], width, "Constraint")
    print(bold("\nThresholds considered:"))
    _print_thresholds_diff(diff['thresholds'], width)
    print()


def run_plan_rm(args: argparse.Namespace) -> None:
    """Deletes every periodization plan version a goal owns, superseded ones included.

    The inventory is printed first because the cascade reaches past the one version the
    athlete has in mind (DESIGN_cli_noargs.md §b1)."""
    goal = runtime.db.get_objective(args.id)
    if not goal:
        notice(f"Goal with ID {args.id} not found.", red)
        return

    macro = runtime.db.get_macrocycle_for_objective(args.id)
    if not macro:
        notice(f"No periodization plan exists for goal '{goal['title']}' (ID {args.id}).")
        return

    if not args.yes:
        notice(f"Removing the plan for goal '{goal['title']}' (ID {args.id}) deletes:")
        print_plan_cascade(args.id)
        print(gray(
            "To replace the plan reversibly instead, use "
            + cmd(f"plan generate --goal {args.id} --force") + "."
        ))
        if not runtime.prompt.confirm("Delete it anyway?", danger=True):
            print("Removal cancelled.")
            return

    runtime.coach_service.plan_rm(args.id)
    print(green(f"Periodization plan for goal '{goal['title']}' removed successfully."))

    # Warn about subsequent plans
    objectives = runtime.db.upcoming_objectives()
    subsequent_goals_with_plans = []
    for obj in objectives:
        if str(obj['target_date']) > str(goal['target_date']):
            if obj['id'] is not None:
                sub_macro = runtime.db.get_macrocycle_for_objective(obj['id'])
                if sub_macro:
                    subsequent_goals_with_plans.append(obj)

    if subsequent_goals_with_plans:
        notice(
            "\nCaution: The following subsequent active goals have existing plans that\n"
            "were aligned with the plan you just deleted. You may need to regenerate them\n"
            "so their dates align correctly (e.g. running "
            + cmd("plan generate --goal <ID> --force") + "):",
        )
        for sg in subsequent_goals_with_plans:
            notice(
                f" - ID {sg['id']}: '{sg['title']}' "
                f"(Target date: {fmt_date(sg['target_date'])})",
            )


def run_plan_wipe(args: argparse.Namespace) -> None:
    """Wipes all plans from the database after confirmation."""
    if not args.yes:
        if not runtime.prompt.confirm(
            "Are you sure you want to wipe all periodization plans?", danger=True
        ):
            print("Wipe cancelled.")
            return

    runtime.db.wipe_plans()
    print(green("All periodization plans wiped successfully."))


def run_plan_rollback(args: argparse.Namespace) -> None:
    """Restores a superseded periodization plan version (and its workouts)."""
    goal = resolve_goal(getattr(args, 'goal_id', None))
    if not goal:
        return

    versions = runtime.db.get_macrocycle_versions(goal['id'])
    superseded = [v for v in versions if v.get('status') == 'superseded']
    if not superseded:
        notice(f"Goal '{goal['title']}' has no earlier plan version to roll back to.")
        return

    # Determine the target version (default: chronologically previous).
    target_id = getattr(args, 'macrocycle_id', None)
    if target_id is None:
        prev = runtime.db.get_previous_macrocycle_version(goal['id'])
        target_id = prev['id'] if prev else None
    if target_id is None:
        notice(f"Goal '{goal['title']}' has no earlier plan version to roll back to.")
        return

    target = runtime.db.get_macrocycle(target_id)
    if not target or target.get('objective_id') != goal['id']:
        notice(f"Plan version {target_id} does not belong to goal '{goal['title']}'.", red)
        return

    if not getattr(args, 'yes', False):
        created = (
            fmt_date(str(target.get('created_at', ''))[:10])
            if target.get('created_at') else '?'
        )
        if not runtime.prompt.confirm(
            f"Roll back the plan for '{goal['title']}' to the version generated "
            f"{created} (plan ID {target_id})?\nThis archives the current plan's "
            f"upcoming workouts and restores that version's on Google Calendar.",
            danger=True,
        ):
            print("Rollback cancelled.")
            return

    try:
        result = runtime.coach_service.plan_rollback(
            objective_id=goal['id'], target_macrocycle_id=target_id
        )
    except ValueError as e:
        notice(str(e), red)
        return

    print(green(
        f"\nRolled back '{goal['title']}' to plan ID {result['to']['id']} "
        f"(was {result['from']['id']})."
    ))
    print(
        f"Restored {result['restored_workouts']} workout(s) from the superseded plan; "
        "Google Calendar updated."
    )
    report_unhonored(result['unhonored'])
    print(green(f"Run {cmd('plan show')} to review the restored strategy."))
