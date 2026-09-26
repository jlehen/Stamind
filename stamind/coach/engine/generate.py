"""The `workout generate` prompt: the week planner writes the sessions for a span.

Holds the TASK and schema sections only this call has — the sessions the athlete is
already looking at and how to answer for each, the mesocycle already under way, the
constraints that ended inside it — and the builder that assembles them. The sections both
calls share come from `sessions.py`.
"""
from typing import Any, Dict, List, Optional

from stamind.coach.engine.sessions import (
    SPORT_TYPE_ENUM, planned_zone_fields, planned_zone_task, replaces_field,
    strength_brief_task,
)
from stamind.coach.formatting import (
    format_baseline, format_completed_activities, format_metrics_history,
    format_standing_workouts,
)
from stamind.output import step
from stamind.text import cyan
from stamind.types import CompletedActivity, Constraint, Objective, Workout
import stamind.coach.engine as _eng


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
        + replaces_field("SESSIONS ALREADY STANDING") +
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


class WorkoutGenerateMixin:
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
        past_constraints: Optional[List[Constraint]] = None,
        terse: bool = False,
    ) -> Dict[str, Any]:
        """Queries LLM to generate workouts for a given number of days based on active strategy.

        `start_str` is the first day to schedule (defaults to today). It is later than
        today when the selectors opened the span there, or when today's session is already
        completed and must be preserved (DESIGN_cli_selectors.md §8).

        `standing_workouts` are the sessions inside the commitment window that this span
        would rewrite (DESIGN_plan_change_continuity.md §4.2). `past_constraints` ended
        earlier in the current mesocycle and explain its record (§6.1). `terse` halves the
        summary (DESIGN_output_verbosity.md §9).
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
        # Half the summary for an athlete who asked for short answers
        # (DESIGN_output_verbosity.md §9).
        sentences = 2 if terse else 4
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
            + strength_brief_task()
            + _standing_sessions_task(standing_workouts)
            + _past_constraints_task(past_constraints)
            + planned_zone_task(zone_currencies)
            + "\n"
            "## RESPONSE FORMAT\n"
            "You MUST respond with a JSON object containing:\n"
            "{\n"
            '  "reasoning": "How this microcycle design serves the active mesocycle focus, in AT\n'
            f'    MOST {sentences} SENTENCES. The sessions themselves are listed below your\n'
            '    prose — describe the shape of the microcycle and why, not each workout in\n'
            '    turn.",\n'
            + _athlete_note_field(standing_workouts)
            # Workout generation is read-only w.r.t. coach learnings (see
            # DESIGN_backward_evaluation.md §11): it consumes the rendered learnings in the
            # system prompt but authors none. Tactical/recent observations are better
            # captured by `adapt`, durable ones by `analyze`. Hence no learning_updates here.
            + '  "workouts": [\n'
            "    {\n"
            '      "date": "YYYY-MM-DD",\n'
            + SPORT_TYPE_ENUM +
            '      "title": "Workout Title (e.g., Tempo Run, Long Ride, Rest Day)",\n'
            '      "short_name": "Hills", (At most 5 characters naming the kind of session,\n'
            '        e.g. "Easy", "Long", "Hills", "Tempo", "Z2", "VO2", "Gym". null on a\n'
            '        rest day)\n'
            '      "description": "Start with the title on its own line in brackets followed by a\n'
            '        newline, e.g. \"[Tempo Run]\\n\", then a detailed description of intensity,\n'
            '        duration, heart rate zones, and goals.",\n'
            "      \"duration_minutes\": 60, (Estimated workout duration in minutes, integer. Use 0 for rest days)\n"
            "      \"rpe\": 6, (Expected Rate of Perceived Exertion, integer 1-10. Use 0 for rest days)\n"
            "      \"tss\": 45, (Expected Training Stress Score, integer. Use 0 for rest days)\n"
            + planned_zone_fields(zone_currencies)
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
            # trajectory (DESIGN_pmc_fitness_fatigue.md §5.2).
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
            system_prompt, user_content, label="workout_generate",
            wait_notice="Writing your sessions",
        )
        return planner_reply
