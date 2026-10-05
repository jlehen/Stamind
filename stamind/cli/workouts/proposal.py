"""The `proposal` kind of the athlete queue: what the week planner would change, saved until
the athlete answers it (DESIGN_waiting_proposal.md §3, §4).

Its wording, the three rules that put it out of date, what each answer does, how a proposal
is saved and how the open one is found. Nothing here sends: `cli/queue.py` does, and it
imports the list of kinds this one is in.
"""
import contextlib
import io
from datetime import datetime, timedelta
from typing import Any, Dict, List, Optional

from stamind import clock, runtime
from stamind.analytics.compare import adherence_verdicts
from stamind.cli.workouts.heads_up import newest_written, revision_dates
from stamind.clock import today_str
from stamind.coach.proposals import RevisionProposal, revision_from_json, revision_to_json
from stamind.db.queue import queue_stamp
from stamind.output import step
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


def out_of_date(item: Dict[str, Any]) -> bool:
    """The three rules of §4: a later change wrote a session, a day the proposal changes is
    over, or it changes today and an activity of today started after it was made."""
    payload = item["payload"]
    today = today_str()
    if newest_written() > payload["written_upto"]:
        return True
    if min(payload["dates"], default=today) < today:
        return True
    return today in payload["dates"] and trained_since(today, made_at(item))


def _pull_today(today: str) -> None:
    """Pulls today's activities past the refresh throttle, so rule 3 sees a session trained
    since the proposal was made. Garmin out of reach leaves what is stored (§4)."""
    try:
        runtime.garmin.ensure_data(today, today, force=True)
    except Exception as e:
        step(f"Could not reach Garmin, checking against what is stored: {e}")


def _apply(item: Dict[str, Any], index: int, text: Optional[str]) -> str:
    """"Change it" writes the saved proposal under one change; "Keep it as planned" writes
    nothing. A change to today is followed by today's sessions as they now stand, which
    nothing in the chat shows yet (§4)."""
    if index != ACCEPT:
        return KEPT_LINE
    today = today_str()
    changes_today = today in item["payload"]["dates"]
    if changes_today:
        _pull_today(today)
        if out_of_date(item):
            runtime.db.close_queue_item(item["id"], STALE, clock.now())
            return OUT_OF_DATE_LINE
    runtime.coach_service.workout_revision_apply(
        revision_from_json(item["payload"]["proposal"])
    )
    if not changes_today:
        return APPLIED_LINE
    return f"{APPLIED_LINE}\n\n{_today_text(today)}".rstrip()


def _today_text(today: str) -> str:
    """Today's sessions as this run's voice draws them after a change. The change is
    written by now, so a failure here must not keep the item open: it draws nothing."""
    try:
        workouts = runtime.db.get_workouts(start_date=today, end_date=today)
        verdicts = adherence_verdicts(runtime.db, today, today, today)
        drawn = io.StringIO()
        with contextlib.redirect_stdout(drawn):
            runtime.render.today_after_change(workouts, verdicts, today)
        return strip_ansi(drawn.getvalue()).strip()
    except Exception as e:
        step(f"Could not draw today's sessions after the change: {e}")
        return ""


PROPOSAL_KIND = Kind(
    name=KIND, shape=QUESTION,
    wording=lambda item: item["payload"]["text"],
    companion_wording=lambda item: QUESTION_LINE,
    is_stale=out_of_date, apply=_apply,
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
    open proposal, so the text opens by saying so (§6.2)."""
    now = clock.now()
    for other in waiting():
        runtime.db.close_queue_item(other["id"], STALE, now)
    text = _shown_text(proposal)
    if replaces:
        text = f"{REPLACES_LINE}\n\n{text}"
    item_id = queue(KIND, queue_stamp(now), {
        "text": text,
        "answers": list(ANSWERS),
        "proposal": revision_to_json(proposal),
        "dates": sorted(revision_dates(proposal)),
        "written_upto": written_upto,
        "sleep_seen": bool(proposal.sleep_seen),
    })
    return runtime.db.get_queue_item(item_id)


def saw_the_night_on(day: str) -> List[datetime]:
    """When each `workout adapt` proposal saved on `day` with the night's sleep score was
    made, whatever its answer: the push counts them as runs of this morning (§5)."""
    recent = runtime.db.queue_items_since(KIND, clock.now() - timedelta(days=1))
    return [
        made_at(item) for item in recent
        if item["payload"]["sleep_seen"] and item["payload"]["proposal"]["kind"] == "adapt"
        and clock.to_local(made_at(item)).strftime("%Y-%m-%d") == day
    ]
