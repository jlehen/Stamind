"""The reminder to enter an RPE in Garmin, for a session whose heart rate data cannot measure
its load (`analytics.load.compute_load`, ARCHITECTURE.md §15). Apart from `cli/bot/views.py`
to break the cycle through `athlete_queue.py`."""
from typing import Any, Dict

from stamind import runtime
from stamind.analytics.load import compute_load
from stamind.clock import fmt_day, shift
from stamind.queue_kind import MESSAGE, Kind, queue

KIND = "rpe_reminder"


def _wording(item: Dict[str, Any]) -> str:
    return item["payload"]["text"]


def _is_stale(item: Dict[str, Any]) -> bool:
    """The RPE reached a pull while the reminder waited, or the activity was deleted."""
    activity = runtime.db.get_completed_activity(item["subject"])
    return activity is None or bool(activity.get("rpe"))


RPE_REMINDER_KIND = Kind(
    name=KIND, shape=MESSAGE, wording=_wording, companion_wording=_wording,
    is_stale=_is_stale, apply=lambda item, index, text: None,
)


def queue_reminders(today: str) -> None:
    """Queues the reminder for each activity of today and yesterday that needs an RPE, once
    per activity. A gym log's placeholder is not in Garmin, so it is left out."""
    for activity in runtime.db.get_completed_activities(shift(today, -1), today):
        if activity["activity_id"].startswith("log:"):
            continue
        duration_sec = activity.get("duration_sec") or 0.0
        if not compute_load(activity, activity, activity.get("rpe"), duration_sec)[2]:
            continue
        name = activity.get("activity_name") or activity.get("activity_type")
        queue(KIND, activity["activity_id"], {"text": (
            f"Please enter the RPE of your {duration_sec / 60:.0f}-minute {name} of "
            f"{fmt_day(activity['date'])} in Garmin. Its heart rate data is too thin to "
            "measure the effort."
        )})
