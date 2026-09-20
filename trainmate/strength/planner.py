"""The strength planner (DESIGN_strength_tracking.md §9): the LLM call that writes a
strength session's exercises, sets, reps and kilograms.

The week planner writes a strength day's brief — what the session is for and what the plan
asks of it — and this call writes the session from that brief, the athlete's recent sets,
the shipped and the athlete's own strength science, and the day's equipment. It runs once
per proposal, in the service, after the week planner's reply is parsed and before the
proposal is built, so every path that writes strength sessions gets it.
"""
import os
from dataclasses import dataclass, field
from datetime import date
from typing import Any, Dict, List, Optional, Sequence, Set, Tuple

from trainmate import runtime
from trainmate.config import config, science_documents
from trainmate.sports import canonical_sport
from trainmate.strength import history, prescription, vocabulary
from trainmate.util import cyan, step

STRENGTH = canonical_sport("strength_training")
LABEL = "strength_planner"

# A call that fails is tried once more; what a second failure costs depends on whether a
# session was to be written (§9).
MAX_ATTEMPTS = 2

SCIENCE_PATH = os.path.join(os.path.dirname(__file__), "progression.md")

_RULE = "=" * 80

# The line on a session to check whose sets were written under another brief or duration:
# the third ground for changing a kept session (§9).
MOVED_ON = "Its brief or its duration changed since these sets were written: write it again."
# The line for the fourth ground, the athlete asking: `workout generate --strength-only` (§9).
ASKED_AGAIN = "The athlete asked for this session to be written again: write it again."

NOT_RECHECKED = (
    "I could not recheck {days} kilograms this morning. They stand as written, and I will "
    "look again tomorrow."
)

SYSTEM_PROMPT = """You are TrainMate's strength planner. You write the exercises, sets, reps \
and kilograms of one athlete's strength sessions.

## TASK
For each session under SESSIONS TO WRITE, write the whole session: every exercise in the
order it is done, how many sets, the rep range, and the load in kilograms. Accessory work is
part of the session — write it too. The brief says what the session is for and what the plan
asks of it; the duration says how long it lasts; the equipment says what the athlete can
reach that day. The athlete's habits decide the rest (CHOOSING THE EXERCISES).

For each session under SESSIONS TO CHECK, the athlete has already been shown it. Answer
"keep" unless one of these three is true:
- The sets on record since it was written say a load should move.
- The athlete has made a habit of doing something other than what it holds (CHOOSING THE
  EXERCISES).
- It says to write it again, because its brief or its duration changed or because the athlete
  asked for it. Then write it again, the way you write a session under SESSIONS TO WRITE.
When you do change it, return the whole session again and say in one sentence why,
written for the athlete to read: "Monday's sets all reached 6 at 140; add 5."

### WRITING THE LOADS
Follow HOW TO PROGRESS below, and the athlete's own guidelines where the two disagree.
Every load must be one you could defend from the history, the equipment or the starting-point
rule. Never leave a load out because you are unsure: an athlete who follows the session to
the letter must not meet a blank where a number belongs.

### CHOOSING THE EXERCISES
Write each session from the most comparable session under SESSIONS AS DONE: one done with
the same equipment, of about the same length and the same character. A day of belt squats
and pulldowns is a gym day, and a day of goblet squats and swings is a day at home. Take its
exercises, their order, which ones were alternated and how many sets each got. Then change
only what the brief, the duration, the day's equipment or HOW TO PROGRESS asks for. Write
alternated exercises one after the other, and name them in the notes.

Size the session to what the athlete fits in the time: the head line of each session as done
gives its length and how many sets it held. Do not size it by adding up rests. Alternating
two exercises does not shorten the rests the athlete's guidelines ask for: an athlete who
does a set of belt squats, then a set of push presses, then belt squats again has rested the
belt squat about three minutes.

A difference between what was prescribed and what the athlete did becomes a habit once it
has happened {habit_after} times in comparable sessions under SESSIONS AS DONE. The
difference can be an exercise done in place of another, one skipped, one added, or another
number of sets. NOT DONE lists what was prescribed and not done, and "(not prescribed)"
marks what was done and not prescribed. A NOT DONE line older than the oldest session as
done does not count. Before a difference is a habit, it is a one-off: keep writing what was
prescribed. Once it is a habit, write it into the session, even where the brief asked for
what the athlete refused. An activity that was not an attempt at a prescription holds
nothing to differ from, and everything in it counts at once: a day with nothing prescribed,
or the activity without the marks on a day the watch split in two. Where a habit and the
athlete's own guidelines disagree, the guidelines win.

The brief may ask for something the comparable session does not hold, such as single-leg
work when the plan prepares a ski season. Then write the new exercise in the place of the one
that did the same job, and keep everything else as the athlete does it. With no sets on
record, the brief, the equipment and the guidelines decide on their own.

A brief names an exercise only when it was requested, as in "step-ups take the place of belt
squats, as requested". Do what it says in that session, and keep everything else as it was: that
brief changes one exercise, not the session. For that session it outranks the athlete's
habits. Only the day's equipment can rule it out, and then the notes say so.

Use only names from EXERCISES TRAINMATE KNOWS, spelled exactly as they appear there. Each
name carries its movement pattern and the equipment it usually needs. Pick exercises the
day's equipment allows: a travel week with dumbbells only gets goblet squats and dumbbell
Romanian deadlifts where the home gym had the belt squat and the barbell. A substitution is
a different exercise doing the same pattern's job, and it keeps its own history.

Write an exercise more than once when it needs a warm-up ramp: the same name at a lighter
load first, then the working sets.

### THE NOTES
Each session's notes are one short paragraph for the athlete: the rests, the warm-up, which
exercises to alternate ("alternate the belt squat and the push press, then the hamstring curl
and the pulldown"), a cue where one is due, and the starting point for anything with no
history. An exercise the athlete has not been doing gets one sentence saying what is new,
why, and what it replaces: "Step-ups are new. The plan wants single-leg work for skiing.
They take the place of the leg press." Do not restate the exercises — they are printed above
your notes from the data you return.

{science}

{guidelines}

## EXERCISES TRAINMATE KNOWS
{exercises}

## RESPONSE FORMAT
You MUST respond with a JSON object containing:
{{
  "sessions": [
    {{
      "date": "YYYY-MM-DD",
      "keep": false, (ONLY on a session under SESSIONS TO CHECK you are leaving exactly as
        it is. Then "date" and "keep" are the only fields to give.)
      "light": false, (true when you wrote this session as a light week's — see HOW TO
        PROGRESS. Every exercise of a light session is marked, not some of them.)
      "reason": "One sentence for the athlete, REQUIRED on a session under SESSIONS TO
        CHECK you are changing, omitted everywhere else.",
      "notes": "The rests, the warm-up and any cue, in one short paragraph.",
      "exercises": [
        {{
          "exercise": "belt squat", (exactly as EXERCISES TRAINMATE KNOWS spells it)
          "sets": 3,
          "reps_low": 4,
          "reps_high": 6, (equal to "reps_low" for a fixed rep count)
          "load_kg": 140 (the weight moved in one rep; null for a bodyweight exercise with
            nothing added)
        }}
      ]
    }}
  ]
}}
Return one entry per session you were asked about.
"""


@dataclass
class _Session:
    """One strength session this call was asked about (§9)."""
    date: str
    sport_type: str
    title: str
    duration: Optional[int]
    brief: str
    entry: Optional[Dict[str, Any]]      # the proposal's row, when the week planner wrote one
    live: Optional[Dict[str, Any]]       # the session standing on that date, when one does
    rows: List[Dict[str, Any]] = field(default_factory=list)
    to_write: bool = True
    asked_again: bool = False            # the athlete asked for it to be written again

    @property
    def lineage_id(self) -> Optional[int]:
        return self.live["id"] if self.live else None


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


# --- what the call is given ---

def _shipped_science() -> str:
    with open(SCIENCE_PATH, encoding="utf-8") as science:
        text = science.read()
    return "\n".join([
        _RULE, "START OF HOW TO PROGRESS", _RULE,
        "TrainMate's own progression rules, shipped with the app. The athlete's own "
        "guidelines\nbelow win wherever the two disagree.",
        "", text, _RULE, "END OF HOW TO PROGRESS", _RULE,
    ])


def _athlete_science() -> str:
    """The athlete's own guidelines, whole, the way every coaching call gets them. The
    science trim's tags are what will cut this to the strength ones (§10)."""
    docs = [
        f"--- {filename} ---\n{text}"
        for filename, text in science_documents(runtime.config.science_dir).items()
    ]
    if not docs:
        return ""
    return "\n".join([
        _RULE, "START OF ATHLETE-PROVIDED SPORTS SCIENCE GUIDELINES", _RULE,
        "The athlete's own material. It governs what is prescribed and how a session is "
        "built.",
        "", "\n\n".join(docs), _RULE,
        "END OF ATHLETE-PROVIDED SPORTS SCIENCE GUIDELINES", _RULE,
    ])


def _exercise_list(done: Set[str]) -> str:
    """Every exercise outside the accessory pattern, plus the accessories the athlete
    actually does. The full accessory list would double the region with names nobody on the
    instance lifts (§9)."""
    lines = []
    for name in vocabulary.names():
        known = vocabulary.get(name)
        if known.pattern == vocabulary.ACCESSORY and name not in done:
            continue
        lines.append(f"{name} ({known.pattern}, {known.equipment})")
    return "\n".join(lines)


def _equipment_for(day: str, profile: Optional[Dict[str, Any]]) -> str:
    """What the athlete can reach on that weekday: the profile's two lists, which is all
    there is — equipment is not a constraint type (§9)."""
    profile = profile or {}
    general = profile.get("equipment") or []
    if isinstance(general, str):
        general = [general]
    schedule = profile.get("weekly_schedule") or {}
    weekday = f"{date.fromisoformat(day):%A}"
    entry = next(
        (value for key, value in schedule.items() if key.lower() == weekday.lower()), None
    )
    on_the_day = (entry or {}).get("equipment", []) if isinstance(entry, dict) else []
    both = list(on_the_day) + [item for item in general if item not in on_the_day]
    return ", ".join(str(item) for item in both) if both else "not stated"


def _constraints_for(day: str, constraints: Sequence[Dict[str, Any]]) -> str:
    """The prose of the constraints active that day — where "hotel gym, dumbbells only"
    would be written (§9)."""
    active = [c for c in constraints if c["start_date"] <= day <= c["end_date"]]
    return "; ".join(
        f"{c['title']}" + (f" — {c['description']}" if c.get("description") else "")
        for c in active
    )


def _system_prompt(done: Set[str]) -> str:
    """The strength planner's system prompt, with the vocabulary's accessories limited to
    the ones in `done` (§9)."""
    return SYSTEM_PROMPT.format(
        science=_shipped_science(), guidelines=_athlete_science(),
        exercises=_exercise_list(done), habit_after=config.strength_habit_after,
    )


def _session_block(
    session: _Session, profile: Optional[Dict[str, Any]],
    constraints: Sequence[Dict[str, Any]],
) -> str:
    duration = f"{session.duration} min" if session.duration else "duration not stated"
    lines = [f"- {session.date} ({duration}) \"{session.title}\""]
    if session.rows and _moved_on(session):
        lines.append(f"  {MOVED_ON}")
    elif session.asked_again:
        lines.append(f"  {ASKED_AGAIN}")
    lines.append(f"  Equipment that day: {_equipment_for(session.date, profile)}")
    active = _constraints_for(session.date, constraints)
    if active:
        lines.append(f"  Constraints that day: {active}")
    if session.rows:
        lines.append("  Written now as:")
        for line in prescription.exercise_lines(session.rows):
            lines.append(f"      {line}")
    lines.append("  Brief:")
    lines.extend(f"      {line}" for line in session.brief.splitlines())
    return "\n".join(lines)


def _user_content(
    to_write: Sequence[_Session], to_check: Sequence[_Session], history_text: str,
    today: str, profile: Optional[Dict[str, Any]], constraints: Sequence[Dict[str, Any]],
) -> str:
    parts = [f"Today's date is {today}."]
    parts.append(history_text or "## STRENGTH HISTORY\nNo sets on record yet.")
    if to_write:
        parts.append(
            "## SESSIONS TO WRITE\n"
            "Write each of these in full.\n"
            + "\n\n".join(_session_block(s, profile, constraints) for s in to_write)
        )
    if to_check:
        parts.append(
            "## SESSIONS TO CHECK\n"
            "The athlete has already been shown these. Keep each unless the sets on record say "
            "a load\nshould move, the athlete has made a habit of doing something else, or it "
            "says to write it\nagain.\n"
            + "\n\n".join(_session_block(s, profile, constraints) for s in to_check)
        )
    return "\n\n".join(parts)


# --- checking what comes back ---

def _clean_exercise(raw: Any) -> Optional[Dict[str, Any]]:
    """One returned exercise as a row, or None when it fails a check (§9)."""
    if not isinstance(raw, dict):
        return None
    name = str(raw.get("exercise") or "").strip().lower()
    if not vocabulary.get(name):
        return None
    try:
        count = int(raw.get("sets"))
        low = int(raw.get("reps_low"))
        high = int(raw.get("reps_high", raw.get("reps_low")))
    except (TypeError, ValueError):
        return None
    if count < 1 or low < 1 or high < low:
        return None
    load = raw.get("load_kg")
    if load is not None:
        try:
            load = float(load)
        except (TypeError, ValueError):
            return None
        if load < 0:
            return None
    return {"exercise": name, "sets": count, "reps_low": low, "reps_high": high,
            "load_kg": load}


@dataclass
class _Answer:
    """One returned session, checked (§9)."""
    rows: List[Dict[str, Any]]
    keep: bool
    reason: str
    notes: str


def _clean_session(raw: Dict[str, Any], dropped: List[str]) -> _Answer:
    """One returned session as an answer, the exercises that fail a check left out with a
    line for the preview (§9)."""
    rows = []
    for entry in raw.get("exercises") or []:
        cleaned = _clean_exercise(entry)
        if cleaned is None:
            name = (entry or {}).get("exercise") if isinstance(entry, dict) else entry
            dropped.append(
                f"{raw.get('date')}: '{name}' is not an exercise TrainMate knows, left out"
            )
            continue
        rows.append(cleaned)
    if raw.get("light"):
        for row in rows:
            row["light"] = True
    return _Answer(
        rows=rows, keep=bool(raw.get("keep")),
        reason=str(raw.get("reason") or "").strip(),
        notes=str(raw.get("notes") or "").strip(),
    )


def _same_rows(written: Sequence[Dict[str, Any]], stored: Sequence[Dict[str, Any]]) -> bool:
    """Whether an answer prescribes exactly what the session already holds. Read from the
    sets and not from the words, so wording alone never touches the kilograms (§9)."""
    def key(row):
        return (row["exercise"], row["sets"], row["reps_low"], row["reps_high"],
                row.get("load_kg"), bool(row.get("light")))
    return [key(r) for r in written] == [key(r) for r in stored]


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
) -> Tuple[List[_Session], List[_Session]]:
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
    to_write: List[_Session] = []
    to_check: List[_Session] = []
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
        session = _Session(
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
        session = _Session(
            date=day, sport_type=live["sport_type"], title=live["title"],
            duration=live.get("duration_minutes"), brief=_brief_now(live), entry=None,
            live=live, rows=rows, to_write=not rows,
        )
        (to_check if rows else to_write).append(session)
    return to_write, to_check


def _moved_on(session: _Session) -> bool:
    """Whether what the sets were written under changed: the brief, or the duration a
    Thursday cut from 70 to 40 minutes now has (§9)."""
    if session.entry is None or session.live is None:
        return False
    if session.brief != prescription.brief_of(session.live.get("description")):
        return True
    return session.duration != session.live.get("duration_minutes")


def _weighed_before(session: _Session, stamp: str, checks: Dict[int, str]) -> bool:
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
    system = _system_prompt(built.exercises)
    user = _user_content(to_write, to_check, built.text, today, profile, constraints)
    step(f"Querying OpenRouter to write {len(to_write)} strength session(s) and check "
         f"{len(to_check)}...", cyan)

    asked = _ask(system, user, to_write, _wait_notice(to_write, to_check))
    if asked is None:
        return _all_kept(to_check)
    answers, dropped = asked
    return _fold_in(answers, dropped, to_write, to_check, stamp, checks, reason_key)


def _wait_notice(to_write: Sequence[_Session], to_check: Sequence[_Session]) -> str:
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
    system: str, user: str, to_write: Sequence[_Session], notice: str
) -> Optional[Tuple[Dict[str, _Answer], List[str]]]:
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
            str(raw.get("date")): _clean_session(raw, dropped)
            for raw in reply.get("sessions") or []
            if isinstance(raw, dict)
        }
        blank = _Answer([], False, "", "")
        missing = [s.date for s in to_write if not answers.get(s.date, blank).rows]
        if not missing:
            return answers, dropped
        last = ValueError(f"no usable exercises came back for {', '.join(missing)}")
    if to_write:
        raise StrengthPlannerFailed(str(last))
    return None


def _complete(system: str, user: str, notice: str) -> Dict[str, Any]:
    from trainmate.openrouter import openrouter_client
    return openrouter_client.complete(system, user, label=LABEL, wait_notice=notice)


def _all_kept(to_check: Sequence[_Session]) -> StrengthPass:
    """A failed call with only sessions to check is a "keep" for all of them: their sets
    stand, the week planner's changes are applied, and the athlete is told (§9). No check
    row is written, so the next adapt asks again."""
    result = StrengthPass(notice=_notice_for([s.date for s in to_check]))
    for session in to_check:
        _keep(session)
    return result


def _keep(session: _Session) -> None:
    """A session whose kilograms stand. When the week planner revised it, its rows are
    copied under the new brief, so the description and the rows never disagree (§9)."""
    if session.entry is None:
        return
    session.entry["description"] = prescription.rebrief(
        session.live.get("description"), session.brief
    )
    session.entry["prescribed_sets"] = list(session.rows)


def _fold_in(
    answers: Dict[str, _Answer], dropped: List[str], to_write: Sequence[_Session],
    to_check: Sequence[_Session], stamp: str, checks: Dict[int, str], reason_key: str,
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
            _weighed_before(session, stamp, checks) and not _moved_on(session)
            and not session.asked_again
        )
        if (answer is None or answer.keep or not answer.rows
                or weighed_already or _same_rows(answer.rows, session.rows)):
            _keep(session)
            result.checked.append((session.date, session.sport_type))
            continue
        _write(session, answer.rows, answer.notes, result, reason_key,
               reason=answer.reason)
    return result


def _write(
    session: _Session, rows: List[Dict[str, Any]], notes: str, result: StrengthPass,
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
