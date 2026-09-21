"""The only file that talks to the Google Calendar API.

Outbound, `CalendarSyncer` puts a workout's event on the calendar, lists the events it
owns and deletes them; what those events *say* is `event.py`, which this file asks for a
body and then pushes. Inbound, the same class pulls tagged signal events into
`daily_signals` (DESIGN_calendar_signal_ingest.md).

No instance is built here. The constructor reads the service-account credentials file, so
building one at import made every CLI command and the web app need that file even on an
instance with no Calendar configured. `runtime.calendar_syncer` builds it on first use
instead (ARCHITECTURE.md §6).
"""
from contextlib import contextmanager
from datetime import datetime, timedelta, timezone
from typing import Any, Iterator, List, Optional

from google.oauth2 import service_account
from googleapiclient.discovery import build
from googleapiclient.errors import HttpError

from stamind import freshness, runtime
from stamind.clock import fmt_date
from stamind.config import config
from stamind.gcal.event import WORKOUT_EVENT_TAG, event_body, event_day
from stamind.output import Progress, warn
from stamind.types import Workout
from stamind.workout_state import calendar_signature

# Events fetched per Calendar API page during a signal sync (the response is paged
# through with pageToken regardless, so this only tunes round-trips vs payload size).
CALENDAR_SYNC_PAGE_SIZE = 250

# Whether each event write announces itself. Callers that push a whole batch render a
# count and a progress bar instead, and silence the per-event lines with `quiet_events()`.
_event_log: bool = True


@contextmanager
def quiet_events() -> Iterator[None]:
    """Silences the per-event 'Created'/'Deleted' lines; warnings and errors still print."""
    global _event_log
    was, _event_log = _event_log, False
    try:
        yield
    finally:
        _event_log = was


class CalendarSyncer:
    """Synchronizes planned and adapted workouts to Google Calendar as all-day events."""

    def __init__(self) -> None:
        """Initializes Google API calendar service using configured service account."""
        self.scopes: List[str] = ['https://www.googleapis.com/auth/calendar']
        self.creds: service_account.Credentials = (
            service_account.Credentials.from_service_account_file(
                config.service_account_file, scopes=self.scopes
            )
        )
        self.service: Any = build('calendar', 'v3', credentials=self.creds)
        self.calendar_id: Optional[str] = config.google_calendar_id

    def sync_workout(
        self, workout: Workout, adherence: Optional[dict] = None
    ) -> Optional[str]:
        """Syncs a single workout to Google Calendar (creating or updating).

        Args:
            workout: The Workout details to synchronize.
            adherence: Optional backward-looking verdict for a *past* event, passed
                straight through to `event.event_body`.

        Returns:
            The Google Calendar event ID if sync was successful, or None.

        Raises:
            HttpError: If API call fails.
        """
        google_event_id = workout.get('google_event_id')
        body = event_body(workout, adherence)

        # If we have a saved google_event_id, try updating it
        if google_event_id:
            try:
                self.service.events().update(
                    calendarId=self.calendar_id,
                    eventId=google_event_id,
                    body=body
                ).execute()

                # Record the push: store the event handle + the signature of what we
                # just pushed, so the row derives as `synced` until edited again.
                if workout.get('id') is not None:
                    runtime.db.mark_workout_pushed(
                        workout['id'], google_event_id, calendar_signature(workout)
                    )
                return google_event_id
            except HttpError as e:
                if e.resp.status in (404, 410):
                    warn(
                        f"Calendar event {google_event_id} was deleted on Google "
                        f"Calendar. Re-creating a new one..."
                    )
                    # Fall through to insert new event
                else:
                    print(f"Error updating Google Calendar event: {e}")
                    raise e
            except Exception as e:
                print(f"Error updating Google Calendar event: {e}")
                raise e

        # Create a new event
        try:
            created_event = self.service.events().insert(
                calendarId=self.calendar_id,
                body=body
            ).execute()
            new_event_id = created_event.get('id')
            if _event_log:
                print(
                    f"Created new calendar event for {fmt_date(workout['date'])} "
                    f"({workout['sport_type']})."
                )

            # Record the push: store the new event handle + the signature of what we
            # just pushed, so the row derives as `synced` until edited again.
            if workout.get('id') is not None:
                runtime.db.mark_workout_pushed(
                    workout['id'], new_event_id, calendar_signature(workout)
                )
            return str(new_event_id)
        except Exception as e:
            print(f"Error inserting event to Google Calendar: {e}")
            raise e

    def sync_multiple(self, workouts: List[Workout]) -> List[Optional[str]]:
        """Syncs a list of workouts sequentially, under one self-erasing progress bar.

        The bar, and the per-event lines it replaces, are what a workout change already
        gets from the reconcile pass (DESIGN_workout_revisions.md §8). `workout push` is
        the same batch of round-trips, so it reads the same way: updating an existing
        event prints nothing of its own, and without the bar a long push is silent.

        Args:
            workouts: List of Workout objects to sync.

        Returns:
            A list of event IDs synced.
        """
        synced_ids = []
        with quiet_events(), Progress(len(workouts)) as bar:
            for w in workouts:
                synced_ids.append(self.sync_workout(w))
                bar.step()
        return synced_ids

    # ------------------------------------------------------------------
    # Inbound: external daily signals (alcohol, sleep, stress, …)
    # ------------------------------------------------------------------
    def sync_signals(self) -> int:
        """Pulls tagged signal events from the calendar into `daily_signals`.

        Incremental via `syncToken` (edit and delete detection come for free); falls
        back to a full pull of *all* tagged events on first run or when the token has
        expired (HTTP 410). The server-side `privateExtendedProperty` filter applies to
        the full pull only — the API forbids it alongside `syncToken`, so the incremental
        stream carries every changed event and is filtered client-side. Returns the number
        of rows upserted or deleted (DESIGN_calendar_signal_ingest.md §3, §6).
        """
        if not self.calendar_id:
            return 0

        state = runtime.db.get_sync_state(key="calendar_signals")
        use_token: Optional[str] = state.get("sync_token") if state else None

        changed = 0
        page_token: Optional[str] = None
        next_sync_token: Optional[str] = None
        while True:
            params: dict = {
                'calendarId': self.calendar_id,
                'showDeleted': True,
                'singleEvents': True,
                'maxResults': CALENDAR_SYNC_PAGE_SIZE,
            }
            # syncToken and the initial-sync params are mutually exclusive beyond
            # pageToken; reuse the *same* base params so the token stays valid.
            if use_token:
                params['syncToken'] = use_token
            else:
                params['privateExtendedProperty'] = f"source={config.calendar_signal_tag}"

            if page_token:
                params['pageToken'] = page_token
            try:
                resp = self.service.events().list(**params).execute()
            except HttpError as e:
                if e.resp.status == 410 and use_token:
                    # Expired token: discard it and restart with a full pull.
                    use_token = None
                    page_token = None
                    changed = 0
                    continue
                raise
            for event in resp.get('items', []):
                changed += self._ingest_signal_event(event)
            page_token = resp.get('nextPageToken')
            if not page_token:
                next_sync_token = resp.get('nextSyncToken')
                break

        runtime.db.set_sync_state(
            through_date=None,
            last_pull_utc=datetime.now(timezone.utc).isoformat(),
            key="calendar_signals",
            sync_token=next_sync_token,
        )
        return changed

    def _ingest_signal_event(self, event: dict) -> int:
        """Reconciles a single signal event into `daily_signals`. A cancelled event
        deletes its row; otherwise the row is upserted by event id. Returns 1 if the DB
        changed, else 0."""
        event_id = event.get('id')
        if not event_id:
            return 0
        if event.get('status') == 'cancelled':
            # Cancelled events arrive stripped of extendedProperties, so the tag guard
            # below can't run: a deleted row is the proof it was ours (§6).
            return 1 if runtime.db.delete_daily_signal_by_event(event_id) else 0

        private = (event.get('extendedProperties', {}) or {}).get('private', {}) or {}
        # On the incremental path this is the *only* filter (no server-side one is
        # allowed with a syncToken) — skip anything not actually ours (§3).
        if private.get('source') != config.calendar_signal_tag:
            return 0

        date = event_day(event)
        if not date:
            return 0

        runtime.db.upsert_daily_signal_by_event(
            google_event_id=event_id,
            date=date,
            metric=private.get('metric') or 'signal',
            value=self._parse_float(private.get('value')),
            text=self._signal_text(event),
            updated=event.get('updated'),
        )
        return 1

    @staticmethod
    def _parse_float(raw: Any) -> Optional[float]:
        """Best-effort parse of the optional numeric `value` tag; None when absent/bad."""
        if raw is None:
            return None
        try:
            return float(raw)
        except (TypeError, ValueError):
            return None

    @staticmethod
    def _signal_text(event: dict) -> Optional[str]:
        """The human blurb handed to the coach: summary then description, trimmed."""
        parts = [event.get('summary'), event.get('description')]
        text = "\n".join(p.strip() for p in parts if p and p.strip())
        return text or None

    def add_signal_event(
        self, date: str, metric: str, value: Optional[float],
        text: Optional[str], existing_event_id: Optional[str] = None
    ) -> Optional[str]:
        """Authors (or updates) a tagged signal event for a single day.

        Stamind becomes the first-party producer of the same `source=<signal_tag>`
        events the external syncer writes (DESIGN_signal_authoring.md). All-day, end
        exclusive = start + 1 day, matching workouts. When `existing_event_id` is given
        the event is updated in place (the idempotent upsert-by-(date,metric) path);
        otherwise a new one is inserted. Returns the event id, or None if no calendar
        is configured.
        """
        if not self.calendar_id:
            return None

        end_date_str = (
            datetime.strptime(date, "%Y-%m-%d").date() + timedelta(days=1)
        ).strftime("%Y-%m-%d")
        private = {'source': config.calendar_signal_tag, 'metric': metric}
        if value is not None:
            private['value'] = str(value)
        body = {
            'summary': text or metric,
            'start': {'date': date},
            'end': {'date': end_date_str},
            'extendedProperties': {'private': private},
        }

        if existing_event_id:
            updated = self.service.events().update(
                calendarId=self.calendar_id, eventId=existing_event_id, body=body
            ).execute()
            return updated.get('id')
        created = self.service.events().insert(
            calendarId=self.calendar_id, body=body
        ).execute()
        return created.get('id')

    def list_workout_events(self) -> List[dict]:
        """Every workout event on the calendar, found by tag rather than by stored id.

        The tag is the only ownership handle that survives the database: a fresh DB
        (or a wipe that skipped the calendar) orphans events no row points at any
        more, so `workout prune-calendar` has to sweep from the calendar side.
        """
        if not self.calendar_id:
            return []

        events: List[dict] = []
        page_token: Optional[str] = None
        while True:
            params: dict = {
                'calendarId': self.calendar_id,
                'singleEvents': True,
                'maxResults': CALENDAR_SYNC_PAGE_SIZE,
                'privateExtendedProperty': f"source={WORKOUT_EVENT_TAG}",
            }
            if page_token:
                params['pageToken'] = page_token
            resp = self.service.events().list(**params).execute()
            events.extend(resp.get('items', []))
            page_token = resp.get('nextPageToken')
            if not page_token:
                return events

    def delete_event(self, google_event_id: str) -> bool:
        """Deletes an event from Google Calendar by id (source-agnostic).

        Args:
            google_event_id: The event ID to delete.

        Returns:
            True if the event was deleted; False if the API refused (best-effort —
            a failure is warned about, never raised, so teardown paths continue).
        """
        try:
            self.service.events().delete(
                calendarId=self.calendar_id,
                eventId=google_event_id
            ).execute()
            if _event_log:
                print(f"Deleted Google Calendar event {google_event_id}.")
            return True
        except Exception as e:
            warn(f"failed to delete Google Calendar event {google_event_id}: {e}")
            return False


# Per-process memo: a single CLI command syncs signals at most once.
_signals_synced: bool = False


def sync_calendar_signals(force: bool = False) -> None:
    """Refreshes daily signals from the calendar, gating/throttling the actual sync.

    Rides along with `data pull` (force=True) and the auto-ensure-before-read path
    (force=False, where it runs at most once per process and skips entirely while the
    last sync is still fresh). Best-effort: no calendar configured is a silent no-op,
    and any Calendar error is swallowed with a warning so a data read never stops on it
    (DESIGN_calendar_signal_ingest.md §6).
    """
    global _signals_synced
    if not config.google_calendar_id:
        return
    if not force:
        if _signals_synced:
            return
        # Skip while a recent sync still covers the freshness window — the same window
        # the Garmin pull uses (stamind/freshness.py).
        age = freshness.last_pull_age(
            runtime.db.get_sync_state(key="calendar_signals")
        )
        if age is not None and age <= timedelta(minutes=config.data_refresh_minutes):
            freshness.fresh_notice(
                "Calendar signals", f"last sync {freshness.age_minutes(age)}m ago"
            )
            _signals_synced = True
            return
    try:
        runtime.calendar_syncer.sync_signals()
        _signals_synced = True
    except Exception as e:
        warn(f"calendar signal sync skipped: {e}")
