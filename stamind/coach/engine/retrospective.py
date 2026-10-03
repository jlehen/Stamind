"""The retrospective writer: the one model call that writes a record's lines and the
sentence for the athlete (DESIGN_cycle_retrospective.md §5).

It gets no science documents and no profile: only what the mesocycle, or the plan, was for
and what was measured in its days.
"""
from typing import Any, Dict, List, Optional, Sequence

import stamind.coach.engine as _eng
from stamind.coach.formatting import format_daily_signals, format_standing_workouts
from stamind.db.retrospectives import CALLED_OFF, FINISHED, PLAN, REPLACED
from stamind.types import Constraint, Workout

# What the writer is asked to keep the record lines within, per level (§2).
RECORD_LIMITS = {"mesocycle": 400, "plan": 600}

HOW_IT_ENDED = {
    FINISHED: "It reached its end date.",
    REPLACED: "It was cut short: a new version of the plan replaced it on the day after "
              "its last day.",
    CALLED_OFF: "It was cut short: the athlete called the goal off on the day after its "
                "last day.",
}

WRITER_SYSTEM_PROMPT = """You are Stamind Coach, an AI endurance coach.
You keep the record of a {what} that has ended.

## TASK
The user message describes one {what}: what it was for, and what was measured in its days.
Write two things about it.

"record" is three short lines for a coach who plans a later season and was not there:
- "For: " what the {what} was meant to do.
- "Happened: " what was trained, and why where a reason is stated.
- "Came out: " what had changed for the athlete by its end.
It is a record and nothing else. Give no advice and no recommendation: the next goal is not
known here.
State a reason only when the user message states it: a constraint, a signal, the athlete's
words, or what the athlete said about a session. Never guess why a week came in low. Say
that it did.
Do not repeat the totals of sessions, hours and load: they are stored beside your lines.
Keep the three lines within {limit} characters in all.

"athlete_line" is one sentence said to the athlete about how this {what} went:
- Plain words, as said to a friend. No jargon.
- No numbers.
- Nothing private. It can appear on a lock screen, so no health detail and no reason for a
  week that came in low.
- Never open with a miss. Start from what was done.
- Never contradict THE ATHLETE'S WORDS, when the user message holds that section.

## RESPONSE FORMAT
You MUST respond with a JSON object containing:
{{
  "record": "For: ...\\nHappened: ...\\nCame out: ...",
  "athlete_line": "The one sentence for the athlete."
}}
"""


def _section(name: str, body: str) -> str:
    return f"## {name}\n{body.strip()}\n"


class RetrospectiveWriterMixin:
    """Part of :class:`CoachEngine` — see coach/engine/__init__.py."""

    def _retrospective_writer(
        self, record: Dict[str, Any], today_str: str,
        measured: str = "",
        constraints: Sequence[Constraint] = (),
        signals: Sequence[Dict[str, Any]] = (),
        spoken_workouts: Sequence[Workout] = (),
        mesocycle_records: str = "",
        wait_notice: Optional[str] = None,
    ) -> Dict[str, Any]:
        """Asks the model for a record's lines and its sentence for the athlete.

        A mesocycle record is sent with `measured`, `constraints`, `signals` and
        `spoken_workouts`; a plan record with `mesocycle_records`, the text of the records
        it covers. `wait_notice` is set only when the athlete has just answered and is
        waiting for the reply."""
        is_plan = record['level'] == PLAN
        what = "training plan" if is_plan else "mesocycle"
        described = (
            f"{record['name']} ({record['start_date']} to {record['end_date']})\n"
            f"{HOW_IT_ENDED[record['ended_by']]}\n"
        )
        if is_plan:
            sections = [
                _section("THE PLAN", f"Goal: {described}Strategy: {record['intent']}"),
                _section("ITS MESOCYCLES", mesocycle_records or "None on record."),
            ]
        else:
            sections = [
                _section("THE MESOCYCLE", f"{described}Description: {record['intent']}"),
                _section("WHAT WAS MEASURED", measured or "Nothing was recorded."),
                _section(
                    "CONSTRAINTS AND SIGNALS IN THOSE WEEKS",
                    self._retrospective_context(constraints, signals),
                ),
            ]
            if spoken_workouts:
                sections.append(_section(
                    "SESSIONS THE ATHLETE SPOKE ABOUT",
                    format_standing_workouts(list(spoken_workouts), eval_date=today_str),
                ))
        if record['athlete_words']:
            sections.append(_section(
                "THE ATHLETE'S WORDS",
                "The athlete's answer to \"how did it go?\", as typed:\n"
                f"\"{record['athlete_words']}\"",
            ))
        user_content = (
            f"Today's date is {today_str}. Please write the record of this {what}.\n\n"
            + "\n".join(sections)
        )
        return _eng.openrouter_client.complete(
            WRITER_SYSTEM_PROMPT.format(what=what, limit=RECORD_LIMITS[record['level']]),
            user_content, label="retrospective_writer", wait_notice=wait_notice,
        )

    def _retrospective_context(
        self, constraints: Sequence[Constraint], signals: Sequence[Dict[str, Any]]
    ) -> str:
        """The constraints and the daily signals stored for the record's days."""
        parts: List[str] = []
        if constraints:
            parts.append(self._render_constraints(list(constraints)).rstrip())
        if signals:
            parts.append(format_daily_signals(list(signals)))
        return "\n".join(parts) or "None stored for those days."
