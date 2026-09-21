"""The three endpoints behind `static/workouts.js`, which fills the Workouts tab: the
session listing and what became of each session, the compare view, and the change log
behind `workout batches`.
"""
import os
import unittest
import unittest.mock
from datetime import date, timedelta

from tests.helpers import clear_all_tables, rebind_test_db, save_workout

from tests import test_db_path

TEST_DB_PATH = test_db_path("test_stamind_web_workouts.db")

from stamind.db import Database

import stamind_web

# An isolated database for the web app's singleton; test_web.py says why.
test_db = Database(db_path=TEST_DB_PATH)
rebind_test_db(test_db)


def _save_activity(db, activity_id, date, activity_type, duration_sec, tss):
    db.save_completed_activity(
        activity_id=activity_id,
        date=date,
        start_time=f"{date} 08:00:00",
        activity_name=f"{activity_type} session",
        activity_type=activity_type,
        duration_sec=duration_sec,
        distance_km=10.0,
        elevation_gain_m=0.0,
        avg_hr=140,
        max_hr=160,
        rpe=None,
        tss=tss,
    )


class TestWorkoutListingCarriesTheVerdict(unittest.TestCase):
    """GET /api/workouts — the dashboard's Workouts tab shows what became of a past
    session, from the CLI's own `adherence_verdicts` rather than a second grader."""

    @classmethod
    def setUpClass(cls):
        if os.path.exists(TEST_DB_PATH):
            os.remove(TEST_DB_PATH)
        global test_db
        test_db = Database(db_path=TEST_DB_PATH)
        rebind_test_db(test_db)
        cls.client = stamind_web.app.test_client()

    @classmethod
    def tearDownClass(cls):
        if os.path.exists(TEST_DB_PATH):
            try:
                os.remove(TEST_DB_PATH)
            except OSError:
                pass

    def setUp(self):
        clear_all_tables(test_db)

    def _rows(self, start, end):
        res = self.client.get(f"/api/workouts?start_date={start}&end_date={end}")
        self.assertEqual(res.status_code, 200)
        return {row["title"]: row for row in res.get_json()}

    def test_a_past_row_carries_its_verdict_and_its_word(self):
        save_workout(test_db,
            date="2026-06-10", sport_type="running", title="Tempo Run",
            description="40min tempo", duration_minutes=40, tss=50,
        )
        save_workout(test_db,
            date="2026-06-11", sport_type="running", title="Long Run",
            description="90min easy", duration_minutes=90, tss=80,
        )
        _save_activity(test_db, "w1", "2026-06-10", "running", 40 * 60, 50.0)

        rows = self._rows("2026-06-10", "2026-06-11")
        self.assertEqual(rows["Tempo Run"]["adherence"]["status"], "done")
        self.assertEqual(rows["Tempo Run"]["adherence"]["label"], "Done")
        self.assertEqual(rows["Long Run"]["adherence"]["status"], "missed")
        # The effort it was graded on rides along, for the row's detail.
        self.assertIsNotNone(rows["Tempo Run"]["adherence"]["completed"])

    def test_a_row_still_ahead_of_us_carries_none(self):
        ahead = (date.today() + timedelta(days=3)).strftime("%Y-%m-%d")
        save_workout(test_db,
            date=ahead, sport_type="running", title="Future Run",
            description="30min", duration_minutes=30, tss=25,
        )
        rows = self._rows(ahead, ahead)
        self.assertIsNone(rows["Future Run"]["adherence"])


class TestCompareEndpoint(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        if os.path.exists(TEST_DB_PATH):
            os.remove(TEST_DB_PATH)
        global test_db
        test_db = Database(db_path=TEST_DB_PATH)
        rebind_test_db(test_db)
        cls.client = stamind_web.app.test_client()

    @classmethod
    def tearDownClass(cls):
        if os.path.exists(TEST_DB_PATH):
            try:
                os.remove(TEST_DB_PATH)
            except OSError:
                pass

    def setUp(self):
        clear_all_tables(test_db)

    def _get(self, start, end):
        return self.client.get(
            f"/api/workouts/compare?start_date={start}&end_date={end}"
        )

    def test_matched_session_no_discrepancy(self):
        # Planned run with a closely-matching completed run -> matched, no discrepancy.
        save_workout(test_db,
            date="2026-06-10", sport_type="running", title="Tempo Run",
            description="40min tempo", duration_minutes=40, tss=50,
        )
        _save_activity(test_db, "a1", "2026-06-10", "running", 40 * 60, 50.0)

        res = self._get("2026-06-10", "2026-06-10")
        self.assertEqual(res.status_code, 200)
        data = res.get_json()
        self.assertEqual(len(data["days"]), 1)
        day = data["days"][0]
        self.assertEqual(day["date"], "2026-06-10")
        self.assertEqual(len(day["results"]), 1)
        self.assertIsNotNone(day["results"][0]["completed"])
        self.assertEqual(day["unplanned"], [])
        self.assertEqual(data["discrepancies"], [])

    def test_missed_session_is_discrepancy(self):
        # Planned run with no completed activity -> complete miss.
        save_workout(test_db,
            date="2026-06-10", sport_type="running", title="Long Run",
            description="90min easy", duration_minutes=90, tss=80,
        )

        res = self._get("2026-06-10", "2026-06-10")
        data = res.get_json()
        self.assertEqual(res.status_code, 200)
        self.assertEqual(len(data["days"]), 1)
        self.assertIsNone(data["days"][0]["results"][0]["completed"])
        # Structured, so the dashboard filters on `kind` rather than parsing English.
        self.assertTrue(
            any(d["kind"] == "missed" for d in data["discrepancies"]),
            data["discrepancies"],
        )
        missed = next(d for d in data["discrepancies"] if d["kind"] == "missed")
        self.assertEqual(missed["planned_title"], "Long Run")
        self.assertIn("Complete Miss", missed["text"])

    def test_unplanned_activity_is_flagged(self):
        # An activity on a day with no planned workout, inside a planned mesocycle
        # (mesocycle), surfaces as an unplanned deviation.
        obj_id = test_db.add_objective(
            title="Race", target_date="2026-09-01", sport_type="running",
        )
        test_db.save_macrocycle(
            objective_id=obj_id, strategy="s", goals_hash="g",
            constraints_hash="l", config_hash="c",
            mesocycles=[{
                "name": "Base", "start_date": "2026-06-01",
                "end_date": "2026-06-30", "focus": "aerobic base",
            }],
        )

        _save_activity(test_db, "a2", "2026-06-10", "running", 60 * 60, 70.0)

        res = self._get("2026-06-10", "2026-06-10")
        data = res.get_json()
        self.assertEqual(res.status_code, 200)
        self.assertEqual(len(data["days"]), 1)
        unplanned = data["days"][0]["unplanned"]
        self.assertEqual(len(unplanned), 1)
        self.assertEqual(unplanned[0]["kind"], "unplanned")

    def test_rest_day_verdict_matches_the_shared_classifier(self):
        """The endpoint used to re-derive rest/violation inline, skipping
        canonical_sport() and the load threshold — so a "Rest" workout read as a normal
        sport and a light stroll read as a violation on the dashboard only."""
        save_workout(test_db,
            date="2026-06-11", sport_type="Rest", title="Rest Day",
            description="full rest", duration_minutes=0, tss=0,
        )
        _save_activity(test_db, "a3", "2026-06-11", "running", 55 * 60, 70.0)

        result = self._get("2026-06-11", "2026-06-11").get_json()["days"][0]["results"][0]
        self.assertTrue(result["is_rest"])
        self.assertTrue(result["rest_violation"])
        self.assertEqual(result["status"], "rest_violation")

    def test_light_activity_on_a_rest_day_is_not_a_violation(self):
        save_workout(test_db,
            date="2026-06-12", sport_type="rest", title="Rest Day",
            description="full rest", duration_minutes=0, tss=0,
        )
        _save_activity(test_db, "a4", "2026-06-12", "walking", 12 * 60, 5.0)

        result = self._get("2026-06-12", "2026-06-12").get_json()["days"][0]["results"][0]
        self.assertTrue(result["is_rest"])
        self.assertFalse(result["rest_violation"])
        self.assertEqual(result["status"], "rest_ok")

    def test_end_date_capped_and_default_range(self):
        # No params -> defaults to a 14-day lookback ending today; valid empty result.
        res = self.client.get("/api/workouts/compare")
        self.assertEqual(res.status_code, 200)
        data = res.get_json()
        self.assertIn("filters", data)
        self.assertIn("days", data)


class TestWorkoutBatchesEndpoint(unittest.TestCase):
    """GET /api/workouts/batches — the web face of `workout batches`
    (see DESIGN_plan_rollback.md §9)."""

    @classmethod
    def setUpClass(cls):
        if os.path.exists(TEST_DB_PATH):
            os.remove(TEST_DB_PATH)
        global test_db
        test_db = Database(db_path=TEST_DB_PATH)
        rebind_test_db(test_db)
        cls.client = stamind_web.app.test_client()

    @classmethod
    def tearDownClass(cls):
        if os.path.exists(TEST_DB_PATH):
            try:
                os.remove(TEST_DB_PATH)
            except OSError:
                pass

    def setUp(self):
        clear_all_tables(test_db)

    def test_batches_empty_when_nothing_written(self):
        res = self.client.get("/api/workouts/batches")
        self.assertEqual(res.status_code, 200)
        self.assertEqual(res.get_json()["batches"], [])

    def test_batches_reports_kind_span_and_upcoming_count(self):
        today = date.today()
        past = (today - timedelta(days=3)).strftime("%Y-%m-%d")
        future = (today + timedelta(days=3)).strftime("%Y-%m-%d")
        with test_db.workout_change(kind="generate", summary="v1") as change:
            for d in (past, future):
                change.append(date=d, sport_type="running", title=f"Run {d}",
                              description="x")

        res = self.client.get("/api/workouts/batches")
        self.assertEqual(res.status_code, 200)
        batches = res.get_json()["batches"]
        self.assertEqual(len(batches), 1)
        self.assertEqual(batches[0]["kind"], "generate")
        self.assertEqual(batches[0]["workouts"], 2)
        self.assertFalse(batches[0]["held"])
        # Only the future revision is still in reach of an undo — the floor spares a day
        # already trained (DESIGN_workout_revisions.md §10).
        self.assertEqual(batches[0]["restorable"], 1)
        self.assertEqual(batches[0]["first_date"], past)
        self.assertEqual(batches[0]["last_date"], future)


if __name__ == "__main__":
    unittest.main()
