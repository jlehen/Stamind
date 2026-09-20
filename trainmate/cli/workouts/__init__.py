"""The `workout` command family, one module per verb group.

`parser` builds the sub-commands and attaches each handler as `func=`, so nothing outside
this package names a handler: `trainmate_cli` imports `add_workout_parser` from `parser`.
The handlers live in `generate`, `calendar_sync`, `revisions`, `heads_up` and
`strength_only`, and are imported from those modules.
"""
