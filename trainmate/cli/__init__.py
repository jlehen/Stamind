"""TrainMate command-line interface, split into per-command-family modules.

Handlers live here; the top-level ``trainmate_cli`` module wires them into the argparse
dispatcher. The singletons a handler needs — db, garmin, calendar_syncer, coach_service,
prompt, render — belong to ``trainmate.runtime``, which builds each one on first use and
is the module a test patches (ARCHITECTURE §6).
"""
