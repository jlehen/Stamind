"""The athlete queue's rows (DESIGN_athlete_queue.md §3).

Every instant is stored in one form, UTC to the microsecond, so `queued_at`, `ready_at` and
`sent_at` compare as strings in time order.
"""
import json
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional


def queue_stamp(moment: datetime) -> str:
    """The one stored form of a queue instant."""
    return moment.astimezone(timezone.utc).isoformat(timespec="microseconds")


def _item(row) -> Dict[str, Any]:
    item = dict(row)
    item["payload"] = json.loads(item["payload"])
    return item


class QueueMixin:
    """Questions and messages waiting for the athlete. The rows know nothing about what an
    item asks; `stamind/athlete_queue.py` does (DESIGN_athlete_queue.md §8)."""

    def queue_item(
        self, kind: str, subject: str, payload: Dict[str, Any], queued_at: datetime
    ) -> Optional[int]:
        """Queues one item, ready from the moment it is queued, and returns its id, or None
        when this kind and subject were queued before, whether that item still waits or
        closed long ago (§3, §13.2)."""
        stamp = queue_stamp(queued_at)
        with self._get_connection() as conn:
            cursor = conn.execute(
                "INSERT OR IGNORE INTO athlete_queue "
                "(kind, subject, payload, queued_at, ready_at) VALUES (?, ?, ?, ?, ?)",
                (kind, subject, json.dumps(payload), stamp, stamp),
            )
            conn.commit()
            return cursor.lastrowid if cursor.rowcount else None

    def get_queue_item(self, item_id: int) -> Optional[Dict[str, Any]]:
        with self._get_connection() as conn:
            row = conn.execute(
                "SELECT * FROM athlete_queue WHERE id = ?", (item_id,)
            ).fetchone()
            return _item(row) if row else None

    def waiting_queue_items(self) -> List[Dict[str, Any]]:
        """Every item still waiting, in the order they become ready: the line, then the
        items put off until a time still ahead (§13.2)."""
        with self._get_connection() as conn:
            rows = conn.execute(
                "SELECT * FROM athlete_queue WHERE closed_at IS NULL ORDER BY ready_at, id"
            ).fetchall()
            return [_item(row) for row in rows]

    def queue_items_since(self, kind: str, since: datetime) -> List[Dict[str, Any]]:
        """Every item of one kind queued from `since` on, waiting or closed, oldest first."""
        with self._get_connection() as conn:
            rows = conn.execute(
                "SELECT * FROM athlete_queue WHERE kind = ? AND queued_at >= ? "
                "ORDER BY queued_at, id",
                (kind, queue_stamp(since)),
            ).fetchall()
            return [_item(row) for row in rows]

    def closed_queue_items(self) -> List[Dict[str, Any]]:
        """Every closed item, in the order they closed (§5.1)."""
        with self._get_connection() as conn:
            rows = conn.execute(
                "SELECT * FROM athlete_queue WHERE closed_at IS NOT NULL "
                "ORDER BY closed_at, id"
            ).fetchall()
            return [_item(row) for row in rows]

    def close_queue_item(self, item_id: int, outcome: str, at: datetime) -> bool:
        """Closes a waiting item with its outcome. False when it was already closed."""
        with self._get_connection() as conn:
            cursor = conn.execute(
                "UPDATE athlete_queue SET closed_at = ?, outcome = ? "
                "WHERE id = ? AND closed_at IS NULL",
                (queue_stamp(at), outcome, item_id),
            )
            conn.commit()
            return cursor.rowcount > 0

    def set_queue_ready(self, item_id: int, ready_at: datetime) -> None:
        """Moves a waiting item's ready time. It is no longer out: it takes its turn again
        once that time has passed (§13.2)."""
        with self._get_connection() as conn:
            conn.execute(
                "UPDATE athlete_queue SET ready_at = ?, sent_at = NULL "
                "WHERE id = ? AND closed_at IS NULL",
                (queue_stamp(ready_at), item_id),
            )
            conn.commit()

    def mark_queue_sent(self, item_id: int, at: Optional[datetime]) -> None:
        """Records that a waiting item was put in front of the athlete at `at`, or with
        None that it no longer is (§13.2)."""
        stamp = queue_stamp(at) if at is not None else None
        with self._get_connection() as conn:
            conn.execute(
                "UPDATE athlete_queue SET sent_at = ? WHERE id = ? AND closed_at IS NULL",
                (stamp, item_id),
            )
            conn.commit()
