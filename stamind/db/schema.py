import sqlite3
from datetime import datetime, timezone

# Bump when the DDL below changes, so an existing database picks the change up once.
# Reusing a number a previous commit already stamped is silent (ARCHITECTURE.md §5).
SCHEMA_VERSION = 18

# The append-only rule, as the database enforces it (DESIGN_workout_revisions.md §14).
# `wipe_workouts` drops both triggers to clear the table and puts them back from here, so
# the rule is written once; `IF NOT EXISTS` is what lets the one text serve both callers.
# Two statements, because `execute` takes one and `executescript` would commit.
WORKOUTS_APPEND_ONLY_TRIGGERS = (
    """
    CREATE TRIGGER IF NOT EXISTS workouts_no_update BEFORE UPDATE ON workouts
    WHEN NOT (OLD.lineage_id IS NULL AND NEW.lineage_id = NEW.id)
    BEGIN SELECT RAISE(ABORT, 'workouts is append-only: append a revision'); END
    """,
    """
    CREATE TRIGGER IF NOT EXISTS workouts_no_delete BEFORE DELETE ON workouts
    BEGIN SELECT RAISE(ABORT, 'workouts is append-only: append a void revision'); END
    """,
)


class SchemaMixin:
    """The DDL, and the stamp that makes it run once.

    Every table is created at SCHEMA_VERSION and the version recorded; a later start reads
    the stamp and does nothing. Each table is documented at its columns in ARCHITECTURE.md
    §5, which is also where the CREATE-only policy is written down.
    """

    def _schema_version(self, conn: sqlite3.Connection) -> int:
        """The version this database has been brought up to, 0 if never stamped."""
        conn.execute(
            "CREATE TABLE IF NOT EXISTS schema_version ("
            "  version INTEGER NOT NULL,"
            "  applied_at TEXT NOT NULL"
            ")"
        )
        row = conn.execute("SELECT MAX(version) FROM schema_version").fetchone()
        return int(row[0]) if row and row[0] is not None else 0

    def _stamp_schema_version(self, conn: sqlite3.Connection, version: int) -> None:
        conn.execute(
            "INSERT INTO schema_version (version, applied_at) VALUES (?, ?)",
            (version, datetime.now(timezone.utc).isoformat()),
        )

    def _init_db(self) -> None:
        """Creates every table at SCHEMA_VERSION, then does nothing on later starts.

        CREATE-only: what the old in-place migrations built is folded into the statements
        below, in the column order they produced (ARCHITECTURE.md §5).
        """
        with self._get_connection() as conn:
            if self._schema_version(conn) >= SCHEMA_VERSION:
                return

        with self._get_connection() as conn:
            cursor = conn.cursor()

            # Objectives table
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS objectives (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    title TEXT NOT NULL,
                    target_date TEXT NOT NULL,
                    sport_type TEXT NOT NULL,
                    description TEXT,
                    status TEXT DEFAULT 'active', -- 'active' | 'archived'; see below
                    date_type TEXT NOT NULL DEFAULT 'event' -- 'event' | 'horizon'; see below
                )
            """)

            # Unified directives — everything the athlete asks the coach to work around, at
            # any horizon (DESIGN_constraints.md §5). A constraint is advisory prose the coach
            # reads unless `rest = 1`, the single deterministic edge: a no-training window
            # whose dates skip the LLM and are forced to rest. `replan` marks one escalated to
            # plan-shaping (§7).
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS constraints (
                    id          INTEGER PRIMARY KEY AUTOINCREMENT,
                    start_date  TEXT NOT NULL,
                    end_date    TEXT NOT NULL,
                    rest        INTEGER NOT NULL DEFAULT 0,
                    title       TEXT NOT NULL,
                    description TEXT,
                    replan      INTEGER NOT NULL DEFAULT 0,
                    source      TEXT,
                    created     TEXT,
                    -- When a coach pass last had this constraint in scope with authority
                    -- over every day of it still ahead (DESIGN_constraint_honoring.md §2).
                    -- NULL = the schedule does not reflect it yet. Not "the schedule
                    -- definitely changed".
                    honored_at  TEXT
                )
            """)
            cursor.execute(
                "CREATE INDEX IF NOT EXISTS idx_constraints_start ON constraints(start_date)"
            )

            # Workouts — an append-only revision log (DESIGN_workout_revisions.md §2).
            # A row is one revision of one session and is never updated or deleted; the
            # highest `id` in a `(date, sport_canonical)` slot is the live one. The
            # triggers at the end of this method are what enforce that (§14).
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS workouts (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    change_id INTEGER NOT NULL, -- the workout_changes row that appended this revision
                    lineage_id INTEGER, -- stable session identity; equals id on a first revision (§4)
                    date TEXT NOT NULL,
                    sport_canonical TEXT NOT NULL, -- the slot key (stamind.sports)
                    sport_type TEXT NOT NULL, -- the spelling as written
                    title TEXT NOT NULL,
                    description TEXT,
                    duration_minutes INTEGER,
                    rpe INTEGER,
                    tss INTEGER,
                    void INTEGER NOT NULL DEFAULT 0, -- 1 <=> this slot holds no session as of this revision
                    reason TEXT, -- per-revision note; why it changed, or why it was cancelled
                    restored_from INTEGER, -- on a rollback/reinstate copy: the revision copied (§7)
                    macrocycle_id INTEGER, -- plan version this session belongs to
                    created_at TEXT, -- when the SESSION entered the plan, carried across revisions
                    benchmark_type TEXT, -- set <=> a fitness test (DESIGN_benchmark_workouts.md §3.1)
                    planned_zone_currency TEXT, -- 'hr' | 'power' (DESIGN_intensity_distribution.md §9.8)
                    planned_zone1_sec INTEGER,
                    planned_zone2_sec INTEGER,
                    planned_zone3_sec INTEGER,
                    planned_zone4_sec INTEGER,
                    planned_zone5_sec INTEGER,
                    planned_zone6_sec INTEGER,
                    planned_zone7_sec INTEGER
                )
            """)

            # One row per command invocation that wrote workouts (§3). `kind` is fixed at
            # write time from the §3 vocabulary, `summary` is the batch rationale, and
            # `macrocycle_id` is the plan version in force when the command ran — context
            # for `workout batches`, distinct from the per-row tag on `workouts`.
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS workout_changes (
                    id            INTEGER PRIMARY KEY AUTOINCREMENT,
                    created_at    TEXT    NOT NULL,
                    kind          TEXT    NOT NULL,
                    summary       TEXT,
                    macrocycle_id INTEGER,
                    -- The coach's one line to the athlete about this change, for the
                    -- morning push (DESIGN_plan_change_continuity.md §6.3). NULL on a
                    -- change with nothing the athlete would notice, which is most of them.
                    note          TEXT,
                    -- The last day of the commitment window in force when this change ran,
                    -- so a void is judged by the window it was written under rather than by
                    -- the one standing whenever the Calendar sync happens to run (§5.2).
                    commitment_end TEXT,
                    -- When the athlete was told about it (DESIGN_change_heads_up.md §6).
                    told_at       TEXT
                )
            """)

            # Calendar sync bookkeeping, keyed by lineage (§8). Off the row because a
            # successful push is not a prescription change: leaving it there would make
            # `workout push -f` append a revision per session.
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS workout_calendar_state (
                    lineage_id                 INTEGER PRIMARY KEY,
                    google_event_id            TEXT,
                    pushed_signature           TEXT,
                    adherence_pushed_signature TEXT
                )
            """)

            # The first serves the live view, the second every lineage derivation (§3).
            cursor.execute(
                "CREATE INDEX IF NOT EXISTS idx_workouts_slot "
                "ON workouts(date, sport_canonical, id)"
            )
            cursor.execute(
                "CREATE INDEX IF NOT EXISTS idx_workouts_lineage "
                "ON workouts(lineage_id, id)"
            )

            # The live view (§5): `id` is AUTOINCREMENT and therefore monotonic, so the
            # highest id in a slot is its newest revision. Void revisions are included on
            # purpose — a cancelled session is still a fact readers must see.
            cursor.execute("DROP VIEW IF EXISTS live_workouts")
            cursor.execute("""
                CREATE VIEW live_workouts AS
                SELECT w.* FROM workouts w
                WHERE w.id = (
                    SELECT MAX(w2.id) FROM workouts w2
                    WHERE w2.date = w.date AND w2.sport_canonical = w.sport_canonical
                )
            """)

            # Append-only, enforced where it cannot be skipped (§14). The UPDATE trigger
            # exempts exactly one transition — the post-insert lineage seeding of §4 — and
            # pins the value it may write to the row's own id.
            for statement in WORKOUTS_APPEND_ONLY_TRIGGERS:
                cursor.execute(statement)

            # Benchmark results logbook (DESIGN_benchmark_workouts.md §3.2), one row per
            # measurement and the ONLY home for the athlete's trainable thresholds (§3.4).
            # The effective-threshold accessor reads the latest row per anchor_kind — newest
            # by date, id as tiebreak — and feeds it to the prompt and the staleness check.
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS benchmark_results (
                    id          INTEGER PRIMARY KEY AUTOINCREMENT,
                    date        TEXT NOT NULL,
                    sport_type  TEXT NOT NULL,
                    anchor_kind TEXT NOT NULL, -- ftp|lthr|threshold_pace|css|e1rm|mas
                    value       REAL NOT NULL,
                    unit        TEXT NOT NULL, -- W|bpm|min/km|sec/100m|kg|km/h
                    source      TEXT NOT NULL DEFAULT 'test', -- test|manual|modeled
                    workout_id  INTEGER,       -- nullable link to the planned benchmark
                    note        TEXT,
                    created     TEXT
                )
            """)
            cursor.execute(
                "CREATE INDEX IF NOT EXISTS idx_benchmark_results_kind "
                "ON benchmark_results(anchor_kind, date)"
            )

            # Completed activities table
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS completed_activities (
                    activity_id TEXT PRIMARY KEY,
                    date TEXT NOT NULL,
                    start_time TEXT,
                    activity_name TEXT,
                    activity_type TEXT NOT NULL,
                    duration_sec REAL,
                    distance_km REAL,
                    elevation_gain_m REAL,
                    avg_hr INTEGER,
                    max_hr INTEGER,
                    rpe INTEGER,
                    tss REAL,
                    bike_avg_watts INTEGER DEFAULT NULL,
                    zone1_sec INTEGER DEFAULT NULL,
                    zone2_sec INTEGER DEFAULT NULL,
                    zone3_sec INTEGER DEFAULT NULL,
                    zone4_sec INTEGER DEFAULT NULL,
                    zone5_sec INTEGER DEFAULT NULL,
                    -- Power zones use Garmin's 7-zone model (cycling with a power meter).
                    power_zone1_sec INTEGER DEFAULT NULL,
                    power_zone2_sec INTEGER DEFAULT NULL,
                    power_zone3_sec INTEGER DEFAULT NULL,
                    power_zone4_sec INTEGER DEFAULT NULL,
                    power_zone5_sec INTEGER DEFAULT NULL,
                    power_zone6_sec INTEGER DEFAULT NULL,
                    power_zone7_sec INTEGER DEFAULT NULL,
                    -- Whether a strength session's sets were read, frozen or discarded
                    -- (DESIGN_strength_tracking.md §5). The summary upsert names its
                    -- columns, so a pull never touches these three.
                    sets_read_at TEXT DEFAULT NULL,
                    sets_final_at TEXT DEFAULT NULL,
                    discarded INTEGER NOT NULL DEFAULT 0
                )
            """)

            # The athlete's answers to "is this activity that session?" — the pairing
            # questions `adherence.is_ambiguous_match` raises (ARCHITECTURE.md §15).
            # Keyed by (activity, sport), not by workout id: workout rows are replaced on
            # every revision, so a workout id would go stale the next time the day is
            # adapted, and the athlete would be asked the same question again.
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS activity_match_decisions (
                    activity_id TEXT NOT NULL,
                    sport_canonical TEXT NOT NULL,
                    accepted INTEGER NOT NULL,
                    decided_at TEXT NOT NULL,
                    PRIMARY KEY (activity_id, sport_canonical)
                )
            """)

            # Athlete metrics cache table
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS athlete_metrics_cache (
                    date TEXT PRIMARY KEY,
                    rhr INTEGER,
                    hrv INTEGER,
                    sleep_score INTEGER,
                    stress INTEGER,
                    ctl REAL,
                    atl REAL,
                    tsb REAL
                )
            """)
            # Athlete baselines table
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS athlete_baselines (
                    date TEXT PRIMARY KEY,
                    rhr_baseline_mean REAL,
                    rhr_baseline_std REAL,
                    hrv_baseline_mean REAL,
                    hrv_baseline_std REAL,
                    sleep_baseline_mean REAL,
                    sleep_baseline_std REAL
                )
            """)

            # Coach learnings: discrete, addressable athlete-observation records, updated
            # incrementally via deltas (see apply_learning_deltas). `confidence` is
            # APP-COMPUTED from the evidence basis in learning_evidence below, never
            # LLM-asserted (DESIGN_evidence_based_confidence.md); `proposed_confidence`
            # holds a pending human-confirmable DOWNGRADE; `status` is 'active' | 'archived',
            # and retiring a learning archives it (DESIGN_learning_doubt_nudge.md §6).
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS coach_learnings (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    text TEXT NOT NULL,
                    sports TEXT NOT NULL DEFAULT 'general',
                    confidence TEXT NOT NULL DEFAULT 'tentative',
                    proposed_confidence TEXT,
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL,
                    last_reinforced_at TEXT,
                    status TEXT DEFAULT 'active'
                )
            """)

            # Evidence basis (DESIGN_evidence_based_confidence.md §5). The distinct training
            # WEEKS that back each learning, tagged +1 supporting / -1 contradicting. Confidence
            # is a pure function of this basis. UNIQUE(learning_id, week_commencing, polarity)
            # is the dedup guarantee: re-citing a counted (week, polarity) is an INSERT-OR-IGNORE
            # no-op, so re-running / --force / overlapping windows cannot inflate confidence.
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS learning_evidence (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    learning_id INTEGER NOT NULL,
                    week_commencing TEXT NOT NULL, -- YYYY-MM-DD (Monday)
                    polarity INTEGER NOT NULL,     -- +1 supporting | -1 contradicting
                    source TEXT,                   -- 'reflect'|'bootstrap'|'plan'|'manual'|'migration'
                    created_at TEXT NOT NULL,
                    reason TEXT,                   -- contradicting: what went against it
                    UNIQUE(learning_id, week_commencing, polarity),
                    FOREIGN KEY (learning_id) REFERENCES coach_learnings(id) ON DELETE CASCADE
                )
            """)
            # Macrocycles table
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS macrocycles (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    objective_id INTEGER NOT NULL,
                    strategy TEXT NOT NULL,
                    goals_hash TEXT NOT NULL,
                    constraints_hash TEXT NOT NULL,
                    config_hash TEXT,
                    config_snapshot TEXT,
                    profile_snapshot TEXT,
                    goals_snapshot TEXT,
                    constraints_snapshot TEXT,
                    all_constraints_snapshot TEXT,
                    science_snapshot TEXT,
                    created_at TEXT NOT NULL,
                    -- The verdict call's re-shaping read, cached against the snapshot it
                    -- was asked about (DESIGN_plan_change_continuity.md §7).
                    reshape_verdict TEXT,
                    reshape_verdict_key TEXT,
                    -- Plan-version axis (DESIGN_plan_rollback.md): a regenerated plan keeps
                    -- the prior macrocycle, marked 'superseded'. Exactly one is 'active'.
                    status TEXT DEFAULT 'active',
                    superseded_at TEXT,
                    FOREIGN KEY (objective_id) REFERENCES objectives(id) ON DELETE CASCADE
                )
            """)


            # Mesocycles table
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS mesocycles (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    macrocycle_id INTEGER NOT NULL,
                    name TEXT NOT NULL,
                    start_date TEXT NOT NULL,
                    end_date TEXT NOT NULL,
                    focus TEXT NOT NULL,
                    FOREIGN KEY (macrocycle_id) REFERENCES macrocycles(id) ON DELETE CASCADE
                )
            """)

            # The plan's feedback log (DESIGN_plan_feedback.md §6): an append-only list of
            # notes the athlete addressed to the NEXT plan version, attached to the version
            # they were written against. `mesocycle_id` NULL = plan-level. Pending means
            # "on the goal's active macrocycle" — supersession is the consumption event, so
            # there is no consumed flag.
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS plan_feedback (
                    id            INTEGER PRIMARY KEY AUTOINCREMENT,
                    macrocycle_id INTEGER NOT NULL,
                    mesocycle_id  INTEGER,
                    created_at    TEXT NOT NULL,
                    text          TEXT NOT NULL,
                    FOREIGN KEY (macrocycle_id) REFERENCES macrocycles(id)
                        ON DELETE CASCADE,
                    FOREIGN KEY (mesocycle_id) REFERENCES mesocycles(id) ON DELETE CASCADE
                )
            """)
            cursor.execute(
                "CREATE INDEX IF NOT EXISTS idx_plan_feedback_macro "
                "ON plan_feedback(macrocycle_id)"
            )
            # Backward-evaluation reconstruction cache (DESIGN_backward_evaluation.md §5.1),
            # keyed by an *evidence fingerprint* so a re-run over unchanged data skips the
            # LLM pass. One row per `horizon` (UNIQUE): a new data pull shifts the
            # fingerprint and overwrites the slot. One JSON blob — nothing queries inside it.
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS analysis_cache (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    horizon TEXT NOT NULL UNIQUE, -- 'long' | 'short' — the cache slot
                    fingerprint TEXT NOT NULL,    -- hash of activity-id set + metrics + window
                    window_start TEXT,
                    window_end TEXT,
                    reconstruction TEXT NOT NULL, -- JSON: inferred cycles + insights
                    created_at TEXT NOT NULL
                )
            """)

            # Sync watermark: how far Garmin data has been pulled, and when.
            # through_date is the FORWARD high-water mark (local YYYY-MM-DD); a
            # backward backfill never regresses it. last_pull_utc is an INSTANT
            # (UTC ISO) compared against now for the freshness interval. sync_token
            # is the opaque Calendar nextSyncToken — populated only by the
            # 'calendar_signals' row (DESIGN_calendar_signal_ingest.md §6.1).
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS sync_state (
                    key            TEXT PRIMARY KEY,
                    through_date   TEXT,
                    last_pull_utc  TEXT,
                    sync_token     TEXT
                )
            """)
            # External daily signals (alcohol, sleep, stress, …) ingested from
            # tagged Google Calendar events. Stamind stays domain-agnostic: metric is
            # an opaque category, value an optional numeric magnitude, text the human
            # blurb for the LLM. google_event_id is the reconciliation key so ingestion
            # is an upsert with edit/delete detection (DESIGN_calendar_signal_ingest.md §5).
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS daily_signals (
                    id              INTEGER PRIMARY KEY AUTOINCREMENT,
                    date            TEXT NOT NULL,
                    metric          TEXT NOT NULL,
                    value           REAL,
                    text            TEXT,
                    google_event_id TEXT NOT NULL UNIQUE,
                    updated         TEXT
                )
            """)
            cursor.execute(
                "CREATE INDEX IF NOT EXISTS idx_daily_signals_date ON daily_signals(date)"
            )

            # App preferences that outlive one invocation but aren't training data. Generic
            # key/value so the next single-value preference needs no schema change. First
            # key: 'llm_model' (DESIGN_model_selection.md §2).
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS settings (
                    key        TEXT PRIMARY KEY,
                    value      TEXT NOT NULL,
                    updated_at TEXT NOT NULL
                )
            """)

            # Questions and messages held for the athlete until she is there to answer.
            # A kind and subject are queued once, ever (DESIGN_athlete_queue.md §3).
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS athlete_queue (
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
            """)

            # Every set of a strength session as Garmin recorded it, rest entries included.
            # Rows go with their activity, so the pull's deletion reconcile and the Garmin
            # data wipe take them along (DESIGN_strength_tracking.md §5).
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS exercise_sets (
                    id            INTEGER PRIMARY KEY AUTOINCREMENT,
                    activity_id   TEXT NOT NULL,
                    seq           INTEGER NOT NULL,
                    set_type      TEXT NOT NULL,
                    exercise      TEXT,
                    garmin_name   TEXT,
                    reps          INTEGER,
                    load_kg       REAL,
                    duration_sec  REAL,
                    named_by      TEXT,
                    UNIQUE (activity_id, seq),
                    FOREIGN KEY (activity_id) REFERENCES completed_activities(activity_id)
                        ON DELETE CASCADE
                )
            """)

            # What the strength planner wrote for one revision of one strength session:
            # an exercise, a count of sets, a rep range and a load
            # (DESIGN_strength_tracking.md §9). Planned sessions are append-only, so these
            # belong to the revision and go with it.
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS prescribed_sets (
                    id          INTEGER PRIMARY KEY AUTOINCREMENT,
                    workout_id  INTEGER NOT NULL,
                    position    INTEGER NOT NULL,
                    exercise    TEXT NOT NULL,
                    sets        INTEGER NOT NULL,
                    reps_low    INTEGER NOT NULL,
                    reps_high   INTEGER NOT NULL,
                    load_kg     REAL,
                    light       INTEGER NOT NULL DEFAULT 0,
                    UNIQUE (workout_id, position),
                    FOREIGN KEY (workout_id) REFERENCES workouts(id) ON DELETE CASCADE
                )
            """)

            # Which evidence the strength planner last weighed for one session, so a
            # "keep" is not asked again the next morning with a fresh draw of randomness
            # (DESIGN_strength_tracking.md §9). Keyed by lineage: it follows the session.
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS strength_checks (
                    lineage_id       INTEGER PRIMARY KEY,
                    checked_against  TEXT NOT NULL
                )
            """)

            self._stamp_schema_version(conn, SCHEMA_VERSION)
            conn.commit()
