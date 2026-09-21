from typing import (
    Any,
    Dict,
    List,
    Optional,
    Sequence,
    Set,
    Tuple,
)

from trainmate.types import Workout
from trainmate.sports import canonical_sport
from trainmate.db.workout_change import _ZONE_COLUMNS


def _fell(new: Any, old: Any) -> bool:
    """Whether a load field dropped. Both values must be present: a missing number is a
    gap in the data, not an easing."""
    if new is None or old is None:
        return False
    return float(new) < float(old)


def _eased(revision: Dict[str, Any], previous: Optional[Dict[str, Any]]) -> bool:
    """Whether an adapt revision actually reduced load against its own predecessor (§7)."""
    if previous is None:
        return False
    return (
        _fell(revision["duration_minutes"], previous["duration_minutes"])
        or _fell(revision["tss"], previous["tss"])
    )


def _describing_revision(
    by_id: Dict[int, Dict[str, Any]], revision: Dict[str, Any]
) -> Dict[str, Any]:
    """The revision whose change describes the *form* this one holds.

    A rollback/reinstate copy re-establishes an earlier prescription, so it reads
    as whatever that prescription was — the same `restored_from` jump the adaptation tally
    makes (§7). Every other revision describes itself. Both the change kind and the
    commitment window are read off it (DESIGN_plan_change_continuity.md §5.2)."""
    seen: Set[int] = set()
    current = revision
    while current["restored_from"] is not None and current["id"] not in seen:
        seen.add(current["id"])
        restored = by_id.get(current["restored_from"])
        if restored is None:
            break
        current = restored
    return current


def _adaptation_tally(
    revisions: List[Dict[str, Any]], head_id: int
) -> Tuple[int, Optional[str]]:
    """Walks a lineage backwards from `head_id` and counts the easings still standing (§7).

    Not a `COUNT(*)`: a rollback/reinstate copy jumps over the span it undid, and a
    `generate` or a `tweak` re-prescribes the session so easings of the previous
    prescription stop describing it. Returns `(adaptation_count, adapted_at)`.
    """
    by_id = {r["id"]: r for r in revisions}
    position = {r["id"]: i for i, r in enumerate(revisions)}
    count, adapted_at = 0, None
    seen: Set[int] = set()
    current = by_id.get(head_id)
    while current is not None and current["id"] not in seen:
        seen.add(current["id"])
        if current["restored_from"] is not None:
            current = by_id.get(current["restored_from"])
            continue
        if current["kind"] in ("generate", "tweak"):
            break
        index = position[current["id"]]
        previous = revisions[index - 1] if index else None
        if current["kind"] == "adapt" and _eased(current, previous):
            count += 1
            if adapted_at is None:
                adapted_at = current["change_created_at"]
        current = previous
    return count, adapted_at


class WorkoutsMixin:
    """Reading a session as it stands today, and the hydration that builds one.

    A raw `workouts` row is one revision; a `Workout` is the live revision of a slot plus
    what its lineage says about it. `_hydrate` is that assembly, and every reader here
    goes through it (DESIGN_workout_revisions.md §4).
    """

    def _lineage_revisions(
        self, conn, lineage_ids: Sequence[int]
    ) -> Dict[int, List[Dict[str, Any]]]:
        """Every revision of the named lineages, oldest first, with its change joined.

        One query for the whole result set: hydration must not turn a sixty-row listing
        into two hundred lineage lookups (§5)."""
        if not lineage_ids:
            return {}
        placeholders = ",".join("?" * len(lineage_ids))
        rows = conn.execute(
            "SELECT w.*, c.kind AS kind, c.created_at AS change_created_at, "
            "       c.summary AS change_summary, c.commitment_end AS commitment_end "
            "FROM workouts w JOIN workout_changes c ON c.id = w.change_id "
            f"WHERE w.lineage_id IN ({placeholders}) "
            "ORDER BY w.lineage_id ASC, w.id ASC",
            tuple(lineage_ids),
        ).fetchall()
        grouped: Dict[int, List[Dict[str, Any]]] = {}
        for row in rows:
            grouped.setdefault(row["lineage_id"], []).append(dict(row))
        return grouped

    def _calendar_state_rows(
        self, conn, lineage_ids: Sequence[int]
    ) -> Dict[int, Dict[str, Any]]:
        if not lineage_ids:
            return {}
        placeholders = ",".join("?" * len(lineage_ids))
        rows = conn.execute(
            f"SELECT * FROM workout_calendar_state WHERE lineage_id IN ({placeholders})",
            tuple(lineage_ids),
        ).fetchall()
        return {row["lineage_id"]: dict(row) for row in rows}

    @staticmethod
    def _prescribed_set_rows(
        conn, revision_ids: Sequence[int]
    ) -> Dict[int, List[Dict[str, Any]]]:
        """The strength planner's exercises for these revisions, in one query — hydration
        must not turn a sixty-row listing into sixty lookups (DESIGN_strength_tracking.md
        §9)."""
        if not revision_ids:
            return {}
        placeholders = ",".join("?" * len(revision_ids))
        rows = conn.execute(
            f"SELECT * FROM prescribed_sets WHERE workout_id IN ({placeholders}) "
            "ORDER BY workout_id, position",
            tuple(revision_ids),
        ).fetchall()
        grouped: Dict[int, List[Dict[str, Any]]] = {}
        for row in rows:
            grouped.setdefault(row["workout_id"], []).append(dict(row))
        return grouped

    @staticmethod
    def _hydrated(
        row: Dict[str, Any], revisions: List[Dict[str, Any]],
        calendar: Optional[Dict[str, Any]],
        prescribed: Optional[List[Dict[str, Any]]] = None,
    ) -> Workout:
        """One live revision as the dict the rest of the app reads (§5).

        `id` is the LINEAGE id, which is what makes the athlete-visible ids stable and
        what `workout show` addresses; the physical row id travels as `revision_id` for the
        history surfaces."""
        by_id = {r["id"]: r for r in revisions}
        head = by_id.get(row["id"], dict(row, kind=None, change_summary=None))
        first = revisions[0] if revisions else row
        count, adapted_at = _adaptation_tally(revisions, row["id"])
        void = bool(row["void"])
        calendar = calendar or {}
        describing = _describing_revision(by_id, head) if revisions else head
        return {  # type: ignore[return-value]
            "id": row["lineage_id"],
            "revision_id": row["id"],
            "date": row["date"],
            "sport_type": row["sport_type"],
            "title": row["title"],
            "description": row["description"],
            "original_description": first["description"],
            "pushed_signature": calendar.get("pushed_signature"),
            "adherence_pushed_signature": calendar.get("adherence_pushed_signature"),
            # A revision's note is either why it changed or why it was cancelled, and the
            # change kind says which (§3).
            "modification_reason": None if void else row["reason"],
            "adaptation_summary": head.get("change_summary"),
            "change_kind": describing.get("kind") if revisions else None,
            # The window this revision was written under, not the one standing now (§5.2).
            "commitment_end": describing.get("commitment_end"),
            "google_event_id": calendar.get("google_event_id"),
            "removed": void,
            "removed_reason": row["reason"] if void else None,
            "duration_minutes": row["duration_minutes"],
            "rpe": row["rpe"],
            "tss": row["tss"],
            "macrocycle_id": row["macrocycle_id"],
            "original_date": first["date"],
            "created_at": row["created_at"],
            "adapted_at": adapted_at,
            "adaptation_count": count,
            "original_duration_minutes": first["duration_minutes"],
            "original_tss": first["tss"],
            "original_rpe": first["rpe"],
            "benchmark_type": row["benchmark_type"],
            "planned_zone_currency": row["planned_zone_currency"],
            **{column: row[column] for column in _ZONE_COLUMNS},
            # What the strength planner wrote for this revision, empty for every other
            # session. The description is rendered from these, so the week planner is shown
            # only the brief above them (DESIGN_strength_tracking.md §9).
            "prescribed_sets": list(prescribed or []),
        }

    def _hydrate(self, conn, rows: List[Dict[str, Any]]) -> List[Workout]:
        if not rows:
            return []
        lineage_ids = sorted({r["lineage_id"] for r in rows if r["lineage_id"]})
        revisions = self._lineage_revisions(conn, lineage_ids)
        calendar = self._calendar_state_rows(conn, lineage_ids)
        prescribed = self._prescribed_set_rows(conn, [r["id"] for r in rows])
        return [
            self._hydrated(
                row, revisions.get(row["lineage_id"], []),
                calendar.get(row["lineage_id"]),
                prescribed.get(row["id"]),
            )
            for row in rows
        ]

    @staticmethod
    def _speaking(conn, rows: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        """Drops a live revision that its lineage no longer speaks through.

        A cross-sport swap leaves the moved session's lineage with a live void at the slot
        it left AND a live copy where it landed; the copy speaks for the lineage, or a
        listing would show one session twice and a push would fight itself (§8). Only a
        void can be the stale half, so only voids need checking.
        """
        stale_candidates = sorted({r["lineage_id"] for r in rows if r["void"]})
        if not stale_candidates:
            return rows
        placeholders = ",".join("?" * len(stale_candidates))
        heads = {
            row["lineage_id"]: row["head"]
            for row in conn.execute(
                "SELECT lineage_id, MAX(id) AS head FROM live_workouts "
                f"WHERE lineage_id IN ({placeholders}) GROUP BY lineage_id",
                tuple(stale_candidates),
            )
        }
        return [
            r for r in rows
            if not r["void"] or heads.get(r["lineage_id"]) == r["id"]
        ]

    # ------------------------------------------------------------------ reading

    def get_workout(self, date: str, sport_type: str) -> Optional[Workout]:
        """The live session in one slot, or None when the slot is empty.

        Matching is canonical (see trainmate.sports), so a lookup for
        ``strength_training`` finds a session stored under ``strength``. A cancelled
        session still answers here — callers filter on `removed`, as they always did."""
        with self._get_connection() as conn:
            row = conn.execute(
                "SELECT * FROM live_workouts WHERE date = ? AND sport_canonical = ?",
                (date, canonical_sport(sport_type)),
            ).fetchone()
            if not row:
                return None
            rows = self._speaking(conn, [dict(row)])
            hydrated = self._hydrate(conn, rows)
            return hydrated[0] if hydrated else None

    def get_workouts(
        self,
        start_date: Optional[str] = None,
        end_date: Optional[str] = None,
        sport_type: Optional[str] = None,
        include_removed: bool = False,
    ) -> List[Workout]:
        """The live sessions, ordered by date, optionally within a range or by sport.

        Cancelled sessions (a void revision — a goal stood down, an adapt or a tweak
        dropping a session) are excluded by default so they never appear in listings,
        comparisons, adaptation inputs or the calendar push. Pass include_removed=True to
        retrieve them, e.g. to tell the week planner a session was deliberately cancelled.

        There is no `include_archived` any more: a superseded revision is not a flagged
        row but an older sibling in its slot, and the history surfaces read it through
        `get_plan_revisions` / `get_workout_changes` (§5, §10).
        """
        query = "SELECT * FROM live_workouts WHERE 1=1"
        params: List[Any] = []
        if not include_removed:
            query += " AND void = 0"
        if start_date:
            query += " AND date >= ?"
            params.append(start_date)
        if end_date:
            query += " AND date <= ?"
            params.append(end_date)
        if sport_type:
            query += " AND sport_canonical = ?"
            params.append(canonical_sport(sport_type))
        query += " ORDER BY date ASC, id ASC"
        with self._get_connection() as conn:
            rows = [dict(r) for r in conn.execute(query, params).fetchall()]
            return self._hydrate(conn, self._speaking(conn, rows))

    def get_cancelled_workouts(self, start_date: str, end_date: str) -> List[Workout]:
        """Every session cancelled in a range, whoever cancelled it: each slot whose live
        revision is a void, ordered by date (DESIGN_workout_tweak.md §3.1).

        Wider than `get_workouts(include_removed=True)`, which hides a void whose session
        lives on as a rest day or another sport on the same date. Such a session is still
        gone from the schedule. A void whose session moved to another date and stands
        there is not listed: that session was moved, not cancelled.
        """
        with self._get_connection() as conn:
            rows = [
                dict(r) for r in conn.execute(
                    "SELECT * FROM live_workouts WHERE void = 1 AND date >= ? AND date <= ? "
                    "ORDER BY date ASC, id ASC",
                    (start_date, end_date),
                ).fetchall()
            ]
            if not rows:
                return []
            lineages = sorted({r["lineage_id"] for r in rows})
            placeholders = ",".join("?" * len(lineages))
            standing_on = {
                row["lineage_id"]: row["date"]
                for row in conn.execute(
                    "SELECT lineage_id, date FROM live_workouts WHERE void = 0 "
                    f"AND lineage_id IN ({placeholders})",
                    tuple(lineages),
                )
            }
            cancelled = [
                r for r in rows
                if standing_on.get(r["lineage_id"], r["date"]) == r["date"]
            ]
            return self._hydrate(conn, cancelled)

    def get_workout_by_id(self, workout_id: int) -> Optional[Workout]:
        """The live session a lineage id names, or None when it no longer holds a slot.

        `workout_id` is a lineage: the id `workout list` printed and the one `workout show`
        is given. Resolving it to the lineage's newest live revision is what stops a
        command addressing a dead revision (§5)."""
        with self._get_connection() as conn:
            row = conn.execute(
                "SELECT * FROM live_workouts WHERE lineage_id = ? ORDER BY id DESC LIMIT 1",
                (workout_id,),
            ).fetchone()
            if not row:
                return None
            hydrated = self._hydrate(conn, [dict(row)])
            return hydrated[0] if hydrated else None

    def count_future_workouts_for_macrocycles(
        self, macrocycle_ids: Sequence[int], from_date: str
    ) -> int:
        """How many live sessions on/after `from_date` those plan versions generated.

        What `goal rm --purge` would strand: deleting the goal cascades the versions away
        but not the sessions tagged with them (DESIGN_backward_evaluation.md §14.5)."""
        if not macrocycle_ids:
            return 0
        with self._get_connection() as conn:
            row = conn.execute(
                "SELECT COUNT(*) AS n FROM live_workouts "
                "WHERE date >= ? AND void = 0 "
                f"AND macrocycle_id IN ({','.join('?' * len(macrocycle_ids))})",
                [from_date] + list(macrocycle_ids),
            ).fetchone()
            return int(row["n"]) if row else 0

    def count_untagged_future_workouts(self, from_date: str) -> int:
        """How many live sessions on/after `from_date` carry no `macrocycle_id`.

        Those rows predate the plan-version tag, so no goal can claim them and calling a
        goal off leaves them alone — reported rather than swept
        (DESIGN_backward_evaluation.md §14)."""
        with self._get_connection() as conn:
            row = conn.execute(
                "SELECT COUNT(*) AS n FROM live_workouts "
                "WHERE date >= ? AND void = 0 AND macrocycle_id IS NULL",
                (from_date,),
            ).fetchone()
            return int(row["n"]) if row else 0

    def live_workouts_for_macrocycles(
        self, macrocycle_ids: Sequence[int], from_date: str
    ) -> List[Workout]:
        """The live sessions on/after `from_date` those plan versions own — what a goal
        stand-down voids (§10)."""
        if not macrocycle_ids:
            return []
        with self._get_connection() as conn:
            rows = [
                dict(r) for r in conn.execute(
                    "SELECT * FROM live_workouts WHERE date >= ? AND void = 0 "
                    f"AND macrocycle_id IN ({','.join('?' * len(macrocycle_ids))}) "
                    "ORDER BY date ASC, id ASC",
                    [from_date] + list(macrocycle_ids),
                ).fetchall()
            ]
            return self._hydrate(conn, self._speaking(conn, rows))

    def hydrate_revisions(self, revision_ids: Sequence[int]) -> List[Workout]:
        """The given physical revisions as hydrated sessions, in date order.

        What a command that just appended reads back, so it reports the sessions it wrote
        rather than re-deriving them from a window."""
        if not revision_ids:
            return []
        placeholders = ",".join("?" * len(revision_ids))
        with self._get_connection() as conn:
            rows = [
                dict(r) for r in conn.execute(
                    f"SELECT * FROM workouts WHERE id IN ({placeholders}) "
                    "ORDER BY date ASC, id ASC",
                    tuple(revision_ids),
                ).fetchall()
            ]
            return self._hydrate(conn, rows)
