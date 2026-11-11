"""`workout compare`: what was planned beside what Garmin recorded, day by day, then each
week that has ended against its sessions as written.

The pairing itself is `analytics/compare.py`, which this command, the dashboard's compare
tab and the Calendar's verdict stamping all read; the week grade is
`analytics/written_week.py` (DESIGN_week_as_written.md). This file only asks them for a
window and draws the answer.
"""
import argparse
from typing import Optional
from stamind import runtime
from stamind.analytics.adherence import (
    MINOR, MISSED, PARTIAL, REST_VIOLATION, UNPLANNED, classify_adherence, unplanned_kind,
)
from stamind.analytics.compare import adherence_window, compare_days, format_actual
from stamind.analytics.written_week import graded_weeks, week_grade_lines
from stamind.config import config
from stamind.gcal.reconcile import mark_adherence_from_results
from stamind.sports import canonical_sport
from stamind.strength.sets import activity_lines
from stamind.text import bold, cyan, gray, green, magenta, red, yellow
from stamind.output import notice, warn
from stamind.clock import (
    fmt_date, fmt_day, parse_date, today_date as _today_date, today_str as _today_str,
    week_start,
)
from stamind.cli.common import strength_table
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
            # From the Monday: an ended week is graded whole (DESIGN_week_as_written.md §5).
            runtime.garmin.ensure_data(
                week_start(start_date), end_date, force=getattr(args, 'force_pull', False)
            )
        except Exception as e:
            warn(f"could not ensure recent data: {e}")

    window = adherence_window(runtime.db, start_date, end_date, today_str)

    sport_filter = (getattr(args, 'sport_type', None) or "").lower() or None
    days = compare_days(
        parse_date(start_date), window.history_days, window.results, window.activities,
        sport_filter,
    )
    weeks = graded_weeks(runtime.db, start_date, end_date, today_str)
    if sport_filter:
        sport = canonical_sport(sport_filter)
        weeks = [(monday, [g for g in grade if g.sport == sport]) for monday, grade in weeks]

    runtime.render.workout_compare(
        days, start_date=start_date, end_date=end_date, sport_filter=sport_filter,
        informational=window.informational, covered_ranges=window.covered_ranges,
        weeks=[(monday, grade) for monday, grade in weeks if grade],
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
    informational: list, covered_ranges: list, weeks: list,
) -> None:
    """The expert compare report: PLANNED/ACTUAL per day, what differed under each session,
    how many discrepancies the days shown hold, then each ended week as written."""
    print(bold(cyan("=== WORKOUT COMPARE ===")))
    filter_parts = [f"From: {fmt_date(start_date)}", f"Until: {fmt_date(end_date)}"]
    if sport_filter:
        filter_parts.append(f"Type: {sport_filter}")
    print(gray(f"Filters: {', '.join(filter_parts)}"))
    print()

    if not days:
        print(gray("No planned workouts or completed activities found in this range."))
        print_graded_weeks(weeks)
        return

    discrepancies = 0
    for date_curr, day_results, unplanned in days:
        print(bold(cyan(fmt_date(date_curr))))

        for r in day_results:
            w = r['planned']
            act = r['completed']
            is_rest = w['sport_type'] == 'rest'
            verdict = classify_adherence(
                w, act, config.minor_activity_load_threshold, pending=r.get('pending', False)
            )
            if verdict['status'] in (MISSED, PARTIAL, REST_VIOLATION):
                discrepancies += 1

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
                table = strength_table(w, act)
                for line in table:
                    print(f"  {line}")
                if not table:
                    print_set_lines(act)
            elif r.get('pending'):
                print(f"  ACTUAL:     {gray('(not yet — still ahead today)')}")
            elif not is_rest:
                print(f"  ACTUAL:     {red('(none — missed)')}")
            for reason in verdict['reasons']:
                notice(f"  Discrepancy: {reason}")

        for act in unplanned:
            act_str = format_actual(act, divergence=True)
            kind = unplanned_kind(
                act, date_curr, covered_ranges, config.minor_activity_load_threshold
            )
            if kind == MINOR:
                print(gray(f"  (minor):    {act_str}"))
            elif kind == UNPLANNED:
                discrepancies += 1
                print(f"  UNPLANNED:  {yellow(act_str)}")
            else:
                print(gray(f"  (off-plan): {act_str}"))
            print_set_lines(act)

        print(gray("-" * 40))

    print()
    if discrepancies:
        noun = "discrepancies" if discrepancies != 1 else "discrepancy"
        print(bold(yellow(f"{discrepancies} {noun} found.")))
    else:
        # No "Great adherence!": the week below can be short (DESIGN_week_as_written.md §5).
        print(bold(green("No discrepancies found.")))
    print_graded_weeks(weeks)

    if informational:
        print()
        print(bold(gray("=== OUTSIDE ANY PLAN (informational) ===")))
        for act in informational:
            print(gray(
                f"- {fmt_date(act['date'])}: {format_actual(act, divergence=True)}"
            ))


def print_graded_weeks(weeks: list) -> None:
    """Each ended week against its sessions as written, in the lines the prompts read; a
    short sport's line is yellow, and nothing is red (DESIGN_week_as_written.md §5)."""
    if not weeks:
        return
    print()
    print(bold(cyan("=== WEEKS AS WRITTEN ===")))
    for monday, grade in weeks:
        print(bold(f"Week of {fmt_day(monday)}"))
        for sport in grade:
            first, *rest = week_grade_lines([sport], "    ")
            if sport.short:
                first = yellow(first)
            print(first)
            for line in rest:
                print(line)


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
