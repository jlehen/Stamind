"""The `bot` views, and the two messages the bot sends unasked.

`bot constraints`, `bot goals` and `bot mesocycle` render a companion list from stored
rows and offer its picker; `bot morning` is the daily push and `bot changes` sends the
changes to the athlete's week they have not been told about yet
(DESIGN_bot_simple_frontend.md §4, §5.5, §11.2, §12.6; DESIGN_change_heads_up.md §4).

The three views run fixed argv and write nothing: the only mutation they reach is what a
tapped picker leaf later runs as a command of its own (§12.1). The two unasked messages do
write — `bot morning` stamps its per-day marker and, with `adapt-first` on, runs the
adaptation before it renders; `bot changes` marks each line told as it prints it.
"""
import argparse
from datetime import datetime
from typing import Any, Dict, List, Optional, Sequence

from stamind import clock, heads_up, runtime, settings
from stamind.analytics.compare import adherence_verdicts
from stamind.cli.common import ensure_recent_data
# The companion surfaces are companion-only by definition, so they call the line
# builders directly rather than through `runtime.render` (DESIGN_render_persona.md §3).
from stamind.cli.render.plan_lines import (
    SIMPLE_PASSED_LINE, picker_label, simple_constraint_lines, simple_goal_lines,
    simple_mesocycle_lines, simple_runway_lines,
)
from stamind.cli.render.session_lines import SIMPLE_DONE_STATUSES, simple_day_lines
from stamind.cli.queue import send_walk_step
from stamind.cli.runway import current_runway, runway_buttons, schedule_exhausted
from stamind.db.objectives import GOAL_ARCHIVED, GOAL_UPCOMING, goal_state
from stamind.sentinels import emit_buttons, emit_flush
from stamind.sports import canonical_sport
from stamind.strength.sets import read_new_activities
from stamind.text import wrap_text
from stamind.output import step
from stamind.clock import today_str as _today_str

# lives in the instance's database so the bot process stays stateless across restarts
# (DESIGN_bot_simple_frontend.md §4.2).
MORNING_MARKER = "push_morning_last"

# What the morning push offers (§4.1/§4.4): the CLI owns WHAT to offer, the bot only
# renders. Each `send` is a canned utterance the bot feeds back through its normal
# command pipeline when the button is tapped; `ack` runs nothing; `menu` nests a
# choose-row at the bot level.
MORNING_BUTTONS = [
    {"label": "👍 Got it", "ack": "Nice — have a good one! 💪"},
    {"label": "😴 Feeling tired",
     "send": 'workout adapt -m "feeling tired this morning"'},
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


# What the push says on a day already trained: the catch-up window runs to mid-afternoon
# (§4.3), so it routinely fires on a session that is already in the bag, and reading its
# prescription back with a "can't today" row attached is a ping about nothing (§4.1).
PUSH_ALL_DONE_LINE = "✅ Already done for today — nice work 💪"

# --- Pickers (§12.1: the model picks that something should change, the tap picks which) ---

def _picker_leaves(rows: Sequence[Dict[str, Any]], command: str) -> List[dict]:
    """One leaf per row, each carrying the deterministic `<command> <id>` its tap sends.
    Which row is acted on is decided by the athlete's tap, never by the model (§5.5)."""
    return [
        {"label": f"🗑 {picker_label(row['title'])}", "send": f"{command} {row['id']}"}
        for row in rows
    ]


def constraint_rm_buttons(constraints: list) -> list:
    """The picker under the simple constraints view (§5.5)."""
    return [
        {"label": "👍 All good", "ack": "Great — I'll keep working around these."},
        {"label": "🗑 Remove one", "menu": _picker_leaves(constraints, "constraint rm")},
    ]


def goal_rm_buttons(goals: list) -> list:
    """The picker under the simple goals view (§12.6). `goal rm` archives — sessions
    stood down, history kept, reinstatable by the operator — so the one goal mutation a
    tap fires is the reversible one; `--purge` is unreachable from chat."""
    return [
        {"label": "👍 All good", "ack": "Great — we keep building toward these 💪"},
        {"label": "🗑 Call one off", "menu": _picker_leaves(goals, "goal rm")},
    ]


def run_bot_constraints(args: argparse.Namespace) -> None:
    """Renders the athlete's current-and-upcoming directives in companion prose and
    offers the remove picker (§5.5). Read-only itself; the only mutation reachable is
    what a tapped leaf later runs."""
    today = _today_str()
    constraints = runtime.db.get_constraints(today, None)
    for line in simple_constraint_lines(constraints, today):
        print(line)
    if constraints:
        emit_buttons(constraint_rm_buttons(constraints))


def run_bot_goals(args: argparse.Namespace) -> None:
    """Renders the goals still ahead in companion prose and offers the call-off picker
    (§12.6). An empty active list renders the §11 invitation, never a bare picker: the
    list she reads IS the answer — already done, or already called off."""
    today = _today_str()
    goals = [g for g in runtime.db.get_objectives()
             if goal_state(g, today) != GOAL_ARCHIVED]
    for line in simple_goal_lines(goals, today):
        print(line)
    upcoming = [g for g in goals if goal_state(g, today) == GOAL_UPCOMING]
    if upcoming:
        emit_buttons(goal_rm_buttons(upcoming))


def run_bot_mesocycle(args: argparse.Namespace) -> None:
    """One training mesocycle in full: the stanza the plan view draws for it, then the
    whole focus rather than its first sentence (§11.2). Read-only; reached from the
    plan view's "Tell me more" leaves, so a stale tap after a replan has to land
    softly rather than as an error."""
    m = runtime.db.get_mesocycle(args.mesocycle_id)
    if not m:
        print("That mesocycle isn't on your plan any more — tap 🧭 My plan for the current road.")
        return
    macrocycle = runtime.db.get_macrocycle(m["macrocycle_id"])
    if macrocycle and macrocycle.get("status") == "superseded":
        print("(a mesocycle from an older version of the plan — a newer one has replaced it)")
    for line in simple_mesocycle_lines(m, _today_str()):
        print(line)
    focus = (m.get("focus") or "").strip()
    if focus:
        print()
        print(wrap_text(focus))


def _adapted_this_morning(date_str: str) -> bool:
    """Whether the daily adaptation already ran today with last night's sleep score in hand
    and nothing has been trained since — then the push does not run it again (§4.2)."""
    change = runtime.db.newest_adapt()
    if not change or not change.get("sleep_seen"):
        return False
    ran_at = clock.to_local(datetime.fromisoformat(change["created_at"]))
    if ran_at.strftime("%Y-%m-%d") != date_str:
        return False
    # Garmin stamps an activity with its local start time, the clock `ran_at` is now in.
    since = ran_at.strftime("%Y-%m-%d %H:%M:%S")
    activities = runtime.db.get_completed_activities(start_date=date_str, end_date=date_str)
    return all((a.get("start_time") or "") <= since for a in activities)


def _auto_adapt_note(date_str: str) -> Optional[str]:
    """Runs the daily adaptation non-interactively (the `workout adapt -y` flow minus
    its preview) and returns the reason line when a change was applied, unless one already
    ran this morning with the night in hand (§4.2). A failure must not sink the push: the
    schedule then renders as stored, and the error surfaces only as a terminal aside —
    never in the athlete's chat.

    The strength planner's notice joins the line whether or not anything else changed,
    which is what covers the morning of the gym day itself
    (DESIGN_strength_tracking.md §9)."""
    try:
        if _adapted_this_morning(date_str):
            return None
        # A pull that found no sleep score yet leaves a row for today that the refresh
        # throttle would keep; the night is what this run is for, so fetch again (§4.2).
        ensure_recent_data(date_str, force_pull=runtime.db.get_sleep_score(date_str) is None)
        proposal = runtime.coach_service.workout_adapt(date_str)
        if not proposal.workouts:
            runtime.coach_service.workout_revision_record_no_change(proposal)
            return proposal.strength_notice
        runtime.coach_service.workout_revision_apply(proposal)
        return " ".join(
            part for part in (proposal.reason, proposal.strength_notice) if part
        )
    except Exception as e:
        step(f"Morning adaptation failed, rendering the stored schedule: {e}")
        return None


def _refresh_garmin(date_str: str) -> None:
    """The recent-data refresh a read command runs, then the strength sets: the push is the
    companion's whole delivery path, so their questions have to join its walk
    (DESIGN_strength_tracking.md §11). A failure briefs what is stored."""
    try:
        runtime.garmin.ensure_data(date_str, date_str)
        read_new_activities()
    except Exception as e:
        step(f"Could not refresh Garmin data, briefing what is stored: {e}")


def _trained_today(date_str: str) -> Dict[int, Dict[str, Any]]:
    """Today's adherence verdicts over freshly pulled activity data — what the push needs
    to tell a session still ahead from one already behind (§4.1). Like the adaptation, a
    failure must not sink the push: an ungraded day renders as the schedule it was."""
    try:
        runtime.garmin.ensure_data(date_str, date_str)
        return adherence_verdicts(runtime.db, date_str, date_str, _today_str())
    except Exception as e:
        step(f"Could not check what was trained today, briefing the schedule: {e}")
        return {}


def run_bot_changes(args: argparse.Namespace) -> None:
    """Sends each change waiting to be told, oldest first, one message each, and records
    each as told once it is printed (DESIGN_change_heads_up.md §4, §6). The bot starts it
    on a scheduler wake or ahead of the athlete's own input."""
    for position, change in enumerate(heads_up.waiting()):
        if position:
            emit_flush(wait=False)
        print(wrap_text(heads_up.message(change)))
        runtime.db.mark_changes_told([change["id"]])


def run_bot_morning(args: argparse.Namespace) -> None:
    """Renders the §4.1 morning message for today and emits its button row.

    Idempotent per day via the settings marker; the bot's scheduler may fire it
    repeatedly (catch-up after sleep, restarts) without double-sending. A day with no
    session gets the one-line rest message, a planned rest day its own line, and a day
    already trained the congratulation, all without buttons — none has a session left to
    change.

    Once the schedule has run out the push says so and offers to extend it, and once even
    that has nothing left to say it sends nothing at all (DESIGN_runway_nudge.md §6)."""
    today = _today_str()
    if not args.force and runtime.db.get_setting(MORNING_MARKER) == today:
        return
    runway = current_runway(today)

    # An exhausted schedule past the passed-state window has nothing honest left to say on
    # an empty day: not the rest-day line, which would describe a hole as a coaching
    # decision, and not a stale celebration. Silence, until a schedule exists again (§6).
    # Decided before the adaptation, so a dead plan does not spend an LLM call each morning.
    if (runway is None and schedule_exhausted(today)
            and not runtime.db.get_workouts(start_date=today, end_date=today)):
        runtime.db.set_setting(MORNING_MARKER, today)
        return
    _refresh_garmin(today)

    adapt_note = _auto_adapt_note(today) if settings.adapt_first() else None
    # After the adaptation, so the verdicts grade the sessions this push is about to show.
    workouts = runtime.db.get_workouts(start_date=today, end_date=today)
    verdicts = _trained_today(today) if workouts else {}
    ahead = [
        w for w in workouts
        if (verdicts.get(w.get("id")) or {}).get("status") not in SIMPLE_DONE_STATUSES
    ]

    if workouts and not ahead:
        print(PUSH_ALL_DONE_LINE)
    elif not workouts and runway is not None and runway["days_left"] < 0:
        print(SIMPLE_PASSED_LINE)
    else:
        for line in simple_day_lines(workouts, today, verdicts):
            print(line)
    if adapt_note:
        print(wrap_text(adapt_note))
    if runway:
        for line in simple_runway_lines(runway, today):
            print(wrap_text(line))
    # Two independent gates, each answering its own question, so relaxing one cannot
    # resurrect the other's buttons (§6). A rest session is graded apart from done, but
    # there is nothing on it to ease or move.
    to_change = [w for w in ahead if canonical_sport(w["sport_type"]) != "rest"]
    buttons = (MORNING_BUTTONS if to_change else []) + runway_buttons(runway)
    if buttons:
        emit_buttons(buttons)
    runtime.db.set_setting(MORNING_MARKER, today)
    # After the briefing, the first item of the athlete queue, as a message of its own
    # (DESIGN_athlete_queue.md §6.1).
    send_walk_step(clock.command_start())

