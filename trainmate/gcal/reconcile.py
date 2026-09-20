"""Making Google Calendar agree with the workouts log (DESIGN_workout_revisions.md §8).

Two passes live here. The first pushes and tears down events so the Calendar shows
the sessions the log holds. The second, at the bottom, stamps the adherence verdict
onto the events of days already behind us — the same idea one step later, once the
activity that answered a session is known.

The event lifecycle used to piggyback on archival: archiving a plan cleared the event
handles and the service tore the events down, and a restore re-pushed. An append-only
table has no such hook, and nothing may creep into the append primitive to replace it — a
Calendar call inside the write path would put network I/O in a transaction and fail
workout writes on push errors.

Instead every change ends with one pass over the lineages it touched, after commit. The
`workout_change` handle schedules it, so the only way to write workouts already schedules
the reconcile; `runtime._build_db` is what attaches this module to the database handle.
"""
from contextlib import contextmanager
from typing import Any, Dict, Iterator, List, Optional, Sequence, Tuple

from trainmate import runtime
from trainmate.analytics.adherence import classify_adherence
from trainmate.analytics.compare import adherence_window, format_actual
from trainmate.workout_state import adherence_signature, calendar_status
from trainmate.clock import fmt_date, today_str as _today_str
from trainmate.config import config
from trainmate.db.workouts import ATHLETE_VOID_KINDS
from trainmate.text import green
from trainmate.output import Progress, fail, warn

# Whether a pass renders as one summary line and a bar, or as the per-event lines. The
# commands that take `-v` flip this around their write.
_verbose: bool = False

# Set by `no_calendar_sync()` while a write that must not reach the Calendar is running.
_suppressed: bool = False


@contextmanager
def no_calendar_sync() -> Iterator[None]:
    """Makes the pass a no-op for the writes inside it, leaving them `[STALE]` for the next
    `workout push` (§8). No command reaches it; it is how a test writes fixture state
    without the write path reconciling it first."""
    global _suppressed
    was, _suppressed = _suppressed, True
    try:
        yield
    finally:
        _suppressed = was


@contextmanager
def verbose_events() -> Iterator[None]:
    """Keeps the per-event Calendar lines, and no bar, so they scroll undisturbed (`-v`)."""
    global _verbose
    was, _verbose = _verbose, True
    try:
        yield
    finally:
        _verbose = was


def reconcile(db, lineage_ids: Sequence[int]) -> None:
    """Pushes, moves or tears down the Calendar events of the given lineages.

    Keyed on each lineage's newest revision, not on a slot: a move leaves the session
    with a void where it left and a copy where it landed, and the copy must speak for the
    lineage or this would delete an event it should move (§8).

    Decided first and executed second, so one batch of Calendar round-trips renders as one
    summary line and a bar rather than a page of per-event chatter.
    """
    if _suppressed:
        return
    pushes, teardowns = _plan(db, lineage_ids)
    total = len(pushes) + len(teardowns)
    if not total:
        return
    syncer = runtime.calendar_syncer
    with _framing(total) as bar:
        for workout in pushes:
            _push(syncer, workout)
            bar.step()
        for lineage_id, event_id in teardowns:
            _tear_down(db, syncer, lineage_id, event_id)
            bar.step()
    print(green("Google Calendar updated: " + _summary(len(pushes), len(teardowns)) + "."))


@contextmanager
def _framing(total: int) -> Iterator[Progress]:
    """A batch of Calendar writes under one bar; `-v` keeps the per-event lines instead."""
    if _verbose:
        yield Progress(0)
        return
    # Imported here, not at module load: `runtime._build_db` imports this module, so a
    # module-scope import would make every command that opens the database pay for
    # googleapiclient whether or not it has an event to push (ARCHITECTURE.md §15).
    from trainmate.gcal.client import quiet_events
    with quiet_events(), Progress(total) as bar:
        yield bar


def leaves_trace(head: Dict[str, Any]) -> bool:
    """Whether a void keeps its Calendar event, retitled, rather than the event being
    torn down (DESIGN_plan_change_continuity.md §5.2).

    A day the athlete was counting on does not disappear: it is marked, with a reason.
    Which days those are is the void's own two clauses — the athlete decided it, or it
    fell inside the commitment window the change that removed it ran under.
    """
    if head["change_kind"] in ATHLETE_VOID_KINDS:
        return True
    commitment_end = head.get("commitment_end")
    return commitment_end is not None and head["date"] <= commitment_end


def _plan(
    db, lineage_ids: Sequence[int]
) -> Tuple[List[Dict[str, Any]], List[Tuple[int, Optional[str]]]]:
    """What each lineage needs: a push, a teardown, or nothing.

    Read from the lineage's newest revision rather than from its slot: a void covered by
    a new session in the same slot is never the slot's live row, and a marker written and
    then covered in one run would be torn down the instant it was written (§5.2).
    """
    pushes: List[Dict[str, Any]] = []
    teardowns: List[Tuple[int, Optional[str]]] = []
    for lineage_id in lineage_ids:
        head = db.get_lineage_head(lineage_id)
        state = db.get_calendar_state(lineage_id)
        event_id = (state or {}).get("google_event_id")
        if head is None:
            if state:
                teardowns.append((lineage_id, event_id))
            continue
        if not head["removed"]:
            # A session, but not its slot's live one: something was appended over it, so
            # the lineage was superseded and its event belongs to nothing.
            if head.get("superseded"):
                if state:
                    teardowns.append((lineage_id, event_id))
                continue
            if calendar_status(head) != "synced":
                pushes.append(head)
            continue
        # A void that leaves a trace keeps its event, retitled — and gets one when it
        # never had one, or a session written and dropped between two syncs would leave
        # no trace at all (§5.2).
        if leaves_trace(head):
            if calendar_status(head) != "synced":
                pushes.append(head)
            continue
        if state:
            teardowns.append((lineage_id, event_id))
    return pushes, teardowns


def _summary(pushed: int, removed: int) -> str:
    parts = []
    if pushed:
        parts.append(f"{pushed} event(s) pushed")
    if removed:
        parts.append(f"{removed} removed")
    return ", ".join(parts)


def _push(syncer, workout) -> None:
    try:
        syncer.sync_workout(workout)
    except Exception as e:
        fail(f"Google Calendar sync of {workout['title']} failed: {e}")


def _tear_down(db, syncer, lineage_id: int, event_id: Optional[str]) -> None:
    if event_id:
        try:
            syncer.delete_event(event_id)
        except Exception as e:
            fail(f"Google Calendar event delete failed: {e}")
    db.clear_calendar_state(lineage_id)


def mark_adherence_from_results(
    matching_results: List[Dict[str, Any]], today_str: Optional[str] = None
) -> int:
    """Stamps the adherence verdict onto past and same-day planned workout Calendar
    events (title tag + 'Adherence' header). Future events are always skipped.
    Today's event is skipped only when no activity was matched — marking an
    unmatched today's session would falsely read as missed. Workouts without an
    existing Calendar event are skipped, as is any event already carrying this
    exact verdict over unchanged content (matched via `adherence_pushed_signature`), so
    re-running compare over a settled range issues no redundant Calendar writes.
    Best-effort per event: a Calendar failure degrades to a warning. Returns the
    number of events actually (re)marked; the caller owns any summary line."""
    today_str = today_str or _today_str()
    threshold = config.minor_activity_load_threshold
    marked = 0
    for r in matching_results:
        w = r['planned']
        if not w.get('google_event_id'):
            continue
        # Skip future dates always, and anything analyze_adherence flagged pending — a
        # not-yet-done session would falsely read as missed. The date test behind
        # `pending` is owned there; it is repeated here only for hand-built rows.
        if r['date'] > today_str or r.get('pending'):
            continue
        if r['date'] == today_str and not r['completed']:
            continue
        verdict = classify_adherence(w, r['completed'], threshold)
        actual = format_actual(r['completed']) if r['completed'] else None
        adherence = {
            "status": verdict["status"],
            "actual": actual,
            "reasons": verdict["reasons"],
        }
        # Skip a no-op Calendar write: if the event already carries this exact
        # verdict over unchanged content, re-pushing would just re-issue an
        # identical update. Re-running compare over a settled past range is the
        # common case, so this avoids a burst of pointless API writes.
        signature = adherence_signature(w, adherence)
        if w.get('adherence_pushed_signature') == signature:
            continue
        try:
            runtime.calendar_syncer.sync_workout(w, adherence=adherence)
            if w.get('id') is not None:
                runtime.db.mark_workout_adherence_pushed(w['id'], signature)
            marked += 1
        except Exception as e:
            warn(f"could not mark {fmt_date(w['date'])} on Calendar: {e}")
    return marked


def mark_adherence_range(start_date: str, end_date: str) -> int:
    """Computes adherence over [start_date, end_date] and marks strictly-past
    Calendar events with the verdict. No-op (returns 0) when no calendar is
    configured. Reads the shared `analytics.compare.adherence_window` pairing; the
    `data pull` ride-along
    calls this once fresh activity data has landed."""
    if not config.google_calendar_id:
        return 0
    today = _today_str()
    window = adherence_window(runtime.db, start_date, end_date, today)
    return mark_adherence_from_results(window.results, today)
