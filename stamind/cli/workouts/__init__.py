"""The `workout` command family, one module per command.

`parser` builds the sub-commands and attaches each handler as `func=`, so nothing outside
this package names a handler: `stamind_cli` imports `add_workout_parser` from `parser`.
The handlers live in `adapt`, `generate`, `rollback`, `listing`, `compare`,
`calendar_sync`, `revisions`, `heads_up` and `strength_only`; `session_line` holds the
one-line rendering three of them share.
"""
