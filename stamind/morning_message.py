"""When the morning message goes out (DESIGN_morning_waits_for_night.md): the marker that
says it went out today, the two-hour mark after which it stops waiting for the night, and
the window in which the bot's scheduler tries it.

The message itself is `sm bot morning` (`cli/bot/views.py`), and the scheduler that tries
it is `chat/scheduler.py`.
"""
from datetime import datetime
from typing import Optional, Tuple

from stamind import clock, runtime, settings

# Not a setting: the moment `bot morning` last sent, on the athlete's clock, kept in the
# `settings` table so the bot process stays stateless across restarts
# (DESIGN_bot_simple_frontend.md §4.2). Its first ten characters are the day, so a value
# written before it held the moment, the day alone, still reads right (§5).
MARKER = "push_morning_last"

# The message waits for the night at most this long after morning-time (§2, §7 choice 1).
NIGHT_WAIT_MINUTES = 120
# The window stays open this long past that mark, so the try at the mark has a wake to start
# on: the scheduler wakes every one to five minutes (§5, §7 choice 13).
LAST_TRY_MINUTES = 10


def sent_on(day: str) -> bool:
    """Whether the morning message of `day` (YYYY-MM-DD) went out."""
    return (runtime.db.get_setting(MARKER) or "")[:10] == day


def sent_at() -> Optional[datetime]:
    """The moment the last morning message went out, or None when the marker holds no
    moment."""
    raw = runtime.db.get_setting(MARKER) or ""
    if len(raw) <= len("YYYY-MM-DD"):
        return None
    return datetime.fromisoformat(raw)


def mark_sent() -> None:
    """Records the moment today's morning message went out."""
    runtime.db.set_setting(MARKER, clock.now().isoformat())


def _later(hhmm: str, minutes: int) -> str:
    """`hhmm` plus `minutes`, at most 23:59: a morning never runs into the next day."""
    hours, mins = settings.parse_hhmm(hhmm).split(":")
    total = min(int(hours) * 60 + int(mins) + minutes, 23 * 60 + 59)
    return f"{total // 60:02d}:{total % 60:02d}"


def night_deadline() -> str:
    """Local HH:MM from which the message goes out without the night: two hours after
    morning-time (§2)."""
    return _later(settings.morning_time(), NIGHT_WAIT_MINUTES)


def window() -> Tuple[str, str]:
    """Local HH:MM between which the scheduler tries the message: from earliest-morning when
    it is on, before morning-time, and the message waits for the night, else from
    morning-time; to the later of morning-deadline and ten minutes past the two-hour mark
    (§5)."""
    opens = settings.morning_time()
    earliest = settings.earliest_morning()
    if settings.adapt_first() and earliest is not None and earliest < opens:
        opens = earliest
    closes = max(settings.morning_deadline(), _later(night_deadline(), LAST_TRY_MINUTES))
    return opens, closes
