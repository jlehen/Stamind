"""The sets of strength activities, read from Garmin (DESIGN_strength_tracking.md §5).

Every instant is stored as the athlete queue stores its own (`db/queue.py::queue_stamp`),
UTC to the microsecond, because the freeze time is part of a queued subject (§7).
"""
from datetime import datetime
from typing import Any, Dict, List, Optional, Sequence

from trainmate.db.queue import queue_stamp

# The raw Garmin type a strength activity is recorded under (§3). The sport table folds
# `fitness` and `indoor_cardio` into strength too; the sets are read for this type only.
STRENGTH_TYPE = "strength_training"

ACTIVE = "active"
REST = "rest"


class StrengthMixin:
    """Exercise sets hanging off a Garmin activity, and the three columns that say whether
    they were read, frozen or discarded."""

    def get_completed_activity(self, activity_id: str) -> Optional[Dict[str, Any]]:
        with self._get_connection() as conn:
            row = conn.execute(
                "SELECT * FROM completed_activities WHERE activity_id = ?", (activity_id,)
            ).fetchone()
            return dict(row) if row else None

    def strength_activities(
        self, since: str, before: Optional[str] = None, date: Optional[str] = None,
        unread: bool = False,
    ) -> List[Dict[str, Any]]:
        """Raw strength activities dated from `since` (and before `before`, or on `date`),
        oldest first; `unread` keeps those whose sets were never read (§6)."""
        sql = "SELECT * FROM completed_activities WHERE activity_type = ? AND date >= ?"
        params: List[Any] = [STRENGTH_TYPE, since]
        if before is not None:
            sql += " AND date < ?"
            params.append(before)
        if date is not None:
            sql += " AND date = ?"
            params.append(date)
        if unread:
            sql += " AND sets_read_at IS NULL"
        with self._get_connection() as conn:
            rows = conn.execute(sql + " ORDER BY date, start_time", params).fetchall()
            return [dict(row) for row in rows]

    def store_exercise_sets(
        self, activity_id: str, sets: Sequence[Dict[str, Any]], read_at: datetime,
        final_at: Optional[datetime],
    ) -> None:
        """Replaces an activity's sets with what Garmin returned and stamps the read, and
        the freeze when `final_at` is given (§6)."""
        with self.transaction() as conn:
            conn.execute("DELETE FROM exercise_sets WHERE activity_id = ?", (activity_id,))
            conn.executemany(
                "INSERT INTO exercise_sets (activity_id, seq, set_type, exercise, garmin_name, "
                "reps, load_kg, duration_sec, named_by) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
                [
                    (activity_id, s["seq"], s["set_type"], s.get("exercise"),
                     s.get("garmin_name"), s.get("reps"), s.get("load_kg"),
                     s.get("duration_sec"), s.get("named_by"))
                    for s in sets
                ],
            )
            conn.execute(
                "UPDATE completed_activities SET sets_read_at = ?, sets_final_at = ? "
                "WHERE activity_id = ?",
                (queue_stamp(read_at), queue_stamp(final_at) if final_at else None,
                 activity_id),
            )

    def get_exercise_sets(self, activity_id: str) -> List[Dict[str, Any]]:
        """An activity's sets in the order Garmin recorded them, rest entries included."""
        with self._get_connection() as conn:
            rows = conn.execute(
                "SELECT * FROM exercise_sets WHERE activity_id = ? ORDER BY seq",
                (activity_id,),
            ).fetchall()
            return [dict(row) for row in rows]

    def freeze_exercise_sets(self, activity_id: str, at: datetime) -> None:
        with self._get_connection() as conn:
            conn.execute(
                "UPDATE completed_activities SET sets_final_at = ? WHERE activity_id = ?",
                (queue_stamp(at), activity_id),
            )
            conn.commit()

    def name_exercise_sets(
        self, activity_id: str, seqs: Sequence[int], exercise: Optional[str]
    ) -> None:
        """Names the sets at `seqs` as a person's answer, or clears their name with None
        (§7). Nothing else sets `named_by = athlete`."""
        named_by = "athlete" if exercise else None
        with self._get_connection() as conn:
            conn.executemany(
                "UPDATE exercise_sets SET exercise = ?, named_by = ? "
                "WHERE activity_id = ? AND seq = ?",
                [(exercise, named_by, activity_id, seq) for seq in seqs],
            )
            conn.commit()

    def set_activity_discarded(self, activity_id: str, discarded: bool) -> None:
        with self._get_connection() as conn:
            conn.execute(
                "UPDATE completed_activities SET discarded = ? WHERE activity_id = ?",
                (1 if discarded else 0, activity_id),
            )
            conn.commit()

    def activity_exercises_by_day(self) -> List[Dict[str, Any]]:
        """Every active set of every activity that was not discarded, newest day first:
        `{date, exercise}` rows, what the recent-exercises answers count (§7)."""
        with self._get_connection() as conn:
            rows = conn.execute(
                "SELECT a.date, s.exercise FROM exercise_sets s "
                "JOIN completed_activities a ON a.activity_id = s.activity_id "
                "WHERE s.set_type = ? AND a.discarded = 0 ORDER BY a.date DESC, s.seq",
                (ACTIVE,),
            ).fetchall()
            return [dict(row) for row in rows]
