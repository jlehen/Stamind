"""The retrospectives' rows: one record per finished mesocycle and per finished plan
(DESIGN_cycle_retrospective.md §11).

The rows know nothing about when a record is created or removed; `stamind/cycle_records.py`
does (§3).
"""
import json
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

MESOCYCLE = "mesocycle"
PLAN = "plan"

# How a record ended (§3, §6).
FINISHED = "finished"
REPLACED = "replaced"
CALLED_OFF = "called_off"

# A record is written this many days after its end, so late Garmin data is in. Its
# question stays open for the same days (§4).
DUE_AFTER_DAYS = 7


def _record(row) -> Dict[str, Any]:
    record = dict(row)
    if record["numbers"] is not None:
        record["numbers"] = json.loads(record["numbers"])
    return record


class RetrospectivesMixin:
    """Create, list, write and remove the records."""

    def add_retrospective(
        self, objective_id: int, level: str, name: str, start_date: str, end_date: str,
        ended_by: str, intent: str,
    ) -> Optional[int]:
        """Creates a blank record and returns its id, or None when the goal already has a
        record of this level starting that day (§11)."""
        with self._get_connection() as conn:
            cursor = conn.execute(
                "INSERT OR IGNORE INTO retrospectives (objective_id, level, name, "
                "start_date, end_date, ended_by, intent, created_at) "
                "VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
                (objective_id, level, name, start_date, end_date, ended_by, intent,
                 datetime.now(timezone.utc).isoformat()),
            )
            conn.commit()
            return cursor.lastrowid if cursor.rowcount else None

    def get_retrospective(self, record_id: int) -> Optional[Dict[str, Any]]:
        with self._get_connection() as conn:
            row = conn.execute(
                "SELECT * FROM retrospectives WHERE id = ?", (record_id,)
            ).fetchone()
            return _record(row) if row else None

    def get_retrospectives(
        self, objective_id: Optional[int] = None, level: Optional[str] = None
    ) -> List[Dict[str, Any]]:
        """The records of one goal, or of every goal, oldest first."""
        clauses, params = [], []
        if objective_id is not None:
            clauses.append("objective_id = ?")
            params.append(objective_id)
        if level is not None:
            clauses.append("level = ?")
            params.append(level)
        where = f" WHERE {' AND '.join(clauses)}" if clauses else ""
        with self._get_connection() as conn:
            rows = conn.execute(
                f"SELECT * FROM retrospectives{where} ORDER BY end_date, start_date, id",
                params,
            ).fetchall()
            return [_record(row) for row in rows]

    def write_retrospective(
        self, record_id: int, numbers: Dict[str, Any], body: str, athlete_line: str
    ) -> None:
        """Stores what the write step produced: the numbers, the record lines and the
        sentence for the athlete (§5)."""
        with self._get_connection() as conn:
            conn.execute(
                "UPDATE retrospectives SET numbers = ?, body = ?, athlete_line = ?, "
                "written_at = ? WHERE id = ?",
                (json.dumps(numbers), body, athlete_line,
                 datetime.now(timezone.utc).isoformat(), record_id),
            )
            conn.commit()

    def set_retrospective_words(self, record_id: int, words: Optional[str]) -> None:
        """Stores the athlete's own words as typed, or clears them with None (§9)."""
        with self._get_connection() as conn:
            conn.execute(
                "UPDATE retrospectives SET athlete_words = ? WHERE id = ?",
                (words, record_id),
            )
            conn.commit()

    def delete_retrospective(self, record_id: int) -> None:
        with self._get_connection() as conn:
            conn.execute("DELETE FROM retrospectives WHERE id = ?", (record_id,))
            conn.commit()
