from typing import Any, List, Optional, Dict, Sequence
from trainmate.config import config
from trainmate.prompt import athlete_watching
from trainmate.types import Objective, Constraint, Workout, CompletedActivity
from trainmate.util import cyan, days_between, step
from trainmate.coach.formatting import (
    format_metrics_history, format_completed_activities, format_baseline,
    format_planned_workouts_detailed,
    format_removed_workouts, format_daily_signals, format_standing_workouts,
)
import trainmate.coach.engine as _eng
from trainmate.sports import CANONICAL_SPORTS


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


_SPORT_TYPE_ENUM = _sport_type_enum()


def _terminal_window_task(days_left: int, meso_end_date_str: str) -> str:
    """Renders the adapt-prompt section used when the mesocycle is about to end.

    An easing proposed here cannot rebound inside the mesocycle and the next mesocycle is out of
    reach, so the model is biased toward holding load (DESIGN_mesocycle_boundary.md §3).
    """
    ending = (
        "ends today" if days_left == 0
        else f"ends in {days_left} day(s), on {meso_end_date_str}"
    )
    return f"""
### THIS MESOCYCLE IS ENDING
The mesocycle you are adapting {ending}.
An easing applied now therefore has no runway to rebound — no later session remains in which
to restore the load you shed — and the days after {meso_end_date_str} belong to the next
mesocycle, which you can neither adapt nor pre-empt.
Hold the planned load unless the signal is one you would act on even if this were the
mesocycle's very last session. Do not deepen a cut to "carry" the athlete into the next mesocycle:
it is planned separately, against their metrics as they stand when it is generated.
"""


def _standing_sessions_task(standing_workouts: Optional[List[Workout]]) -> str:
    """The section of the generate TASK covering the sessions already standing
    (DESIGN_plan_change_continuity.md §4.5/§4.6).

    Gated on there being such a session, so a bare `workout generate` extending the
    schedule into empty days produces the prompt it always did.
    """
    if not standing_workouts:
        return ""
    return """
### THE SESSIONS THE ATHLETE IS ALREADY LOOKING AT
The user content includes a section titled "SESSIONS ALREADY STANDING": the sessions this
span already holds inside the days the athlete has already read and planned around. A
session may also carry a tag:

- "[BENCHMARK: ...]" — a scheduled fitness test, and the strongest commitment on the
  calendar: the athlete arranges to be fresh for it, so moving or dropping one needs a
  reason that says why the test can wait.
- "[REST DAY]" — a day they were told holds no session. Putting work on it is a change
  like any other, and needs the same reason.

KEEP each of these sessions unless it contradicts the athlete's profile, the plan, or a
constraint AS THEY STAND TODAY. If it does, name the line it contradicts in the sentence
you write for the athlete, and make the smallest change that resolves that contradiction.
Wording is never a contradiction: a session whose day, sport and load still fit, that you
would merely describe differently, is kept.

Answer for every session in that list with exactly one of these, and nothing in between:

- KEEP it. Return `{"date": ..., "sport_type": ..., "keep": true}` and no other field. The
  session stays exactly as it stands, down to the interval structure and prose you were not
  shown, and the athlete sees no change on that day. Count its target toward the week's
  intensity distribution when you write the days around it, but do not restate it: a KEEP
  carries no "planned_zone_sec" and anything else attached to one is discarded.
- REVISE it. Return it as an ordinary workout in the SAME date and sport, fully written
  out, with a "change_reason". Its history will show the athlete the form it had before.
- MOVE it, or CHANGE ITS SPORT. Return the session in its new slot, fully written out,
  with `"replaces": {"date": ..., "sport_type": ...}` naming the slot it came from, and a
  "change_reason". The day it left follows the session, so the athlete sees one change and
  not a disappearance and an arrival.
- DROP it. Return `{"date": ..., "sport_type": ..., "drop": true, "change_reason": ...}`.
  The day becomes a rest day carrying your sentence, in place of the session.

A session in that list you do not mention at all is KEPT. So say it when you mean to
remove one — silence is never how a cancellation is expressed.

"change_reason" is ONE SENTENCE, written for the athlete to read, about that day, naming
the line it answers: "your profile asks for four sessions a week, so Friday is now a
session", not "deload, polarised week". It is REQUIRED on a revise, a move and a drop, and
belongs only to the sessions in that list: every other day of the span is yours to write
from scratch, the athlete has never seen it, and there is nothing there for a change to be
FROM.

A session already eased by an adaptation says what it was FIRST prescribed as, alongside
how often and how recently it was eased. Keep the eased form unless the moment it answered
has passed — writing the day back at its first numbers hands the athlete the exact load the
adaptation took off. One thing outranks a fresh easing: a constraint or a profile line the
session contradicts. An easing answers "how is the athlete today"; a constraint answers
"what may this athlete do at all", and the second wins.
"""


# What no revision may rewrite: shared by `workout adapt` and `workout tweak`.
_LOCKED_HISTORY_TASK = """
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

# How to read a depressed morning, and why not to cut twice. Adapt's alone: a tweak does
# not ask whether the athlete's state calls for a change (DESIGN_workout_tweak.md §3.2).
_FATIGUE_READING_TASK = """
### ATTRIBUTING A DEPRESSED MORNING — TRAINING FATIGUE vs LIFESTYLE NOISE
By rule 5, read the externally-logged daily signal from the DAY BEFORE a depressed
morning: if one (e.g. alcohol, a bad night, high stress) explains the dip, that suppression
is transient lifestyle noise, NOT accumulated training fatigue.
That changes WHY, not WHAT TO DO TODAY: a suppressed body trains a hard session poorly and
with more risk regardless of cause, so easing or moving today's hard session remains a fair
call on acute readiness. What it changes is what the day is EVIDENCE of — reserve genuine
load REDUCTIONS for fatigue the TRAINING actually caused (a depressed morning following
genuinely hard days, with no lifestyle signal to explain it). When a hard day AND a
lifestyle signal coincide, both may contribute — weigh them rather than blaming training.

### DO NOT COMPOUND A PRIOR ADAPTATION
Sessions tagged "[ALREADY EASED by a prior adaptation ...]" are NOT the original plan —
their numbers are the reduced form a previous adaptation already produced. Rule 5 again:
the morning after an easing still looks depressed from the very fatigue you already acted
on, and reading that as "still too hard" spirals the load down without ever letting it
rebound. Default to HOLDING the already-eased form. Cut further only if the metrics have
clearly WORSENED since it was eased, or a genuinely NEW signal (a hard completed session, a
fresh constraint/signal event) warrants it — and the more recently and more times it was
already eased (see the tag), the higher your bar. Restoring load toward the original as the
athlete recovers is encouraged; deepening an already-fresh cut is not.
"""


def _strength_brief_task(has_message: bool = False) -> str:
    """The one instruction that makes a strength day's description a brief
    (DESIGN_strength_tracking.md §9).

    Always on, in both the generate and the adapt TASK: a strength day can fall anywhere in
    a span, and TrainMate's strength planner writes every one of them from the sets the
    athlete actually lifted — which this call is never shown.

    `has_message` adds how a request made inside a strength session reaches that call: the
    week planner writes it into the brief (DESIGN_workout_tweak.md §4).
    """
    return _STRENGTH_BRIEF_TASK + (_STRENGTH_REQUEST_TASK if has_message else "")


_STRENGTH_BRIEF_TASK = """
### WRITING A STRENGTH DAY
A strength session's "description" is a BRIEF, not a session: what the session is for in the
plan, its character, and what the plan asks of it that day. Write NO exercise, no set count,
no rep count and no load into it. TrainMate's strength planner writes those, from the sets
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


def _tweak_task(
    target_date_str: str, meso_end_date_str: str, tweak_dates: Sequence[str], watching: bool
) -> str:
    """The head of the `workout tweak` TASK: the days the request is about, changed as
    asked (DESIGN_workout_tweak.md §3.2).

    `tweak_dates` are the days the caller already knows, from `-d`; empty, the week planner
    reads them off the request. `watching` is false when the athlete's human coach typed
    the request from outside their chat, so the reason is written to the athlete and never
    as a reply (DESIGN_change_heads_up.md §3).
    """
    if tweak_dates:
        days_line = f"The days are: {', '.join(sorted(tweak_dates))}."
    else:
        days_line = (
            'Read them off the request ("Friday", "tomorrow", "swap Thursday and Friday").\n'
            "  The Evaluation Date is today, and every day must fall between "
            f"{target_date_str} and\n  {meso_end_date_str}. If you cannot tell which days "
            "are meant, or one falls outside that\n"
            '  range, return "change_needed": false and "tweak_dates": [], and say why in\n'
            '  "reason".'
        )
    if watching:
        opening = "The athlete asks for a change to the schedule."
        voice = ""
    else:
        opening = (
            "The athlete's human coach, who manages their week from outside their chat, "
            "asks for\na change to the schedule."
        )
        voice = """
The athlete has not seen the request. The "reason" is sent to them as a message about the
change to their week. Write it to the athlete: what changed and why, in plain words. Never
write it as a reply — the athlete asked for nothing, so "as you asked" is wrong.
"""
    return f"""
## TASK
{opening}
The request is in the user content under THE ATHLETE'S REQUEST. Carrying it out is this
run's whole job. Do not adapt the schedule to the metrics here: the morning adaptation does
that.
{voice}
- FIND THE DAYS the request is about, and return them as "tweak_dates".
  {days_line}
- CHANGE ONLY THOSE DAYS. Every session on every other date stays exactly as planned. A
  session may move between those days, never to or from another date.
- DO WHAT IS ASKED. The request may be for a session made shorter, longer, easier or
  harder; another sport in its place; other exercises in a strength session; a session
  added; a session dropped, which you write as a rest day; a session moved to another day,
  or two days swapped, which MOVING A SESSION TO ANOTHER DAY says how to write; or a
  cancelled session brought back, which you write again from its line under SESSIONS NO
  LONGER ON THE SCHEDULE. Write each session in full — title, description, duration, RPE
  and TSS — sized to fit the week around it. The metrics and the planned sessions are your
  context for that. To change a session's sport, return the new session on the same date
  with "replaces" naming the slot it takes over.
- IT IS THE ATHLETE'S CALL. If the request looks unwise, carry it out and say so in one
  sentence of "reason": three hard days in a row after a swap is that kind of sentence.
  Refuse only what is clearly unsafe given the recovery metrics, or what would rewrite a
  session already performed: return "change_needed": false and say why in "reason".
- NAME THE REQUEST. Every session you change carries a "change_reason" that says what was
  asked, e.g. "On request: hike with friends in place of the long ride." A later run reads
  it, knows this session was asked for, and leaves it alone.
"""


def _past_constraints_task(past_constraints: Optional[List[Constraint]]) -> str:
    """The section naming the constraints that ended earlier in this mesocycle
    (DESIGN_plan_change_continuity.md §6.1)."""
    if not past_constraints:
        return ""
    return """
### WHAT ALREADY HAPPENED IN THIS MESOCYCLE
The user content includes a section titled "CONSTRAINTS EARLIER IN THIS MESOCYCLE": directives
whose dates have passed but which fall inside the mesocycle the athlete is in. They are not
yours to work around any more — they explain the mesocycle's record. A week that shows far less
training than it was planned was often a week under one of these, and reading it as the
athlete failing to train, or as evidence the mesocycle is too hard, would be wrong.
"""


def _mesocycle_progress_task(mesocycle_progress: Optional[str]) -> str:
    """The CONTINUING A MESOCYCLE section (DESIGN_mesocycle_progress.md §4).

    Gated on the data being present, so a run that starts a mesocycle cleanly produces the
    prompt it always did. It also conditions BENCHMARK PLACEMENT above, which on its own
    cannot know a boundary test was already run earlier in the mesocycle (§4.1).
    """
    if not mesocycle_progress:
        return ""
    return """
### CONTINUING A MESOCYCLE ALREADY UNDER WAY
The user content includes a section titled "MESOCYCLE PROGRESS SO FAR": what the mesocycle the
athlete is currently in has already banked — its volume and measured intensity, then each
already-trained week with the load the plan asked of it beside the load the athlete actually
produced, then any fitness test it has already run. Those days are history and are not yours
to write — you are producing this mesocycle's REMAINDER, not the mesocycle.

Read it as the progression's starting point, not as a fresh mesocycle. Carry the ramp on from
where the last completed week left it instead of restarting at week-one volume, and keep
the mesocycle's remaining weeks pointed at the focus it was given. If one elapsed week's
planned load dips clearly below the weeks around it, that week WAS this mesocycle's deload —
do not schedule a second one; if no such dip has happened yet and the mesocycle's design calls
for one, it still belongs in the weeks you are writing. A dip that recurs on a fixed rhythm
— every other week, where the athlete's guidelines alternate a heavier and a lighter week —
is the microcycle, not the deload: the deload is the one-off dip below that rhythm.

Where a week's actual load fell well short of what was planned, build from the volume the
athlete actually produced rather than from the plan they did not complete — ramping from an
unfulfilled number spikes the acute load. Where actual ran above planned, do not reward it
with a further jump on top.

This also BOUNDS the BENCHMARK PLACEMENT rule above: a boundary week whose fitness test
already appears in that section has had its test, and must not be given a second one.
Place a benchmark only where this mesocycle has not already run it.
"""


def _mesocycle_composition_task(mesocycle_progress: Optional[str], has_intensity: bool) -> str:
    """The JUDGING THE MESOCYCLE'S COMPOSITION section — the other end of
    DESIGN_intensity_distribution.md §9.4's handoff, which tells `adapt` that an over-hard
    mesocycle "belongs to the next `workout generate`" (§9.2a).

    Gated on the zone tables actually having rows, not merely on the mesocycle-progress section
    existing: every paragraph below quotes those tables, and an athlete with no zone
    recordings would be pointed at a table that says "no zone data".
    """
    if not mesocycle_progress or not has_intensity:
        return ""
    return """
### JUDGING THE MESOCYCLE'S COMPOSITION
The mesocycle-progress section carries what the athlete's activities actually MEASURED, per sport
and zone, beside what the plan PRESCRIBED over the same weeks and beside the mesocycle's stated
focus. Composition is yours: how many hard sessions the mesocycle holds, and how its easy and
hard work divide. `workout adapt` owns the other half — it sharpens how an already-scheduled
session is prescribed and may not change what the mesocycle contains — and it defers exactly
this question to you.

ATTRIBUTE BEFORE YOU ACT. Read the measured table against the PRESCRIBED table first,
because the same divergence from the focus has two opposite causes and one wrong answer:
- Measured tracks the prescription, but neither delivers the focus -> the PLAN is wrong,
  and fixing it is yours. Re-shape the weeks still ahead so the mesocycle's hard/easy split
  actually produces what its focus asks for.
- Measured diverges from the prescription -> the athlete is executing something other than
  what was written. That is adapt's lane and it is already correcting it session by
  session. Do NOT re-shape the mesocycle to match the deviation: cutting hard sessions because
  easy days were run hard rewards the drift and hands the athlete an easier mesocycle for
  ignoring the plan. Hold the composition and keep the prescription honest.
- Both track the focus -> there is nothing to correct here. Carry the design on.

Where a change against the preceding mesocycle is shown, that is the periodization signal
proper: intensity creeping up mesocycle over mesocycle is how a base phase quietly becomes a race
season, and deciding whether the weeks you are writing continue or arrest that trend is the
one intensity judgement no other command can make.

Condition all of this on the coverage line and the power table where one exists. An HR-only
table under-reads a hard session, so a mesocycle can measure easy that was not — do not
conclude a mesocycle was too soft from heart rate alone.
"""


def constraint_extraction_task(lead: str) -> str:
    """The prompt section that turns a note into `new_constraints` candidates.

    `lead` is the one clause that differs between the two passes that ask for these
    candidates — `workout adapt -m` extracts alongside adapting, `bot capture note`
    extracts as its whole job — so the rules themselves stay one text on both paths
    (DESIGN_bot_simple_frontend.md §12.10).
    """
    return f"""
### EXTRACTING A DURABLE CONSTRAINT FROM THE NOTE
{lead}
Decide whether the note states something the coach must work around beyond today:
unavailability, a time/intensity cap, an injury layoff, a venue/equipment limit, or a
stated preference with a date or date range (e.g. "no run Thursday", "only 45 min today",
"broke my ankle, out 6 weeks"). If so, return it in "new_constraints" below — one entry per
distinct directive, exactly as if the athlete had run `constraint add`. A note only about
how they feel right now ("felt flat, ease today") is NOT a constraint — leave
"new_constraints" empty for it (it may still be a signal, below). When unsure, leave it
out: a durable-looking note mis-filed as a constraint is worse than a missed one. A rule
with no time bound at all — "I never have time for two workouts in a day", "no gym on
Fridays, ever" — is OPEN-ENDED: return it with "open_ended": true and both dates null.
The app does not store those as constraints; it tells the athlete where such a rule
belongs. Everything else is dated: never omit "start_date"/"end_date" for it (default
both to today when the note is about the days at hand but names none). This is
extraction only — never invent a plan-shaping escalation. Extracted constraints are
always advisory; the deterministic-rest and plan-shaping escalations are deliberate human
actions and the app, not you, decides those.
"""


def signal_extraction_task(vocabulary: Optional[str], earliest_date: str) -> str:
    """The prompt section that turns a note into `new_signals` candidates.

    Shows the category vocabulary so one string is reused per category instead of a new one
    coined per occasion, and forbids inventing a `value` the note never stated
    (DESIGN_signal_extraction.md §2, §5). Shared with `bot capture note` for the same
    reason its constraint sibling is (DESIGN_bot_simple_frontend.md §12.10).
    """
    catalogue = vocabulary or "(no categories configured yet — propose one, kept short.)"
    return f"""
### RECORDING A DAILY SIGNAL FROM THE NOTE
Also decide whether the note reports something that HAPPENED TO the athlete on particular
days and would help explain their recovery readings: a heavy night's drinking, a broken
night, a heatwave, illness, life stress. If so, return it in "new_signals" below, one entry
per category per span.

Tell it apart from a constraint by what the coach must do with it. A CONSTRAINT is a rule to
plan around ("no run Thursday"). A SIGNAL is an external cause acting on the body on given
days, which the coach reads beside the HRV/sleep/RHR numbers. A note that is only a mood
report with no cause ("felt flat today") is NEITHER — leave both lists empty for it.

Use one of these categories, spelled EXACTLY as shown, whenever one fits:
{catalogue}
Propose a category outside the list only when none fits. A category is a reusable label you
would expect to log again — one or two words, lowercase, underscore-separated. It is never a
description of this occasion: "kid_was_ill_all_night" is wrong, "disturbed_sleep" is right.

"date"/"end_date" carry the days the signal ACTED ON, which is usually the recent past —
"last night" is yesterday, "over the weekend" is those dates. Default to today when the note
gives no day. Never go earlier than {earliest_date}.

Set "value" ONLY when the note states a number, in the unit named by the category above
("three beers" -> 3; "it hit 38" -> 38). Otherwise omit it or send null. NEVER invent a
severity score: a category with free text and no number is complete and useful, and a
fabricated number is read as a measurement.
"""


# The two candidate members, written once. `workout adapt -m` and `bot capture note` both
# ask for them, and a divergence between the two schemas would mean the same sentence
# stored two different ways depending on which inbox read it (§12.10).
NEW_CONSTRAINTS_SCHEMA = (
    '  "new_constraints": [\n'
    "    // Optional. Directives extracted from the athlete's note this run (see\n"
    "    // EXTRACTING A DURABLE CONSTRAINT above). Every entry is created exactly as\n"
    "    // if the athlete had run `constraint add`. Omit entirely, or leave empty, if\n"
    "    // the note was only a one-off nudge about today.\n"
    "    {\n"
    '      "title": "the directive, stated short (required)",\n'
    '      "start_date": "YYYY-MM-DD (required; default today)",\n'
    '      "end_date": "YYYY-MM-DD (required; == start for a single day)",\n'
    '      "open_ended": "true ONLY for a rule with no time bound at all (dates null)",\n'
    '      "description": "optional richer context or null/omit"\n'
    "    }\n"
    "  ]"
)

NEW_SIGNALS_SCHEMA = (
    '  "new_signals": [\n'
    "    // Optional. Daily signals extracted from the athlete's note this run\n"
    "    // (see RECORDING A DAILY SIGNAL above). Every entry is created exactly as\n"
    "    // if the athlete had run `signal add`. Omit entirely, or leave empty, when\n"
    "    // the note reports no external cause.\n"
    "    {\n"
    '      "metric": "the category, spelled exactly as listed where one fits\n'
    '        (required)",\n'
    '      "date": "YYYY-MM-DD, the first day it acted on (required)",\n'
    '      "end_date": "YYYY-MM-DD (required; == date for a single day)",\n'
    '      "value": 3 (the number the note stated, in the unit named for that\n'
    "        category; null or omitted when the note gave none — never invent one),\n"
    '      "text": "the athlete\'s own words for it, short (optional)"\n'
    "    }\n"
    "  ]"
)


def _planned_zone_task(zone_currencies: Optional[Dict[str, str]]) -> str:
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


def _replaces_field(listing: str) -> str:
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


def _standing_answer_fields(standing_workouts: Optional[List[Workout]]) -> str:
    """The `keep`, `drop`, `replaces` and `change_reason` members of the generate response
    schema (DESIGN_plan_change_continuity.md §4.5).

    Third region on the same gate as the TASK section and the data section: a schema that
    offers these where the prompt never explained them is exactly the half-application
    `tests/test_prompt_gates.py` exists to catch.
    """
    if not standing_workouts:
        return ""
    return (
        '      "keep": true (OMIT on an ordinary session. Present ONLY on a session listed\n'
        "        in SESSIONS ALREADY STANDING that you are keeping exactly as it stands —\n"
        '        see THE SESSIONS THE ATHLETE IS ALREADY LOOKING AT — in which case "date"\n'
        '        and "sport_type" are the only other fields to give),\n'
        '      "drop": true (OMIT on an ordinary session. Present ONLY on a session listed\n'
        "        in SESSIONS ALREADY STANDING that you are removing, in which case\n"
        '        "date", "sport_type" and "change_reason" are the only other fields to\n'
        "        give. The date becomes a rest day carrying your sentence),\n"
        + _replaces_field("SESSIONS ALREADY STANDING") +
        '      "change_reason": "One sentence for the athlete about this day, naming the\n'
        "        line it answers. REQUIRED on any session listed in SESSIONS ALREADY\n"
        "        STANDING that you revise, move or drop; omitted on every other session.\",\n"
    )


def _athlete_note_field(standing_workouts: Optional[List[Workout]]) -> str:
    """The `athlete_note` member: one line about the change as a whole, for the morning
    push (DESIGN_plan_change_continuity.md §6.3). Same gate as the rest — a run that
    extends the schedule into empty days changed nothing the athlete had seen."""
    if not standing_workouts:
        return ""
    return (
        '  "athlete_note": "ONE line for the athlete about this change as a whole, in\n'
        "    their own language — what moved and why, e.g. \"Four sessions a week now,\n"
        "    never two hard days in a row.\" Omit it entirely when nothing they would\n"
        "    notice changed.\",\n"
    )


def _planned_zone_fields(zone_currencies: Optional[Dict[str, str]]) -> str:
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


# Two of adapt's STANDING RULES as constants, so `tests/test_prompt_gates.py` can assert
# which rules the TASK is given against the constants rather than against quoted prose
# (DESIGN_adapt_task_prompt.md §2). The other three are written inline at the call site.
RULE_MOVE_FIRST = (
    "MOVE BEFORE YOU EASE, EASE BEFORE YOU DELETE. Rescheduling a session a day or two\n"
    "   preserves the planned work; deleting it loses it."
)

RULE_MESOCYCLE_NOT_YOURS = (
    "THE MESOCYCLE IS NOT YOURS TO RESHAPE. You adapt the sessions inside it.\n"
    "   No single day's signal — a depressed morning, a note, a drift reading —\n"
    "   is evidence the MESOCYCLE is too hard, and none permanently re-cuts its planned\n"
    "   volume/intensity. When you do believe the mesocycle itself is wrong, say so in\n"
    "   \"reason\" and leave it alone."
)


def _standing_rules_task(*rules: str) -> str:
    """The STANDING RULES section, numbered in the order given."""
    body = "\n".join(f"{i}. {rule}" for i, rule in enumerate(rules, start=1))
    return f"""
### STANDING RULES
These govern every section below, and none of them restates these rules:
{body}
"""


def _move_task() -> str:
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


def _benchmark_task() -> str:
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


class WorkoutLogicMixin:
    """Part of :class:`CoachEngine` — see coach/engine/__init__.py."""

    def _workout_generate_logic(
        self, objectives: List[Objective], constraints: List[Constraint],
        today_str: str, guidelines: str, profile: Optional[Dict[str, Any]],
        strategy: str, meso_text: str, learnings: str,
        num_days: int = 28,
        start_str: Optional[str] = None,
        metrics: Optional[List[Dict[str, Any]]] = None,
        completed_activities: Optional[List[CompletedActivity]] = None,
        baseline: Optional[Dict[str, Any]] = None,
        pmc_warmup_cutoff: Optional[str] = None,
        pmc_context: Optional[str] = None,
        mesocycle_progress: Optional[str] = None,
        mesocycle_has_intensity: bool = False,
        zone_currencies: Optional[Dict[str, str]] = None,
        anchor_history: Optional[str] = None,
        standing_workouts: Optional[List[Workout]] = None,
        past_constraints: Optional[List[Constraint]] = None
    ) -> Dict[str, Any]:
        """Queries LLM to generate workouts for a given number of days based on active strategy.

        `start_str` is the first day to schedule (defaults to today). It is later than
        today when the selectors opened the span there, or when today's session is already
        completed and must be preserved (DESIGN_cli_selectors.md §8).

        `standing_workouts` are the sessions inside the commitment window that this span
        would rewrite (DESIGN_plan_change_continuity.md §4.2). `past_constraints` ended
        earlier in the current mesocycle and explain its record (§6.1).
        """
        start_str = start_str or today_str
        starting_phrase = "today" if start_str == today_str else start_str
        weeks = num_days / 7
        if weeks == int(weeks):
            duration_desc = f"{int(weeks)} week{'s' if weeks != 1 else ''} ({num_days} days)"
        else:
            duration_desc = f"{num_days} day{'s' if num_days != 1 else ''}"
        # Whether a test is DUE is benchmarks.md §1's call (triggers, cadence, floor);
        # this section names only the slot and the one fact the guidelines cannot know —
        # the tests this same span is placing (DESIGN_benchmark_workouts.md §4.1). The
        # no-test-near-goal carve-out is event logic — a horizon goal has no event for a
        # test to compete with. `objectives` is the upcoming list, date-ascending, so [0]
        # is the goal governing this span.
        if objectives and objectives[0].get('date_type') == 'horizon':
            goal_week_exception = (
                " The athlete's goal date is a training horizon, not a scheduled event,\n"
                "so a boundary week near it is an ordinary boundary."
            )
        else:
            goal_week_exception = (
                " Never place a test inside the last seven days before the goal or the\n"
                "goal's own week — the final mesocycle tapers into the event, and a maximal "
                "test there\n"
                "competes with the effort it is meant to serve."
            )
        custom_task = (
            "## TASK\n"
            f"Generate a training schedule for the next {duration_desc} starting from "
            f"{starting_phrase}.\n"
            "Ensure the microcycles — one week, or longer where the athlete's guidelines\n"
            "alternate weeks — are designed specifically to match the focus, target volume, and\n"
            "intensity of the active mesocycle(s) the athlete is in during this period, and\n"
            "incorporate any deload weeks or exceptions for the athlete's active constraints in accordance\n"
            "with the science guidelines.\n"
            "Cover EVERY date of the span: a training day carries its session, a rest\n"
            "day carries an explicit \"Rest Day\" entry. Never omit a date — an absent\n"
            "date and a planned rest day mean different things to the athlete's adherence\n"
            "record, and a hole reads as the schedule ending.\n"
            "\n"
            "### BENCHMARK PLACEMENT (fitness tests — see the BENCHMARK guidelines above)\n"
            "A mesocycle's final week is the natural slot for a fitness test;\n"
            "whether one is DUE there is the BENCHMARK guidelines' call. Apply their re-benchmark\n"
            "triggers, typical cadence and minimum-interval floor — counting any tests you are placing\n"
            "in this same span — and leave a boundary week without a test when none is due. ANCHORS ON\n"
            "RECORD in the user content dates each anchor's last measurement."
            + goal_week_exception
            + " When you do place one: set \"benchmark_type\" to the test kind, precede it with an opener\n"
            "or easy day so the athlete is fresh (positive TSB) on test day, keep the title/description\n"
            "venue-neutral (e.g. \"20-min FTP test\" — the athlete's preferences say where\n"
            "they test), and never put it in a week the athlete's constraints put under full rest.\n"
            + _mesocycle_progress_task(mesocycle_progress)
            + _mesocycle_composition_task(mesocycle_progress, mesocycle_has_intensity)
            + _strength_brief_task()
            + _standing_sessions_task(standing_workouts)
            + _past_constraints_task(past_constraints)
            + _planned_zone_task(zone_currencies)
            + "\n"
            "## RESPONSE FORMAT\n"
            "You MUST respond with a JSON object containing:\n"
            "{\n"
            '  "reasoning": "How this microcycle design serves the active mesocycle focus, in AT\n'
            '    MOST 4 SENTENCES. The sessions themselves are listed below your prose — describe\n'
            '    the shape of the microcycle and why, not each workout in turn.",\n'
            + _athlete_note_field(standing_workouts)
            # Workout generation is read-only w.r.t. coach learnings (see
            # DESIGN_backward_evaluation.md §11): it consumes the rendered learnings in the
            # system prompt but authors none. Tactical/recent observations are better
            # captured by `adapt`, durable ones by `analyze`. Hence no learning_updates here.
            + '  "workouts": [\n'
            "    {\n"
            '      "date": "YYYY-MM-DD",\n'
            + _SPORT_TYPE_ENUM +
            '      "title": "Workout Title (e.g., Tempo Run, Long Ride, Rest Day)",\n'
            '      "description": "Start with the title on its own line in brackets followed by a\n'
            '        newline, e.g. \"[Tempo Run]\\n\", then a detailed description of intensity,\n'
            '        duration, heart rate zones, and goals.",\n'
            "      \"duration_minutes\": 60, (Estimated workout duration in minutes, integer. Use 0 for rest days)\n"
            "      \"rpe\": 6, (Expected Rate of Perceived Exertion, integer 1-10. Use 0 for rest days)\n"
            "      \"tss\": 45, (Expected Training Stress Score, integer. Use 0 for rest days)\n"
            + _planned_zone_fields(zone_currencies)
            + _standing_answer_fields(standing_workouts) +
            '      "benchmark_type": null (Normally null. Set ONLY on a scheduled fitness\n'
            "        test — see BENCHMARK PLACEMENT — to the test kind, e.g. \"ftp_20min\" |\n"
            '        "ftp_ramp" | "run_threshold_30min" | "run_5k_tt" | "css_400_200" |\n'
            '        "e1rm" | "mas_cooper". An ordinary training session leaves it null.)\n'
            "    }\n"
            "  ]\n"
            "}\n"
        )
        system_prompt = self._build_system_prompt(
            objectives=objectives,
            constraints=constraints,
            guidelines=guidelines,
            strategy=strategy,
            meso_text=meso_text,
            learnings=learnings,
            profile=profile,
            custom_task=custom_task
        )
        user_content = (
            f"Today's date is {today_str}. "
            f"Please generate the microcycles (workouts) for the next {duration_desc} "
            f"starting from {starting_phrase}."
        )
        if start_str != today_str:
            user_content += (
                f" Today's ({today_str}) session is already completed and must NOT be "
                f"regenerated — the first workout you schedule must be dated {start_str}."
            )

        history_text_parts = []
        # What BENCHMARK PLACEMENT's interval rule reads against — without dates the
        # model cannot know whether an anchor is due (DESIGN_benchmark_workouts.md §4.1).
        if anchor_history:
            history_text_parts.append(self._anchors_on_record_section(anchor_history))
        # First of the history sections: it frames what the metrics and activities below
        # mean — the same volume reads differently in a mesocycle's first week than its last.
        # Same gate as the task section above, so the two never disagree about its presence.
        if mesocycle_progress:
            history_text_parts.append(
                "## MESOCYCLE PROGRESS SO FAR\n"
                "The part of the current mesocycle already trained — see CONTINUING A MESOCYCLE "
                f"ALREADY UNDER WAY.\n{mesocycle_progress}"
            )
        if metrics:
            metrics_text = format_metrics_history(metrics, pmc_warmup_cutoff)
            # The single CTL ramp line + warm-up flag ride beside the per-day lines (not
            # repeated per day), so the prompt that sets next week's load sees the fitness
            # trajectory (§5.2).
            if pmc_context:
                metrics_text += "\n" + pmc_context
            history_text_parts.append(
                f"## ATHLETE'S METRICS HISTORY (PAST 15 DAYS)\n{metrics_text}"
            )
        if baseline:
            baseline_str = format_baseline(baseline)
            history_text_parts.append(
                f"## BASELINE REFERENCE\n{baseline_str}"
            )
        if completed_activities:
            completed_text = format_completed_activities(completed_activities)
            history_text_parts.append(
                f"## ACTUAL COMPLETED GARMIN ACTIVITIES IN WINDOW\n{completed_text}"
            )

        # Why a week in this mesocycle went quiet, for a coach that can no longer see the
        # days themselves — the metrics window does not reach them (§6.1).
        if past_constraints:
            history_text_parts.append(
                "## CONSTRAINTS EARLIER IN THIS MESOCYCLE\n"
                "These have passed — they are not yours to work around. They are why the "
                "mesocycle's record\nreads as it does. See WHAT ALREADY HAPPENED IN THIS "
                "MESOCYCLE.\n"
                + self._render_constraints(past_constraints)
            )

        # Last, closest to where the model starts writing: unlike the sections above it
        # is not context about the athlete but a claim on the output. Same gate as THE
        # SESSIONS THE ATHLETE IS ALREADY LOOKING AT above, so the two never disagree
        # about its presence.
        if standing_workouts:
            history_text_parts.append(
                "## SESSIONS ALREADY STANDING\n"
                "You must answer for every session listed here — keep it, revise it, move "
                "it or drop it.\nEvery date this list does not name is yours to write "
                "from scratch.\n"
                + format_standing_workouts(standing_workouts, eval_date=today_str)
            )

        if history_text_parts:
            user_content += "\n\n" + "\n\n".join(history_text_parts)

        step("Querying OpenRouter to generate training workouts (microcycles)...", cyan)
        planner_reply = _eng.openrouter_client.complete(
            system_prompt, user_content, label="workout_generate"
        )
        return planner_reply

    def _workout_adapt_logic(
        self, target_date_str: str, history_days: int, start_date_str: str,
        metrics: List[Dict[str, Any]], completed_activities: List[CompletedActivity],
        planned_workouts: List[Workout], baseline_str: str,
        meso_end_date_str: str, objectives: List[Objective], constraints: List[Constraint],
        guidelines: str, profile: Optional[Dict[str, Any]], strategy: str,
        meso_text: str, learnings: str, discrepancies: List[str],
        informational: Optional[List[CompletedActivity]] = None,
        removed_workouts: Optional[List[Workout]] = None,
        daily_signals: Optional[List[Dict[str, Any]]] = None,
        performed: Optional[dict] = None,
        athlete_message: Optional[str] = None,
        pmc_warmup_cutoff: Optional[str] = None,
        pmc_context: Optional[str] = None,
        intensity_context: Optional[str] = None,
        zone_currencies: Optional[Dict[str, str]] = None,
        signal_vocabulary: Optional[str] = None,
        signal_earliest_date: Optional[str] = None,
        tweak: bool = False,
        tweak_dates: Sequence[str] = (),
    ) -> Dict[str, Any]:
        """Queries LLM to evaluate metrics/activities and adapt workouts if needed.

        `athlete_message` is an optional free-text note for THIS adaptation only; when
        present it is surfaced as a clearly-bounded section of the user content and the
        model is told to weigh it as today's intent without treating it as a durable
        signal about the mesocycle.

        `tweak` makes this the `workout tweak` call: the message is a request to change the
        days it is about, `tweak_dates` when the caller already knows them, and the TASK
        asks for that and nothing else (DESIGN_workout_tweak.md §3.2). `removed_workouts`
        is then every cancelled session in the range, not only the athlete's (§3.1).
        """
        # has_message gates SIX regions that sit hundreds of lines apart: the clause
        # spliced into the change_reason wording, the note-handling instructions, the
        # constraint- and signal-extraction instructions, the "new_constraints" and
        # "new_signals" schema members, and the note DATA section. They must appear
        # together or the model is told about a section that isn't present.
        # tests/test_prompt_gates.py asserts that, so the invariant survives edits here.
        has_message = bool(athlete_message and athlete_message.strip())
        # Same gate discipline: the drift branch, the CORRECTING EXECUTION DRIFT
        # instructions and the drift DATA section move together.
        has_intensity = bool(intensity_context and intensity_context.strip())
        # Shared change_reason wording, with the note-footprint clause spliced in only when
        # a note could actually have driven the change.
        note_clause = ''
        if tweak:
            note_clause = ' Say what was\n        asked: see NAME THE REQUEST.'
        elif has_message:
            note_clause = (
                ' If an external\n'
                '        constraint from the athlete\'s note drove the change rather than\n'
                '        the metrics, name that cause here so a future run without the note\n'
                '        understands it, e.g. \"Rest — athlete away, no training access this\n'
                '        day.\"'
            )
        change_reason_field = (
            '      "change_reason": "One short sentence on why THIS specific session\n'
            '        changed, e.g. \"Cut to easy Z2 to shed intensity.\"'
            + note_clause
            + '\n        Keep it to a single sentence of at most 20 words; do not restate\n'
              '        the overall reason.",\n'
        )
        # The fourth branch the TASK is missing (§9.1): every existing branch treats
        # adaptation as a response to fatigue or absence, and an athlete running their
        # easy days at Z3 is neither — they showed up for everything and feel fine.
        drift_branch = "" if not has_intensity else (
            "- If the mesocycle's measured intensity distribution has diverged from its stated\n"
            "  focus, correct the prescriptions of the sessions still ahead — even when\n"
            "  recovery metrics are fine. A healthy athlete executing the wrong workout is\n"
            "  the case no other branch here covers.\n"
        )
        # All five: adapt is the pass that sees the metrics, the adherence window and the
        # athlete's note, so every rule has something to bind to here (§9). The last three
        # are adapt's alone and live here rather than as hoisted constants.
        standing_rules = _standing_rules_task(
            RULE_MOVE_FIRST,
            RULE_MESOCYCLE_NOT_YOURS,
            "NAME THE CAUSE. Every session you change carries a \"change_reason\" (see the\n"
            "   schema); when something other than the metrics drove it, that cause belongs\n"
            "   there.",
            "NOT EVERY GAP IS A MISS. Activities listed as informational fell on dates no\n"
            "   plan governed; sessions listed as deliberately removed belonged to a goal the\n"
            "   athlete called off. Count both when judging load and intent — neither is an\n"
            "   adherence failure.",
            "RECOVERY METRICS LAG. A morning reflects what came before it, not what you\n"
            "   schedule after it. Two sections below turn on this.",
        )
        adapt_task = f"""
## TASK
Analyze the athlete's actual workout adherence and physiological metrics trajectory over
the past {history_days} days: completed activities against planned workouts, the calculated
discrepancies (misses, workload/duration differences, rest violations), and the rolling
baseline against the daily metrics sequence for signs of accumulated fatigue.

Based on this, determine if we need to adapt the sessions for the remainder of
the active mesocycle (from {target_date_str} to {meso_end_date_str}).
- If they are showing high fatigue or injury risk (e.g. elevated RHR, depressed HRV,
  poor sleep, or ATL:CTL > 1.3 without a planned overload reason), replace hard workouts
  with recovery or rest.
- If they have missed key workouts, adjust the remaining workouts to safely build back
  volume without spiking the acute load too fast.
- If they are fully recovered and on track, keep the plan as scheduled or make minor
  optimal adjustments.
{drift_branch}{standing_rules}
"""
        if tweak:
            custom_task = _tweak_task(
                target_date_str, meso_end_date_str, tweak_dates, athlete_watching()
            )
            custom_task += _LOCKED_HISTORY_TASK
        else:
            custom_task = adapt_task + _LOCKED_HISTORY_TASK + _FATIGUE_READING_TASK

        # A strength day's description is a brief, here as in generate: the same rule has
        # to reach every call that writes one (DESIGN_strength_tracking.md §9).
        custom_task += _strength_brief_task(has_message)

        # How to encode a move at all — its own section rather than a clause inside the
        # benchmark text, because an ordinary move relies on it too
        # (DESIGN_adapt_task_prompt.md §2).
        custom_task += _move_task()

        # Why a test may never be softened, and why moving it is the model's call and not a
        # deterministic pass: DESIGN_benchmark_workouts.md §4.2.
        custom_task += _benchmark_task()

        # Adapt owns execution, generate owns periodization (§9.2): changing what zone
        # Tuesday's run is prescribed at is adapt's call; changing how many hard sessions
        # the mesocycle contains is not.
        if has_intensity:
            custom_task += """
### CORRECTING EXECUTION DRIFT
The mesocycle summary shows what the athlete's activities ACTUALLY measured, per sport
and zone, beside the mesocycle's stated focus — as a per-week rate over the mesocycle's
completed weeks, then the current week's raw minutes so far with how much of that
week has elapsed. The current week is NOT extrapolated: read it against the
elapsed fraction yourself.

A measured picture that disagrees with the focus is an execution error, not a
fatigue signal, and it is yours to fix — by changing HOW the remaining sessions
are prescribed, not how much they contain. Hold duration and planned TSS; sharpen
the intensity target and give it an explicit guard rail the athlete can act on
mid-session (a HR ceiling, a pace cap, "walk the hills").
- Drift upward means the athlete WANTS more, so do not only cap it: say where the
  appetite may legitimately go, in the batch-level reason, and spend it in the
  mesocycle's own currency — in a volume mesocycle, more easy minutes; in an intensity
  mesocycle, a fuller effort on the days already designated hard.
- Drift downward means under-execution, so the guard rail becomes a floor and the
  advice is about how to reach it. Condition this on the power table where one
  exists — HR lag makes under-execution look real when it is not.

This is never a load reduction. If the mesocycle genuinely contains too much hard work
— as opposed to easy work being run too hard — that is composition, and it
belongs to the next `workout generate`, not to you.
"""

        # §9.2 gives adapt the intensity factor of a scheduled session, and §9.4's drift
        # correction IS a rewrite of how a session is prescribed — so a session whose
        # zones adapt leaves alone would keep describing the prescription it just
        # replaced, and the future half of the zone table would grade the athlete against
        # a target no longer on the page (§9.8).
        custom_task += _planned_zone_task(zone_currencies)

        # Inside the mesocycle's terminal window a cut cannot rebound before the mesocycle ends
        # (DESIGN_mesocycle_boundary.md §3). Outside it the prompt is unchanged.
        days_left = days_between(target_date_str, meso_end_date_str)
        if not tweak and 0 <= days_left <= config.adapt_terminal_window_days:
            custom_task += _terminal_window_task(days_left, meso_end_date_str)

        # A run the athlete does not watch sends its reason to them later, so the note is
        # presented as their coach's and the reason is written to them, never as a reply
        # (DESIGN_change_heads_up.md §3). Only this paragraph changes; the titles stay.
        # A tweak's request is spoken for by its own TASK head.
        if has_message and not tweak and athlete_watching():
            custom_task += """
### ATHLETE'S NOTE FOR TODAY
The user content includes a section titled "ATHLETE'S NOTE FOR THIS ADAPTATION": a
free-text note the athlete attached to THIS run — extra intent or constraints the metrics
can't show (e.g. a niggle to protect, no access to a sport/venue on a given day, or how
they feel). Weigh it as today's intent alongside the data: honour stated constraints, and
let it tip a judgement call. It is advisory, not an override — do NOT schedule clearly
unsafe load just because the athlete asks (if recovery signals warrant easing, ease and say
why). It speaks for this adaptation only and is never durable evidence about the mesocycle.
"""
        elif has_message and not tweak:
            custom_task += """
### ATHLETE'S NOTE FOR TODAY
The user content includes a section titled "ATHLETE'S NOTE FOR THIS ADAPTATION". Despite
that title, the athlete did NOT write it: it is a note from the athlete's human coach, who
manages their week from outside their chat, and the athlete has not seen it. It carries
extra intent or constraints the metrics can't show (e.g. the weather, no access to a
sport/venue on a given day, a niggle to protect). Weigh it as today's intent alongside the
data: honour stated constraints, and let it tip a judgement call. It is advisory, not an
override — do NOT schedule clearly unsafe load just because the note asks (if recovery
signals warrant easing, ease and say why). It speaks for this adaptation only and is never
durable evidence about the mesocycle.
The "reason" is sent to the athlete as a message about the change to their week. Write it
to the athlete: what changed and why, in plain words. Never write it as a reply to the
note — the athlete asked for nothing, so "as you asked" or "as requested" is wrong.
"""

        if has_message:
            custom_task += constraint_extraction_task(
                "Separately from adapting today's sessions, this is a second job."
            )
            custom_task += signal_extraction_task(
                signal_vocabulary, signal_earliest_date or target_date_str
            )

        custom_task += """
### DURABLE OBSERVATIONS ARE READ-ONLY HERE
This daily adaptation is READ-ONLY with respect to the coach's durable observations:
use the COACH LEARNINGS as context, but do NOT emit any learning updates here — durable,
evidence-backed observations are authored only by the weekly history analysis
(`data bootstrap` / `data reflect`).
"""

        # Each entry is one top-level member of the response object, without its trailing
        # comma — the ",\n".join below places the separators, so no code hand-writes a
        # comma and the has_message branch can't desync the punctuation.
        schema_members = [
            '  "change_needed": true | false',
            (
                '  "reason": "Overall rationale for the whole adaptation: the readiness/load\n'
                '    picture and the strategy applied to the mesocycle, in AT MOST 3 SENTENCES\n'
                '    (~60 words). Adapt runs daily, so this is the line the athlete reads most\n'
                '    often — name the signal you acted on and what you did about it, and leave\n'
                '    out the readings that did NOT change your mind. This is the batch-level\n'
                '    summary, shared by every adapted workout below — do NOT repeat it per\n'
                '    workout; keep per-workout notes in "change_reason"."'
            ),
            (
                '  "adapted_workouts": [\n'
                "    // Include ONLY sessions you are actually changing. Omit any session that\n"
                "    // stays exactly as planned — it is preserved automatically, so re-listing\n"
                "    // an unchanged session (even verbatim) is wrong and counts as a spurious\n"
                "    // adaptation.\n"
                "    // ONE EXCEPTION, and it does NOT need a full entry: a date you are\n"
                "    // changing keeps only the sports you name, so a session of ANOTHER sport\n"
                "    // that day is dropped unless you name it. Name it with a KEEP MARKER —\n"
                "    // three fields, nothing else:\n"
                '    //     { "date": "YYYY-MM-DD", "sport_type": "...", "keep": true }\n'
                "    // That holds it exactly as planned. Use it ONLY for a session you are\n"
                "    // leaving alone; do not restate its title, description or numbers to\n"
                "    // keep it.\n"
                "    // Rewriting only a session's DESCRIPTION is a real change, not churn —\n"
                "    // the athlete reads it, so a better cue, an updated reference to a\n"
                "    // session just executed, or a clearer instruction is worth making. Give\n"
                "    // it a full entry and say why in \"change_reason\".\n"
                "    {\n"
                '      "date": "YYYY-MM-DD",\n'
                + _SPORT_TYPE_ENUM +
                '      "title": "Adapted Workout Title",\n'
                + change_reason_field +
                '      "description": "Start with the title on its own line in brackets followed by a\n'
                '        newline, e.g. \"[Tempo Run]\\n\", then an adapted description of intensity,\n'
                '        duration, heart rate zones, and goals.",\n'
                '      "duration_minutes": 45,\n'
                '      "rpe": 5,\n'
                '      "tss": 30,\n'
                + _planned_zone_fields(zone_currencies)
                + _replaces_field("PLANNED WORKOUTS") +
                '      "benchmark_type": null (Preserve VERBATIM on the row that still IS\n'
                "        the test — a moved/kept test must stay a test. null on EVERY\n"
                "        other session, including one that takes over a test's date.\n"
                "        Never invent one here. See PROTECTING A BENCHMARK.)\n"
                "    }\n"
                "  ]"
            ),
        ]
        if tweak:
            schema_members.append(
                '  "tweak_dates": ["YYYY-MM-DD", ...] (every day the request is about; []\n'
                '    when you cannot tell)'
            )
        if has_message:
            schema_members.append(NEW_CONSTRAINTS_SCHEMA)
            schema_members.append(NEW_SIGNALS_SCHEMA)
        custom_task += (
            "\n## RESPONSE FORMAT\n"
            "You MUST respond with a JSON object containing:\n{\n"
            + ",\n".join(schema_members)
            + "\n}\n"
        )
        system_prompt = self._build_system_prompt(
            objectives=objectives,
            constraints=constraints,
            guidelines=guidelines,
            strategy=strategy,
            meso_text=meso_text,
            learnings=learnings,
            profile=profile,
            custom_task=custom_task
        )

        metrics_text = format_metrics_history(metrics, pmc_warmup_cutoff)
        # Single ramp line + warm-up flag beside the per-day mesocycle, so adapt sees the
        # fatigue trajectory (§5.2).
        if pmc_context:
            metrics_text += "\n" + pmc_context
        signals_text = (
            format_daily_signals(daily_signals) if daily_signals
            else "No external daily signals logged in this window."
        )
        discrepancy_text = (
            "\n".join(discrepancies) if discrepancies
            else "No discrepancies detected (athlete fully on track)."
        )
        planned_text = format_planned_workouts_detailed(
            planned_workouts, performed, eval_date=target_date_str
        )
        completed_text = format_completed_activities(completed_activities)

        removed_section = ""
        if removed_workouts and tweak:
            removed_section = (
                "\n## SESSIONS NO LONGER ON THE SCHEDULE\n"
                "Cancelled, dropped or replaced, by the coach or the athlete. A request to\n"
                "bring one back is written again from its line.\n"
                + format_removed_workouts(removed_workouts) + "\n"
            )
        elif removed_workouts:
            removed_section = (
                "\n## WORKOUTS REMOVED BY ATHLETE (deliberately cancelled — not misses)\n"
                + format_removed_workouts(removed_workouts) + "\n"
            )

        informational_section = ""
        if informational:
            informational_section = (
                "\n## ACTIVITIES OUTSIDE ANY PLAN (informational — load counts, "
                "but not adherence failures)\n" + format_completed_activities(informational) + "\n"
            )

        # Ephemeral, this-run-only note from the athlete (see custom_task guidance). Same
        # has_message gate as the instructions above, so the two never disagree. Omitted
        # entirely when absent so a message-less run is byte-for-byte the prior behaviour.
        message_section = ""
        if tweak:
            message_section = (
                "\n## THE ATHLETE'S REQUEST\n"
                "The change asked for, to the days it is about only — see the TASK.\n"
                f"{(athlete_message or '').strip()}\n"
            )
        elif has_message:
            message_section = (
                "\n## ATHLETE'S NOTE FOR THIS ADAPTATION\n"
                "Free-text intent/constraints for today only — advisory, not an override;\n"
                "do not treat as durable evidence about the mesocycle.\n"
                f"{athlete_message.strip()}\n"
            )

        # The measured mesocycle summary (§9.3). Kept out of the metrics section on purpose:
        # this is an execution signal, not a readiness one, and the two must not blur.
        intensity_section = ""
        if has_intensity:
            intensity_section = (
                "\n## MEASURED INTENSITY DISTRIBUTION OF THE ACTIVE MESOCYCLE\n"
                "What the athlete's activities actually recorded, per sport and zone —\n"
                "see CORRECTING EXECUTION DRIFT.\n"
                f"{intensity_context.strip()}\n"
            )

        descriptions_note = (
            "Adapt as boldly as the athlete's state warrants, but only\nwhere their state "
            "actually warrants it; the descriptions are here only so detail you are\n"
            "keeping isn't lost for lack of being restated:"
        )
        if tweak:
            descriptions_note = (
                "The descriptions are here only so detail you\nare keeping isn't lost for "
                "lack of being restated:"
            )
        user_content = f"""
Evaluation Date: {target_date_str}
Adaptation Range: {target_date_str} to {meso_end_date_str}
{message_section}{intensity_section}

## ATHLETE'S METRICS HISTORY (PAST {history_days} DAYS)
{metrics_text}

## EXTERNALLY-LOGGED DAILY SIGNALS (alcohol, poor sleep, stress, etc.)
{signals_text}

## BASELINE REFERENCE
{baseline_str}

## PLANNED WORKOUTS
The recent window for adherence, plus already-scheduled sessions through the
adaptation range. This is the full forward plan for CONTEXT — most of it will
usually be fine and should be left untouched; return a session in "adapted_workouts"
only if you are genuinely changing it (the schema's "adapted_workouts" comment covers
omitting unchanged sessions and why re-listing one is a spurious adaptation).
When you DO change a session, modify it in place: preserve its date and sport_type
unless you are deliberately moving it to another day or changing its sport, which
MOVING A SESSION TO ANOTHER DAY says how to write. Only invent a brand-new session for a
date that currently has none.
Each session below includes its full description so you can reuse its specifics —
interval structure, heart-rate zones, rest/recovery durations — when you carry a changed
session over largely as-is. {descriptions_note}
{planned_text}
{removed_section}
## ACTUAL COMPLETED GARMIN ACTIVITIES IN WINDOW
{completed_text}

## ADHERENCE DISCREPANCIES & VIOLATIONS
{discrepancy_text}
{informational_section}"""
        if tweak:
            step("Querying OpenRouter to make the change asked for...", cyan)
            return _eng.openrouter_client.complete(
                system_prompt, user_content, label="workout_tweak"
            )
        step(f"Querying OpenRouter to evaluate adaptation for the remainder of the mesocycle "
             f"({target_date_str} -> {meso_end_date_str})...", cyan)
        decision = _eng.openrouter_client.complete(
            system_prompt, user_content, label="workout_adapt"
        )
        return decision
