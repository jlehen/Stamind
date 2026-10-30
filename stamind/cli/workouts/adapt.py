"""`workout adapt` and `workout tweak`: today's recovery metrics, or the athlete's own
words, change the days ahead.

Both walk the same flow — freshen the data, settle any pairing the matcher guessed at, ask
the week planner, show what it proposes, apply it — so they share one private `_adapt`.
A tweak is that flow with a narrower job (DESIGN_workout_tweak.md §3.2). A run started from
the athlete's chat does not ask and apply: it saves the proposal, sends it and ends
(DESIGN_waiting_proposal.md §2).
"""
import argparse
from datetime import datetime, timedelta
from typing import List, Optional
from stamind import athlete_queue, runtime
from stamind.coach.proposals import NOTE_SESSION_UNCLEAR
from stamind.config import config
from stamind.db.base import WeekHold
from stamind.prompt import Choice, athlete_watching
from stamind.sports import canonical_sport
from stamind.types import Workout
from stamind.text import red, wrap_text
from stamind.output import notice, step, warn
from stamind.clock import fmt_date, today_str as _today_str
from stamind.cli.candidates import (
    confirm_new_constraints, confirm_new_signals, keep_note, queue_candidates,
    queue_note_question, tell_open_ended,
)
from stamind.cli.common import ensure_recent_data
from stamind.cli.queue import send_alone, send_own_questions
from stamind.cli.runway import current_runway, plan_is_behind
from stamind.cli.workouts import cut_short, proposal as saved_proposal
from stamind.cli.workouts.heads_up import (
    Window, newest_written, print_send_notice, replacing_unsent, revision_dates, week_changed,
)


def _note_candidates(proposal, message: Optional[str]) -> List[Workout]:
    """The sessions that the athlete's note may be kept with, as the week planner read it:
    on the day it names, the one it names, every one when it cannot tell which, and none
    when the note is about something else (DESIGN_session_notes.md §3)."""
    day, about = proposal.note_date, proposal.note_session
    if not day or not about or not (message or "").strip():
        return []
    sessions = [
        w for w in runtime.db.get_workouts(start_date=day, end_date=day)
        if canonical_sport(w['sport_type']) != canonical_sport('rest')
    ]
    if about == NOTE_SESSION_UNCLEAR:
        return sessions
    return [w for w in sessions if canonical_sport(w['sport_type']) == canonical_sport(about)]


def _pick_note_session(sessions: List[Workout]) -> List[Workout]:
    """On a terminal: asks on the spot which of the day's sessions the note is about."""
    picked = runtime.prompt.choose(
        "Which session is this about?",
        [Choice(str(w['id']), w['title']) for w in sessions]
        + [Choice("none", "Not about a session")],
        default="none",
    )
    return [w for w in sessions if str(w['id']) == picked]


def _adapt_date(args: argparse.Namespace, tweak: bool) -> str:
    """The day the run is evaluated on: `workout adapt`'s `--date`, else today. A tweak's
    `--date` names the days to change, so the tweak itself is evaluated today."""
    if tweak or not args.date:
        return _today_str()
    return args.date


def _adapt_window(args: argparse.Namespace, tweak: bool) -> Window:
    """The days this run may write, for the replace question (DESIGN_change_heads_up.md §5).

    A tweak's `--date` names them outright. Every other run leaves its last day open: only
    the week planner's answer says which day it moved a session onto, and all it promises
    beforehand is that it changes nothing before the day it is evaluated on."""
    if tweak and args.date:
        return min(args.date), max(args.date)
    return _adapt_date(args, tweak), None


def run_workout_adapt(args: argparse.Namespace) -> None:
    # Executes the daily workout Garmin adaptation checks command.
    runtime.coach_service.retrospectives_step()   # DESIGN_cycle_retrospective.md §3, §5
    with replacing_unsent(skip=args.auto, window=_adapt_window(args, tweak=False)):
        _adapt(args)


def run_workout_tweak(args: argparse.Namespace) -> None:
    """Changes the days a request is about: `workout adapt`'s flow with a narrower job
    (DESIGN_workout_tweak.md §3)."""
    with replacing_unsent(skip=args.auto, window=_adapt_window(args, tweak=True)):
        _adapt(args, tweak=True)


def _confirm_candidates(proposal, date_str: str, message: Optional[str]) -> None:
    """On a terminal, asks about each constraint and each daily signal the note produced
    (DESIGN_constraints.md §8, DESIGN_signal_extraction.md §2). The same call that wrote
    the proposal extracted them, so the note informed this run whatever the answers; a
    signal confirmed here informs the next run. `bot capture note` asks the same questions
    through `cli/candidates.py` (DESIGN_bot_simple_frontend.md §12.10)."""
    confirm_new_constraints(proposal.new_constraints, date_str, message or "")
    confirm_new_signals(proposal.new_signals, date_str)


def _settle(
    args: argparse.Namespace, tweak: bool, proposal, in_chat: bool, replaces: bool,
    written_upto: int,
) -> None:
    """What becomes of the week planner's answer. A terminal run shows the preview, asks and
    applies. A run started from the athlete's chat never asks and never waits: it saves its
    proposal and sends it, and `-y` writes without asking wherever it was typed
    (DESIGN_waiting_proposal.md §2).

    `replaces` says a proposal was open when the run started, and `written_upto` is the
    newest change that wrote a session at that moment (§6.2)."""
    saves = in_chat and not args.auto
    if saves and proposal.week_planner_changed:
        # In place of the confirm: the reason and the preview, then the two answers (§3).
        send_alone(saved_proposal.save(proposal, written_upto, replaces=replaces))
        return

    runtime.render.adapt_reason(proposal.reason)

    if not proposal.workouts and tweak:
        runtime.render.tweak_no_change()
    elif not proposal.workouts:
        runtime.render.adapt_no_change()
    if not proposal.workouts:
        # The pass still had its constraints in scope, which is all `honored_at`
        # claims — requiring a *change* would flag them forever (§8). A proposal that
        # waits stays open (DESIGN_waiting_proposal.md §6.2).
        runtime.coach_service.workout_revision_record_no_change(proposal)
        return
    print_send_notice(revision_dates(proposal))

    if saves:
        # Only the kilograms moved: written at once, with the strength planner's
        # sentences as the reason above (DESIGN_waiting_proposal.md §7).
        if proposal.strength_notice:
            print(f"\n{wrap_text(proposal.strength_notice)}")
    else:
        # The renderer draws the preview, the prompt asks the question: voice and
        # transport are two objects and neither calls the other
        # (DESIGN_render_persona.md §4).
        heading, question = runtime.render.adapt_confirm_words()
        runtime.render.revision_preview(proposal, heading)
        if not (args.auto or runtime.prompt.confirm(question)):
            runtime.render.adapt_discarded()
            return

    # A terminal let go of the week while it asked (`_adapt`), so a session may have been
    # written meanwhile (DESIGN_long_runs_beside_chat.md §3).
    with runtime.db.week_lock():
        if week_changed(written_upto):
            return
        step("\nApplying adaptations...")
        runtime.coach_service.workout_revision_apply(proposal)
    runtime.render.adapt_applied()


def _adapt(args: argparse.Namespace, tweak: bool = False) -> None:
    date_str = _adapt_date(args, tweak)
    if not tweak and not args.date:
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

    # Before the week planner is told anything, a terminal with someone there settles any
    # pairing the matcher had to guess at. Every other run queues the question below and
    # goes on with the app's own pairing (DESIGN_chat_questions.md §3).
    in_chat = athlete_watching()
    if not (in_chat or args.auto):
        cut_short.ask_on_the_spot(date_str)
    with runtime.db.week_lock() as week:
        _consult(args, tweak, date_str, in_chat, week)


def _consult(
    args: argparse.Namespace, tweak: bool, date_str: str, in_chat: bool, week: WeekHold
) -> None:
    """The week planner's look at the week, and what becomes of its answer. Nothing writes
    the week from the reading below to the save, and a terminal lets go once the week
    planner has answered, since it asks a person next (DESIGN_long_runs_beside_chat.md
    §3)."""
    # Every run shows the week planner the proposal that still waits
    # (DESIGN_waiting_proposal.md §6.2).
    still_open = saved_proposal.open_proposal()
    written_upto = newest_written()

    try:
        if tweak:
            step("Asking the coach for the change...")
            proposal = runtime.coach_service.workout_tweak(
                args.message, tweak_dates=args.date or (), today_str=date_str,
                **saved_proposal.shown_to_week_planner(still_open),
            )
        else:
            step(f"Evaluating daily Garmin metrics adaptation for {fmt_date(date_str)}...")
            proposal = runtime.coach_service.workout_adapt(
                date_str, message=getattr(args, 'message', None),
                **saved_proposal.shown_to_week_planner(still_open),
            )
        if not in_chat:
            week.release()
        # The note is kept with the session the week planner says it is about, once its
        # call has returned (DESIGN_session_notes.md §3). When it cannot tell which of
        # several, a terminal asks on the spot and the chat queues the question. A tweak's
        # request is acted on at once and is not kept.
        message = getattr(args, 'message', None)
        about = [] if tweak else _note_candidates(proposal, message)
        if len(about) > 1 and not in_chat:
            about = _pick_note_session(about)
        if len(about) == 1:
            keep_note(about[0], proposal.note_date, message)

        # The questions about a constraint or a signal found in the note. A terminal asks them
        # before the preview (DESIGN_constraints.md §8). The chat queues them, the
        # cut-short question after them: they go out at once, or behind the proposal when
        # its answer comes (DESIGN_waiting_proposal.md §6.3, DESIGN_chat_questions.md §3).
        if not in_chat:
            _confirm_candidates(proposal, date_str, message)
        _settle(args, tweak, proposal, in_chat, still_open is not None, written_upto)
        if in_chat:
            if len(about) > 1:
                queue_note_question(about, proposal.note_date, message)
            queue_candidates(
                proposal.new_constraints, proposal.new_signals, date_str, message or "",
                offer=False,
            )
            tell_open_ended(proposal.new_constraints, message or "")
        if in_chat or args.auto:
            cut_short.queue_questions(date_str)
        if in_chat:
            send_own_questions()

    except ValueError as e:
        # A domain refusal (no active plan to adapt towards), not a failure: say it
        # plainly. Anything else belongs to the entry point's error boundary.
        notice(str(e), red)
