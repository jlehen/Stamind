"""Per-mesocycle, per-sport, per-zone time in zone — the intensity axis TSS folds away.

``load = volume x intensity``, and TSS is the product: given it you can recover neither
factor, so a mesocycle whose easy days drifted to tempo reads as flat weekly TSS and a flat
PMC. Zone distribution is the only intensity signal in the schema. The whole rationale —
why every zone is reported separately, why per sport, why rates over completed weeks
only — lives in DESIGN_intensity_distribution.md.

The zone model itself: the currencies, which sports qualify and in which, the
per-sport sums, and the zone target carried on a planned session. `zone_tables.py`
renders these rows as text and `mesocycle_report.py` assembles the report.

No DB access here (same rule as ``trainmate.sports``): callers pass activity rows or a
fetch callable, so one implementation serves `workout adapt`, the strategy prompt and
the CLI mesocycle summary.
"""
from typing import Any, Dict, List, NamedTuple, Optional, Sequence, Tuple

from trainmate.config import config
from trainmate.sports import canonical_sport


class Currency(NamedTuple):
    """One measurement currency and the zone model it is bucketed into (§4/§5)."""
    key: str
    tag: str
    prefix: str
    labels: Tuple[str, ...]


# Power first: it is instantaneous, so it is the currency to read on a short-interval
# session (§7). Every zone stands alone — no Z1-2/Z3/Z4-5 banding (§5).
CURRENCIES: Tuple[Currency, ...] = (
    Currency("power", "[pwr]", "power_zone", (
        "recovery", "endurance", "tempo", "threshold", "VO2max",
        "anaerobic", "neuromuscular",
    )),
    Currency("hr", "[HR]", "zone", (
        "recovery", "aerobic", "tempo", "threshold", "VO2max+",
    )),
)
CURRENCY_BY_KEY: Dict[str, Currency] = {c.key: c for c in CURRENCIES}


# A week's row admits it is incomplete below this. Uncovered time is not always a
# recording failure — it is also the rest between sets, the chairlift back up, the held
# pose — so the bar is per sport, each set near that sport's own 25th percentile (§11).
# Deliberately NOT `hr_zone_coverage_min`, which is a "safe to compute load from" bar
# (§9.6). Keys must be CANONICAL sports: the lookup canonicalizes first, so an alias key
# is unreachable and falls back to the global bar.
COVERAGE_MIN_BY_SPORT: Dict[str, float] = {
    "strength_training": 0.45,
    "downhill_skiing": 0.15,
    "indoor_climbing": 0.15,
    "hiking": 0.10,
    "yoga": 0.05,
}


def coverage_display_min(sport: str) -> float:
    """The bar one sport's weekly row is graded against: a config override first, then
    the shipped per-sport table, then the global default (§11)."""
    key = canonical_sport(sport)
    override = config.zone_coverage_display_min_by_sport.get(key)
    if override is not None:
        return override
    return COVERAGE_MIN_BY_SPORT.get(key, config.zone_coverage_display_min)


def judgeable(act: Dict[str, Any]) -> bool:
    """Whether an activity is big enough to carry a claim about recording quality, or
    about undercounted load (`config.zone_min_activity_minutes`, §11).

    A 5-minute mobility activity with a cold strap is not evidence that a 340-TSS week is
    undercounted, and it is not evidence about the strap either — it is below the noise
    floor of both questions. Its load and its zone minutes still count everywhere; only
    its vote on the markers is withheld."""
    return float(act.get("duration_sec") or 0.0) / 60.0 >= config.zone_min_activity_minutes
# Power is instantaneous and so the currency to read, but only once it can see the whole
# window — the fraction it cannot see is the meterless easy commutes (§9.6). Shares a
# number with the bar above and nothing else: that one grades a single week's row, this
# one picks the column a whole table is drawn in.
PREFER_POWER_COVERAGE_MIN = 0.8

# --------------------------------------------------------- zone aggregation

class ZoneRow(NamedTuple):
    """One (canonical sport x currency) row: seconds per zone over a window (§4).

    `coverage` is that currency's recorded seconds over the sport's TOTAL duration in
    the window, so both currencies share one denominator and read comparably (§7): a
    ride with no meter contributes its full duration and zero power seconds.

    `judged_coverage` is the same ratio over the activities big enough to say anything
    about recording quality (`judgeable`), and is what the `!` marker reads; None when
    none of the window's activities for this sport clear that floor, which is not a
    failing recording but an unanswerable question (§11). `coverage` keeps every
    session, because the header percentage and the currency choice are about how much
    of the training this currency saw — a different question.
    """
    sport: str
    currency: str
    seconds: Tuple[float, ...]
    coverage: float
    judged_coverage: Optional[float] = None

    @property
    def total(self) -> float:
        return sum(self.seconds)

    @property
    def undercounted(self) -> bool:
        """Whether this row should mark itself incomplete (§11): a judgeable coverage
        below the sport's own bar. Unjudgeable rows never mark."""
        return (
            self.judged_coverage is not None
            and self.judged_coverage < coverage_display_min(self.sport)
        )


def sport_durations(activities: Sequence[Dict[str, Any]]) -> Dict[str, float]:
    """Total recorded duration per canonical sport — `zone_rows`' denominator, exposed
    on its own because a sport can have activities and no zone rows at all.

    That distinction is the whole reason the weekly table needs three states rather than
    two: no duration means not trained, duration with no zone seconds means trained and
    not recorded, and the two must not render as the same thing (§9.6).
    """
    out: Dict[str, float] = {}
    for act in activities:
        sport = canonical_sport(act.get("activity_type") or "unknown")
        out[sport] = out.get(sport, 0.0) + float(act.get("duration_sec") or 0.0)
    return out


def pick_currency(coverage: Dict[str, float]) -> Optional[str]:
    """The one currency a sport's table is drawn in, from that sport's per-currency
    coverage over the WHOLE window (§9.6).

    Prefer power once it reaches `PREFER_POWER_COVERAGE_MIN`, otherwise take whichever
    currency covers more. Power is more precise at the top end and blind to every ride
    without a meter, so below that bar it cannot answer "did my easy volume shrink" —
    the fraction it cannot see IS the easy commutes. Chosen once over the window and
    never per row: a column that switched currency mid-table would be adding HR minutes
    to power minutes down the page, §6's one prohibition committed vertically.
    """
    power, hr = coverage.get("power") or 0.0, coverage.get("hr") or 0.0
    if power >= PREFER_POWER_COVERAGE_MIN:
        return "power"
    if not power and not hr:
        return None
    return "power" if power > hr else "hr"


def currency_by_sport(activities: Sequence[Dict[str, Any]]) -> Dict[str, str]:
    """`{canonical sport: 'power'|'hr'}` over one window — §9.6's currency rule applied to
    raw activity rows, for callers that have no weekly payload to read it from.

    `workout generate` uses it to pick the currency it PRESCRIBES in (§9.8). One rule
    applied twice: get it wrong in either place and the plan is written in a currency the
    table never renders. Sports with no recorded zone seconds are absent from the result
    — swimming is anchored on CSS and strength on e1RM, and neither yields a zone model.
    """
    coverage: Dict[str, Dict[str, float]] = {}
    for row in zone_rows(activities):
        coverage.setdefault(row.sport, {})[row.currency] = row.coverage
    out = {}
    for sport, cov in coverage.items():
        picked = pick_currency(cov)
        if picked:
            out[sport] = picked
    return out


# A sport must hold this share of the window's duration to earn a table by default; the
# rest are named in the footer, never silently dropped.
ZONE_SPORT_MIN_SHARE = 0.10


def window_sport_stats(weeks: List[Dict[str, Any]]) -> Dict[str, Dict[str, Any]]:
    """Per canonical sport over the displayed window: total duration and total recorded
    seconds per currency — everything the sport filter, the 10% floor and the currency
    choice read.

    All three are computed over the DISPLAYED window, which is what the header's share
    figure means. One consequence to expect rather than to fix: `--weeks all` can qualify
    a different set of sports than the default does, and can draw one of them in a
    different currency, because both rules read the window they are given (§9.6).
    """
    stats: Dict[str, Dict[str, Any]] = {}

    def entry(sport: str) -> Dict[str, Any]:
        return stats.setdefault(sport, {"seconds": 0.0, "zone_seconds": {}})

    for week in weeks:
        for sport, secs in (week.get("sport_seconds") or {}).items():
            entry(sport)["seconds"] += secs
        for row in week.get("zone_rows") or []:
            zones = entry(row.sport)["zone_seconds"]
            zones[row.currency] = zones.get(row.currency, 0.0) + row.total
    for agg in stats.values():
        agg["coverage"] = {
            cur: (secs / agg["seconds"] if agg["seconds"] else 0.0)
            for cur, secs in agg["zone_seconds"].items()
        }
    return stats


def select_zone_sports(
    explicit: Optional[Sequence[str]], preferences: Sequence[str],
    stats: Dict[str, Dict[str, Any]],
) -> Tuple[List[str], List[str], List[str]]:
    """`(sports, omitted_low_volume, omitted_no_zone_data)` — which sports get a table.

    Naming sports explicitly overrides all three filters; the default is every
    `sport_preferences` entry, **in config order** (the athlete's own priority list, and
    stable across invocations — a screen someone checks daily must not reshuffle its rows
    because last week's volume moved) that has zone data in the window and holds at least
    `ZONE_SPORT_MIN_SHARE` of its duration.
    """
    if explicit:
        return [canonical_sport(s) for s in explicit], [], []
    total = sum(agg["seconds"] for agg in stats.values())
    sports, low, no_data = [], [], []
    for name in preferences:
        sport = canonical_sport(name)
        agg = stats.get(sport)
        if not agg or not agg["seconds"]:
            continue
        if not any(agg["zone_seconds"].values()):
            no_data.append(sport)
        elif total and agg["seconds"] / total < ZONE_SPORT_MIN_SHARE:
            low.append(sport)
        else:
            sports.append(sport)
    return sports, low, no_data


def zone_currency(
    stats: Dict[str, Dict[str, Any]], sport: str, forced: Optional[str] = None
) -> Optional[str]:
    """The currency one sport's table is drawn in. `forced` (`--power`/`--hr`) wins where
    that currency has data, and has no effect on a sport that has only the other."""
    agg = stats.get(sport)
    if not agg:
        return None
    if forced and agg["zone_seconds"].get(forced):
        return forced
    return pick_currency(agg["coverage"])


# The window the planning currency is chosen over. Authoring has no window of its own —
# at generation time there is only forward plan — so it borrows the display default, and
# the ordinary case agrees by construction (§9.8).
PLANNING_COVERAGE_WEEKS = 8


def parse_planned_zones(
    payload: Dict[str, Any]
) -> Tuple[Optional[str], Optional[List[Optional[int]]]]:
    """`(currency, 7-slot seconds list)` from one LLM-authored workout, or `(None, None)`.

    Validates rather than corrects: an unknown currency, a non-list, or an all-zero
    distribution yields nothing at all, and anything past the currency's zone count is
    dropped. What it does NOT do is scale the seconds to match `duration_minutes` — the
    numbers are a prescription, not an accounting identity, and rescaling them would put
    the app back in the business of correcting the model rather than aligning for it (§7).
    """
    currency = (payload.get("planned_zone_currency") or "").strip().lower()
    spec = CURRENCY_BY_KEY.get(currency)
    raw = payload.get("planned_zone_sec")
    if spec is None or not isinstance(raw, (list, tuple)):
        return None, None
    out: List[Optional[int]] = [None] * 7
    for i in range(min(len(raw), len(spec.labels))):
        try:
            value = int(round(float(raw[i])))
        except (TypeError, ValueError):
            continue
        out[i] = max(0, value)
    if not any(out):
        return None, None
    return currency, out


def planned_zone_seconds(workout: Dict[str, Any]) -> Optional[Tuple[str, Tuple[int, ...]]]:
    """`(currency, seconds per zone)` from a planned workout's columns, or None when the
    session carries no intensity target (§9.8). A proposal not yet written carries the week
    planner's list instead, read through the check the write applies to it."""
    if "planned_zone_sec" in workout:
        currency, raw = parse_planned_zones(workout)
        if currency is None:
            return None
        count = len(CURRENCY_BY_KEY[currency].labels)
        return currency, tuple(int(s or 0) for s in raw[:count])
    currency = (workout.get("planned_zone_currency") or "").strip().lower()
    spec = CURRENCY_BY_KEY.get(currency)
    if spec is None:
        return None
    secs = tuple(
        int(workout.get(f"planned_zone{i}_sec") or 0)
        for i in range(1, len(spec.labels) + 1)
    )
    return (currency, secs) if any(secs) else None


def format_planned_zones(workout: Dict[str, Any]) -> Optional[str]:
    """'Target: ~25min recovery, ~30min aerobic, ~10min threshold' — the prescription an
    athlete can act on, rendered FROM the columns at display time and never stored, so
    the sentence cannot drift from the columns it describes (§9.8).

    Zone NAMES, not indices: `30 min aerobic` survives a ruler shift in a way `30 min Z2`
    does not — the index is the join key, the name is the prescription.
    """
    parsed = planned_zone_seconds(workout)
    if parsed is None:
        return None
    currency, secs = parsed
    labels = CURRENCY_BY_KEY[currency].labels
    parts = [
        f"~{int(round(s / 60.0))}min {labels[i]}"
        for i, s in enumerate(secs) if s
    ]
    return f"Target: {', '.join(parts)}" if parts else None


def zone_rows(activities: Sequence[Dict[str, Any]]) -> List[ZoneRow]:
    """Zone seconds per canonical sport and currency, busiest sport first.

    Currency is per ACTIVITY, not per sport (§6): a ride that recorded both joins its
    sport's HR row and its power row. A currency row exists only where that currency
    has recorded seconds, so strength training never grows an empty `[pwr] 0%` row.
    """
    duration: Dict[str, float] = {}
    acc: Dict[Tuple[str, str], List[float]] = {}
    # The same two totals over judgeable activities only — the basis for `!` (§11).
    judged_duration: Dict[str, float] = {}
    judged: Dict[Tuple[str, str], float] = {}
    for act in activities:
        sport = canonical_sport(act.get("activity_type") or "unknown")
        secs = float(act.get("duration_sec") or 0.0)
        big = judgeable(act)
        duration[sport] = duration.get(sport, 0.0) + secs
        if big:
            judged_duration[sport] = judged_duration.get(sport, 0.0) + secs
        for cur in CURRENCIES:
            vals = [
                float(act.get(f"{cur.prefix}{i}_sec") or 0.0)
                for i in range(1, len(cur.labels) + 1)
            ]
            if not any(vals):
                continue
            bucket = acc.setdefault((sport, cur.key), [0.0] * len(cur.labels))
            for i, v in enumerate(vals):
                bucket[i] += v
            if big:
                key = (sport, cur.key)
                judged[key] = judged.get(key, 0.0) + sum(vals)

    def _judged_coverage(sport: str, key: str) -> Optional[float]:
        denom = judged_duration.get(sport)
        return (judged.get((sport, key), 0.0) / denom) if denom else None

    rows = [
        ZoneRow(
            sport=sport, currency=key, seconds=tuple(vals),
            coverage=(sum(vals) / duration[sport]) if duration.get(sport) else 0.0,
            judged_coverage=_judged_coverage(sport, key),
        )
        for (sport, key), vals in acc.items()
    ]
    order = [c.key for c in CURRENCIES]
    rows.sort(key=lambda r: (-duration.get(r.sport, 0.0), r.sport, order.index(r.currency)))
    return rows


def planned_zone_rows(workouts: Sequence[Dict[str, Any]]) -> List[ZoneRow]:
    """The same `(sport x currency x zone)` shape, summed over PLANNED sessions — the
    future half of the weekly table (§9.8).

    `coverage` is 1.0 throughout: a prescription is not a recording, so there is no
    measurement gap to report and the `!` marker has nothing to say about these rows.
    """
    acc: Dict[Tuple[str, str], List[float]] = {}
    for w in workouts:
        parsed = planned_zone_seconds(w)
        if parsed is None:
            continue
        currency, secs = parsed
        sport = canonical_sport(w.get("sport_type") or "unknown")
        bucket = acc.setdefault((sport, currency), [0.0] * len(secs))
        for i, s in enumerate(secs):
            bucket[i] += s
    return [
        ZoneRow(sport=sport, currency=key, seconds=tuple(vals), coverage=1.0)
        for (sport, key), vals in acc.items()
    ]


class WeekZoneState(NamedTuple):
    """What one week says about one sport in one currency.

    Three states, not two (DESIGN_intensity_distribution.md §9.6): a week with no
    duration in this sport was *not trained* and is unmarked; a week with duration but
    nothing recorded in this currency is *undercounted*, and calling that "not trained"
    would turn §7's meaning exactly backwards; a week with a row reports its seconds.
    `undercounted` reads the JUDGEABLE duration, so a single five-minute activity with
    no zone data cannot light the week (§11).

    `currency_mismatch` applies to future weeks only: work planned in the other
    currency is offered as a fact and never converted, because Power Z6/Z7 have no HR
    equivalent and collapsing seven zones onto five would be banding by the back door
    (§5, §9.8).
    """
    seconds: Optional[Tuple[float, ...]]
    trained: bool
    undercounted: bool
    currency_mismatch: bool


def week_zone_state(
    week: Dict[str, Any], sport: str, currency: str, is_future: bool = False
) -> WeekZoneState:
    """The one derivation of a week's zone state, for every surface that shows it.

    The CLI table and /api/zones each used to derive this, citing the same design
    sections — and had already drifted on which duration answers "trained".
    """
    rows_key = "planned_zone_rows" if is_future else "zone_rows"
    rows = week.get(rows_key) or []
    row = next((r for r in rows if r.sport == sport and r.currency == currency), None)

    trained = bool((week.get("sport_seconds") or {}).get(sport))
    judged = bool((week.get("judged_sport_seconds") or {}).get(sport))

    if row is not None:
        undercounted = bool(row.undercounted)
    else:
        # No row in this currency: the week is undercounted only if it holds enough
        # judgeable duration to support the claim, and only in the measured past.
        undercounted = judged and not is_future

    mismatch = False
    if is_future and row is None:
        mismatch = any(r.sport == sport for r in (week.get("planned_zone_rows") or []))

    return WeekZoneState(
        seconds=tuple(row.seconds) if row is not None else None,
        trained=trained,
        undercounted=undercounted,
        currency_mismatch=mismatch,
    )
