"""Past (measured) and future (planned) load on one continuous day series, and the
CTL/ATL/TSB fitness/fatigue model run across the seam.

Pure functions, no singleton state. Rows are passed in by the caller (CLI handler / web
endpoint); nothing here touches `db` directly, so the same computation is shared verbatim
by every front-end (DESIGN_progress_timeline.md §5). `timeline.py` assembles these series
into the payload a front-end draws.

The past half is **read, not recomputed** (§4): CTL/ATL/TSB for days before today come
verbatim from the stored `athlete_metrics_cache` rows `analytics.pmc.compute_pmc` wrote, so
`tm progress` and `tm status` never disagree about the same day's fitness. The future
half is an *anchored fold*: the same recurrence folded forward from the latest stored
row over the merged daily loads — measured past → planned future.

One purity caveat, same as `adherence.py`'s: `analytics.load.activity_load` reads
`config` thresholds, so these functions are deterministic given rows + config rather
than rows alone.
"""
from datetime import timedelta
from typing import Any, Dict, List, Optional, Tuple

from stamind.analytics import intensity
from stamind.analytics import pmc as pmc_math
from stamind.analytics.load import activity_load, load_method, planned_load
from stamind.analytics.runway import plan_dates, plan_end
from stamind.clock import day_str, parse_date
from stamind.sports import canonical_sport


DayPoint = Dict[str, Any]  # {date, load, source: 'actual'|'planned',
#                            ctl, atl, tsb: float | None}
#   ctl/atl/tsb are None inside the warm-up window, on days with no stored
#   metrics row, and everywhere when there is no anchor (§4).
#   tsb is day-ENTERING form: CTL_{d-1} - ATL_{d-1}


def _monday(d):
    return d - timedelta(days=d.weekday())


def _window_end(workouts: List[Dict[str, Any]], today: str) -> str:
    """Last day the merged series should cover: `today` when there's no plan or the
    plan has already lapsed (plan end < today), else the plan-end date (§2's
    `max(today, plan end)`)."""
    end = plan_end(workouts)
    return end if (end and end > today) else today


def _series_start(
    activities: List[Dict[str, Any]], workouts: List[Dict[str, Any]]
) -> Optional[str]:
    """First day of the merged series: min(first activity, first planned workout)
    (§5/§6.0). With no activities but a plan already generated, "first activity" is
    undefined, so the plan's first workout seeds the series instead — the weekly
    bars still render the plan about to start (§3 empty state)."""
    dates = [a["date"] for a in activities]
    dates += plan_dates(workouts)
    return min(dates) if dates else None


def _group_by_date(rows: List[Dict[str, Any]]) -> Dict[str, List[Dict[str, Any]]]:
    grouped: Dict[str, List[Dict[str, Any]]] = {}
    for r in rows:
        grouped.setdefault(r["date"], []).append(r)
    return grouped


def daily_loads(
    activities: List[Dict[str, Any]],
    workouts: List[Dict[str, Any]],
    today: str,
    *,
    window_end: Optional[str] = None,
) -> List[DayPoint]:
    """Merged per-day load series (DESIGN_progress_timeline.md §3): past days are
    measured load (`analytics.load.activity_load` over `completed_activities`), future days
    are planned load (`analytics.load.planned_load` over non-removed `workouts`), today is
    actual if any completed activity **with load > 0** exists, else planned. Runs from
    min(first activity, first planned workout) through plan end (or today, if there's
    no plan or it's already lapsed) with no gaps — zero-load days are included.

    Empty only when there is neither an activity nor a planned workout to seed a
    series from."""
    start = _series_start(activities, workouts)
    if start is None:
        return []
    end = window_end if window_end is not None else _window_end(workouts, today)

    acts_by_date = _group_by_date(activities)
    workouts_by_date = _group_by_date([w for w in workouts if not w.get("removed")])

    points: List[DayPoint] = []
    d = parse_date(start)
    end_d = parse_date(end)
    while d <= end_d:
        date_str = day_str(d)
        day_acts = acts_by_date.get(date_str, [])
        # Measured load computed once (activity_load is non-negative, so >0 ≡ the
        # "any completed activity with load" test of the §3 today-rule).
        actual = sum(activity_load(a) for a in day_acts) if day_acts else 0.0
        if date_str < today or (date_str == today and actual > 0):
            load, source = actual, "actual"
        else:
            load = sum(planned_load(w) for w in workouts_by_date.get(date_str, []))
            source = "planned"
        points.append({"date": date_str, "load": load, "source": source})
        d += timedelta(days=1)
    return points


def _anchor(
    metrics_rows: List[Dict[str, Any]], today: str
) -> Optional[Tuple[str, float, float]]:
    """The projection anchor (§4): the latest stored metrics row dated **strictly
    before today** whose `ctl`/`atl` are both non-NULL, as `(date, ctl, atl)`.

    *Strictly before today* — a morning auto-ensure pull writes today's row (load 0)
    before the evening session; anchoring on it would drop today's planned session.
    *Non-NULL* — a pull that died before `recompute_derived()` leaves trailing NULL
    PMC rows; seeding from one is a TypeError, so skip back to the newest valid row.
    None when no such row exists (the no-anchor / young-DB state)."""
    best: Optional[Tuple[str, float, float]] = None
    for m in metrics_rows:  # sorted date ASC
        if m["date"] >= today:
            break
        if m.get("ctl") is not None and m.get("atl") is not None:
            best = (m["date"], float(m["ctl"]), float(m["atl"]))
    return best


def fitness_series(
    day_points: List[DayPoint],
    metrics_rows: List[Dict[str, Any]],
    today: str,
    ctl_days: int,
    atl_days: int,
    warmup_cutoff: Optional[str],
) -> List[DayPoint]:
    """Attaches CTL/ATL/TSB to each `daily_loads` point (DESIGN_progress_timeline.md
    §4). **Never recomputes the past.**

    - Past days (`date < today`): `ctl`/`atl`/`tsb` copied verbatim from the stored
      metrics row for that date, blanked to None before `warmup_cutoff`
      (`analytics.pmc.pmc_display_values` semantics). A past day with no stored row carries
      no PMC point (renderers join the line across the gap).
    - From the anchor (latest stored row strictly before today with non-NULL PMC):
      the same recurrence is folded forward via `pmc_math.compute_pmc(seed=(ctl_A,
      atl_A))` over the merged loads — actual for anchor+1..yesterday, the §3 rule for
      today, planned beyond — through plan end. Full-precision storage makes this fold
      reproduce the stored series bit-exactly, so today's fold equals the stored
      today-row whenever today's load has synced (§7.1 consistency contract).
    - No anchor → every point's PMC is None (the panel is suppressed by the renderer).

    Time constants come from config (`ctl_days`/`atl_days`), matching the stored past,
    so the folded future never kinks at the seam. The caller fetches `metrics_rows`,
    the config τs and the cutoff — this stays row-in/row-out."""
    metrics_by_date = {m["date"]: m for m in metrics_rows}
    anchor = _anchor(metrics_rows, today)
    folded: Dict[str, Tuple[float, float, float]] = {}
    if anchor and day_points:
        anchor_date, ctl_a, atl_a = anchor
        loads = {p["date"]: p["load"] for p in day_points}
        fold_start = day_str(parse_date(anchor_date) + timedelta(days=1))
        fold_end = day_points[-1]["date"]
        if fold_start <= fold_end:
            folded = pmc_math.compute_pmc(
                loads, fold_start, fold_end, ctl_days, atl_days,
                seed=(ctl_a, atl_a),
            )

    out: List[DayPoint] = []
    for p in day_points:
        date = p["date"]
        ctl = atl = tsb = None
        if anchor and date > anchor[0]:
            # Anchor+1 onward (incl. today and the whole projection) — the fold.
            vals = folded.get(date)
            if vals is not None:
                ctl, atl, tsb = vals
        elif date < today:
            # Stored past, blanked inside the warm-up window; None if no row.
            m = metrics_by_date.get(date)
            if m is not None:
                ctl, atl, tsb = pmc_math.pmc_display_values(m, warmup_cutoff)
        out.append({**p, "ctl": ctl, "atl": atl, "tsb": tsb})
    return out


def _load_by_sport(
    items: List[Dict[str, Any]], load_fn, sport_field: str
) -> Dict[str, float]:
    """Sums `load_fn(item)` per canonical sport (DESIGN_mesocycle_progress.md §3.3) — the
    same bucketing `intensity.sport_durations` uses, so a week's per-sport load and its
    per-sport duration never disagree about which sport an item belongs to.

    `sport_field` differs by row type and is the caller's job to get right: a
    completed activity's sport lives in `activity_type` (the raw `completed_activities`
    column), a planned workout's in `sport_type` — the same split `analytics/intensity.py`'s
    sport-keyed helpers already draw between the two row shapes."""
    by_sport: Dict[str, float] = {}
    for item in items:
        sport = canonical_sport(item.get(sport_field) or "unknown")
        by_sport[sport] = by_sport.get(sport, 0.0) + load_fn(item)
    return by_sport


def _week_meso(week_dates: List[str], meso_spans: List[Dict[str, Any]]):
    """Majority-overlap mesocycle label/source for one Monday-aligned week (§6.1):
    the mesocycle covering the most of the week's 7 days wins; a tie favors the later
    mesocycle (spans are given chronological, so a later match on an equal count
    overwrites the earlier one)."""
    best = None
    best_count = 0
    for span in meso_spans:
        count = sum(
            1 for d in week_dates if span["start_date"] <= d <= span["end_date"]
        )
        if count and count >= best_count:
            best_count = count
            best = span
    if best is None:
        return None, None
    return best["label"], best["source"]


def weekly_aggregates(
    activities: List[Dict[str, Any]],
    workouts: List[Dict[str, Any]],
    today: str,
    meso_spans: List[Dict[str, Any]],
    *,
    window_end: Optional[str] = None,
) -> List[Dict[str, Any]]:
    """Monday-commencing weekly planned-vs-actual load (§5/§6), one dict per week from
    the earliest activity/workout date through plan end (or today):

        {week_commencing, planned_load, planned_load_by_sport, planned_load_elapsed?,
         planned_load_elapsed_by_sport?, partial_plan?, in_progress, actual_load,
         actual_load_by_sport, meso_label, meso_source, zone_rows, sport_seconds,
         judged_sport_seconds, load_sparse, planned_zone_rows}

    The `_by_sport` dicts (canonical sport -> load) let a caller tell WHICH sport drove a
    week's gap without re-deriving it — the raw material for DESIGN_mesocycle_progress.md
    §3.3. Bucketed on `activity_type` for the actual dict and `sport_type` for the two
    planned ones, the same split `analytics/intensity.py`'s sport-keyed helpers draw.

    `planned_load` is None for a week the plan never covered, matching `adherence.py`:
    activity outside planned coverage is informational, not a deviation. `partial_plan`
    marks a week the plan covers only part of, where no honest percentage can be formed
    from the pair (§3 'comparable days'); the in-progress week also carries
    `planned_load_elapsed` so it doesn't read as poor adherence every Monday."""
    non_removed_workouts = [w for w in workouts if not w.get("removed")]
    start = _series_start(activities, non_removed_workouts)
    if start is None:
        return []
    end = window_end if window_end is not None else _window_end(workouts, today)
    week_start = _monday(parse_date(start))
    end_d = parse_date(end)

    # The span the plan speaks for. A week only partly inside it compares a partial
    # planned total against a whole week of training (§3).
    covered = plan_dates(workouts)
    plan_first = min(covered) if covered else None
    plan_last = plan_end(workouts)

    acts_by_date = _group_by_date(activities)
    workouts_by_date = _group_by_date(non_removed_workouts)

    weeks: List[Dict[str, Any]] = []
    w_start = week_start
    while w_start <= end_d:
        week_dates = [day_str(w_start + timedelta(days=i)) for i in range(7)]
        week_mon, week_sun = week_dates[0], week_dates[-1]
        in_progress = week_mon <= today <= week_sun

        week_acts = [a for d in week_dates for a in acts_by_date.get(d, [])]
        actual_load = sum(activity_load(a) for a in week_acts)
        actual_load_by_sport = _load_by_sport(week_acts, activity_load, "activity_type")
        week_workouts = [w for d in week_dates for w in workouts_by_date.get(d, [])]

        meso_label, meso_source = _week_meso(week_dates, meso_spans)

        week: Dict[str, Any] = {
            "week_commencing": week_mon,
            "actual_load": actual_load,
            "actual_load_by_sport": actual_load_by_sport,
            "in_progress": in_progress,
            "meso_label": meso_label,
            "meso_source": meso_source,
            # The intensity half of the same rows (DESIGN_intensity_distribution.md §9.6).
            # Joined here rather than fetched again: this function already holds every
            # activity bucketed by week, and `render_progress` is handed one payload and
            # reads no database — the property the one-payload rule exists to protect.
            "zone_rows": intensity.zone_rows(week_acts),
            "sport_seconds": intensity.sport_durations(week_acts),
            # The same durations over activities big enough to grade: what the "trained but
            # nothing recorded" `!` reads, so the floor applies there too (§11).
            "judged_sport_seconds": intensity.sport_durations(
                [a for a in week_acts if intensity.judgeable(a)]
            ),
            # The athlete trained normally, the strap died, and no RPE was entered — so
            # the week's own LOAD is undercounted and reads as an adherence miss the
            # week planner will then adapt the sessions around. A `progress` defect that predates
            # the zone tables (DESIGN_intensity_distribution.md §11). Only activities big
            # enough to hide material load count: a 5-minute mobility activity with a
            # cold strap lit this on two thirds of a real athlete's weeks.
            "load_sparse": any(
                load_method(a) == "hr_sparse" for a in week_acts
                if intensity.judgeable(a)
            ),
            # The future half of the zone table: what the plan PRESCRIBES per zone, ghost
            # rows under today exactly like the load table's ghost bars
            # (DESIGN_intensity_distribution.md §9.8). Empty for every week planned
            # before those columns existed — the rolling horizon rewrites the future on
            # each generation, so nothing needs backfilling.
            "planned_zone_rows": intensity.planned_zone_rows(week_workouts),
        }
        if week_workouts:
            week["planned_load"] = sum(planned_load(w) for w in week_workouts)
            week["planned_load_by_sport"] = _load_by_sport(
                week_workouts, planned_load, "sport_type"
            )
            # Elapsed = Mon..yesterday, plus today only once its load has synced
            # (today's §3 source is 'actual'). Including an unfinished today would
            # make an evening athlete read <100% all day (§3).
            if in_progress:
                today_synced = any(
                    activity_load(a) > 0 for a in acts_by_date.get(today, [])
                )
                elapsed_end = today if today_synced else (
                    day_str(parse_date(today) - timedelta(days=1))
                )
                elapsed_workouts = [w for w in week_workouts if w["date"] <= elapsed_end]
                week["planned_load_elapsed"] = sum(
                    planned_load(w) for w in elapsed_workouts
                )
                week["planned_load_elapsed_by_sport"] = _load_by_sport(
                    elapsed_workouts, planned_load, "sport_type"
                )
            else:
                elapsed_end = week_sun
            # Comparable only if the plan speaks for every day already trained: the
            # week the plan *starts* otherwise divides three planned days by seven
            # trained ones and reads 477% (§3).
            if elapsed_end >= week_mon and not (
                plan_first is not None and plan_first <= week_mon
                and plan_last is not None and plan_last >= elapsed_end
            ):
                week["partial_plan"] = True
        else:
            week["planned_load"] = None

        weeks.append(week)
        w_start += timedelta(days=7)

    return weeks


def week_plan_denom(week: Dict[str, Any]) -> Optional[float]:
    """The planned figure a week's bar and percentage compare against (§3 'comparable
    days'): the elapsed slice for the in-progress week, the full planned total
    otherwise, None for a week no plan covered.

    Lives here rather than in one renderer because §3 is a payload rule, not a layout
    one: the CLI table and the PNG both read it, and the PNG reading `planned_load`
    directly is exactly how the two surfaces disagreed about the same week."""
    if week.get("planned_load") is None:
        return None
    if week.get("in_progress"):
        return week.get("planned_load_elapsed", 0.0)
    return week["planned_load"]


def week_plan_denom_by_sport(week: Dict[str, Any]) -> Optional[Dict[str, float]]:
    """The per-sport counterpart of `week_plan_denom`: same elapsed-vs-full rule, but
    keyed by canonical sport. None for a week no plan covered, matching the scalar."""
    if week.get("planned_load") is None:
        return None
    if week.get("in_progress"):
        return week.get("planned_load_elapsed_by_sport", {})
    return week.get("planned_load_by_sport", {})
