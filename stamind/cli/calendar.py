"""`sm calendar`: one month as a grid, in expert marks (DESIGN_calendar_miniapp.md §7).

Built on the same list of days as the bot's calendar page (`stamind/calendar_days.py`), so
the two agree on the facts. The grid itself is `cli/render/calendar_grid.py`, reached
through `runtime.render`. A day's detail stays `workout list -d <date> -vv`.
"""
import argparse
import calendar as month_calendar

from stamind import calendar_days, runtime
from stamind.clock import day_str, parse_date, today_str
from stamind.output import warn
from stamind.cli.selectors import parse_single_date


def run_calendar(args: argparse.Namespace) -> None:
    """Prints the month holding `args.date`, today's by default."""
    today = today_str()
    anchor = parse_date(args.date or today)
    year, month = anchor.year, anchor.month
    first = day_str(anchor.replace(day=1))
    last = day_str(anchor.replace(day=month_calendar.monthrange(year, month)[1]))
    # Fresh grades, pulled the way `workout list` pulls them (§7).
    if first <= today and not getattr(args, "no_pull", False):
        try:
            runtime.garmin.ensure_data(
                first, min(last, today), force=getattr(args, "force_pull", False)
            )
        except Exception as e:
            warn(f"could not ensure recent data: {e}")
    cal = calendar_days.gather(runtime.db, first, last, today)
    runtime.render.calendar_month(cal, year, month)


def add_calendar_parser(subparsers, pull_bypass_parser):
    parser = subparsers.add_parser(
        "calendar",
        parents=[pull_bypass_parser],
        help="Show one month as a grid of sessions, grades, constraints and signals",
        description=(
            "Show the month holding DATE (today by default) as a grid, Monday first: each "
            "day's sessions and their grade (✓ done, ½ partial, ✗ missed), an activity "
            "nothing planned after a '+', ◆ for a constraint and • for a signal. A day's "
            "detail is 'workout list -d DATE -vv'."
        ),
    )
    parser.add_argument(
        "date", nargs="?", type=parse_single_date, metavar="DATE",
        help="A day of the month to show: YYYY-MM-DD, today, or an offset like +4w",
    )
    parser.set_defaults(func=run_calendar)
    return parser
