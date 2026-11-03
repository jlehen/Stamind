"""`data backup`: the snapshot holds what the WAL holds, and both files reach the bucket."""
import gzip
import os
import sqlite3
import tempfile
import unittest
from unittest.mock import MagicMock, patch

from stamind.cli.data import backup
from stamind.config import config


def _wal_db(path: str) -> sqlite3.Connection:
    """A WAL database whose one row is committed but not checkpointed into the file."""
    conn = sqlite3.connect(path)
    conn.execute("PRAGMA journal_mode = WAL")
    conn.execute("PRAGMA wal_autocheckpoint = 0")
    conn.execute("CREATE TABLE t (x)")
    conn.execute("INSERT INTO t VALUES (42)")
    conn.commit()
    return conn


def _rows(data: bytes) -> list:
    """The rows of a snapshot written to disk, as a restore would."""
    with tempfile.TemporaryDirectory() as where:
        path = os.path.join(where, "restored.db")
        with open(path, "wb") as f:
            f.write(data)
        conn = sqlite3.connect(path)
        try:
            return conn.execute("SELECT x FROM t").fetchall()
        finally:
            conn.close()


class DataBackupTests(unittest.TestCase):
    def setUp(self):
        self.dir = tempfile.TemporaryDirectory()
        self.db = os.path.join(self.dir.name, "stamind.db")
        self.writer = _wal_db(self.db)
        self.config_file = os.path.join(self.dir.name, "config_x.yaml")
        with open(self.config_file, "wb") as f:
            f.write(b"google: {}\n")

    def tearDown(self):
        self.writer.close()
        self.dir.cleanup()

    def test_snapshot_holds_the_wal(self):
        self.assertEqual(_rows(backup.snapshot(self.db)), [(42,)])

    def test_uploads_the_database_and_the_config_file(self):
        remote = MagicMock()
        with patch.dict(config.data, {"google": {"backup_bucket": "b"}, "database": self.db,
                                      "user_profile": {"name": "Sam"}}), \
                patch.object(backup, "CONFIG_PATH", self.config_file), \
                patch.object(backup._bucket, "Bucket", return_value=remote) as made:
            backup.run_data_backup(None)
        made.assert_called_once_with("b", "Sam")
        uploads = {c.args[0]: c.args[1] for c in remote.upload.call_args_list}
        self.assertEqual(uploads["config_x.yaml"], b"google: {}\n")
        self.assertEqual(_rows(gzip.decompress(uploads["stamind.db.gz"])), [(42,)])

    def test_pages_bucket_is_refused(self):
        with patch.dict(config.data, {"google": {"backup_bucket": "b", "storage_bucket": "b"}}), \
                patch.object(backup._bucket, "Bucket") as made:
            with self.assertRaises(SystemExit):
                backup.run_data_backup(None)
        made.assert_not_called()

    def test_failed_upload_exits_non_zero_and_names_the_file(self):
        remote = MagicMock()
        remote.upload.side_effect = RuntimeError
        with patch.dict(config.data, {"google": {"backup_bucket": "b"}, "database": self.db,
                                      "data_dir": self.dir.name, "user_profile": {}}), \
                patch.object(backup, "CONFIG_PATH", self.config_file), \
                patch.object(backup._bucket, "Bucket", return_value=remote):
            with self.assertRaises(SystemExit) as raised:
                backup.run_data_backup(None)
        self.assertIn("stamind.db.gz", raised.exception.code)
        remote.upload.assert_called_once()


if __name__ == "__main__":
    unittest.main()
