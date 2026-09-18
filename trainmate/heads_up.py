"""Telling the athlete when the week changes out of their sight (DESIGN_change_heads_up.md).

A change `workout generate` or `workout adapt` makes while the athlete is not watching waits
in `workout_changes` until the bot tells them (§6): at their next morning time, unless the
operator runs `workout notify`. This module holds the wording (§3), the one rule for when
the bot's scheduler sends (§4), and when the terminal says the line will go out (§8), so the
scheduler, `bot changes`, `workout notify` and the terminal notice read the same rule.
`trainmate.db` is reached through `runtime` at call time, so importing this module from the
database layer opens nothing.
"""
from datetime import datetime, timedelta
from typing import Any, Dict, List, Optional, Sequence

from trainmate import clock, runtime, settings
from trainmate.config import config

# Nothing is sent after this hour: a change the bot could not send at the morning time
# waits for the next morning (§4).
EVENING = "21:00"

# The id of the newest change `workout notify` asked the bot to send at once (§4).
NOTIFY_MARKER = "changes_notify_upto"

# English, as every fixed string in the companion is; the coach's own sentence follows in
# the athlete's language.
CHANGE_LEAD = "Your coach changed your week:"
UNDONE_ONE = "Your coach undid this change:"
UNDONE_SEVERAL = "Your coach undid these changes:"
UNDONE_PLAIN = "The change to your week was undone."


def undone_note(told: Sequence[Dict[str, Any]]) -> Optional[str]:
    """What a rollback tells the athlete, or None when it tells nothing (§6).

    `told` holds the changes the rollback undoes that the athlete was told about and that
    wrote a session dated today or later, oldest first. Each one's own line is quoted; a
    rollback among them is not."""
    if not told:
        return None
    quoted = [c["note"] for c in told if c["kind"] != "rollback" and c.get("note")]
    if not quoted:
        return UNDONE_PLAIN
    if len(quoted) == 1:
        return f"{UNDONE_ONE} {quoted[0]}"
    return UNDONE_SEVERAL + "\n" + "\n".join(f"- {line}" for line in quoted)


def message(change: Dict[str, Any]) -> str:
    """The message `bot changes` sends for one waiting change: a rollback's line as it is,
    any other line after the lead (§6)."""
    if change["kind"] == "rollback":
        return change["note"]
    return f"{CHANGE_LEAD} {change['note']}"


def _at(moment: datetime, hhmm: str) -> datetime:
    """`moment`'s day at the local time `hhmm`."""
    hours, minutes = settings.parse_hhmm(hhmm).split(":")
    return moment.replace(hour=int(hours), minute=int(minutes), second=0, microsecond=0)


def _made_at(change: Dict[str, Any]) -> datetime:
    return clock.to_local(datetime.fromisoformat(change["created_at"]))


def due(
    waiting: Sequence[Dict[str, Any]], now: datetime, morning: str,
    notify_upto: Optional[int],
) -> bool:
    """Whether the scheduler sends the waiting changes on this wake (§4).

    At once when `workout notify` asked for a change that is still waiting. Otherwise from
    the morning time to the evening, once one of them was made before this morning's
    morning time: a change made later in the day waits for the next morning."""
    if not waiting:
        return False
    if notify_upto is not None and any(c["id"] <= notify_upto for c in waiting):
        return True
    morning_at = _at(now, morning)
    if not morning_at <= now < _at(now, EVENING):
        return False
    return any(_made_at(c) < morning_at for c in waiting)


def sends_at(now: datetime, morning: str) -> datetime:
    """When a change made now reaches the athlete unless `workout notify` sends it sooner:
    this morning's morning time while it is still ahead, else tomorrow's (§8)."""
    morning_at = _at(now, morning)
    if now < morning_at:
        return morning_at
    return morning_at + timedelta(days=1)


def waiting() -> List[Dict[str, Any]]:
    """The changes waiting to be told, oldest first. None outside companion mode, where
    the athlete is the operator (§2)."""
    if config.telegram_ui != "simple":
        return []
    return runtime.db.waiting_changes()


def _notify_upto() -> Optional[int]:
    try:
        return int(runtime.db.get_setting(NOTIFY_MARKER) or "")
    except ValueError:
        return None


def changes_due() -> bool:
    """The check the bot's scheduler makes on each wake (§4)."""
    return due(waiting(), clock.now(), settings.morning_time(), _notify_upto())
