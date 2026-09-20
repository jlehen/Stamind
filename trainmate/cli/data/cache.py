"""`data pull`, `data backfill-tss` and `data wipe`: the local Garmin cache itself.

Every other command freshens the cache on its own through `ensure_recent_data`; these
three are the ones the athlete runs when they want to say exactly which days to fetch,
recompute or throw away.
"""
import argparse
from trainmate import runtime
from trainmate.gcal.reconcile import mark_adherence_range
from trainmate.text import green, red
from trainmate.output import notice, warn
from trainmate.clock import fmt_date, fmt_span
from trainmate.cli.selectors import resolve_window


def run_data_pull(args: argparse.Namespace) -> None:
    """Pulls athlete metrics and activities directly from Garmin Connect.

    Explicit/manual pull: does exactly the range asked for (mirrors GarminScraper's
    options) and advances the watermark. The watermark/auto-ensure logic lives in
    runtime.garmin.ensure_data, which commands call when reading.
    """
    start_date, end_date = resolve_window(args)

    pulled = False
    try:
        # The sync's own step-by-step narration is side information; its summary is
        # this command's answer, so it prints here (DESIGN_output_verbosity.md §3.1).
        print(green(runtime.garmin.pull(
            start_date, end_date,
            metrics=not args.activities_only,
            activities=not args.metrics_only,
            throttle=args.sleep,
        )))
        pulled = True
    except runtime.garmin.GarminAuthRequired as e:
        notice(f"Garmin authentication required: {e}", red)
        notice("Run this command in an interactive terminal to complete MFA.")
    except Exception as e:
        notice(f"Error pulling from Garmin: {e}", red)

    # Ride-along: with fresh activity data in hand, stamp the adherence verdict
    # onto past Calendar events over the pulled range (best-effort — a Calendar
    # failure never breaks the pull; no-op when no calendar is configured).
    if pulled and not getattr(args, 'no_mark', False):
        try:
            marked = mark_adherence_range(start_date, end_date)
            if marked:
                print(green(f"Marked {marked} past Calendar event(s) with adherence."))
        except Exception as e:
            warn(f"adherence Calendar marking skipped: {e}")


def run_data_backfill_tss(args: argparse.Namespace) -> None:
    """Recomputes stored TSS for all cached activities under the current
    zone-based hierarchy, then refreshes the derived PMC."""
    start_date, end_date = resolve_window(args)
    changed = runtime.garmin.backfill_tss(
        start_date=start_date,
        end_date=end_date,
        verbose=getattr(args, "verbose", False),
    )
    print(green(f"Backfill complete. {changed} activities updated."))


def run_data_wipe(args: argparse.Namespace) -> None:
    """Wipes locally cached data after confirmation. --garmin / --calendar scope the
    wipe to Garmin evidence or ingested daily signals respectively (neither flag = both);
    -d restricts it to a date window."""
    garmin = getattr(args, "garmin", False)
    calendar = getattr(args, "calendar", False)
    # No scope flag means "everything" — keep the historical full-wipe behaviour.
    if not garmin and not calendar:
        garmin = calendar = True

    start, end = resolve_window(args)

    scope_parts = []
    if garmin:
        scope_parts.append("Garmin metrics, baselines, and activities")
    if calendar:
        scope_parts.append("ingested daily signals")
    scope = " and ".join(scope_parts)

    if start and end:
        window = f" dated {fmt_span(start, end)}"
    elif start:
        window = f" dated {fmt_date(start)} onward"
    elif end:
        window = f" dated up to {fmt_date(end)}"
    else:
        window = ""

    if not args.yes:
        if not runtime.prompt.confirm(
            f"Are you sure you want to wipe {scope}{window}?", danger=True
        ):
            print("Wipe cancelled.")
            return

    if garmin:
        # The post-wipe PMC sweep is part of wiping now, not something the caller has
        # to remember (see db/wipes.py).
        runtime.db.wipe_garmin_data(start, end)
    if calendar:
        runtime.db.wipe_calendar_signals(start, end)
    print(green(f"Wiped {scope}{window}."))
