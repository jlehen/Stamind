"""The one-off migration that adds `workouts.short_name` and `mesocycles.summary`
(DESIGN_calendar_miniapp.md §3.6, §3.7).

The fixture is a database made by the current code with both columns dropped again and the
stamp put back to 20: the shape the author's and the companion's databases have on the day
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
    "scripts", "migrate_calendar_columns.py",
)
_spec = importlib.util.spec_from_file_location("migrate_calendar_columns", _SCRIPT)
migrate = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(migrate)


def _columns(path: str, table: str):
    conn = sqlite3.connect(path)
    try:
        return [row[1] for row in conn.execute(f"PRAGMA table_info({table})")]
    finally:
        conn.close()


class AddColumnsTest(unittest.TestCase):
    def setUp(self):
        self.dir = tempfile.mkdtemp(prefix="stamind-calendar-columns-test-")
        self.addCleanup(shutil.rmtree, self.dir, True)
        self.path = os.path.join(self.dir, "athlete.db")
        db = Database(db_path=self.path)
        with db.workout_change(kind="generate", summary="before") as change:
            change.append(
                date="2026-07-02", sport_type="running", title="Hill repeats",
                description="6x90s", duration_minutes=60,
            )
        goal = db.add_objective(title="Autumn 10k", target_date="2026-10-18",
                                sport_type="running")
        db.save_macrocycle(
            objective_id=goal, strategy="s", goals_hash="g", constraints_hash="c",
            mesocycles=[{"name": "Build", "start_date": "2026-07-01",
                         "end_date": "2026-07-31", "focus": "f"}],
        )
        conn = sqlite3.connect(self.path)
        conn.execute("ALTER TABLE workouts DROP COLUMN short_name")
        conn.execute("ALTER TABLE mesocycles DROP COLUMN summary")
        conn.execute("DELETE FROM schema_version")
        conn.execute(
            "INSERT INTO schema_version (version, applied_at) VALUES (20, '2026-09-26')"
        )
        conn.commit()
        conn.close()

    def test_each_column_is_added_once(self):
        self.assertNotIn("short_name", _columns(self.path, "workouts"))
        self.assertNotIn("summary", _columns(self.path, "mesocycles"))

        self.assertEqual(migrate.add_columns(self.path),
                         ["workouts.short_name", "mesocycles.summary"])
        self.assertEqual(migrate.add_columns(self.path), [])

        self.assertEqual(_columns(self.path, "workouts").count("short_name"), 1)
        self.assertEqual(_columns(self.path, "mesocycles").count("summary"), 1)

    def test_the_migrated_database_takes_both(self):
        """The new code opens the migrated file, keeps the old rows, and writes and reads
        a short name and a summary."""
        migrate.add_columns(self.path)
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

        goal = db.add_objective(title="Winter 10k", target_date="2026-12-13",
                                sport_type="running")
        db.save_macrocycle(
            objective_id=goal, strategy="s", goals_hash="g2", constraints_hash="c",
            mesocycles=[{"name": "Base", "start_date": "2026-10-19", "end_date": "2026-11-15",
                         "focus": "f", "summary": "Easy volume back"}],
        )
        mesocycles, _ = db.get_governing_mesocycles("2026-07-01", "2026-12-13")
        self.assertIn("Easy volume back", [m["summary"] for m in mesocycles])


if __name__ == "__main__":
    unittest.main()
