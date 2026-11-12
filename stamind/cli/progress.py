"""`sm progress`: the Fitness, Weeks, Mesocycles and Intensity views, one word each, as the
Progress page's four tabs (DESIGN_progress_page.md §6). A bare `sm progress` is Fitness.

This file is the command: the argparse tree, the Fitness view's handler and chart delivery,
and `render_progress`, which assembles the Fitness view from `cli/progress_load.py`
(DESIGN_progress_timeline.md §7.1). The Weeks and Mesocycles views are
`cli/progress_weeks.py`, the Intensity view `cli/progress_zones.py`. Fitness and Intensity
are fed the `assemble_timeline` payload (§6.0), so the formatting is unit-testable without a
database."""
import argparse
from datetime import timedelta
from typing import Any, Dict, List, Optional

from stamind import runtime
from stamind.analytics import chart, timeline
from stamind.analytics.pmc import PMC_TSB_LAG_NOTE
from stamind.text import cmd, dim, keep_whole, red, visible_len, wrap_text
from stamind.output import notice
from stamind.clock import parse_date, today_str as _today_str
from stamind.cli.common import ensure_recent_data
from stamind.cli.progress_load import (
    LOAD_TABLE_WIDTH, format_form_line, format_no_plan_banner,
    format_objective_projection_lines,
    format_plan_end_proj, format_plan_gap_banner, format_sparkline_line,
    format_weekly_table, short_date, warning_line, weekday,
)
from stamind.cli.progress_weeks import run_progress_mesocycles, run_progress_weeks
from stamind.cli.progress_zones import run_progress_intensity
from stamind.cli.selectors import parse_single_date

# `timeline_rows` is imported inside `run_progress` and stays there: it reaches the
# Garmin package for the warm-up cutoff, so a module-level import would put all of
# `garmin/` on the startup path of every command, this one included
# (ARCHITECTURE.md §14).


def render_progress(
    payload: Dict[str, Any], weeks_window: Any, explain: bool = False,
) -> List[str]:
    """The Fitness view (§7.1) as a list of lines, built purely from the
    `assemble_timeline` payload — no DB, unit-testable. Width-agnostic here;
    `print_progress_report` wraps prose lines through `wrap_text` and the table is already
    fixed-width. `weeks_window` is a positive int or `'all'` and windows *both* halves
    (§7.1); `explain` adds the PMC footnotes."""
    today = payload["today"]
    plan_end = payload["plan_end"]
    days = payload["days"]
    objectives = payload["objectives"]
    warnings = payload["warnings"]
    by_date = {p["date"]: p for p in days}

    past_weeks, future_weeks, hidden_weeks = timeline.select_weeks(
        payload["weeks"], weeks_window, today
    )
    display_weeks = past_weeks + future_weeks

    lines: List[str] = []

    today_point = by_date.get(today)
    tsb_shown = bool(today_point and today_point.get("tsb") is not None)
    lines.append(format_form_line(
        today_point.get("source") if today_point else None,
        today_point.get("ctl") if today_point else None,
        today_point.get("atl") if today_point else None,
        today_point.get("tsb") if today_point else None,
    ))

    # Sparkline: one CTL sample per displayed past week (its last day <= today).
    ctl_samples: List[Optional[float]] = []
    for w in past_weeks:
        w_start = parse_date(w["week_commencing"])
        sample: Optional[float] = None
        for offset in range(6, -1, -1):
            d = (w_start + timedelta(days=offset)).strftime("%Y-%m-%d")
            if d <= today and d in by_date:
                sample = by_date[d].get("ctl")
                break
        ctl_samples.append(sample)

    # Projection region: per-objective lines when the plan reaches objectives, else a
    # plan-end summary on the sparkline line plus the gap banner.
    reached = []
    if plan_end is not None:
        # today..plan_end only: the payload deliberately carries completed objectives for
        # the chart's flags, and a race already run has no projection (§7.1/§11).
        reached = [
            o for o in objectives
            if o.get("target_date") and today <= o["target_date"] <= plan_end
            and o["target_date"] in by_date
            and by_date[o["target_date"]].get("ctl") is not None
        ]
        reached.sort(key=lambda o: str(o["target_date"]))

    plan_end_proj = None
    if plan_end is not None and not reached:
        end_pt = by_date.get(plan_end)
        if end_pt and end_pt.get("ctl") is not None:
            plan_end_proj = format_plan_end_proj(
                plan_end, end_pt["ctl"], end_pt["tsb"]
            )

    # Label the cells actually drawn, not the window asked for: on a young DB
    # `--weeks 8` over one week of history used to render 'CTL 8w ▁' (§7.1).
    lines.append(format_sparkline_line(ctl_samples, len(past_weeks), plan_end_proj))

    if plan_end is None:
        lines += format_no_plan_banner(None)
    elif plan_end < today:
        # Plan lapsed: the rolling horizon was outrun, window ended at today (§3).
        lines += format_no_plan_banner(plan_end)
    else:
        # Per-objective projections for objectives the plan reaches, plus the gap
        # banner for the next active objective it doesn't yet reach (§3) — both can
        # apply in a multi-objective season.
        for o in reached:
            pt = by_date[o["target_date"]]
            lines += format_objective_projection_lines(o, pt["ctl"], pt["tsb"])
        gap = payload.get("plan_gap")
        if gap:
            lines += format_plan_gap_banner(
                plan_end, gap["objective"], gap["weeks_before"]
            )

    # The lag note is a standing caveat, not news: printing it on every invocation
    # trained the eye to skip it. Behind `--explain` (§7.1).
    if tsb_shown and explain:
        lines.append(dim(PMC_TSB_LAG_NOTE))

    lines.append("")

    has_inferred = any(b["source"] == "inferred" for b in payload["meso_bands"])
    # Name whichever plan edge falls inside a displayed week: that week's planned total
    # covers fewer days than its bar does, which is why its adherence reads `—` (§3).
    shown = {w["week_commencing"] for w in display_weeks}
    notes = []
    for verb, date, aligned in (
        ("starts", payload.get("plan_start"), 0), ("ends", plan_end, 6),
    ):
        if not date or parse_date(date).weekday() == aligned:
            continue  # a plan starting Monday / ending Sunday leaves no partial week
        d = parse_date(date)
        if (d - timedelta(days=d.weekday())).strftime("%Y-%m-%d") in shown:
            notes.append(f"plan {verb} {short_date(date)} ({weekday(date)})")
    lines += format_weekly_table(
        display_weeks, today, has_inferred,
        " · ".join(notes) if notes else None, hidden_weeks,
    )
    lines += [warning_line(w) for w in warnings]
    return lines

DEFAULT_CHART_PATH = "./progress.png"


def emit_chart(chart_arg: Any, payload: Dict[str, Any], caption: str) -> None:
    """Renders the §2 two-panel chart and delivers it per front-end (§7.2): a sentinel
    photo line under the bot's json frontend (temp file, bot-owned cleanup), else a
    plain overwritten file path printed to stdout.

    Rendering happens *before* any file is created, so a missing matplotlib fails with
    an install hint and leaves nothing behind — no orphaned temp file for the bot to
    clean up (it never learns of one, since no photo sentinel is emitted)."""
    try:
        png = chart.render_timeline_png(payload)
    except ImportError:
        notice(
            "matplotlib is not installed — run: "
            + cmd(keep_whole("venv/bin/pip install -r requirements.txt"), quote=False),
            red,
        )
        return

    from stamind.sentinels import emit_photo, is_json_frontend
    if is_json_frontend():
        import tempfile
        with tempfile.NamedTemporaryFile(delete=False, suffix=".png") as tmp:
            tmp.write(png)
            path = tmp.name
        emit_photo(path, caption=caption)
    else:
        path = chart_arg if isinstance(chart_arg, str) else DEFAULT_CHART_PATH
        with open(path, "wb") as f:
            f.write(png)
        print(f"Chart written to {path}")


def run_progress(args: argparse.Namespace) -> None:
    """The Fitness view, and a bare `sm progress`: measured load to date, planned load
    through plan end, and the weekly planned-vs-actual bars (§7.1). Auto-ensures fresh
    Garmin data first (the seam would otherwise read yesterday's un-synced ride as a
    0-load day)."""
    from stamind import timeline_rows
    ensure_recent_data(
        no_pull=args.no_pull, force_pull=getattr(args, "force_pull", False)
    )
    today = _today_str()
    weeks_window = getattr(args, "weeks", None) or 8

    payload = timeline_rows.build_timeline_payload(runtime.db)
    runtime.render.progress(payload, args, today, weeks_window)


def print_progress_report(
    payload: Dict[str, Any], args: argparse.Namespace, today: str, weeks_window: int,
) -> None:
    """The expert Fitness view: the fitness line, the goals, the load table, and the chart
    captioned with the table's first line.

    The companion form of this is CompanionRenderer.progress
    (DESIGN_render_persona.md §5)."""
    lines = render_progress(payload, weeks_window, getattr(args, "explain", False))
    for line in lines:
        # Table rows are already fixed-width; prose (banners, footnotes) wraps.
        print(wrap_text(line) if visible_len(line) > LOAD_TABLE_WIDTH else line)

    chart_arg = getattr(args, "chart", False)
    if chart_arg:
        emit_chart(
            chart_arg,
            timeline.clip_payload_for_weeks(
                payload, weeks_window, today, cap_future=True
            ),
            lines[0] if lines else "",
        )


def _weeks_arg(raw: str):
    """`--weeks N` must be a whole number >= 1, or the literal `all`
    (DESIGN_progress_timeline.md §7.1) — rejected at argparse, so a `0` can't silently
    fall through to the default. `all` matches the web endpoint's `?weeks=all`."""
    if raw == "all":
        return "all"
    try:
        n = int(raw)
    except ValueError:
        raise argparse.ArgumentTypeError(f"invalid int value: '{raw}'")
    if n < 1:
        raise argparse.ArgumentTypeError("must be >= 1")
    return n


def _add_weeks_flag(parser: argparse.ArgumentParser) -> argparse.Action:
    """The weeks either side of today, which every view but Mesocycles reads
    (DESIGN_progress_page.md §6)."""
    return parser.add_argument(
        "-w", "--weeks", type=_weeks_arg, default=8, metavar="N",
        help="Weeks to show either side of today, this week counted (default: 8, must be "
             ">= 1, or 'all' for every week). The projection lines above the load table "
             "always run to plan end regardless."
    )


def _add_fitness_flags(parser: argparse.ArgumentParser) -> argparse.Action:
    """The Fitness view's flags, which a bare `sm progress` takes too (§6). Returns the
    weeks flag's action."""
    weeks = _add_weeks_flag(parser)
    parser.add_argument(
        "--explain", action="store_true",
        help="Append the PMC footnotes (e.g. why TSB lags same-day CTL - ATL)."
    )
    parser.add_argument(
        "--chart", nargs="?", const=True, default=False, metavar="PATH",
        help="Also render the two-panel chart (PMC + weekly load) to a PNG "
             "(default: ./progress.png; requires matplotlib). Additive — the "
             "text output above still prints."
    )
    return weeks


def add_progress_parser(subparsers, pull_bypass_parser):
    progress_parser = subparsers.add_parser(
        "progress",
        parents=[pull_bypass_parser],
        help="Show how training went: fitness, weeks, mesocycles, intensity",
        description=(
            "One view per word, as the Progress page's tabs: fitness, weeks, mesocycles "
            "and intensity. A bare 'progress' is the fitness view and takes its flags. "
            "Another view's flag goes after its word: 'progress weeks -w 12'."
        )
    )
    # `weeks` names the view here, so the bare run's flag is spelt with its dashes only
    # (DESIGN_progress_page.md §6).
    _add_fitness_flags(progress_parser).dashless = False
    # A bare `sm progress` is the Fitness view (DESIGN_cli_noargs.md §a3).
    progress_parser.set_defaults(func=run_progress)
    views = progress_parser.add_subparsers(dest="subcommand", help="Progress views")

    fitness = views.add_parser(
        "fitness",
        parents=[pull_bypass_parser],
        help="Fitness and form, the goals, and the weekly load; a bare 'progress'",
        description=(
            "Show a single continuous timeline of training load: past days measured "
            "from completed activities, future days from the scheduled sessions, one "
            "fitness/fatigue model (CTL/ATL/TSB) run across the seam. Projects to plan "
            "end (or each objective the plan reaches) so you can see whether the plan "
            "as written delivers peak fitness with positive form on race day. The "
            "weekly table ends with the hours planned (h.plan) and the hours done "
            "(h.done). Both count only what is worth more load per hour than "
            "garmin.hours_load_floor, so a walk logged very light adds nothing. A bare "
            "'progress' is this view."
        )
    )
    _add_fitness_flags(fitness)
    fitness.set_defaults(func=run_progress)

    weeks = views.add_parser(
        "weeks",
        parents=[pull_bypass_parser],
        help="Each week that has ended against its sessions as written",
        description=(
            "One line per week that has ended in the window, graded whole, per sport, "
            "against its sessions as workout generate wrote them: strength in sessions, "
            "yoga and rest not graded, every other sport by load. The week under way is "
            "never graded. With DATE, that week in full: each sport, and under a short "
            "sport the sessions no longer as written, with the day and the reason of the "
            "change."
        )
    )
    _add_weeks_flag(weeks)
    weeks.add_argument(
        "date", nargs="?", type=parse_single_date, metavar="DATE",
        help="Any day of the week to show in full, such as 2026-11-04",
    )
    weeks.set_defaults(func=run_progress_weeks)

    mesocycles = views.add_parser(
        "mesocycles",
        help="Every mesocycle's record, newest first",
        description=(
            "Every retrospective record, a plan's among them, newest first, printed as "
            "'plan retrospective' prints one goal's, under the mesocycle under way. A "
            "record not written yet says so."
        )
    )
    mesocycles.set_defaults(func=run_progress_mesocycles)

    intensity = views.add_parser(
        "intensity",
        parents=[pull_bypass_parser],
        help="Weekly time in zone, one table per sport",
        description=(
            "Weekly time-in-zone tables, one per sport: weeks behind today show what you "
            "measured, weeks ahead what the plan prescribes, marked '+'. TSS folds volume "
            "and intensity into one number, so easy days drifting to tempo read as flat "
            "weekly load and flat adherence; these tables show it."
        )
    )
    _add_weeks_flag(intensity)
    intensity.add_argument(
        "sports", nargs="*", metavar="SPORT",
        help="Canonical sports to report, one table each in the order given (e.g. "
             "'sm progress intensity running cycling'). Without them, every sport "
             "preference with zone data in the window that holds at least 10%% of its "
             "duration, in config order; the rest are named in the footer."
    )
    intensity.add_argument(
        "--mesocycles", action="store_true",
        help="Report intensity per mesocycle instead of per week, single-sport: "
             "per-week rates over each mesocycle's completed weeks beside its stated "
             "focus, the mesocycle-over-mesocycle delta and the structural rows. LONGER "
             "than the weekly tables it replaces."
    )
    currency = intensity.add_mutually_exclusive_group()
    currency.add_argument(
        "--power", action="store_true",
        help="Draw the zone tables in power zones instead of choosing by coverage. "
             "No effect on a sport that has only HR."
    )
    currency.add_argument(
        "--hr", action="store_true",
        help="Draw the zone tables in HR zones instead of choosing by coverage. "
             "No effect on a sport that has only power."
    )
    intensity.set_defaults(func=run_progress_intensity)

    return progress_parser
