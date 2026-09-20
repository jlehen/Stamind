"""`workout adapt` and `workout tweak`: today's recovery metrics, or the athlete's own
words, change the days ahead.

Both walk the same flow — freshen the data, settle any pairing the matcher guessed at, ask
the week planner, show what it proposes, apply it — so they share one private `_adapt`.
A tweak is that flow with a narrower job (DESIGN_workout_tweak.md §3.2).
"""
import argparse
from datetime import datetime, timedelta
from trainmate import athlete_queue, runtime
from trainmate.analytics.compare import format_actual
from trainmate.config import config
from trainmate.text import gray, red
from trainmate.output import notice, step, warn
from trainmate.clock import fmt_date, today_str as _today_str
from trainmate.cli.candidates import confirm_new_constraints, confirm_new_signals
from trainmate.cli.common import ensure_recent_data
from trainmate.cli.runway import current_runway, plan_is_behind
from trainmate.cli.workouts.heads_up import (
    print_send_notice, replacing_unsent, revision_dates,
)
from trainmate.cli.workouts.session_line import workout_line


def _resolve_ambiguous_matches(date_str: str, auto: bool) -> None:
    """Asks the athlete about any pairing the matcher had to guess at, before the week planner
    is told a session was performed (ARCHITECTURE.md §15).

    Skipped under `--auto` and on any non-interactive run, which then falls back to the
    matcher's own answer — the question is a refinement, never a gate.
    """
    if auto:
        return
    try:
        questions = runtime.coach_service.pending_match_questions(date_str)
    except Exception as e:
        warn(f"could not check activity matching: {e}")
        return
    if not questions:
        return

    for q in questions:
        planned, act = q["planned"], q["completed"]
        # The pairing travels *inside* the question, not in a preceding `step`: an aside is
        # suppressed on the chat front-end, which left Telegram asking "was that the
        # session, cut short?" about nothing at all (DESIGN_output_verbosity.md §3.4).
        # Each side is rendered by its own surface formatter, so the two lines are read in
        # the same units: a hand-rolled "at 66m" was read as GPS distance, not minutes.
        accepted = runtime.prompt.confirm(
            f"\nPlanned: {workout_line(planned)}\n"
            f"Only matching activity: {format_actual(act)} — far short of it.\n"
            "Was that the session, cut short? (No = it was something else, "
            "e.g. a warm-up to discard)", default=False
        )
        runtime.coach_service.record_match_decision(
            q["activity_id"], q["sport"], accepted
        )
        if accepted:
            print(gray("  Counted as that session, partially performed."))
        else:
            print(gray("  Discarded — the session reads as not done."))


def run_workout_adapt(args: argparse.Namespace) -> None:
    # Executes the daily workout Garmin adaptation checks command.
    with replacing_unsent(skip=args.auto):
        _adapt(args)


def run_workout_tweak(args: argparse.Namespace) -> None:
    """Changes the days a request is about: `workout adapt`'s flow with a narrower job
    (DESIGN_workout_tweak.md §3)."""
    with replacing_unsent(skip=args.auto):
        _adapt(args, tweak=True)


def _adapt(args: argparse.Namespace, tweak: bool = False) -> None:
    # A tweak's `--date` names the days to change; the run itself is evaluated today.
    date_str = _today_str()
    if not tweak and args.date:
        date_str = args.date
    elif not tweak:
        # Name the defaulted target so a bare `adapt` isn't silent (DESIGN_cli_noargs.md §b).
        step(f"No date given — adapting today ({fmt_date(date_str)}).")

    ensure_recent_data(
        date_str, no_pull=args.no_pull, force_pull=getattr(args, 'force_pull', False)
    )

    # The week planner reads the full per-day trajectory (HRV/RHR/sleep/PMC) from the same
    # window; here we only tell the athlete how many days fed the decision, not the numbers.
    try:
        history_days = getattr(args, "lookback", None) or config.metrics_lookback_days
        date_obj = datetime.strptime(date_str, "%Y-%m-%d").date()
        start_date = (date_obj - timedelta(days=history_days - 1)).strftime("%Y-%m-%d")
        metrics_history = runtime.db.get_metrics_cache(start_date=start_date, end_date=date_str)
        step(f"\nUsing {len(metrics_history)} days of recovery metrics "
             f"(past {history_days}-day window).")
    except Exception as e:
        warn(f"could not load metrics trajectory: {e}")

    state = current_runway(date_str)
    if plan_is_behind(date_str):
        # Nothing to adapt *towards* once the whole periodization is behind us — say what
        # to do instead of an all-clear over an empty calendar (DESIGN_runway_nudge.md §4,
        # extending DESIGN_mesocycle_boundary.md §6's "adapt requires a mesocycle").
        runtime.render.adapt_plan_behind(state, date_str)
        runtime.render.queue_hint(*athlete_queue.waiting_counts())
        return
    runtime.render.runway_hint(state, date_str)
    # What waits in the athlete queue shares that place (DESIGN_athlete_queue.md §5.2).
    runtime.render.queue_hint(*athlete_queue.waiting_counts())

    # Before the week planner is told anything: settle any pairing the matcher had to guess at.
    _resolve_ambiguous_matches(date_str, auto=args.auto)

    try:
        if tweak:
            step("Asking the coach for the change...")
            proposal = runtime.coach_service.workout_tweak(
                args.message, tweak_dates=args.date or (), today_str=date_str
            )
        else:
            step(f"Evaluating daily Garmin metrics adaptation for {fmt_date(date_str)}...")
            proposal = runtime.coach_service.workout_adapt(
                date_str, message=getattr(args, 'message', None)
            )
        reason = proposal.reason
        proposed_workouts = proposal.workouts

        # §8 two-confirmation flow, step 1: confirm any constraint(s) extracted from the
        # athlete's note BEFORE the adaptation preview below — an independent commit that
        # runs even when no workout changes are proposed. Declining discards the
        # extraction; the note still informed this run's adaptation via the advisory text
        # (already baked into `reason`/`proposed_workouts` from the same LLM call).
        # Step 1b: the same note may also carry daily signals, confirmed one at a time and
        # written the same way (DESIGN_signal_extraction.md §2). A signal confirmed here
        # informs the NEXT run, not this one — the call that proposed it has returned.
        # Both loops live in cli/candidates.py: `bot capture note` asks the same questions
        # about the same candidates (DESIGN_bot_simple_frontend.md §12.10).
        confirm_new_constraints(
            proposal.new_constraints, date_str, getattr(args, 'message', None) or ""
        )
        confirm_new_signals(proposal.new_signals, date_str)

        runtime.render.adapt_reason(reason)

        if not proposed_workouts and tweak:
            runtime.render.tweak_no_change()
        elif not proposed_workouts:
            runtime.render.adapt_no_change()
        if not proposed_workouts:
            # The pass still had its constraints in scope, which is all `honored_at`
            # claims — requiring a *change* would flag them forever (§8).
            runtime.coach_service.workout_revision_record_no_change(proposal)
            return
        print_send_notice(revision_dates(proposal))

        # The renderer draws the preview, the prompt asks the question: voice and
        # transport are two objects and neither calls the other
        # (DESIGN_render_persona.md §4).
        heading, question = runtime.render.adapt_confirm_words()
        runtime.render.revision_preview(proposal, heading)
        if not (args.auto or runtime.prompt.confirm(question)):
            runtime.render.adapt_discarded()
            return

        step("\nApplying adaptations...")
        runtime.coach_service.workout_revision_apply(proposal)
        runtime.render.adapt_applied()

    except ValueError as e:
        # A domain refusal (no active plan to adapt towards), not a failure: say it
        # plainly. Anything else belongs to the entry point's error boundary.
        notice(str(e), red)
