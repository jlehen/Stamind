"""The mesocycle intensity report: one text block per mesocycle, built from the tables.

Rates over completed weeks only, so unequal mesocycles compare like for like
(DESIGN_intensity_distribution.md §4). The window helpers that decide what
"completed" means live here because the report is what divides by them.
"""
from datetime import date, timedelta
from typing import Any, Callable, Dict, List, Optional, Sequence, Tuple

from trainmate.analytics.intensity import planned_zone_rows, zone_rows
from trainmate.analytics.load import activity_load, rpe_tss
from trainmate.analytics.zone_tables import (
    PROMPT_WIDTH, fmt_duration, format_coverage, format_delta_table, format_notes,
    format_table, wrap_line,
)
from trainmate.benchmarks import format_delta, format_value, label_for_kind
from trainmate.clock import day_str, parse_date
from trainmate.sports import canonical_sport

FetchActivities = Callable[[str, str], List[Dict[str, Any]]]
# Same shape, planned side: returns the workouts in an inclusive window. Only the
# periodization consumer passes one (§9.2a).
FetchWorkouts = Callable[[str, str], List[Dict[str, Any]]]

# --------------------------------------------------------------------- dates

def counted_days(start: str, end: str, as_of: str) -> int:
    """Days of the mesocycle that are over: elapsed before `as_of`, capped at the mesocycle's
    own span. Zero or negative means the mesocycle has not started."""
    span = (parse_date(end) - parse_date(start)).days + 1
    return min((parse_date(as_of) - parse_date(start)).days, span)


def rate_window(start: str, end: str, as_of: str) -> Optional[Tuple[str, str, int]]:
    """``(window_start, window_end, completed_weeks)`` — the whole 7-day weeks of a mesocycle
    finished by `as_of`, the only span a per-week rate may divide (§4).

    Weeks run from the mesocycle's own start, not calendar Mondays, so mesocycles compare
    like for like. The partial tail is excluded from BOTH sides of the division;
    including it understates easy volume every time, in the same direction, because
    the long easy session sits on the weekend. None when under a week has elapsed.
    """
    days = counted_days(start, end, as_of)
    weeks = days // 7 if days > 0 else 0
    if weeks < 1:
        return None
    return start, day_str(parse_date(start) + timedelta(days=weeks * 7 - 1)), weeks


def current_week_window(start: str, end: str, as_of: str) -> Optional[Tuple[str, str, int]]:
    """``(week_start, as_of, day_of_week)`` for the week in progress (§9.3), or None when
    `as_of` sits outside the mesocycle or exactly on a week boundary with nothing elapsed."""
    if not (start <= as_of <= end):
        return None
    elapsed = (parse_date(as_of) - parse_date(start)).days
    if elapsed < 0:
        return None
    week_start = parse_date(start) + timedelta(days=(elapsed // 7) * 7)
    return day_str(week_start), as_of, elapsed % 7 + 1


def measured_window(start: str, end: str, as_of: str) -> Tuple[str, str, int]:
    """``(window_start, window_end, weeks)`` — the window a mesocycle's zone table divides.

    The whole-week rate window where one exists (§4), else the mesocycle's elapsed span raw
    with ``weeks = 0``, which is how `mesocycle_report` labels a mesocycle too young to average.
    Shared so a caller deciding whether a table will HAVE rows asks about the same window
    the table is built from.
    """
    win = rate_window(start, end, as_of)
    return win if win else (start, min(as_of, end), 0)


def mesocycle_weeks(start: str, end: str) -> int:
    """The mesocycle's planned length in weeks, rounded up — the denominator of
    '2 completed weeks of 4'."""
    return max(1, ((parse_date(end) - parse_date(start)).days + 7) // 7)


# -------------------------------------------------------------- structural

def format_structural(
    activities: Sequence[Dict[str, Any]],
    benchmarks: Optional[Sequence[Dict[str, Any]]],
    start: str, end: str, indent: str = "", width: int = PROMPT_WIDTH,
) -> List[str]:
    """The non-zone view: session counts, RPE and sRPE load per sport, plus any threshold
    that moved inside the window.

    No sport is routed away from the zone table into this one (§6) — a HIIT kettlebell
    activity's Z4 minutes are real work, and dropping them tells a coach to prescribe
    intensity on top of intensity already done. This section sits BESIDE the zone rows,
    never instead of them.
    """
    by_sport: Dict[str, Dict[str, float]] = {}
    order: List[str] = []
    for act in activities:
        sport = canonical_sport(act.get("activity_type") or "unknown")
        if sport not in by_sport:
            by_sport[sport] = {"n": 0, "sec": 0.0, "rpe_sum": 0.0, "rpe_n": 0, "srpe": 0.0}
            order.append(sport)
        agg = by_sport[sport]
        duration_sec = float(act.get("duration_sec") or 0.0)
        agg["n"] += 1
        agg["sec"] += duration_sec
        rpe = act.get("rpe")
        if rpe:
            agg["rpe_sum"] += float(rpe)
            agg["rpe_n"] += 1
            agg["srpe"] += rpe_tss(float(rpe), duration_sec)

    lines: List[str] = []
    rows = [(s, by_sport[s]) for s in order if by_sport[s]["rpe_n"]]
    kinds = {r["anchor_kind"] for r in (benchmarks or []) if start <= r["date"] <= end}
    label_width = max(
        [len(s) for s, _ in rows]
        + [len(label_for_kind(k)) for k in kinds]
        + [4]
    )
    for sport, agg in rows:
        n = int(agg["n"])
        lines.append(
            f"{indent}{sport.ljust(label_width)}  {n} activit{'ies' if n != 1 else 'y'}, "
            f"{fmt_duration(agg['sec'])}, avg RPE {agg['rpe_sum'] / agg['rpe_n']:.1f}, "
            f"{agg['srpe']:.0f} sRPE load"
        )
    for line in _benchmark_lines(benchmarks or [], start, end, label_width, indent):
        lines.append(line)
    return lines


def _benchmark_lines(
    benchmarks: Sequence[Dict[str, Any]], start: str, end: str,
    label_width: int, indent: str,
) -> List[str]:
    """One line per anchor kind that has a value in the window, measured against the
    latest reading before it. e1RM collides across lifts (§10) — track one lift."""
    by_kind: Dict[str, List[Dict[str, Any]]] = {}
    for row in benchmarks:
        by_kind.setdefault(row["anchor_kind"], []).append(row)
    out: List[str] = []
    for kind in sorted(by_kind):
        rows = sorted(by_kind[kind], key=lambda r: (r["date"], r.get("id") or 0))
        inside = [r for r in rows if start <= r["date"] <= end]
        if not inside:
            continue
        before = [r for r in rows if r["date"] < start]
        label = label_for_kind(kind).ljust(label_width)
        latest = float(inside[-1]["value"])
        if not before:
            out.append(f"{indent}{label}  {format_value(kind, latest)} (first on record)")
            continue
        baseline = float(before[-1]["value"])
        delta = format_delta(kind, latest, baseline)
        suffix = f" ({delta})" if delta else ""
        out.append(
            f"{indent}{label}  {format_value(kind, baseline)} -> "
            f"{format_value(kind, latest)}{suffix}"
        )
    return out


# ------------------------------------------------------------ the assembler

def format_header(meso: Dict[str, Any], as_of: str, with_focus: bool = True) -> str:
    """'Build 1 — focus "threshold development" (2 completed weeks of 4, plus 2 days)'.

    Rates, not totals: mesocycles are unequal length and the current one is always partial,
    so the reader is told exactly what divided the numbers (§4). `with_focus` is off for
    the CLI, which has already printed the focus above the table."""
    start, end = meso["start_date"], meso["end_date"]
    days = max(0, counted_days(start, end, as_of))
    weeks, spare = days // 7, days % 7
    total = mesocycle_weeks(start, end)
    parts = [f"{weeks} completed week{'s' if weeks != 1 else ''}"]
    if weeks < total:
        parts[0] += f" of {total}"
    if spare:
        parts.append(f"plus {spare} day{'s' if spare != 1 else ''}")
    if not with_focus:
        return f"{meso['name']} ({', '.join(parts)})"
    focus = meso.get("focus") or "unstated"
    return f"{meso['name']} — focus \"{focus}\" ({', '.join(parts)})"


class _WindowCache:
    """Serves overlapping sub-windows of one span from a single fetch.

    `mesocycle_report` asks its fetcher for up to four windows per mesocycle — elapsed, the
    rate window, the current week, the previous mesocycle — and all but the last are
    sub-ranges of the mesocycle itself. Against the database that was four queries per
    mesocycle, which `progress --mesocycles` multiplied by the number of mesocycles. Dates are
    ISO strings, so slicing by comparison is chronological.
    """

    def __init__(self, fetch: "FetchActivities", span_start: str, span_end: str):
        self._fetch = fetch
        self._start, self._end = span_start, span_end
        self._rows: Optional[List[Dict[str, Any]]] = None
        self.calls = 0

    def __call__(self, start: str, end: str) -> Sequence[Dict[str, Any]]:
        if start < self._start or end > self._end:
            # Outside the span we cached (the previous mesocycle); ask directly.
            self.calls += 1
            return self._fetch(start, end)
        if self._rows is None:
            self.calls += 1
            self._rows = list(self._fetch(self._start, self._end))
        return [a for a in self._rows if start <= str(a.get("date") or "") <= end]


def mesocycle_report(
    meso: Dict[str, Any],
    as_of: str,
    fetch_activities: FetchActivities,
    *,
    current_week: bool = False,
    previous: Optional[Dict[str, Any]] = None,
    benchmarks: Optional[Sequence[Dict[str, Any]]] = None,
    fetch_workouts: Optional[FetchWorkouts] = None,
    with_focus: bool = True,
    notes: bool = True,
    indent: str = "  ",
    width: int = PROMPT_WIDTH,
) -> Optional[str]:
    """The whole intensity report for one mesocycle, or None when it has not started.

    `fetch_activities(start, end)` returns completed activities over an inclusive window.
    `current_week` adds the in-progress week as RAW minutes beside the elapsed fraction —
    never extrapolated, which would be a fabrication (§9.3). `previous` adds the
    mesocycle-over-mesocycle delta, which belongs to plan generation only (§4.1/§9.2).

    `fetch_workouts` adds what the plan PRESCRIBED over the same rate window, in the same
    units and format as the measured table — the pair that separates a mis-designed mesocycle
    from a mis-executed one (§9.2a). Only the periodization consumer passes it: measured
    diverging from the prescription is an execution question, and adapt owns those.

    `notes` off leaves the measurement caveats to the caller: three mesocycles in a row would
    otherwise repeat them three times, nine lines saying two things (§9.6). It defaults on
    for the prompt paths, which send one mesocycle each.

    The mesocycle it is given is the mesocycle it reports: no fallback to a future or first
    mesocycle, so a not-yet-started mesocycle renders nothing rather than an empty table (§8).
    """
    start, end = meso["start_date"], meso["end_date"]
    days = counted_days(start, end, as_of)
    if days <= 0:
        return None

    # One fetch covers every window inside this mesocycle; see _WindowCache.
    fetch_activities = _WindowCache(fetch_activities, start, max(end, as_of))

    inner = indent + "  "
    # Prose, so it wraps: at width=48 the header runs 57 characters and would break the
    # column contract the zone rows below it keep (§9.6).
    lines = wrap_line(format_header(meso, as_of, with_focus), indent, width)
    through = min(as_of, end)
    elapsed = fetch_activities(start, through)
    # Volume and load beside the distribution: load = volume x intensity, and this
    # feature exists because the third alone cannot recover the first two (§2).
    if not elapsed:
        lines.extend(wrap_line(
            f"No completed activities recorded in {start}..{through}.", inner, width
        ))
        return "\n".join(lines)
    lines.extend(wrap_line(
        f"Volume and load ({start}..{through}): {len(elapsed)} "
        f"activit{'ies' if len(elapsed) != 1 else 'y'}, "
        f"{fmt_duration(sum(float(a.get('duration_sec') or 0.0) for a in elapsed))}, "
        f"{sum(activity_load(a) for a in elapsed):.0f} TSS",
        inner, width,
    ))
    win_start, win_end, weeks = measured_window(start, end, as_of)
    rows = zone_rows(fetch_activities(win_start, win_end))
    if weeks:
        lines.extend(wrap_line(
            f"Intensity distribution, per week over {weeks} completed "
            f"week{'s' if weeks != 1 else ''} ({win_start}..{win_end})", inner, width
        ))
    else:
        lines.extend(wrap_line(
            f"Intensity distribution, RAW minutes ({win_start}..{win_end}) — the mesocycle is "
            f"{days} day{'s' if days != 1 else ''} old, too young for a per-week rate",
            inner, width
        ))

    if not rows:
        lines.append(f"{inner}  No zone data recorded in this window.")
    else:
        lines.extend(format_table(rows, divisor=weeks or 1, indent=inner + "  ", width=width))
        lines.extend(format_coverage(rows, indent=inner + "  ", width=width))
        if notes:
            lines.extend(format_notes(rows, indent=inner + "  ", width=width))

    # Beside the measured table, never instead of it: same rows, same divisor, same
    # renderer, so the two are compared line for line (§9.2a). Only over the rate window —
    # a prescription and a recording must divide the same weeks to be comparable. Silent
    # when the mesocycle's sessions carry no planned zones (nothing prescribed them, or they
    # predate §9.8): an empty table would read as "the plan asked for nothing".
    if fetch_workouts is not None and rows:
        planned = planned_zone_rows(fetch_workouts(win_start, win_end))
        if planned:
            lines.extend(wrap_line(
                "What the plan PRESCRIBED over the same "
                + ("weeks, per week" if weeks else "window (raw)"), inner, width
            ))
            lines.extend(format_table(
                planned, divisor=weeks or 1, indent=inner + "  ", width=width
            ))

    if previous and weeks:
        # A finished mesocycle's own last day is over, so measure it one day past its end —
        # counted_days counts days that are OVER, not days that exist.
        prev_window = rate_window(
            previous["start_date"], previous["end_date"],
            day_str(parse_date(previous["end_date"]) + timedelta(days=1)),
        )
        if prev_window:
            p_start, p_end, p_weeks = prev_window
            prev_rows = zone_rows(fetch_activities(p_start, p_end))
            delta = format_delta_table(
                rows, weeks, prev_rows, p_weeks, previous["name"],
                indent=inner + "  ", width=width,
            )
            if delta:
                lines.extend(wrap_line(
                    f"Change vs {previous['name']} "
                    f"({p_weeks} completed week{'s' if p_weeks != 1 else ''}), per week",
                    inner, width,
                ))
                lines.extend(delta)

    # With no completed week the raw table above already IS the current week — same
    # window, same numbers — so printing it twice says nothing new.
    if current_week and weeks:
        lines.extend(
            _current_week_lines(start, end, as_of, fetch_activities, inner, width)
        )

    structural = format_structural(
        elapsed, benchmarks, start, through, indent=inner + "  ", width=width,
    )
    if structural:
        lines.extend(wrap_line(f"Structural work ({start}..{through})", inner, width))
        lines.extend(structural)

    return "\n".join(lines)


def _current_week_lines(
    start: str, end: str, as_of: str, fetch_activities: FetchActivities,
    inner: str, width: int,
) -> List[str]:
    """The in-progress week: raw minutes and how much of the week has gone (§9.3).

    Two days in and already over the week's whole Z3 allowance is correctable NOW;
    the mesocycle-to-date average would take another fortnight to show it."""
    win = current_week_window(start, end, as_of)
    if win is None:
        return []
    week_start, week_end, day = win
    rows = zone_rows(fetch_activities(week_start, week_end))
    lines = wrap_line(
        f"Current week so far ({week_start}..{week_end}) — day {day} of 7 "
        f"({day / 7 * 100:.0f}% elapsed). RAW minutes, NOT extrapolated: read them "
        f"against that fraction yourself.", inner, width
    )
    if not rows:
        lines.append(f"{inner}  Nothing recorded yet this week.")
        return lines
    lines.extend(format_table(rows, with_pct=False, indent=inner + "  ", width=width))
    return lines
