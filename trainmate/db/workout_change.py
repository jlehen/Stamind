from contextlib import contextmanager
from datetime import datetime, timezone
from typing import (
    Any,
    Dict,
    Iterator,
    List,
    Optional,
    Sequence,
    Set,
    Tuple,
)

from trainmate.heads_up import undone_note
from trainmate.prompt import athlete_watching
from trainmate.types import Constraint, Workout
from trainmate.sports import canonical_sport

# One value per command invocation, fixed at write time (§3).
CHANGE_KINDS = (
    "generate", "adapt", "tweak", "rollback", "stand-down", "reinstate",
)

# The voids the athlete decided, as against the ones the coach wrote. A goal stood down is
# a decision, and both the week planner and Calendar treat it as one: the prompt calls it a
# deliberate cancellation and the event stays, retitled. A day a generate, an adapt or a
# tweak stopped scheduling is the coach's writing (DESIGN_workout_tweak.md §6).
ATHLETE_VOID_KINDS = ("stand-down",)

_ZONE_COLUMNS = tuple(f"planned_zone{i}_sec" for i in range(1, 8))

# The physical revision columns, in INSERT order. `id` is assigned by SQLite.
REVISION_COLUMNS = (
    "change_id", "lineage_id", "date", "sport_canonical", "sport_type",
    "title", "description", "duration_minutes", "rpe", "tss",
    "void", "reason", "restored_from", "macrocycle_id", "created_at",
    "benchmark_type", "planned_zone_currency",
) + _ZONE_COLUMNS

# What "the same prescription" means for the §9 no-op rule. `reason` is deliberately
# out: if the prescription did not move, the session was held, and a rationale for
# holding is not worth a revision.
PRESCRIPTION_FIELDS = (
    "date", "sport_canonical", "sport_type", "title", "description",
    "duration_minutes", "rpe", "tss", "benchmark_type", "planned_zone_currency",
    "void",
) + _ZONE_COLUMNS


def _same_prescription(row: Dict[str, Any], live: Dict[str, Any]) -> bool:
    """Whether a proposed revision prescribes exactly what the live one already does (§9)."""
    return all(row.get(f) == live[f] for f in PRESCRIPTION_FIELDS)

class WorkoutChange:
    """One command's worth of appends, all under a single `workout_changes` row (§6).

    The handle is the enforcement, not a convenience: a writer cannot append a revision
    without a change row, because `append` is the only door in, and cannot forget the
    Calendar reconcile, because the handle schedules it on close (§8).
    """

    def __init__(self, db, conn, change_id: int, kind: str, created_at: str) -> None:
        self._db = db
        self._conn = conn
        self.id = change_id
        self.kind = kind
        self.created_at = created_at
        # Every lineage this change looked at, written or not: the §8 pass compares each
        # against `workout_calendar_state`, so including an unchanged one costs a hash
        # and catches a session whose event was never pushed.
        self.touched_lineages: Set[int] = set()
        self.appended: List[int] = []

    # --- reading the slot ---

    @property
    def conn(self):
        """The transaction every append in this change shares."""
        return self._conn

    def live_revision(self, date: str, sport_canonical: str) -> Optional[Dict[str, Any]]:
        """The newest revision in a slot — the live one. Reads `workouts` directly
        because this IS the append path; everything else reads the view."""
        row = self._conn.execute(
            "SELECT * FROM workouts WHERE date = ? AND sport_canonical = ? "
            "ORDER BY id DESC LIMIT 1",
            (date, sport_canonical),
        ).fetchone()
        return dict(row) if row else None

    # --- the lineage rules (§4) ---

    def _lineage_for(
        self, live: Optional[Dict[str, Any]], explicit: Optional[int]
    ) -> Optional[int]:
        """Which lineage a revision joins, or None to start a new one.

        "Next occupant of the slot" and "same session" are different things, so this is
        not a blanket inherit-from-the-slot (§4)."""
        if explicit is not None:
            # A moved session carries its own lineage to the destination, not the
            # destination slot's.
            return explicit
        if live is None or live["void"]:
            # Appending over a void is a new session, not a resurrection of the removed
            # one: it must not inherit its Calendar event, its originals or its tally.
            return None
        return live["lineage_id"]

    # --- writing ---

    def prescribed_sets(self, revision_id: int) -> List[Dict[str, Any]]:
        """One revision's prescribed exercises, read inside this change's transaction
        (DESIGN_strength_tracking.md §9)."""
        rows = self._conn.execute(
            "SELECT exercise, sets, reps_low, reps_high, load_kg, light "
            "FROM prescribed_sets WHERE workout_id = ? ORDER BY position",
            (revision_id,),
        ).fetchall()
        return [dict(row) for row in rows]

    def _write_prescribed(
        self, revision_id: int, rows: Sequence[Dict[str, Any]]
    ) -> None:
        """The strength planner's exercises, written with the revision they belong to and in
        the same transaction (DESIGN_strength_tracking.md §9)."""
        self._conn.executemany(
            "INSERT INTO prescribed_sets "
            "  (workout_id, position, exercise, sets, reps_low, reps_high, load_kg, light) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
            [
                (revision_id, position, row["exercise"], row["sets"], row["reps_low"],
                 row["reps_high"], row.get("load_kg"), 1 if row.get("light") else 0)
                for position, row in enumerate(rows, start=1)
            ],
        )

    def _write(
        self, row: Dict[str, Any], lineage_id: Optional[int],
        live: Optional[Dict[str, Any]],
        prescribed: Optional[Sequence[Dict[str, Any]]] = None,
    ) -> Optional[int]:
        """Inserts one revision, or returns None when §9 suppresses it as a no-op.

        `prescribed` are the strength planner's exercises for this revision. A suppressed
        no-op writes none of them either, and the live row's sets stand — which is always
        right, because the description is rendered from them, so different kilograms make a
        different description (DESIGN_strength_tracking.md §9)."""
        if live is not None and live["lineage_id"] is not None:
            self.touched_lineages.add(live["lineage_id"])
        if lineage_id is not None:
            self.touched_lineages.add(lineage_id)
        if live is not None and _same_prescription(row, live):
            return None

        row["change_id"] = self.id
        row["lineage_id"] = lineage_id
        cursor = self._conn.cursor()
        columns = ", ".join(REVISION_COLUMNS)
        placeholders = ", ".join("?" * len(REVISION_COLUMNS))
        cursor.execute(
            f"INSERT INTO workouts ({columns}) VALUES ({placeholders})",
            [row.get(c) for c in REVISION_COLUMNS],
        )
        revision_id = int(cursor.lastrowid)
        if lineage_id is None:
            # A first revision is born with a NULL lineage — the id does not exist until
            # the insert assigns it — and is seeded here. The one UPDATE the §14 trigger
            # lets through, and it may write nothing but the row's own id.
            cursor.execute(
                "UPDATE workouts SET lineage_id = id WHERE id = ?", (revision_id,)
            )
            self.touched_lineages.add(revision_id)
        if prescribed:
            self._write_prescribed(revision_id, prescribed)
        self.appended.append(revision_id)
        return revision_id

    def append(
        self, *, date: str, sport_type: str, title: str,
        description: Optional[str] = None,
        duration_minutes: Optional[int] = None, rpe: Optional[int] = None,
        tss: Optional[int] = None, reason: Optional[str] = None,
        benchmark_type: Optional[str] = None, clear_benchmark: bool = False,
        planned_zone_currency: Optional[str] = None,
        planned_zone_sec: Optional[Sequence[Optional[int]]] = None,
        macrocycle_id: Optional[int] = None, lineage_id: Optional[int] = None,
        restored_from: Optional[int] = None,
        prescribed_sets: Optional[Sequence[Dict[str, Any]]] = None,
    ) -> Optional[int]:
        """Appends one revision of the session in `(date, sport_type)`.

        The new revision is the slot's live one merged with what is supplied here (§6
        step 2), so a partial re-save cannot read an omission as a deletion: `title` and
        `description` are always taken as given, every other field carries forward when
        omitted. `clear_benchmark` is the one way to blank `benchmark_type` in place, for
        an adaptation that replaces a test with something that is no longer that test
        (DESIGN_benchmark_workouts.md §4.2). `lineage_id` names the session explicitly,
        which is what a moved session's destination needs (§4).

        `prescribed_sets` are the strength planner's exercises for this revision
        (DESIGN_strength_tracking.md §9). Omitted, a revision that CONTINUES the session in
        the slot keeps the ones it already had, the way every other field carries forward;
        one that starts a new lineage is given them or has none.

        Returns the new revision's id, or None when §9 suppressed it as a no-op.
        """
        sport_canonical = canonical_sport(sport_type)
        live = self.live_revision(date, sport_canonical)
        joined = self._lineage_for(live, lineage_id)
        # Only a revision that CONTINUES the session already in the slot carries its
        # fields forward. One that starts a new lineage — a session appended over a void,
        # a moved session's destination — must not inherit the previous occupant's load
        # (§4/§6).
        continues = live is not None and joined == live["lineage_id"]
        base = live if continues else {}
        row: Dict[str, Any] = {
            "date": date,
            "sport_canonical": sport_canonical,
            "sport_type": sport_type,
            "title": title,
            "description": description,
            "void": 0,
            "reason": reason,
            "restored_from": restored_from,
        }
        for field, supplied in (
            ("duration_minutes", duration_minutes), ("rpe", rpe), ("tss", tss),
            ("planned_zone_currency", planned_zone_currency),
        ):
            row[field] = supplied if supplied is not None else base.get(field)
        zones = list(planned_zone_sec or [])[:7]
        zones += [None] * (7 - len(zones))
        for column, supplied in zip(_ZONE_COLUMNS, zones):
            row[column] = supplied if supplied is not None else base.get(column)
        if clear_benchmark:
            row["benchmark_type"] = None
        else:
            row["benchmark_type"] = (
                benchmark_type if benchmark_type is not None
                else base.get("benchmark_type")
            )
        row["macrocycle_id"] = self._db._macrocycle_tag(
            date, macrocycle_id, base.get("macrocycle_id")
        )
        # When the session first entered the plan. Carried across a lineage's revisions;
        # a new session starts its own clock at the change that created it.
        row["created_at"] = base.get("created_at") or self.created_at
        if prescribed_sets is None and continues:
            prescribed_sets = self.prescribed_sets(live["id"])
        return self._write(row, joined, live, prescribed_sets)

    def void(
        self, *, date: str, sport_type: str, reason: Optional[str] = None
    ) -> Optional[int]:
        """Appends a revision saying this slot now holds no session (§3).

        A void carries the lineage of the session it ends — the removed or departing one,
        never a fresh one: it is the last chapter of a lineage, not a first (§4). Returns
        None when the slot is already empty or already void.
        """
        sport_canonical = canonical_sport(sport_type)
        live = self.live_revision(date, sport_canonical)
        if live is None or live["void"]:
            return None
        row = {k: live[k] for k in REVISION_COLUMNS}
        row["void"] = 1
        row["reason"] = reason
        row["restored_from"] = None
        return self._write(row, live["lineage_id"], live)

    def restore(
        self, revision: Dict[str, Any], reason: Optional[str] = None
    ) -> Optional[int]:
        """Appends a copy of an earlier revision, stamped `restored_from`.

        Restore is a duplicate rather than an un-flag: the copy gets a new, higher id and
        becomes live by the same rule as everything else, so there is no second mechanism
        (§5). The stamp is what lets the adaptation tally skip the span this undid (§7).

        The copy carries the restored revision's prescribed sets, or the kilograms in its
        text would have no rows behind them (DESIGN_strength_tracking.md §9).
        """
        row = {k: revision[k] for k in REVISION_COLUMNS}
        row["restored_from"] = revision["id"]
        if reason is not None:
            row["reason"] = reason
        live = self.live_revision(revision["date"], revision["sport_canonical"])
        return self._write(
            row, revision["lineage_id"], live, self.prescribed_sets(revision["id"]),
        )


class WorkoutChangeMixin:
    """The only way to write a session, and the one way to undo one.

    `workout_change` opens the handle; `rollback_to_change` is the undo primitive every
    rollback command reduces to. Reading what these wrote is `db/workouts.py` and
    `db/workout_history.py` (DESIGN_workout_revisions.md §6).
    """

    @contextmanager
    def workout_change(
        self, kind: str, summary: Optional[str] = None,
        macrocycle_id: Optional[int] = None, note: Optional[str] = None,
        commitment_end: Optional[str] = None,
    ) -> Iterator[WorkoutChange]:
        """Opens the single write path onto `workouts` (§6).

        One `workout_changes` row per command invocation, written even when the pass
        appends nothing — an adapt that looked at the metrics and held is a real event
        (§3). Everything inside shares one transaction; the §8 Calendar reconcile runs
        over the lineages the change touched once that transaction has committed.

        `note` is the coach's line to the athlete about this change and `commitment_end`
        the last day of the window in force while it ran
        (DESIGN_plan_change_continuity.md §6.3, §5.2). A change the athlete watched is
        told as it is written (DESIGN_change_heads_up.md §6).
        """
        if kind not in CHANGE_KINDS:
            raise ValueError(f"unknown workout change kind: {kind!r}")
        created_at = datetime.now(timezone.utc).isoformat()
        told_at = created_at if athlete_watching() else None
        change: Optional[WorkoutChange] = None
        with self.transaction() as conn:
            cursor = conn.cursor()
            cursor.execute(
                "INSERT INTO workout_changes "
                "(created_at, kind, summary, macrocycle_id, note, commitment_end, told_at) "
                "VALUES (?, ?, ?, ?, ?, ?, ?)",
                (created_at, kind, summary, macrocycle_id, note, commitment_end, told_at),
            )
            change = WorkoutChange(self, conn, int(cursor.lastrowid), kind, created_at)
            yield change
        self._reconcile_calendar(change.touched_lineages)

    def _reconcile_calendar(self, lineage_ids: Set[int]) -> None:
        """Runs the §8 pass, if a Calendar is attached (see BaseDB.calendar_hook)."""
        if not lineage_ids or self.calendar_hook is None:
            return
        self.calendar_hook(self, sorted(lineage_ids))

    def _macrocycle_tag(
        self, date: str, supplied: Optional[int], inherited: Optional[int]
    ) -> Optional[int]:
        """Which plan version a revision belongs to: what the caller named, else what the
        session already carried, else the macrocycle governing its date."""
        if supplied is not None:
            return supplied
        if inherited is not None:
            return inherited
        ids = self.get_periodization_ids_for_date(date)
        return ids[1] if ids else None

    def rollback_to_change(
        self, change_id: int, from_date: str, summary: Optional[str] = None
    ) -> Tuple[List[Workout], List[Constraint]]:
        """Point-in-time undo: reverts change N and every change after it (§10).

        Worked per SLOT rather than per lineage, because a change can end a lineage by
        appending over it — a move landing on a slot another session held — and the session
        to bring back is then the slot's previous occupant, whose own lineage the change
        never touched. For every slot N or a later change wrote, the revision live there
        just before N is copied forward, stamped `restored_from`; a slot that held nothing
        before N gets a void.

        The date floor is the same rule `archive_future_workouts` had: appending a copy
        into a past slot would silently make it the live session for a day already
        trained (DESIGN_plan_rollback.md §9).

        The rollback's `note` tells the athlete what was undone, quoting the changes they
        were told about (DESIGN_change_heads_up.md §6).

        Returns `(restored sessions, constraints un-honored by the restore)`.
        """
        target = self.get_change(change_id)
        if target is None:
            raise ValueError(f"No workout change #{change_id}.")
        with self._get_connection() as conn:
            told = [
                dict(row) for row in conn.execute(
                    "SELECT c.* FROM workout_changes c "
                    "WHERE c.id >= ? AND c.told_at IS NOT NULL AND EXISTS ("
                    "  SELECT 1 FROM workouts w WHERE w.change_id = c.id AND w.date >= ?"
                    ") ORDER BY c.id ASC",
                    (change_id, from_date),
                ).fetchall()
            ]
        with self.workout_change(
            kind="rollback", summary=summary, note=undone_note(told)
        ) as change:
            slots = change.conn.execute(
                "SELECT DISTINCT date, sport_canonical FROM workouts "
                "WHERE change_id >= ? AND date >= ? ORDER BY date ASC",
                (change_id, from_date),
            ).fetchall()
            for slot in slots:
                previous = change.conn.execute(
                    "SELECT * FROM workouts WHERE date = ? AND sport_canonical = ? "
                    "AND change_id < ? ORDER BY id DESC LIMIT 1",
                    (slot["date"], slot["sport_canonical"], change_id),
                ).fetchone()
                if previous is None:
                    live = change.live_revision(slot["date"], slot["sport_canonical"])
                    if live is not None:
                        change.void(
                            date=live["date"], sport_type=live["sport_type"],
                            reason="Undone by a rollback",
                        )
                    continue
                change.restore(dict(previous))
            # The restored plan predates these honorings and cannot reflect them (§10).
            unhonored = self.clear_honored_after(target["created_at"], from_date)
            appended = list(change.appended)
        restored = [
            w for w in self.hydrate_revisions(appended) if not w["removed"]
        ]
        return restored, unhonored
