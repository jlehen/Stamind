"""A run, a ride or a swim written as steps (DESIGN_endurance_steps.md).

The week planner writes each running, cycling and swimming session as a list of steps. This
module checks them (§4), works out the remainder and the seconds in each zone, prints the
step block at the top of the description (§2, §5), and prints it again when a threshold
changes (§6). The stored steps are as the week planner wrote them, "remainder" included.
"""
from datetime import date
from typing import Any, Dict, List, Optional, Sequence, Tuple

from stamind import journal
from stamind.analytics.intensity import CURRENCY_BY_KEY
from stamind.clock import today_str
from stamind.sports import canonical_sport
from stamind.strength.prescription import body_of, title_line

SPORTS = ("running", "cycling", "swimming")
PHASES = ("warm-up", "work", "steady", "cool-down")
REMAINDER = "remainder"
# A swim's step times are the week planner's estimates, so they may miss the duration by this
# much (§8 choice 26).
SWIM_SLACK_SECONDS = 60
# How a target names its threshold on the page.
ANCHOR_NAMES = {"ftp": "FTP", "lthr": "LTHR", "threshold_pace": "threshold", "css": "CSS"}


def writes_steps(entry: Any) -> bool:
    """Whether an entry of the week planner's answer writes a run, a ride or a swim. A `keep`
    or a `drop` writes no session and is not checked (§4)."""
    if not isinstance(entry, dict) or entry.get("keep") or entry.get("drop"):
        return False
    return canonical_sport(entry.get("sport_type") or "") in SPORTS


def _number(value: Any) -> bool:
    return isinstance(value, (int, float)) and not isinstance(value, bool)


def _positive(value: Any) -> bool:
    return _number(value) and value > 0


def _repeat(step: Dict[str, Any]) -> int:
    return step.get("repeat") or 1


def _shape(steps: Any, swim: bool) -> Optional[str]:
    """Check 1 of §4: what is wrong with the steps' shape, or None."""
    if not isinstance(steps, list) or not steps:
        return "has no steps"
    remainders = 0
    for number, step in enumerate(steps, start=1):
        if not isinstance(step, dict) or step.get("phase") not in PHASES:
            return f"step {number} has no phase among {', '.join(PHASES)}"
        if step.get("seconds") == REMAINDER:
            remainders += 1
            if swim:
                return "a swim has no remainder step"
            if step.get("repeat") or step.get("recovery"):
                return f"step {number} is the remainder, which has no repeat and no recovery"
            continue
        if not _positive(step.get("seconds")):
            return f"step {number} has no positive number of seconds"
        repeat = step.get("repeat")
        if repeat is not None and (not isinstance(repeat, int) or isinstance(repeat, bool)
                                   or repeat < 1):
            return f"step {number} repeats a number of times that is not a whole number"
        recovery = step.get("recovery")
        if recovery is not None and not (
            isinstance(recovery, dict) and _positive(recovery.get("seconds"))
        ):
            return f"the recovery of step {number} has no positive number of seconds"
    if remainders > 1:
        return f"{remainders} steps are the remainder, and at most one may be"
    return None


def _fixed_seconds(steps: Sequence[Dict[str, Any]]) -> float:
    """The seconds every step but the remainder takes, repeats and recoveries included."""
    total = 0.0
    for step in steps:
        if step.get("seconds") == REMAINDER:
            continue
        recovery = (step.get("recovery") or {}).get("seconds") or 0
        total += _repeat(step) * (step["seconds"] + recovery)
    return total


def _minutes(seconds: float) -> str:
    return f"{seconds / 60:g}"


def _fit(steps: Sequence[Dict[str, Any]], duration_minutes: Any, swim: bool) -> Optional[str]:
    """Check 2 of §4: the steps fill the session's minutes, a swim's to within
    SWIM_SLACK_SECONDS, and a remainder gets some time."""
    budget = (duration_minutes or 0) * 60
    fixed = _fixed_seconds(steps)
    if not any(step.get("seconds") == REMAINDER for step in steps):
        slack = SWIM_SLACK_SECONDS if swim else 0
        if abs(round(fixed) - round(budget)) <= slack:
            return None
        return f"the steps take {_minutes(fixed)} of the {_minutes(budget)} minutes"
    if budget > fixed:
        return None
    return (
        f"the steps without the remainder take {_minutes(fixed)} of the {_minutes(budget)} "
        "minutes, which leaves no time for the remainder"
    )


def _zones(steps: Sequence[Dict[str, Any]], currency: Optional[str]) -> Optional[str]:
    """Check 3 of §4: every step and every recovery has a zone of the sport's zone type."""
    if currency is None:
        return None
    count = len(CURRENCY_BY_KEY[currency].labels)
    for number, step in enumerate(steps, start=1):
        for part, where in ((step, f"step {number}"),
                            (step.get("recovery"), f"the recovery of step {number}")):
            if part is None:
                continue
            zone = part.get("zone")
            if not (isinstance(zone, int) and not isinstance(zone, bool) and 1 <= zone <= count):
                return f"{where} has no {currency} zone (1-{count})"
    return None


def fault(entry: Dict[str, Any], zone_currencies: Dict[str, str]) -> Optional[str]:
    """The first check of §4 a run, ride or swim fails, as the line WHAT TO FIX shows the week
    planner, or None when it passes."""
    sport = canonical_sport(entry.get("sport_type") or "")
    steps = entry.get("steps")
    problem = (
        _shape(steps, sport == "swimming")
        or _fit(steps, entry.get("duration_minutes"), sport == "swimming")
        or _zones(steps, zone_currencies.get(sport))
    )
    if problem is None:
        return None
    day = str(entry.get("date") or "")
    try:
        day = f"{date.fromisoformat(day):%a} {day}"
    except ValueError:
        pass
    return f"{day} {sport}: {problem}"


def resolve(steps: Sequence[Dict[str, Any]], duration_minutes: Any) -> List[Dict[str, Any]]:
    """The steps with the remainder's seconds worked out from the duration; never below 0."""
    left = max(0.0, (duration_minutes or 0) * 60 - _fixed_seconds(steps))
    return [
        {**step, "seconds": left} if step.get("seconds") == REMAINDER else step
        for step in steps
    ]


def zone_seconds(steps: Sequence[Dict[str, Any]], currency: str) -> List[int]:
    """The seconds in each zone of `currency`, low to high, from resolved steps (§5)."""
    out = [0.0] * len(CURRENCY_BY_KEY[currency].labels)
    for step in steps:
        out[step["zone"] - 1] += _repeat(step) * step["seconds"]
        recovery = step.get("recovery")
        if recovery:
            out[recovery["zone"] - 1] += _repeat(step) * recovery["seconds"]
    return [round(seconds) for seconds in out]


# --- printing (§2, §5) ---

def _span(low: float, high: float, fmt) -> str:
    first, last = fmt(low), fmt(high)
    return first if first == last else f"{first}–{last}"


def _mmss(seconds: float) -> str:
    minutes, rest = divmod(round(seconds), 60)
    return f"{minutes}:{rest:02d}"


def _gap(low: float, high: float) -> str:
    """How far from threshold pace: "+ 10–20 s", "− 5 s"."""
    fmt = lambda seconds: f"{seconds:g}"  # noqa: E731
    if low >= 0:
        return f"+ {_span(low, high, fmt)} s"
    if high <= 0:
        return f"− {_span(-high, -low, fmt)} s"
    return f"− {fmt(-low)} to + {fmt(high)} s"


def _target(target: Any, thresholds: Dict[str, Any]) -> Optional[str]:
    """"106–112% FTP (250–264 W)" or "4:50–5:00/km (threshold + 10–20 s)"; None when the
    athlete has no value for the threshold it names, or it is not one Stamind knows."""
    if not isinstance(target, dict):
        return None
    anchor, low = target.get("anchor"), target.get("low")
    high = target.get("high", low)
    value = thresholds.get(anchor) if anchor in ANCHOR_NAMES else None
    if not (_number(value) and _number(low) and _number(high)):
        return None
    low, high = sorted((low, high))
    name = ANCHOR_NAMES[anchor]
    if anchor in ("ftp", "lthr"):
        unit = "W" if anchor == "ftp" else "bpm"
        absolute = _span(low, high, lambda share: str(round(value * share / 100)))
        return f"{_span(low, high, lambda share: f'{share:g}')}% {name} ({absolute} {unit})"
    # threshold_pace is stored in minutes per km, css in seconds per 100 m.
    base, per = (value * 60, "/km") if anchor == "threshold_pace" else (value, "/100 m")
    pace = _span(low, high, lambda gap: _mmss(base + gap))
    return f"{pace}{per} ({name} {_gap(low, high)})"


def _what(part: Dict[str, Any], thresholds: Dict[str, Any]) -> str:
    """The words after a step's length: the target, else the zone, and the effort."""
    target = _target(part.get("target"), thresholds)
    zone = f"zone {part['zone']}" if part.get("zone") else ""
    effort = str(part.get("effort") or "").strip()
    if target:
        words = [target, effort or zone]
    elif part.get("target"):
        # A threshold with no value on record prints as zone and effort (§2).
        words = [zone, effort]
    else:
        words = [effort or zone]
    return ", ".join(word for word in words if word)


def _duration(seconds: float) -> str:
    if seconds < 60:
        return f"{seconds:g} s"
    if seconds % 30 == 0:
        return f"{seconds / 60:g} min"
    return f"{_mmss(seconds)} min"


def _clock(seconds: float) -> str:
    """When a phase starts: "0:15", "0:37:30"."""
    hours, rest = divmod(round(seconds), 3600)
    minutes, secs = divmod(rest, 60)
    return f"{hours}:{minutes:02d}:{secs:02d}" if secs else f"{hours}:{minutes:02d}"


def _length(step: Dict[str, Any]) -> str:
    each = f"{step['metres']:g} m" if _positive(step.get("metres")) else _duration(
        step["seconds"]
    )
    return f"{_repeat(step)} × {each}" if _repeat(step) > 1 else each


def block(
    steps: Sequence[Dict[str, Any]], sport: str, duration_minutes: Any,
    thresholds: Dict[str, Any],
) -> str:
    """The step block: one aligned line per phase with the clock time it starts, the lines
    under it, and the TOTAL. A remainder that gets no time prints as nothing (§4)."""
    rows: List[Tuple[str, str, str, str, List[str]]] = []
    at = 0.0
    metres = 0.0
    for step in resolve(steps, duration_minutes):
        recovery = step.get("recovery")
        took = _repeat(step) * (step["seconds"] + (recovery["seconds"] if recovery else 0))
        if not took:
            continue
        under = []
        if recovery:
            under.append(f"{_duration(recovery['seconds'])} {_what(recovery, thresholds)} "
                         "after each".replace("  ", " "))
        if str(step.get("note") or "").strip():
            under.append(str(step["note"]).strip())
        rows.append((_clock(at), step["phase"].upper(), _length(step),
                     _what(step, thresholds), under))
        at += took
        if _positive(step.get("metres")):
            metres += _repeat(step) * step["metres"]
    total = _duration(at)
    if sport == "swimming" and all(_positive(step.get("metres")) for step in steps):
        total = f"{round(metres):,} m, {total}"
    clock_width = max(len(row[0]) for row in rows) + 2 if rows else 0
    phase_width = max([len(row[1]) for row in rows] + [len("TOTAL")]) + 2
    lengths = [len(row[2]) for row in rows] + [len(total)]
    length_width = max(lengths) + 2
    lines = []
    for clock, phase, length, what, under in rows:
        lines.append(f"{clock:<{clock_width}}{phase:<{phase_width}}{length:<{length_width}}"
                     f"{what}".rstrip())
        lines.extend(" " * (clock_width + phase_width + length_width) + line for line in under)
    lines.append(" " * (clock_width + phase_width) + "─" * max(lengths))
    lines.append(" " * clock_width + f"{'TOTAL':<{phase_width}}{total}")
    return "\n".join(lines)


def describe(
    title: str, prose: str, steps: Sequence[Dict[str, Any]], sport: str,
    duration_minutes: Any, thresholds: Dict[str, Any],
) -> str:
    """The "[Title]" line, the step block, the seam, then the week planner's prose (§5)."""
    text = f"{title}\n{block(steps, sport, duration_minutes, thresholds)}"
    return f"{text}\n\n{prose}" if prose else text


def _written(entry: Dict[str, Any]) -> Tuple[str, str]:
    """The title line and the prose of a description the week planner wrote."""
    lines = (entry.get("description") or "").strip().splitlines()
    title = title_line(entry.get("description"))
    if not title:
        return f"[{entry.get('title') or ''}]", "\n".join(lines).strip()
    return title, "\n".join(lines[1:]).strip()


def finish(
    entries: Sequence[Any], zone_currencies: Dict[str, str], thresholds: Dict[str, Any]
) -> None:
    """Prints the steps of each run, ride or swim of an answer into its description and works
    out its zone minutes, in place (§4, §5). Every other session gets no zone minutes.

    Steps that still fail are stored and printed without zone minutes; steps that cannot be
    printed are not stored, and the session keeps its prose alone (§4)."""
    for entry in entries:
        if not isinstance(entry, dict) or entry.get("keep") or entry.get("drop"):
            continue
        entry["planned_zone_currency"] = entry["planned_zone_sec"] = None
        if not writes_steps(entry):
            entry.pop("steps", None)
            continue
        sport = canonical_sport(entry["sport_type"])
        steps = entry.get("steps")
        problem = fault(entry, zone_currencies)
        if problem and _shape(steps, sport == "swimming"):
            journal.record("note", f"Steps not stored: {problem}", lvl="warn")
            entry["steps"] = None
            continue
        if problem:
            journal.record("note", f"Steps stored without zone minutes: {problem}", lvl="warn")
        title, prose = _written(entry)
        entry["description"] = describe(
            title, prose, steps, sport, entry.get("duration_minutes"), thresholds
        )
        currency = zone_currencies.get(sport)
        if problem or currency is None:
            continue
        entry["planned_zone_currency"] = currency
        entry["planned_zone_sec"] = zone_seconds(
            resolve(steps, entry.get("duration_minutes")), currency
        )


def reprint(db, thresholds: Dict[str, Any], summary: str) -> None:
    """Prints every session from today on that has steps again, with the thresholds now in
    use, as `reprint` copies of the live revisions. No model call (§6).

    Holds the week lock from the read to the write, and opens no change when no text moved,
    so an e1RM writes nothing."""
    with db.week_lock():
        changed = []
        for workout in db.get_workouts(start_date=today_str()):
            if not workout.get("steps"):
                continue
            text = describe(
                title_line(workout["description"]), body_of(workout["description"]),
                workout["steps"], canonical_sport(workout["sport_type"]),
                workout["duration_minutes"], thresholds,
            )
            if text != workout["description"]:
                changed.append((workout, text))
        if not changed:
            return
        with db.workout_change(kind="reprint", summary=summary) as change:
            for workout, text in changed:
                live = change.live_revision(
                    workout["date"], canonical_sport(workout["sport_type"])
                )
                change.restore(live, description=text)
