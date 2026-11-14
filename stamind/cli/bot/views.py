"""The `bot` views, the Garmin check, and the changes to the athlete's week.

`bot constraints` and `bot goals` render a companion list from stored rows and offer its
picker (DESIGN_bot_simple_frontend.md §5.5, §12.6). They run fixed argv and write nothing:
the only mutation they reach is what a tapped picker leaf later runs as a command of its own
(§12.1). `bot garmin-check` pulls a new activity and queues its questions (ARCHITECTURE.md
§15), and `bot changes` sends the changes to the athlete's week they have not been told about
yet, marking each told as it prints it (DESIGN_change_heads_up.md §4). The morning message is
`morning.py`.
"""
import argparse
from typing import Any, Dict, List, Sequence

from stamind import heads_up, journal, runtime
from stamind.cli.bot.session_questions import queue_session_questions
# The companion surfaces are companion-only by definition, so they call the line
# builders directly rather than through `runtime.render` (DESIGN_render_persona.md §3).
from stamind.cli.render.plan_lines import (
    picker_label, simple_constraint_lines, simple_goal_lines,
)
from stamind.db.objectives import GOAL_ARCHIVED, GOAL_UPCOMING, goal_state
from stamind.sentinels import emit_buttons, emit_flush
from stamind.text import wrap_text
from stamind.config import config
from stamind.clock import today_str as _today_str

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
    """The picker under the simple goals view (§12.6). `goal rm` archives, the reversible
    action; `--purge` is unreachable from chat."""
    return [
        {"label": "👍 All good", "ack": "Great — we keep building toward these 💪"},
        {"label": "🗑 Call one off", "menu": _picker_leaves(goals, "goal rm")},
    ]


def run_bot_constraints(args: argparse.Namespace) -> None:
    """The current and upcoming constraints in companion prose, with the remove picker
    (§5.5). Read-only: a tapped leaf runs its own command."""
    today = _today_str()
    constraints = runtime.db.get_constraints(today, None)
    for line in simple_constraint_lines(constraints, today):
        print(line)
    if constraints:
        emit_buttons(constraint_rm_buttons(constraints))


def run_bot_goals(args: argparse.Namespace) -> None:
    """The goals still ahead in companion prose, with the call-off picker (§12.6). With
    none ahead, the §11 invitation and no picker."""
    today = _today_str()
    goals = [g for g in runtime.db.get_objectives()
             if goal_state(g, today) != GOAL_ARCHIVED]
    for line in simple_goal_lines(goals, today):
        print(line)
    upcoming = [g for g in goals if goal_state(g, today) == GOAL_UPCOMING]
    if upcoming:
        emit_buttons(goal_rm_buttons(upcoming))


def run_bot_garmin_check(args: argparse.Namespace) -> None:
    """Pulls today's activities when Garmin lists one not stored yet that lasts at least
    `garmin.min_activity_minutes`, and queues the questions about it; daily metrics stay out
    of it. A check that pulls nothing leaves no run in the journal; a failure prints its
    reason, exits 1, and the scheduler decides whether to journal it (ARCHITECTURE.md §15)."""
    if not (config.garmin_email and config.garmin_password):
        journal.drop_run()
        return
    today = _today_str()
    known = {a["activity_id"] for a in runtime.db.get_completed_activities(today, today)}
    try:
        listed = runtime.garmin.connect(announce=False).get_activities(today, today)
    except Exception as exc:
        journal.drop_run()
        print(f"{type(exc).__name__}: {exc}")
        raise SystemExit(1)
    shortest = config.min_activity_minutes * 60
    if not any(str(a.get("activityId")) not in known and (a.get("duration") or 0) >= shortest
               for a in listed):
        journal.drop_run()
        return
    journal.name_run("bot", "garmin-check")
    journal.record(
        "bot.garmin_check",
        runtime.garmin.pull(today, today, metrics=False, advance_watermark=False),
    )
    queue_session_questions(today)


def run_bot_changes(args: argparse.Namespace) -> None:
    """Sends each change waiting to be told, oldest first, one message each, and records
    each as told once it is printed (DESIGN_change_heads_up.md §4, §6). The bot starts it
    on a scheduler wake or ahead of the athlete's own input."""
    for position, change in enumerate(heads_up.waiting()):
        if position:
            emit_flush()
        print(wrap_text(heads_up.message(change)))
        runtime.db.mark_changes_told([change["id"]])
