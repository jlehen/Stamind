"""What is done with the athlete's words.

The sections that turn free text into something the app acts on or records: the head of
the `workout tweak` TASK, how to weigh a note attached to one adaptation, and the two
extraction passes that read a note into candidate constraints and candidate signals with
the schemas they answer in. `workout adapt -m` and `bot capture note` both ask for the
extractions, so the rules and the schemas are one text on both paths
(DESIGN_bot_simple_frontend.md §12.10).
"""
from typing import Optional, Sequence


def tweak_task(
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


def note_for_today_task(watching: bool) -> str:
    """The ATHLETE'S NOTE FOR TODAY section: how to weigh the note attached to this run.

    `watching` is false when the athlete's human coach typed the note from outside their
    chat, so the section says the athlete has not seen it and asks for the reason to be
    written to them rather than as a reply (DESIGN_change_heads_up.md §3). Only that
    paragraph differs; the title is the same either way.
    """
    if watching:
        return """
### ATHLETE'S NOTE FOR TODAY
The user content includes a section titled "ATHLETE'S NOTE FOR THIS ADAPTATION": a
free-text note the athlete attached to THIS run — extra intent or constraints the metrics
can't show (e.g. a niggle to protect, no access to a sport/venue on a given day, or how
they feel). Weigh it as today's intent alongside the data: honour stated constraints, and
let it tip a judgement call. It is advisory, not an override — do NOT schedule clearly
unsafe load just because the athlete asks (if recovery signals warrant easing, ease and say
why). It speaks for this adaptation only and is never durable evidence about the mesocycle.
"""
    return """
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
