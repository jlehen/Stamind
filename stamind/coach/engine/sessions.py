"""How the week planner writes one session entry.

The prompt sections about a single session rather than about the span: the sport enum
both schemas list, the intensity target, its two schema members, the `replaces` field,
the strength brief, what may not be rewritten, how a move is written, and what a
benchmark entry must keep. The first five of those are sent by `workout generate` and
`workout adapt` both, and a second copy of one would slowly stop meaning the same thing
in the two prompts (DESIGN_adapt_task_prompt.md §1). The last three only adapt sends
today; they live here because they are about the entry, not about adapting.
"""
from typing import Dict, List, Optional

from stamind.sports import CANONICAL_SPORTS


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


def planned_zone_task(zone_currencies: Optional[Dict[str, str]]) -> str:
    """The PRESCRIBING INTENSITY section (DESIGN_intensity_distribution.md §9.8).

    The week planner already decides an intensity target — it writes "6x3min @ VO2max" — and is
    the only thing in the system that knows the intent. So it states the distribution as
    structured data while it still knows it, instead of the app parsing it back out of
    prose afterwards (§10). Which currency each sport is planned in is the APP's call,
    not the model's: it comes from the same coverage rule the display uses, so the plan
    is never written in a currency the table cannot render.
    """
    if not zone_currencies:
        return ""
    names = {"power": "power (7 zones)", "hr": "heart rate (5 zones)"}
    lines = "\n".join(
        f"  {sport}: {names.get(cur, cur)}"
        for sport, cur in sorted(zone_currencies.items())
    )
    return f"""
### PRESCRIBING INTENSITY (planned time in zone)
State each session's intensity target as structured data, not only in the prose. The
currency per sport is fixed by what the athlete's recordings actually cover — use
exactly these and nothing else:
{lines}
A sport not listed above (and any rest day) leaves "planned_zone_currency" null and
"planned_zone_sec" empty: swimming is anchored on pace and strength on load, and neither
yields a zone model. Do NOT invent one for them.

Split the session's minutes across the zones the way you intend it to be executed —
warm-up and recovery minutes into the low zones, work minutes into the target zone. A
5x4min VO2max session is mostly Z2 by the clock and that is what to write. Do NOT derive
these numbers from "tss": TSS is duration x intensity folded into one scalar and cannot
be unfolded, and zones computed from it would make planned-vs-measured intensity a
restatement of the adherence percentage that already exists.

The seconds do not have to sum to "duration_minutes" x 60 — they are a prescription, not
an accounting identity. HR sessions fill zones 1-5 and leave 6 and 7 null.
"""


def planned_zone_fields(zone_currencies: Optional[Dict[str, str]]) -> str:
    """The two response-schema members carrying §9.8's target, declared the way every
    other field is: a prose-annotated JSON example."""
    if not zone_currencies:
        return ""
    return (
        '      "planned_zone_currency": "hr" | "power" | null (the currency for THIS\n'
        "        session's sport, from PRESCRIBING INTENSITY above; null for rest days\n"
        "        and for any sport not listed there),\n"
        '      "planned_zone_sec": [300, 1800, 600, 0, 0, null, null] (seconds intended\n'
        "        in each zone, low to high. Five entries for heart rate, seven for\n"
        "        power; use null or omit entirely when the currency is null),\n"
    )


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
A brief reads like this: "[Full-Body Strength (Heavy, Non-Failure)]\\nHeavy full-body
strength, second week of the build, non-failure. 70 min at the gym. Keep the legs fresh for
Saturday's long ride."
A brief names an exercise in one case only: it was requested, and the brief says "as
requested". When you rewrite such a brief, keep what it says was requested.
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
