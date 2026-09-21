"""What one week of training looked like, as evidence a prompt can read.

Six answers, each over rows the caller already fetched: which constraints covered the
week, how the athlete's overnight metrics moved against their own baseline, how a logged
signal's magnitude is written, which days a signal plausibly reached, and where the
fitness/fatigue series stood at the week's end.

They were static methods of the coach service, which is where the backward evaluation
that consumes them lives (DESIGN_backward_evaluation.md, DESIGN_quantitative_signal_impact.md).
None of them touches a database or a model — they are the arithmetic under the evidence,
and they belong with the rest of the training maths.
"""
from datetime import datetime, timedelta
from typing import Any, Dict, List, Optional, Tuple

from trainmate.analytics.load import activity_load
from trainmate.analytics.pmc import pmc_ramp
from trainmate.signals import excluded_channels


# Channels of the per-day z, mapping the metric column to its baseline mean/std keys.
# Sign convention (documented for the LLM): +hrv better, +rhr worse, +sleep better
# (DESIGN_quantitative_signal_impact.md §3).
RESPONSE_Z_CHANNELS = (
    ("rhr", "rhr", "rhr_baseline_mean", "rhr_baseline_std"),
    ("hrv", "hrv", "hrv_baseline_mean", "hrv_baseline_std"),
    ("sleep", "sleep_score", "sleep_baseline_mean", "sleep_baseline_std"),
)


def week_constraints(
    constraints: List[Constraint], week_start, week_end
) -> List[Dict[str, Any]]:
    """Constraints overlapping [week_start, week_end] (date objects), each tagged
    'full' (spans the whole in-window week) or 'partial'. Fed to the analysis as
    discounting context only — a constraint may explain an anomaly away but is never
    cited as supporting evidence (DESIGN_constraints.md §2, §6). Dates are ISO strings
    so lexicographic comparison is chronological."""
    ws, we = week_start.strftime("%Y-%m-%d"), week_end.strftime("%Y-%m-%d")
    out: List[Dict[str, Any]] = []
    for c in constraints:
        start, end = c.get('start_date'), c.get('end_date')
        if not start or not end or start > we or end < ws:
            continue  # missing dates or no overlap with this week
        out.append({
            "title": c.get('title'),
            "impact": c.get('description') or "",
            "coverage": "full" if (start <= ws and end >= we) else "partial",
        })
    return out

def day_response_z(
    metric_row: Dict[str, Any], baseline: Optional[Dict[str, Any]]
) -> Dict[str, Optional[float]]:
    """Baseline-relative z-score `(value - mean) / std` for ONE morning's rhr/hrv/sleep
    — the shared definition of "notches from normal" used by both the weekly feature
    (averaged over the week) and the signal-impact alignment (per morning). A channel
    is None when its metric value is missing, the baseline mean/std is missing, or std
    is zero (undefined). Unrounded; callers round as they emit
    (DESIGN_quantitative_signal_impact.md §3)."""
    out: Dict[str, Optional[float]] = {}
    for channel, metric_key, mean_key, std_key in RESPONSE_Z_CHANNELS:
        mean = baseline.get(mean_key) if baseline else None
        std = baseline.get(std_key) if baseline else None
        value = metric_row.get(metric_key)
        if mean is None or not std or value is None:
            out[channel] = None  # missing baseline/value or zero std -> undefined
        else:
            out[channel] = (value - mean) / std
    return out

def week_response_features(
    w_metrics: List[Dict[str, Any]], baseline: Optional[Dict[str, Any]]
) -> Dict[str, Any]:
    """Deterministic body-response features for one week: mean sleep/stress, and
    baseline-relative z-scores `(value - mean) / std` for rhr/hrv/sleep averaged over
    the week's days. A component is None when its baseline mean/std is missing or std
    is zero (undefined), or no metric day carries the value; `vs_baseline_z` is only
    included when at least one component is computable (§3)."""
    def _avg(key: str) -> Optional[float]:
        vals = [m[key] for m in w_metrics if m.get(key) is not None]
        return round(sum(vals) / len(vals), 1) if vals else None

    def _z(channel: str) -> Optional[float]:
        vals = [
            z for z in (
                day_response_z(m, baseline)[channel] for m in w_metrics
            ) if z is not None
        ]
        return round(sum(vals) / len(vals), 2) if vals else None

    vs_baseline_z = {
        "rhr": _z("rhr"),
        "hrv": _z("hrv"),
        "sleep": _z("sleep"),
    }
    features: Dict[str, Any] = {
        "avg_sleep_score": _avg("sleep_score"),
        "avg_stress": _avg("stress"),
    }
    if any(v is not None for v in vs_baseline_z.values()):
        features["vs_baseline_z"] = vs_baseline_z
    return features

def norm_signal_value(value: Optional[float]):
    """Pass a logged signal magnitude through for display: drop float noise on whole
    numbers (4.0 -> 4) so doses read cleanly, keep fractional values rounded; None
    (presence-only / unparseable) stays None (§3.1). TrainMate never interprets the
    scale — it only tidies the number."""
    if value is None:
        return None
    f = float(value)
    return int(f) if f.is_integer() else round(f, 2)

def signal_days(
    daily_signals: List[Dict[str, Any]],
    metrics: List[Dict[str, Any]],
    activities: List[Dict[str, Any]],
    baseline_for,
    k: int,
    min_signal_days: int = 1,
) -> Dict[str, List[Dict[str, Any]]]:
    """Deterministic per-episode alignment of external signals against the
    mornings that bracket them (DESIGN_quantitative_signal_impact.md §3–§4). NO
    statistics: pure clustering + join + the existing per-day z.

    For each signal category it (1) clusters the logged signal-days into *episodes* —
    maximal runs separated by fewer than `k` drink-free days (§3.0); (2) emits, per
    episode, the `days` dose sequence (each signal-day's magnitude + that day's
    training load) and the `surrounding_mornings` strip spanning
    `(first − k + 1) … (last + k)`, each morning carrying its preceding day's load and
    the baseline-relative z of the recovery channels; (3) drops any response channel
    that duplicates the signal's own construct (§3.2). Categories below
    `min_signal_days` total signal-days are omitted (§5).

    `baseline_for(date_str)` returns the baseline valid on/just before that morning
    (or None). `k` is the look-ahead, `min_signal_days` the inclusion floor."""
    # Day-of training load: sum of derived load over the day's activities (0 on a rest
    # day), NOT the rolling acute EWMA — the stimulus for a morning is the day before it
    # (§3 "Day-of load").
    load_by_date: Dict[str, float] = {}
    for act in activities:
        load_by_date[act['date']] = load_by_date.get(act['date'], 0.0) + activity_load(act)

    def day_load(date_str: str) -> int:
        return int(round(load_by_date.get(date_str, 0.0)))

    metric_by_date = {m['date']: m for m in metrics}

    # Aggregate signal magnitude per (category, date): a day may carry more than one
    # row of the same category (combined dose); None when no row supplies a value.
    per_cat: Dict[str, Dict[str, Optional[float]]] = {}
    for c in daily_signals:
        cat = c.get('metric')
        if not cat:
            continue
        day_map = per_cat.setdefault(cat, {})
        v = c.get('value')
        if v is not None:
            day_map[c['date']] = (day_map.get(c['date']) or 0.0) + float(v)
        else:
            day_map.setdefault(c['date'], None)

    out: Dict[str, List[Dict[str, Any]]] = {}
    for cat in sorted(per_cat.keys()):
        day_map = per_cat[cat]
        signal_dates = sorted(day_map.keys())
        if len(signal_dates) < min_signal_days:
            continue  # too few signal-days to be worth prompting on (§5)

        excluded = excluded_channels(cat)

        # Cluster signal-days into episodes: two consecutive signal-days join the same
        # episode when fewer than k drink-free days separate them (§3.0).
        episodes: List[List[str]] = []
        run = [signal_dates[0]]
        for prev, cur in zip(signal_dates, signal_dates[1:]):
            gap_free = (
                datetime.strptime(cur, "%Y-%m-%d").date()
                - datetime.strptime(prev, "%Y-%m-%d").date()
            ).days - 1
            if gap_free < k:
                run.append(cur)
            else:
                episodes.append(run)
                run = [cur]
        episodes.append(run)

        rows: List[Dict[str, Any]] = []
        for ep in episodes:
            first = datetime.strptime(ep[0], "%Y-%m-%d").date()
            last = datetime.strptime(ep[-1], "%Y-%m-%d").date()
            days = [
                {
                    "date": d,
                    "value": norm_signal_value(day_map[d]),
                    "load_tss": day_load(d),
                }
                for d in ep
            ]
            mornings = []
            cur = first - timedelta(days=k - 1)
            end = last + timedelta(days=k)
            while cur <= end:
                m_str = cur.strftime("%Y-%m-%d")
                prev_str = (cur - timedelta(days=1)).strftime("%Y-%m-%d")
                zs = day_response_z(
                    metric_by_date.get(m_str, {}), baseline_for(m_str)
                )
                vs_normal = {
                    ch: round(z, 2)
                    for ch, z in zs.items()
                    if z is not None and ch not in excluded
                }
                mornings.append({
                    "morning": m_str,
                    "prev_day_load_tss": day_load(prev_str),
                    "vs_normal": vs_normal,
                })
                cur += timedelta(days=1)
            rows.append({"days": days, "surrounding_mornings": mornings})

        out[cat] = rows
    return out


def pmc_week_summary(
    w_metrics: List[Dict[str, Any]],
    ctl_by_date: Dict[str, Optional[float]],
    warmup_cutoff: Optional[str],
) -> Tuple[Optional[float], Optional[float], Optional[float]]:
    """(end_ctl, week_ramp, min_tsb) for one week of the analysis digest (§5.4):
    end_ctl = last day's CTL, min_tsb = deepest overload, week_ramp = end_ctl vs CTL
    7 days earlier. Guards: a week entirely inside the warm-up window emits all None
    (no phantom overreach from seeding artifacts); week_ramp comes from pmc_ramp,
    which applies the §3.1 nearest-earlier interior-gap rule, the straddle guard
    (a -7d lookback before the cutoff would ramp off a warm-up baseline), and the
    first-week boundary omit (no baseline in the window slice)."""
    end_ctl = week_ramp = min_tsb = None
    past_warmup = [
        m for m in w_metrics
        if (warmup_cutoff is None or m['date'] >= warmup_cutoff)
    ]
    ctl_days = [m for m in past_warmup if m.get('ctl') is not None]
    if ctl_days:
        end_row = max(ctl_days, key=lambda m: m['date'])
        end_ctl = end_row['ctl']
        week_ramp = pmc_ramp(
            ctl_by_date, end_row['date'], warmup_cutoff=warmup_cutoff
        )
    tsbs = [m['tsb'] for m in past_warmup if m.get('tsb') is not None]
    if tsbs:
        min_tsb = min(tsbs)
    return end_ctl, week_ramp, min_tsb

# ------------------------------------------------------ intensity distribution
