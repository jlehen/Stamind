"""Google Calendar, outbound and inbound (DESIGN_calendar_lineage.md,
DESIGN_calendar_signal_ingest.md, DESIGN_workout_revisions.md §8).

Four submodules, lowest first:

* `history` — the `History` section an event's description ends with: every earlier form
  of the session, newest first, and the one load line the top of the event uses too.
* `event` — what a workout's event says: its title tags, its whole description, and the
  day an event sits on. No Google import anywhere in it.
* `client` — `CalendarSyncer`, the only file here that talks to the API, plus the daily
  signal sync in both directions.
* `reconcile` — the pass that makes the calendar agree with the workouts log after a
  change commits.

The package is `gcal` and not `calendar` because the standard library owns that name.
Nothing is re-exported here. ARCHITECTURE.md §15 has both reasons.
"""
