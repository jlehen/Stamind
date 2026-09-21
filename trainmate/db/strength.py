"""The sets of strength activities, read from Garmin (DESIGN_strength_tracking.md §5),
and what the strength planner prescribed for a planned session (§9).

Every instant is stored as the athlete queue stores its own (`db/queue.py::queue_stamp`),
UTC to the microsecond, because the freeze time is part of a queued subject (§7).
"""
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional, Sequence

from trainmate.db.queue import queue_stamp

# The raw Garmin type a strength activity is recorded under (§3). The sport table folds
# `fitness` and `indoor_cardio` into strength too; the sets are read for this type only.
STRENGTH_TYPE = "strength_training"

ACTIVE = "active"
REST = "rest"

# Who named a set (§5). GARMIN is a person's pick in Garmin Connect or on the watch
# face; ATHLETE is an answer they gave TrainMate; WATCH is the watch's own guess.
# Only the two a person left reach the strength history and the naming answers
# (§5, §8), which is what `NAMED_BY_PERSON` is for — it is built from them rather
# than spelling the same two strings twice.
GARMIN = "garmin"
ATHLETE = "athlete"
WATCH = "watch"
NAMED_BY_PERSON = (GARMIN, ATHLETE)

# When the strength history last changed, in the settings table: code writes it, the
# athlete never edits it, and the strength planner reads it as its evidence (§5, §9).
HISTORY_STAMP_KEY = "strength_history_changed_at"


def _person_marks() -> str:
    """The `?` placeholders for NAMED_BY_PERSON, so the two never fall out of step."""
    return ",".join("?" * len(NAMED_BY_PERSON))


class StrengthMixin:
    """Exercise sets hanging off a Garmin activity, and the three columns that say whether
    they were read, frozen or discarded."""

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

    def bump_strength_history(self) -> None:
        """Records that the strength history now shows something different, which is the
        new evidence a kept session's kilograms may change on (§9)."""
        self.set_setting(HISTORY_STAMP_KEY, datetime.now(timezone.utc).isoformat())

    def strength_history_stamp(self) -> str:
        """When the strength history last changed; "" when nothing ever changed it."""
        return self.get_setting(HISTORY_STAMP_KEY) or ""

    def store_exercise_sets(
        self, activity_id: str, sets: Sequence[Dict[str, Any]], read_at: datetime,
        final_at: Optional[datetime],
    ) -> None:
        """Replaces an activity's sets with what Garmin returned and stamps the read, and
        the freeze when `final_at` is given (§6)."""
        if sets:
            self.bump_strength_history()
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
        self.bump_strength_history()

    def name_exercise_sets(
        self, activity_id: str, seqs: Sequence[int], exercise: Optional[str]
    ) -> None:
        """Names the sets at `seqs` as a person's answer, or clears their name with None
        (§7). Nothing else sets `named_by = athlete`."""
        named_by = ATHLETE if exercise else None
        with self._get_connection() as conn:
            conn.executemany(
                "UPDATE exercise_sets SET exercise = ?, named_by = ? "
                "WHERE activity_id = ? AND seq = ?",
                [(exercise, named_by, activity_id, seq) for seq in seqs],
            )
            conn.commit()
        self.bump_strength_history()

    def confirm_watch_names(self, activity_id: str) -> int:
        """Makes the watch's guesses still standing in an activity the athlete's own, which
        is what "yes, final" and `strength reset` say about them (§6). Returns how many."""
        with self._get_connection() as conn:
            cursor = conn.execute(
                "UPDATE exercise_sets SET named_by = ? "
                "WHERE activity_id = ? AND named_by = ?",
                (ATHLETE, activity_id, WATCH),
            )
            conn.commit()
            confirmed = cursor.rowcount
        if confirmed:
            self.bump_strength_history()
        return confirmed

    def set_activity_discarded(self, activity_id: str, discarded: bool) -> None:
        with self._get_connection() as conn:
            conn.execute(
                "UPDATE completed_activities SET discarded = ? WHERE activity_id = ?",
                (1 if discarded else 0, activity_id),
            )
            conn.commit()
        self.bump_strength_history()

    def exercise_history(self) -> List[Dict[str, Any]]:
        """Every named active set of every activity that counts, oldest day first: the rows
        `strength log` reads (§7). Ordered so a day with two lifting activities reads as one
        day (§3). A name only the watch guessed is on the athlete's own record and marked
        there, which is what tells it apart from one she gave."""
        with self._get_connection() as conn:
            rows = conn.execute(
                "SELECT a.date, s.exercise, s.reps, s.load_kg, s.duration_sec, s.named_by "
                "FROM exercise_sets s "
                "JOIN completed_activities a ON a.activity_id = s.activity_id "
                "WHERE s.set_type = ? AND s.exercise IS NOT NULL AND a.discarded = 0 "
                "ORDER BY a.date, a.start_time, s.seq",
                (ACTIVE,),
            ).fetchall()
            return [dict(row) for row in rows]

    def activity_exercises_by_day(self) -> List[Dict[str, Any]]:
        """Every active set of every activity that was not discarded, newest day first:
        `{date, exercise}` rows, what the recent-exercises answers count (§7). A name only
        the watch guessed is not one of them, so a wrong guess never becomes an answer."""
        with self._get_connection() as conn:
            rows = conn.execute(
                "SELECT a.date, s.exercise FROM exercise_sets s "
                "JOIN completed_activities a ON a.activity_id = s.activity_id "
                "WHERE s.set_type = ? AND a.discarded = 0 "
                f"AND (s.named_by IS NULL OR s.named_by IN ({_person_marks()})) "
                "ORDER BY a.date DESC, s.seq",
                (ACTIVE,) + NAMED_BY_PERSON,
            ).fetchall()
            return [dict(row) for row in rows]

    def strength_set_rows(
        self, since: str, before: Optional[str] = None
    ) -> List[Dict[str, Any]]:
        """Every active set of every strength activity from `since` on that was not
        discarded, newest day first — what the strength history is built from (§8).

        A set carries its activity's day, start time, length and RPE, so a day the watch
        split into two activities keeps them apart. A name only the watch guessed comes back
        as no name: the history shows names a person gave.
        """
        sql = (
            "SELECT a.date, a.start_time, a.activity_id, a.rpe, "
            "  a.duration_sec AS activity_duration_sec, s.seq, s.reps, s.load_kg, "
            "  s.duration_sec, "
            f"  CASE WHEN s.named_by IN ({_person_marks()}) THEN s.exercise END AS exercise "
            "FROM exercise_sets s "
            "JOIN completed_activities a ON a.activity_id = s.activity_id "
            "WHERE s.set_type = ? AND a.discarded = 0 AND a.activity_type = ? AND a.date >= ?"
        )
        params: List[Any] = list(NAMED_BY_PERSON) + [ACTIVE, STRENGTH_TYPE, since]
        if before is not None:
            sql += " AND a.date < ?"
            params.append(before)
        with self._get_connection() as conn:
            rows = conn.execute(
                sql + " ORDER BY a.date DESC, a.start_time, s.seq", params
            ).fetchall()
            return [dict(row) for row in rows]

    # --- what the strength planner prescribed (§9) ---

    def prescribed_sets_for_revisions(
        self, revision_ids: Sequence[int]
    ) -> Dict[int, List[Dict[str, Any]]]:
        """The prescribed exercises of several revisions at once, keyed by revision.

        The same read hydration does, with a connection of its own rather than one it was
        handed (`db/workouts.py::_prescribed_set_rows`)."""
        if not revision_ids:
            return {}
        with self._get_connection() as conn:
            return self._prescribed_set_rows(conn, revision_ids)

    def get_strength_check(self, lineage_id: int) -> Optional[str]:
        """The stamp this session's kilograms were last weighed against, or None."""
        with self._get_connection() as conn:
            row = conn.execute(
                "SELECT checked_against FROM strength_checks WHERE lineage_id = ?",
                (lineage_id,),
            ).fetchone()
            return row["checked_against"] if row else None

    def strength_checks_for(self, lineage_ids: Sequence[int]) -> Dict[int, str]:
        """Those stamps for several sessions at once."""
        if not lineage_ids:
            return {}
        placeholders = ",".join("?" * len(lineage_ids))
        with self._get_connection() as conn:
            rows = conn.execute(
                f"SELECT * FROM strength_checks WHERE lineage_id IN ({placeholders})",
                tuple(lineage_ids),
            ).fetchall()
            return {row["lineage_id"]: row["checked_against"] for row in rows}

    def record_strength_check(self, lineage_id: int, stamp: str) -> None:
        """Remembers that this session's kilograms were written or checked against
        `stamp` — the value the history shown to the strength planner was built from, not
        the clock (§9)."""
        with self._get_connection() as conn:
            conn.execute(
                "INSERT INTO strength_checks (lineage_id, checked_against) VALUES (?, ?) "
                "ON CONFLICT(lineage_id) DO UPDATE SET "
                "  checked_against = excluded.checked_against",
                (lineage_id, stamp),
            )
            conn.commit()
