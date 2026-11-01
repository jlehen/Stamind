"""The Garmin check and the RPE reminder (ARCHITECTURE.md §15, "Questions soon after a session")."""
import datetime as dt
import os
import unittest
from unittest.mock import MagicMock, patch

from tests import test_db_path
from tests.helpers import clear_all_tables, pin_clock, rebind_test_db, restore_db_handles, run_cli

TEST_DB_PATH = test_db_path("test_garmin_check.db")

from stamind.db import Database
import stamind_cli  # noqa: F401 — the CLI binds its handles at import, before the rebind

from stamind import rpe_reminder, runtime
from stamind.analytics import load as load_math
from stamind.chat import scheduler
from stamind.config import config

TODAY = "2026-09-16"


def tearDownModule():
    try:
        os.remove(TEST_DB_PATH)
    except OSError:
        pass


def _save(db, activity_id, minutes, rpe=None, date=TODAY, covered_sec=60):
    zones = {f"zone{i}_sec": 0 for i in range(1, 6)}
    zones["zone1_sec"] = covered_sec
    power = {f"power_zone{i}_sec": None for i in range(1, 8)}
    db.save_completed_activity(
        activity_id=activity_id, date=date, start_time=f"{date} 18:00:00",
        activity_name="Yoga", activity_type="yoga", duration_sec=minutes * 60.0,
        distance_km=0.0, elevation_gain_m=0.0, avg_hr=80, max_hr=90, rpe=rpe, tss=0.3,
        bike_avg_watts=None, **zones, **power,
    )


class TheShortActivityTest(unittest.TestCase):
    def _warning(self, minutes):
        hr = {f"zone{i}_sec": 0 for i in range(1, 6)}
        hr["zone1_sec"] = 30
        power = {f"power_zone{i}_sec": None for i in range(1, 8)}
        return load_math.compute_load(power, hr, None, minutes * 60.0)

    def test_low_coverage_is_only_complained_about_from_the_minimum_length(self):
        with patch.dict(config.data, {"garmin": {"min_activity_minutes": 15}}):
            load, method, warning = self._warning(14)
            self.assertEqual(method, "hr_sparse")
            self.assertIsNone(warning)
            self.assertIsNotNone(self._warning(15)[2])

    def test_no_data_at_all_follows_the_same_length(self):
        power = {f"power_zone{i}_sec": None for i in range(1, 8)}
        hr = {f"zone{i}_sec": 0 for i in range(1, 6)}
        with patch.dict(config.data, {"garmin": {"min_activity_minutes": 15}}):
            self.assertIsNone(load_math.compute_load(power, hr, None, 600.0)[2])
            self.assertIsNotNone(load_math.compute_load(power, hr, None, 1800.0)[2])


class PollDueTest(unittest.TestCase):
    def _due(self, hhmm, last=None, every=15):
        hour, minute = hhmm.split(":")
        now = dt.datetime(2026, 9, 16, int(hour), int(minute))
        return scheduler.garmin_poll_due(now, last, every, "08:00", "21:00")

    def test_only_between_the_morning_and_the_evening_time(self):
        self.assertFalse(self._due("07:59"))
        self.assertTrue(self._due("08:00"))
        self.assertTrue(self._due("20:59"))
        self.assertFalse(self._due("21:00"))

    def test_every_so_many_minutes(self):
        last = dt.datetime(2026, 9, 16, 10, 0).isoformat()
        self.assertFalse(self._due("10:14", last))
        self.assertTrue(self._due("10:15", last))
        self.assertTrue(self._due("10:05", last, every=5))

    def test_zero_turns_it_off(self):
        self.assertFalse(self._due("10:00", every=0))


class _Case(unittest.TestCase):
    def setUp(self):
        restore_db_handles(self)
        if os.path.exists(TEST_DB_PATH):
            os.remove(TEST_DB_PATH)
        self.db = Database(db_path=TEST_DB_PATH)
        rebind_test_db(self.db)
        clear_all_tables(self.db)
        pin_clock(self, TODAY)
        self.addCleanup(patch.stopall)
        self.client = MagicMock()
        patch.object(runtime.garmin, "connect", return_value=self.client).start()
        self.pull = patch.object(runtime.garmin, "pull", return_value="pulled").start()
        patch.dict(config.data, {"garmin": {"min_activity_minutes": 15}}).start()
        patch.object(type(config), "garmin_email", "a").start()
        patch.object(type(config), "garmin_password", "b").start()


class TheCheckTest(_Case):
    def _listed(self, *activities):
        self.client.get_activities.return_value = [
            {"activityId": activity_id, "duration": minutes * 60.0}
            for activity_id, minutes in activities
        ]

    def test_nothing_new_pulls_nothing(self):
        _save(self.db, "1", 45)
        self._listed(("1", 45))
        run_cli(["bot", "garmin-check"])
        self.pull.assert_not_called()

    def test_a_warm_up_pulls_nothing(self):
        """Tuesday 18:10, a 10-minute warm-up is uploaded and the run is still going."""
        self._listed(("1", 10))
        run_cli(["bot", "garmin-check"])
        self.pull.assert_not_called()

    def test_a_new_session_pulls_only_its_activities_and_keeps_the_last_pull_time(self):
        self._listed(("1", 45))
        code, _, _ = run_cli(["bot", "garmin-check"])
        self.assertEqual(code, 0)
        self.pull.assert_called_once_with(TODAY, TODAY, metrics=False, advance_watermark=False)

    def test_a_new_session_gets_its_reminder_in_the_line(self):
        self._listed(("1", 45))
        self.pull.side_effect = lambda *a, **k: _save(self.db, "1", 45) or "pulled"
        run_cli(["bot", "garmin-check"])
        [item] = self.db.waiting_queue_items()
        self.assertEqual((item["kind"], item["subject"]), ("rpe_reminder", "1"))
        self.assertIn("45-minute Yoga", item["payload"]["text"])
        self.assertIn("in Garmin", item["payload"]["text"])


class TheReminderTest(_Case):
    """Only what needs an RPE, once, and it goes stale when the RPE arrives."""

    def _kinds(self):
        return [item["subject"] for item in self.db.waiting_queue_items()]

    def test_who_gets_one(self):
        _save(self.db, "short", 10)
        _save(self.db, "has_rpe", 45, rpe=5)
        _save(self.db, "covered", 45, covered_sec=2000)
        _save(self.db, "log:" + TODAY, 45)
        _save(self.db, "old", 45, date="2026-09-14")
        _save(self.db, "yesterday", 45, date="2026-09-15")
        _save(self.db, "today", 45)
        rpe_reminder.queue_reminders(TODAY)
        rpe_reminder.queue_reminders(TODAY)
        self.assertEqual(sorted(self._kinds()), ["today", "yesterday"])

    def test_it_goes_stale_once_the_rpe_is_in(self):
        _save(self.db, "1", 45)
        rpe_reminder.queue_reminders(TODAY)
        [item] = self.db.waiting_queue_items()
        self.assertFalse(rpe_reminder.RPE_REMINDER_KIND.is_stale(item))
        _save(self.db, "1", 45, rpe=6)
        self.assertTrue(rpe_reminder.RPE_REMINDER_KIND.is_stale(item))


if __name__ == "__main__":
    unittest.main()
