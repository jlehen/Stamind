import os
import sqlite3
from contextlib import contextmanager
from datetime import datetime, timezone
from typing import Any, Dict, Generator, Optional
from stamind.config import config


# How long a connection waits for a writer to finish before raising "database is
# locked". The CLI, the web app and the Telegram bot are concurrent surfaces against one
# file, so a pull that overlaps a dashboard refresh is ordinary, not exceptional.
BUSY_TIMEOUT_SECONDS = 5.0


class _JoinedConnection:
    """A connection borrowed from an open `transaction()`.

    Methods are written `with db._get_connection() as conn: ...; conn.commit()`, which
    is right when each call owns its connection. Inside a transaction those commits
    would end it early — one fsync per row, which is the cost the transaction exists to
    avoid — so they are deferred to the single commit at the end. Everything else
    forwards to the real connection untouched.
    """

    def __init__(self, conn: sqlite3.Connection):
        self._conn = conn

    def commit(self) -> None:
        """Deferred: the enclosing transaction commits once, at the end."""

    def __getattr__(self, name):
        return getattr(self._conn, name)

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False


class BaseDB:
    """The connection every mixin opens, and the transaction that joins several.

    Last in `Database`'s bases, so its `__init__` is the one that runs. The DDL it calls
    on the way in is `SchemaMixin` in `db/schema.py`.
    """

    def __init__(self, db_path: Optional[str] = None, calendar_hook=None) -> None:
        """Initializes database path and sets up tables.

        `calendar_hook` is what the §8 reconcile pass calls when a workout change closes:
        `hook(db, lineage_ids)`. Left unset the pass is inert, which is what an isolated
        unit test wants; `runtime._build_db` attaches the real one, so the running app
        cannot write workouts without reconciling Calendar
        (DESIGN_workout_revisions.md §8).
        """
        self.db_path: str = db_path or config.db_path
        # A fresh `data_dir:` instance must run before its directory exists — sqlite
        # won't create parents, and every other writer already makedirs its own.
        parent = os.path.dirname(self.db_path)
        if parent:
            os.makedirs(parent, exist_ok=True)
        self._joined: Optional[_JoinedConnection] = None
        self.calendar_hook = calendar_hook
        self._init_db()   # SchemaMixin, db/schema.py

    def _connect(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self.db_path, timeout=BUSY_TIMEOUT_SECONDS)
        conn.execute("PRAGMA foreign_keys = ON")
        # WAL lets a reader carry on while a writer commits, which is the normal case
        # here: the dashboard polls while `data pull` writes. It is a property of the
        # database file, so this takes effect once and persists.
        conn.execute("PRAGMA journal_mode = WAL")
        conn.row_factory = sqlite3.Row
        return conn

    @contextmanager
    def _get_connection(self) -> Generator[sqlite3.Connection, None, None]:
        """Creates and returns a connection to SQLite database with constraints enabled."""
        if self._joined is not None:
            yield self._joined
            return
        conn = self._connect()
        try:
            with conn:
                yield conn
        finally:
            conn.close()

    @contextmanager
    def transaction(self) -> Generator[sqlite3.Connection, None, None]:
        """Runs everything inside as one unit of work: one connection, one commit.

        Without it, each write opens, commits and closes its own connection — a PMC
        recompute over a long history did that around fifteen hundred times, after
        every pull. It also makes multi-step work atomic: regenerating a plan archives,
        supersedes, inserts and pushes, and a crash between those steps used to leave
        archived workouts with no active plan.

        Nesting joins the outer transaction rather than starting a second one, so a
        method that opens one is safe to call from inside another.
        """
        if self._joined is not None:
            yield self._joined
            return
        conn = self._connect()
        joined = _JoinedConnection(conn)
        self._joined = joined
        try:
            with conn:          # commits once here, or rolls back if the body raises
                yield joined
        finally:
            self._joined = None
            conn.close()


class SettingsMixin:
    """App preferences kept as key/value rows.

    See DESIGN_model_selection.md §2. Not training data — a data wipe leaves these alone.
    """

    def get_setting(self, key: str) -> Optional[str]:
        """Returns the stored value for `key`, or None if it was never set."""
        with self._get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("SELECT value FROM settings WHERE key = ?", (key,))
            row = cursor.fetchone()
            return row["value"] if row else None

    def get_setting_row(self, key: str) -> Optional[Dict[str, Any]]:
        """Returns {key, value, updated_at} for `key`, or None. Callers that report *when*
        a preference was last changed need the timestamp too."""
        with self._get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("SELECT key, value, updated_at FROM settings WHERE key = ?", (key,))
            row = cursor.fetchone()
            return dict(row) if row else None  # type: ignore

    def set_setting(self, key: str, value: str) -> None:
        """Upserts `key`, stamping updated_at with the current UTC instant."""
        now = datetime.now(timezone.utc).isoformat()
        with self._get_connection() as conn:
            conn.execute(
                "INSERT INTO settings (key, value, updated_at) VALUES (?, ?, ?) "
                "ON CONFLICT(key) DO UPDATE SET "
                "value=excluded.value, updated_at=excluded.updated_at",
                (key, value, now)
            )
            conn.commit()

    def clear_setting(self, key: str) -> bool:
        """Deletes `key`. Returns True if a row was actually removed."""
        with self._get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("DELETE FROM settings WHERE key = ?", (key,))
            conn.commit()
            return cursor.rowcount > 0
