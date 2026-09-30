"""The record: what Stamind remembers of each file it uploaded for the pages
(DESIGN_miniapp_storage.md §6). A row is keyed by the file's full address, bucket, folder
and name, so a database run under another bot token or bucket finds no row of its own.
"""
from datetime import datetime, timezone
from typing import Any, Dict, Optional


class PageFilesMixin:
    """The `page_files` table, and the first day the calendar's history starts on."""

    def get_page_files(self) -> Dict[str, Dict[str, Any]]:
        """Every row, by address."""
        with self._get_connection() as conn:
            rows = conn.execute("SELECT * FROM page_files").fetchall()
        return {row["address"]: dict(row) for row in rows}

    def get_page_file(self, address: str) -> Optional[Dict[str, Any]]:
        with self._get_connection() as conn:
            row = conn.execute(
                "SELECT * FROM page_files WHERE address = ?", (address,)
            ).fetchone()
        return dict(row) if row else None

    def record_page_upload(self, address: str, label: str, fingerprint: str) -> None:
        """A file uploaded now, holding the content `fingerprint` names."""
        uploaded_at = datetime.now(timezone.utc).isoformat(timespec="microseconds")
        with self._get_connection() as conn:
            conn.execute(
                """
                INSERT INTO page_files (address, label, fingerprint, uploaded_at, error)
                VALUES (?, ?, ?, ?, NULL)
                ON CONFLICT(address) DO UPDATE SET
                    label=excluded.label, fingerprint=excluded.fingerprint,
                    uploaded_at=excluded.uploaded_at, error=NULL
                """,
                (address, label, fingerprint, uploaded_at),
            )
            conn.commit()

    def record_page_error(self, address: str, label: str, error: str) -> None:
        """The last attempt at a file failed; what it last held stays as it was."""
        with self._get_connection() as conn:
            conn.execute(
                """
                INSERT INTO page_files (address, label, error) VALUES (?, ?, ?)
                ON CONFLICT(address) DO UPDATE SET label=excluded.label, error=excluded.error
                """,
                (address, label, error),
            )
            conn.commit()

    def forget_page_file(self, address: str) -> None:
        with self._get_connection() as conn:
            conn.execute("DELETE FROM page_files WHERE address = ?", (address,))
            conn.commit()

    def forget_page_files(self) -> None:
        """Empties the record, as it was before `sm data publish` was ever run (§9.3)."""
        with self._get_connection() as conn:
            conn.execute("DELETE FROM page_files")
            conn.commit()

    def first_training_day(self) -> Optional[str]:
        """The earliest day on which the database holds a session or an activity, or None
        (§4, which months have a file)."""
        with self._get_connection() as conn:
            row = conn.execute(
                "SELECT MIN(day) FROM (SELECT MIN(date) AS day FROM live_workouts "
                "UNION ALL SELECT MIN(date) FROM completed_activities)"
            ).fetchone()
        return row[0]
