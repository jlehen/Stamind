"""The strength planner (DESIGN_strength_tracking.md §9): the LLM call that writes a
strength session's exercises, sets, reps and kilograms.

The week planner writes a strength day's brief — what the session is for and what the plan
asks of it — and this call writes the session from that brief, the athlete's recent sets,
the shipped and the athlete's own strength science, and the day's equipment. It runs once
per proposal, in the service, after the week planner's reply is parsed and before the
proposal is built, so every path that writes strength sessions gets it.

This file is the pass: which sessions the call is about, the call itself, folding the
answers into the proposal, and writing them. `planner_prompt.py` holds what the model is
told and the checks on what it says back.
"""
from dataclasses import dataclass, field
from datetime import date
from typing import Any, Dict, List, Optional, Sequence, Set, Tuple

from trainmate import runtime
from trainmate.openrouter import openrouter_client
from trainmate.sports import canonical_sport
from trainmate.strength import history, prescription
from trainmate.strength.planner_prompt import (
    Answer, Session, clean_session, same_rows, system_prompt, user_content,
)
from trainmate.text import cyan
from trainmate.output import step

STRENGTH = canonical_sport("strength_training")
LABEL = "strength_planner"

# A call that fails is tried once more; what a second failure costs depends on whether a
# session was to be written (§9).
MAX_ATTEMPTS = 2

NOT_RECHECKED = (
    "I could not recheck {days} kilograms this morning. They stand as written, and I will "
    "look again tomorrow."
)


@dataclass
class StrengthPass:
    """What the strength planner did to a proposal, for the caller to fold in (§9)."""
    # Sessions to add to the proposal: a kept session whose kilograms moved, which the week
    # planner never mentioned.
    added: List[Dict[str, Any]] = field(default_factory=list)
    # One sentence per session it changed, which becomes the proposal's reason when the
    # week planner changed nothing.
    reasons: List[str] = field(default_factory=list)
    # `(date, sport_type)` of every session it weighed, and the stamp the history it read
    # was built from. The rows are written when the proposal is applied (§9).
    checked: List[Tuple[str, str]] = field(default_factory=list)
    stamp: str = ""
    # The dates whose other sessions adapt must hold, because this call named a date the
    # week planner did not (§9).
    held_dates: List[str] = field(default_factory=list)
    # What the preview and the morning briefing say when the kilograms were not rechecked.
    notice: Optional[str] = None
    # Entries the checks dropped, one line each, for the preview.
    dropped: List[str] = field(default_factory=list)


def proposal_fields(pass_: Optional["StrengthPass"]) -> Dict[str, Any]:
    """What a proposal carries about the strength pass, as keyword arguments.

    `workout generate`, `workout adapt` and the strength-only regenerate all end by
    building a proposal, and all three wrote these four fields out by hand with the
    same `if there was a pass` guard. `record_checks` below reads them back.
    """
    return {
        "strength_checks": tuple(pass_.checked) if pass_ else (),
        "strength_stamp": pass_.stamp if pass_ else "",
        "strength_notice": pass_.notice if pass_ else None,
        "strength_dropped": tuple(pass_.dropped) if pass_ else (),
    }


def record_checks(db: Any, proposal: Any) -> None:
    """Remembers which evidence each strength session's kilograms were weighed against (§9).

    Called when a proposal is applied and when it is recorded as no change, never when it is
    proposed: a proposal the athlete declined leaves no row, and the next adapt asks again.
    The value is the stamp the history the call read was built from, not the clock, so sets
    read while a preview waited are not counted as weighed.
    """
    stamp = getattr(proposal, "strength_stamp", "")
    if not stamp:
        return
    for day, sport_type in getattr(proposal, "strength_checks", ()):
        session = db.get_workout(day, sport_type)
        if session and not session.get("removed"):
            db.record_strength_check(session["id"], stamp)


class StrengthPlannerFailed(Exception):
    """The call failed twice with a session to write in the proposal. A strength day with a
    brief and no exercises is worse than yesterday's schedule, so the proposal fails (§9)."""


# --- which sessions this call is about ---

def _brief_now(session: Dict[str, Any]) -> str:
    """A standing strength session's brief: what stands above the seam. A session written
    before phase 2 has old prose naming sets and reps there, so only its title line is
    kept — the exercise lines below replace the rest (§9)."""
    if session.get("prescribed_sets"):
        return prescription.brief_of(session.get("description"))
    return prescription.title_line(session.get("description")) or f"[{session['title']}]"


def _moved_from(
    entry: Dict[str, Any], live_by_slot: Dict[Tuple[str, str], Dict[str, Any]]
) -> Optional[Dict[str, Any]]:
    """The strength session an entry carries to a new slot, or None when it carries none.

    A move writes the session at its destination under the lineage of the one it replaces
    (DESIGN_workout_revisions.md §4, §11), so it is the same session and keeps its
    kilograms.
    """
    named = entry.get("replaces_slot") or entry.get("replaces")
    if not named:
        return None
    if isinstance(named, dict):
        named = (named.get("date"), named.get("sport_type"))
    source = live_by_slot.get((named[0], canonical_sport(named[1] or "")))
    if source is None or canonical_sport(source["sport_type"]) != STRENGTH:
        return None
    return source


def _collect(
    entries: Sequence[Dict[str, Any]], live_sessions: Sequence[Dict[str, Any]],
    span_start: str, span_end: str, held: Sequence[Tuple[str, str]] = (),
) -> Tuple[List[Session], List[Session]]:
    """The sessions to write and the sessions to check (§9).

    A session with prescribed sets is checked, whether the week planner kept it, revised it
    or it arrived with its lineage. Every other strength session is written.

    `held` are the slots the week planner named only to keep. It matters for the strength
    session standing on a date the proposal speaks for without naming it: that session is
    being removed, not kept, so writing kilograms for it would put it back on the calendar.
    A week planner moving Thursday's gym to Friday for the rain returns Thursday as rest and
    Friday as a gym day, and Thursday's session must go.
    """
    live_by_slot = {
        (w["date"], canonical_sport(w["sport_type"])): w for w in live_sessions
        if not w.get("removed")
    }
    live_by_date = {
        day: w for (day, sport), w in live_by_slot.items() if sport == STRENGTH
    }
    to_write: List[Session] = []
    to_check: List[Session] = []
    answered: Set[str] = set()

    for entry in entries:
        if canonical_sport(entry.get("sport_type", "")) != STRENGTH:
            continue
        day = entry.get("date", "")
        if not (span_start <= day <= span_end):
            continue
        answered.add(day)
        kept = bool(entry.get("keep"))
        # The sets follow the lineage (§9). A session that arrives on a date carrying the
        # lineage of the one it replaces is the same session, so its kilograms come from
        # the slot it left, not from whatever stood where it landed. Both `workout
        # generate` and `workout adapt` say so with `replaces`.
        came_from = _moved_from(entry, live_by_slot)
        live = came_from or live_by_date.get(day)
        rows = list(live["prescribed_sets"]) if live else []
        brief = (
            _brief_now(live) if kept and live
            else prescription.collapse_brief(entry.get("description"))
        )
        session = Session(
            date=day, sport_type=entry.get("sport_type", "strength_training"),
            title=entry.get("title") or (live or {}).get("title") or "Strength",
            duration=entry.get("duration_minutes"), brief=brief, entry=entry, live=live,
            rows=rows, to_write=not rows,
        )
        (to_check if rows else to_write).append(session)

    # A standing session no answer named: the week planner kept it by saying nothing.
    mentioned = {
        entry.get("date", "") for entry in entries
        if span_start <= entry.get("date", "") <= span_end
    }
    held_here = {day for day, sport in held if canonical_sport(sport) == STRENGTH}
    for day, live in sorted(live_by_date.items()):
        if day in answered or not (span_start <= day <= span_end):
            continue
        if day in mentioned and day not in held_here:
            continue
        rows = list(live["prescribed_sets"])
        session = Session(
            date=day, sport_type=live["sport_type"], title=live["title"],
            duration=live.get("duration_minutes"), brief=_brief_now(live), entry=None,
            live=live, rows=rows, to_write=not rows,
        )
        (to_check if rows else to_write).append(session)
    return to_write, to_check


def _weighed_before(session: Session, stamp: str, checks: Dict[int, str]) -> bool:
    """Whether this session's kilograms were already weighed against the evidence standing
    now — the rule that keeps a "keep" from being asked again the next morning with a fresh
    draw of randomness (§9)."""
    lineage_id = session.lineage_id
    return lineage_id is not None and checks.get(lineage_id, "") >= stamp


def _day_name(day: str) -> str:
    return f"{date.fromisoformat(day):%A}'s"


def _notice_for(days: Sequence[str]) -> str:
    named = [_day_name(day) for day in sorted(set(days))]
    if len(named) == 1:
        listed = named[0]
    else:
        listed = ", ".join(named[:-1]) + " and " + named[-1]
    return NOT_RECHECKED.format(days=listed)


# --- the pass ---

def run(
    entries: List[Dict[str, Any]], live_sessions: Sequence[Dict[str, Any]],
    span_start: str, span_end: str, today: str,
    profile: Optional[Dict[str, Any]], constraints: Sequence[Dict[str, Any]],
    reason_key: str, held: Sequence[Tuple[str, str]] = (), write_again: bool = False,
) -> Optional[StrengthPass]:
    """Writes and checks the proposal's strength sessions, in place (§9).

    `entries` are the proposal's rows, which this mutates: a session to write gets its
    description and its exercises, and a kept session whose kilograms moved comes back in
    `StrengthPass.added` for the caller to add. Returns None when there is nothing new to
    write from, which is what makes a morning adapt in a week with no lifting cost no call.

    `write_again` (`workout generate --strength-only` and `--fresh`) asks for every session to
    check to be written again, new evidence or not (§9).

    Raises `StrengthPlannerFailed` when the call fails twice with a session to write: a
    strength day with a brief and no exercises must never exist.
    """
    to_write, to_check = _collect(entries, live_sessions, span_start, span_end, held)
    if not to_write and not to_check:
        return None
    for session in to_check:
        session.asked_again = write_again
    stamp = runtime.db.strength_history_stamp()
    checks = runtime.db.strength_checks_for(
        [s.lineage_id for s in to_check if s.lineage_id is not None]
    )
    fresh_evidence = [s for s in to_check if not _weighed_before(s, stamp, checks)]
    written_by_the_week_planner = any(
        s.entry is not None and not s.entry.get("keep") for s in to_write + to_check
    )
    if (not to_write and not fresh_evidence and not written_by_the_week_planner
            and not write_again):
        return None

    built = history.build(today)
    system = system_prompt(built.exercises)
    mesocycles = _mesocycles_for(to_write + to_check)
    user = user_content(
        to_write, to_check, built.text, today, profile, constraints, mesocycles
    )
    step(f"Querying OpenRouter to write {len(to_write)} strength session(s) and check "
         f"{len(to_check)}...", cyan)

    asked = _ask(system, user, to_write, _wait_notice(to_write, to_check))
    if asked is None:
        return _all_kept(to_check)
    answers, dropped = asked
    return _fold_in(answers, dropped, to_write, to_check, stamp, checks, reason_key)


def _mesocycles_for(sessions: Sequence[Session]) -> Dict[str, Any]:
    """The mesocycle covering each date the call was asked about, one lookup per date."""
    return {
        day: runtime.db.get_covering_mesocycle(day)
        for day in sorted({session.date for session in sessions})
    }


def _wait_notice(to_write: Sequence[Session], to_check: Sequence[Session]) -> str:
    """What the chat reads while the call runs: "Writing 2 strength sessions and checking
    1" (DESIGN_output_verbosity.md §8.2)."""
    written = _strength_sessions(len(to_write))
    if to_write and to_check:
        return f"Writing {written} and checking {len(to_check)}"
    if to_write:
        return f"Writing {written}"
    return f"Checking {_strength_sessions(len(to_check))}"


def _strength_sessions(count: int) -> str:
    if count == 1:
        return "1 strength session"
    return f"{count} strength sessions"


def _ask(
    system: str, user: str, to_write: Sequence[Session], notice: str
) -> Optional[Tuple[Dict[str, Answer], List[str]]]:
    """The call, tried once more when it fails or comes back unusable — a session to write
    left unanswered, or one whose every exercise failed a check, is a failed call (§9).

    None when it failed twice with only sessions to check, which is a "keep" for all of
    them; it raises instead when a session was to be written.
    """
    last: Optional[Exception] = None
    for _attempt in range(MAX_ATTEMPTS):
        dropped: List[str] = []
        try:
            reply = _complete(system, user, notice)
        except Exception as e:
            last = e
            continue
        answers = {
            str(raw.get("date")): clean_session(raw, dropped)
            for raw in reply.get("sessions") or []
            if isinstance(raw, dict)
        }
        blank = Answer([], False, "", "")
        missing = [s.date for s in to_write if not answers.get(s.date, blank).rows]
        if not missing:
            return answers, dropped
        last = ValueError(f"no usable exercises came back for {', '.join(missing)}")
    if to_write:
        raise StrengthPlannerFailed(str(last))
    return None


def _complete(system: str, user: str, notice: str) -> Dict[str, Any]:
    return openrouter_client.complete(system, user, label=LABEL, wait_notice=notice)


def _all_kept(to_check: Sequence[Session]) -> StrengthPass:
    """A failed call with only sessions to check is a "keep" for all of them: their sets
    stand, the week planner's changes are applied, and the athlete is told (§9). No check
    row is written, so the next adapt asks again."""
    result = StrengthPass(notice=_notice_for([s.date for s in to_check]))
    for session in to_check:
        _keep(session)
    return result


def _keep(session: Session) -> None:
    """A session whose kilograms stand. When the week planner revised it, its rows are
    copied under the new brief, so the description and the rows never disagree (§9)."""
    if session.entry is None:
        return
    session.entry["description"] = prescription.rebrief(
        session.live.get("description"), session.brief
    )
    session.entry["prescribed_sets"] = list(session.rows)


def _fold_in(
    answers: Dict[str, Answer], dropped: List[str], to_write: Sequence[Session],
    to_check: Sequence[Session], stamp: str, checks: Dict[int, str], reason_key: str,
) -> StrengthPass:
    result = StrengthPass(stamp=stamp, dropped=dropped)
    for session in to_write:
        _write(session, answers[session.date].rows, answers[session.date].notes, result,
               reason_key)
    for session in to_check:
        answer = answers.get(session.date)
        # New evidence, a new brief, a new duration or the athlete asking: without one of
        # those a kept session could come back at 142.5 where it stood at 145, for no reason
        # anyone can defend.
        weighed_already = (
            _weighed_before(session, stamp, checks) and not session.moved_on
            and not session.asked_again
        )
        if (answer is None or answer.keep or not answer.rows
                or weighed_already or same_rows(answer.rows, session.rows)):
            _keep(session)
            result.checked.append((session.date, session.sport_type))
            continue
        _write(session, answer.rows, answer.notes, result, reason_key,
               reason=answer.reason)
    return result


def _write(
    session: Session, rows: List[Dict[str, Any]], notes: str, result: StrengthPass,
    reason_key: str, reason: str = "",
) -> None:
    """Puts one written session into the proposal. A session the week planner never
    mentioned needs a row of its own, and its date's other sessions have to be held or
    adapt would remove Thursday's intervals over a kilogram (§9)."""
    description = prescription.render_description(session.brief, rows, notes)
    result.checked.append((session.date, session.sport_type))
    if reason:
        result.reasons.append(reason)
    if session.entry is not None:
        session.entry["description"] = description
        session.entry["prescribed_sets"] = rows
        session.entry.pop("keep", None)
        session.entry.pop("unmentioned", None)
        if reason:
            session.entry[reason_key] = reason
        return
    live = session.live or {}
    result.added.append({
        "date": session.date,
        "sport_type": session.sport_type,
        "title": session.title,
        "description": description,
        "duration_minutes": live.get("duration_minutes"),
        "rpe": live.get("rpe"),
        "tss": live.get("tss"),
        "benchmark_type": live.get("benchmark_type"),
        "macrocycle_id": live.get("macrocycle_id"),
        "prescribed_sets": rows,
        reason_key: reason or None,
    })
    result.held_dates.append(session.date)
