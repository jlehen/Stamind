from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List, Optional, Tuple
from stamind.types import Macrocycle, PlanFeedback
from stamind.clock import today_date
from stamind.db.objectives import ARCHIVED


def repair_mesocycle_contiguity(
    mesocycles: List[Dict[str, Any]]
) -> Tuple[List[Dict[str, Any]], List[str]]:
    """Sorts a plan's mesocycles and re-dates them so consecutive mesocycles are contiguous.

    Contiguity is asked of the model; this repairs what came back so the stored plan
    always holds it (DOMAIN_MODEL.md §4). End dates are authoritative: a mesocycle whose
    start is not the day after its predecessor's end is re-dated to start there, and a
    mesocycle ending inside its predecessor is dropped. Returns (mesocycles, notes), the notes
    naming each repair — empty when nothing needed one. Idempotent, so the write
    boundary re-applies it as a no-op after `plan_apply` has surfaced the notes."""
    ordered = sorted(mesocycles, key=lambda b: (b['start_date'], b['end_date']))
    repaired: List[Dict[str, Any]] = []
    notes: List[str] = []
    for mesocycle in ordered:
        if not repaired:
            repaired.append(dict(mesocycle))
            continue
        prev = repaired[-1]
        expected = (
            datetime.strptime(prev['end_date'], "%Y-%m-%d") + timedelta(days=1)
        ).strftime("%Y-%m-%d")
        if mesocycle['end_date'] < expected:
            notes.append(
                f"dropped '{mesocycle['name']}' ({mesocycle['start_date']} to "
                f"{mesocycle['end_date']}): it ends inside '{prev['name']}'"
            )
            continue
        if mesocycle['start_date'] != expected:
            if mesocycle['start_date'] < expected:
                how = f"overlapped '{prev['name']}'"
            else:
                how = f"left a gap after '{prev['name']}'"
            notes.append(
                f"moved the start of '{mesocycle['name']}' from {mesocycle['start_date']} to "
                f"{expected}: it {how}, which ends {prev['end_date']}"
            )
            mesocycle = dict(mesocycle, start_date=expected)
        repaired.append(dict(mesocycle))
    return repaired, notes


class PeriodizationMixin:
    """Plan versions, the feedback log, and the write that lays a plan down.

    `save_macrocycle` writes the mesocycle rows too; reading them back is
    `db/mesocycles.py`.
    """

    def get_macrocycle_for_objective(self, objective_id: int) -> Optional[Macrocycle]:
        """Fetches the active macrocycle for a specific objective.

        Superseded plan versions (kept for `plan rollback`, see DESIGN_plan_rollback.md)
        are excluded — only the one currently-active macrocycle is returned. Legacy rows
        predating the version axis default to 'active'."""
        with self._get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute(
                "SELECT * FROM macrocycles WHERE objective_id = ? "
                "AND COALESCE(status, 'active') = 'active' "
                "ORDER BY id DESC LIMIT 1",
                (objective_id,)
            )
            row = cursor.fetchone()
            return dict(row) if row else None  # type: ignore

    def get_macrocycle_versions(self, objective_id: int) -> List[Macrocycle]:
        """Returns every macrocycle version for an objective, newest first.

        Includes the active version and all superseded ones, for rollback target
        selection and history display (see DESIGN_plan_rollback.md)."""
        with self._get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute(
                "SELECT * FROM macrocycles WHERE objective_id = ? ORDER BY id DESC",
                (objective_id,)
            )
            return [dict(row) for row in cursor.fetchall()]  # type: ignore

    def get_previous_macrocycle_version(
        self, objective_id: int, before_id: Optional[int] = None
    ) -> Optional[Macrocycle]:
        """Returns the macrocycle version chronologically prior to the active one.

        With `before_id` given, returns the newest version older than that id instead.
        Used by `plan rollback` to walk backwards through plan history one step at a
        time (see DESIGN_plan_rollback.md). Returns None when there is no earlier version.

        Named for the *version* axis on purpose: what comes back is superseded, and its
        mesocycles sit on the same calendar dates as the active version's while describing
        training that never happened. A retrospective view wants `get_preceding_macrocycle`
        (DESIGN_plan_rollback.md §6.1)."""
        if before_id is None:
            active = self.get_macrocycle_for_objective(objective_id)
            if not active:
                return None
            before_id = active['id']
        with self._get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute(
                "SELECT * FROM macrocycles WHERE objective_id = ? AND id < ? "
                "ORDER BY id DESC LIMIT 1",
                (objective_id, before_id)
            )
            row = cursor.fetchone()
            return dict(row) if row else None  # type: ignore

    def set_active_macrocycle(self, macrocycle_id: int) -> None:
        """Makes `macrocycle_id` the active version for its objective, superseding any
        other active version (see DESIGN_plan_rollback.md). Idempotent."""
        now = datetime.now(timezone.utc).isoformat()
        with self._get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute(
                "SELECT objective_id FROM macrocycles WHERE id = ?", (macrocycle_id,)
            )
            row = cursor.fetchone()
            if not row:
                return
            objective_id = row['objective_id']
            # Supersede whichever version is currently active for this objective.
            cursor.execute(
                "UPDATE macrocycles SET status = 'superseded', superseded_at = ? "
                "WHERE objective_id = ? AND COALESCE(status, 'active') = 'active' "
                "AND id != ?",
                (now, objective_id, macrocycle_id)
            )
            # Promote the target.
            cursor.execute(
                "UPDATE macrocycles SET status = 'active', superseded_at = NULL "
                "WHERE id = ?",
                (macrocycle_id,)
            )
            conn.commit()

    def get_macrocycle(self, macrocycle_id: int) -> Optional[Macrocycle]:
        """Fetches a specific macrocycle by its unique ID, regardless of status."""
        with self._get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("SELECT * FROM macrocycles WHERE id = ?", (macrocycle_id,))
            row = cursor.fetchone()
            return dict(row) if row else None  # type: ignore

    def get_preceding_macrocycle(self, objective_id: int) -> Optional[Macrocycle]:
        """The active plan of the goal whose target date immediately precedes this one's.

        The other sense of "the previous plan", and the one a retrospective view wants:
        which plan governed the calendar dates *before* this goal's plan did. A window
        reaching further back than the current plan's first mesocycle runs into it, and
        nothing else supplies those mesocycles.

        Deliberately distinct from `get_previous_macrocycle_version`, which returns an
        earlier *version* of this same goal's plan — superseded, never trained, and
        overlapping the active one's dates (DESIGN_plan_rollback.md §6.1). Only active
        versions are considered here, for the same reason. Returns None when no earlier
        goal has a plan."""
        with self._get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("""
                SELECT mac.* FROM macrocycles mac
                JOIN objectives o ON mac.objective_id = o.id
                WHERE COALESCE(mac.status, 'active') = 'active'
                  AND o.target_date < (SELECT target_date FROM objectives WHERE id = ?)
                ORDER BY o.target_date DESC, mac.id DESC
                LIMIT 1
            """, (objective_id,))
            row = cursor.fetchone()
            return dict(row) if row else None  # type: ignore

    def get_governing_macrocycle(self) -> Optional[Macrocycle]:
        """The macrocycle of the *governing objective* — the earliest goal still ahead
        that has a plan (i.e. the objective the current workouts implement). Its
        mesocycles label the timeline weeks (DESIGN_progress_timeline.md §6.1).

        Falls back to the most recent *completed* goal's plan when nothing ahead has one:
        the day after an event, the months of workouts behind the athlete still belong to
        that plan, and dropping the labels then would blank the timeline exactly when it
        is being looked at. Advancing used to be a side effect of marking the goal
        completed by hand; it is now the date's job (DESIGN_backward_evaluation.md §12).

        Deliberately distinct from `get_active_objective()` (next goal, plan-or-not):
        meso labels must follow whichever plan the current workouts implement. Returns
        None when no goal has a macrocycle."""
        live = [o for o in self.get_objectives() if o.get('status') != ARCHIVED]
        today = today_date().strftime("%Y-%m-%d")
        ahead = [o for o in live if str(o['target_date']) >= today]   # ORDER BY date ASC
        for obj in ahead:
            macro = self.get_macrocycle_for_objective(obj['id'])
            if macro:
                return macro
        for obj in reversed([o for o in live if str(o['target_date']) < today]):
            macro = self.get_macrocycle_for_objective(obj['id'])
            if macro:
                return macro
        return None

    def add_plan_feedback(
        self, macrocycle_id: int, text: str, mesocycle_id: Optional[int] = None
    ) -> int:
        """Appends one note to a plan's feedback log and returns its id.

        `mesocycle_id` None files the note against the plan as a whole
        (DESIGN_plan_feedback.md §6)."""
        created_at = datetime.now(timezone.utc).isoformat()
        with self._get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute(
                "INSERT INTO plan_feedback (macrocycle_id, mesocycle_id, created_at, text) "
                "VALUES (?, ?, ?, ?)",
                (macrocycle_id, mesocycle_id, created_at, text)
            )
            conn.commit()
            return int(cursor.lastrowid)

    def list_plan_feedback(self, macrocycle_id: int) -> List[PlanFeedback]:
        """The notes attached to one plan version, **oldest first**, each carrying the
        name of the mesocycle it was filed against (None = plan-level).

        One ordering everywhere — this listing, `plan show`, the regeneration prompt — so
        the log reads as a conversation in the order it happened, and a later note reads
        as an amendment of an earlier one (DESIGN_plan_feedback.md §4/§7)."""
        with self._get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("""
                SELECT f.*, m.name AS mesocycle_name
                FROM plan_feedback f
                LEFT JOIN mesocycles m ON f.mesocycle_id = m.id
                WHERE f.macrocycle_id = ?
                ORDER BY f.created_at ASC, f.id ASC
            """, (macrocycle_id,))
            return [dict(row) for row in cursor.fetchall()]  # type: ignore

    def get_plan_feedback(self, feedback_id: int) -> Optional[PlanFeedback]:
        """One note by id, with the name of the mesocycle it was filed against."""
        with self._get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("""
                SELECT f.*, m.name AS mesocycle_name
                FROM plan_feedback f
                LEFT JOIN mesocycles m ON f.mesocycle_id = m.id
                WHERE f.id = ?
            """, (feedback_id,))
            row = cursor.fetchone()
            return dict(row) if row else None  # type: ignore

    def rm_plan_feedback(self, feedback_id: int) -> None:
        """Deletes one note from the log."""
        with self._get_connection() as conn:
            conn.cursor().execute(
                "DELETE FROM plan_feedback WHERE id = ?", (feedback_id,)
            )
            conn.commit()

    def save_macrocycle(
        self, objective_id: int, strategy: str, goals_hash: str,
        constraints_hash: str, mesocycles: List[Dict[str, Any]],
        config_hash: str = "", config_snapshot: str = "", goals_snapshot: str = "",
        constraints_snapshot: str = "", all_constraints_snapshot: str = "",
        profile_snapshot: str = "", science_snapshot: str = ""
    ) -> int:
        """Saves a macrocycle and its nested mesocycles for the objective.

        The `*_snapshot` arguments are JSON of the inputs the plan was generated from,
        preserved so they can be shown and judged for drift after the live records change;
        `db/schema.py` documents each at its column.

        The previously-active macrocycle for the objective is *superseded* rather than
        deleted (see DESIGN_plan_rollback.md): it and its mesocycles are kept so that
        `plan rollback` can restore them, while the freshly-saved version becomes active.

        Mesocycles pass through `repair_mesocycle_contiguity` before insertion, so within-plan
        gaps and overlaps never reach the table (DOMAIN_MODEL.md §4).
        """
        mesocycles, _ = repair_mesocycle_contiguity(mesocycles)
        created_at = datetime.now(timezone.utc).isoformat()
        with self._get_connection() as conn:
            cursor = conn.cursor()
            # Retire any currently-active version for this objective (kept for rollback).
            cursor.execute(
                "UPDATE macrocycles SET status = 'superseded', superseded_at = ? "
                "WHERE objective_id = ? AND COALESCE(status, 'active') = 'active'",
                (created_at, objective_id)
            )

            cursor.execute("""
                INSERT INTO macrocycles (
                    objective_id, strategy, goals_hash, constraints_hash, config_hash,
                    config_snapshot, profile_snapshot, goals_snapshot,
                    constraints_snapshot, all_constraints_snapshot, science_snapshot,
                    created_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """, (objective_id, strategy, goals_hash, constraints_hash, config_hash,
                  config_snapshot or None, profile_snapshot or None,
                  goals_snapshot or None, constraints_snapshot or None,
                  all_constraints_snapshot or None, science_snapshot or None,
                  created_at))
            macrocycle_id = cursor.lastrowid

            for meso in mesocycles:
                cursor.execute("""
                    INSERT INTO mesocycles (macrocycle_id, name, start_date, end_date, focus)
                    VALUES (?, ?, ?, ?, ?)
                """, (macrocycle_id, meso['name'], meso['start_date'], meso['end_date'],
                      meso['focus']))

            conn.commit()
            return int(macrocycle_id)

    def update_macrocycle_config_hash(
        self, macrocycle_id: int, config_hash: str,
        config_snapshot: Optional[str] = None,
        profile_snapshot: Optional[str] = None,
        goals_hash: Optional[str] = None,
        goals_snapshot: Optional[str] = None,
        constraints_hash: Optional[str] = None,
        constraints_snapshot: Optional[str] = None,
        science_snapshot: Optional[str] = None,
    ) -> None:
        """Updates the config hash (and, when provided, the threshold and profile
        snapshots, the goals, the plan-shaping constraints and the science documents) for
        a specific macrocycle — the "keep current plan, accept new inputs" path.

        The stamp has to clear everything the staleness check flags, or a kept plan flags
        again tomorrow (DESIGN_plan_change_continuity.md §6.5). A value left as None is
        not written, so a caller re-stamping only the hash cannot blank out what the plan
        was generated against."""
        sets, params = ["config_hash = ?"], [config_hash]
        for column, value in (('config_snapshot', config_snapshot),
                              ('profile_snapshot', profile_snapshot),
                              ('goals_hash', goals_hash),
                              ('goals_snapshot', goals_snapshot),
                              ('constraints_hash', constraints_hash),
                              ('constraints_snapshot', constraints_snapshot),
                              ('science_snapshot', science_snapshot)):
            if value is not None:
                sets.append(f"{column} = ?")
                params.append(value)
        with self._get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute(
                f"UPDATE macrocycles SET {', '.join(sets)} WHERE id = ?",
                (*params, macrocycle_id)
            )
            conn.commit()

    def save_reshape_verdict(
        self, macrocycle_id: int, key: str, verdict: Optional[str]
    ) -> None:
        """Caches the verdict call's re-shaping read against the edit it was asked about, so
        `plan show` asks once per edit rather than on every read
        (DESIGN_plan_change_continuity.md §7)."""
        with self._get_connection() as conn:
            conn.execute(
                "UPDATE macrocycles SET reshape_verdict = ?, reshape_verdict_key = ? "
                "WHERE id = ?",
                (verdict, key, macrocycle_id),
            )
            conn.commit()

    def delete_macrocycle_for_objective(self, objective_id: int) -> None:
        """Deletes the macrocycle and its nested mesocycles for a specific objective."""
        with self._get_connection() as conn:
            conn.cursor().execute(
                "DELETE FROM macrocycles WHERE objective_id = ?",
                (objective_id,)
            )
            conn.commit()
