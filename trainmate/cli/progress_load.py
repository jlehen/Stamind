"""The load half of `tm progress`: the fitness line and the weekly load table
(DESIGN_progress_timeline.md §7.1).

Pure formatting over the `assemble_timeline` payload — no database, no dispatch — laid
out to the bot's 48-column budget so a TTY and Telegram render identically. Widths are
measured with `visible_len` (emoji are double-width), never `len`. The zone grid drawn
under this table is `cli/progress_zones.py`, which shares this file's week column, band
walk and column budget."""
from typing import Any, Dict, List, Optional

from trainmate.analytics import progression
from trainmate.analytics.pmc import color_tsb
from trainmate.text import bold, cmd, dim, gray, green, pad_visible, visible_len, yellow
from trainmate.clock import fmt_date, parse_date


SPARK_CHARS = "▁▂▃▄▅▆▇█"  # ▁..█
BAR_WIDTH = 12
WEEK_COL_WIDTH = 11
NUM_COL_WIDTH = 4
TABLE_WIDTH = 48  # the bot's column budget; the band rule may use all of it
BAND_LABEL_WIDTH = TABLE_WIDTH - 5  # '── ' + label + ' ' + at least one closing '─'

# The load table's own marker, and a different claim from the zone table's `!`: the week
# contains an activity whose HR recording was too sparse to trust AND carried no RPE, so
# the LOAD is undercounted too and the week reads as an adherence miss it never was
# (DESIGN_intensity_distribution.md §11).
LOAD_SPARSE = "?"

NO_BAND = object()  # sentinel: no band emitted yet (a real meso_label may be None)


def short_date(date_str: str) -> str:
    """'2026-07-31' -> '07-31'.

    The one place a displayed day carries no weekday: this table is laid out to the
    bot's 48-column budget, and four more characters per label does not fit. The
    footer notes spell the weekday out where a plan edge actually matters."""
    return date_str[5:]


def weekday(date_str: str) -> str:
    """'2026-07-31' -> 'Wed'."""
    return parse_date(date_str).strftime("%a")


def sparkline(values: List[Optional[float]]) -> str:
    """Min-max-scaled 8-level sparkline, one char per value. `None` cells (warm-up
    edge inside the window, or no anchor) render as a blank space; a flat series
    (min == max) renders all present cells at the floor glyph. Range-stretching can
    make a small climb look steep — accepted (§7.1): the real numbers sit alongside."""
    present = [v for v in values if v is not None]
    if not present:
        return " " * len(values)
    lo, hi = min(present), max(present)
    chars = []
    for v in values:
        if v is None:
            chars.append(" ")
        elif hi == lo:
            chars.append(SPARK_CHARS[0])
        else:
            idx = round((v - lo) / (hi - lo) * (len(SPARK_CHARS) - 1))
            chars.append(SPARK_CHARS[idx])
    return "".join(chars)


def _cells(value: Optional[float], scale_max: float, width: int) -> int:
    """`value` as a whole number of bar cells on the shared scale, clamped to the bar.
    A zero scale_max yields 0 (no division by the zero max)."""
    if scale_max <= 0 or not value:
        return 0
    return max(0, min(width, round(width * value / scale_max)))


def render_bar(
    actual: float, plan: Optional[float], scale_max: float, is_future: bool,
    width: int = BAR_WIDTH,
) -> str:
    """Bullet bar on the shared absolute-load scale `scale_max` (§7.1): past weeks
    fill `▓` to actual and tick `│` at plan, future weeks ghost-fill `▒` to plan."""
    if is_future:
        n = _cells(plan, scale_max, width)
        return "▒" * n + "░" * (width - n)

    n = _cells(actual, scale_max, width)
    bar = ["▓"] * n + ["░"] * (width - n)
    if plan:
        # First cell *beyond* plan: filled-up-to-the-tick reads as on-plan. Clamped
        # into the bar, because the week whose plan *is* scale_max maps to p == width
        # and is precisely the week whose tick matters most (§7.1).
        p = min(_cells(plan, scale_max, width), width - 1)
        bar[p] = "│"
    return "".join(bar)


def truncate_label(label: str, width: int = BAND_LABEL_WIDTH) -> str:
    """Truncates a mesocycle label to `width` with a trailing ellipsis."""
    if len(label) <= width:
        return label
    return label[: width - 1] + "…"


def band_header(label: Optional[str], width: int = TABLE_WIDTH) -> str:
    """A mesocycle band rule spanning the table — `── Base Consolidation ─────────`
    (§7.1). Weeks the plan never governed band under 'unplanned' (§6.1 'no match')."""
    text = truncate_label(label) if label else "unplanned"
    prefix = f"── {text} "
    # At least one closing dash, so the table's right edge stays straight (§7.1);
    # BAND_LABEL_WIDTH reserves the room.
    return prefix + "─" * max(1, width - visible_len(prefix))


def format_form_line(
    source: Optional[str], ctl: Optional[float], atl: Optional[float],
    tsb: Optional[float],
) -> str:
    """'FORM today (actual)  CTL 55  ATL 61  TSB -6' — the numbers-first answer to
    'am I on track', tagging where today's load came from (§7.1): `(actual)` once
    today's session has synced, `(planned)` while the fold counts the planned session
    in its place. TSB is coloured by `color_tsb`, reusing `tm status`'s conventions.
    Returns the still-warming message when today has no PMC value (§4).

    One decimal on all three, matching `tm status` — `color_tsb` has always printed
    TSB to 1 dp, so rounding CTL/ATL to whole numbers beside it made one line carry
    two precisions. Single-space separation keeps the trio inside the 48-col budget."""
    if ctl is None or atl is None or tsb is None:
        return dim("FORM today   PMC still warming — not enough history yet")
    tag = f" ({source})" if source else ""
    return f"FORM today{tag} CTL {ctl:.1f} ATL {atl:.1f} TSB {color_tsb(tsb)}"


def format_sparkline_line(
    ctl_samples: List[Optional[float]], weeks_shown: int,
    plan_end_proj: Optional[str] = None,
) -> str:
    """'CTL 8w ▁▂▂▃▃▅▅▆   plan end 07-31: CTL 61 TSB +1' — the CTL trend, one cell per
    displayed week, with the plan-end projection appended when the plan reaches no
    objective (else the per-objective lines carry it). `weeks_shown` counts the cells
    drawn, which on a short history is fewer than `--weeks` asked for (§7.1)."""
    spark = sparkline(ctl_samples)
    line = f"CTL {weeks_shown}w {spark}"
    if plan_end_proj:
        line += f"   {plan_end_proj}"
    return line


def format_plan_end_proj(plan_end_date: str, ctl: float, tsb: float) -> str:
    return f"plan end {short_date(plan_end_date)}: CTL {ctl:.0f} TSB {tsb:+.0f}"


def format_objective_projection_lines(
    objective: Dict[str, Any], ctl: float, tsb: float
) -> List[str]:
    """Per-objective projection, shown once the plan reaches that objective's target
    date (§7.1)."""
    return [
        f"\U0001F3C1 {fmt_date(objective['target_date'])} {objective['title']}",
        f"   projected CTL {ctl:.0f}, TSB {tsb:+.0f}",
    ]


def format_plan_gap_banner(
    plan_end_date: str, next_objective: Dict[str, Any], weeks_before: int
) -> List[str]:
    """The plan-end gap banner (§3): plan generated through X, N weeks before the next
    objective it doesn't yet reach; names the fix (`workout generate -g`, whose bare form
    is the active goal). The gap itself (which objective, how many weeks) is computed once
    in `analytics.runway.plan_gap` and passed in — this is presentation only (§7.1)."""
    return [
        yellow(
            f"⚠ plan generated through {short_date(plan_end_date)} "
            f"— {weeks_before} wks before"
        ),
        f"  \U0001F3C1 {fmt_date(next_objective['target_date'])} {next_objective['title']}",
        yellow(f"  ({cmd('workout generate -g', quote=False)})"),
    ]


def warning_line(w: Dict[str, Any]) -> str:
    """One footer warning in yellow. The payload stays ANSI-free for the web, so a
    warning that names a command carries it in `command` and gets it styled here —
    rather than this end guessing from the prose (§6.0)."""
    text = w["text"]
    name = w.get("command")
    marker = f"`{name}`" if name else None
    if marker and marker in text:
        head, _, tail = text.partition(marker)
        return yellow(f"⚠ {head}") + cmd(name) + yellow(tail)
    return yellow(f"⚠ {text}")


def format_no_plan_banner(lapsed_date: Optional[str]) -> List[str]:
    """The 'no plan generated' / 'plan lapsed' empty states (§3): past-only PMC, name
    the fix. `lapsed_date` set → the plan was outrun by the rolling horizon."""
    if lapsed_date:
        return [
            yellow(f"⚠ plan lapsed {short_date(lapsed_date)} — projection unavailable"),
            green(f"  Run {cmd('workout generate')} to project forward again."),
        ]
    return [
        yellow("⚠ no plan generated — projection unavailable"),
        green(f"  Run {cmd('plan generate')} "
              f"(after {cmd('data bootstrap')} if never run) to project forward."),
    ]


def _week_row(week: Dict[str, Any], scale_max: float, today: str) -> str:
    week_label = f"w/c {short_date(week['week_commencing'])}"
    # One marker, one meaning: this row's planned figure spans fewer than seven days —
    # because the week is still running, or because a plan edge falls inside it (§3).
    if week.get("in_progress") or week.get("partial_plan"):
        week_label += "*"
    if week.get("load_sparse"):
        week_label += LOAD_SPARSE
    week_col = pad_visible(week_label, WEEK_COL_WIDTH)

    denom = progression.week_plan_denom(week)
    plan_col = pad_visible(
        "—" if denom is None else f"{denom:.0f}", NUM_COL_WIDTH, align_left=False
    )

    is_future = week["week_commencing"] > today and not week.get("in_progress")
    bar = render_bar(week["actual_load"], denom, scale_max, is_future)
    if is_future:
        # No actual and no adherence yet — leave the columns off rather than filling
        # them with em-dashes the eye has to skip.
        return f"{week_col} {plan_col}  {bar}"

    actual_col = pad_visible(
        f"{week['actual_load']:.0f}", NUM_COL_WIDTH, align_left=False
    )
    # A week the plan only half covers has no comparable pair to divide (§3): three
    # planned days over seven trained ones is the 477% the `*` now stands for.
    if denom and not week.get("partial_plan"):
        pct = f"{round(week['actual_load'] / denom * 100)}%"
    else:
        pct = "—"
    pct_col = pad_visible(pct, NUM_COL_WIDTH, align_left=False)
    return f"{week_col} {plan_col}  {bar} {actual_col} {pct_col}"


def table_rows(weeks: List[Dict[str, Any]], today: str) -> List[str]:
    """The fixed-width WEEKLY LOAD table rows only (header, band rules, one row per
    week) — the part held to the 48-column budget (§7.1). Legend/warning lines are
    ordinary prose and wrap at the normal CLI width instead. Bar scale is the max
    weekly load among the displayed rows, so it doesn't jump when future weeks
    arrive."""
    if not weeks:
        return []
    scale_candidates = [
        w["planned_load"] if w.get("planned_load") is not None else 0.0 for w in weeks
    ] + [w["actual_load"] for w in weeks]
    scale_max = max(scale_candidates) if scale_candidates else 0.0

    header = (
        f"{pad_visible('WEEKLY LOAD', WEEK_COL_WIDTH)} "
        f"{pad_visible('plan', NUM_COL_WIDTH, align_left=False)}  "
        f"{pad_visible('▓done ▒plan', BAR_WIDTH)} "
        f"{pad_visible('done', NUM_COL_WIDTH, align_left=False)} "
        f"{pad_visible('adh', NUM_COL_WIDTH, align_left=False)}"
    )
    lines = [bold(header)]

    # A band rule wherever the mesocycle changes, so each label is written once, in
    # full, instead of truncated onto every row.
    current_label: Any = NO_BAND
    for week in weeks:
        label = week.get("meso_label")
        if label != current_label:
            lines.append(gray(band_header(label)))
            current_label = label
        lines.append(_week_row(week, scale_max, today))
    return lines


def format_weekly_table(
    weeks: List[Dict[str, Any]], today: str,
    has_inferred: bool, partial_note: Optional[str], hidden_weeks: int = 0,
) -> List[str]:
    """The WEEKLY LOAD table (§7.1): fixed-width rows plus a legend footer. `weeks`
    must already be windowed by the caller; `hidden_weeks` counts every week that
    window dropped — past *and* projected — named in the legend so the truncation is
    never silent."""
    lines = table_rows(weeks, today)
    if not lines:
        return []
    legend_parts = []
    if has_inferred:
        legend_parts.append("~ inferred")
    legend_parts.append("* part week")
    if any(w.get("load_sparse") for w in weeks):
        legend_parts.append(f"{LOAD_SPARSE} load undercounted — recording gap, no RPE")
    if partial_note:
        legend_parts.append(partial_note)
    if hidden_weeks:
        legend_parts.append(f"+{hidden_weeks} more (--weeks all)")
    lines.append(gray(" · ".join(legend_parts)))
    return lines
