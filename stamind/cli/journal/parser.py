"""Argparse wiring for the `journal` command group.

Each sub-parser binds its handler with set_defaults(func=...), so the flags and the
function that reads them are defined together.
"""
from stamind.cli.selectors import add_selector_args
from stamind.cli.journal.views import (
    DEFAULT_LIMIT, run_journal, run_journal_prune, run_journal_show,
)


def add_journal_parser(subparsers):
    # journal command & subparsers — the operator's view of what the app did
    # (DESIGN_logging.md §7).
    journal_parser = subparsers.add_parser(
        "journal",
        help="What this app did, and when: one line per command run",
        description=(
            "The operational record beside the training one: which command ran, from "
            "where, how long it took, what it called out to and how it ended. Runs are "
            "listed newest first; name a run's id (a unique prefix is enough) to read "
            "everything it wrote, including the traceback if it failed. The read-only "
            "views — 'list', 'show', 'status', 'journal', help — are left out unless -a "
            "asks for them, and each command line is clipped to the width of the screen "
            "unless -v asks for it. Kept for logging.retain_days and never read by the "
            "app itself."
        )
    )
    # Read-only at the top level, so a bare `journal` lists rather than printing help
    # (DESIGN_cli_noargs.md §a3).
    journal_parser.set_defaults(func=run_journal)
    # `sm journal 5a0e` is the short form of `sm journal show 5a0e`: `prune` stays a
    # real sub-command, which is what keeps it from being read as a run id (§7).
    journal_parser.set_defaults(_fallback_subcommand="show")
    journal_parser.add_argument(
        "-n", dest="limit", type=int, default=DEFAULT_LIMIT, metavar="N",
        help=f"How many runs to list (default {DEFAULT_LIMIT}; 0 for all)"
    )
    # `none`: each side of the window is bounded only where the athlete bounded it, so
    # `-d 2026-08-01..` reads as "everything since then" rather than being narrowed to a
    # default span. `-d 7d` is still the last seven days.
    add_selector_args(journal_parser, date=True, direction="none")
    journal_parser.add_argument(
        "--source", metavar="SRC",
        help="Only runs from one front-end: cli, repl, bot, push, route, web, test"
    )
    journal_parser.add_argument(
        # Not dest="command": that is the top-level sub-parser's own dest, and a
        # sub-parser's namespace is copied wholesale over its parent's.
        "--command", dest="command_filter", metavar="CMD",
        help="Only runs of one command, e.g. --command \"workout adapt\""
    )
    journal_parser.add_argument(
        "--failed", action="store_true",
        help="Only runs that failed, were killed, or logged a warning or an error"
    )
    journal_parser.add_argument(
        "-a", "--all", action="store_true", dest="show_all",
        help="Also list the read-only views: 'list', 'show', 'status', 'journal', help"
    )
    journal_parser.add_argument(
        "-v", "--verbose", action="store_true",
        help="Print command lines and warnings in full rather than clipped to the screen"
    )
    journal_parser.add_argument(
        "--cost", action="store_true",
        help="Roll the model calls up by model and by command instead of listing runs"
    )
    journal_parser.add_argument(
        "--follow", action="store_true",
        help="Print each new record as it lands, until Ctrl-C"
    )
    journal_subparsers = journal_parser.add_subparsers(
        dest="subcommand", help="Journal sub-commands"
    )

    # journal show
    journal_show = journal_subparsers.add_parser(
        "show",
        help="Everything one run wrote, found by id prefix",
        description=(
            "One run in full: where it ran, every event it recorded as an offset from "
            "its start, the LLM exchange files it produced, the traceback if it failed, "
            "and the runs it spawned. The id may be any unique prefix; an ambiguous one "
            "lists what it matched. Same as naming the id straight after 'journal'."
        )
    )
    journal_show.set_defaults(func=run_journal_show)
    journal_show.add_argument("run", metavar="RUN", help="Run id, or a unique prefix of one")

    # journal prune
    journal_prune = journal_subparsers.add_parser(
        "prune",
        help="Delete journal days and LLM exchanges past their retention now",
        description=(
            "Forces the sweep that otherwise runs at most once a day, off the first "
            "command to finish after midnight UTC. Deletes journal files older than "
            "logging.retain_days and LLM exchange files older than "
            "logging.retain_exchange_days; nothing else in either directory is touched."
        )
    )
    journal_prune.set_defaults(func=run_journal_prune)
