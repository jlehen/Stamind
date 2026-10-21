"""The `proposal` kind of the athlete queue: what the week planner would change, saved until
the athlete answers it (DESIGN_waiting_proposal.md §3, §4).

Its wording, the three rules that put it out of date, what each answer does, how a proposal
is saved and how the open one is found. The two kinds `workout generate --propose` saves
are here too, since they share two of those rules: the weeks it would write, `schedule`, and
the question it asks before it plans over sessions that stand, `replace_sessions`
(DESIGN_long_runs_beside_chat.md §4). Nothing here sends: `cli/queue.py` does, and it
imports the list of kinds these are in.
"""
import contextlib
import io
from datetime import datetime
from typing import Any, Callable, Dict, List, Optional, Tuple

from stamind import clock, runtime
from stamind.analytics.compare import adherence_verdicts
from stamind.chat.routing import PLANNING_RUN
from stamind.cli.render.proposal_lines import page_content, short_text
from stamind.cli.workouts.heads_up import generate_dates, newest_written, revision_dates
from stamind.clock import today_str
from stamind.coach import picture
from stamind.coach.proposals import (
    GenerateProposal, RevisionProposal, generate_from_json, generate_to_json, revision_from_json,
    revision_to_json, sessions_replaced,
)
from stamind.db.queue import queue_stamp
from stamind.output import step
from stamind.page_files import sync as page_files
from stamind.queue_kind import QUESTION, STALE, Kind, queue
from stamind.text import strip_ansi

KIND = "proposal"

QUESTION_LINE = "Shall I make these changes?"
ANSWERS = ({"label": "✅ Change it"}, {"label": "💪 Keep it as planned"})
ACCEPT = 0

APPLIED_LINE = "Done — your week is updated. 💪"
KEPT_LINE = "Okay — nothing changed."
OUT_OF_DATE_LINE = "That proposal is out of date, so I left your week as it is."
REPLACES_LINE = "This replaces my earlier proposal."


def made_at(item: Dict[str, Any]) -> datetime:
    """When a proposal was saved: its subject is that instant (§3)."""
    return datetime.fromisoformat(item["subject"])


def trained_since(day: str, moment: datetime) -> bool:
    """Whether an activity recorded on `day` started after `moment`. Garmin stamps an
    activity with its local start time (DESIGN_bot_simple_frontend.md §4.2)."""
    since = clock.to_local(moment).strftime("%Y-%m-%d %H:%M:%S")
    activities = runtime.db.get_completed_activities(start_date=day, end_date=day)
    return any((a.get("start_time") or "") > since for a in activities)


def _past_or_trained(item: Dict[str, Any]) -> bool:
    """Rules 2 and 3 of §4: a day the item writes is over, or it writes today and an
    activity of today started after it was made."""
    dates = item["payload"]["dates"]
    today = today_str()
    if min(dates, default=today) < today:
        return True
    return today in dates and trained_since(today, made_at(item))


def out_of_date(item: Dict[str, Any]) -> bool:
    """The three rules of §4: a later change wrote a session, a day the proposal changes is
    over, or it changes today and an activity of today started after it was made."""
    return newest_written() > item["payload"]["written_upto"] or _past_or_trained(item)


def _pull_today(today: str) -> None:
    """Pulls today's activities past the refresh throttle, so rule 3 sees a session trained
    since the proposal was made. Garmin out of reach leaves what is stored (§4)."""
    try:
        runtime.garmin.ensure_data(today, today, force=True)
    except Exception as e:
        step(f"Could not reach Garmin, checking against what is stored: {e}")


def _spoiled_today(
    item: Dict[str, Any], is_out_of_date: Callable[[Dict[str, Any]], bool]
) -> bool:
    """Whether an item that writes today went out of date since it was saved, checked
    after today's activities are pulled. It is then closed as stale (§4)."""
    today = today_str()
    if today not in item["payload"]["dates"]:
        return False
    _pull_today(today)
    if not is_out_of_date(item):
        return False
    runtime.db.close_queue_item(item["id"], STALE, clock.now())
    return True


def _apply(item: Dict[str, Any], index: int, text: Optional[str]) -> str:
    """"Change it" writes the saved proposal under one change; "Keep it as planned" writes
    nothing (§4)."""
    if index != ACCEPT:
        return KEPT_LINE
    if _spoiled_today(item, out_of_date):
        return OUT_OF_DATE_LINE
    runtime.coach_service.workout_revision_apply(
        revision_from_json(item["payload"]["proposal"])
    )
    return APPLIED_LINE


def _show_today(item: Dict[str, Any]) -> None:
    """After either answer about today, today's sessions as they then stand, which the
    morning push no longer draws above such a proposal (§4, §5). The answer is written by
    now, so a failure here only leaves them out."""
    today = today_str()
    if today not in item["payload"]["dates"]:
        return
    try:
        workouts = runtime.db.get_workouts(start_date=today, end_date=today)
        verdicts = adherence_verdicts(runtime.db, today, today, today)
    except Exception as e:
        step(f"Could not draw today's sessions after the answer: {e}")
        return
    runtime.render.today_after_change(workouts, verdicts, today)


def _asks(item: Dict[str, Any]) -> str:
    """The question's message: the short text above it where the proposal has its page, else
    the question alone, under the long text sent before it (DESIGN_short_messages.md §3)."""
    if not page_files.has_page(runtime.db, item):
        return QUESTION_LINE
    return f"{item['payload']['short']}\n\n{QUESTION_LINE}"


PROPOSAL_KIND = Kind(
    name=KIND, shape=QUESTION,
    wording=lambda item: item["payload"]["text"],
    companion_wording=_asks,
    is_stale=out_of_date, apply=_apply, after_answer=_show_today,
    stands_alone=True, closed_line=OUT_OF_DATE_LINE,
)


def _shown_text(proposal: RevisionProposal) -> str:
    """The coach's reason, then the preview, as this run's voice draws them."""
    drawn = io.StringIO()
    with contextlib.redirect_stdout(drawn):
        runtime.render.adapt_reason(proposal.reason)
        heading, _question = runtime.render.adapt_confirm_words()
        runtime.render.revision_preview(proposal, heading)
    return strip_ansi(drawn.getvalue()).strip()


def waiting() -> List[Dict[str, Any]]:
    """The proposals not answered yet, out of date or not."""
    return [item for item in runtime.db.waiting_queue_items() if item["kind"] == KIND]


def open_proposal() -> Optional[Dict[str, Any]]:
    """The proposal that waits and is not out of date, or None. One that waits and is out
    of date is closed on the way (§6.2)."""
    found = None
    for item in waiting():
        if out_of_date(item):
            runtime.db.close_queue_item(item["id"], STALE, clock.now())
            continue
        found = item
    return found


def shown_to_week_planner(item: Optional[Dict[str, Any]]) -> Dict[str, Any]:
    """What a run hands `workout_adapt` about the open proposal, as keyword arguments, and
    nothing when none is open (§6.2). The text is the day it was made and the days it
    changes, then what the athlete read, whose day words count from that day."""
    if item is None:
        return {}
    dates = tuple(item["payload"]["dates"])
    made_on = clock.to_local(made_at(item)).strftime("%Y-%m-%d")
    return {
        "open_proposal": (
            f"Proposed on {made_on}. The days it changes: {', '.join(dates)}.\n"
            f"{item['payload']['text']}"
        ),
        "open_dates": dates,
    }


def save(proposal: RevisionProposal, written_upto: int, replaces: bool = False) -> Dict[str, Any]:
    """Saves a proposal and returns its item. Every other proposal that still waits is
    closed, so one is open at a time (§3). `written_upto` is the newest change that wrote a
    session when the run read the week (§4, rule 1). `replaces` says the run was shown an
    open proposal, so the text opens by saying so (§6.2). The run's picture is written
    here, since saving is how this run ends (DESIGN_quiet_morning.md §3)."""
    now = clock.now()
    for other in waiting():
        runtime.db.close_queue_item(other["id"], STALE, now)
    opening = REPLACES_LINE if replaces else None
    text = _shown_text(proposal)
    if opening:
        text = f"{opening}\n\n{text}"
    # The long text, the short one and the page's, so the page can be built again from the
    # database (DESIGN_short_messages.md §3, §6.2).
    item_id = queue(KIND, queue_stamp(now), {
        "text": text,
        "short": short_text(proposal, opening),
        "page": page_content(proposal),
        "answers": list(ANSWERS),
        "proposal": revision_to_json(proposal),
        "dates": sorted(revision_dates(proposal)),
        "written_upto": written_upto,
    })
    picture.remember(runtime.db, proposal)
    return runtime.db.get_queue_item(item_id)


# --- What `workout generate --propose` saves (DESIGN_long_runs_beside_chat.md §4) ---

SCHEDULE = "schedule"
SCHEDULE_ANSWERS = ({"label": "✅ Schedule them"}, {"label": "✖️ Leave it"})
SCHEDULED_LINE = "Done — they're in your schedule. 💪"

REPLACE_SESSIONS = "replace_sessions"
REPLACE_ANSWERS = ({"label": "✅ Plan them"}, {"label": "✖️ Leave it"})
REPLACE_CLOSED_LINE = (
    "That question is out of date, so I planned nothing. The morning message offers "
    "📅 Plan my next weeks while your schedule runs short."
)


def written_inside(item: Dict[str, Any]) -> bool:
    """Rule 1 for saved weeks, narrower than a proposal's: a later change wrote a session on
    one of the days they write (choice 2b)."""
    payload = item["payload"]
    return runtime.db.wrote_between(payload["written_upto"], payload["start"], payload["end"])


def weeks_out_of_date(item: Dict[str, Any]) -> bool:
    """The three rules of §4 there: rule 1 above, and a proposal's rules 2 and 3."""
    return written_inside(item) or _past_or_trained(item)


def _schedule(item: Dict[str, Any], index: int, text: Optional[str]) -> str:
    """"Schedule them" writes exactly the weeks that were shown, under one change, and
    Google Calendar follows; "Leave it" writes nothing."""
    if index != ACCEPT:
        return KEPT_LINE
    if _spoiled_today(item, weeks_out_of_date):
        return OUT_OF_DATE_LINE
    runtime.coach_service.workout_generate_apply(
        generate_from_json(item["payload"]["proposal"])
    )
    return SCHEDULED_LINE


# It has a proposal's manners: sent at once by the run, in no line, never sent again
# (§4 there, "Where it is kept").
SCHEDULE_KIND = Kind(
    name=SCHEDULE, shape=QUESTION,
    wording=lambda item: item["payload"]["text"],
    companion_wording=lambda item: item["payload"]["question"],
    is_stale=weeks_out_of_date, apply=_schedule,
    stands_alone=True, closed_line=OUT_OF_DATE_LINE,
)


def _drawn_weeks(proposal: GenerateProposal) -> str:
    """The proposed sessions, as this run's voice draws them."""
    drawn = io.StringIO()
    with contextlib.redirect_stdout(drawn):
        runtime.render.workout_generate_preview(proposal)
    return strip_ansi(drawn.getvalue()).strip()


def save_weeks(proposal: GenerateProposal, written_upto: int) -> Dict[str, Any]:
    """Saves the weeks a `--propose` run would write and returns their item. The weeks saved
    before are closed, and a proposal that waits is left alone (choice 2a). `written_upto`
    is the newest change that wrote a session when the run read the schedule."""
    now = clock.now()
    for other in runtime.db.waiting_queue_items():
        if other["kind"] == SCHEDULE:
            runtime.db.close_queue_item(other["id"], STALE, now)
    dates = sorted(generate_dates(proposal))
    question = runtime.render.schedule_words(
        len(proposal.workouts), sessions_replaced(proposal), proposal.gen_start,
        proposal.gen_end,
    )
    item_id = queue(SCHEDULE, queue_stamp(now), {
        "text": _drawn_weeks(proposal),
        "question": question,
        "answers": list(SCHEDULE_ANSWERS),
        "proposal": generate_to_json(proposal),
        "dates": dates,
        "start": dates[0] if dates else proposal.gen_start,
        "end": dates[-1] if dates else proposal.gen_end,
        "written_upto": written_upto,
    })
    return runtime.db.get_queue_item(item_id)


def _replace_stale(item: Dict[str, Any]) -> bool:
    """Out of date once its first day is over. A change written on its days does not count:
    "Plan them" reads the schedule as it then stands (§4 there, ruled 2026-10-15)."""
    return item["payload"]["start"] < today_str()


def _plan_them(item: Dict[str, Any], index: int, text: Optional[str]) -> Optional[str]:
    """"Leave it" writes nothing. "Plan them" says nothing here: the planning that follows
    in the same command speaks (`cli/queue_commands.py`)."""
    if index == ACCEPT:
        return None
    return KEPT_LINE


# A confirmation, drawn bare, whose "Plan them" starts the planning beside the chat (§4,
# §6 there, choices 2c and 2f).
REPLACE_SESSIONS_KIND = Kind(
    name=REPLACE_SESSIONS, shape=QUESTION,
    wording=lambda item: item["payload"]["text"],
    companion_wording=lambda item: item["payload"]["text"],
    is_stale=_replace_stale, apply=_plan_them, bare=True, confirmation=True,
    long_run=(ACCEPT, PLANNING_RUN), closed_line=REPLACE_CLOSED_LINE,
)


def ask_to_replace(
    span: Tuple[str, str], standing: List[Dict[str, Any]], prefer_macro_id: Optional[int],
    fresh: bool,
) -> None:
    """Saves the question asked before planning `span` over the sessions `standing` in it.
    Its answer plans the same days, the same way."""
    start, end = span
    queue(REPLACE_SESSIONS, queue_stamp(clock.now()), {
        "text": runtime.render.replace_sessions_words(
            len(standing), standing[0]["date"], standing[-1]["date"],
        ),
        "answers": list(REPLACE_ANSWERS),
        "start": start,
        "end": end,
        "prefer_macro_id": prefer_macro_id,
        "fresh": fresh,
    })
