"""What a workout's Calendar event says, and how to read one back.

Everything here is text over a row the caller already has, so none of it imports Google.
`client.py` is what puts the result on the calendar; keeping the wording apart from the
API call is what lets a test assert on an event's description without a service account.

It is not a leaf module, though: the identifier footer reads the database for the plan a
date belongs to, `history.for_workout` reads the session's earlier revisions, and
`_void_label` imports the athlete's void kinds from `db.workout_change`. Nothing here writes.
"""
import base64
from datetime import datetime, timedelta
from typing import Any, Dict, List, Optional

from stamind import runtime
from stamind.analytics import intensity
from stamind.analytics.adherence import STATUS_LABELS
from stamind.clock import fmt_timestamp
from stamind.gcal import history
from stamind.types import Workout

# Tag stamped on every workout event we write, and the only handle on ownership left
# once the rows that referenced the events are gone (see `client.list_workout_events`).
WORKOUT_EVENT_TAG = "stamind"

# Past-event adherence verdict -> title tag, shared rather than copied
# (adherence.STATUS_LABELS). "Not yet" is in the map but unreachable here:
# `mark_adherence_from_results` skips pending rows before rendering a verdict.
ADHERENCE_TAGS = STATUS_LABELS

# The bracketed word a changed session's title carries, read off the change kind rather
# than off "does it have a reason" (DESIGN_plan_change_continuity.md §5.1). A `generate`
# revision is absent on purpose: it is the plan being written, not a decision about the
# athlete's state, so it renders plainly. So is a `tweak`, which the athlete asked for
# (DESIGN_workout_tweak.md §3.3).
_REVISION_LABELS = {"adapt": "[Adapted]"}


def _void_label(change_kind: Optional[str]) -> str:
    """`[Deleted]` when the athlete ended the session, `[Cancelled]` when the coach did
    (DESIGN_plan_change_continuity.md §5.1)."""
    from stamind.db.workout_change import ATHLETE_VOID_KINDS
    return "[Deleted]" if change_kind in ATHLETE_VOID_KINDS else "[Cancelled]"


def event_url(event_id: Optional[str], calendar_id: Optional[str]) -> Optional[str]:
    """Rebuild an event's Google Calendar htmlLink from its stored id.

    The `eid` query parameter is base64 of "<event id> <calendar id>".
    """
    if not event_id or not calendar_id:
        return None
    eid = base64.b64encode(f"{event_id} {calendar_id}".encode()).decode().rstrip("=")
    return f"https://www.google.com/calendar/event?eid={eid}"


def event_day(event: dict) -> Optional[str]:
    """The day an event sits on. The events we write are all-day (`start.date`); a timed
    start is tolerated in case one was hand-edited in Google Calendar."""
    start = event.get('start') or {}
    return start.get('date') or (start.get('dateTime') or "")[:10] or None


def event_body(workout: Workout, adherence: Optional[dict] = None) -> dict:
    """The whole event as the API wants it: summary, description, all-day span and tag.

    `adherence` is a backward-looking verdict for a *past* event,
    ``{"status": str, "actual": Optional[str], "reasons": [str]}`` (built by
    `workout compare --mark`). When present, a status tag is prepended to the title and
    an "Adherence" header to the description.
    """
    date_str = workout['date']
    title = workout['title']
    description = workout['description']
    mod_reason = workout.get('modification_reason')

    # Calculate end date (exclusive for all-day events: start_date + 1 day)
    start_date = datetime.strptime(date_str, "%Y-%m-%d")
    end_date_str = (start_date + timedelta(days=1)).strftime("%Y-%m-%d")

    # Format Summary and Description. The body is the session's CURRENT form only;
    # every earlier form is rendered by the `History` section below
    # (DESIGN_calendar_lineage.md §5).
    change_kind = workout.get('change_kind')
    if workout.get('removed'):
        summary = f"{_void_label(change_kind)} {title}"
        event_description = description or ""
        removed_reason = workout.get('removed_reason')
        if removed_reason:
            event_description = f"{event_description}\n\nReason:\n{removed_reason}"
    elif mod_reason:
        # The word comes off the change kind, not off the presence of a reason: a
        # `workout generate` revision now carries one too, and "[Adapted]" means the
        # coach eased this because of how the athlete was doing
        # (DESIGN_plan_change_continuity.md §5.1).
        label = _REVISION_LABELS.get(change_kind)
        summary = f"{label} {title}" if label else title
        event_description = f"{description or ''}\n\nReason:\n{mod_reason}"
    else:
        summary = title
        event_description = description or ""

    # Backward-looking adherence tag for a past event (Done/Missed/Partial/…).
    # Prepended so it reads first — for a finished session the verdict is the
    # salient state — and composes with any [Adapted] tag above.
    if adherence:
        tag = ADHERENCE_TAGS.get(adherence.get("status"))
        if tag:
            summary = f"[{tag}] {summary}"

    # Prepend the session's current load, in the same words each history entry uses.
    prefix = history.load_line(workout)
    if prefix:
        if event_description:
            event_description = f"{prefix}\n\n{event_description}"
        else:
            event_description = prefix

    # The intensity target, rendered FROM the planned-zone columns here and never
    # stored, so the sentence cannot drift from the columns it describes
    # (DESIGN_intensity_distribution.md §9.8).
    target = intensity.format_planned_zones(workout)
    if target:
        event_description = (
            f"{event_description}\n\n{target}" if event_description else target
        )

    # Lifecycle footer: before the history, because it describes this form of the
    # session, not the earlier ones (DESIGN_calendar_lineage.md §5). The load it was
    # planned with is not repeated here — the oldest history entry carries it.
    footer_lines: List[str] = []
    lifecycle_parts = []
    created_at = workout.get('created_at')
    adapted_at = workout.get('adapted_at')
    adaptation_count = workout.get('adaptation_count') or 0
    if created_at:
        lifecycle_parts.append(f"Planned: {fmt_timestamp(created_at)}")
    if adapted_at:
        lifecycle_parts.append(f"Last adapted: {fmt_timestamp(adapted_at)}")
    if adaptation_count:
        lifecycle_parts.append(f"Adapted ×{adaptation_count}")
    if lifecycle_parts:
        footer_lines.append(" · ".join(lifecycle_parts))

    # Append an identifier footer so each event stays traceable back to the plan
    # that produced it: goal/macro/meso are resolved from the workout's date, the
    # workout id comes from the row itself.
    id_parts = []
    ids = runtime.db.get_periodization_ids_for_date(date_str)
    if ids:
        objective_id, macrocycle_id, mesocycle_id = ids
        id_parts.append(f"Goal: {objective_id}")
        id_parts.append(f"Macro: {macrocycle_id}")
        id_parts.append(f"Meso: {mesocycle_id}")
    workout_id = workout.get('id')
    if workout_id is not None:
        id_parts.append(f"Workout: {workout_id}")
    if id_parts:
        footer_lines.append(" | ".join(id_parts))

    footer = "\n".join(footer_lines)

    # Prepend the adherence header so the verdict + actual effort sit at the top
    # of a past event's description, above the planned Duration/TSS and body.
    header = ""
    if adherence:
        status = adherence.get("status")
        tag = ADHERENCE_TAGS.get(status, status)
        header_lines = [f"Adherence: {tag}"]
        actual = adherence.get("actual")
        if actual:
            header_lines.append(f"Actual: {actual}")
        reasons = adherence.get("reasons") or []
        if reasons:
            header_lines.append(f"Notes: {', '.join(reasons)}")
        header = "\n".join(header_lines)

    # Every earlier form of this session, newest first — the event is the only place
    # the athlete can ask "what was this before?" without a terminal
    # (DESIGN_calendar_lineage.md §2). Placed last and sized last because it is the
    # part that yields: it takes the space the rest of the event does not need, so a
    # long prescription is never the thing that gets cut (§7).
    spare = history.MAX_DESCRIPTION - len(header) - len(event_description)
    earlier = history.for_workout(workout, budget=spare - len(footer) - 8)

    event_description = "\n\n".join(
        part for part in (header, event_description, footer, earlier) if part
    )

    body: Dict[str, Any] = {
        'summary': summary,
        'description': event_description,
        'start': {
            'date': date_str,
        },
        'end': {
            'date': end_date_str,
        },
        # Add metadata tag to identify Stamind events
        'extendedProperties': {
            'private': {
                'source': WORKOUT_EVENT_TAG,
                'sport_type': workout['sport_type'],
            }
        }
    }
    return body
