"""The progress payload: mesocycle bands, the warnings, the assembly and the clipping.

`progression.py` computes the series; this module turns them into the one §6.0 payload
every front-end draws, so `sm progress`, the chart and `/api/timeline.png` cannot
disagree about the same day (DESIGN_progress_timeline.md §6.0). Row-in, row-out: the
fetch that feeds it is `stamind/timeline_rows.py`, which is outside
`stamind/analytics/` because it reads the database.
"""
from datetime import timedelta
from typing import Any, Dict, List, Optional, Tuple

from stamind.analytics import pmc as pmc_math
from stamind.analytics.load import planned_load
from stamind.analytics.progression import (
    daily_loads, fitness_series, weekly_aggregates,
)
from stamind.analytics.runway import plan_dates, plan_end, plan_gap
from stamind.clock import day_str, parse_date


def _plural(n: int) -> str:
    return "s" if n != 1 else ""


def _history_start(
    activities: List[Dict[str, Any]], metrics_rows: List[Dict[str, Any]]
) -> Optional[str]:
    """Earliest Garmin evidence — min(first activity, first metrics row), mirroring
    `garmin.pmc_history_start` but over the rows the caller already handed in (so the
    young-DB caveat stays row-in/row-out, §4)."""
    dates = [a["date"] for a in activities] + [m["date"] for m in metrics_rows]
    return min(dates) if dates else None


def zero_load_workout_count(workouts: List[Dict[str, Any]], today: str) -> int:
    """Count of non-removed, non-rest planned workouts **from today on** that value to
    0 load — no usable TSS and no RPE+duration, so `planned_load` falls back to 0 (§3).

    Dated from today because the warning is about rows feeding the *projection*:
    counting the whole table left the banner permanently lit by history nobody can
    fix (CODE_REVIEW finding, 'the stale-workout warning never heals')."""
    return sum(
        1 for w in workouts
        if not w.get("removed") and w.get("sport_type") != "rest"
        and w["date"] >= today and planned_load(w) == 0
    )


def _valid_span(start: Any, end: Any) -> bool:
    """Whether an inferred (LLM-authored) mesocycle has parseable dates with
    start <= end — the guard for §6.1's 'unparseable dates are skipped'."""
    try:
        return bool(start) and bool(end) and parse_date(start) <= parse_date(end)
    except (ValueError, TypeError):
        return False


def _subtract_spans(
    span: Tuple[str, str], cutters: List[Tuple[str, str]]
) -> List[Tuple[str, str]]:
    """Date-interval subtraction (inclusive): removes each cutter from `span`,
    returning the remaining sub-intervals (0, 1, or more). Used to trim inferred
    bands where plan bands cover part of them (§6.1 band trimming)."""
    pieces = [span]
    for cs, ce in cutters:
        next_pieces: List[Tuple[str, str]] = []
        for s, e in pieces:
            if ce < s or cs > e:  # no overlap
                next_pieces.append((s, e))
                continue
            if s < cs:  # left remainder, up to the day before the cutter
                next_pieces.append((s, day_str(parse_date(cs) - timedelta(days=1))))
            if ce < e:  # right remainder, from the day after the cutter
                next_pieces.append((day_str(parse_date(ce) + timedelta(days=1)), e))
        pieces = next_pieces
    return pieces


def meso_bands(
    mesocycles: List[Dict[str, Any]],
    inferred_mesocycles: List[Dict[str, Any]],
) -> List[Dict[str, Any]]:
    """The layered mesocycle band list (§6.1), most authoritative first, with no
    overlaps in the output:

    - **Plan bands** — the governing objective's mesocycles (the caller resolves
      which plan governs via `db.get_governing_macrocycle`), labelled by name.
    - **Inferred bands** — the bootstrap reconstruction's mesocycles, `~`-prefixed and
      `source='inferred'`. Mesocycles with unparseable dates are skipped; the survivors
      are trimmed to the parts no plan band covers, and dropped where fully covered
      (plan wins). The payload therefore never contains overlapping bands — renderers
      draw spans as given."""
    plan_bands = [
        {"label": m["name"], "source": "plan",
         "start_date": m["start_date"], "end_date": m["end_date"]}
        for m in sorted(mesocycles, key=lambda m: m["start_date"])
    ]
    plan_spans = [(b["start_date"], b["end_date"]) for b in plan_bands]

    inferred_bands: List[Dict[str, Any]] = []
    for m in sorted(
        (m for m in inferred_mesocycles if _valid_span(m.get("start_date"), m.get("end_date"))),
        key=lambda m: m["start_date"],
    ):
        for s, e in _subtract_spans((m["start_date"], m["end_date"]), plan_spans):
            inferred_bands.append({
                "label": f"~{m['name']}", "source": "inferred",
                "start_date": s, "end_date": e,
            })

    return sorted(plan_bands + inferred_bands, key=lambda b: b["start_date"])


def _warning(code: str, text: str, command: Optional[str] = None) -> Dict[str, Any]:
    """One payload warning. `code` is what renderers dispatch on and `command` is what
    a surface may style as a call to action — so nobody has to recognise a warning by
    matching its prose (§6.0)."""
    w: Dict[str, Any] = {"code": code, "text": text}
    if command:
        w["command"] = command
    return w


def assemble_timeline(
    activities: List[Dict[str, Any]],
    workouts: List[Dict[str, Any]],
    metrics_rows: List[Dict[str, Any]],
    mesocycles: List[Dict[str, Any]],
    inferred_mesocycles: List[Dict[str, Any]],
    objectives: List[Dict[str, Any]],
    today: str,
    ctl_days: int,
    atl_days: int,
    warmup_cutoff: Optional[str],
) -> Dict[str, Any]:
    """The ENTIRE §6.0 timeline payload — days, weeks, meso_bands, objectives,
    plan_gap, warnings — built here and ONLY here, from the §5 helpers plus the §6.1
    layered lookup. Callers do db reads and hand rows in; neither the CLI handler nor
    the web endpoint owns any assembly or warning-wording logic, so the two surfaces
    render one payload (the fix for the rev-4 divergence, CODE_REVIEW #5).

    `objectives` are ALL active AND completed objectives, unfiltered — a race weeks
    ago still gets its flag; renderers clip to their window. Stays row-in/row-out.
    """
    warnings: List[Dict[str, Any]] = []

    if not activities:
        # §3 empty state: no past series and no PMC, but the planned future still
        # renders (weekly bars); every surface shows this.
        warnings.append(_warning(
            "no_history", "no activity history yet — run `data pull` first",
            command="data pull",
        ))

    valid_inferred = [
        m for m in inferred_mesocycles
        if _valid_span(m.get("start_date"), m.get("end_date"))
    ]
    skipped = len(inferred_mesocycles) - len(valid_inferred)
    if skipped:
        warnings.append(_warning(
            "bootstrap_dates",
            f"{skipped} bootstrap mesocycle{_plural(skipped)} skipped "
            f"— unparseable dates",
        ))
    bands = meso_bands(mesocycles, valid_inferred)

    # One plan-end scan for the whole payload: `end` (payload `plan_end`, or None) and
    # the merged-series window derived from it, threaded into both series builders so
    # they don't each re-walk the workouts (mirrors `_window_end`'s rule).
    end = plan_end(workouts)
    window_end = end if (end and end > today) else today

    day_points = daily_loads(activities, workouts, today, window_end=window_end)
    days = fitness_series(
        day_points, metrics_rows, today, ctl_days, atl_days, warmup_cutoff
    )

    weeks = weekly_aggregates(
        activities, workouts, today, bands, window_end=window_end
    )

    zero_count = zero_load_workout_count(workouts, today)
    if zero_count:
        warnings.append(_warning(
            "zero_load_workouts",
            f"{zero_count} planned workout{_plural(zero_count)} lack TSS/RPE "
            f"— count as 0",
        ))

    gap = None
    if end is not None:
        gap = plan_gap(objectives, end)

    history_start = _history_start(activities, metrics_rows)
    caveat = pmc_math.pmc_data_caveat(history_start, as_of=today)
    if caveat:
        warnings.append(_warning(
            "pmc_warming",
            f"PMC still warming: CTL based on {caveat['n_days']} days of history",
        ))

    covered = plan_dates(workouts)
    return {
        "today": today,
        # Both edges: a plan that begins or ends mid-week leaves that week's planned
        # total covering fewer days than its actual, which the footnote names (§3).
        "plan_start": min(covered) if covered else None,
        "plan_end": end,
        "days": days,
        "weeks": weeks,
        "meso_bands": bands,
        "objectives": objectives,
        # Structured, not a `warnings` string: the CLI draws it as a three-line banner
        # rather than prefix-matching prose to recover the same facts.
        "plan_gap": (
            {"objective": gap[0], "weeks_before": gap[1], "plan_end": end}
            if gap else None
        ),
        "warnings": warnings,
    }


def clip_payload(
    payload: Dict[str, Any], start_date: str, end_date: str
) -> Dict[str, Any]:
    """A window-clipped view of an `assemble_timeline` payload for one renderer
    (§6.0). `days` clip by date; `weeks` and `meso_bands` are returned **whole**
    whenever they overlap the window (reslicing a straddling week would corrupt its
    adherence percentage), never silently dropped. `objectives` pass through whole —
    the renderer clips flags to its own window. The stored series is full-history and
    the fold starts at the anchor, so clipping never changes any value inside the
    window."""
    def week_overlaps(w: Dict[str, Any]) -> bool:
        ws = w["week_commencing"]
        we = day_str(parse_date(ws) + timedelta(days=6))
        return ws <= end_date and we >= start_date

    return {
        **payload,
        "days": [d for d in payload["days"] if start_date <= d["date"] <= end_date],
        "weeks": [w for w in payload["weeks"] if week_overlaps(w)],
        "meso_bands": [
            b for b in payload["meso_bands"]
            if b["start_date"] <= end_date and b["end_date"] >= start_date
        ],
    }


def select_weeks(
    weeks: List[Dict[str, Any]], weeks_window: Any, today: str
) -> Tuple[List[Dict[str, Any]], List[Dict[str, Any]], int]:
    """`(past, future, hidden)` — the weeks a surface shows for `--weeks`, and how many
    it drops. `weeks_window` is a positive int (that many either side of today) or
    ``'all'``.

    THE one answer to "which weeks", so the text table, the `--chart` window and the
    `--mesocycles` section cannot disagree about the span they are all describing (§7.1).
    `hidden` covers both sides: a default run over a long history drops far more past
    weeks than projected ones, and the legend names the total."""
    past = [w for w in weeks if w["week_commencing"] <= today]
    future = [w for w in weeks if w["week_commencing"] > today]
    if weeks_window == "all":
        return past, future, 0
    n = int(weeks_window)
    shown_past, shown_future = past[-n:], future[:n]
    hidden = (len(past) - len(shown_past)) + (len(future) - len(shown_future))
    return shown_past, shown_future, hidden


def clip_payload_for_weeks(
    payload: Dict[str, Any], weeks: Any, today: str, *, cap_future: bool = False
) -> Dict[str, Any]:
    """A payload windowed to what `select_weeks` shows (§6.0/§7.1) — the date form of
    the same decision, for the chart and the web endpoint.

    `cap_future` cuts the projection to the last projected week shown. The CLI passes
    it so `--chart` frames the same span its text table does; the web endpoint leaves
    it off — an `<img>` has no accompanying table to agree with, and the whole
    projection is what that panel is for (§7.3)."""
    past, future, _ = select_weeks(payload["weeks"], weeks, today)
    start_date = past[0]["week_commencing"] if past else (
        future[0]["week_commencing"] if future else today
    )
    end_date = payload["plan_end"] or today
    if end_date < today:
        end_date = today
    if cap_future and future:
        last_sunday = parse_date(future[-1]["week_commencing"]) + timedelta(days=6)
        end_date = min(end_date, day_str(last_sunday))
    return clip_payload(payload, start_date, end_date)
