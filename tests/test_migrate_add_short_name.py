"""The one-off migration that adds `workouts.short_name` (DESIGN_calendar_miniapp.md §3.6).

The fixture is a database made by the current code with the column dropped again and the
stamp put back to 19: the shape the author's and the companion's databases have on the day
this ships.
"""
import importlib.util
import os
import shutil
import sqlite3
import tempfile
import unittest

from stamind.db import Database

_SCRIPT = os.path.join(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
    "scripts", "migrate_add_short_name.py",
)
_spec = importlib.util.spec_from_file_location("migrate_add_short_name", _SCRIPT)
migrate = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(migrate)


def _columns(path: str):
    conn = sqlite3.connect(path)
    try:
        return [row[1] for row in conn.execute("PRAGMA table_info(workouts)")]
    finally:
        conn.close()


class AddShortNameTest(unittest.TestCase):
    def setUp(self):
        self.dir = tempfile.mkdtemp(prefix="stamind-short-name-test-")
        self.addCleanup(shutil.rmtree, self.dir, True)
        self.path = os.path.join(self.dir, "athlete.db")
        db = Database(db_path=self.path)
        with db.workout_change(kind="generate", summary="before") as change:
            change.append(
                date="2026-07-02", sport_type="running", title="Hill repeats",
                description="6x90s", duration_minutes=60,
            )
        conn = sqlite3.connect(self.path)
        conn.execute("ALTER TABLE workouts DROP COLUMN short_name")
        conn.execute("DELETE FROM schema_version")
        conn.execute(
            "INSERT INTO schema_version (version, applied_at) VALUES (19, '2026-09-01')"
        )
        conn.commit()
        conn.close()

    def test_the_column_is_added_once(self):
        self.assertNotIn("short_name", _columns(self.path))

        self.assertTrue(migrate.add_short_name(self.path))
        self.assertFalse(migrate.add_short_name(self.path))

        self.assertEqual(_columns(self.path).count("short_name"), 1)

    def test_the_migrated_database_takes_a_short_name(self):
        """The new code opens the migrated file, keeps the old session, and writes and
        reads a short name through the live view."""
        migrate.add_short_name(self.path)
        db = Database(db_path=self.path)

        old = db.get_workouts()[0]
        self.assertEqual(old["title"], "Hill repeats")
        self.assertIsNone(old["short_name"])

        with db.workout_change(kind="adapt", summary="after") as change:
            change.append(
                date="2026-07-02", sport_type="running", title="Short hill repeats",
                description="4x90s", short_name="Hills",
            )
        self.assertEqual(db.get_workouts()[0]["short_name"], "Hills")


if __name__ == "__main__":
    unittest.main()
