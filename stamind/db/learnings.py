from datetime import datetime, timedelta, timezone
from typing import Any, Dict, Iterable, List, Optional, Set, Tuple

from stamind.config import config
from stamind.learning_confidence import (
    RETIRE_PROPOSAL, confidence_rank, derive_confidence,
    learning_is_dormant, normalize_sports, step_down, valid_confidence,
)

# `coach_learnings.status`. Retiring a learning archives it, so a slip is restored with its
# evidence (DESIGN_learning_doubt_nudge.md §6).
ACTIVE = "active"
ARCHIVED = "archived"


def _monday_str(date_str: str) -> Optional[str]:
    """Returns the Monday (ISO week start) for a YYYY-MM-DD string, or None if unparseable."""
    try:
        d = datetime.strptime(date_str[:10], "%Y-%m-%d").date()
    except (ValueError, TypeError):
        return None
    return (d - timedelta(days=d.weekday())).strftime("%Y-%m-%d")


def _one_line(value: Any) -> Optional[str]:
    """A delta's free-text field, stripped, or None when it carries none."""
    if not isinstance(value, str) or not value.strip():
        return None
    return value.strip()


class LearningsMixin:
    """Coach learnings: discrete, addressable athlete-observation records whose confidence
    is computed by the app from a per-learning evidence basis (the distinct training weeks
    that back each observation). See DESIGN_evidence_based_confidence.md."""

    # ------------------------------------------------------------------ reads

    def get_learnings(self) -> List[Dict[str, Any]]:
        """Returns every observation record ordered by id, archived ones included. Each
        carries a computed `dormant` flag (decayed past its budget), an `archived` flag and
        its (nullable) `proposed_confidence` downgrade. Whatever leaves dormant learnings
        out leaves archived ones out too (DESIGN_learning_doubt_nudge.md §6)."""
        with self._get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute(
                "SELECT id, text, sports, confidence, proposed_confidence, status, created_at, "
                "updated_at, last_reinforced_at FROM coach_learnings ORDER BY id"
            )
            learnings = [dict(row) for row in cursor.fetchall()]
        now = datetime.now(timezone.utc)
        for learning in learnings:
            learning["dormant"] = learning_is_dormant(learning, now)
            learning["archived"] = learning["status"] == ARCHIVED
        return learnings

    def get_learning(self, learning_id: int) -> Optional[Dict[str, Any]]:
        """One record as `get_learnings` returns it, archived or not; None when there is
        none with that id."""
        return next((l for l in self.get_learnings() if l["id"] == learning_id), None)

    def get_learning_evidence(self, learning_id: int) -> List[Dict[str, Any]]:
        """Returns the evidence basis rows for a learning, ordered by week then polarity."""
        with self._get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute(
                "SELECT id, learning_id, week_commencing, polarity, source, reason, created_at "
                "FROM learning_evidence WHERE learning_id=? "
                "ORDER BY week_commencing, polarity",
                (learning_id,)
            )
            return [dict(row) for row in cursor.fetchall()]

    # ------------------------------------------------------------- basic CRUD

    def add_learning(
        self, text: str, sports: str = "general", confidence: str = "tentative"
    ) -> int:
        """Adds a single observation record and returns its id.

        A synthetic supporting basis sized to sustain the requested `confidence` is seeded
        (source 'manual'), so the app-computed recompute keeps the level instead of demoting
        it for lack of evidence — mirroring the grandfather migration (§9)."""
        now = datetime.now(timezone.utc).isoformat()
        sports = normalize_sports(sports)
        confidence = valid_confidence(confidence) or "tentative"
        with self._get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute(
                "INSERT INTO coach_learnings (text, sports, confidence, created_at, "
                "updated_at, last_reinforced_at) VALUES (?, ?, ?, ?, ?, ?)",
                (text, sports, confidence, now, now, now)
            )
            lid = cursor.lastrowid
            self._seed_synthetic_evidence(cursor, lid, confidence, now, source="manual")
            return lid

    def update_learning(self, learning_id: int, text: str) -> None:
        """Revises the text of an existing observation record."""
        now = datetime.now(timezone.utc).isoformat()
        with self._get_connection() as conn:
            conn.execute(
                "UPDATE coach_learnings SET text=?, updated_at=? WHERE id=?",
                (text, now, learning_id)
            )

    def delete_learning(self, learning_id: int) -> None:
        """Deletes an observation record for good, its evidence basis cascading
        (`learnings rm --purge`)."""
        with self._get_connection() as conn:
            conn.execute("DELETE FROM coach_learnings WHERE id=?", (learning_id,))

    def archive_learning(self, learning_id: int) -> bool:
        """Retires a learning by archiving it (DESIGN_learning_doubt_nudge.md §6). False
        when it was not active."""
        now = datetime.now(timezone.utc).isoformat()
        with self._get_connection() as conn:
            return self._archive(conn.cursor(), learning_id, now)

    def restore_learning(self, learning_id: int) -> bool:
        """Puts an archived learning back at tentative, with its evidence and a fresh
        dormancy clock (§6). False when it was not archived."""
        now = datetime.now(timezone.utc).isoformat()
        with self._get_connection() as conn:
            cursor = conn.execute(
                "UPDATE coach_learnings SET status=?, confidence='tentative', "
                "proposed_confidence=NULL, last_reinforced_at=?, updated_at=? "
                "WHERE id=? AND status=?",
                (ACTIVE, now, now, learning_id, ARCHIVED)
            )
            return cursor.rowcount > 0

    # ----------------------------------------------------- evidence internals

    def _evidence_counts(self, cursor, learning_id: int) -> Tuple[int, int]:
        """(distinct supporting weeks, distinct contradicting weeks) for a learning."""
        cursor.execute(
            "SELECT polarity, COUNT(DISTINCT week_commencing) FROM learning_evidence "
            "WHERE learning_id=? GROUP BY polarity",
            (learning_id,)
        )
        sup = con = 0
        for polarity, count in cursor.fetchall():
            if polarity >= 0:
                sup = count
            else:
                con = count
        return sup, con

    def _archive(self, cursor, learning_id: int, now: str) -> bool:
        """Archives an active learning and drops its pending proposal (§6)."""
        cursor.execute(
            "UPDATE coach_learnings SET status=?, proposed_confidence=NULL, updated_at=? "
            "WHERE id=? AND status=?",
            (ARCHIVED, now, learning_id, ACTIVE)
        )
        return cursor.rowcount > 0

    def _add_evidence_weeks(
        self, cursor, learning_id: int, weeks: Iterable[str], polarity: int,
        source: str, now: str, reason: Optional[str] = None
    ) -> int:
        """Inserts (week, polarity) evidence rows, deduped via INSERT-OR-IGNORE. Returns the
        number of *new* rows actually inserted (0 means every cited week was already counted).
        `reason` is what a contradiction says went against the learning
        (DESIGN_learning_doubt_nudge.md §4)."""
        inserted = 0
        for raw in weeks:
            monday = _monday_str(raw) if isinstance(raw, str) else None
            if not monday:
                continue
            cursor.execute(
                "INSERT OR IGNORE INTO learning_evidence "
                "(learning_id, week_commencing, polarity, source, reason, created_at) "
                "VALUES (?, ?, ?, ?, ?, ?)",
                (learning_id, monday, polarity, source, reason, now)
            )
            inserted += cursor.rowcount
        return inserted

    def _seed_synthetic_evidence(
        self, cursor, learning_id: int, confidence: str, anchor_iso: str, source: str
    ) -> None:
        """Seeds enough distinct synthetic supporting weeks (stepping back from the anchor
        week) to sustain `confidence`, so a basis-derived recompute keeps the level (§9)."""
        thresholds = config.learning_confidence_thresholds
        need = {
            "established": thresholds.get("established", 5),
            "moderate": thresholds.get("moderate", 3),
            "tentative": 1,
        }.get(confidence, 1)
        anchor = _monday_str(anchor_iso) or _monday_str(
            datetime.now(timezone.utc).isoformat()
        )
        base = datetime.strptime(anchor, "%Y-%m-%d").date()
        weeks = [(base - timedelta(weeks=i)).strftime("%Y-%m-%d") for i in range(need)]
        self._add_evidence_weeks(cursor, learning_id, weeks, +1, source, anchor_iso)

    def _recompute_confidence(self, cursor, learning_id: int, now: str) -> None:
        """Re-derives a learning's confidence from its basis and applies the upgrade/propose
        rule (§3, §7): an upgrade (or unchanged) is applied immediately; a downgrade is only
        *proposed* (written to proposed_confidence), leaving the live level intact."""
        cursor.execute(
            "SELECT confidence, proposed_confidence FROM coach_learnings WHERE id=?",
            (learning_id,)
        )
        row = cursor.fetchone()
        if not row:
            return
        current = row["confidence"] or "tentative"
        sup, con = self._evidence_counts(cursor, learning_id)
        derived = derive_confidence(sup, con)
        if confidence_rank(derived) >= confidence_rank(current):
            # Earned upgrade (or no change): apply now, clear any pending downgrade.
            if derived != current or row["proposed_confidence"] is not None:
                cursor.execute(
                    "UPDATE coach_learnings SET confidence=?, proposed_confidence=NULL, "
                    "updated_at=? WHERE id=?",
                    (derived, now, learning_id)
                )
        else:
            # Downgrade: propose, don't apply.
            cursor.execute(
                "UPDATE coach_learnings SET proposed_confidence=?, updated_at=? WHERE id=?",
                (derived, now, learning_id)
            )

    # -------------------------------------------------------- delta application

    def apply_learning_deltas(
        self, deltas: List[Dict[str, Any]],
        available_weeks: Optional[Iterable[str]] = None, source: str = "reflect"
    ) -> Dict[str, int]:
        """Applies evidence-cited learning operations in one transaction, then recomputes the
        confidence of every touched learning from its (updated) basis.

        Each delta is one of (DESIGN_evidence_based_confidence.md §6):
          {"op": "add", "text": "...", "sports"?: "...", "evidence"?: [weeks]}
          {"op": "revise", "id": <int>, "text"?: "...", "sports"?: "...", "evidence"?: [weeks]}
          {"op": "reinforce", "id": <int>, "evidence": [weeks]}   # no evidence ⇒ no-op
          {"op": "contradict", "id": <int>, "evidence": [weeks], "reason"?: "..."}
          {"op": "retire", "id": <int>}                            # archives it

        The LLM no longer sets confidence — it only attributes observations to the
        `week_commencing` weeks it was shown. Cited weeks are normalized to their Monday and,
        when `available_weeks` is provided, validated against it (weeks outside the analysed
        window are dropped, mirroring the skip-malformed philosophy). `last_reinforced_at` is
        refreshed only when a *new* supporting week actually lands — so re-citing counted
        weeks neither inflates confidence nor resets decay. Malformed deltas, and deltas
        addressed to a missing or archived learning, are skipped.

        Returns `{"applied": n, "skipped": n}`. Skipping stays silent here, but the count
        does not: a response whose deltas ALL skip is indistinguishable from one that
        authored none, and the caller has to be able to tell those apart
        (DESIGN_backward_evaluation.md §13).
        """
        tally = {"applied": 0, "skipped": 0}
        if not deltas:
            return tally
        allowed: Optional[Set[str]] = None
        if available_weeks is not None:
            allowed = {
                m for m in (_monday_str(w) for w in available_weeks if isinstance(w, str))
                if m
            }
        now = datetime.now(timezone.utc).isoformat()

        def filtered(raw_weeks: Any) -> List[str]:
            if not isinstance(raw_weeks, (list, tuple)):
                return []
            out = []
            for w in raw_weeks:
                m = _monday_str(w) if isinstance(w, str) else None
                if m and (allowed is None or m in allowed):
                    out.append(m)
            return out

        def _exists(cursor, lid) -> bool:
            cursor.execute(
                "SELECT 1 FROM coach_learnings WHERE id=? AND status=?", (lid, ACTIVE)
            )
            return cursor.fetchone() is not None

        touched: Set[int] = set()
        with self._get_connection() as conn:
            cursor = conn.cursor()
            for delta in deltas:
                if not isinstance(delta, dict):
                    tally["skipped"] += 1
                    continue
                op = delta.get("op")
                if op == "add":
                    text = (delta.get("text") or "").strip()
                    if not text:
                        tally["skipped"] += 1
                        continue
                    cursor.execute(
                        "INSERT INTO coach_learnings (text, sports, confidence, created_at, "
                        "updated_at, last_reinforced_at) VALUES (?, ?, 'tentative', ?, ?, ?)",
                        (text, normalize_sports(delta.get("sports")), now, now, now)
                    )
                    lid = cursor.lastrowid
                    self._add_evidence_weeks(
                        cursor, lid, filtered(delta.get("evidence")), +1, source, now
                    )
                    touched.add(lid)
                    tally["applied"] += 1
                elif op == "revise":
                    lid = delta.get("id")
                    if lid is None or not _exists(cursor, lid):
                        tally["skipped"] += 1
                        continue  # skip hallucinated ids (FK would abort the txn)
                    sets, params = [], []
                    text = (delta.get("text") or "").strip()
                    if text:
                        sets.append("text=?")
                        params.append(text)
                    if delta.get("sports"):
                        sets.append("sports=?")
                        params.append(normalize_sports(delta.get("sports")))
                    if sets:
                        sets.append("updated_at=?")
                        params.append(now)
                        params.append(lid)
                        cursor.execute(
                            f"UPDATE coach_learnings SET {', '.join(sets)} WHERE id=?", params
                        )
                    new_weeks = self._add_evidence_weeks(
                        cursor, lid, filtered(delta.get("evidence")), +1, source, now
                    )
                    if new_weeks:
                        cursor.execute(
                            "UPDATE coach_learnings SET last_reinforced_at=? WHERE id=?",
                            (now, lid)
                        )
                    touched.add(lid)
                    tally["applied"] += 1
                elif op == "reinforce":
                    lid = delta.get("id")
                    if lid is None or not _exists(cursor, lid):
                        tally["skipped"] += 1
                        continue
                    new_weeks = self._add_evidence_weeks(
                        cursor, lid, filtered(delta.get("evidence")), +1, source, now
                    )
                    # Recency follows evidence: only a genuinely new week keeps it fresh.
                    if new_weeks:
                        cursor.execute(
                            "UPDATE coach_learnings SET last_reinforced_at=? WHERE id=?",
                            (now, lid)
                        )
                        touched.add(lid)
                    # A re-cited week lands nothing by design, so this counts as applied
                    # either way — it is a recognized op against a real learning.
                    tally["applied"] += 1
                elif op == "contradict":
                    lid = delta.get("id")
                    if lid is None or not _exists(cursor, lid):
                        tally["skipped"] += 1
                        continue
                    new_weeks = self._add_evidence_weeks(
                        cursor, lid, filtered(delta.get("evidence")), -1, source, now,
                        reason=_one_line(delta.get("reason")),
                    )
                    if new_weeks:
                        touched.add(lid)
                    tally["applied"] += 1
                elif op == "retire":
                    lid = delta.get("id")
                    if lid is None or not _exists(cursor, lid):
                        tally["skipped"] += 1
                        continue
                    self._archive(cursor, lid, now)
                    tally["applied"] += 1
                else:
                    # No recognized op — the delta named something the app cannot act on
                    # (or the key itself came back mangled, as with a model that prefixes
                    # every nested key). Skipping is right; hiding it is not.
                    tally["skipped"] += 1

            # Re-level every touched learning from its (updated) basis in the same transaction
            # the denormalized confidence column lives in.
            for lid in touched:
                self._recompute_confidence(cursor, lid, now)
        return tally

    def recompute_all_confidence(self) -> None:
        """Re-derives confidence for every learning from its basis (upgrade auto-applies,
        downgrade is proposed). Used to re-level after `learning_confidence_thresholds`
        changes — no migration needed (§3)."""
        now = datetime.now(timezone.utc).isoformat()
        with self._get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("SELECT id FROM coach_learnings")
            ids = [row["id"] for row in cursor.fetchall()]
            for lid in ids:
                self._recompute_confidence(cursor, lid, now)

    # ---------------------------------------------------- staleness & proposals

    def apply_staleness_steps(self) -> None:
        """Lowers each active learning that has gone dormant by one level and re-arms its
        clock at the lower level's shorter budget, so an untouched learning walks down over
        real time; below tentative it is archived. Every reflect and bootstrap run applies
        these, and a learning with a proposal pending is left to that proposal
        (DESIGN_learning_doubt_nudge.md §3.2)."""
        now_dt = datetime.now(timezone.utc)
        now = now_dt.isoformat()
        with self._get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute(
                "SELECT id, confidence, proposed_confidence, created_at, last_reinforced_at "
                "FROM coach_learnings WHERE status=?",
                (ACTIVE,)
            )
            rows = [dict(r) for r in cursor.fetchall()]
            for row in rows:
                if row.get("proposed_confidence") or not learning_is_dormant(row, now_dt):
                    continue
                target = step_down(row["confidence"] or "tentative")
                if target == RETIRE_PROPOSAL:
                    self._archive(cursor, row["id"], now)
                    continue
                cursor.execute(
                    "UPDATE coach_learnings SET confidence=?, last_reinforced_at=?, "
                    "updated_at=? WHERE id=?",
                    (target, now, now, row["id"])
                )

    def demote_learning(self, learning_id: int) -> Optional[str]:
        """Accepts a pending downgrade: writes confidence = proposed_confidence, clears the
        proposal and re-arms the dormancy clock at the new level, or archives the learning
        on the retirement sentinel (DESIGN_learning_doubt_nudge.md §6). Returns the new
        level, 'retired', or None if nothing was pending."""
        now = datetime.now(timezone.utc).isoformat()
        with self._get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute(
                "SELECT proposed_confidence FROM coach_learnings WHERE id=?", (learning_id,)
            )
            row = cursor.fetchone()
            if not row or not row["proposed_confidence"]:
                return None
            target = row["proposed_confidence"]
            if target == RETIRE_PROPOSAL:
                self._archive(cursor, learning_id, now)
                return "retired"
            cursor.execute(
                "UPDATE coach_learnings SET confidence=?, proposed_confidence=NULL, "
                "last_reinforced_at=?, updated_at=? WHERE id=?",
                (target, now, now, learning_id)
            )
            return target

    def keep_learning(self, learning_id: int) -> None:
        """Overrules a pending downgrade (§7): deletes the contradicting weeks behind it,
        clears the proposal and re-derives confidence. Staleness steps apply directly, so
        every proposal is a contradiction (DESIGN_learning_doubt_nudge.md §3.2)."""
        now = datetime.now(timezone.utc).isoformat()
        with self._get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute(
                "SELECT proposed_confidence FROM coach_learnings WHERE id=?", (learning_id,)
            )
            row = cursor.fetchone()
            if not row or not row["proposed_confidence"]:
                return
            cursor.execute(
                "DELETE FROM learning_evidence WHERE learning_id=? AND polarity < 0",
                (learning_id,)
            )
            cursor.execute(
                "UPDATE coach_learnings SET proposed_confidence=NULL, updated_at=? WHERE id=?",
                (now, learning_id)
            )
            self._recompute_confidence(cursor, learning_id, now)
