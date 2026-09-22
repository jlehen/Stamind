"""The athlete's voice, on top of the expert one (DESIGN_render_persona.md §2, §3).

`CompanionRenderer` extends `ExpertRenderer`, so the set of methods it overrides IS the
list of surfaces companion mode has opted into; anything it does not override falls back
to the expert form. Each override is the *when* — which line builder in
`session_lines.py` or `plan_lines.py` says this, and with what."""
from typing import Any, Dict, List, Optional, Tuple

from stamind import runtime
from stamind.analytics import timeline
from stamind.analytics.adherence import MINOR, unplanned_kind
from stamind.coach.proposals import RevisionProposal
from stamind.config import config
from stamind.sentinels import emit_buttons
from stamind.strength.prescription import exercise_lines
from stamind.text import green, wrap_text
from stamind.output import notice
from stamind.clock import today_date as _today_date, today_str as _today_str
from stamind.cli.common import print_strength_notes
from stamind.cli.progress import emit_chart
from stamind.cli.render.expert import ExpertRenderer
from stamind.cli.render.plan_lines import (
    SIMPLE_NO_PLAN_LINE, simple_end_buttons, simple_end_note, simple_goal_line,
    simple_goal_lines, simple_mesocycle_buttons, simple_metric_words, simple_plan_lines,
    simple_plan_setup_line, simple_plan_shaping_line, simple_plan_wrapped_line,
    simple_progress_lines, simple_queue_message, simple_runway_lines,
)
from stamind.cli.render.session_lines import (
    SIMPLE_SESSION_RULE, simple_compare_lines, simple_day_lines, simple_revision_lines,
    simple_span_words, simple_week_lines,
)


class CompanionRenderer(ExpertRenderer):
    """The athlete's voice: prose, day words, no IDs, no commands they cannot type.

    Overrides only what it words differently; everything else falls through to the
    expert form, which is what makes that fallback structural rather than a discipline
    (DESIGN_bot_simple_frontend.md §6). Tone rule: lead with what is next, state gaps as
    neutral facts after the lead, never open with a miss."""

    # -- workout adapt --

    def adapt_reason(self, reason: str) -> None:
        # No report header: the reason is already prose.
        print(f"\n{wrap_text(reason)}")

    def adapt_no_change(self) -> None:
        print(green("\nAll clear — the plan stands as it is. 💪"))

    def tweak_no_change(self) -> None:
        print("\nSo I left your week as it is.")

    def adapt_confirm_words(self) -> Tuple[str, str]:
        return "Here's what I'd change:", "Shall I make these changes?"

    def adapt_discarded(self) -> None:
        print("\nOkay — nothing changed.")

    def adapt_applied(self) -> None:
        print(green("Done — your week is updated. 💪"))

    # -- confirming a note's candidates --
    # The companion's main felt surface once notes stop riding the coach: she says
    # something, and this is what asks before anything is stored
    # (DESIGN_bot_simple_frontend.md §12.3). Day words, no IDs, no ISO spans (§6).

    def constraint_candidate_question(
        self, title: str, start: str, end: str, today: str
    ) -> str:
        return f"Shall I remember that? “{title}” — {simple_span_words(start, end, today)}"

    def constraint_captured(
        self, constraint_id: int, title: str, start: str, end: str, today: str
    ) -> None:
        print(green("Noted — I'll work around that 👍"))

    def constraint_candidate_discarded(self) -> None:
        print("Okay — I won't note that one.")

    def constraints_open_ended(self, titles: List[str], text: str) -> None:
        """One forwardable message: her words are quoted so a Telegram forward carries
        the rule to the operator without retyping (§12.3, 2026-09-16)."""
        print(wrap_text(
            "That sounds like a rule, not something for the next few days. Ask "
            f"{config.telegram_operator_name} to record this in your preferences for "
            "good. You can just forward this message:"
        ))
        print()
        print(f"“{text.strip()}”")

    def constraint_plan_shaping(self, constraint_id: int, impact: Dict[str, Any]) -> None:
        """The same fact, without the commands: reshaping the plan around it is one tap
        away on the offer that follows this capture, and `plan generate` is operator work
        the athlete cannot run (DESIGN_bot_simple_frontend.md §12.10)."""
        print(wrap_text(simple_plan_shaping_line(impact)))

    def signal_candidate_question(
        self, metric: str, value: Optional[float], start: str, end: str, today: str,
        *, new_category: bool,
    ) -> str:
        words = simple_metric_words(metric)
        shown = "" if value is None else f" ({value:g})"
        when = simple_span_words(start, end, today)
        if new_category:
            # The ladder's second rung still reads as one question, but says plainly that
            # this is a kind of note she has not logged before (§6 of the signal design).
            return f"That's a new one for me — log it as “{words}”{shown}, {when}?"
        return f"Shall I log that? “{words}”{shown} — {when}"

    def signal_logged(
        self, metric: str, days: int, start: str, end: str, today: str
    ) -> None:
        print(green("Logged — thanks for telling me 👍"))

    def signal_candidate_discarded(self) -> None:
        print("Okay — I won't log that one.")

    def signal_not_logged(self, metric: str) -> None:
        print("Hmm — that didn't save. Tell me again in a bit?")

    # -- listings --

    def workout_list(
        self, workouts: list, verdicts: dict, args, *, start_date: Optional[str],
        end_date: Optional[str], ids: list, names_a_range: bool,
    ) -> None:
        # A single-day window reads as the day, any other window as the week ahead
        # (DESIGN_bot_simple_frontend.md §6).
        if start_date and start_date == end_date:
            for line in simple_day_lines(workouts, start_date, verdicts):
                print(line)
            return
        for line in simple_week_lines(
            workouts, verdicts,
            end_note=simple_end_note(end_date) if names_a_range else None,
        ):
            print(line)
        # The note states that the schedule stops; the button is what she does about it,
        # offered where she is already looking (DESIGN_runway_nudge.md §6).
        buttons = simple_end_buttons(end_date) if names_a_range else []
        if buttons:
            emit_buttons(buttons)

    def workout_generate_preview(self, proposal) -> bool:
        # The sessions render the way her week view does — the runway button makes this
        # preview reachable by tap, so it must not be a table (DESIGN_runway_nudge.md §6).
        print(f"\n{wrap_text(proposal.reasoning)}\n")
        if not proposal.workouts:
            notice("The coach proposed no sessions — nothing to apply.")
            return False
        for line in simple_week_lines(list(proposal.workouts)):
            print(line)
        # The kilograms are what the athlete is being asked to accept on a gym day, so they
        # are shown here too (DESIGN_strength_tracking.md §9).
        for w in proposal.workouts:
            for line in exercise_lines(w.get('prescribed_sets') or []):
                print(f"   {line}")
        print_strength_notes(proposal)
        print()
        return True

    def workout_compare(
        self, days: list, *, start_date: str, end_date: str, sport_filter: Optional[str],
        discrepancies: list, informational: list, covered_ranges: list,
    ) -> None:
        # The discrepancy list, the load-from-RPE note and the in-mesocycle/off-plan
        # distinction are expert detail: the glyph on each line is the whole verdict here,
        # and an effort under the minor-load bar is not mentioned at all
        # (DESIGN_bot_simple_frontend.md §6). It asks the same question the expert view
        # asks; it just keeps two of the three answers apart only on screen.
        kept = []
        for date_str, results, unplanned in days:
            worth_a_line = [
                a for a in unplanned
                if unplanned_kind(
                    a, date_str, covered_ranges, config.minor_activity_load_threshold
                ) != MINOR
            ]
            if results or worth_a_line:
                kept.append((date_str, results, worth_a_line))
        for line in simple_compare_lines(kept, start_date, end_date, _today_str()):
            print(line)

    def calendar_marked(self, marked: int) -> None:
        # Bookkeeping on the operator's Calendar; chat is not the audit surface (§6).
        return

    def goal_list(self, goals: list, called_off: list, show_all: bool, today: str) -> None:
        for line in simple_goal_lines(goals, today):
            print(line)

    def plan(self, goal: dict, macrocycle: dict, args) -> None:
        mesocycles = runtime.db.get_mesocycles_for_macrocycle(macrocycle['id'])
        today = _today_date().strftime("%Y-%m-%d")
        for line in simple_plan_lines(goal, macrocycle, mesocycles, today):
            print(line)
        # The road names the mesocycles; the button is how she reads one in full (§11.2).
        # Only for the version in force — an older version's mesocycles are history.
        if macrocycle.get("status") != "superseded":
            buttons = simple_mesocycle_buttons(mesocycles, today)
            if buttons:
                emit_buttons(buttons)

    def progress(self, payload: dict, args, today: str, weeks_window: int) -> None:
        lines = simple_progress_lines(payload, today)
        for line in lines:
            print(wrap_text(line))
        chart_arg = getattr(args, "chart", False)
        if not chart_arg:
            return
        # The chart captions itself with the trend line, where the expert form captions
        # it with the table's first row (DESIGN_bot_simple_frontend.md §6).
        emit_chart(
            chart_arg,
            timeline.clip_payload_for_weeks(
                payload, weeks_window, today, cap_future=True
            ),
            lines[0],
        )

    def revision_preview(self, proposal: RevisionProposal, heading: str) -> None:
        print(f"\n{heading}")
        for index, entry in enumerate(simple_revision_lines(proposal)):
            if index:
                print(f"\n{SIMPLE_SESSION_RULE}")
            print(f"\n{entry}")
        # The kilograms not being rechecked is hers to know too, in the same words
        # (DESIGN_strength_tracking.md §9).
        if proposal.strength_notice:
            print(f"\n{wrap_text(proposal.strength_notice)}")

    # -- goals a tap can reach --

    def goal_row(self, goal: dict, today: str) -> None:
        from stamind.db.objectives import GOAL_ARCHIVED, goal_state
        # An archived goal was called off and says nothing at all in companion mode
        # (§11 tone rule) — the sentence that follows is the whole of what she hears.
        if goal_state(goal, today) == GOAL_ARCHIVED:
            return
        print(simple_goal_line(goal, today))

    def goal_added(self) -> None:
        print(green("All set 🎯"))
        print(wrap_text(simple_plan_setup_line()))

    def goal_updated(self) -> None:
        print(green("Done — that's updated 👍"))

    def goal_stood_down(self, archived: dict) -> None:
        if archived.get('archived_workouts'):
            print(wrap_text(
                "I've cleared the sessions that were building toward it — nothing else "
                "on your schedule changes."
            ))

    def goal_called_off(self, goal: dict, archived: dict, today: str) -> None:
        # The tone rule does the mourning: this is the last time she hears about it, and
        # nothing here names the reinstate command, which is the operator's (§12.6).
        print(green(f"Okay — {goal['title']} is off the list."))
        self.goal_stood_down(archived)

    # -- constraints an edit can reach --

    def constraint_replan_offer(self, impact: Dict[str, Any]) -> Optional[str]:
        print(wrap_text(simple_plan_shaping_line(impact)))
        return None

    def constraint_honor_hint(self, constraint_id: int) -> None:
        """Draws nothing: every route it names — `workout generate`, `plan generate` —
        is operator work the athlete cannot run (§12.9). The same shape as
        `runway_hint`, and for the same reason."""

    # -- settings --

    def setting_changed(self, name: str, stored: str, before: str) -> None:
        # The confirm already read the change back as its effect; this only says it took
        # (DESIGN_bot_simple_frontend.md §12.7).
        print(green("Done — that's set 👍" if stored != before
                    else "That's already how it is 👍"))

    # -- a doubted learning's answer --

    def learning_kept(self, learning: Dict[str, Any]) -> None:
        print(green("Thanks — good to know, I'll keep that in mind."))

    def learning_demoted(self, learning_id: int, result: Optional[str]) -> None:
        if result == "retired":
            print(green("Got it — I've set that idea aside."))
            return
        print(green("Got it — I'll lean on that less."))

    # -- one-liners --

    def constraint_removed(self, constraint_id: int) -> None:
        print(green("Done — I've dropped that one and will stop working around it 👍"))

    def no_upcoming_goal(self) -> None:
        print(SIMPLE_NO_PLAN_LINE)

    def no_plan_yet(self, goal: dict) -> None:
        print(SIMPLE_NO_PLAN_LINE)

    def runway_hint(self, state: Optional[Dict[str, Any]], today: str) -> None:
        """Draws nothing: the companion week view and the morning push word this fact
        themselves, and one fact gets one wording per message
        (DESIGN_runway_nudge.md §6)."""

    def adapt_plan_behind(self, state: Optional[Dict[str, Any]], today: str) -> None:
        # The morning push's plan-cliff wording, reached from adapt: the sentence
        # already exists, it just was not reachable from here
        # (DESIGN_render_persona.md §5).
        lines = simple_runway_lines(state, today) if state else [
            simple_plan_wrapped_line()
        ]
        for line in lines:
            print(wrap_text(line))

    def queue_hint(self, questions: int, messages: int) -> None:
        """Draws nothing: the morning message brings the questions, and a hint about a
        command she cannot type is noise (DESIGN_athlete_queue.md §5.2)."""

    def queue_message(
        self, item: Dict[str, Any], left: Optional[int]
    ) -> Tuple[str, List[dict]]:
        return simple_queue_message(item, left)

    def queue_acted(self, item: Dict[str, Any], action: str, line: Optional[str]) -> None:
        """Only the kind's own line: the tapped message already shows her choice
        (DESIGN_athlete_queue.md §6.1)."""
        if line:
            print(wrap_text(line))
