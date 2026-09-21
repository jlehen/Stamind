"""`plan feedback`: the log of notes the next `plan generate` reads
(DESIGN_plan_feedback.md §4).

Appending, listing, pruning, and the `--replan` shortcut that files a note and runs
`plan generate` in one command."""
import argparse
import sys
from typing import Optional

from stamind import runtime
from stamind.text import bold, cmd, default_wrap_width, gray, green, red
from stamind.output import aside, notice
from stamind.cli.common import add_feedback_note, print_feedback_notes
from stamind.cli.plans.generate import run_plan_generate
from stamind.cli.selectors import IdRange, SelectorError, resolve_meso_atom
from stamind.cli.windows import resolve_goal


# `--rm` given without an ID: argparse hands the const through untouched, so the handler
# can answer it with DESIGN_cli_noargs.md §a's missing-argument treatment rather than
# argparse's bare "expected one argument".
RM_NO_ID = object()


def _feedback_list(goal: dict, macro: dict) -> None:
    """The bare run: the pending log, read-only (DESIGN_cli_noargs.md bucket 1)."""
    notes = runtime.db.list_plan_feedback(macro['id'])
    if not notes:
        print(gray(
            f"No feedback pending on the plan for '{goal['title']}'. Add a note with "
            + cmd('plan feedback "…"') + "."
        ))
        return
    print(bold(f"Plan feedback for '{goal['title']}'") + gray(
        f" ({len(notes)} pending — feeds the next {cmd('plan generate')})"
    ) + ":")
    print_feedback_notes(notes, default_wrap_width())


def _feedback_rm(args: argparse.Namespace) -> None:
    """Deletes one note. Rewording is `--rm` + re-add, which is why there is no --edit."""
    if args.rm is RM_NO_ID:
        args._parser.error("the following arguments are required: --rm ID")
    note = runtime.db.get_plan_feedback(args.rm)
    if not note:
        notice(f"No feedback note with ID {args.rm}.", red)
        sys.exit(1)
    print_feedback_notes([note], default_wrap_width())
    if not args.yes and not runtime.prompt.confirm("Delete this note?", danger=True):
        print("Removal cancelled.")
        return
    runtime.db.rm_plan_feedback(args.rm)
    print(green(f"Removed feedback note {args.rm}."))


def _feedback_mesocycles(goal_id: Optional[int], macro: dict) -> list:
    """What `-m` may name: with `-g`, that goal's plan; without it, every upcoming goal's
    active plan, soonest first, so the mesocycle picks the plan (DESIGN_plan_feedback.md §4)."""
    if goal_id is not None:
        return runtime.db.get_mesocycles_for_macrocycle(macro['id'])
    mesocycles = []
    for goal in runtime.db.upcoming_objectives():
        plan = runtime.db.get_macrocycle_for_objective(goal['id'])
        if plan:
            mesocycles += [dict(m, goal_title=goal['title'])
                           for m in runtime.db.get_mesocycles_for_macrocycle(plan['id'])]
    return mesocycles


def _meso_owner_hint(atom, goal: dict) -> str:
    """Where a rejected mesocycle ID actually lives — another goal's plan, or a
    superseded version of this one (DESIGN_plan_feedback.md §4/§5)."""
    if not (isinstance(atom, str) and atom.strip().isdigit()):
        return ""
    meso = runtime.db.get_mesocycle(int(atom))
    macro = runtime.db.get_macrocycle(meso['macrocycle_id']) if meso else None
    if not macro:
        return ""
    if macro.get('status') == 'superseded':
        return (f"\nMesocycle {atom} ('{meso['name']}') belongs to a superseded version of "
                "this plan, and a note can only steer the active one.")
    owner = runtime.db.get_objective(macro['objective_id'])
    if not owner or owner['id'] == goal['id']:
        return ""
    return (f"\nMesocycle {atom} ('{meso['name']}') belongs to the plan for "
            f"'{owner['title']}' — reach it with " + cmd("-g " + str(owner['id'])) + ".")


def _feedback_replan(goal: dict) -> None:
    """Runs the regeneration flow right after saving, so feedback → new plan is one
    command. It does not imply --force and does not need to: pending notes are a plan
    input, so the gate lets the regeneration through (§7). The preview and its human `y`
    still stand, per the constraints precedent (stamind/cli/constraints.py)."""
    print(green("Regenerating the periodization plan around your feedback..."))
    run_plan_generate(argparse.Namespace(
        no_pull=False, force_pull=False, auto=False,
        goal_range=IdRange(start=goal['id'], end=goal['id']), force=False, fresh=False,
    ))
    aside("If you applied the new plan, run " + cmd("workout generate")
          + " to schedule it.")


def run_plan_feedback(args: argparse.Namespace) -> None:
    """Appends to — or lists, or prunes — the plan's feedback log
    (DESIGN_plan_feedback.md §4).

    No LLM anywhere here: capture is an INSERT, and the one consumer of the result is the
    regeneration, which reads the whole log and does the understanding there (§2)."""
    goal = resolve_goal(args.goal_id)
    if not goal:
        sys.exit(1)
    macro = runtime.db.get_macrocycle_for_objective(goal['id'])
    if not macro:
        notice(f"No active periodization plan exists for goal '{goal['title']}'.")
        print(green(f"Run {cmd('plan generate')} to create one."))
        sys.exit(1)

    if args.rm is not None:
        if args.text or args.meso is not None or args.replan:
            notice("Error: --rm deletes one note by ID; it takes nothing else.", red)
            sys.exit(1)
        _feedback_rm(args)
        return

    if args.text is not None and not args.text.strip():
        notice("Error: the note is empty; nothing was saved.", red)
        sys.exit(1)

    if args.text is None:
        if args.meso is not None or args.replan:
            notice("Error: give the note text — there is nothing to file yet.", red)
            sys.exit(1)
        _feedback_list(goal, macro)
        return

    # Filing to a superseded version cannot steer the next one, so the atom only ever sees
    # active plans' mesocycles (§5); the one it names decides which plan the note joins.
    meso = None
    if args.meso is not None:
        try:
            meso = resolve_meso_atom(args.meso, _feedback_mesocycles(args.goal_id, macro))
        except SelectorError as e:
            print(red(f"Error: {e}") + _meso_owner_hint(args.meso, goal))
            sys.exit(1)
        if meso['macrocycle_id'] != macro['id']:
            macro = runtime.db.get_macrocycle(meso['macrocycle_id'])
            goal = runtime.db.get_objective(macro['objective_id'])

    add_feedback_note(macro, args.text.strip(), meso)

    if args.replan:
        _feedback_replan(goal)
        return
    pending = len(runtime.db.list_plan_feedback(macro['id']))
    # A bare `plan generate` plans the soonest goal only; any other goal needs its -g.
    upcoming = runtime.db.upcoming_objectives()
    soonest = bool(upcoming) and upcoming[0]['id'] == goal['id']
    generate = "plan generate" if soonest else f"plan generate -g {goal['id']}"
    on_plan = "" if soonest else f" on the plan for '{goal['title']}'"
    aside(
        f"{pending} note{'s' if pending != 1 else ''} pending{on_plan} — "
        f"{'they feed' if pending != 1 else 'it feeds'} the next {cmd(generate)} "
        f"({cmd('--replan')} runs it now)."
    )
