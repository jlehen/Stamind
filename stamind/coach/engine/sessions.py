"""How the week planner writes one session entry.

The prompt sections about a single session rather than about the span: the sport enum
both schemas list, a run, a ride or a swim written as steps, the `replaces` field, the
strength brief, what the athlete said about a session, the sessions just outside the days
being written, what may not be rewritten, how a move is written, and what a benchmark entry
must keep; and `ask_week_planner`, the call both send, which checks the steps (§4 of
DESIGN_endurance_steps.md). The first seven sections are sent by `workout generate` and
`workout adapt` both,
and a second copy of one would slowly stop meaning the same thing in the two prompts
(DESIGN_adapt_task_prompt.md §1). The last three only adapt sends today; they live here
because they are about the entry, not about adapting.
"""
import json
from typing import Any, Callable, Dict, List, Optional, Sequence

from stamind.coach import steps
from stamind.coach.formatting import format_neighbour_workouts
from stamind.coach.steps import SPORTS as ENDURANCE_SPORTS
from stamind.sports import CANONICAL_SPORTS
from stamind.types import Workout
import stamind.coach.engine as _eng


def _sport_type_enum() -> str:
    """The `"sport_type": ...` JSON-schema line(s) shared by the generate and adapt
    prompts, wrapped like the surrounding hand-written schema. Built from
    `CANONICAL_SPORTS` so adding a sport reaches both prompts."""
    head, cont, width = '      "sport_type": ', "        ", 90
    options = [f'"{s}"' for s in CANONICAL_SPORTS] + ['"rest"']
    lines: List[str] = []
    current = head
    for i, option in enumerate(options):
        token = option + ("," if i == len(options) - 1 else " |")
        separator = "" if current in (head, cont) else " "
        if len(current) + len(separator) + len(token) > width:
            lines.append(current)
            current = cont + token
            continue
        current += separator + token
    lines.append(current)
    return "".join(f"{line}\n" for line in lines)


SPORT_TYPE_ENUM = _sport_type_enum()


def endurance_task(zone_currencies: Optional[Dict[str, str]]) -> str:
    """The WRITING AN ENDURANCE SESSION section: a run, a ride or a swim as steps
    (DESIGN_endurance_steps.md §3). The zone type per sport is Stamind's call, from the
    athlete's recordings (`_planning_zone_currencies`)."""
    names = {"power": "power (7 zones)", "hr": "heart rate (5 zones)"}
    zone_lines = "\n".join(
        f"  {sport}: {names.get(currency, currency)}"
        for sport, currency in sorted((zone_currencies or {}).items())
        if sport in ENDURANCE_SPORTS
    ) or "  (none yet)"
    return f"""
### WRITING AN ENDURANCE SESSION
Every running, cycling and swimming session carries a "steps" list: its phases in order, each
with an exact length. Stamind prints the steps at the top of the description, with the clock
time each phase starts and the watts, beats or pace worked out from the athlete's thresholds,
and works out the minutes in each zone from them.
- The "description" holds the "[Title]" line and your prose only: why the session is there,
  the morning check, the advice, the fuel. Never write a step into it.
- The steps hold the main path only. An alternative, such as indoors instead of outdoors or
  an easier session after a poor night, stays in the prose.
- The steps fill "duration_minutes" exactly. At most one step may give "remainder" as its
  seconds: Stamind gives it whatever the other steps leave of the duration. A swim has no
  remainder: its steps add up to the duration, to within a minute.
- Neither the prose nor "summary" gives watts, beats per minute or a pace. Name a target by
  its zone or as a share of the threshold ("66-74% FTP", "zone 2"). The steps carry the
  numbers, so a new threshold reaches every session ahead.

Each step has:
- "phase": "warm-up" | "work" | "steady" | "cool-down".
- "seconds": one exact number, or "remainder". A range such as "10-15 min" cannot be written.
  The remainder is a plain step, with no "repeat" and no "recovery".
- "repeat" and "recovery": an interval set, the work then the recovery, "repeat" times. The
  recovery follows every repetition, the last one included. A recovery has "seconds", "zone"
  and "effort". There is no deeper nesting.
- "zone": the zone in the sport's zone type below, on every step and every recovery. A sport
  not listed below has no zone type, and its steps carry no "zone". A swim never has one.
{zone_lines}
- "target" (optional): {{"anchor": ..., "low": ..., "high": ...}}, a range against one of the
  athlete's thresholds in the profile. For "ftp" and "lthr" the range is a percentage of the
  threshold. For "threshold_pace" (per km) and "css" (per 100 m) it is seconds slower than
  the threshold, and a negative number is faster. Write the percentage or the seconds, never
  a watt, a beat or a pace: Stamind works those out. An easy step can carry an effort alone.
- "effort": a few words or an RPE, printed as written ("easy", "8/10").
- "note" (optional): one short line printed under the step.
- "metres": on a swim step only, with "seconds" your estimate of how long the metres take.

A 75-minute ride:
"steps": [
  {{"phase": "warm-up", "seconds": 900, "zone": 1, "effort": "easy, building to a sweat",
   "note": "two 1-min lifts to about 93% FTP"}},
  {{"phase": "work", "repeat": 3, "seconds": 300, "zone": 5,
   "target": {{"anchor": "ftp", "low": 106, "high": 112}}, "effort": "8/10",
   "recovery": {{"seconds": 150, "zone": 1, "effort": "easy"}}}},
  {{"phase": "steady", "seconds": "remainder", "zone": 2,
   "target": {{"anchor": "ftp", "low": 66, "high": 74}}}},
  {{"phase": "cool-down", "seconds": 600, "zone": 1, "effort": "easy"}}
]
"""


STEPS_FIELD = (
    '      "steps": [...] (Running, cycling and swimming only: see WRITING AN ENDURANCE\n'
    "        SESSION. Leave it out on every other sport and on a rest day),\n"
)


def ask_week_planner(
    system: str, user: str, *, label: str, wait_notice: str,
    entries: Callable[[Dict[str, Any]], Sequence[Any]],
    zone_currencies: Optional[Dict[str, str]], profile: Dict[str, Any],
) -> Dict[str, Any]:
    """Asks the week planner, and once more when a run, a ride or a swim of its answer fails
    the check; then prints the steps into each description (DESIGN_endurance_steps.md §4).

    `entries` picks the session entries out of an answer. The second answer replaces the
    first as a whole."""
    currencies = zone_currencies or {}
    reply = _eng.openrouter_client.complete(system, user, label=label, wait_notice=wait_notice)
    faults = [
        problem for problem in (
            steps.fault(entry, currencies) for entry in entries(reply)
            if steps.writes_steps(entry)
        ) if problem
    ]
    if faults:
        again = (
            f"{user}\n\n## YOUR LAST ANSWER\n"
            f"{json.dumps(reply, ensure_ascii=False, indent=2)}\n\n"
            "## WHAT TO FIX\n" + "\n".join(faults)
        )
        reply = _eng.openrouter_client.complete(
            system, again, label=label, wait_notice=wait_notice
        )
    steps.finish(entries(reply), currencies, profile)
    return reply


def replaces_field(listing: str) -> str:
    """The `replaces` member of a revision response schema: how a session says which slot
    it came from (DESIGN_plan_change_continuity.md §4.5).

    `listing` names the user-content section holding the sessions it may point at —
    `workout generate` answers for SESSIONS ALREADY STANDING, `workout adapt` for the
    PLANNED WORKOUTS it was shown. One builder for both, because a second copy of a field
    slowly stops meaning the same thing in the two prompts (DESIGN_adapt_task_prompt.md §1).
    """
    return (
        '      "replaces": {"date": "YYYY-MM-DD", "sport_type": "..."} (OMIT unless this\n'
        f"        session takes the place of one listed in {listing} that\n"
        "        stood in a DIFFERENT slot — moved to another day, or changed sport. Names\n"
        "        the slot it came from, so that day's session follows this one instead of\n"
        "        vanishing and reappearing),\n"
    )


def strength_brief_task(has_message: bool = False) -> str:
    """The one instruction that makes a strength day's description a brief
    (DESIGN_strength_tracking.md §9).

    Always on, in both the generate and the adapt TASK: a strength day can fall anywhere in
    a span, and Stamind's strength planner writes every one of them from the sets the
    athlete actually lifted — which this call is never shown.

    `has_message` adds how a request made inside a strength session reaches that call: the
    week planner writes it into the brief (DESIGN_workout_tweak.md §4).
    """
    return _STRENGTH_BRIEF_TASK + (_STRENGTH_REQUEST_TASK if has_message else "")


_STRENGTH_BRIEF_TASK = """
### WRITING A STRENGTH DAY
A strength session's "description" is a BRIEF, not a session: what the session is for in the
plan, its character, and what the plan asks of it that day. Write NO exercise, no set count,
no rep count and no load into it. Stamind's strength planner writes those, from the sets
the athlete has actually lifted; you are not shown them, so a rep count written here would
fix a number only that call can read. When the week is a light one, say so in the brief — the
plan's mesocycle is where that is decided, and the brief is how it travels.
The date, the duration, the RPE and the load stay yours: they are the week's budget and the
fit against the endurance days.
Set the duration from how long the athlete's own sessions of that kind took, under ACTUAL
COMPLETED GARMIN ACTIVITIES IN WINDOW: an evening circuit that took 19 and 22 minutes is
written at 20, even where the plan or an earlier session says 15. Go under or over that
length only to ask for less or more work than those sessions held, as in a light week. With
no such activity on record, the plan's minutes stand.
A brief reads like this: "[Full-Body Strength (Heavy, Non-Failure)]\\nHeavy full-body
strength, second week of the build, non-failure. 70 min at the gym. Keep the legs fresh for
Saturday's long ride."
A brief names an exercise in one case only: it was requested, and the brief says "as
requested". When you rewrite such a brief, keep what it says was requested.
A timed conditioning circuit the athlete follows on their own, such as a kettlebell video, is
sport "hiit", not a strength session: give it a normal description with its length and what it
is for, never a brief. An interval ride or run keeps its own sport; "hiit" is not for those.
Nor is a circuit of exercises with sets and reps: that is a strength session, whatever the
athlete calls it.
"""

_STRENGTH_REQUEST_TASK = """
When the message you were given asks for something INSIDE a strength session (an exercise
swapped, added or left out, a lighter session), rewrite that session's brief so that it says
what was requested, in your own words, and return the session. Mark it "as requested", never
"as you asked": the request may come from the athlete's coach rather than the athlete. Take
only the part of the message that is about that session. Still write no set, rep or load.
For example: "[Lower-Body Strength (Heavy)]\\nLower-body strength, heavy and low in volume.
Step-ups take the place of belt squats, as requested: the machine is broken." The strength
planner reads the brief and writes the exercises from it.
A message that is not about the inside of a strength session leaves every brief as it was.
"""


# What no revision may rewrite: shared by `workout adapt` and `workout tweak`.
LOCKED_HISTORY_TASK = """
### WHAT YOU MAY NOT TOUCH
Sessions tagged "[COMPLETED — locked history, not adaptable]" have already been performed,
including any the athlete trained earlier on the evaluation date. Do NOT adapt them, and
never restate a finished session to match what was actually done — adapt only sessions
still ahead.
A session tagged "[PARTIAL — ...]" did NOT go as planned: the tag reports the duration and
load actually performed, and those are the truth — do not read the planned numbers beside
it as work the athlete banked. Where the tag also says "locked history", the day is behind
us, so the difference is a fact to plan AROUND, not a session to rewrite. Where it says the
session is not yet history, the athlete started it and stopped, and today is still yours to
shape: salvage what remains of it, move the exposure to another day, or — if the athlete
tells you the day is gone — write that day off to rest so the calendar records what
actually happened. Do not leave a session standing that the athlete has told you they
abandoned.
"""


def athlete_words_task(sessions: Sequence[Workout]) -> str:
    """The WHAT THE ATHLETE SAID ABOUT A SESSION section, sent by `workout adapt` and the
    week planner when a session they list carries the athlete's words
    (DESIGN_session_notes.md §4)."""
    if not any(w.get("athlete_notes") for w in sessions):
        return ""
    return _ATHLETE_WORDS_TASK


_ATHLETE_WORDS_TASK = """
### WHAT THE ATHLETE SAID ABOUT A SESSION
A session the user content lists may carry lines starting "The athlete said", each with the
time it was sent: the athlete's own words about that session, typed into the chat. They hold
what Garmin cannot record: how hard it felt, whether they stopped by choice, the setup (ERG
mode, a Zwift climb, the real road), a time or a wattage read off the head unit. Read them
beside the session's prescription and that day's Garmin activity, and pitch the next
comparable session from all three. The words are how the session felt and the numbers are
what it measured; when they disagree, weigh both. A request in those words was about that
day and has already been answered: it asks nothing of today.
"""


def neighbour_sessions_task(neighbour_workouts: Optional[Sequence[Workout]]) -> str:
    """The THE DAYS JUST OUTSIDE THE SPAN section, sent by `workout generate` for the week
    either side of its span and by `workout adapt` for the week after its range
    (DESIGN_mesocycle_boundary.md §7)."""
    if not neighbour_workouts:
        return ""
    return """
### THE DAYS JUST OUTSIDE THE SPAN
The user content includes a section titled "SESSIONS JUST OUTSIDE THE SPAN": the sessions
already planned in the week just outside the days you may write. They are not yours to
change: never return an entry dated on one of those days, and never name one of them in
"replaces". Count them when you write the days next to them. A weekly rule — how many
strength sessions, how many hard days, a rest day, no gym day before a hard ride or a heavy
lift — holds over the week the athlete lives, and that week does not stop at the edge of the
days you write.
"""


def neighbour_sessions_section(neighbour_workouts: Sequence[Workout], eval_date: str) -> str:
    """The SESSIONS JUST OUTSIDE THE SPAN section of the user content, one summary line per
    session (DESIGN_mesocycle_boundary.md §7)."""
    return (
        "## SESSIONS JUST OUTSIDE THE SPAN\n"
        "Already planned and not yours to change — see THE DAYS JUST OUTSIDE THE SPAN.\n"
        + format_neighbour_workouts(neighbour_workouts, eval_date=eval_date)
    )


def move_task() -> str:
    """The MOVING A SESSION TO ANOTHER DAY section, always-on in the adapt TASK.

    A move used to be two entries the model had to remember to pair, and forgetting the
    second left the session standing on both days (DESIGN_adapt_task_prompt.md §2). It is
    now one entry naming the slot it came from, which is also what carries the session's
    history to its new day (DESIGN_workout_revisions.md §11).
    """
    return """
### MOVING A SESSION TO ANOTHER DAY
Return the session ONCE, on its new date, written out in full, with
"replaces": {"date": ..., "sport_type": ...} naming the slot it came from, and a
"change_reason" saying where it went and why (e.g. "Long ride moved to Sunday — away
Saturday."). Its history follows it, so the athlete reads one change rather than a
disappearance and an arrival, and the day it left becomes a rest day carrying that same
sentence — you do not write one yourself.
Return an entry for the day it left ONLY when that day should still carry work: an easy
session in place of the one that moved. Never return the same session on both days, and
never write it on its new date without "replaces" — the day it left would keep the session
it already has, and the work would be scheduled twice.
When its new date already holds a session of the same sport, the moved session takes that
session's place and that session is removed. Say so in "change_reason", and move that
session too if it should survive.
"""


def benchmark_task() -> str:
    """The PROTECTING A BENCHMARK section of the adapt TASK
    (DESIGN_benchmark_workouts.md §4.2).

    Its own function rather than inline prose because the closing line — that an unchanged
    benchmark is not returned — is what makes `workout_revision_apply`'s
    `clear_benchmark` inference sound, so the two must not drift apart.
    """
    return """
### PROTECTING A BENCHMARK — RESCHEDULE, DON'T DILUTE
A session tagged "[BENCHMARK ...]" is a fitness test: measurement, not stimulus, so the
usual "ease the hard day" logic is exactly wrong for it — run tired it reads low and then
mis-scales every workout after it. NEVER reduce, soften or shorten a benchmark, and never
blank the flag on the session that still IS the test. If the athlete will not be fresh on
test day (negative TSB / poor recovery), MOVE it intact — same content, same
benchmark_type — to a later day within THIS mesocycle where they will be fresher, and lighten
the days before it; emit the test on its new date, naming the day it came from in
"replaces" as MOVING A SESSION TO ANOTHER DAY says.
If it already sits on the mesocycle's LAST day and no later in-mesocycle day exists,
POSTPONE it: replace it with an ordinary easy session (no benchmark_type) — a compromised
maximal test sets a wrong anchor that mis-scales every session after it, so a skipped test
costs a retest where a bad number costs a mesocycle.
The next generated mesocycle re-places the test when it is due.
A benchmark you are NOT changing is not returned at all — like any unchanged session.

benchmark_type says what a session IS, not which day it sits on — it travels with the test,
not with the date. So any OTHER session you put on a test's date — the easy day of a
postponement, or something the athlete asked for instead — is NOT the test and MUST carry
"benchmark_type": null. Copying the flag onto it files that session as a completed fitness
test: a social ride is then read as an FTP result, and the mesocycle believes it has already
tested and skips the real one. If you replace a test rather than move it, say so in the
reason and leave the flag off.
"""
