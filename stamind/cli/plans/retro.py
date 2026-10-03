"""`plan retro redo`: has one retrospective record written again
(DESIGN_cycle_retrospective.md §9).

The way out for a record that is wrong, a writer prompt that was improved, or words that
were corrected. It never deletes the record, and the athlete is not asked again."""
import argparse
import sys

from stamind import runtime
from stamind.cli.common import print_retrospective
from stamind.output import fail, notice
from stamind.text import cmd, default_wrap_width, green, red


def run_plan_retro(args: argparse.Namespace) -> None:
    """Replaces the athlete's words when asked to, then computes the numbers again and
    calls the retrospective writer at once. When the writer fails, the record keeps the
    lines and the sentence it held."""
    record = runtime.db.get_retrospective(args.id)
    if not record:
        notice(
            f"Retrospective with ID {args.id} not found. {cmd('plan show')} lists the "
            "records of a goal with their IDs.", red,
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
    print_retrospective(runtime.db.get_retrospective(args.id), default_wrap_width())
