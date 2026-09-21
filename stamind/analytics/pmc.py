"""The fitness/fatigue (PMC) model: the CTL/ATL/TSB series, and how it is shown.

Maths and rendering over values the caller passes in. Nothing here imports the storage
layer or talks to Garmin — `garmin/derived.py` is what reads the rows and writes the
computed ones back. (`pmc_data_caveat` does read the clock when the caller gives it no
`as_of`, and the clock reads the athlete's stored timezone; that is the one indirect
touch, and it is why `tests/test_layering.py` asserts on imports rather than on calls.)

The bands that colour a ratio, a TSB or a ramp live here rather than beside the other
colour helpers, because the number and the band that judges it are one rule: moving the
threshold without moving the maths is how two surfaces come to disagree about the same
day. See DESIGN_pmc_fitness_fatigue.md.
"""
import math
from datetime import timedelta
from typing import Any, Dict, Optional, Tuple

from stamind.clock import parse_date, today_str
from stamind.config import config
from stamind.text import red, yellow

# The PMC CTL/ATL EWMA time constants are config-backed under `garmin:` and read live
# every sweep (not frozen at import) so an edit can't drift derived values apart.
# Non-default windows are experimental — calibration caveat in config_template_full.yaml and
# DESIGN_pmc_fitness_fatigue.md §3.4.


def derivation_pad_days() -> int:
    """Raw history needed *before* a displayed window so the baselines and the CTL EWMA
    are warm for the earliest displayed day. Read live from config.

    `max(28, ceil(1.5*pmc_ctl_days))` (= 63 at defaults): the 28 floor pins the pad to
    the hardcoded 28-day baseline lookback in recompute_derived(); the 1.5*τ_ctl term
    warms CTL to ~78% at the left edge (the §3.3(b) accuracy caveat carries the
    residual). See DESIGN_pmc_fitness_fatigue.md §3.4."""
    return max(
        28,
        math.ceil(1.5 * config.pmc_ctl_days),
    )
def load_ratio(atl: Optional[float], ctl: Optional[float]) -> Optional[float]:
    """ATL/CTL — fatigue relative to the athlete's own fitness base, the scale-invariant
    companion to TSB's absolute difference (training_load.md §3).

    None when either EWMA is NULL (pre-recompute row) or CTL has not warmed above zero:
    there is no base to divide by, and a ratio against ~0 is noise, not a spike."""
    if atl is None or ctl is None or ctl <= 0.0:
        return None
    return atl / ctl
def compute_pmc(
    daily_load: Dict[str, float],
    start: str, end: str,
    ctl_days: int, atl_days: int,
    seed: Tuple[float, float] = (0.0, 0.0),
) -> Dict[str, Tuple[float, float, float]]:
    """CTL/ATL/TSB per calendar day via the classic Coggan discrete 1/τ EWMA.

    Walks EVERY calendar day in [start, end] (not just days with load), so rest days
    and gaps decay the EWMAs with zero load. Both EWMAs seed from `seed` (the state
    at end of `start - 1`; default (0.0, 0.0) reproduces the from-zero full-history
    sweep). A non-zero seed is the progression fold's anchor — the last stored row's
    (CTL, ATL) — so a fold from any day reproduces the unbroken series bit-exactly
    (DESIGN_progress_timeline.md §4).

        ctl_d = ctl_{d-1} + (load_d - ctl_{d-1}) / ctl_days
        atl_d = atl_{d-1} + (load_d - atl_{d-1}) / atl_days
        tsb_d = ctl_{d-1} - atl_{d-1}   # yesterday's values — the form you woke up with

    The TSB off-by-one is deliberate and load-bearing (training_load.md §1): today's
    form must NOT include today's workout. Returns {ISO date -> (ctl, atl, tsb)} at
    full precision — rounding moves to display, so the seed stays exact
    (DESIGN_progress_timeline.md §4). Empty {} on a degenerate span.
    """
    out: Dict[str, Tuple[float, float, float]] = {}
    if not start or not end:
        return out
    cur, last = parse_date(start), parse_date(end)
    if cur > last:
        return out
    ctl, atl = seed
    while cur <= last:
        ds = cur.isoformat()
        load = daily_load.get(ds, 0.0)
        tsb = ctl - atl                       # yesterday's (pre-update) balance
        ctl = ctl + (load - ctl) / ctl_days
        atl = atl + (load - atl) / atl_days
        out[ds] = (ctl, atl, tsb)
        cur += timedelta(days=1)
    return out
def pmc_warmup_cutoff_for(start: Optional[str], ctl_days: int) -> Optional[str]:
    """ISO date at/after which PMC display values have cleared the leading-edge warm-up.
    A date d is a warm-up artifact (suppress it) iff d < cutoff = start + ctl_days.
    Returns None when there is no history start."""
    if not start:
        return None
    return (parse_date(start) + timedelta(days=ctl_days)).isoformat()
def pmc_ramp(
    ctl_by_date: Dict[str, Optional[float]], date_iso: str, window: int = 7,
    warmup_cutoff: Optional[str] = None,
) -> Optional[float]:
    """CTL ramp = ctl(date) - ctl(date - window days), in load units per week.

    Uses the exact d-window day, else the nearest EARLIER day carrying a CTL value
    (interior-gap rule, §3.1) — bounded at 2*window back, and scaled to a per-window
    rate when the baseline is older than `window` days, so a stored-series hole can
    never quietly report a multi-week delta as "/week". Returns None when `date` has
    no CTL, when no usable baseline exists at/under date-window (don't emit garbage),
    or when the baseline lands before `warmup_cutoff` — a ramp measured against a
    suppressed warm-up-artifact CTL would read as a phantom overload spike (the §5.4
    straddle guard, applied here so every surface gets it). Callers pass the FULL
    stored series, never a short prompt window, so a small window never spuriously
    drops it."""
    today_ctl = ctl_by_date.get(date_iso)
    if today_ctl is None:
        return None
    # The baseline can only live on one of the `window` days in [d-2w, d-w]; look
    # those up directly (nearest to d-w first) instead of scanning the whole series.
    d0 = parse_date(date_iso)
    for offset in range(window, 2 * window + 1):
        base_date = (d0 - timedelta(days=offset)).isoformat()
        val = ctl_by_date.get(base_date)
        if val is None:
            continue
        if warmup_cutoff and base_date < warmup_cutoff:
            return None
        return round((today_ctl - val) * window / offset, 1)
    return None
def pmc_display_values(
    m: Dict[str, Any], warmup_cutoff: Optional[str]
) -> Tuple[Optional[float], Optional[float], Optional[float]]:
    """(ctl, atl, tsb) of a metrics row for DISPLAY: all None inside the §3.3(a)
    warm-up window (stored values there are leading-edge artifacts), the stored
    values (each possibly None) otherwise. The one blanking rule every user surface
    (status line, show-metrics table, CSV) shares."""
    if warmup_cutoff and m["date"] < warmup_cutoff:
        return None, None, None
    return m.get("ctl"), m.get("atl"), m.get("tsb")
def pmc_data_caveat(
    history_start: Optional[str],
    as_of: Optional[str] = None,
) -> Optional[Dict[str, Any]]:
    """Static "still warming up" flag for when today's own PMC values are short on
    history (§3.3b). A τ_ctl-day CTL EWMA needs months to settle, so while total history
    behind today is short the latest value is warm-up grade even though the leading-edge
    blanking (§3.3a) can't suppress *today*.

    Pure: takes the pmc_history_start() the caller already fetched. Returns
    {'n_days','history_start'} while N = today − history_start is under 3·τ_ctl
    (≈126 days), else None (above that the artifact is negligible). This is a flat flag,
    not a computed accuracy figure: a young/just-returned athlete simply sees low numbers
    under a plain flag. The caller renders the coach/user wording; the *direction* of any
    discount (is a low CTL an artifact or a real beginner?) is the LLM's to judge from the
    athlete's pre-DB history — the app only flags that the number is young."""
    if not history_start:
        return None
    end = as_of or today_str()
    n_days = (parse_date(end) - parse_date(history_start)).days
    if n_days < 0 or n_days >= 3 * config.pmc_ctl_days:
        return None
    return {"n_days": n_days, "history_start": history_start}


def color_load_ratio(ratio: float) -> str:
    """ATL/CTL (fatigue vs fitness) coloring — colors only the overload end, phase-blind
    (training_load.md §3).

    > 1.5 red (excessive relative spike), 1.3-1.5 yellow (caution). Everything at or
    below 1.3 stays uncolored: a *low* ratio is phase-dependent, not a fault — an
    intensity or realization mesocycle drives it to ~0.7 by design, and coloring that as
    "under-training" is what made the old ACWR band fight block periodization. Bands are
    half-open so no value is double-claimed."""
    s = f"{ratio:.2f}"
    if ratio > 1.5:
        return red(s)
    if ratio > 1.3:
        return yellow(s)
    return s


# The printed CTL | ATL | TSB triple won't subtract to the shown TSB, because TSB is
# CTL(yesterday) - ATL(yesterday) (training_load.md §1) while CTL/ATL are today's. This
# lag is correct (matching TrainingPeaks) but reads as an arithmetic error, so this
# one-line footnote rides wherever TSB is surfaced (per-day prompt lines, coach summary,
# tm status). Lives here — not in coach.formatting — because both the CLI and the coach
# layer render it.
PMC_TSB_LAG_NOTE = (
    "(Note: TSB is CTL(yesterday) - ATL(yesterday), so it won't equal the shown "
    "same-day CTL - ATL; this ~1-day lag is expected, not an error.)"
)


def color_tsb(tsb: float) -> str:
    """TSB (form) coloring — colors only the two risk ends, phase-blind
    (DESIGN_pmc_fitness_fatigue.md §6.1).

    < -30 red (excessive fatigue), > +25 yellow (detraining / over-tapered). The
    -30..+25 middle stays uncolored: its meaning is phase-dependent (mid-build a +15
    means fitness is decaying; peaking, it means race-ready), and that interpretive call
    belongs to the coach reading the science file, not to a phase-blind color map. Bands
    are half-open so no value is double-claimed."""
    s = f"{tsb:.1f}"
    if tsb < -30:
        return red(s)
    if tsb > 25:
        return yellow(s)
    return s


def color_ramp(ramp: float) -> str:
    """CTL ramp-rate coloring, bands touching so no value falls in an uncolored gap
    (§6.1): >= 8 red (unsustainable), 5 <= ramp < 8 yellow (watch), else plain. No green
    band — a low ramp is correct during a taper, so green would wrongly bless it."""
    s = f"{ramp:+.1f}"
    if ramp >= 8:
        return red(s)
    if 5 <= ramp < 8:
        return yellow(s)
    return s


def pmc_cells(
    ctl: Optional[float], atl: Optional[float], tsb: Optional[float]
) -> Tuple[str, str, str]:
    """The CTL/ATL/TSB triple as display strings, shared by every user surface that
    renders it (tm status, data show-metrics, the workout-adapt trajectory).

    Feed it the output of `pmc_display_values`, which already blanks warm-up rows.
    A missing value renders "—" and never "0.0": a printed "TSB 0.0" reads as a real
    neutral balance rather than as absent data (DESIGN_pmc_fitness_fatigue.md §6.1)."""
    return (
        f"{ctl:.1f}" if ctl is not None else "—",
        f"{atl:.1f}" if atl is not None else "—",
        color_tsb(tsb) if tsb is not None else "—",
    )


def pmc_warming_note(n_days: int, ctl_days: int) -> str:
    """The §3.3(b) "PMC still warming" caveat, parameterized by τ_ctl so it never
    hardcodes a 42 that a non-default config would make a lie."""
    return (
        f"PMC still warming: CTL based on {n_days} days of history (a {ctl_days}-day "
        f"average needs ~{3 * ctl_days} days to settle); fitness/freshness may read low."
    )
