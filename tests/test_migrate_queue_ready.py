"""The one-off migration that gives the athlete queue's rows a ready time and a sent time
(DESIGN_athlete_queue.md §13.7).

The fixture is a database made by the current code whose `athlete_queue` is put back to the
shape of version 26, with three items: one waiting, one put off until Thursday 07:58, one
answered.
"""
import importlib.util
import os
import shutil
import sqlite3
import tempfile
import unittest
from datetime import datetime, timezone

from stamind.db import Database

_SCRIPT = os.path.join(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
    "scripts", "migrate_queue_ready.py",
)
_spec = importlib.util.spec_from_file_location("migrate_queue_ready", _SCRIPT)
migrate = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(migrate)

OLD_TABLE = """
    CREATE TABLE athlete_queue (
        id         INTEGER PRIMARY KEY AUTOINCREMENT,
        kind       TEXT NOT NULL,
        subject    TEXT NOT NULL,
        payload    TEXT NOT NULL,
        queued_at  TEXT NOT NULL,
        remind_at  TEXT,
        closed_at  TEXT,
        outcome    TEXT,
        UNIQUE (kind, subject)
    )
"""
QUEUED = "2026-10-07T06:00:00.000000+00:00"
PUT_OFF_UNTIL = "2026-10-08T05:58:00.000000+00:00"
OLD_ROWS = (
    ("message", "waiting", '{"text": "Charge your watch."}', QUEUED, None, None, None),
    ("message", "put off", '{"text": "Book the pool."}', QUEUED, PUT_OFF_UNTIL, None, None),
    ("message", "answered", '{"text": "Well done."}', QUEUED, None, QUEUED, "answered"),
)


class QueueReadyTest(unittest.TestCase):
    def setUp(self):
        self.dir = tempfile.mkdtemp(prefix="stamind-queue-ready-test-")
        self.addCleanup(shutil.rmtree, self.dir, True)
        self.path = os.path.join(self.dir, "athlete.db")
        Database(db_path=self.path)
        conn = sqlite3.connect(self.path)
        conn.execute("DROP TABLE athlete_queue")
        conn.execute(OLD_TABLE)
        conn.executemany(
            "INSERT INTO athlete_queue "
            "(kind, subject, payload, queued_at, remind_at, closed_at, outcome) "
            "VALUES (?, ?, ?, ?, ?, ?, ?)", OLD_ROWS,
        )
        conn.execute("DELETE FROM schema_version")
        conn.execute(
            "INSERT INTO schema_version (version, applied_at) VALUES (26, '2026-10-03')"
        )
        conn.commit()
        conn.close()

    def test_the_table_is_rebuilt_once(self):
        self.assertTrue(migrate.migrate(self.path))
        self.assertFalse(migrate.migrate(self.path))
        conn = sqlite3.connect(self.path)
        self.addCleanup(conn.close)
        columns = [row[1] for row in conn.execute("PRAGMA table_info(athlete_queue)")]
        self.assertIn("ready_at", columns)
        self.assertIn("sent_at", columns)
        self.assertNotIn("remind_at", columns)

    def test_a_put_off_item_keeps_its_time_and_the_others_are_ready_since_queued(self):
        migrate.migrate(self.path)
        db = Database(db_path=self.path)
        waiting, put_off = db.waiting_queue_items()
        self.assertEqual((waiting["subject"], waiting["ready_at"]), ("waiting", QUEUED))
        self.assertEqual((put_off["subject"], put_off["ready_at"]), ("put off", PUT_OFF_UNTIL))
        self.assertIsNone(waiting["sent_at"])
        [closed] = db.closed_queue_items()
        self.assertEqual((closed["subject"], closed["outcome"]), ("answered", "answered"))

    def test_the_migrated_database_queues_and_numbers_on(self):
        """The new code writes to the migrated file, and a new item does not take the id of
        an old one."""
        migrate.migrate(self.path)
        db = Database(db_path=self.path)
        now = datetime(2026, 10, 10, 9, 0, tzinfo=timezone.utc)
        item_id = db.queue_item("message", "new", {"text": "Hello."}, now)
        self.assertEqual(item_id, len(OLD_ROWS) + 1)
        self.assertIsNone(db.queue_item("message", "waiting", {"text": "Again."}, now))
        db.mark_queue_sent(item_id, now)
        self.assertIsNotNone(db.get_queue_item(item_id)["sent_at"])


if __name__ == "__main__":
    unittest.main()
