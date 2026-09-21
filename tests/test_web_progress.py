"""The timeline behind `static/progress.js`, which fills the Progress tab: the PNG the
page draws, and the payload the shared builder hands it.
"""
import os
import unittest
import unittest.mock
from datetime import date, timedelta

from tests.helpers import clear_all_tables, rebind_test_db, save_workout


def _goal_ahead(days: int = 100) -> str:
    """A goal date comfortably in the future, on the app's clock.

    These goals are scaffolding — nothing asserts the date — but a plan is only active
    while its goal is ahead, so a literal expired the tests the day it passed.
    """
    from trainmate.clock import today_date
    return (today_date() + timedelta(days=days)).isoformat()

from tests import test_db_path

TEST_DB_PATH = test_db_path("test_trainmate_web_progress.db")

from trainmate.db import Database
from trainmate.analytics import timeline

import trainmate_web

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


class TestTimelinePngEndpoint(unittest.TestCase):
    """GET /api/timeline.png (DESIGN_progress_timeline.md §6). Pure reader — no
    Garmin/LLM mocks needed, which is itself part of the assertion. Pixels stay
    untested (visual output); only status/content-type/framing and the assembled
    payload are asserted."""

    @classmethod
    def setUpClass(cls):
        if os.path.exists(TEST_DB_PATH):
            os.remove(TEST_DB_PATH)
        global test_db
        test_db = Database(db_path=TEST_DB_PATH)
        rebind_test_db(test_db)
        cls.client = trainmate_web.app.test_client()

    @classmethod
    def tearDownClass(cls):
        if os.path.exists(TEST_DB_PATH):
            try:
                os.remove(TEST_DB_PATH)
            except OSError:
                pass

    def setUp(self):
        clear_all_tables(test_db)

    def test_returns_png_bytes(self):
        _save_activity(test_db, "a1", "2026-06-10", "running", 3600, 40.0)
        res = self.client.get("/api/timeline.png")
        self.assertEqual(res.status_code, 200)
        self.assertEqual(res.mimetype, "image/png")
        self.assertTrue(res.data.startswith(b"\x89PNG\r\n\x1a\n"))

    def test_empty_db_still_renders_a_png(self):
        res = self.client.get("/api/timeline.png")
        self.assertEqual(res.status_code, 200)
        self.assertTrue(res.data.startswith(b"\x89PNG"))

    def test_weeks_validation(self):
        _save_activity(test_db, "a1", "2026-06-10", "running", 3600, 40.0)
        self.assertEqual(self.client.get("/api/timeline.png?weeks=0").status_code, 400)
        self.assertEqual(self.client.get("/api/timeline.png?weeks=all").status_code, 200)
        self.assertEqual(self.client.get("/api/timeline.png?weeks=x").status_code, 400)

    def test_matplotlib_absent_returns_503_with_hint(self):
        import builtins
        real_import = builtins.__import__

        def fake_import(name, *args, **kwargs):
            if name == "matplotlib" or name.startswith("matplotlib."):
                raise ImportError("no matplotlib")
            return real_import(name, *args, **kwargs)

        _save_activity(test_db, "a1", "2026-06-10", "running", 3600, 40.0)
        with unittest.mock.patch("builtins.__import__", side_effect=fake_import):
            res = self.client.get("/api/timeline.png")
        self.assertEqual(res.status_code, 503)
        self.assertIn("matplotlib", res.get_data(as_text=True))


class TestTimelinePayload(unittest.TestCase):
    """The assembled payload behind the PNG (via the shared builder), where the pixel
    output can't assert the numbers."""

    @classmethod
    def setUpClass(cls):
        global test_db
        test_db = Database(db_path=TEST_DB_PATH)
        rebind_test_db(test_db)

    @classmethod
    def tearDownClass(cls):
        if os.path.exists(TEST_DB_PATH):
            try:
                os.remove(TEST_DB_PATH)
            except OSError:
                pass

    def setUp(self):
        clear_all_tables(test_db)

    def _payload(self):
        from trainmate import timeline_rows
        return timeline_rows.build_timeline_payload(test_db)

    def test_no_activity_at_all_warns_and_empty_days(self):
        data = self._payload()
        self.assertEqual(data["days"], [])
        self.assertIsNone(data["plan_end"])
        self.assertIn("no_history", {w["code"] for w in data["warnings"]})

    def test_plan_end_is_last_non_removed_workout(self):
        _save_activity(test_db, "a1", "2026-06-10", "running", 3600, 40.0)
        save_workout(test_db, date="2026-07-10", sport_type="running", title="Run",
                             description="d", duration_minutes=60, tss=50)
        later = save_workout(test_db, date="2026-07-20", sport_type="running",
                                     title="Run late", description="d",
                                     duration_minutes=60, tss=50)
        with test_db.workout_change(kind="tweak") as change:
            change.void(date="2026-07-20", sport_type="running", reason="cancelled")
        self.assertEqual(self._payload()["plan_end"], "2026-07-10")

    def test_meso_bands_layers_inferred_and_plan(self):
        oid = test_db.add_objective(title="Race", target_date=_goal_ahead(),
                                    sport_type="running")
        test_db.save_macrocycle(
            objective_id=oid, strategy="s", goals_hash="g", constraints_hash="l",
            mesocycles=[{"name": "Build", "start_date": "2026-07-01",
                         "end_date": "2026-07-31", "focus": "build"}],
        )
        test_db.save_analysis_cache(
            horizon="long", fingerprint="fp", window_start="2026-05-01",
            window_end="2026-06-30",
            reconstruction={"inferred_mesocycles": [{
                "name": "Base", "start_date": "2026-05-01", "end_date": "2026-05-31",
                "focus": "base"}]},
        )
        _save_activity(test_db, "a1", "2026-05-05", "running", 3600, 30.0)
        sources = [b["source"] for b in self._payload()["meso_bands"]]
        self.assertIn("inferred", sources)
        self.assertIn("plan", sources)

    def test_clip_payload_keeps_full_history_seeding(self):
        for i in range(60):
            d = (date(2026, 5, 1) + timedelta(days=i)).isoformat()
            _save_activity(test_db, f"a{i}", d, "running", 3600, 50.0)
        payload = self._payload()
        full = timeline.clip_payload(payload, "2026-05-01", "2026-06-29")
        narrow = timeline.clip_payload(payload, "2026-06-25", "2026-06-29")
        full_point = next(d for d in full["days"] if d["date"] == "2026-06-25")
        narrow_point = next(d for d in narrow["days"] if d["date"] == "2026-06-25")
        self.assertAlmostEqual(full_point["ctl"], narrow_point["ctl"])
        self.assertEqual(len(narrow["days"]), 5)


if __name__ == "__main__":
    unittest.main()
