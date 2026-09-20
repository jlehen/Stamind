"""Two of the three things that can be true of a planned session at once.

ARCHITECTURE §5 calls them orthogonal axes: what the athlete changed about a session
(`modification_markers`), and how far its Calendar event has fallen behind
(`calendar_status`). The third axis, what became of it, is the adherence verdict and
lives with the maths that decides it.

The two sit together because every surface that shows one shows the other, and
because neither reads the database: both are derived from a workout row the caller
already has. That is what lets the read-only web app import this module without
pulling the CLI in behind it (REORG_code_layout.md §4.3).

The calendar half works like this. The freshness of a workout's Google Calendar event is
*derived*, not stored: on
a successful push we record `pushed_signature` = a hash of exactly the fields
that determine the rendered event. The current state then falls out of a compare
against `calendar_signature(current_row)`:

    unpushed  google_event_id is NULL            (never sent to Calendar)
    synced    pushed_signature == current hash    (event matches local content)
    stale     pushed_signature != current hash    (edited since last push)

This replaces a hand-maintained `synced` boolean that every write path had to
remember to reset — miss it once and the calendar silently drifted. Now any edit
through any path leaves `pushed_signature` untouched and the row reads `stale`
automatically. `Workout` is a TypedDict, so these are free functions, not methods.
"""

import hashlib
import json
from typing import Literal

# Exactly the fields `gcal.event.event_body` renders into the event's
# summary/description. Deliberately EXCLUDES the periodization footer, which
# derives deterministically from the date and effectively never changes.
#
# `revision_id` stands in for the whole lineage the event now renders as its
# history: a lineage only changes by gaining a revision, so the live revision's
# id moves exactly when the `History` section does (DESIGN_calendar_lineage.md §6).
CALENDAR_FIELDS = (
    "revision_id", "date", "sport_type", "title", "description",
    "original_description", "modification_reason", "duration_minutes", "tss",
    "rpe", "removed", "removed_reason",
)

CalendarStatus = Literal["unpushed", "synced", "stale"]


def calendar_signature(workout) -> str:
    """Stable hash of the calendar-relevant fields of a workout."""
    payload = []
    for field in CALENDAR_FIELDS:
        value = workout.get(field)
        if field == "removed":
            value = bool(value)  # normalize 0/1/None/False to a stable bool
        payload.append(value)
    blob = json.dumps(payload, ensure_ascii=False, sort_keys=True)
    return hashlib.sha256(blob.encode("utf-8")).hexdigest()


def adherence_signature(workout, adherence) -> str:
    """Stable hash of a workout's calendar fields *plus* its backward-looking
    adherence verdict, as rendered by `workout compare --mark`.

    `mark_adherence_from_results` stores this on each adherence push and compares
    the prospective signature against it to skip a no-op Calendar update when the
    event already carries the same verdict. Kept distinct from `calendar_signature`
    (and stored in its own `adherence_pushed_signature` column) because the adherence verdict
    isn't a workout field — folding it into the freshness hash would make every
    marked past row read `stale`. `adherence` is the dict built in
    `mark_adherence_from_results`: ``{"status", "actual", "reasons"}``.
    """
    payload = [calendar_signature(workout)]
    payload.append(adherence.get("status") if adherence else None)
    payload.append(adherence.get("actual") if adherence else None)
    payload.append(list(adherence.get("reasons") or []) if adherence else None)
    blob = json.dumps(payload, ensure_ascii=False, sort_keys=True)
    return hashlib.sha256(blob.encode("utf-8")).hexdigest()


def calendar_status(workout) -> CalendarStatus:
    """Derives {unpushed, synced, stale} from the row's stored signature."""
    if not workout.get("google_event_id"):
        return "unpushed"
    if workout.get("pushed_signature") == calendar_signature(workout):
        return "synced"
    return "stale"


# The change kind of a session's live revision, as the athlete reads it
# (DESIGN_workout_revisions.md §7). A `generate` is the plan saying what it says, so it
# gets no marker, and a void carries [REMOVED] instead.
_KIND_MARKERS = {
    'adapt': 'ADAPTED',
    'tweak': 'TWEAKED',
}


def modification_markers(w: dict) -> list:
    """What has happened to a session: the kind of its latest change, plus the easings
    that still stand.

    Two facts rather than one, which is why there is no precedence rule any more: a
    session eased twice and then copied forward by a rollback still reads `[ADAPTED ×2]`
    (§12)."""
    kind = w.get('change_kind')
    count = w.get('adaptation_count') or 0
    eased = f"ADAPTED ×{count}" if count > 1 else ("ADAPTED" if count else "")
    if kind == 'adapt':
        # The tally is the whole story here; an adapt that eased nothing still reads
        # [ADAPTED], because the prescription did change.
        return [eased or "ADAPTED"]
    return [m for m in (_KIND_MARKERS.get(kind), eased) if m]
