"""`workout compare`: what was planned beside what Garmin recorded, day by day.

The pairing itself is `analytics/compare.py`, which this command, the dashboard's compare
tab and the Calendar's verdict stamping all read; this file only asks it for a window and
draws the answer.
"""
import argparse
from typing import Optional
from stamind import runtime
from stamind.analytics.adherence import (
    MINOR, UNPLANNED, format_discrepancies, unplanned_kind,
)
from stamind.analytics.compare import adherence_window, compare_days, format_actual
from stamind.config import config
from stamind.gcal.reconcile import mark_adherence_from_results
from stamind.strength.sets import activity_lines
from stamind.text import bold, cyan, gray, green, magenta, red, yellow
from stamind.output import notice, warn
from stamind.clock import (
    fmt_date, parse_date, today_date as _today_date, today_str as _today_str,
)
from stamind.cli.windows import resolve_window


def run_workout_compare(args: argparse.Namespace) -> None:
    """Compares planned workouts against completed activities for the given date range."""
    today_str = _today_str()
    today_obj = _today_date()

    # The 14-day lookback and the backward reading of a bare span are declared on the
    # parser (direction="backward"), so this handler only caps the far end.
    start_date, end_date = resolve_window(args)

    # Cap end_date at today — we can only compare past/present activities
    if end_date is None or end_date > today_str:
        end_date = today_str

    if not getattr(args, 'no_pull', False):
        try:
            runtime.garmin.ensure_data(
                start_date, end_date, force=getattr(args, 'force_pull', False)
            )
        except Exception as e:
            warn(f"could not ensure recent data: {e}")

    window = adherence_window(runtime.db, start_date, end_date, today_str)

    sport_filter = (getattr(args, 'sport_type', None) or "").lower() or None
    days = compare_days(
        parse_date(start_date), window.history_days, window.results, window.activities,
        sport_filter,
    )

    runtime.render.workout_compare(
        days, start_date=start_date, end_date=end_date, sport_filter=sport_filter,
        discrepancies=window.discrepancies, informational=window.informational,
        covered_ranges=window.covered_ranges,
    )
    if not days:
        return
    if getattr(args, 'no_mark', False) or not config.google_calendar_id:
        return
    runtime.render.calendar_marked(
        mark_adherence_from_results(window.results, today_str)
    )


def print_workout_compare(
    days: list, *, start_date: str, end_date: str, sport_filter: Optional[str],
    discrepancies: list, informational: list, covered_ranges: list,
) -> None:
    """The expert compare report: PLANNED/ACTUAL per day, then the discrepancy list."""
    print(bold(cyan("=== WORKOUT COMPARE ===")))
    filter_parts = [f"From: {fmt_date(start_date)}", f"Until: {fmt_date(end_date)}"]
    if sport_filter:
        filter_parts.append(f"Type: {sport_filter}")
    print(gray(f"Filters: {', '.join(filter_parts)}"))
    print()

    if not days:
        print(gray("No planned workouts or completed activities found in this range."))
        return

    for date_curr, day_results, unplanned in days:
        print(bold(cyan(fmt_date(date_curr))))

        for r in day_results:
            w = r['planned']
            act = r['completed']
            is_rest = w['sport_type'] == 'rest'

            if is_rest:
                print(f"  PLANNED:    [{magenta('REST')}]")
            else:
                parts = []
                if w.get('duration_minutes'):
                    parts.append(f"{w['duration_minutes']}min")
                if w.get('tss') is not None:
                    parts.append(f"TSS {w['tss']}")
                info = f" ({', '.join(parts)})" if parts else ""
                print(
                    f"  PLANNED:    [{magenta(w['sport_type'].upper())}] "
                    f"{bold(w['title'])}{info}"
                )

            if act:
                act_str = format_actual(act, divergence=True)
                if is_rest:
                    print(f"  ACTUAL:     {red(act_str)} {bold(red('[REST VIOLATION]'))}")
                else:
                    print(f"  ACTUAL:     {green(act_str)}")
                print_set_lines(act)
            elif r.get('pending'):
                print(f"  ACTUAL:     {gray('(not yet — still ahead today)')}")
            elif not is_rest:
                print(f"  ACTUAL:     {red('(none — missed)')}")

        for act in unplanned:
            act_str = format_actual(act, divergence=True)
            kind = unplanned_kind(
                act, date_curr, covered_ranges, config.minor_activity_load_threshold
            )
            if kind == MINOR:
                print(gray(f"  (minor):    {act_str}"))
            elif kind == UNPLANNED:
                print(f"  UNPLANNED:  {yellow(act_str)}")
            else:
                print(gray(f"  (off-plan): {act_str}"))
            print_set_lines(act)

        print(gray("-" * 40))

    print()
    if discrepancies:
        print(bold(yellow("=== DISCREPANCIES ===")))
        for line in format_discrepancies(discrepancies):
            notice(line)
        print()
        n = len(discrepancies)
        print(bold(yellow(f"{n} discrepanc{'ies' if n != 1 else 'y'} found.")))
    else:
        print(bold(green("No discrepancies found. Great adherence!")))

    if informational:
        print()
        print(bold(gray("=== OUTSIDE ANY PLAN (informational) ===")))
        for act in informational:
            print(gray(
                f"- {fmt_date(act['date'])}: {format_actual(act, divergence=True)}"
            ))


def print_set_lines(act: dict) -> None:
    """What was lifted, under a strength session's activity line (DESIGN_strength_tracking.md
    §7)."""
    for line in activity_lines(act):
        print(gray(f"              {line}"))


def print_calendar_marked(marked: int) -> None:
    """What the adherence stamping did to the Calendar, after the expert report."""
    print()
    if marked:
        print(green(f"Marked {marked} past event(s) on Calendar with adherence."))
    else:
        print(gray("Calendar adherence already up to date for this range."))
