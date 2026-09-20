"""The `data` command family, one module per job.

`parser` builds the sub-commands and attaches each handler as `func=`, so nothing outside
this package names a handler: `trainmate_cli` imports `add_data_parser` from `parser`.
The handlers live in `cache` (the local Garmin cache itself), `show` (the cached rows as
tables or CSV) and `analysis` (what the model made of past training).
"""
