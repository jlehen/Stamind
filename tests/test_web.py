"""The rule the whole dashboard obeys, and the read views nothing else owns.

The read-only rule is about the whole app rather than about one panel, and three tests do
not earn a file of their own, so it sits here beside the views the CLI demotion brought
over: the benchmark logbook, the signal vocabulary and one metric's history, the active
model, `plan show` and the zone tables. Those five are drawn by three different dashboard
scripts, which is why they are not one of the files below.

The three that do follow a script are `test_web_workouts.py` (`static/workouts.js`),
`test_web_plan.py` (`static/plan.js`) and `test_web_progress.py` (`static/progress.js`).
"""
import os
import unittest
import unittest.mock
from datetime import date, timedelta

from tests.helpers import clear_all_tables, rebind_test_db

from tests import test_db_path

TEST_DB_PATH = test_db_path("test_stamind_web.db")

from stamind.db import Database

import stamind_web

# Point the web app's db singleton at an isolated test database. The handlers
# reference the module-level `stamind_web.db`, so patching it here is enough
# for the read-only endpoints exercised below (the web app never pulls from
# Garmin — it is a pure reader, ARCHITECTURE.md §8).
test_db = Database(db_path=TEST_DB_PATH)
rebind_test_db(test_db)


class TestReadOnly(unittest.TestCase):
    """The dashboard reads and nothing else (ARCHITECTURE.md §8). These tests are the
    enforcement: a route added with a mutating verb fails here, which is the whole point
    of demoting the surface rather than merely documenting it as read-only."""

    @classmethod
    def setUpClass(cls):
        cls.client = stamind_web.app.test_client()

    def test_every_route_is_get_only(self):
        for rule in stamind_web.app.url_map.iter_rules():
            verbs = rule.methods - {"HEAD", "OPTIONS"}
            self.assertEqual(
                verbs, {"GET"},
                f"{rule} exposes {sorted(verbs)}; the dashboard must stay read-only",
            )

    def test_mutating_verbs_are_refused(self):
        for verb, path in (
            ("post", "/api/objectives"),
            ("post", "/api/workouts"),
            ("put", "/api/objectives/1"),
            ("delete", "/api/objectives/1"),
            ("post", "/api/plan"),
            ("post", "/api/adapt"),
        ):
            res = getattr(self.client, verb)(path)
            self.assertEqual(res.status_code, 405, f"{verb.upper()} {path}")
            self.assertIn("read-only", res.get_json()["error"])

    def test_only_a_failed_request_is_journalled_and_it_carries_no_run(self):
        """A read-only GET neither changes anything nor costs anything, so it is not a
        run — the web app opens none, which is also what keeps the journal's
        module-level run stack away from Flask's threading. Only failures are recorded,
        and with no run id at all (DESIGN_logging.md §13)."""
        from werkzeug.exceptions import NotFound
        from stamind import journal

        with open(stamind_web.__file__) as handle:
            self.assertNotIn("start_run", handle.read())

        recorded = []
        with unittest.mock.patch.object(
            journal, "record", side_effect=lambda *a, **k: recorded.append((a, k))
        ):
            with stamind_web.app.test_request_context("/api/workouts"):
                # An HTTPException is Flask's own to render, and not an event.
                not_found = NotFound()
                self.assertIs(stamind_web._journal_failure(not_found), not_found)
                self.assertEqual(recorded, [])
                with self.assertRaises(RuntimeError):        # re-raised, not swallowed
                    stamind_web._journal_failure(RuntimeError("boom"))
        (args, kwargs), = recorded
        self.assertEqual(args[0], "internal")
        self.assertEqual(kwargs["lvl"], "error")
        self.assertIn("boom", args[1])
        self.assertEqual(kwargs["path"], "/api/workouts")


class TestNewReadEndpoints(unittest.TestCase):
    """The CLI-only features the demotion brought over as views: the benchmark logbook,
    the daily-signal vocabulary, the model menu, plan show and the zone tables."""

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

    def test_benchmarks_carry_formatted_value_and_directional_delta(self):
        test_db.add_benchmark_result(
            date="2026-05-01", sport_type="cycling", anchor_kind="ftp",
            value=240.0, unit="W", source="test",
        )
        test_db.add_benchmark_result(
            date="2026-06-01", sport_type="cycling", anchor_kind="ftp",
            value=250.0, unit="W", source="test",
        )
        data = self.client.get("/api/benchmarks").get_json()
        # Newest first, and the newest compares against the older row of the same kind.
        self.assertEqual([r["value"] for r in data["results"]], [250.0, 240.0])
        newest = data["results"][0]
        self.assertTrue(newest["improvement"])
        self.assertTrue(newest["delta"].startswith("+"))
        self.assertIsNone(data["results"][1]["delta"])
        self.assertEqual(
            [t["anchor_kind"] for t in data["thresholds"]], ["ftp"]
        )
        self.assertEqual(data["thresholds"][0]["value"], 250.0)

    def test_benchmark_pace_delta_reads_positive_when_faster(self):
        # A lower threshold pace is an improvement; the sign must reflect that (§3.2).
        test_db.add_benchmark_result(
            date="2026-05-01", sport_type="running", anchor_kind="threshold_pace",
            value=300.0, unit="min/km", source="test",
        )
        test_db.add_benchmark_result(
            date="2026-06-01", sport_type="running", anchor_kind="threshold_pace",
            value=285.0, unit="min/km", source="test",
        )
        newest = self.client.get("/api/benchmarks").get_json()["results"][0]
        self.assertTrue(newest["improvement"])
        self.assertTrue(newest["delta"].startswith("+"))

    def test_benchmarks_filter_by_sport(self):
        test_db.add_benchmark_result(
            date="2026-05-01", sport_type="cycling", anchor_kind="ftp",
            value=240.0, unit="W", source="test",
        )
        test_db.add_benchmark_result(
            date="2026-05-02", sport_type="running", anchor_kind="threshold_pace",
            value=300.0, unit="min/km", source="test",
        )
        data = self.client.get("/api/benchmarks?sport=cycling").get_json()
        self.assertEqual([r["sport_type"] for r in data["results"]], ["cycling"])

    def test_signal_metrics_vocabulary(self):
        for d, val in (("2026-06-01", 2), ("2026-06-03", 1)):
            test_db.upsert_daily_signal_by_event(
                google_event_id=f"e{d}", date=d, metric="alcohol",
                value=val, text="drinks",
            )
        data = self.client.get("/api/daily-signals/metrics").get_json()
        self.assertEqual(len(data["metrics"]), 1)
        row = data["metrics"][0]
        self.assertEqual(row["metric"], "alcohol")
        self.assertEqual(row["count"], 2)
        self.assertEqual(row["first_date"], "2026-06-01")
        self.assertEqual(row["last_date"], "2026-06-03")

    def test_daily_signals_filters_by_metric(self):
        test_db.upsert_daily_signal_by_event(
            google_event_id="e1", date="2026-06-01", metric="alcohol", value=2, text="")
        test_db.upsert_daily_signal_by_event(
            google_event_id="e2", date="2026-06-01", metric="stress", value=7, text="")
        rows = self.client.get("/api/daily-signals?metric=stress").get_json()
        self.assertEqual([r["metric"] for r in rows], ["stress"])

    def test_models_menu_marks_the_active_entry(self):
        data = self.client.get("/api/models").get_json()
        self.assertIn("models", data)
        self.assertTrue(data["active"])
        actives = [m for m in data["models"] if m["active"]]
        self.assertEqual(len(actives), 1)
        self.assertEqual(actives[0]["model"], data["active"])

    def test_plan_show_returns_macro_and_mesocycles(self):
        # Relative to today: `/api/plan` resolves the next ACTIVE goal, so a hard-coded
        # target date silently stops testing anything once it passes.
        from datetime import date, timedelta
        target = (date.today() + timedelta(days=60)).isoformat()
        goal_id = test_db.add_objective(
            title="A race", target_date=target, sport_type="running",
            description="", status="active",
        )
        test_db.save_macrocycle(
            objective_id=goal_id, strategy="build then peak", goals_hash="g",
            constraints_hash="l", config_hash="c",
            mesocycles=[{"name": "Base", "start_date": "2026-06-01",
                         "end_date": "2026-06-28", "focus": "aerobic"}],
        )
        data = self.client.get("/api/plan").get_json()
        self.assertEqual(data["goal"]["id"], goal_id)
        self.assertEqual(data["macrocycle"]["strategy"], "build then peak")
        self.assertEqual([m["name"] for m in data["mesocycles"]], ["Base"])

    def test_plan_show_without_a_goal_is_empty_not_an_error(self):
        res = self.client.get("/api/plan")
        self.assertEqual(res.status_code, 200)
        self.assertIsNone(res.get_json()["goal"])

    def test_zones_rejects_a_bad_window_or_currency(self):
        self.assertEqual(self.client.get("/api/zones?weeks=0").status_code, 400)
        self.assertEqual(self.client.get("/api/zones?weeks=x").status_code, 400)
        self.assertEqual(self.client.get("/api/zones?currency=rpe").status_code, 400)

    def test_zones_empty_history_reports_no_sports(self):
        data = self.client.get("/api/zones").get_json()
        self.assertEqual(data["sports"], [])
        self.assertEqual(data["window"]["weeks"], 8)

    def test_zones_report_measured_seconds_for_a_recorded_sport(self):
        # One run with its HR zone seconds recorded, inside the default 8-week window.
        today = date.fromisoformat(stamind_web.today_str())
        when = (today - timedelta(days=7)).isoformat()
        test_db.save_completed_activity(
            activity_id="z1", date=when, start_time=f"{when} 08:00:00",
            activity_name="Zone run", activity_type="running",
            duration_sec=3600, distance_km=10.0, elevation_gain_m=0.0,
            avg_hr=145, max_hr=170, rpe=None, tss=60.0,
            zone1_sec=600, zone2_sec=1800, zone3_sec=900, zone4_sec=300, zone5_sec=0,
        )
        # Naming the sport explicitly is the CLI's own override of the volume filter,
        # so the assertion does not depend on the machine's configured preferences.
        data = self.client.get("/api/zones?sport=running").get_json()

        running = next((s for s in data["sports"] if s["sport"] == "running"), None)
        self.assertIsNotNone(running, f"expected a running table, got {data['sports']}")
        self.assertEqual(running["currency"], "hr")
        self.assertEqual(len(running["zone_labels"]), 5)
        week = next(w for w in running["weeks"] if w["seconds"])
        self.assertEqual(sum(week["seconds"]), 3600)
        self.assertFalse(week["future"])


if __name__ == "__main__":
    unittest.main()
