"""`data show-metrics` and `data show-activities`: the cached rows, as tables or as CSV.

Both read what `data pull` stored and print it; neither calls the model and neither
writes. The zone columns and the load tag are the widest part of either table, so the
narrow-client and `--zones` variants live beside the table they vary.
"""
import argparse
import csv as csv_mod
import sys
from trainmate import runtime
from trainmate.analytics import intensity, zone_tables
from trainmate.analytics.baselines import classify_metric, is_anomalous, UNKNOWN
from trainmate.analytics.load import activity_load, load_method
from trainmate.analytics.pmc import (
    color_load_ratio, load_ratio, pmc_cells, pmc_display_values,
)
from trainmate.sports import sport_aliases
from trainmate.text import (
    bold, cyan, default_wrap_width, gray, green, is_narrow_client, red, render_table,
    visible_len, wrap_text,
)
from trainmate.output import aside, warn
from trainmate.clock import fmt_date, fmt_span
from trainmate.cli.windows import resolve_window


def run_data_show_metrics(args: argparse.Namespace) -> None:
    """Displays athlete metrics over the resolved date range."""
    start_date, end_date = (None, None) if args.all else resolve_window(args)

    if not getattr(args, 'no_pull', False) and not getattr(args, 'all', False):
        try:
            runtime.garmin.ensure_data(
                start_date, end_date, force=getattr(args, 'force_pull', False)
            )
        except Exception as e:
            warn(f"could not ensure recent data: {e}")

    metrics_history = runtime.db.get_metrics_cache(start_date=start_date, end_date=end_date)

    if getattr(args, 'csv', False):
        _show_metrics_csv(metrics_history)
        return

    range_str = fmt_span(start_date, end_date) if start_date and end_date else "All Time"
    print(bold(cyan(f"\n=== ATHLETE METRICS ({range_str}) ===")))
    if not metrics_history:
        print("No metrics cached in this range.")
        return

    headers = [
        "Date", "HRV", "HRV Base", "RHR", "RHR Base", "Sleep", "Sleep Base",
        "Stress", "CTL", "ATL", "TSB", "ATL:CTL",
    ]
    rows = []

    warmup_cutoff = runtime.garmin.warmup_cutoff(runtime.db)

    for m in metrics_history:
        base = runtime.db.get_baseline(m['date'])

        hrv_val = m['hrv']
        rhr_val = m['rhr']
        sleep_val = m['sleep_score']
        stress_val = m['stress']

        hrv_str = str(hrv_val) if hrv_val is not None else "N/A"
        rhr_str = str(rhr_val) if rhr_val is not None else "N/A"
        sleep_str = str(sleep_val) if sleep_val is not None else "N/A"
        stress_str = str(stress_val) if stress_val is not None else "N/A"

        # Ratio off the *display* values, so a warm-up-suppressed CTL can't surface as a
        # spurious spike (DESIGN_pmc_fitness_fatigue.md §6.2).
        ctl_v, atl_v, tsb_v = pmc_display_values(m, warmup_cutoff)
        ctl_str, atl_str, tsb_str = pmc_cells(ctl_v, atl_v, tsb_v)
        ratio_val = load_ratio(atl_v, ctl_v)
        ratio_str = color_load_ratio(ratio_val) if ratio_val is not None else "N/A"

        hrv_base_str = "N/A"
        rhr_base_str = "N/A"
        sleep_base_str = "N/A"

        if base:
            hrv_verdict = classify_metric('hrv', hrv_val, base)
            if hrv_verdict != UNKNOWN:
                hrv_str = (
                    red(f"{hrv_val} (v)") if is_anomalous(hrv_verdict)
                    else green(str(hrv_val))
                )
            if base['hrv_baseline_mean'] is not None:
                hrv_base_str = f"{base['hrv_baseline_mean']:.1f}"

            rhr_verdict = classify_metric('rhr', rhr_val, base)
            if rhr_verdict != UNKNOWN:
                rhr_str = (
                    red(f"{rhr_val} (^)") if is_anomalous(rhr_verdict)
                    else green(str(rhr_val))
                )
            if base['rhr_baseline_mean'] is not None:
                rhr_base_str = f"{base['rhr_baseline_mean']:.1f}"

            sleep_verdict = classify_metric('sleep', sleep_val)
            if sleep_verdict != UNKNOWN:
                sleep_str = (
                    red(f"{sleep_val} (v)") if is_anomalous(sleep_verdict)
                    else green(str(sleep_val))
                )
            if base['sleep_baseline_mean'] is not None:
                sleep_base_str = f"{base['sleep_baseline_mean']:.1f}"

        rows.append([
            fmt_date(m['date']), hrv_str, hrv_base_str, rhr_str, rhr_base_str,
            sleep_str, sleep_base_str, stress_str,
            ctl_str, atl_str, tsb_str, ratio_str,
        ])

    print(render_table(headers, rows))
    print(gray("((v) suppressed/poor, (^) elevated compared to baseline)\n"))


def _show_metrics_csv(metrics_history: list) -> None:
    """Output metrics as CSV."""
    writer = csv_mod.writer(sys.stdout)
    writer.writerow([
        "date", "hrv", "hrv_baseline", "rhr", "rhr_baseline",
        "sleep_score", "sleep_baseline", "stress", "ctl", "atl", "tsb",
        "atl_ctl_ratio",
    ])
    # Suppressed (warm-up) or NULL PMC values are emitted as empty cells, never 0, so
    # downstream parsing can't read a zero as data (DESIGN_pmc_fitness_fatigue.md §6.2).
    warmup_cutoff = runtime.garmin.warmup_cutoff(runtime.db)
    for m in metrics_history:
        base = runtime.db.get_baseline(m['date'])
        hrv_base = None
        rhr_base = None
        sleep_base = None
        if base:
            hrv_base = base.get('hrv_baseline_mean')
            rhr_base = base.get('rhr_baseline_mean')
            sleep_base = base.get('sleep_baseline_mean')
        ctl_v, atl_v, tsb_v = pmc_display_values(m, warmup_cutoff)
        ratio_v = load_ratio(atl_v, ctl_v)
        writer.writerow([
            m['date'], m['hrv'], hrv_base, m['rhr'], rhr_base,
            m['sleep_score'], sleep_base, m['stress'],
            "" if ctl_v is None else ctl_v,
            "" if atl_v is None else atl_v,
            "" if tsb_v is None else tsb_v,
            "" if ratio_v is None else ratio_v,
        ])


# Where `activity_load` took a row's number from, as a tag beside it
# (DESIGN_intensity_distribution.md §9.7). `rpe+` is a path `compute_load` has no word
# for — the measurement was trustworthy but the athlete's RPE implied materially more
# strain, so the load came from RPE anyway (the kettlebell case §6 exists for).
LOAD_TAGS = {
    "power": "pwr", "hr": "hr", "rpe": "rpe", "hr_sparse": "sparse!",
    "rpe_divergence": "rpe+", "measured": "tss", "none": "—",
}


def _load_cell(act: dict) -> str:
    """`188 (pwr)` — the load and where it came from, about six characters.

    The figure is `activity_load()`, NOT the stored `tss`. `measured_tss` defines that
    column as a pure measurement — no coverage gate, never RPE — while `progress`, the
    PMC and every coaching path use `activity_load()`, so the two commands already
    disagreed about an activity's load, silently. A tag on the measurement would name a
    provenance that is not the provenance of the number shown.
    """
    return f"{activity_load(act):.1f} ({LOAD_TAGS.get(load_method(act), '?')})"


def _zone_coverage(act: dict, prefix: str, n: int) -> float:
    duration = float(act.get("duration_sec") or 0.0)
    if not duration:
        return 0.0
    total = sum(float(act.get(f"{prefix}{i}_sec") or 0.0) for i in range(1, n + 1))
    return total / duration


def _show_activities_zones(activities: list) -> None:
    """`--zones`: one row per activity x currency, both currencies, nothing aggregated.

    It SWAPS columns rather than widening — Distance, Elev, Avg HR, Max HR and Avg Watts
    are not what the flag was reached for, and five HR zones plus seven power zones
    cannot join twelve existing columns. A ride with both a meter and a strap renders two
    rows, which keeps §6's one prohibition structural: the two views of the same time are
    separate rows, never adjacent columns inviting addition (§9.7).
    """
    headers = ["Date", "Type", "Duration", "Cur"] + [
        f"Z{i}" for i in range(1, 8)
    ] + ["Cov", "TSS"]
    rows = []
    for act in activities:
        for cur in intensity.CURRENCIES:
            n = len(cur.labels)
            secs = [
                float(act.get(f"{cur.prefix}{i}_sec") or 0.0) for i in range(1, n + 1)
            ]
            if not any(secs):
                continue
            cells = [zone_tables.fmt_duration(s) if s else "—" for s in secs]
            cells += [""] * (7 - n)  # HR rows leave Z6/Z7 blank
            rows.append(
                [fmt_date(act["date"]), act["activity_type"].upper(),
                 zone_tables.fmt_duration(act.get("duration_sec") or 0.0), cur.tag]
                + cells
                + [f"{_zone_coverage(act, cur.prefix, n) * 100:.0f}%", _load_cell(act)]
            )
    if not rows:
        print("No zone data recorded for these activities.")
        return
    print(render_table(headers, rows))
    aside(wrap_text(zone_tables.NEVER_SUM_NOTE), color_fn=gray)


def run_data_show_activities(args: argparse.Namespace) -> None:
    """Displays completed activities over the resolved date range."""
    start_date, end_date = (None, None) if args.all else resolve_window(args)

    if not getattr(args, 'no_pull', False) and not getattr(args, 'all', False):
        try:
            runtime.garmin.ensure_data(
                start_date, end_date, force=getattr(args, 'force_pull', False)
            )
        except Exception as e:
            warn(f"could not ensure recent data: {e}")

    activities = runtime.db.get_completed_activities(
        start_date=start_date, end_date=end_date
    )

    if getattr(args, 'sport_type', None) is not None:
        # Alias-aware, so `--type cycling` stops missing `road_biking`,
        # `gravel_cycling`, `mountain_biking` and `indoor_cycling` — the athlete
        # filtering for their cycling and seeing a fraction of it (§9.7).
        wanted = set(sport_aliases(args.sport_type))
        activities = [
            act for act in activities
            if (act['activity_type'] or "").strip().lower() in wanted
        ]

    if getattr(args, 'csv', False):
        _show_activities_csv(activities)
        return

    range_str = fmt_span(start_date, end_date) if start_date and end_date else "All Time"
    print(bold(cyan(f"\n=== COMPLETED ACTIVITIES ({range_str}) ===")))
    if not activities:
        print("No completed activities found in this range.")
        return

    if getattr(args, 'zones', False):
        _show_activities_zones(activities)
        return

    headers = [
        "Date", "Time", "Type", "Name", "Duration", "Distance", "Elev",
        "Avg HR", "Max HR", "Avg Watts", "RPE", "TSS",
    ]
    rows = []

    for act in activities:
        dur_sec = act.get('duration_sec') or 0.0
        h = int(dur_sec // 3600)
        m = int((dur_sec % 3600) // 60)
        s = int(dur_sec % 60)
        dur_str = f"{h:02d}:{m:02d}:{s:02d}" if h > 0 else f"{m:02d}:{s:02d}"

        name_str = act.get('activity_name') or ""
        if len(name_str) > 25:
            name_str = name_str[:22] + "..."

        dist_val = act.get('distance_km')
        dist_str = f"{dist_val:.1f} km" if dist_val is not None else "0.0 km"

        elev_val = act.get('elevation_gain_m')
        elev_str = f"{elev_val:.0f} m" if elev_val is not None else "0 m"

        avg_hr = act.get('avg_hr')
        avg_hr_str = str(avg_hr) if avg_hr is not None else "N/A"

        max_hr = act.get('max_hr')
        max_hr_str = str(max_hr) if max_hr is not None else "N/A"

        watts = act.get('bike_avg_watts')
        watts_str = f"{watts} W" if watts is not None else "N/A"

        rpe_val = act.get('rpe')
        rpe_str = str(rpe_val) if rpe_val is not None else "N/A"

        tss_str = _load_cell(act)

        start_time = act.get('start_time') or ""
        if " " in start_time:
            time_str = start_time.split(" ", 1)[1]
        elif "T" in start_time:
            time_str = start_time.split("T", 1)[1]
            if "+" in time_str:
                time_str = time_str.split("+", 1)[0]
            elif "-" in time_str:
                time_str = time_str.split("-", 1)[0]
            elif "Z" in time_str:
                time_str = time_str.split("Z", 1)[0]
        else:
            time_str = start_time or "N/A"
        if len(time_str) > 8:
            time_str = time_str[:8]

        rows.append([
            fmt_date(act['date']), time_str, act['activity_type'].upper(), name_str,
            dur_str, dist_str, elev_str, avg_hr_str, max_hr_str, watts_str,
            rpe_str, tss_str,
        ])

    table = render_table(headers, rows)
    print(table)

    # Summary footer
    total_count = len(activities)
    total_duration_sec = sum(act.get('duration_sec') or 0.0 for act in activities)
    total_distance_km = sum(act.get('distance_km') or 0.0 for act in activities)
    total_elevation_m = sum(act.get('elevation_gain_m') or 0.0 for act in activities)
    # The load, matching the column above — so this command and `progress` finally quote
    # one number for the same activity (§9.7).
    total_tss = sum(activity_load(act) for act in activities)

    tot_h = int(total_duration_sec // 3600)
    tot_m = int((total_duration_sec % 3600) // 60)
    tot_dur_str = f"{tot_h}h {tot_m}m" if tot_h > 0 else f"{tot_m}m"

    narrow = is_narrow_client()
    sep = "\n" if narrow else " | "
    rule_width = (
        default_wrap_width() if narrow
        else max(visible_len(line) for line in table.splitlines())
    )
    print(gray("-" * rule_width))
    print(bold(sep.join([
        f"Summary: {total_count} activities",
        f"Duration: {tot_dur_str}",
        f"Distance: {total_distance_km:.1f} km",
        f"Elevation: {total_elevation_m:.0f} m",
        f"TSS: {total_tss:.1f}",
    ])))


_CSV_ZONE_COLUMNS = (
    [f"zone{i}_sec" for i in range(1, 6)]
    + [f"power_zone{i}_sec" for i in range(1, 8)]
)


def _show_activities_csv(activities: list) -> None:
    """Output activities as CSV — everything, with no flag gating it.

    No width constraint here and its consumers want completeness, so all twelve zone
    columns, both coverage fractions and the load provenance go in unconditionally
    (§9.7). `tss` stays the stored measurement; `load` and `load_method` carry the
    number every coaching path actually uses, so a script can see both and know which
    is which.
    """
    writer = csv_mod.writer(sys.stdout)
    writer.writerow([
        "date", "start_time", "activity_type", "activity_name",
        "duration_sec", "distance_km", "elevation_gain_m",
        "avg_hr", "max_hr", "bike_avg_watts", "rpe", "tss",
        "load", "load_method", "hr_coverage", "power_coverage",
    ] + _CSV_ZONE_COLUMNS)
    for act in activities:
        writer.writerow([
            act.get('date'), act.get('start_time'),
            act.get('activity_type'), act.get('activity_name'),
            act.get('duration_sec'), act.get('distance_km'),
            act.get('elevation_gain_m'), act.get('avg_hr'),
            act.get('max_hr'), act.get('bike_avg_watts'),
            act.get('rpe'), act.get('tss'),
            f"{activity_load(act):.1f}", load_method(act),
            f"{_zone_coverage(act, 'zone', 5):.3f}",
            f"{_zone_coverage(act, 'power_zone', 7):.3f}",
        ] + [act.get(col) for col in _CSV_ZONE_COLUMNS])

