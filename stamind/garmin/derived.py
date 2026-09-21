"""The stored side of the derived metrics: read the rows, run the maths, write it back.

The maths itself is `analytics/pmc.py` and `analytics/load.py`, which touch no database.
This module is where a database handle meets them. See DESIGN_pmc_fitness_fatigue.md.
"""
import math
from datetime import timedelta
from typing import Any, Dict, List, Optional, Tuple

from stamind import runtime
from stamind.analytics.load import _hr_zone_coverage, activity_load, compute_load, measured_tss
from stamind.analytics.pmc import compute_pmc, pmc_warmup_cutoff_for
from stamind.clock import parse_date
from stamind.config import config
from stamind.output import warn


def pmc_history_start(dbh=None) -> Optional[str]:
    """Earliest ISO date with any Garmin evidence — min(first activity, first metrics
    row); two MIN() queries. The single source the warm-up cutoff and the
    still-warming-up flag derive from — callers fetch it ONCE per command and pass it
    (or the cutoff derived from it) down, so no two surfaces can compute it differently.

    `dbh` defaults to the module db; callers holding their own handle (CoachService's
    injected db, the CLI's rebindable one) pass it so the cutoff is derived from the
    same database as the metrics it gates."""
    dbh = dbh or runtime.db
    firsts = [
        d for d in (dbh.get_first_activity_date(), dbh.get_first_metric_date()) if d
    ]
    return min(firsts) if firsts else None


def warmup_cutoff(dbh=None, history_start: Optional[str] = None) -> Optional[str]:
    """The §3.3(a) warm-up cutoff for `dbh`: its history start, read through the
    configured CTL window. Every surface that blanks warm-up rows asks this one function,
    so none of them can pair a history start with a different window.

    Pass `history_start` when the caller already has it — the still-warming-up flag needs
    the same value, and fetching it costs two queries. An athlete with no history has no
    cutoff either way, so the extra read a None start causes changes no answer."""
    if history_start is None:
        history_start = pmc_history_start(dbh)
    return pmc_warmup_cutoff_for(history_start, config.pmc_ctl_days)


def _mean_std(values: List[float]) -> Tuple[float, float]:
    if not values:
        return 0.0, 0.0
    n = len(values)
    mean = sum(values) / n
    if n < 2:
        return mean, 0.0
    variance = sum((x - mean) ** 2 for x in values) / (n - 1)
    return mean, math.sqrt(variance)
def recompute_derived(dbh=None) -> None:
    """Recomputes the PMC (CTL/ATL/TSB) and 28-day baselines for ALL cached days. A full
    sweep is trivially cheap on a local DB and avoids windowed-recompute bugs (an
    activity affects 28 days of derived values).

    `dbh` defaults to the module db; the post-wipe recompute (`db/wipes.py`) passes the
    handle the wipe ran against, so it sweeps that same database even when the
    singleton has been rebound (tests, embeddings that inject a db)."""
    dbh = dbh or runtime.db
    # One unified load per activity via the fallback hierarchy (power TSS ->
    # hrTSS -> sRPE), not the old `tss + rpe*hours` blend.
    daily_load: Dict[str, float] = {}
    for act in dbh.get_completed_activities():
        date_str = act["date"]
        daily_load[date_str] = daily_load.get(date_str, 0.0) + activity_load(act)

    metrics = dbh.get_metrics_cache()  # sorted by date asc
    by_date = {m["date"]: m for m in metrics}

    # PMC (CTL/ATL/TSB) over EVERY calendar day so rest/gap days decay the EWMAs. The
    # span ends at max(last activity, last metrics): an activities-only pull can leave
    # trailing activity days past the last metrics row, and those carry load that must be
    # walked. Upserted onto existing metrics rows only (activity-only days feed the EWMA
    # but create no cache row).
    span_dates = list(daily_load.keys()) + [m["date"] for m in metrics]
    pmc: Dict[str, Tuple[float, float, float]] = {}
    if span_dates:
        pmc = compute_pmc(
            daily_load, min(span_dates), max(span_dates),
            config.pmc_ctl_days, config.pmc_atl_days,
        )

    # One connection and one commit for the whole sweep. Each per-day write used to
    # open, commit and close its own — roughly one such cycle per day of history, after
    # every pull. The sweep is also all-or-nothing now, so an interruption cannot leave
    # half the history carrying refreshed CTL/ATL and half the old values.
    with dbh.transaction():
        _write_derived(dbh, metrics, by_date, pmc)


def _write_derived(dbh, metrics, by_date, pmc) -> None:
    """Upserts the PMC triple and the 28-day baselines for every cached day."""
    for m in metrics:
        date_str = m["date"]
        date_obj = parse_date(date_str)

        ctl_atl_tsb = pmc.get(date_str)
        ctl, atl, tsb = ctl_atl_tsb if ctl_atl_tsb else (None, None, None)

        dbh.save_metric_cache(
            date=date_str, rhr=m.get("rhr"), hrv=m.get("hrv"),
            sleep_score=m.get("sleep_score"), stress=m.get("stress"),
            ctl=ctl, atl=atl, tsb=tsb,
        )

        rhr_vals, hrv_vals, sleep_vals = [], [], []
        for d in range(1, 29):
            prev = by_date.get((date_obj - timedelta(days=d)).isoformat())
            if not prev:
                continue
            if prev.get("rhr") is not None:
                rhr_vals.append(prev["rhr"])
            if prev.get("hrv") is not None:
                hrv_vals.append(prev["hrv"])
            if prev.get("sleep_score") is not None:
                sleep_vals.append(prev["sleep_score"])

        if len(rhr_vals) >= 7 or len(hrv_vals) >= 7 or len(sleep_vals) >= 7:
            rhr_mean, rhr_std = _mean_std(rhr_vals)
            hrv_mean, hrv_std = _mean_std(hrv_vals)
            sleep_mean, sleep_std = _mean_std(sleep_vals)
            dbh.save_baseline(
                date=date_str, rhr_mean=rhr_mean, rhr_std=rhr_std,
                hrv_mean=hrv_mean, hrv_std=hrv_std,
                sleep_mean=sleep_mean, sleep_std=sleep_std,
            )
def backfill_tss(
    start_date: Optional[str] = None,
    end_date: Optional[str] = None,
    verbose: bool = False,
) -> int:
    """Recomputes the measured TSS (power TSS or hrTSS) for every cached activity
    and rewrites the stored value. Activities keep their raw zone seconds, so
    this needs no Garmin calls. Returns the number of rows whose TSS changed, and
    refreshes the derived PMC (which runs off the on-the-fly load)."""
    activities = runtime.db.get_completed_activities(start_date=start_date, end_date=end_date)
    changed = 0
    sparse: List[Dict[str, Any]] = []
    for act in activities:
        new_tss = measured_tss(act, act)
        old_tss = act.get("tss")
        if (old_tss is None) != (new_tss is None) or (
            old_tss is not None and new_tss is not None
            and abs(float(old_tss) - new_tss) > 1e-6
        ):
            runtime.db.update_activity_tss(act["activity_id"], new_tss)
            changed += 1
        _load, _method, warning = compute_load(
            act, act, act.get("rpe"), act.get("duration_sec") or 0.0
        )
        if warning:
            sparse.append(act)
    print(f"Recomputed measured TSS for {len(activities)} activities "
          f"({changed} changed).")
    if sparse:
        warn(
            f"{len(sparse)} activities have low HR-zone coverage and no RPE; "
            "their load is an underestimate. Enter an RPE in Garmin for accuracy."
        )
        if verbose:
            for act in sparse:
                date = act.get("date", "?")
                name = act.get("activity_name") or act.get("activity_type", "?")
                dur_sec = act.get("duration_sec") or 0.0
                dur_min = int(dur_sec // 60)
                coverage = _hr_zone_coverage(act, dur_sec)
                print(f"    {date}  {name}  ({dur_min} min, "
                      f"HR-zone coverage {coverage:.0%})")
    recompute_derived()
    return changed
