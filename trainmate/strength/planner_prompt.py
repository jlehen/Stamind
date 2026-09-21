"""What the strength planner tells the model, and what it accepts back
(DESIGN_strength_tracking.md §9).

`planner.py` is the other half: which sessions the call is about, the call itself, and what
is done with the answers. This file holds the system prompt, the blocks the user message is
built from, and the checks a returned exercise passes before it becomes a prescribed set —
one that fails is left out with a line for the preview. `Session`, one session the call was
asked about, lives here because the prompt is written from it.
"""
import os
from dataclasses import dataclass, field
from datetime import date
from typing import Any, Dict, List, Optional, Sequence, Set

from trainmate import runtime
from trainmate.coach.formatting import BANNER_RULE, science_section
from trainmate.config import config
from trainmate.strength import prescription, vocabulary

SCIENCE_PATH = os.path.join(os.path.dirname(__file__), "progression.md")


# The line on a session to check whose sets were written under another brief or duration:
# the third ground for changing a kept session (§9).
MOVED_ON = "Its brief or its duration changed since these sets were written: write it again."
# The line for the fourth ground, the athlete asking: `workout generate --strength-only` (§9).
ASKED_AGAIN = "The athlete asked for this session to be written again: write it again."

SYSTEM_PROMPT = """You are TrainMate's strength planner. You write the exercises, sets, reps \
and kilograms of one athlete's strength sessions.

## TASK
For each session under SESSIONS TO WRITE, write the whole session: every exercise in the
order it is done, how many sets, the rep range, and the load in kilograms. Accessory work is
part of the session — write it too. The brief says what the session is for and what the plan
asks of it; the duration says how long it lasts; the equipment says what the athlete can
reach that day. The mesocycle names the phase of the plan the session falls in, its span and
which week of it the session is; week 1 opens a new mesocycle, where the plan's character
changes. The athlete's habits decide the rest (CHOOSING THE EXERCISES).

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
class Session:
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

    @property
    def moved_on(self) -> bool:
        """Whether what the sets were written under changed: the brief, or the duration a
        Thursday cut from 70 to 40 minutes now has (§9)."""
        if self.entry is None or self.live is None:
            return False
        if self.brief != prescription.brief_of(self.live.get("description")):
            return True
        return self.duration != self.live.get("duration_minutes")


# --- what the call is given ---

def _shipped_science() -> str:
    with open(SCIENCE_PATH, encoding="utf-8") as science:
        text = science.read()
    return "\n".join([
        BANNER_RULE, "START OF HOW TO PROGRESS", BANNER_RULE,
        "TrainMate's own progression rules, shipped with the app. The athlete's own "
        "guidelines\nbelow win wherever the two disagree.",
        "", text, BANNER_RULE, "END OF HOW TO PROGRESS", BANNER_RULE,
    ])


def _athlete_science() -> str:
    """The athlete's own guidelines, whole, the way every coaching call gets them. The
    science trim's tags are what will cut this to the strength ones (§10).

    Same banner as the coach's own prompts, built by the same function — the wording of
    the line under it is this call's, because a strength session is what it asks about.
    """
    return science_section(
        runtime.config.science_dir,
        "ATHLETE-PROVIDED SPORTS SCIENCE GUIDELINES",
        "The athlete's own material. It governs what is prescribed and how a session is "
        "built.",
    )


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


def _mesocycle_for(day: str, mesocycles: Dict[str, Any]) -> str:
    """Which mesocycle the day falls in, its span, and which week of it the day is.

    Read from the plan's own table rather than from the brief's prose, so a boundary the
    week planner did not spell out is still exact (§9)."""
    meso = mesocycles.get(day)
    if not meso:
        return ""
    start = date.fromisoformat(meso["start_date"])
    end = date.fromisoformat(meso["end_date"])
    week = (date.fromisoformat(day) - start).days // 7 + 1
    total = (end - start).days // 7 + 1
    return (f"{meso['name']} ({meso['start_date']} to {meso['end_date']}), "
            f"week {week} of {total}")


def system_prompt(done: Set[str]) -> str:
    """The strength planner's system prompt, with the vocabulary's accessories limited to
    the ones in `done` (§9)."""
    return SYSTEM_PROMPT.format(
        science=_shipped_science(), guidelines=_athlete_science(),
        exercises=_exercise_list(done), habit_after=config.strength_habit_after,
    )


def _session_block(
    session: Session, profile: Optional[Dict[str, Any]],
    constraints: Sequence[Dict[str, Any]], mesocycles: Dict[str, Any],
) -> str:
    duration = f"{session.duration} min" if session.duration else "duration not stated"
    lines = [f"- {session.date} ({duration}) \"{session.title}\""]
    if session.rows and session.moved_on:
        lines.append(f"  {MOVED_ON}")
    elif session.asked_again:
        lines.append(f"  {ASKED_AGAIN}")
    mesocycle = _mesocycle_for(session.date, mesocycles)
    if mesocycle:
        lines.append(f"  Mesocycle: {mesocycle}")
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


def user_content(
    to_write: Sequence[Session], to_check: Sequence[Session], history_text: str,
    today: str, profile: Optional[Dict[str, Any]], constraints: Sequence[Dict[str, Any]],
    mesocycles: Dict[str, Any],
) -> str:
    parts = [f"Today's date is {today}."]
    parts.append(history_text or "## STRENGTH HISTORY\nNo sets on record yet.")
    if to_write:
        parts.append(
            "## SESSIONS TO WRITE\n"
            "Write each of these in full.\n"
            + "\n\n".join(_session_block(s, profile, constraints, mesocycles) for s in to_write)
        )
    if to_check:
        parts.append(
            "## SESSIONS TO CHECK\n"
            "The athlete has already been shown these. Keep each unless the sets on record say "
            "a load\nshould move, the athlete has made a habit of doing something else, or it "
            "says to write it\nagain.\n"
            + "\n\n".join(_session_block(s, profile, constraints, mesocycles) for s in to_check)
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
class Answer:
    """One returned session, checked (§9)."""
    rows: List[Dict[str, Any]]
    keep: bool
    reason: str
    notes: str


def clean_session(raw: Dict[str, Any], dropped: List[str]) -> Answer:
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
    return Answer(
        rows=rows, keep=bool(raw.get("keep")),
        reason=str(raw.get("reason") or "").strip(),
        notes=str(raw.get("notes") or "").strip(),
    )


def same_rows(written: Sequence[Dict[str, Any]], stored: Sequence[Dict[str, Any]]) -> bool:
    """Whether an answer prescribes exactly what the session already holds. Read from the
    sets and not from the words, so wording alone never touches the kilograms (§9)."""
    def key(row):
        return (row["exercise"], row["sets"], row["reps_low"], row["reps_high"],
                row.get("load_kg"), bool(row.get("light")))
    return [key(r) for r in written] == [key(r) for r in stored]
