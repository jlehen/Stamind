"""The two commands on the retrospective records (DESIGN_cycle_retrospective.md §8, §9).

`plan retrospective` shows the records of a goal, laid out like `plan show`. `plan retro
redo` has one record written again: the way out for a record that is wrong, a writer
prompt that was improved, or words that were corrected. It never deletes the record, and
the athlete is not asked again."""
import argparse
import sys

from stamind import cycle_records, runtime
from stamind.cli.common import (
    print_mesocycle_head, print_mesocycle_rule, print_plan_goal, print_retrospective,
)
from stamind.cli.windows import resolve_goal
from stamind.db.retrospectives import MESOCYCLE, PLAN
from stamind.output import fail, notice
from stamind.text import bold, cmd, cyan, default_wrap_width, gray, green, red


def run_plan_retrospective(args: argparse.Namespace) -> None:
    """Shows the retrospective records of a goal in the layout of `plan show -vv`, without
    the plan's own text: the record of the plan where the strategy stands, and the record
    of each mesocycle in its entry of the timeline (DESIGN_cycle_retrospective.md §8)."""
    goal = resolve_goal(args.goal_id)
    if not goal:
        return
    macrocycle = runtime.db.get_macrocycle_for_objective(goal['id'])
    if not macrocycle:
        runtime.render.no_plan_yet(goal)
        return

    width = default_wrap_width()
    print(bold(cyan(f"\n=== PLAN RETROSPECTIVE [Macrocycle ID: {macrocycle['id']}] ===")))
    print_plan_goal(goal, width)
    plans = runtime.db.get_retrospectives(goal['id'], PLAN)
    if not plans:
        print(f"{bold('Plan Retrospective')}:")
        print("  " + gray("no retrospective yet"))
    for record in plans:
        print_retrospective("Plan Retrospective", record, "", width, show_id=True)
    print()

    # A record is the mesocycle that starts on its first day (§3). A recorded mesocycle
    # is drawn from its record, so one that this plan version does not hold has an entry.
    mesocycles = {
        m['start_date']: m
        for m in runtime.db.get_mesocycles_for_macrocycle(macrocycle['id'])
    }
    records = {
        record['start_date']: record
        for record in runtime.db.get_retrospectives(goal['id'], MESOCYCLE)
    }
    print(bold("Mesocycle Timeline:"))
    for start in sorted(mesocycles.keys() | records.keys()):
        m, record = mesocycles.get(start), records.get(start)
        id_label = f"[Mesocycle ID: {m['id']}]" if m else "not in this plan version"
        pad = print_mesocycle_head(record or m, id_label, width)
        if record:
            print_retrospective("Retrospective", record, pad, width, show_id=True)
        else:
            print(pad + gray("no retrospective yet"))
        print_mesocycle_rule(pad, width)


def run_plan_retro(args: argparse.Namespace) -> None:
    """Replaces the athlete's words when asked to, then computes the numbers again and
    calls the retrospective writer at once. When the writer fails, the record keeps the
    lines and the sentence it held."""
    record = runtime.db.get_retrospective(args.id)
    if not record:
        notice(
            f"Retrospective with ID {args.id} not found. {cmd('plan retrospective')} "
            "shows the records of a goal with their IDs.", red,
        )
        sys.exit(1)

    if args.clear_words:
        runtime.db.set_retrospective_words(args.id, None)
    elif args.words is not None:
        words = args.words.strip()
        if not words:
            notice("Error: the words are empty. Use --clear-words to remove them.", red)
            sys.exit(1)
        runtime.db.set_retrospective_words(args.id, words)

    try:
        runtime.coach_service.write_retrospective(runtime.db.get_retrospective(args.id))
    except Exception as e:
        fail(f"The record was not written again, and keeps what it held: {e}")
        sys.exit(1)

    print(green(f"Retrospective {args.id} written again."))
    record = runtime.db.get_retrospective(args.id)
    print_retrospective(cycle_records.record_name(record), record, "", default_wrap_width())
