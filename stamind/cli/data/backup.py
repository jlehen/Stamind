"""`data backup`: uploads a snapshot of this instance's database and its config file to a
private bucket, under the athlete's name (README, "Backups"). The bot runs it nightly; the bucket's
version history keeps the older copies, so nothing here deletes or names by date.
"""
import argparse
import gzip
import os
import pathlib
import sqlite3

from stamind.config import CONFIG_PATH, config
from stamind.page_files import bucket as _bucket
from stamind.text import green


def snapshot(path: str) -> bytes:
    """The database as one consistent file, taken by SQLite's backup call so a bot writing
    at the same moment cannot leave a half-copied page in it."""
    source = sqlite3.connect(f"file:{path}?mode=ro", uri=True)
    copy = sqlite3.connect(":memory:")
    try:
        source.backup(copy)
        return copy.serialize()
    finally:
        source.close()
        copy.close()


def run_data_backup(args: argparse.Namespace) -> None:
    """Uploads `<db>.gz` and the config file; exits non-zero on a failure."""
    if not config.backup_bucket:
        raise SystemExit("✗ No backup bucket is configured. Write its name in config.yaml "
                         "as google.backup_bucket (README, \"Backups\").")
    if config.backup_bucket == config.storage_bucket:
        raise SystemExit("✗ google.backup_bucket names the pages' bucket, which anyone can "
                         "read. Create a private bucket for the backups (README, \"Backups\").")
    folder = (config.user_profile.get("name")
              or os.path.basename(os.path.normpath(config.data_dir)))
    remote = _bucket.Bucket(config.backup_bucket, folder)
    files = {
        os.path.basename(config.db_path) + ".gz": gzip.compress(snapshot(config.db_path)),
        os.path.basename(CONFIG_PATH): pathlib.Path(CONFIG_PATH).read_bytes(),
    }
    for name, data in files.items():
        try:
            remote.upload(name, data)
        except Exception as exc:
            raise SystemExit(f"✗ {name} was not uploaded ({_bucket.describe(exc)}).")
    print(green(f"✓ Uploaded {', '.join(files)} to {remote.name}/{remote.folder}/."))
