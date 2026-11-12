"""`sm progress weeks` and `sm progress mesocycles`: each week that has ended against its
sessions as written, and the mesocycles' records (DESIGN_progress_page.md §6).

The week grade is `analytics/written_week.py` (DESIGN_week_as_written.md); a record prints
through `cli/common.py:print_retrospective`, as `plan retrospective` prints one goal's. The
Progress page's file reads the records in the order `records_newest_first` gives."""
import argparse
from typing import Any, Dict, List, Optional

from stamind import runtime
from stamind.analytics.written_week import graded_weeks, week_grade_lines, week_line
from stamind.clock import fmt_day, shift, today_str as _today_str, week_start
from stamind.cycle_records import record_name
from stamind.db.retrospectives import PLAN
from stamind.text import bold, default_wrap_width, gray, yellow
from stamind.cli.common import ensure_recent_data, print_retrospective
from stamind.cli.progress_load import short_date


def window_start(dbh, weeks_window: Any, today: str) -> str:
    """The Monday the window opens on: `weeks_window` weeks back, this one counted, as the
    Fitness view counts them; the first day on record for `all`."""
    if weeks_window == "all":
        return week_start(dbh.first_training_day() or today)
    return shift(week_start(today), -7 * (int(weeks_window) - 1))


def run_progress_weeks(args: argparse.Namespace) -> None:
    """One line per week that has ended in the window, or with DATE that week in full. The
    week under way is never graded (DESIGN_week_as_written.md §2)."""
    ensure_recent_data(no_pull=args.no_pull, force_pull=getattr(args, "force_pull", False))
    today = _today_str()
    if args.date:
        print_week(week_start(args.date), today)
        return
    start = window_start(runtime.db, args.weeks, today)
    weeks = graded_weeks(runtime.db, start, today, today)
    print(bold("WEEKS AS WRITTEN"))
    if not weeks:
        print(gray("No week that has ended in this window had sessions written."))
        return
    for monday, grade in weeks:
        print(f"w/c {short_date(monday)}  {week_line(grade)}")


def print_week(monday: str, today: str) -> None:
    """One ended week in the lines the prompts read, a short sport's line in yellow and
    nothing in red (DESIGN_week_as_written.md §5)."""
    if monday >= week_start(today):
        print(gray(f"The week of {fmt_day(monday)} has not ended: only a week that has "
                   "ended is graded."))
        return
    weeks = graded_weeks(runtime.db, monday, monday, today)
    if not weeks:
        print(gray(f"Nothing was written for the week of {fmt_day(monday)}."))
        return
    print(bold(f"Week of {fmt_day(monday)}"))
    for sport in weeks[0][1]:
        first, *rest = week_grade_lines([sport], "    ")
        if sport.short:
            first = yellow(first)
        print(first)
        for line in rest:
            print(line)


def records_newest_first(dbh) -> List[Dict[str, Any]]:
    """Every record, a plan's above the mesocycles it closes (DESIGN_progress_page.md §3.3)."""
    return sorted(
        dbh.get_retrospectives(),
        key=lambda r: (r["end_date"], r["level"] == PLAN, r["start_date"]), reverse=True,
    )


def mesocycle_under_way(dbh, today: str) -> Optional[Dict[str, Any]]:
    """The governing plan's mesocycle holding today, which has no record yet (§3.3)."""
    macro = dbh.get_governing_macrocycle()
    if not macro:
        return None
    for meso in dbh.get_mesocycles_for_macrocycle(macro["id"]):
        if meso["start_date"] <= today <= meso["end_date"]:
            return meso
    return None


def dates(row: Dict[str, Any]) -> str:
    """'Sun 25 Oct – Tue 3 Nov': a mesocycle's or a record's days."""
    return f"{fmt_day(row['start_date'])} – {fmt_day(row['end_date'])}"


def run_progress_mesocycles(args: argparse.Namespace) -> None:
    """The mesocycle under way, then every record newest first, each as `plan
    retrospective` prints it; a blank record says "not written yet"."""
    today = _today_str()
    current = mesocycle_under_way(runtime.db, today)
    records = records_newest_first(runtime.db)
    if current is None and not records:
        print(gray("No mesocycle has a record yet."))
        return
    if current is not None:
        print(f"{bold(current['name'])}, {dates(current)} (under way)")
    width = default_wrap_width()
    for record in records:
        print_retrospective(f"{record_name(record)}, {dates(record)}", record, "", width)
