from datetime import datetime
from typing import Any, Dict, List, Optional, Tuple
from stamind.types import Objective, Constraint
from stamind.text import cyan, wrap_text
from stamind.output import step
import stamind.coach.engine as _eng


def _previous_strategy_section(
    previous_plan: Optional[Tuple[str, List[Dict[str, Any]]]]
) -> Optional[str]:
    """The plan being replaced, as the prompt section that carries it.

    Built here because every other `## …` section of every prompt is built here: a
    section assembled in the service is one the prompt-structure rules do not reach
    (designs/DESIGN_prompt_structure.md). The service hands over the strategy and its
    mesocycles; the wording of the section is the engine's.
    """
    if not previous_plan:
        return None
    strategy, mesocycles = previous_plan
    meso_text = "".join(
        f"  - {m['name']} ({m['start_date']} to {m['end_date']}): {m['focus']}\n"
        for m in mesocycles
    )
    return (
        "## PREVIOUS PERIODIZATION STRATEGY (FOR CONTEXT)\n"
        f"- Overall Strategy: {strategy}\n"
        f"- Mesocycles:\n{meso_text or '  - None\n'}"
    )


class PlanStrategyMixin:
    """Part of :class:`CoachEngine` — see coach/engine/__init__.py."""

    def _plan_generate_strategy(
        self, next_goal: Objective, objectives: List[Objective],
        constraints: List[Constraint], today_str: str, guidelines: str,
        profile: Optional[Dict[str, Any]],
        previous_plan: Optional[Tuple[str, List[Dict[str, Any]]]] = None,
        plan_start_str: Optional[str] = None, athlete_feedback: Optional[str] = None,
        history_summary: Optional[str] = None, prior_training_text: Optional[str] = None,
        learnings: Optional[str] = None,
        current_mesocycle: Optional[Dict[str, Any]] = None,
        changed_inputs: Optional[str] = None,
        anchor_history: Optional[str] = None,
    ) -> Dict[str, Any]:
        """Queries LLM to determine the overall macrocycle strategy and mesocycles.

        The plan always runs from the start date to the goal, however far out that is: how
        a long horizon gets structured is a question for the science guidelines, not for a
        duration threshold in the app.

        Builds its own system prompt rather than calling `_build_system_prompt`: that one
        states the ACTIVE strategy and mesocycles as settled fact, which is the very thing this
        call produces (DESIGN_backward_evaluation.md §10.1).

        `changed_inputs` is the staleness reason and its diff, when this run is answering
        one: the model may open the strategy text with a paragraph saying what moved
        (DESIGN_plan_change_continuity.md §6.2)."""
        plan_start = plan_start_str or today_str
        # The date-as-event framing is structural — repeated in the task, the response
        # format, and the user message — so a horizon goal has to branch it here; prose
        # in the goal description cannot override it (ARCHITECTURE.md §15 "Goal dates").
        is_horizon = next_goal.get('date_type') == 'horizon'
        custom_task = f"""
## TASK
Determine the overall periodization strategy (macrocycle) from {plan_start} until the target
goal ({next_goal['target_date']}).

Divide this timeframe into contiguous, sequential mesocycles (determining the duration of each
mesocycle based on the periodization style guidelines provided in the science file). When planning
mesocycles, it is acceptable to shorten/extend a mesocycle by a few days to align its transition or
recovery boundaries with the athlete's active constraints (e.g. aligning a deload week or phase
change with a long trip).
Make sure there are no gaps between the end date of one mesocycle and the start date of the next.
The last mesocycle must end on or around the goal date ({next_goal['target_date']}).
"""
        # Keeping the in-flight mesocycle means repeating its ORIGINAL start date: mesocycles own
        # their sessions by date containment, so one re-dated to today reads as empty
        # (DESIGN_mesocycle_progress.md §7).
        if current_mesocycle:
            meso = current_mesocycle
            trained_days = (
                datetime.strptime(today_str, "%Y-%m-%d").date()
                - datetime.strptime(meso['start_date'], "%Y-%m-%d").date()
            ).days
            custom_task += f"""
### THE MESOCYCLE ALREADY UNDER WAY
The athlete is part-way through a mesocycle of the plan you are replacing:

  "{meso['name']}" ({meso['start_date']} to {meso['end_date']})
  Focus: {meso['focus']}
  Already trained: {trained_days} days of it, starting {meso['start_date']}.

Decide whether that mesocycle still fits the plan you are now designing.

- If it DOES, keep it: emit it as your FIRST mesocycle with its ORIGINAL start date
  ({meso['start_date']}), its original end date ({meso['end_date']}),
  its name and its focus, all unchanged. Do NOT re-date it to {plan_start}: the athlete
  finishes the mesocycle they are in, and the days already trained stay part of it. Your
  second mesocycle then starts the day after it ends.
- If it does NOT, because the goals, the constraints or the athlete's profile have changed
  enough that continuing it would be wrong, discard it and start your first mesocycle on
  {plan_start}.

State which of the two you chose, and why, in the strategy text.
"""
        else:
            custom_task += f"""
The first mesocycle must start on the start date ({plan_start}).
"""
        if is_horizon:
            custom_task += f"""
The goal's date is a TRAINING HORIZON, not a scheduled event: nothing happens on
{next_goal['target_date']} itself. Do NOT plan a peak, taper, or race-day realization phase
pinned to that date — finish with an ordinary training mesocycle, and let any performance attempt
(e.g. a timed effort at the goal) fall wherever the plan has the athlete fit and fresh.
"""

        if athlete_feedback:
            custom_task += f"""
### ATHLETE FEEDBACK ON THE CURRENT PLAN
Verbatim notes from the athlete about the plan in place, oldest first. A note marked
(phase: <name>) was filed against that mesocycle; unmarked notes address the plan as a whole.
{athlete_feedback}
You MUST address every note: revise the macrocycle strategy and/or the duration, boundaries,
and focuses of individual mesocycles accordingly (e.g. scheduling more rest, changing mesocycle
emphasis, extending/shortening specific cycles), while continuing to respect overall sports
science principles and guidelines.
"""

        if changed_inputs:
            custom_task += """
### SAYING WHAT MOVED
This replanning is answering a change to one of the inputs the previous plan was built
from; the change is given above as its own section, with the edit itself. You may open
your "strategy" text with ONE paragraph saying what moved and why the plan is now shaped
as it is — written for the athlete, in their language, naming the line that changed
rather than the field it lives in. If the change did not actually reshape anything,
write no such paragraph: an opening that announces a change the mesocycles do not show is
worse than none. Everything after that paragraph is the strategy as usual.
"""

        previous_strategy_text = _previous_strategy_section(previous_plan)
        if previous_strategy_text:
            custom_task += """
### CONTINUITY WITH THE PREVIOUS PLAN
The PREVIOUS periodization strategy that was in place before this replanning is
given above, as its own section. Please take it into account to ensure continuity
in the athlete's training, adapting or building on top of what has been planned
or done so far, rather than starting completely from scratch, unless a complete
reset is warranted by major changes.
"""

        phase_examples = (
            "Base Building, Specific Preparation, Build, Consolidation" if is_horizon
            else "Base Building, Specific Preparation, Build,\n        Peak & Taper, Race/Event"
        )
        custom_task += f"""
## RESPONSE FORMAT
You MUST respond with a JSON object containing:
{{
  "strategy": "Explain the overall training strategy philosophy and periodization strategy
    until the goal date ({next_goal['target_date']}).",
  "mesocycles": [
    {{
      "name": "Phase Name (e.g., {phase_examples})",
      "start_date": "YYYY-MM-DD",
      "end_date": "YYYY-MM-DD",
      "focus": "Key focus and description of this mesocycle (e.g., volume progression,
        aerobic threshold, rest, peak load, etc.)"
    }}
  ]
}}
"""
        obj_text = self._render_goal_lines(objectives)

        c_text = self._render_constraints(constraints)

        athlete_profile = self._format_athlete_profile(profile)
        system_prompt = (
            "You are Stamind Coach, an advanced AI sports science training coach.\n"
            "You design periodized training plans (macro, meso, micro cycles) leading up "
            "to target goals.\n\n"
            f"{guidelines}\n"
        )

        if previous_strategy_text:
            system_prompt += f"\n{previous_strategy_text}\n"

        system_prompt += (
            f"\n## ATHLETE PROFILE & PREFERENCES\n{athlete_profile}\n"
        )
        # Beside the profile's bare threshold values, which say nothing of how each was
        # obtained (DESIGN_benchmark_workouts.md Rev. 5).
        if anchor_history:
            system_prompt += f"\n{self._anchors_on_record_section(anchor_history)}\n"
        if history_summary:
            system_prompt += (
                f"\n## ATHLETE RECENT TRAINING SUMMARY (PAST 15 DAYS)\n{history_summary}\n"
            )
        # Planned-vs-actual review of the prior plan + any inferred reconstruction, fed as
        # read-only context so the new plan is grounded in demonstrated reality rather than
        # an idealized template (DESIGN_backward_evaluation.md §6, Option A).
        if prior_training_text:
            system_prompt += f"\n## PRIOR TRAINING REVIEW\n{prior_training_text}\n"
        # The distilled half of what the analysis flow found; the reconstruction above is
        # its narrative half (DESIGN_backward_evaluation.md §10.1).
        if learnings:
            system_prompt += (
                "\n## ATHLETE-SPECIFIC OBSERVATIONS\n"
                "Accumulated by the training-history analysis, tagged "
                "[id|sports|confidence].\n"
                f"{learnings}\n"
                "Weigh these when shaping the mesocycles — a higher confidence means more weeks "
                "of evidence\nbehind the observation. They are input only here: authoring "
                "and revising them belongs\nto the analysis flow.\n"
            )
        if changed_inputs:
            system_prompt += (
                "\n## WHAT CHANGED SINCE THE PREVIOUS PLAN\n"
                "The input that flagged this plan out of date, and the edit itself. "
                "See SAYING WHAT MOVED.\n"
                f"{changed_inputs}\n"
            )
        system_prompt += (
            f"\n## ACTIVE ATHLETE GOALS (CHRONOLOGICAL)\n"
            f"{obj_text if obj_text else 'No active goals.'}\n\n"
            f"## ACTIVE CONSTRAINTS (athlete-declared directives to work around)\n"
            f"{c_text if c_text else 'No active constraints.'}\n\n"
            f"{custom_task}\n"
        )

        if is_horizon:
            goal_phrase = (
                f"'{next_goal['title']}', training toward a horizon of "
                f"{next_goal['target_date']}"
            )
        else:
            goal_phrase = f"'{next_goal['title']}' on {next_goal['target_date']}"
        start_phrase = (
            f"starting from {plan_start}, unless you keep the mesocycle already under way, "
            f"which starts {current_mesocycle['start_date']}"
            if current_mesocycle else f"starting from {plan_start}"
        )
        user_content = (
            f"Today's date is {today_str}. The target goal is {goal_phrase}. "
            f"Please determine the macrocycle and mesocycles {start_phrase}."
        )

        step(wrap_text(
            "Querying OpenRouter to generate macrocycle and mesocycles "
            "periodization strategy..."
        ), cyan)
        result = _eng.openrouter_client.complete(
            system_prompt, user_content, label="plan_generate",
            wait_notice="Writing your plan",
        )
        return result

    def _plan_reshape_verdict(
        self, change_reason: str, diff_text: str, strategy: str,
        mesocycles: List[Dict[str, Any]],
    ) -> Dict[str, Any]:
        """The verdict call: asks the coach model whether a changed input would have altered
        the periodization — the DESIGN_plan_staleness.md §2 test, applied by the model that
        would do the rebuilding rather than by the athlete alone (§10).

        A small call on purpose: the rubric, the diff, and the plan as it stands. No
        science file, no history — the question is structural, and a model told to look
        for a reason to regenerate will find one, so the rubric demands the concrete
        change it would make and treats "cannot name one" as keep."""
        mesocycle_lines = "\n".join(
            f"- {m['name']} ({m['start_date']} to {m['end_date']}): {m['focus']}"
            for m in mesocycles
        )
        system_prompt = """You are an endurance coach reviewing a periodization plan you built earlier.

## TASK
One of the inputs the plan was generated from has changed. Decide whether, had the new value
been in force at generation time, you would have built a structurally different periodization.

"Structurally different" means one of exactly three things: a different mesocycle structure
(number, type or length of mesocycles), a different phase order, or a different volume ramp.
Nothing else counts. Changes to wording, tone, motivation, how sessions should be described,
what to listen to, or which days sessions land on are absorbed by the next workout
generation and do NOT reshape the plan.

Be strict. Answer "reshaping" only if you can name the specific structural change you would
make. If you cannot name one, the answer is keep.

## RESPONSE FORMAT
Return a JSON object with exactly these keys:
{
  "reshaping": true or false,
  "why": "one sentence naming the structural change you would make, or why none is needed"
}
"""
        user_content = f"""## WHAT CHANGED
{change_reason}

{diff_text or "(no field-level diff available)"}

## THE PLAN AS IT STANDS
{strategy}

Mesocycles:
{mesocycle_lines}
"""
        step("Asking the coach whether this change reshapes the plan...", cyan)
        return _eng.openrouter_client.complete(
            system_prompt, user_content, label="plan_verdict",
            wait_notice="Checking whether this change reshapes your plan",
        )
