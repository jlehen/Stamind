"""The `journal` command family: reading the run journal back (DESIGN_logging.md §7).

`stamind/journal.py` owns what a record is and how it is written; this package reads the
files it wrote. It is `journal` and not `log` because `sm log` would read as the athlete's
training log, which is what the workouts already are (§5.2).

`runs` turns the records into one summary per run and filters them, `views` prints them,
and `parser` builds the sub-commands: `stamind_cli` imports `add_journal_parser` from
`parser`.
"""
