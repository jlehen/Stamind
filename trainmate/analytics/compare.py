"""Which activity was which session, over a window of days.

Three surfaces ask this question — `workout compare` on the terminal, the compare tab of
the dashboard, and the Calendar marking pass — and each used to answer it with its own
copy of the same four steps: fetch the window's rows, pair them, walk the days, and say
what an unpaired activity was. A fix to one copy reached neither of the others.

`adherence_window` is now the one step that reads the database, and it is handed the
handle rather than importing one, so this module stays pure of the storage layer. What
each surface then does with the pairing — a table, JSON, a Calendar write — stays its own.
"""
from datetime import timedelta
from typing import Any, Dict, List, NamedTuple, Optional

from trainmate.analytics.adherence import STATUS_LABELS, analyze_adherence, classify_adherence
from trainmate.analytics.load import activity_load, rpe_divergence
from trainmate.clock import parse_date
from trainmate.config import config

__all__ = [
    "AdherenceWindow", "adherence_window", "adherence_verdicts", "compare_days",
    "format_actual",
]


class AdherenceWindow(NamedTuple):
    """What one window of days looked like, planned against actual.

    `results` is the pairing, one row per planned session. `discrepancies` is what
    departed from the plan and `informational` the efforts no mesocycle governed.
    `activities` and `covered_ranges` come back too because every caller walks the days
    afterwards and would otherwise re-read the same rows.
    """
    discrepancies: List[Any]
    results: List[Dict[str, Any]]
    informational: List[Dict[str, Any]]
    activities: List[Dict[str, Any]]
    covered_ranges: List[Any]
    history_days: int


def adherence_window(dbh, start_date: str, end_date: str, today: str) -> AdherenceWindow:
    """The planned-vs-actual pairing over [start_date, end_date], read from `dbh`.

    This never pulls from Garmin and never clamps the window: freshening the data and
    deciding which days to ask about belong to the caller, because the three callers
    disagree about both (the dashboard is read-only, `workout compare` pulls, the
    Calendar pass runs after a pull has already landed).

    It is fed **every** planned session in the window rather than the ones a caller means
    to show, so a narrowed listing is still graded against the whole day
    (ARCHITECTURE.md §5). `today` is what counts as "not finished yet"; a session dated
    on or after it is pending rather than missed.
    """
    workouts = dbh.get_workouts(start_date=start_date, end_date=end_date)
    activities = dbh.get_completed_activities(start_date=start_date, end_date=end_date)
    covered_ranges = dbh.get_mesocycle_ranges(start_date, end_date)
    history_days = (parse_date(end_date) - parse_date(start_date)).days + 1
    discrepancies, results, informational = analyze_adherence(
        planned_workouts=workouts,
        completed_activities=activities,
        start_date_obj=parse_date(start_date),
        history_days=history_days,
        minor_activity_load_threshold=config.minor_activity_load_threshold,
        covered_ranges=covered_ranges,
        pending_from=today,
        rejected_matches=dbh.get_rejected_matches(),
    )
    return AdherenceWindow(
        discrepancies, results, informational, activities, covered_ranges, history_days
    )


def adherence_verdicts(
    dbh, start_date: str, end_date: str, today: str
) -> Dict[int, Dict[str, Any]]:
    """Per-workout-id verdict over [start_date, end_date], for the listings that show
    what became of a planned session (ARCHITECTURE.md §5, "Backward adherence marking").

    Each value is `classify_adherence`'s ``{"status", "reasons"}`` plus the athlete-facing
    `label` and the `completed` activity it graded against — so a caller can name the
    verdict and the effort without re-looking-up either."""
    threshold = config.minor_activity_load_threshold
    verdicts: Dict[int, Dict[str, Any]] = {}
    for r in adherence_window(dbh, start_date, end_date, today).results:
        w = r['planned']
        if w.get('id') is None:
            continue
        verdict = classify_adherence(
            w, r['completed'], threshold, pending=r.get('pending', False)
        )
        verdicts[w['id']] = {
            **verdict,
            "label": STATUS_LABELS.get(verdict["status"], verdict["status"]),
            "completed": r['completed'],
        }
    return verdicts


def compare_days(
    start_date_obj, history_days: int, results: list, activities: list,
    sport_filter: Optional[str],
) -> list:
    """The window day by day, keeping only days with something to say: a list of
    ``(date, matched results, unmatched activities)`` with the sport filter applied.
    Both personas and the dashboard walk this list, so the pairing is decided once
    (DESIGN_render_persona.md §3).

    The sport filter is deliberately lopsided: a planned session matches on its exact
    lowercased sport, an activity on a substring of its type. `matched_act_ids` is built
    from the unfiltered pairing, so an activity that paired with a filtered-out session
    stays hidden rather than resurfacing as unplanned."""
    matched_act_ids = {
        r['completed']['activity_id'] for r in results if r['completed']
    }

    acts_by_date: dict = {}
    for act in activities:
        acts_by_date.setdefault(act['date'], []).append(act)

    results_by_date: dict = {}
    for r in results:
        results_by_date.setdefault(r['date'], []).append(r)

    days = []
    for d in range(history_days):
        date_curr = (start_date_obj + timedelta(days=d)).strftime("%Y-%m-%d")
        day_results = results_by_date.get(date_curr, [])
        day_acts = acts_by_date.get(date_curr, [])
        unplanned = [a for a in day_acts if a['activity_id'] not in matched_act_ids]

        if sport_filter:
            day_results = [
                r for r in day_results
                if r['planned']['sport_type'].lower() == sport_filter
            ]
            unplanned = [
                a for a in unplanned
                if sport_filter in a['activity_type'].lower()
            ]

        if not day_results and not unplanned:
            continue
        days.append((date_curr, day_results, unplanned))
    return days


def format_actual(act: Dict[str, Any], divergence: bool = False) -> str:
    """Compact 'actual effort' line for one completed activity, e.g.
    '[running] Morning Run (48min, load 62, TSS 58)'.

    One renderer for every surface that names the effort a planned session matched: the
    Calendar adherence header, `workout compare`'s ACTUAL row and `workout list -v`.
    `divergence` adds the "load from RPE" note — compare shows it, the Calendar header
    does not, and that is the only difference the three ever had."""
    parts = [f"{act['duration_sec'] / 60:.0f}min", f"load {activity_load(act):.0f}"]
    if act.get('tss'):
        parts.append(f"TSS {act['tss']:.0f}")
    if act.get('rpe'):
        parts.append(f"RPE {act['rpe']}")
    line = f"[{act['activity_type']}] {act['activity_name']} ({', '.join(parts)})"
    if not divergence:
        return line
    div = rpe_divergence(act)
    if div is None:
        return line
    return f"{line} [load from RPE: HR under-counted {div:.1f}x]"
