"""The athlete's time, and how a day is written.

Three things live here. The athlete's timezone, which is where "now" comes from. The
day as the rest of the app says it: `today_str`, `fmt_date`, `fmt_span`. And the plain
arithmetic on an ISO date — one parser, one range, one shift — which used to be copied
into seven modules that each wanted a date a week ago.

See DESIGN_user_timezone.md. The `settings.timezone` row holds an IANA zone name and is
written by `tm settings set timezone`; with no row the machine's own zone rules (§3).
`today_date()` sits on every code path, so the handle is read as `runtime.db` at call
time — importing this module must never open the database.
"""

import sqlite3
from datetime import date, datetime, timedelta, timezone
from typing import List, Optional
from zoneinfo import ZoneInfo, available_timezones

from trainmate import runtime

TIMEZONE_SETTING = "timezone"

# The resolved zone, or None for "follow the machine". Resolved once per process because
# today_date() asks on every call; `reset_cache` is the registry's hook after a write.
_UNRESOLVED = object()
_zone: object = _UNRESOLVED


def stored_name() -> Optional[str]:
    """The zone name stored in the database, or None when the machine's zone rules."""
    return runtime.db.get_setting(TIMEZONE_SETTING)


def stored_at() -> Optional[str]:
    """UTC ISO instant the stored zone was last written, or None if nothing is stored."""
    row = runtime.db.get_setting_row(TIMEZONE_SETTING)
    return row["updated_at"] if row else None


def reset_cache() -> None:
    """Drops the resolved zone so the next date call re-reads the setting."""
    global _zone
    _zone = _UNRESOLVED


def active_zone() -> Optional[ZoneInfo]:
    """The zone every date is computed in, or None to follow the machine (§3)."""
    global _zone
    if _zone is not _UNRESOLVED:
        return _zone  # type: ignore[return-value]
    try:
        name = stored_name()
    except sqlite3.Error:
        # today_date() sits on every code path, so a database that momentarily cannot be
        # read degrades to the machine's zone for this call rather than taking the command
        # down — and is not cached, so the next call tries again (§3).
        return None
    _zone = _resolve_stored(name)
    return _zone  # type: ignore[return-value]


def _resolve_stored(name: Optional[str]) -> Optional[ZoneInfo]:
    """The stored name as a zone. A name this machine's tzdata does not carry warns and
    falls back rather than aborting every command (§3)."""
    if not name:
        return None
    try:
        return ZoneInfo(name)
    except (KeyError, ValueError):
        # Safe to journal from here even though `active_zone`'s cache is still unset:
        # the journal takes its day and its timestamps from the system clock and imports
        # nothing from this module, so nothing asks for the zone again
        # (DESIGN_logging.md §5.3).
        from trainmate.output import warn
        from trainmate.text import cmd
        warn(
            f"stored timezone '{name}' is unknown on this machine — using the "
            f"machine's own timezone. Set a valid one with "
            f"{cmd('settings set timezone <zone>')}."
        )
        return None


def now() -> datetime:
    """The current instant, aware, in the athlete's zone. The one clock every "what day is
    it" computation reads (`today_date` below)."""
    zone = active_zone()
    return datetime.now(zone) if zone else datetime.now().astimezone()


# When the running command started, to the second; None between commands. A walk of the
# athlete queue and every item a command queues are dated by it, and the queue's buttons
# carry it in whole seconds (DESIGN_athlete_queue.md §4, §6.2).
_command_start: Optional[datetime] = None


def start_command() -> None:
    """Stamps the start of the command `trainmate_cli.run_once` is about to run."""
    global _command_start
    _command_start = now().replace(microsecond=0)


def end_command() -> None:
    global _command_start
    _command_start = None


def command_start() -> datetime:
    """When the running command started, or this second outside a command."""
    return _command_start or now().replace(microsecond=0)


def to_local(dt: datetime) -> datetime:
    """Moves an instant into the athlete's zone for display. A naive value is read as UTC,
    which is what every stored timestamp column holds (§5)."""
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    zone = active_zone()
    return dt.astimezone(zone) if zone else dt.astimezone()


def offset_label(dt: Optional[datetime] = None) -> str:
    """The zone's UTC offset at `dt` (default: now) as 'UTC+02:00'."""
    moment = dt or now()
    raw = moment.strftime("%z") or "+0000"
    return f"UTC{raw[:3]}:{raw[3:5]}"


def describe() -> str:
    """The active zone as one display string: the stored name, or what the machine says
    when nothing is stored — no IANA name is invented for the machine's zone (§3)."""
    zone = active_zone()
    if zone is not None:
        return str(zone)
    local = datetime.now().astimezone()
    return f"the machine's timezone ({local.tzname()}, {offset_label(local)})"


def today_date() -> date:
    """Returns today's date in the athlete's timezone (DESIGN_user_timezone.md §1).

    Garmin keys daily metrics and activities on the athlete's local calendar
    date, so every "what day is it" computation must use local time rather than
    UTC (a UTC frontier drifts a day at the boundary hours). Instants stored for
    comparison (created_at, last-pull timestamps) stay in UTC elsewhere.
    """
    return now().date()


def day_str(value: date) -> str:
    """Returns a date as a YYYY-MM-DD string — the inverse of `parse_date`."""
    return value.strftime("%Y-%m-%d")


def today_str() -> str:
    """Returns today's local calendar date as a YYYY-MM-DD string."""
    return day_str(today_date())


def days_between(start: str, end: str) -> int:
    """Returns whole days from `start` to `end` (both YYYY-MM-DD), negative if end precedes it."""
    return (parse_date(end) - parse_date(start)).days


def fmt_date(date_str: Optional[str]) -> str:
    """Renders a YYYY-MM-DD date as 'YYYY-MM-DD Ddd' (e.g. '2026-06-05 Fri').

    The one date renderer for every surface with room for the weekday. Falls back to
    the raw string when the value isn't a parseable date, so a caller can hand this
    whatever a row happens to hold."""
    if not date_str:
        return "?"
    try:
        return parse_date(str(date_str)).strftime("%Y-%m-%d %a")
    except ValueError:
        return str(date_str)


def fmt_span(start: Optional[str], end: Optional[str], sep: str = " to ") -> str:
    """Renders a date range with the weekday on both ends. A range that starts and
    ends on the same day collapses to that one date."""
    if start and end and start == end:
        return fmt_date(start)
    return f"{fmt_date(start)}{sep}{fmt_date(end)}"


def fmt_timestamp(iso: Optional[str]) -> str:
    """Renders a stored UTC ISO timestamp as 'YYYY-MM-DD Ddd HH:MM' in the athlete's
    timezone — stored precise, converted only on display (DESIGN_user_timezone.md §5).

    Falls back to the raw string if it isn't parseable (e.g. a date-only legacy value)."""
    if not iso:
        return "?"
    try:
        return to_local(datetime.fromisoformat(iso)).strftime("%Y-%m-%d %a %H:%M")
    except ValueError:
        return iso


def parse_date(date_str: str) -> date:
    """An ISO `YYYY-MM-DD` string as a date, raising ValueError on anything else.

    Every date TrainMate stores is written this way, so one parser serves them all."""
    return datetime.strptime(date_str, "%Y-%m-%d").date()


def date_range(start: str, end: str) -> List[str]:
    """Every ISO date from `start` to `end`, both ends included. Empty when `end` falls
    before `start`."""
    out: List[str] = []
    cur, last = parse_date(start), parse_date(end)
    while cur <= last:
        out.append(cur.isoformat())
        cur += timedelta(days=1)
    return out


def shift(date_str: str, days: int) -> str:
    """`date_str` moved `days` forward (backward when negative), as an ISO date."""
    return (parse_date(date_str) + timedelta(days=days)).isoformat()


def resolve(token: str) -> str:
    """Maps a `settings set timezone` argument to a canonical IANA zone name.

    Matching is case-insensitive, so 'europe/paris' lands on 'Europe/Paris'. Raises
    ValueError with a ready-to-print message — naming a city or a region lists the zones
    that contain it, which is how an athlete finds their own name (§4)."""
    name = (token or "").strip()
    if not name:
        raise ValueError("Name a timezone, e.g. 'Europe/Paris'.")
    zones = available_timezones()
    if name in zones:
        return name
    by_lower = {zone.lower(): zone for zone in zones}
    if name.lower() in by_lower:
        return by_lower[name.lower()]
    near = sorted(zone for zone in zones if name.lower() in zone.lower())
    if not near:
        raise ValueError(
            f"'{name}' is not a known timezone. Names look like 'Europe/Paris' or "
            "'America/New_York'; search with part of a city or region name."
        )
    shown = near[:12]
    listing = "\n".join(f"  {zone}" for zone in shown)
    more = f"\n  ... and {len(near) - len(shown)} more" if len(near) > len(shown) else ""
    raise ValueError(f"'{name}' is not a timezone name. Did you mean:\n{listing}{more}")
