from typing import Any, List, Optional, Dict
from stamind.types import Objective, Constraint
from stamind.clock import today_date as _today_date
from stamind.benchmarks import ANCHOR_KINDS, format_value


class PromptBuildMixin:
    """Part of :class:`CoachEngine` — see coach/engine/__init__.py."""

    @staticmethod
    def _anchors_on_record_section(anchor_history: str) -> str:
        """The ANCHORS ON RECORD section, shared by `plan generate` and `workout generate`
        so neither reads a threshold without its provenance (DESIGN_benchmark_workouts.md
        Rev. 5)."""
        return (
            "## ANCHORS ON RECORD\n"
            "The dated logbook behind the profile's thresholds. A 'manual' or 'modeled' "
            "value is\nan assumption, not a measurement — only a test starts the interval "
            "clock. This record,\nnot an earlier plan's text, says how each value was "
            "obtained.\n" + anchor_history
        )

    def _format_athlete_profile(self, profile: Optional[Dict[str, Any]]) -> str:
        """Formats the athlete's user profile into a readable prompt segment."""
        if not profile:
            return "No athlete profile configured."

        lines = []
        if "name" in profile:
            lines.append(f"- Name: {profile['name']}")
        if "birth_year" in profile:
            current_year = _today_date().year
            age = current_year - profile['birth_year']
            lines.append(f"- Birth Year: {profile['birth_year']} (Age: {age})")
        if profile.get("gender"):
            lines.append(f"- Gender: {profile['gender']}")
        # Render whatever threshold anchors the (effective) profile carries, generically
        # with each kind's unit — no kind is privileged (DESIGN_benchmark_workouts.md §3.5),
        # so a first swim/strength test shows up here with zero further code. Ordered by the
        # vocabulary so output is stable. max_hr comes from config, the rest from the logbook.
        for kind, anchor in ANCHOR_KINDS.items():
            if profile.get(kind) is not None:
                lines.append(f"- {anchor.label}: {format_value(kind, profile[kind])}")
        if "weekly_target_hours" in profile:
            lines.append(f"- Weekly Target Hours: {profile['weekly_target_hours']} hours")
        if "sport_preferences" in profile:
            lines.append(f"- Sport Preferences: {', '.join(profile['sport_preferences'])}")

        chronic_injuries = profile.get("chronic_injuries")
        if chronic_injuries:
            if isinstance(chronic_injuries, list):
                lines.append(f"- Chronic Injuries: {', '.join(chronic_injuries)}")
            else:
                lines.append(f"- Chronic Injuries: {chronic_injuries}")

        # Session-level by contract: the science documents set the structure, the
        # preferences say how a session is written up (DESIGN_plan_staleness.md §11).
        preferences = profile.get("preferences")
        if preferences:
            if isinstance(preferences, list):
                preferences = ', '.join(preferences)
            lines.append(f"- Preferences / Static Constraints: {preferences}")
            lines.append(
                "  (Preferences describe how sessions are written up, where they happen, "
                "with what kit, and how to speak to the athlete. Session counts, mesocycle "
                "order and taper depth come from the athlete-provided science guidelines, "
                "never from here.)"
            )

        general_equipment = profile.get("equipment")
        if general_equipment:
            if isinstance(general_equipment, list):
                lines.append(
                    f"- General Equipment (always available): {', '.join(general_equipment)}"
                )
            else:
                lines.append(f"- General Equipment (always available): {general_equipment}")

        weekly_schedule = profile.get("weekly_schedule")
        if weekly_schedule:
            lines.append("- Weekly Availability & Equipment:")
            days_order = [
                "Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday", "Sunday"
            ]
            for day in days_order:
                day_key = next((k for k in weekly_schedule if k.lower() == day.lower()), None)
                if not day_key:
                    lines.append(f"  * {day}: No availability configured")
                    continue
                day_data = weekly_schedule[day_key]
                if isinstance(day_data, dict):
                    hours = day_data.get("total_available_hours", 0.0)
                    max_sessions = day_data.get("max_sessions", 1)
                    cert = day_data.get("certainty_percent", 100)
                    equip = day_data.get("equipment", [])
                    equip_str = f" (Equipment: {', '.join(equip)})" if equip else ""
                    lines.append(
                        f"  * {day}: {hours} hours | "
                        f"Max sessions: {max_sessions} | "
                        f"Certainty: {cert}%{equip_str}"
                    )
                else:
                    lines.append(f"  * {day}: {day_data} hours")
        else:
            # weekly_schedule is optional — without one, say so explicitly rather than
            # leaving the coach to guess why no availability section appears.
            lines.append(
                "- Weekly Availability: no day-by-day schedule configured — any day can "
                "hold a session; size the week by the weekly target hours."
            )

        return "\n".join(lines)

    @staticmethod
    def _render_constraints(constraints: List[Constraint]) -> str:
        """Renders active directives for the prompt, one per line (DESIGN_constraints.md
        §6): `title | dates | [enforcement] | description`. A `rest` directive is already
        enforced deterministically before the LLM runs (the rest pre-pass forces those
        dates to rest), so it appears here only as context; every other directive is
        advisory prose the coach honors via judgement — the title says what to work
        around, and the LLM is trusted to honor it and choose any substitute itself."""
        lines = ""
        for c in constraints:
            desc = c.get('description') or ''
            enforcement = "no training (rest enforced)" if c.get('rest') else "advisory"
            lines += (
                f"- Constraint: {c['title']} | Dates: {c['start_date']} to {c['end_date']} | "
                f"{enforcement}"
                + (f" | Details: {desc}" if desc else "") + "\n"
            )
        return lines

    def _render_goal_lines(self, objectives: List[Objective]) -> str:
        """One `- Goal:` line per objective, the same everywhere goals reach a prompt.

        A horizon goal's date is tagged so every prompt carries what the date means,
        not just the planning task (ARCHITECTURE.md §15 "Goal dates")."""
        lines = ""
        for o in objectives:
            details = o.get('description', '')
            if o.get('date_type') == 'horizon':
                date_txt = (
                    f"around {o['target_date']} (a training horizon — "
                    "nothing is scheduled on this date)"
                )
            else:
                date_txt = str(o['target_date'])
            lines += (
                f"- Goal: {o['title']} | Date: {date_txt} | "
                f"Sport: {o['sport_type']} | Details: {details}\n"
            )
        return lines

    def _build_system_prompt(
        self, objectives: List[Objective], constraints: List[Constraint],
        guidelines: str, strategy: str, meso_text: str, learnings: str,
        profile: Optional[Dict[str, Any]], custom_task: str = ""
    ) -> str:
        """Constructs the system prompt with sports science guidelines and athlete details.

        Sections are marked `## NAME`; `custom_task` supplies `## TASK` and everything under
        it. The one hierarchy every prompt in the app follows: DESIGN_prompt_structure.md §2.
        """
        obj_text = self._render_goal_lines(objectives)

        c_text = self._render_constraints(constraints)

        athlete_profile = self._format_athlete_profile(profile)
        # weekly_schedule is optional; don't instruct adherence to a schedule that isn't there.
        if (profile or {}).get("weekly_schedule"):
            availability_rule = """\
5. Adhere to the day-by-day weekly availability schedule and day-dependent equipment access
   (e.g., do not schedule gym workouts on home-only days; do not schedule workouts on rest days;
   do not exceed daily availability or max sessions). Respect certainty percentages (higher
   values indicate more rigid constraints; lower values allow flexibility)."""
        else:
            availability_rule = """\
5. No day-by-day availability schedule is configured: place sessions on whichever days serve
   the plan best, within the weekly target hours and the active constraints."""
        system_prompt = f"""You are Stamind Coach, an advanced AI sports science training coach.
You design and adapt personalized training plans for endurance athletes using sports science
principles.

## COACHING ROLE AND OBJECTIVES
1. Design periodized training plans (macro, meso, micro cycles) leading up to the target goals.
2. Focus scheduling on the NEXT CHRONOLOGICAL GOAL only. If there are multiple goals, identify
   synergies between them (e.g. general base or strength building phases).
3. Dynamically adjust the scheduled sessions based on recent Garmin metrics (Resting HR, HRV, Sleep,
   and the PMC CTL/ATL/TSB) to optimize recovery and prevent injury.
4. Shift or scale training volume and intensity around the athlete's active constraints
   (travel, injury, capacity/intensity caps, preferences) to manage fatigue and respect
   what they've asked you to work around.
{availability_rule}

{guidelines}

## COACH LEARNINGS & ACTIVE PERIODIZATION STRATEGY
- Established Training Strategy for the current macro-cycle:
{strategy}
- Mesocycles making up the macro-cycle:
{meso_text}
- Athlete-Specific Observations (reference by [id] when revising or retiring):
{learnings}

## ATHLETE PROFILE & PREFERENCES
{athlete_profile}

## ACTIVE ATHLETE GOALS (CHRONOLOGICAL)
{obj_text if obj_text else "No active goals."}

## ACTIVE CONSTRAINTS (athlete-declared directives to work around)
{c_text if c_text else "No active constraints."}

## WRITING FOR THE ATHLETE
Your prose is read on a phone, by one athlete who is already looking at the numbers and the
sessions this command prints beside your words. Write accordingly:
- Lead with the decision. No preamble, no restating the question, no summing up at the end.
- Name only the signals that actually drove it. Do not re-list metrics, dates, or session
  details that are already on the athlete's screen.
- Say a thing once. A rationale that reads well after deleting half its words was twice as
  long as it needed to be.
Any length limit stated on a field in RESPONSE FORMAT is a hard limit, not a target. This
section governs rationale and summary prose only: a workout "description" is the
prescription the athlete trains from, and stays as complete as the session requires.

{custom_task}
"""
        return system_prompt
