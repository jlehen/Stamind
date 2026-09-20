from datetime import datetime, timezone
from typing import (
    Any,
    Dict,
    List,
    Optional,
    Sequence,
    Set,
)

from trainmate.types import Workout


class WorkoutHistoryMixin:
    """What happened to a session, rather than what it is today.

    Three things that are all the same question asked at different scales: every form one
    session has ever had, the log of the changes that wrote them, and which Calendar event
    a lineage currently holds (DESIGN_workout_revisions.md §5, DESIGN_calendar_lineage.md).
    """

    def get_lineage_head(self, lineage_id: int) -> Optional[Workout]:
        """A lineage's newest revision, whether or not it still owns its slot.

        `get_workout_by_id` above answers "what session does this lineage hold now?" and
        returns nothing once another session has been appended over its slot. The Calendar
        reconcile asks a different question — "what is the last thing that happened to this
        session?" — because a void written and then covered in the same slot is never the
        slot's live row, and reading the slot would tear its marker down the instant it was
        written (DESIGN_plan_change_continuity.md §5.2). `superseded` says which case this
        is: True when the row no longer owns its slot.
        """
        with self._get_connection() as conn:
            row = conn.execute(
                "SELECT w.*, (w.id = (SELECT MAX(w2.id) FROM workouts w2 "
                "  WHERE w2.date = w.date AND w2.sport_canonical = w.sport_canonical)) "
                "  AS slot_live "
                "FROM workouts w WHERE w.lineage_id = ? ORDER BY w.id DESC LIMIT 1",
                (lineage_id,),
            ).fetchone()
            if not row:
                return None
            raw = dict(row)
            slot_live = bool(raw.pop("slot_live"))
            hydrated = self._hydrate(conn, [raw])
            if not hydrated:
                return None
            return {**hydrated[0], "superseded": not slot_live}  # type: ignore[return-value]

    def get_workout_revision(self, revision_id: int) -> Optional[Dict[str, Any]]:
        """One physical revision, raw."""
        with self._get_connection() as conn:
            row = conn.execute(
                "SELECT * FROM workouts WHERE id = ?", (revision_id,)
            ).fetchone()
            return dict(row) if row else None

    def get_plan_revisions(self) -> List[Dict[str, Any]]:
        """Every revision ever appended, raw, flagged with whether it is still live.

        `plan show`'s per-version listing, which is history rather than plan: it asks what
        a plan version scheduled, including what a later version displaced (§5)."""
        with self._get_connection() as conn:
            rows = conn.execute(
                "SELECT w.*, "
                "  (w.id = (SELECT MAX(w2.id) FROM workouts w2 "
                "           WHERE w2.date = w.date "
                "             AND w2.sport_canonical = w.sport_canonical)) AS live "
                "FROM workouts w ORDER BY w.date ASC, w.id ASC"
            ).fetchall()
            return [dict(r) for r in rows]

    def get_lineage_revisions(self, lineage_id: int) -> List[Dict[str, Any]]:
        """Every form one session has ever had, oldest first, with its change joined.

        The whole story of a single session rather than of a plan version — what the
        Calendar event renders as its history (DESIGN_calendar_lineage.md §4)."""
        with self._get_connection() as conn:
            return self._lineage_revisions(conn, [lineage_id]).get(lineage_id, [])

    def get_change(self, change_id: int) -> Optional[Dict[str, Any]]:
        with self._get_connection() as conn:
            row = conn.execute(
                "SELECT * FROM workout_changes WHERE id = ?", (change_id,)
            ).fetchone()
            return dict(row) if row else None

    def get_workout_changes(
        self, from_date: Optional[str] = None
    ) -> List[Dict[str, Any]]:
        """Every change, newest first — the list `workout batches` renders (§10).

        The batch key moved from `archived_at` (stamped on the rows a command killed) to
        `change_id` (carried by the rows a command created), so every write is a batch and
        every batch is undoable, adapts and tweaks included. A change that appended
        nothing is listed too, flagged `held`.

        Each entry: {id, created_at, kind, summary, note, workouts, first_date, last_date,
        macrocycle_ids, held, waiting} plus, when `from_date` is given, `restorable` — how
        many of its revisions are dated from there on. `waiting` says the athlete has not
        been told about it yet (DESIGN_change_heads_up.md §8).
        """
        waiting = {c["id"] for c in self.waiting_changes()}
        with self._get_connection() as conn:
            rows = conn.execute(
                "SELECT c.id, c.created_at, c.kind, c.summary, c.note, "
                "       COUNT(w.id) AS workouts, MIN(w.date) AS first_date, "
                "       MAX(w.date) AS last_date, "
                "       GROUP_CONCAT(DISTINCT w.macrocycle_id) AS macro_ids "
                "FROM workout_changes c LEFT JOIN workouts w ON w.change_id = c.id "
                "GROUP BY c.id ORDER BY c.id DESC"
            ).fetchall()
            changes = []
            for row in rows:
                raw_ids = row["macro_ids"] or ""
                changes.append({
                    "id": row["id"],
                    "created_at": row["created_at"],
                    "kind": row["kind"],
                    "summary": row["summary"],
                    "note": row["note"],
                    "workouts": row["workouts"],
                    "first_date": row["first_date"],
                    "last_date": row["last_date"],
                    "macrocycle_ids": sorted(
                        int(i) for i in raw_ids.split(",") if i.strip()
                    ),
                    "held": row["workouts"] == 0,
                    "waiting": row["id"] in waiting,
                })
            if from_date is None:
                return changes
            counts = {
                r["change_id"]: r["n"] for r in conn.execute(
                    "SELECT change_id, COUNT(*) AS n FROM workouts WHERE date >= ? "
                    "GROUP BY change_id", (from_date,)
                )
            }
            for change in changes:
                change["restorable"] = counts.get(change["id"], 0)
            return changes

    def newest_change_for_macrocycles(
        self, macrocycle_ids: Sequence[int]
    ) -> Optional[int]:
        """The newest change that appended any revision tagged with one of these plan
        versions — what `plan rollback` derives its target from (§10)."""
        if not macrocycle_ids:
            return None
        with self._get_connection() as conn:
            row = conn.execute(
                "SELECT MAX(change_id) AS c FROM workouts "
                f"WHERE macrocycle_id IN ({','.join('?' * len(macrocycle_ids))})",
                tuple(macrocycle_ids),
            ).fetchone()
            return int(row["c"]) if row and row["c"] is not None else None

    def newest_change_with_sessions(self) -> Optional[Dict[str, Any]]:
        """The newest change that wrote at least one revision, or None: the one a terminal
        run offers to replace (DESIGN_change_heads_up.md §5)."""
        with self._get_connection() as conn:
            row = conn.execute(
                "SELECT c.* FROM workout_changes c "
                "WHERE EXISTS (SELECT 1 FROM workouts w WHERE w.change_id = c.id) "
                "ORDER BY c.id DESC LIMIT 1"
            ).fetchone()
            return dict(row) if row else None

    def change_has_live_revisions(self, change_id: int) -> bool:
        """Whether anything this change wrote is still the live revision of its slot —
        that is, whether the change still stands (DESIGN_plan_change_continuity.md §6.4).

        A rollback brings a change back by writing copies of its rows, so a live copy
        counts too, and so does a copy of a copy (DESIGN_change_heads_up.md §6)."""
        with self._get_connection() as conn:
            row = conn.execute(
                "WITH RECURSIVE copies(id) AS ("
                "  SELECT id FROM workouts WHERE change_id = ? "
                "  UNION "
                "  SELECT w.id FROM workouts w JOIN copies c ON w.restored_from = c.id"
                ") "
                "SELECT 1 FROM live_workouts WHERE id IN (SELECT id FROM copies) LIMIT 1",
                (change_id,),
            ).fetchone()
            return row is not None

    def waiting_changes(self) -> List[Dict[str, Any]]:
        """The changes waiting to be told, oldest first: each has a line for the athlete,
        no `told_at`, and still stands (DESIGN_change_heads_up.md §6)."""
        with self._get_connection() as conn:
            rows = conn.execute(
                "SELECT * FROM workout_changes "
                "WHERE note IS NOT NULL AND note != '' AND told_at IS NULL "
                "ORDER BY id ASC"
            ).fetchall()
        return [dict(row) for row in rows if self.change_has_live_revisions(row["id"])]

    def mark_changes_told(self, change_ids: Sequence[int]) -> None:
        """Records that the athlete was told about these changes (§6)."""
        if not change_ids:
            return
        told_at = datetime.now(timezone.utc).isoformat()
        with self._get_connection() as conn:
            conn.execute(
                "UPDATE workout_changes SET told_at = ? "
                f"WHERE told_at IS NULL AND id IN ({','.join('?' * len(change_ids))})",
                [told_at, *change_ids],
            )
            conn.commit()

    def next_change_after(self, change_id: int) -> Optional[int]:
        """The change that ran immediately after `change_id`, if any."""
        with self._get_connection() as conn:
            row = conn.execute(
                "SELECT MIN(id) AS c FROM workout_changes WHERE id > ?", (change_id,)
            ).fetchone()
            return int(row["c"]) if row and row["c"] is not None else None

    def stood_down_sessions(
        self, macrocycle_ids: Sequence[int], from_date: str
    ) -> List[Dict[str, Any]]:
        """The revisions a goal's live `stand-down` voids ended — what reinstating it
        copies back (§10).

        Read off the live view, so a slot regenerated or edited since the stand-down no
        longer has that void live and is skipped: something else owns it now. Each entry
        is a raw revision plus `stood_down_at`, the void's change timestamp, which is what
        the caller un-honors constraints against.
        """
        if not macrocycle_ids:
            return []
        with self._get_connection() as conn:
            voids = conn.execute(
                "SELECT w.id AS void_id, w.lineage_id AS lineage_id, "
                "       c.created_at AS stood_down_at "
                "FROM live_workouts w JOIN workout_changes c ON c.id = w.change_id "
                "WHERE w.void = 1 AND c.kind = 'stand-down' AND w.date >= ? "
                f"AND w.macrocycle_id IN ({','.join('?' * len(macrocycle_ids))}) "
                "ORDER BY w.lineage_id ASC",
                [from_date] + list(macrocycle_ids),
            ).fetchall()
            sessions = []
            for void in voids:
                ended = conn.execute(
                    "SELECT * FROM workouts WHERE lineage_id = ? AND id < ? "
                    "ORDER BY id DESC LIMIT 1",
                    (void["lineage_id"], void["void_id"]),
                ).fetchone()
                if ended is None or ended["date"] < from_date:
                    continue
                sessions.append(dict(ended, stood_down_at=void["stood_down_at"]))
            return sessions

    def claimed_calendar_event_ids(self) -> Set[str]:
        """Every Calendar event a lineage still owns.

        The state table is the ownership record: the reconcile clears a row when it tears
        an event down, so a row that is still there means the event is still claimed. Read
        here rather than off the live rows because a void that keeps its event is not
        always its slot's live row — a marker written and then covered would otherwise
        read as an orphan (DESIGN_plan_change_continuity.md §5.2/§5.6)."""
        with self._get_connection() as conn:
            return {
                row["google_event_id"] for row in conn.execute(
                    "SELECT google_event_id FROM workout_calendar_state "
                    "WHERE google_event_id IS NOT NULL"
                )
            }

    def get_calendar_state(self, lineage_id: int) -> Optional[Dict[str, Any]]:
        with self._get_connection() as conn:
            row = conn.execute(
                "SELECT * FROM workout_calendar_state WHERE lineage_id = ?",
                (lineage_id,),
            ).fetchone()
            return dict(row) if row else None

    def mark_workout_pushed(
        self, lineage_id: int, google_event_id: str, signature: str
    ) -> None:
        """Records a successful Google Calendar push: the event handle and the signature
        of the content that was pushed. Freshness is derived by comparing that signature
        against the live content (see trainmate.workout_state), so this is the *only*
        method that marks a session `synced`. Keyed by lineage, because there is one
        event per session and it must follow it across edits and date moves (§8)."""
        with self._get_connection() as conn:
            conn.execute(
                "INSERT INTO workout_calendar_state "
                "  (lineage_id, google_event_id, pushed_signature) VALUES (?, ?, ?) "
                "ON CONFLICT(lineage_id) DO UPDATE SET "
                "  google_event_id = excluded.google_event_id, "
                "  pushed_signature = excluded.pushed_signature",
                (lineage_id, google_event_id, signature),
            )
            conn.commit()

    def mark_workout_adherence_pushed(self, lineage_id: int, signature: str) -> None:
        """Records a successful `workout compare --mark` push: the adherence-inclusive
        signature (see trainmate.workout_state.adherence_signature), so a later compare
        over the same range can skip a no-op Calendar update when the event already
        carries the same verdict. Orthogonal to `pushed_signature` — the underlying
        `sync_workout` already refreshed that (§8)."""
        with self._get_connection() as conn:
            conn.execute(
                "INSERT INTO workout_calendar_state "
                "  (lineage_id, adherence_pushed_signature) VALUES (?, ?) "
                "ON CONFLICT(lineage_id) DO UPDATE SET "
                "  adherence_pushed_signature = excluded.adherence_pushed_signature",
                (lineage_id, signature),
            )
            conn.commit()

    def clear_calendar_state(self, lineage_id: int) -> None:
        """Forgets a session's Calendar event, after the event itself has been deleted."""
        with self._get_connection() as conn:
            conn.execute(
                "DELETE FROM workout_calendar_state WHERE lineage_id = ?", (lineage_id,)
            )
            conn.commit()
