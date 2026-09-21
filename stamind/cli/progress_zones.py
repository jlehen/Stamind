"""The intensity half of `tm progress`: time in zone, by week and by mesocycle
(DESIGN_intensity_distribution.md §9.6).

It lives here rather than in `analytics/zone_tables.py` because it aligns row for row
with the load table in `cli/progress_load.py` and shares that table's week column, band
walk and 48-column budget. `analytics/zone_tables.py` keeps the prompt-width table the
coach reads, and `analytics/intensity.py` the aggregation under both."""
import textwrap
from datetime import timedelta
from typing import Any, Dict, List, Optional, Sequence, Tuple

from stamind.analytics import intensity, timeline, zone_tables
from stamind.analytics.mesocycle_report import mesocycle_report
from stamind.plan_versions import delta_baseline, plan_lineage
# Which sports get a table, and in which currency: aggregation, not layout, so it lives
# in `intensity` where the web dashboard reads it from too (ARCHITECTURE.md §8).
from stamind.analytics.intensity import (
    ZONE_SPORT_MIN_SHARE, select_zone_sports, window_sport_stats, zone_currency,
)
from stamind.sports import SPORT_MAPPING, canonical_sport
from stamind.text import asides_enabled, bold, gray, pad_visible, yellow
from stamind.clock import parse_date
from stamind.cli.progress_load import (
    NO_BAND, TABLE_WIDTH, WEEK_COL_WIDTH, band_header, short_date,
)


# Zone-table columns (DESIGN_intensity_distribution.md §9.6). Z1 and Z2 get a sixth
# character so they keep their minutes past ten hours — the only two zones that ever get
# there, and they get there on exactly the hiking, ski-touring and high-volume cycling
# weeks where the aerobic base is the whole question. 11 + 6 + 6 + 5x5 = 48 for the
# 7-zone power table, 11 + 6 + 6 + 3x5 = 38 for the 5-zone HR one.
ZONE_WIDE_COL = 6
ZONE_COL = 5
NOT_TRAINED = "—"
UNDERCOUNTED = "!"

# The future half: this week's cells are what the plan PRESCRIBES, not what was measured
# (DESIGN_intensity_distribution.md §9.8).
PLANNED = "+"
# Not a glyph — a footer note. The plan for this sport was written in the other currency,
# so no comparison is offered: power Z6/Z7 have no HR equivalent and collapsing seven onto
# five would be banding by the back door.
CURRENCY_MISMATCH = "~mismatch"


def fmt_zone_cell(seconds: float) -> str:
    """A zone's time capped to four characters — `55m`, `5h00`, `12h`, `—` for none.

    `zone_tables.fmt_duration` renders `12h30` at five characters, and a 7-zone power table
    of five-character cells is 55 columns — it overruns the budget precisely for the
    high-volume cyclist the power table exists to serve. Z3 and above never reach ten
    hours in a week, so nothing above tempo loses precision anywhere (§9.6).
    """
    minutes = int(round((seconds or 0.0) / 60.0))
    if minutes <= 0:
        return NOT_TRAINED
    if minutes < 60:
        return f"{minutes}m"
    hours = minutes // 60
    return f"{hours}h" if hours >= 10 else f"{hours}h{minutes % 60:02d}"


def zone_col_widths(n_zones: int) -> List[int]:
    return [ZONE_WIDE_COL, ZONE_WIDE_COL][:n_zones] + [ZONE_COL] * max(0, n_zones - 2)


def _zone_cells_row(label: str, cells: Sequence[str]) -> str:
    widths = zone_col_widths(len(cells))
    body = "".join(
        pad_visible(c, w, align_left=False) for c, w in zip(cells, widths)
    )
    return pad_visible(label, WEEK_COL_WIDTH) + body


def zone_week_cells(
    week: Dict[str, Any], sport: str, currency: str, n_zones: int
) -> Tuple[List[str], bool]:
    """`(cells, undercounted)` for one week of one sport's table.

    Three states, not two (§9.6): no duration is not-trained and renders `—` unmarked;
    duration with nothing recorded in this currency renders `—` and takes a `!`, because
    asserting the athlete simply did not train would be §7's meaning turned exactly
    backwards; a real row renders its minutes and takes a `!` below the display bar.

    The unrecorded branch reads the JUDGEABLE duration, so one 5-minute unrecorded
    activity does not light the week — §11's floor, applied to both `!` paths.
    """
    state = intensity.week_zone_state(week, sport, currency)
    if state.seconds is None:
        return [NOT_TRAINED] * n_zones, state.undercounted
    return [fmt_zone_cell(s) for s in state.seconds], state.undercounted


def planned_week_cells(
    week: Dict[str, Any], sport: str, currency: str, n_zones: int
) -> Tuple[List[str], bool]:
    """`(cells, currency_mismatch)` for a FUTURE week — what the plan prescribes (§9.8).

    Comparison is offered only when the planned currency matches the displayed one.
    Power Z6 (anaerobic) and Z7 (neuromuscular) have no HR equivalent, so collapsing
    seven onto five would be banding by the back door and §5 forbids it. A mismatch
    therefore renders `—` and says why in the footer rather than converting.
    """
    state = intensity.week_zone_state(week, sport, currency, is_future=True)
    if state.seconds is not None:
        return [fmt_zone_cell(s) for s in state.seconds], False
    return [NOT_TRAINED] * n_zones, state.currency_mismatch


def _legend(text: str) -> List[str]:
    """One legend paragraph wrapped into the table's budget, continuations indented so
    they read as the same line rather than as a new one."""
    return textwrap.wrap(
        text, width=TABLE_WIDTH, subsequent_indent="  ", break_on_hyphens=False
    ) or [text]


def zone_table(
    weeks: List[Dict[str, Any]], sport: str, currency: str,
    sport_seconds: float, window_seconds: float, coverage: float,
    today: Optional[str] = None,
) -> Tuple[List[str], set]:
    """One sport's weekly zone table plus the set of glyphs it actually used: header,
    column row, band rules, one row per week.

    Past and in-progress weeks carry what was MEASURED; weeks beyond today carry what the
    plan PRESCRIBES, ghost rows under today exactly like the load table's ghost bars
    (§9.8). The current week sits inline with full weeks, marked `*`: the marker is what
    §4's argument asks for at weekly grain, and a separate section for one week would cost
    more than it saves.
    """
    spec = intensity.CURRENCY_BY_KEY[currency]
    n_zones = len(spec.labels)
    tag = "pwr" if currency == "power" else "HR"
    lines = _legend(
        f"ZONES {sport} [{tag} {coverage * 100:.0f}%] — "
        f"{zone_tables.fmt_duration(sport_seconds)} of "
        f"{zone_tables.fmt_duration(window_seconds)} total"
    )
    lines = [bold(lines[0])] + lines[1:]
    lines.append(_zone_cells_row(
        "week", [f"Z{i}" for i in range(1, n_zones + 1)]
    ))

    used: set = set()
    current_label: Any = NO_BAND
    for week in weeks:
        label = week.get("meso_label")
        if label != current_label:
            lines.append(gray(band_header(label)))
            current_label = label
        week_label = f"w/c {short_date(week['week_commencing'])}"
        is_future = (
            today is not None
            and week["week_commencing"] > today
            and not week.get("in_progress")
        )
        if is_future:
            cells, mismatch = planned_week_cells(week, sport, currency, n_zones)
            if any(c != NOT_TRAINED for c in cells):
                week_label += PLANNED
                used.add(PLANNED)
            if mismatch:
                used.add(CURRENCY_MISMATCH)
        else:
            cells, undercounted = zone_week_cells(week, sport, currency, n_zones)
            if week.get("in_progress"):
                week_label += "*"
            if undercounted:
                week_label += UNDERCOUNTED
                used.add(UNDERCOUNTED)
        used.update(c for c in cells if c == NOT_TRAINED)
        lines.append(_zone_cells_row(week_label, cells))

    names = " · ".join(
        f"Z{i} {label}" for i, label in enumerate(spec.labels, start=1)
    )
    lines.extend(gray(l) for l in _legend(f"{names} · * in progress"))
    return lines, used


def zone_section(
    weeks: List[Dict[str, Any]], preferences: Sequence[str],
    explicit: Optional[Sequence[str]] = None, forced_currency: Optional[str] = None,
    hidden_weeks: int = 0, today: Optional[str] = None,
    stats_weeks: Optional[List[Dict[str, Any]]] = None,
) -> List[str]:
    """Every zone table plus the shared footer, or the empty-state line.

    `weeks` is the whole displayed window, past and future (§9.8); `stats_weeks` is the past
    half, since every filter reads MEASURED coverage. The default stacks one table
    per qualifying sport, because fixing the grain to a single sport buys legibility at
    the price of a new lie: an athlete who swapped two planned runs for two rides of equal
    TSS reads a running-only table as whole-athlete load held flat beside a collapsed
    aerobic base — the exact signature of intensity creep, on a week where nothing went
    wrong. The cycling table rising as the running table falls makes "they rode instead"
    self-evident (§9.6).
    """
    # The sport filter, the 10% floor and the currency choice all read MEASURED coverage,
    # so they are computed over the past weeks even when future ones are drawn (§9.6).
    stats = window_sport_stats(weeks if stats_weeks is None else stats_weeks)
    window_seconds = sum(agg["seconds"] for agg in stats.values())
    sports, low, no_data = select_zone_sports(explicit, preferences, stats)

    lines: List[str] = []
    drawn: List[str] = []
    used_markers: set = set()
    for sport in sports:
        agg = stats.get(sport)
        currency = zone_currency(stats, sport, forced_currency)
        if not agg or currency is None:
            continue
        if lines:
            lines.append("")
        table, markers = zone_table(
            weeks, sport, currency, agg["seconds"], window_seconds,
            agg["coverage"].get(currency, 0.0), today=today,
        )
        lines.extend(table)
        drawn.append(sport)
        used_markers |= markers

    if not drawn:
        # Both failures key on *no rows in the window*, not on *not a known sport*:
        # `canonical_sport` passes unknown values through stripped and lowercased, so
        # nothing is unrecognised at that layer and the list must come from the data.
        have = sorted(
            s for s, agg in stats.items() if any(agg["zone_seconds"].values())
        )
        asked = ", ".join(canonical_sport(s) for s in explicit) if explicit else None
        if asked:
            lines.extend(yellow(l) for l in _legend(
                f"No zone data for {asked} in this window."
            ))
        else:
            lines.extend(yellow(l) for l in _legend(
                "No zone data in this window."
            ))
        if have:
            lines.extend(gray(l) for l in _legend(
                f"Sports with zone data here: {', '.join(have)}"
            ))
        return lines

    footer: List[str] = []
    parts = []
    if NOT_TRAINED in used_markers:
        parts.append(f"{NOT_TRAINED} not trained")
    if UNDERCOUNTED in used_markers:
        # Says nothing about the TSS beside it: the load fallback swaps at
        # `hr_zone_coverage_min`, not at the display bar, so across most of the 0.5-0.8
        # band the week's TSS is still hrTSS computed from these very seconds (§9.6).
        parts.append(
            f"{UNDERCOUNTED} zone minutes undercounted — the recording missed time"
        )
    if PLANNED in used_markers:
        parts.append(f"{PLANNED} planned, not yet ridden")
    if parts:
        footer.extend(_legend(" · ".join(parts)))
    if CURRENCY_MISMATCH in used_markers:
        footer.extend(_legend(
            "Some planned sessions were written in the other currency — no comparison "
            "is offered for those weeks. The next plan generation re-picks it."
        ))
    if no_data:
        footer.extend(_legend(
            f"{', '.join(no_data)}: activities but no zone recording in this window"
        ))
    if low:
        footer.extend(_legend(
            f"{', '.join(low)} omitted (under {ZONE_SPORT_MIN_SHARE * 100:.0f}% of "
            f"volume) — name them to see: tm progress {low[0]}"
        ))
    if hidden_weeks:
        footer.append(f"+{hidden_weeks} more weeks (--weeks all)")
    lines.extend(gray(l) for l in footer)
    return lines


def unknown_sport_preferences(preferences: Sequence[str]) -> List[str]:
    """Warnings for `sport_preferences` entries that are not canonical sports (§9.6).

    A warning and not an error: `SPORT_MAPPING` has no `swimming` or `rowing` entry and a
    genuinely new sport must still round-trip. Emitted here, where the list is consumed,
    and not in `Config.__init__` — `config.py` has no validation pass and is imported in
    every process, so a warning there would greet `tm --help`, the Telegram bot and the
    web app alike, none of which read this list.
    """
    import difflib
    out = []
    for name in preferences:
        key = canonical_sport(name)
        if key in SPORT_MAPPING:
            continue
        close = difflib.get_close_matches(key, list(SPORT_MAPPING), n=1, cutoff=0.6)
        hint = f" Did you mean '{close[0]}'?" if close else ""
        out.append(
            f"sport_preferences: '{name}' is not a known sport — it will be matched "
            f"literally against activity types.{hint}"
        )
    return out


def _mesocycles_in_window(dbh, start: str, end: str) -> List[Dict[str, Any]]:
    """Every mesocycle overlapping `start..end`, plus the mesocycle preceding the first of
    them so §4.1's delta has a left-hand side.

    The preceding plan is the previous *goal's* — the one that governed the window's
    earlier dates — never an earlier version of this goal's own, which was superseded
    before it was ever trained (DESIGN_plan_rollback.md §6.1).
    """
    governing = dbh.get_governing_macrocycle()
    preceding = (
        dbh.get_preceding_macrocycle(governing["objective_id"]) if governing else None
    )
    return plan_lineage(dbh, [preceding, governing])


def _orphan_week_note(
    weeks: List[Dict[str, Any]], reported: List[Dict[str, Any]]
) -> List[str]:
    """The weeks in the window that belong to no reported mesocycle, named.

    `--mesocycles` reproduces the very loss §9.6 exists to prevent, and by more than one
    route: weeks belonging to no mesocycle are silently absent, and `rate_window`
    additionally excludes each mesocycle's partial tail from both sides of its division —
    correctly, and invisibly, dropping up to six more days per mesocycle. Silence would be
    the mesocycle-grained blindness this section was written about, reintroduced by the flag
    that opts into mesocycle grain.
    """
    orphans = []
    for week in weeks:
        mon = week["week_commencing"]
        sun = parse_date(mon) + timedelta(days=6)
        sun_s = sun.strftime("%Y-%m-%d")
        if not any(
            b["start_date"] <= sun_s and b["end_date"] >= mon for b in reported
        ):
            orphans.append(short_date(mon))
    if not orphans:
        return []
    shown = orphans[:2]
    tail = f", +{len(orphans) - len(shown)} more" if len(orphans) > len(shown) else ""
    return _legend(
        f"{len(orphans)} week{'s' if len(orphans) != 1 else ''} in this window "
        f"belong to no mesocycle ({', '.join(shown)}{tail}), and each mesocycle's final partial "
        f"week is excluded from its rate — run without --mesocycles for the weekly view"
    )


def render_mesocycle_section(
    dbh, payload: Dict[str, Any], weeks_window: Any, today: str,
    explicit: Sequence[str], preferences: Sequence[str],
) -> List[str]:
    """`--mesocycles`: the graded view, per mesocycle instead of per week (§9.6).

    Two grains, two questions — the week table answers *when did it change*, the mesocycle
    table answers *did the mesocycle do what it said*. Only the mesocycle has a stated intent to
    be graded against, which is why the weekly table carries no verdict and no focus. It
    REPLACES the weekly zone table rather than appending to it: the flag is a choice of
    grain, not an extra section.

    Single-sport, because N sports x M mesocycles is not a view. And it trades brevity for
    grain rather than the other way round — a single mesocycle runs about 25 lines at phone
    width — so the help text says so.
    """
    weeks, _, _ = timeline.select_weeks(payload["weeks"], weeks_window, today)
    if not weeks:
        return []
    window_start = weeks[0]["week_commencing"]

    stats = window_sport_stats(weeks)
    sports, _, _ = select_zone_sports(explicit, preferences, stats)
    if not sports:
        return [yellow("No sport with zone data in this window.")]
    sport = sports[0]

    def fetch(start: str, end: str) -> List[Dict[str, Any]]:
        return [
            a for a in dbh.get_completed_activities(start_date=start, end_date=end)
            if canonical_sport(a.get("activity_type") or "unknown") == sport
        ]

    mesocycles = _mesocycles_in_window(dbh, window_start, today)
    benchmarks = dbh.get_benchmark_results()
    lines: List[str] = [bold(f"ZONES BY MESOCYCLE — {sport}")]
    reported: List[Dict[str, Any]] = []
    for i, meso in enumerate(mesocycles):
        if meso["end_date"] < window_start or meso["start_date"] > today:
            continue
        text = mesocycle_report(
            meso, today, fetch,
            current_week=meso["start_date"] <= today <= meso["end_date"],
            previous=delta_baseline(mesocycles, i),
            benchmarks=benchmarks, notes=False, indent="", width=TABLE_WIDTH,
        )
        if text:
            lines.append("")
            lines.extend(text.split("\n"))
            reported.append(meso)

    if not reported:
        return [yellow("No mesocycle overlaps this window.")]

    # Once per section, under the last mesocycle — `mesocycle_report` printing its own would
    # render the same two caveats three times over three mesocycles (§9.6). Standing
    # boilerplate, so terminal-only (DESIGN_output_verbosity.md §3.2).
    rows = intensity.zone_rows(fetch(window_start, today))
    notes = zone_tables.format_notes(rows, width=TABLE_WIDTH) if asides_enabled() else []
    if notes:
        lines.append("")
        lines.extend(gray(n) for n in notes)
    orphan = _orphan_week_note(weeks, reported)
    if orphan:
        lines.append("")
        lines.extend(gray(o) for o in orphan)
    return lines
