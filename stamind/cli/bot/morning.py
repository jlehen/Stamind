"""`bot morning`, the morning message, and `bot today`, what the chat's "📅 Today" runs
(DESIGN_bot_simple_frontend.md §4, DESIGN_morning_waits_for_night.md).

`bot morning` stamps its per-day marker and, with `adapt-first` on, waits for the night
(DESIGN_morning_waits_for_night.md §5), asks the week planner before it renders when
something is new since the last run or a night is not normal (DESIGN_quiet_morning.md §2),
and saves what it would change as a proposal (DESIGN_waiting_proposal.md §5). `bot today` is
that message while it has not gone out, else today's sessions.
"""
import argparse
from typing import Any, Dict, Optional, Tuple

from stamind import clock, heads_up, journal, morning_message, runtime, settings
from stamind.analytics.compare import adherence_verdicts
from stamind.cli.bot.session_questions import queue_session_questions
from stamind.cli.common import deload_progress, ensure_recent_data, in_deload
# The companion surfaces are companion-only by definition, so they call the line
# builders directly rather than through `runtime.render` (DESIGN_render_persona.md §3).
from stamind.cli.render.plan_lines import SIMPLE_PASSED_LINE, simple_runway_lines
from stamind.cli.render.session_lines import SIMPLE_DONE_STATUSES, simple_day_lines
from stamind.cli.queue import send_alone, send_next
from stamind.cli.runway import current_runway, runway_buttons, schedule_exhausted
from stamind.cli.workouts import proposal as saved_proposal
from stamind.cli.workouts.heads_up import newest_written
from stamind.coach import picture
from stamind.openrouter import openrouter_client
from stamind.page_files import sync as page_files
from stamind.sentinels import emit_buttons, emit_flush
from stamind.sports import canonical_sport
from stamind.strength.sets import read_new_activities
from stamind.text import wrap_text, yellow
from stamind.output import aside, step
from stamind.config import config
from stamind.clock import fmt_day, shift, today_str as _today_str
import stamind.cli.bot.views as _views

# What the morning push offers (§4.1, §4.4): a tap feeds `send` back through the bot's
# pipeline, `ack` runs nothing, and `menu` nests a row.
GOT_IT_BUTTON = {"label": "👍 Got it", "ack": "Nice — have a good one! 💪"}
# The buttons about today's session. Under a proposal they follow its two answers, which
# stand where "Got it" would (DESIGN_waiting_proposal.md §5).
SESSION_BUTTONS = [
    {"label": "😴 Should I rest?",
     "send": 'workout adapt -m "feeling tired today"'},
    {"label": "🕐 Can't today", "menu": [
        {"label": "📆 Move it",
         "send": 'workout adapt -m "no time to train today - please move today\'s '
                 'session to another day if that makes sense"'},
        {"label": "✂️ Shorten it",
         "send": 'workout adapt -m "short on time today - please shorten today\'s '
                 'session"'},
        {"label": "⏭️ Skip it",
         "send": 'workout adapt -m "can\'t train today - please skip today\'s '
                 'session"'},
    ]},
]


# What the push says on a day already trained, in place of the briefing (§4.1).
PUSH_ALL_DONE_LINE = "✅ Already done for today — nice work 💪"

def _warn_quietly(text: str) -> None:
    """A warning the terminal sees and the journal keeps at warn level, kept out of the
    athlete's chat, where `warn` would print it (DESIGN_quiet_morning.md §6)."""
    aside(text, yellow)
    journal.note(text, lvl="warn")


def _asks(date_str: str) -> bool:
    """Whether this morning asks the week planner: something is new since the last run, a
    night since the last one in hand is not normal, or the strength planner has work
    (DESIGN_quiet_morning.md §2, §3, §4). The journal gets one line either way (§5). Its
    own `try`, apart from the run's: a gate that breaks asks, and says so at warn level
    (§6)."""
    try:
        before = picture.last(runtime.db)
        if before is None:
            _warn_quietly("Asking the week planner: no picture of the last run")
            return True
        reasons = picture.news(runtime.db, before, picture.take(runtime.db, date_str))
        graded = picture.nights(runtime.db, before["night"], date_str)
        reasons += [why for why in graded.values() if why]
        since = picture.taken(before)
    except Exception as e:
        _warn_quietly(f"Asking the week planner: the gate failed: {e}")
        return True
    if reasons:
        step("Asking the week planner: " + "; ".join(reasons))
        return True
    if graded:
        step(f"Quiet morning: the night is normal and nothing is new since {since}")
    else:
        step(f"Quiet morning: nothing is new since {since} and no night since has a reading")
    return False


def _morning_adaptation(date_str: str) -> Tuple[Optional[str], Optional[Dict[str, Any]]]:
    """Asks the week planner about today when something is new or a night is not normal
    (DESIGN_quiet_morning.md §2), and returns (the line for the briefing, the saved
    proposal's item); a quiet morning returns neither. A session that would change is saved
    as a proposal, and kilograms that moved alone are written at once
    (DESIGN_waiting_proposal.md §5, §7). With nothing changed, the strength planner's notice
    is the line (DESIGN_strength_tracking.md §9). A failure renders the stored schedule and
    stays out of the athlete's chat."""
    try:
        # A pull that found no sleep score yet leaves a row for today that the refresh
        # throttle would keep; the night is what this morning is about, so fetch again,
        # and grade it only after (§4.2, DESIGN_quiet_morning.md §4).
        ensure_recent_data(date_str, force_pull=runtime.db.get_sleep_score(date_str) is None)
        # From the gate to the save nothing writes the week, and a tap waits its turn
        # (DESIGN_long_runs_beside_chat.md §3). Nobody asked for this run, so the chat is
        # not told when it waits.
        with runtime.db.week_lock(waiting=None):
            return _ask_week_planner(date_str)
    except Exception as e:
        step(f"Morning adaptation failed, rendering the stored schedule: {e}")
        return None, None


def _ask_week_planner(date_str: str) -> Tuple[Optional[str], Optional[Dict[str, Any]]]:
    """`_morning_adaptation`'s look at the week, under the week lock."""
    if not _asks(date_str):
        return None, None
    written_upto = newest_written()
    # The proposal that still waits is shown to the week planner, and a new one replaces it
    # (DESIGN_waiting_proposal.md §6.2).
    still_open = saved_proposal.open_proposal()
    # Nobody asked for this run, so the chat is not told it is waiting
    # (DESIGN_output_verbosity.md §8.4).
    with openrouter_client.unannounced():
        proposal = runtime.coach_service.workout_adapt(
            date_str, **saved_proposal.shown_to_week_planner(still_open)
        )
    if not proposal.workouts:
        runtime.coach_service.workout_revision_record_no_change(proposal)
        return proposal.strength_notice, None
    if proposal.week_planner_changed:
        item = saved_proposal.save(proposal, written_upto, replaces=still_open is not None)
        return None, item
    runtime.coach_service.workout_revision_apply(proposal)
    note = " ".join(part for part in (proposal.reason, proposal.strength_notice) if part)
    return note, None


def _refresh_garmin(date_str: str) -> None:
    """The recent-data refresh a read command runs, then the strength sets, so their
    questions are in the line (DESIGN_strength_tracking.md §11). A failure briefs what is
    stored."""
    try:
        runtime.garmin.ensure_data(date_str, date_str)
        read_new_activities()
    except Exception as e:
        step(f"Could not refresh Garmin data, briefing what is stored: {e}")


def _trained_today(date_str: str) -> Dict[int, Dict[str, Any]]:
    """Today's adherence verdicts over freshly pulled activity data, which tell a session
    still ahead from one done (§4.1). A failure renders the day ungraded."""
    try:
        runtime.garmin.ensure_data(date_str, date_str)
        return adherence_verdicts(runtime.db, date_str, date_str, _today_str())
    except Exception as e:
        step(f"Could not check what was trained today, briefing the schedule: {e}")
        return {}


def _deload_day_line(today: str) -> Optional[str]:
    """'🔋 Deload, day 3 of 7.' on a deload day (DESIGN_deload_weeks.md §11.1)."""
    mesocycle = runtime.db.get_covering_mesocycle(today)
    if not mesocycle or not in_deload(mesocycle, today):
        return None
    return f"🔋 Deload, {deload_progress(mesocycle, today)}."


def _deload_eve_line(today: str) -> Optional[str]:
    """'🔋 Your deload starts tomorrow, until Sun 8 Nov.' the day before one
    (DESIGN_deload_weeks.md §11.1)."""
    tomorrow = shift(today, 1)
    mesocycle = runtime.db.get_covering_mesocycle(tomorrow)
    if not mesocycle or mesocycle.get("deload_start") != tomorrow:
        return None
    until = fmt_day(mesocycle["end_date"])
    return f"🔋 Your deload {deload_progress(mesocycle, today)}, until {until}."


# What "📅 Today" says under today's sessions while the morning message waits for the night,
# and what it says before it sends the message itself (DESIGN_morning_waits_for_night.md §4,
# §5). The time is the two-hour mark.
WAITING_LINE = (
    "Garmin does not have your night yet. Once your watch has synced, tap 📅 Today again. "
    "Otherwise your morning message comes by {time} at the latest."
)
PREPARING_LINE = "Preparing your morning message…"
NIGHT_IN_LINE = "Your night is in. " + PREPARING_LINE


def _today_view(today: str) -> None:
    """Today's sessions, as "📅 Today" draws them once the morning message has gone out."""
    workouts = runtime.db.get_workouts(start_date=today, end_date=today)
    verdicts = _trained_today(today) if workouts else {}
    runtime.render.workout_list(
        workouts, verdicts, argparse.Namespace(sport_type=None), start_date=today,
        end_date=today, ids=[], names_a_range=True,
    )


def run_bot_today(args: argparse.Namespace) -> None:
    """"📅 Today" and "what's on today?": today's morning message while it has not gone out,
    else today's sessions. With the push off, or on a day the message sends nothing, always
    the sessions. With `adapt-first` on the message waits for the night, and the sessions
    then carry one line saying so (DESIGN_morning_waits_for_night.md §4, §5)."""
    today = _today_str()
    runway = current_runway(today)
    if not settings.push_enabled() or morning_message.sent_on(today) or _silent(today, runway):
        _today_view(today)
        return
    if settings.adapt_first():
        night_in = _night_in(today, "today")
        if not night_in and _may_wait():
            _today_view(today)
            print(wrap_text(WAITING_LINE.format(time=morning_message.night_deadline())))
            return
        # Past the two-hour mark, or without Garmin, the message goes out without the night.
        line = PREPARING_LINE
        if night_in:
            line = NIGHT_IN_LINE
        print(line)
        emit_flush()
    _morning_message(today, runway)


def _silent(today: str, runway: Optional[Dict[str, Any]]) -> bool:
    """Whether the morning message sends nothing: the schedule ran out past the
    passed-state window and today is empty. Not the rest-day line, which would describe a
    hole as a coaching decision, and not a stale celebration (DESIGN_runway_nudge.md §6)."""
    return (runway is None and schedule_exhausted(today)
            and not runtime.db.get_workouts(start_date=today, end_date=today))


def _garmin_set_up() -> bool:
    return bool(config.garmin_email and config.garmin_password)


def _may_wait() -> bool:
    """Whether the morning message may still wait for the night: Garmin is set up and the
    two-hour mark has not passed (DESIGN_morning_waits_for_night.md §5)."""
    return _garmin_set_up() and clock.now().strftime("%H:%M") < morning_message.night_deadline()


def _night_in(today: str, command: str) -> bool:
    """Whether Garmin has today's sleep score: stored already, or found by one call after
    the login. A look that fails counts as no night (DESIGN_morning_waits_for_night.md §5),
    and its warning keeps the run of `bot <command>` in the journal, named."""
    if runtime.db.get_sleep_score(today) is not None:
        return True
    if not _garmin_set_up():
        return False
    try:
        return runtime.garmin.connect(announce=False).get_sleep_score(today) is not None
    except Exception as e:
        journal.name_run("bot", command)
        _warn_quietly(f"Waiting for the night: Garmin could not be asked: {e}")
        return False


def run_bot_morning(args: argparse.Namespace) -> None:
    """Renders the §4.1 morning message for today and emits its button row, under the
    briefing or under the proposal's question (DESIGN_waiting_proposal.md §5).

    Idempotent per day via the settings marker; the bot's scheduler tries it until the
    marker says today (DESIGN_morning_waits_for_night.md §5). A try that waits for the night
    leaves no run in the journal. Once the schedule has run out the push says so and offers
    to extend it, and once even that has nothing left to say it sends nothing at all
    (DESIGN_runway_nudge.md §6)."""
    today = _today_str()
    if not args.force and morning_message.sent_on(today):
        journal.drop_run()
        return
    runway = current_runway(today)
    # Decided before the adaptation, so a dead plan does not spend an LLM call each morning.
    if _silent(today, runway):
        journal.name_run("bot", "morning")
        runtime.coach_service.retrospectives_step()
        morning_message.mark_sent()
        return
    if (not args.force and settings.adapt_first() and _may_wait()
            and not _night_in(today, "morning")):
        journal.drop_run()
        return
    journal.name_run("bot", "morning")
    _morning_message(today, runway)


def _morning_message(today: str, runway: Optional[Dict[str, Any]]) -> None:
    """The morning message itself, once `run_bot_morning` or `run_bot_today` has decided it
    goes out. A day with no session gets the one-line rest message, a planned rest day its
    own line, and a day already trained the congratulation, all without buttons — none has
    a session left to change."""
    # Marked as it starts, so a try that breaks half-way is not tried again
    # (DESIGN_morning_waits_for_night.md §5, §7 choice 16).
    morning_message.mark_sent()
    # The changes to the week not told yet go first, each as a message of its own, as before
    # a tap (DESIGN_change_heads_up.md §4).
    if heads_up.waiting():
        _views.run_bot_changes(argparse.Namespace())
        emit_flush()
    # A plan that has run out gets its records too, on the silent branch above
    # (DESIGN_cycle_retrospective.md §3, §5).
    runtime.coach_service.retrospectives_step()
    # Before the refresh, so it is the first line whatever the refresh prints
    # (DESIGN_deload_weeks.md §11.2).
    deload_day = _deload_day_line(today)
    if deload_day:
        print(deload_day)
    _refresh_garmin(today)
    # The cut-short question then stands first in the line, after the briefing
    # (DESIGN_chat_questions.md §3).
    queue_session_questions(today)

    adapt_note, proposal_item = None, None
    if settings.adapt_first():
        adapt_note, proposal_item = _morning_adaptation(today)
    # After the adaptation, so the verdicts grade the sessions this push is about to show.
    workouts = runtime.db.get_workouts(start_date=today, end_date=today)
    verdicts = _trained_today(today) if workouts else {}
    ahead = [
        w for w in workouts
        if (verdicts.get(w.get("id")) or {}).get("status") not in SIMPLE_DONE_STATUSES
    ]

    # A proposal that changes today says what today would become, and either answer draws
    # today as it then stands, so today as stored is not drawn above it
    # (DESIGN_waiting_proposal.md §5).
    changes_today = proposal_item is not None and today in proposal_item["payload"]["dates"]
    page = None
    if workouts and not ahead:
        print(PUSH_ALL_DONE_LINE)
    elif not workouts and runway is not None and runway["days_left"] < 0:
        print(SIMPLE_PASSED_LINE)
    elif not changes_today:
        # Each session's short line where the pages are published, its whole text one tap
        # away (DESIGN_short_messages.md §4).
        short = page_files.pages_published(runtime.db)
        for line in simple_day_lines(workouts, today, verdicts, short=short):
            print(line)
        page = page_files.day_button(runtime.db, workouts, today)
    if adapt_note:
        print(wrap_text(adapt_note))
    if runway:
        for line in simple_runway_lines(runway, today):
            print(wrap_text(line))
    deload_eve = _deload_eve_line(today)
    if deload_eve:
        print(deload_eve)
    # Two independent gates, each answering its own question, so relaxing one cannot
    # resurrect the other's buttons (§6). A rest session is graded apart from done, but
    # there is nothing on it to ease or move.
    to_change = [w for w in ahead if canonical_sport(w["sport_type"]) != "rest"]
    buttons = (SESSION_BUTTONS if to_change else []) + runway_buttons(runway)
    # With no proposal the row sits under the briefing and opens with "Got it". With one,
    # the briefing has no row: the buttons go under the proposal's question
    # (DESIGN_waiting_proposal.md §5).
    if proposal_item is None and to_change:
        buttons = [GOT_IT_BUTTON] + buttons
    if proposal_item is None and buttons:
        emit_buttons(buttons, page=page)
    elif page:
        # A page button asks nothing and is no live row, so the briefing keeps it on a
        # morning with a proposal (DESIGN_short_messages.md §5, D8).
        emit_buttons([], page=page)
    # The last act is the queue's step: the first item of the line, unless an item is
    # out (DESIGN_athlete_queue.md §13.2). What the week planner would change goes first,
    # as a message of its own. It is then out, so the line starts when the athlete answers
    # it (DESIGN_waiting_proposal.md §5).
    if proposal_item is not None:
        emit_flush()
        send_alone(proposal_item, buttons)
    send_next()
