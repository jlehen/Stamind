"""The `workout adapt` and `workout tweak` prompt: the week planner revises a span.

Holds the TASK sections only these two calls have — the standing rules, how to read a
depressed morning, and the mesocycle's terminal window — and the builder that assembles
them. The sections both calls share come from `sessions.py`, and the ones about the
athlete's words from `notes.py`.
"""
from typing import Any, Dict, List, Optional, Sequence

from stamind.clock import days_between
from stamind.coach.engine.notes import (
    NEW_CONSTRAINTS_SCHEMA, NEW_SIGNALS_SCHEMA, constraint_extraction_task,
    note_for_today_task, signal_extraction_task, tweak_task,
)
from stamind.coach.engine.sessions import (
    LOCKED_HISTORY_TASK, SPORT_TYPE_ENUM, benchmark_task, move_task, planned_zone_fields,
    planned_zone_task, replaces_field, strength_brief_task,
)
from stamind.coach.formatting import (
    format_completed_activities, format_daily_signals, format_metrics_history,
    format_planned_workouts_detailed, format_removed_workouts,
)
from stamind.config import config
from stamind.output import step
from stamind.prompt import athlete_watching
from stamind.text import cyan
from stamind.types import CompletedActivity, Constraint, Objective, Workout
import stamind.coach.engine as _eng


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


# Adapt owns execution, generate owns periodization (DESIGN_intensity_distribution.md
# §9.2): changing what zone Tuesday's run is prescribed at is adapt's call; changing how
# many hard sessions the mesocycle contains is not.
_DRIFT_TASK = """
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


class WorkoutAdaptMixin:
    """Part of :class:`CoachEngine` — see coach/engine/__init__.py."""

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
        terse: bool = False,
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
        `terse` halves the summary (DESIGN_output_verbosity.md §9).
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
        # The fourth branch the TASK is missing (DESIGN_intensity_distribution.md
        # §9.1): every existing branch treats
        # adaptation as a response to fatigue or absence, and an athlete running their
        # easy days at Z3 is neither — they showed up for everything and feel fine.
        drift_branch = "" if not has_intensity else (
            "- If the mesocycle's measured intensity distribution has diverged from its stated\n"
            "  focus, correct the prescriptions of the sessions still ahead — even when\n"
            "  recovery metrics are fine. A healthy athlete executing the wrong workout is\n"
            "  the case no other branch here covers.\n"
        )
        # All five: adapt is the pass that sees the metrics, the adherence window and the
        # athlete's note, so every rule has something to bind to here
        # (DESIGN_adapt_task_prompt.md §2). The last three
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
            custom_task = tweak_task(
                target_date_str, meso_end_date_str, tweak_dates, athlete_watching()
            )
            custom_task += LOCKED_HISTORY_TASK
        else:
            custom_task = adapt_task + LOCKED_HISTORY_TASK + _FATIGUE_READING_TASK

        # A strength day's description is a brief, here as in generate: the same rule has
        # to reach every call that writes one (DESIGN_strength_tracking.md §9).
        custom_task += strength_brief_task(has_message)

        # How to encode a move at all — its own section rather than a clause inside the
        # benchmark text, because an ordinary move relies on it too
        # (DESIGN_adapt_task_prompt.md §2).
        custom_task += move_task()

        # Why a test may never be softened, and why moving it is the model's call and not a
        # deterministic pass: DESIGN_benchmark_workouts.md §4.2.
        custom_task += benchmark_task()

        if has_intensity:
            custom_task += _DRIFT_TASK

        # §9.2 gives adapt the intensity factor of a scheduled session, and §9.4's drift
        # correction IS a rewrite of how a session is prescribed — so a session whose
        # zones adapt leaves alone would keep describing the prescription it just
        # replaced, and the future half of the zone table would grade the athlete against
        # a target no longer on the page (§9.8).
        custom_task += planned_zone_task(zone_currencies)

        # Inside the mesocycle's terminal window a cut cannot rebound before the mesocycle ends
        # (DESIGN_mesocycle_boundary.md §3). Outside it the prompt is unchanged.
        days_left = days_between(target_date_str, meso_end_date_str)
        if not tweak and 0 <= days_left <= config.adapt_terminal_window_days:
            custom_task += _terminal_window_task(days_left, meso_end_date_str)

        # A run the athlete does not watch sends its reason to them later, so the note is
        # presented as their coach's and the reason is written to them, never as a reply
        # (DESIGN_change_heads_up.md §3). A tweak's request is spoken for by its own TASK
        # head.
        if has_message and not tweak:
            custom_task += note_for_today_task(athlete_watching())

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

        # Half the summary for an athlete who asked for short answers. Only the summary:
        # "change_reason" is read again by later runs (DESIGN_output_verbosity.md §9).
        if terse:
            reason_field = (
                '  "reason": "What you changed and why, or why nothing needs to change, in AT\n'
                '    MOST 2 SHORT SENTENCES (~30 words in all): the athlete prefers short\n'
                '    answers. When the note or the request drove a change, name that change\n'
                '    first. Name the signal you acted on, and leave out every reading that did\n'
                '    NOT change your mind. This is the batch-level summary, shared by every\n'
                '    adapted workout below — do NOT repeat it per workout; keep per-workout\n'
                '    notes in "change_reason"."'
            )
        else:
            reason_field = (
                '  "reason": "Overall rationale for the whole adaptation: the readiness/load\n'
                '    picture and the strategy applied to the mesocycle, in AT MOST 3 SENTENCES\n'
                '    (~60 words). Adapt runs daily, so this is the line the athlete reads most\n'
                '    often — name the signal you acted on and what you did about it, and leave\n'
                '    out the readings that did NOT change your mind. This is the batch-level\n'
                '    summary, shared by every adapted workout below — do NOT repeat it per\n'
                '    workout; keep per-workout notes in "change_reason"."'
            )
        # Each entry is one top-level member of the response object, without its trailing
        # comma — the ",\n".join below places the separators, so no code hand-writes a
        # comma and the has_message branch can't desync the punctuation.
        schema_members = [
            '  "change_needed": true | false',
            reason_field,
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
                + SPORT_TYPE_ENUM +
                '      "title": "Adapted Workout Title",\n'
                + change_reason_field +
                '      "description": "Start with the title on its own line in brackets followed by a\n'
                '        newline, e.g. \"[Tempo Run]\\n\", then an adapted description of intensity,\n'
                '        duration, heart rate zones, and goals.",\n'
                '      "duration_minutes": 45,\n'
                '      "rpe": 5,\n'
                '      "tss": 30,\n'
                + planned_zone_fields(zone_currencies)
                + replaces_field("PLANNED WORKOUTS") +
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
        # fatigue trajectory (DESIGN_pmc_fitness_fatigue.md §5.2).
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
                system_prompt, user_content, label="workout_tweak",
                wait_notice="Making the change you asked for",
            )
        step(f"Querying OpenRouter to evaluate adaptation for the remainder of the mesocycle "
             f"({target_date_str} -> {meso_end_date_str})...", cyan)
        decision = _eng.openrouter_client.complete(
            system_prompt, user_content, label="workout_adapt",
            wait_notice="Reviewing your coming sessions",
        )
        return decision
