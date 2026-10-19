"""The picture: what a `workout adapt` run saw, kept so the morning push can tell what is new
(DESIGN_quiet_morning.md §3, §4).

A run takes it where it reads its inputs, the proposal carries it, and the step that persists
the run's outcome writes it to the `settings` row `adapt_last_seen`. The next morning the
push takes a fresh one with the same function and compares the two: identifiers and hashes,
never the sources' timestamps. Reads the database and the config only, and never a model.
"""
import hashlib
import json
from datetime import date, datetime
from typing import Any, Dict, List, Optional

from stamind import clock, settings
from stamind.analytics.baselines import classify_metric, is_anomalous
from stamind.analytics.compare import adherence_verdicts
from stamind.analytics.load import activity_load
from stamind.clock import shift
from stamind.config import config
from stamind.plan_inputs import athlete_science_documents, clean_constraints_all, goals_hash
from stamind.strength import planner as strength_planner


def _hash(value: Any) -> str:
    return hashlib.sha256(
        json.dumps(value, sort_keys=True, default=str).encode("utf-8")
    ).hexdigest()


def _day(day: str) -> str:
    return f"{date.fromisoformat(day):%A}"


def _window_start(day: str) -> str:
    """The first day of the metrics window a run evaluated on `day` reads."""
    return shift(day, 1 - config.metrics_lookback_days)


def take(db: Any, day: str) -> Dict[str, Any]:
    """The picture of a run evaluated on `day`: the keys of the table in §3, read the way
    `workout_adapt` reads them. `at` is when it was taken, for the journal line."""
    start = _window_start(day)
    meso = db.get_active_mesocycle(day)
    range_end = meso["end_date"] if meso else day
    nights = [
        m["date"] for m in db.get_metrics_cache(start_date=start, end_date=day)
        if m.get("sleep_score") is not None
    ]
    written = db.newest_change_with_sessions(exclude_kind="adapt")
    return {
        "date": day,
        "at": clock.now().isoformat(),
        "night": max(nights) if nights else None,
        "activities": [
            a["activity_id"] for a in db.get_completed_activities(start, day)
        ],
        "written": written["id"] if written else 0,
        "constraints": _hash(clean_constraints_all(db.get_constraints(day, range_end))),
        "signals": [
            [s["id"], s["updated"]]
            for s in db.get_daily_signals(start_date=shift(start, -1), end_date=day)
        ],
        "plan": [meso["macrocycle_id"], meso["id"], meso["end_date"]] if meso else None,
        "goals": goals_hash(db.upcoming_objectives()),
        "benchmarks": max((r["id"] for r in db.get_benchmark_results()), default=0),
        "profile": _hash(config.user_profile),
        "science": _hash(athlete_science_documents()),
    }


def last(db: Any) -> Optional[Dict[str, Any]]:
    """The last run's picture, or None when none was written yet. A row that will not parse
    raises, and the gate asks the week planner (§6)."""
    stored = db.get_setting(settings.ADAPT_LAST_SEEN)
    return json.loads(stored) if stored else None


def taken(picture: Dict[str, Any]) -> str:
    """When a picture was taken, as the athlete's clock read it: 'Thursday 08:00'."""
    return clock.to_local(datetime.fromisoformat(picture["at"])).strftime("%A %H:%M")


def remember(db: Any, proposal: Any) -> None:
    """Writes the picture a proposal carries, when its run was evaluated on today (§3, §6).
    A tap's proposal and a tweak's carry none, and a `--date` run's names another day."""
    seen = proposal.seen
    if seen is None or seen["date"] != clock.today_str():
        return
    db.set_setting(settings.ADAPT_LAST_SEEN, json.dumps(seen))


def _new_activities(
    db: Any, before: Dict[str, Any], now: Dict[str, Any], verdicts: Dict[int, Dict[str, Any]]
) -> List[str]:
    """The activities present now that the last run never saw and that are not clean: done
    as planned with no reason attached, or unmatched and below the minor threshold. A
    matched activity is never minor (§3)."""
    fresh = set(now["activities"]) - set(before["activities"])
    if not fresh:
        return []
    matched = {v["completed"]["activity_id"]: v for v in verdicts.values() if v["completed"]}
    threshold = config.minor_activity_load_threshold

    def is_new(act: Dict[str, Any]) -> bool:
        verdict = matched.get(act["activity_id"])
        if verdict is None:
            return activity_load(act) >= threshold
        return verdict["status"] != "done" or bool(verdict["reasons"])

    return [
        f"a new activity on {_day(a['date'])}: {a.get('activity_name') or a['activity_type']}"
        for a in db.get_completed_activities(_window_start(now["date"]), now["date"])
        if a["activity_id"] in fresh and is_new(a)
    ]


def _missed(db: Any, since: str, today: str, verdicts: Dict[int, Dict[str, Any]]) -> List[str]:
    """The sessions dated from the last run's day to yesterday with the verdict missed (§3)."""
    return [
        f"{_day(w['date'])}'s {w['title']} is missed"
        for w in db.get_workouts(start_date=since, end_date=today)
        if (verdicts.get(w["id"]) or {}).get("status") == "missed"
    ]


def _strength_work(db: Any, now: Dict[str, Any]) -> bool:
    """The strength planner's own work test, asked live: a gym session ahead with no sets, or
    one whose kilograms were checked before the strength history last changed (§3)."""
    if not now["plan"]:
        return False
    range_end = now["plan"][2]
    live = db.get_workouts(start_date=now["date"], end_date=range_end)
    return strength_planner.has_work(live, now["date"], range_end)


def news(db: Any, before: Dict[str, Any], now: Dict[str, Any]) -> List[str]:
    """Each difference between the last run's picture and the fresh one, named, and the
    strength planner's work test (§3). Empty when nothing is new."""
    verdicts = adherence_verdicts(db, before["date"], now["date"], now["date"])
    reasons = _new_activities(db, before, now, verdicts)
    reasons += _missed(db, before["date"], now["date"], verdicts)
    if now["written"] != before["written"]:
        reasons.append("a session was written")
    for key, what in (
        ("constraints", "a constraint changed"), ("plan", "the plan changed"),
        ("goals", "a goal changed"), ("profile", "the profile changed"),
        ("science", "a science guideline changed"),
    ):
        if now[key] != before[key]:
            reasons.append(what)
    if {tuple(s) for s in now["signals"]} - {tuple(s) for s in before["signals"]}:
        reasons.append("a daily signal changed")
    if now["benchmarks"] > before["benchmarks"]:
        reasons.append("a benchmark was logged")
    if _strength_work(db, now):
        reasons.append("the strength planner has work")
    return reasons


def nights(db: Any, since: Optional[str], today: str) -> Dict[str, str]:
    """Each day after `since`, up to today, that has a sleep score, with the sentence that
    says what is not normal about it, or "" for a normal night: HRV suppressed, resting HR
    elevated or sleep poor, by the verdicts `status` colours with (§4). A day without a
    sleep score is unknown and is not graded."""
    start = shift(since, 1) if since else _window_start(today)
    graded: Dict[str, str] = {}
    for row in db.get_metrics_cache(start_date=start, end_date=today):
        if row.get("sleep_score") is None:
            continue
        baseline = db.get_baseline(row["date"])
        off = []
        for kind, label, value, bad in (
            ("hrv", "HRV", row.get("hrv"), "suppressed"),
            ("rhr", "resting HR", row.get("rhr"), "elevated"),
            ("sleep", "sleep", row.get("sleep_score"), "poor"),
        ):
            if is_anomalous(classify_metric(kind, value, baseline)):
                off.append(f"{label} {bad}")
        graded[row["date"]] = ""
        if off:
            graded[row["date"]] = f"{_day(row['date'])}'s night is not normal: {', '.join(off)}"
    return graded
