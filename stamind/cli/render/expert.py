"""The default voice: reports, tables, IDs, operator nudges
(DESIGN_render_persona.md §4).

One method per thing a command has to say. The tables themselves stay in the command
modules and this class delegates to them (§7 step 3), so the import runs one way: this
file reaches into the commands, and a command reaches this voice only through
`runtime.render`."""
from datetime import datetime
from typing import Any, Dict, List, Optional, Tuple

from stamind.coach.proposals import RevisionProposal
from stamind.text import bold, cmd, dim, green, wrap_text
from stamind.output import notice
from stamind.cli.goals import print_goal_row, print_goal_table, report_archived_sessions
from stamind.cli.learnings import print_learning_demoted, print_learning_kept
from stamind.cli.plans.generate import print_plan_generate_preview
from stamind.cli.plans.show import print_plan
from stamind.cli.progress import print_progress_report
from stamind.cli.queue import (
    print_closed_queue_list, print_queue_acted, print_queue_list, queue_chat_message,
    queue_hint_lines,
)
from stamind.cli.runway import runway_hint_lines
from stamind.cli.render.calendar_grid import month_lines
from stamind.cli.workouts.compare import print_calendar_marked, print_workout_compare
from stamind.cli.workouts.generate import print_generate_preview
from stamind.cli.workouts.listing import print_workout_table
from stamind.cli.workouts.revisions import print_revision_preview


def _iso_span(start: str, end: str) -> str:
    """A window the expert way — one date, or `start..end`, the form the candidate
    confirms have always asked in."""
    return start if start == end else f"{start}..{end}"


class ExpertRenderer:
    """The default voice: reports, tables, IDs, operator nudges.

    One method per thing a command has to say, never per sentence and never per
    command (§4). A method may read what the code it wraps reads; it may not judge —
    no coaching decision belongs in a formatter (DESIGN_bot_simple_frontend.md §10)."""

    # -- workout adapt (cli/workouts/adapt.py) --

    def adapt_reason(self, reason: str) -> None:
        print(f"\n{bold('Decision Summary')}:\n{wrap_text(reason)}")

    def adapt_no_change(self) -> None:
        print(green(
            "\nAll metrics are green and the schedule is on track. "
            "No changes recommended."
        ))

    def tweak_no_change(self) -> None:
        print("\nNothing was changed.")

    def adapt_confirm_words(self) -> Tuple[str, str]:
        """The preview's heading and the question that follows it. The renderer only
        supplies the words; `runtime.prompt` asks (§4)."""
        return (
            "PROPOSED WORKOUT ADAPTATIONS:",
            "Apply these adaptations to your schedule and sync to Calendar?",
        )

    def adapt_discarded(self) -> None:
        print("\nAdaptations discarded.")

    def adapt_applied(self) -> None:
        print(green("Adaptations applied and synced to calendar successfully."))

    # -- confirming a note's candidates (cli/candidates.py) --

    def constraint_candidate_question(
        self, title: str, start: str, end: str, today: str
    ) -> str:
        return f"Add constraint: {title} ({_iso_span(start, end)})?"

    def constraint_captured(
        self, constraint_id: int, title: str, start: str, end: str, today: str
    ) -> None:
        print(green(
            f"Captured constraint [{constraint_id}]: {title} ({_iso_span(start, end)})"
        ))

    def constraint_candidate_discarded(self) -> None:
        print("Discarded — not saved as a constraint.")

    def constraints_open_ended(self, titles: List[str], text: str) -> None:
        """A rule with no time bound has no home in the constraints table; the profile is
        where it belongs (DESIGN_bot_simple_frontend.md §12.3, 2026-09-16)."""
        quoted = ", ".join(f"“{t}”" for t in titles)
        notice(
            f"Not saved: {quoted} — a rule for good, not a dated constraint. Record it "
            "in config.yaml under user_profile.preferences, or the weekly schedule."
        )

    def constraint_plan_shaping(self, constraint_id: int, impact: Dict[str, Any]) -> None:
        """What a capture says when the directive it just stored is big enough to
        reshape the plan (DESIGN_constraints.md §7). Names the escalation commands,
        which is the operator's next step and no one else's."""
        notice(
            f"  This looks plan-shaping ({impact['days']} days, displaces "
            f"~{impact['displaced_pct']:.0f}% of a typical week). To build it into "
            "the plan, run " + cmd(f"constraint edit {constraint_id} --replan")
            + " or " + cmd("plan generate") + ".",
        )

    def signal_candidate_question(
        self, metric: str, value: Optional[float], start: str, end: str, today: str,
        *, new_category: bool,
    ) -> str:
        shown = "" if value is None else f" = {value}"
        span = _iso_span(start, end)
        if new_category:
            return f"Log as NEW category '{metric}'{shown} on {span}?"
        return f"Log signal: {metric}{shown} on {span}?"

    def signal_logged(
        self, metric: str, days: int, start: str, end: str, today: str
    ) -> None:
        print(green(
            f"Logged {metric} ({days} day{'s' if days != 1 else ''}, "
            f"{_iso_span(start, end)})."
        ))

    def signal_candidate_discarded(self) -> None:
        print("Discarded — not logged as a signal.")

    def signal_not_logged(self, metric: str) -> None:
        notice(f"Could not log '{metric}' — no calendar write succeeded.")

    # -- listings --

    def workout_list(
        self, workouts: list, verdicts: dict, args, *, start_date: Optional[str],
        end_date: Optional[str], ids: list, names_a_range: bool,
    ) -> None:
        print_workout_table(
            workouts, verdicts, args, start_date=start_date, end_date=end_date,
            ids=ids, names_a_range=names_a_range,
        )

    def plan_generate_preview(self, proposal: dict) -> None:
        """Draws the periodization about to be applied, and the review behind it."""
        print_plan_generate_preview(proposal)

    def workout_generate_preview(self, proposal) -> bool:
        """Draws the proposal; False when there is nothing to apply."""
        return print_generate_preview(proposal)

    def workout_compare(
        self, days: list, *, start_date: str, end_date: str, sport_filter: Optional[str],
        discrepancies: list, informational: list, covered_ranges: list,
    ) -> None:
        print_workout_compare(
            days, start_date=start_date, end_date=end_date, sport_filter=sport_filter,
            discrepancies=discrepancies, informational=informational,
            covered_ranges=covered_ranges,
        )

    def calendar_marked(self, marked: int) -> None:
        print_calendar_marked(marked)

    def goal_list(self, goals: list, called_off: list, show_all: bool, today: str) -> None:
        print_goal_table(goals, called_off, show_all)

    def plan(self, goal: dict, macrocycle: dict, args) -> None:
        print_plan(goal, macrocycle, args)

    def progress(self, payload: dict, args, today: str, weeks_window: int) -> None:
        print_progress_report(payload, args, today, weeks_window)

    def calendar_month(self, cal, year: int, month: int) -> None:
        # `sm calendar` has one voice: the companion reaches the page instead
        # (DESIGN_calendar_miniapp.md §2).
        for line in month_lines(cal, year, month):
            print(line)

    def revision_preview(self, proposal: RevisionProposal, heading: str) -> None:
        print_revision_preview(proposal, heading)

    # -- goals a tap can reach (DESIGN_bot_simple_frontend.md §12.5, §12.6) --

    def goal_row(self, goal: dict, today: str) -> None:
        """The goal as it now stands, after an add or an edit."""
        print_goal_row(goal)

    def goal_added(self) -> None:
        print(green("Goal added successfully. Run " + cmd("plan generate")
                    + " to generate training cycles."))

    def goal_updated(self) -> None:
        print(green("Goal updated successfully. Run " + cmd("plan generate")
                    + " to regenerate training cycles if needed."))

    def goal_stood_down(self, archived: dict) -> None:
        """What calling a goal off did to the schedule."""
        report_archived_sessions(archived)

    def goal_called_off(self, goal: dict, archived: dict, today: str) -> None:
        """`goal rm` in full — the row, what stood down, and the way back. Its own
        method rather than the three above in sequence because the companion says the
        whole of it in one sentence (§12.6)."""
        print_goal_row(goal)
        self.goal_stood_down(archived)
        print(green(
            "Goal called off. Its plan, versions and feedback are kept — "
            + cmd(f"goal edit {goal['id']} --status active") + " brings it back."
        ))

    # -- constraints an edit can reach (§12.4) --

    def constraint_replan_offer(self, impact: Dict[str, Any]) -> Optional[str]:
        """States a directive's magnitude and returns the question that offers to build
        it into the plan — or None where that escalation is not the reader's to make.

        Returning the question rather than asking it keeps voice and transport apart
        (§4); returning None is how the companion says the fact and stops, since
        `plan generate` is operator work (DESIGN_bot_simple_frontend.md §12.9)."""
        notice(
            f"This {impact['days']}-day constraint displaces "
            f"~{impact['displaced_pct']:.0f}% of a typical week's planned load."
        )
        return "Replan around it?"

    def constraint_honor_hint(self, constraint_id: int) -> None:
        """Where a plan-shaping directive lands, and what would build it in
        (DESIGN_constraint_honoring.md §4)."""
        from stamind.cli.constraints import point_at_honor
        point_at_honor(constraint_id)

    # -- settings (§12.7) --

    def setting_changed(self, name: str, stored: str, before: str) -> None:
        if stored == before:
            print(green(f"{name} is {stored} (unchanged)."))
            return
        print(green(f"{name} set to {stored}") + dim(f" — was {before}."))

    # -- a doubted learning's answer (DESIGN_learning_doubt_nudge.md §4) --

    def learning_kept(self, learning: Dict[str, Any]) -> None:
        print_learning_kept(learning)

    def learning_demoted(self, learning_id: int, result: Optional[str]) -> None:
        print_learning_demoted(learning_id, result)

    # -- one-liners --

    def constraint_removed(self, constraint_id: int) -> None:
        print(green(f"Constraint [{constraint_id}] removed."))

    def no_upcoming_goal(self) -> None:
        """`plan show`'s empty state — the sentence `selectors.resolve_goal` would print."""
        notice("No active goals found. Stamind needs at least one goal.")

    def no_plan_yet(self, goal: dict) -> None:
        notice(f"No active macrocycle strategy found for goal '{goal['title']}'.")
        print(green(f"Run {cmd('plan generate')} to create one."))

    def runway_hint(self, state: Optional[Dict[str, Any]], today: str) -> None:
        """The end-of-schedule nudge: the fact, then the exact command
        (DESIGN_runway_nudge.md §4)."""
        if not state:
            return
        print()
        for line in runway_hint_lines(state, today):
            notice(line)
        print()

    def adapt_plan_behind(self, state: Optional[Dict[str, Any]], today: str) -> None:
        """Why `workout adapt` refuses when the whole periodization is behind us
        (DESIGN_render_persona.md §5). The hint says it when the detector is still
        firing; past that window the refusal says it on its own."""
        if state:
            self.runway_hint(state, today)
            return
        notice(
            "Your plan is behind you — there is nothing left to adapt towards. Set "
            "what's next with " + cmd("goal add") + ", then " + cmd("plan generate")
            + "."
        )

    def queue_hint(self, questions: int, messages: int) -> None:
        """What waits in the athlete queue, in the runway hint's place and yellow
        (DESIGN_athlete_queue.md §5.2)."""
        lines = queue_hint_lines(questions, messages)
        if not lines:
            return
        print()
        for line in lines:
            notice(line)
        print()

    def queue_list(self, items: List[Dict[str, Any]], now: datetime) -> None:
        print_queue_list(items, now)

    def queue_closed_list(self, items: List[Dict[str, Any]], start: str, end: str) -> None:
        print_closed_queue_list(items, start, end)

    def queue_message(
        self, item: Dict[str, Any], left: Optional[int]
    ) -> Tuple[str, List[dict]]:
        """One queued item as a chat message: its text and its buttons
        (DESIGN_athlete_queue.md §6.1)."""
        return queue_chat_message(item, left)

    def queue_acted(self, item: Dict[str, Any], action: str, line: Optional[str]) -> None:
        print_queue_acted(item, action, line)
