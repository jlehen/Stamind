"""`workout batches` and `workout rollback`: the only undo the schedule has.

Every command that wrote sessions is one row here, and undoing one puts the plan back the
way it was the moment before it ran (DESIGN_workout_revisions.md §10).
"""
import argparse
from stamind import runtime
from stamind.text import (
    bold, cmd, cyan, gray, green, pad_visible, red, truncate_visible, wrap_text, yellow,
)
from stamind.output import aside, notice
from stamind.clock import fmt_date, fmt_timestamp, today_str as _today_str
from stamind.cli.common import report_unhonored


def _change_line(label: str, change: dict) -> str:
    """One `workout batches` row: '<label>  <when>  <kind>  <n> workouts · <span>  plan …',
    then what the change was, cut short.

    Every change is listed, adapts and tweaks included, because every change is
    undoable now (DESIGN_workout_revisions.md §10). A change that appended nothing — an
    adapt that looked at the metrics and held — says so rather than being left out.

    A rollback gets no description: its stored one names a change by an internal number
    this list does not show. A change the athlete has not been told about says so
    (DESIGN_change_heads_up.md §8)."""
    when = fmt_timestamp(change['created_at'])
    if change['held']:
        count = gray("(held) — nothing changed")
        span = ""
    else:
        count = f"{change['workouts']} revision(s)"
        restorable = change.get('restorable')
        if restorable == 0:
            count += gray(" — all in the past")
        elif restorable is not None and restorable < change['workouts']:
            count += gray(f" ({restorable} upcoming)")
        span = f"{fmt_date(change['first_date'])} → {fmt_date(change['last_date'])}"
    macros = change.get('macrocycle_ids') or []
    plan = f"plan ID {', '.join(str(m) for m in macros)}" if macros else "unversioned"
    row = (
        f"{pad_visible(label, 5)} {pad_visible(when, 22)} "
        f"{pad_visible(change['kind'], 12)} {pad_visible(count, 32)} "
        f"{gray(span)}  {gray(plan)}"
    )
    if change.get('waiting'):
        row += f"  {yellow('not sent yet')}"
    summary = " ".join((change.get('summary') or "").split())
    if change['kind'] == 'rollback' or not summary:
        return row
    return row + "\n" + gray(wrap_text("      " + truncate_visible(summary, 200)))


def run_workout_batches(args: argparse.Namespace) -> None:
    """Lists the workout changes a `workout rollback` can undo."""
    today = _today_str()
    changes = runtime.db.get_workout_changes(from_date=today)

    print(bold(cyan("\n=== WORKOUT CHANGES ===")))
    if not changes:
        print(gray(
            "Nothing has written workouts yet — so there is nothing to roll back to."
        ))
        return
    print(gray(wrap_text(
        "Every command that wrote workouts, newest first. Undoing one puts the plan back "
        "the way it was the moment before it ran, which also undoes every change made "
        "after it."
    ) + "\n"))
    for i, change in enumerate(changes, start=1):
        print(_change_line(cyan(f"#{i}"), change))
    print()
    aside("Undo one with " + cmd("workout rollback [--batch N]")
         + " (defaults to #1, the newest). Numbering is positional and shifts after "
           "each change.",
         color_fn=gray)


def run_workout_rollback(args: argparse.Namespace) -> None:
    """Undoes a workout change — and every change made after it."""
    today = _today_str()
    changes = runtime.db.get_workout_changes(from_date=today)
    if not changes:
        notice("No workout changes to roll back — nothing has written workouts yet.")
        return

    index = getattr(args, 'batch', None) or 1
    if not 1 <= index <= len(changes):
        notice(
            f"No change #{index} — there {'is' if len(changes) == 1 else 'are'} "
            f"{len(changes)}.", red,
        )
        print(green(f"Run {cmd('workout batches')} to list them."))
        return
    target = changes[index - 1]

    if not getattr(args, 'yes', False):
        live = len(runtime.db.get_workouts(start_date=today))
        if not runtime.prompt.confirm(
            f"Undo change #{index} ({target['kind']}, {fmt_timestamp(target['created_at'])}) "
            f"and everything after it?\nThis puts the {live} currently planned "
            "session(s) from today onward back the way they were just before it ran, and "
            "updates Google Calendar. The active plan version is unchanged.",
            danger=True,
        ):
            print("Rollback cancelled.")
            return

    try:
        result = runtime.coach_service.workout_rollback(
            change_id=target['id'], verbose=getattr(args, 'verbose', False)
        )
    except ValueError as e:
        notice(str(e), red)
        return

    span = (
        f" ({fmt_date(result['first_date'])} → {fmt_date(result['last_date'])})"
        if result['first_date'] else ""
    )
    print(green(
        f"\nUndid change #{index} ({target['kind']}): restored "
        f"{result['restored_workouts']} session(s){span}."
    ))
    report_unhonored(result['unhonored'])
    print(green(f"Run {cmd('workout list')} to review the restored sessions."))
