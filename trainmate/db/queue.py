"""The athlete queue's rows (DESIGN_athlete_queue.md §3).

Every instant is stored in one form, UTC to the microsecond, so `queued_at` and `remind_at`
compare as strings in time order.
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
    item asks; `trainmate/athlete_queue.py` does (DESIGN_athlete_queue.md §8)."""

    def queue_item(
        self, kind: str, subject: str, payload: Dict[str, Any], queued_at: datetime
    ) -> Optional[int]:
        """Queues one item and returns its id, or None when this kind and subject were
        queued before, whether that item still waits or closed long ago (§3)."""
        with self._get_connection() as conn:
            cursor = conn.execute(
                "INSERT OR IGNORE INTO athlete_queue (kind, subject, payload, queued_at) "
                "VALUES (?, ?, ?, ?)",
                (kind, subject, json.dumps(payload), queue_stamp(queued_at)),
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
        """Every item still waiting, hidden ones included, in queue order."""
        with self._get_connection() as conn:
            rows = conn.execute(
                "SELECT * FROM athlete_queue WHERE closed_at IS NULL ORDER BY queued_at, id"
            ).fetchall()
            return [_item(row) for row in rows]

    def queue_walk(
        self, since: datetime, now: datetime, after: Optional[Dict[str, Any]] = None
    ) -> List[Dict[str, Any]]:
        """What the walk that started at `since` has left to show after `after`, in queue
        order: the items waiting, queued by `since`, and not hidden at `now` (§4)."""
        sql = (
            "SELECT * FROM athlete_queue WHERE closed_at IS NULL AND queued_at <= ? "
            "AND (remind_at IS NULL OR remind_at <= ?)"
        )
        params: List[Any] = [queue_stamp(since), queue_stamp(now)]
        if after is not None:
            # `after` is the row as it was read before the action: "after the others" has
            # moved it since, and the walk goes on from where it stood.
            sql += " AND (queued_at > ? OR (queued_at = ? AND id > ?))"
            params += [after["queued_at"], after["queued_at"], after["id"]]
        with self._get_connection() as conn:
            rows = conn.execute(sql + " ORDER BY queued_at, id", params).fetchall()
            return [_item(row) for row in rows]

    def due_queue_items(self, now: datetime) -> List[Dict[str, Any]]:
        """The waiting items whose reminder time has passed, in queue order (§6.5)."""
        with self._get_connection() as conn:
            rows = conn.execute(
                "SELECT * FROM athlete_queue WHERE closed_at IS NULL "
                "AND remind_at IS NOT NULL AND remind_at <= ? ORDER BY queued_at, id",
                (queue_stamp(now),),
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

    def requeue_queue_item(self, item_id: int, at: datetime) -> None:
        """Puts a waiting item behind everything else: "after the others" (§4)."""
        with self._get_connection() as conn:
            conn.execute(
                "UPDATE athlete_queue SET queued_at = ?, remind_at = NULL "
                "WHERE id = ? AND closed_at IS NULL",
                (queue_stamp(at), item_id),
            )
            conn.commit()

    def set_queue_reminder(self, item_id: int, remind_at: Optional[datetime]) -> None:
        """Hides a waiting item until `remind_at`, or clears its reminder with None."""
        stamp = queue_stamp(remind_at) if remind_at is not None else None
        with self._get_connection() as conn:
            conn.execute(
                "UPDATE athlete_queue SET remind_at = ? WHERE id = ? AND closed_at IS NULL",
                (stamp, item_id),
            )
            conn.commit()
