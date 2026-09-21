"""`tm progress` — the projected Performance Management Chart, numbers-first
(DESIGN_progress_timeline.md §7.1).

This file is the command: the argparse tree, the handler, the chart delivery, and
`render_progress`, which assembles one page out of the two halves beside it —
`cli/progress_load.py` for the fitness line and the weekly load table,
`cli/progress_zones.py` for the time-in-zone grid and the mesocycle report. All of it is
fed the `assemble_timeline` payload (§6.0), so the formatting is unit-testable without a
database, per the `coach/formatting.py` precedent."""
import argparse
from datetime import timedelta
from typing import Any, Dict, List, Optional

from stamind import runtime
from stamind.analytics import chart, timeline
from stamind.analytics.pmc import PMC_TSB_LAG_NOTE
from stamind.config import config
from stamind.text import cmd, dim, keep_whole, red, visible_len, wrap_text
from stamind.output import notice, warn
from stamind.clock import parse_date, today_str as _today_str
from stamind.cli.common import ensure_recent_data
from stamind.cli.progress_load import (
    format_form_line, format_no_plan_banner, format_objective_projection_lines,
    format_plan_end_proj, format_plan_gap_banner, format_sparkline_line,
    format_weekly_table, short_date, warning_line, weekday,
)
from stamind.cli.progress_zones import (
    render_mesocycle_section, unknown_sport_preferences, zone_section,
)

# `timeline_rows` is imported inside `run_progress` and stays there: it reaches the
# Garmin package for the warm-up cutoff, so a module-level import would put all of
# `garmin/` on the startup path of every command, this one included
# (ARCHITECTURE.md §14).


def render_progress(
    payload: Dict[str, Any], weeks_window: Any, explain: bool = False,
    zone_opts: Optional[Dict[str, Any]] = None,
) -> List[str]:
    """The complete `tm progress` text output (§7.1) as a list of lines, built purely
    from the `assemble_timeline` payload — no DB, unit-testable. Width-agnostic here;
    `run_progress` wraps prose lines through `wrap_text` and the table is already
    fixed-width. `weeks_window` is a positive int or `'all'` and windows *both*
    halves (§7.1); `explain` adds the PMC footnotes.

    `zone_opts` (`{preferences, sports, currency}`) adds the per-sport intensity tables
    under the load table (DESIGN_intensity_distribution.md §9.6). It scopes the intensity
    content ONLY: CTL, ATL, TSB, the projection and the WEEKLY LOAD table stay
    whole-athlete, because a running-only CTL is not a quantity — the fitness model
    integrates every activity the body paid for — and adherence is measured against the
    whole plan. Every line it emits is inside the 48-column budget, so `run_progress`'s
    re-wrap never fires on one."""
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

    if zone_opts is not None:
        # Both halves, aligned row for row with the load table: measured behind today,
        # the plan's own zone targets ahead of it (§9.8 closing §9.6's one asymmetry).
        # Sessions planned before those columns existed simply render no ghost row until
        # the next `workout generate`.
        zone_lines = zone_section(
            display_weeks, zone_opts.get("preferences") or [],
            explicit=zone_opts.get("sports"),
            forced_currency=zone_opts.get("currency"),
            hidden_weeks=hidden_weeks, today=today, stats_weeks=past_weeks,
        )
        if zone_lines:
            lines.append("")
            lines += zone_lines

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
    """Displays the projected fitness/fatigue timeline: measured load to date, planned
    load through plan end, and the weekly planned-vs-actual bars (§7.1). Auto-ensures
    fresh Garmin data first (the seam would otherwise read yesterday's un-synced ride
    as a 0-load day)."""
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
    """The expert `progress` body: the load table, the optional zone and mesocycle sections,
    and the chart captioned with the table's first line.

    The companion form of this is CompanionRenderer.progress
    (DESIGN_render_persona.md §5)."""
    sports = list(getattr(args, "sports", None) or [])
    mesocycles = getattr(args, "mesocycles", False)
    # Naming a sport IS a request for its zone table; otherwise the tables are opt-in
    # (`-z`). They are the longest thing on the screen and answer a different question
    # from the load table above them (DESIGN_intensity_distribution.md §9.6).
    zones = mesocycles or bool(sports) or getattr(args, "zones", False)
    forced = "power" if getattr(args, "power", False) else (
        "hr" if getattr(args, "hr", False) else None
    )
    preferences: List[str] = []
    if zones and not sports:
        preferences = list(config.user_profile.get("sport_preferences") or [])
        for warning in unknown_sport_preferences(preferences):
            warn(warning)

    zone_opts = {
        "preferences": preferences, "sports": sports, "currency": forced,
    } if (zones and not mesocycles) else None
    lines = render_progress(
        payload, weeks_window, getattr(args, "explain", False), zone_opts
    )
    for line in lines:
        # Table rows are already fixed-width; prose (banners, footnotes) wraps.
        print(wrap_text(line) if visible_len(line) > 48 else line)

    if mesocycles:
        # Printed outside the loop above: `mesocycle_report` lays one zone cell per line at
        # phone width, and a screen-width re-wrap would shred those columns (§9.6).
        for line in render_mesocycle_section(
            runtime.db, payload, weeks_window, today, sports, preferences
        ):
            print(line)

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


def add_progress_parser(subparsers, pull_bypass_parser):
    # progress command — the projected Performance Management Chart
    progress_parser = subparsers.add_parser(
        "progress",
        parents=[pull_bypass_parser],
        help="Show the training progress timeline: measured load to date, projected forward",
        description=(
            "Show a single continuous timeline of training load: past days measured "
            "from completed activities, future days from the scheduled sessions, one "
            "fitness/fatigue model (CTL/ATL/TSB) run across the seam. Projects to plan "
            "end (or each objective the plan reaches) so you can see whether the plan "
            "as written delivers peak fitness with positive form on race day. Add -z "
            "for time-in-zone tables under the load table: TSS folds volume and "
            "intensity into one number, so easy days drifting to tempo read as flat "
            "weekly load and flat adherence. Naming sports implies -z and scopes those "
            "tables ONLY: CTL/ATL/TSB, the projection and the weekly load table stay "
            "whole-athlete."
        )
    )
    progress_parser.add_argument(
        "sports", nargs="*", metavar="SPORT",
        help="Canonical sports to report intensity for, one table each in the order "
             "given (e.g. 'tm progress running cycling'). Implies --zones. Without "
             "them, --zones covers every sport preference with zone data in the window "
             "that holds at least 10%% of its duration, in config order; the rest are "
             "named in the footer."
    )
    progress_parser.add_argument(
        "-z", "--zones", action="store_true",
        help="Also show weekly time-in-zone tables, one per sport. Weeks behind today "
             "show what you measured; weeks ahead show what the plan prescribes, "
             "marked '+'. Roughly triples the length of the output."
    )
    progress_parser.add_argument(
        "-w", "--weeks", type=_weeks_arg, default=8, metavar="N",
        help="Weeks of weekly load to show either side of today (default: 8, must be "
             ">= 1, or 'all' for the whole plan). The projection lines above the table "
             "always run to plan end regardless."
    )
    progress_parser.add_argument(
        "--mesocycles", action="store_true",
        help="Report intensity per mesocycle instead of per week, single-sport: "
             "per-week rates over each mesocycle's completed weeks beside its stated focus, "
             "the mesocycle-over-mesocycle delta and the structural rows. Replaces the weekly "
             "zone table (the load table stays) and is LONGER than what it replaces."
    )
    currency = progress_parser.add_mutually_exclusive_group()
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
    progress_parser.add_argument(
        "--explain", action="store_true",
        help="Append the PMC footnotes (e.g. why TSB lags same-day CTL - ATL)."
    )
    progress_parser.add_argument(
        "--chart", nargs="?", const=True, default=False, metavar="PATH",
        help="Also render the two-panel chart (PMC + weekly load) to a PNG "
             "(default: ./progress.png; requires matplotlib). Additive — the "
             "text output above still prints."
    )

    progress_parser.set_defaults(func=run_progress)

    return progress_parser
