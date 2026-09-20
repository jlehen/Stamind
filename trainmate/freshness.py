"""How fresh is fresh enough, for the two things TrainMate pulls from elsewhere.

The age of the last pull and the line that announces a cache hit, shared by `garmin/` and
`gcal/`. What is deliberately *not* here is the decision each one makes from that age;
ARCHITECTURE.md §15 says why it stayed with the callers, and why this module is flat.
"""
from datetime import datetime, timedelta, timezone
from typing import Any, Mapping, Optional

from trainmate.output import step


def last_pull_age(state: Optional[Mapping[str, Any]]) -> Optional[timedelta]:
    """How long ago this sync last pulled, from its `sync_state` row.

    None when it never has, or when the stored timestamp will not parse — both of which
    every caller reads as "not fresh", so a corrupt row costs a re-fetch and nothing more.
    """
    stamp = (state or {}).get("last_pull_utc")
    if not stamp:
        return None
    try:
        return datetime.now(timezone.utc) - datetime.fromisoformat(stamp)
    except (ValueError, TypeError):
        return None


def age_minutes(age: timedelta) -> int:
    """An age in whole minutes, as both callers word it. Truncated: "0m ago" means seconds."""
    return int(age.total_seconds() // 60)


def fresh_notice(what: str, detail: str) -> None:
    """Say that a throttle, not a lack of work, is why nothing was fetched.

    Without this line the reuse is opaque: the command simply looks fast. `what` names
    the data ("Garmin data"), `detail` says how it was judged ("last sync 3m ago").
    """
    step(f"{what} is fresh ({detail}); using cache. Pass --force-pull to refresh now.")
