"""The two plan-version endpoints behind `static/plan.js`: the list of versions, and the
comparison of two of them that `plan diff` renders on the terminal.

The panel they fill sits inside the dashboard's Dashboard view rather than in a tab of
its own.
"""
import json
import os
import unittest
import unittest.mock
from datetime import timedelta

from tests.helpers import clear_all_tables, rebind_test_db


def _goal_ahead(days: int = 100) -> str:
    """A goal date comfortably in the future, on the app's clock.

    These goals are scaffolding — nothing asserts the date — but a plan is only active
    while its goal is ahead, so a literal expired the tests the day it passed.
    """
    from stamind.clock import today_date
    return (today_date() + timedelta(days=days)).isoformat()

from tests import test_db_path

TEST_DB_PATH = test_db_path("test_stamind_web_plan.db")

from stamind.db import Database

import stamind_web

# An isolated database for the web app's singleton; test_web.py says why.
test_db = Database(db_path=TEST_DB_PATH)
rebind_test_db(test_db)


class TestPlanVersionsEndpoint(unittest.TestCase):
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

    def test_plan_versions_lists_active_and_superseded(self):
        oid = test_db.add_objective(
            title="Web Goal", target_date=_goal_ahead(),
            sport_type="running",
        )
        meso = [{
            "name": "Base", "start_date": "2026-06-01",
            "end_date": "2026-06-28", "focus": "Base",
        }]
        v1 = test_db.save_macrocycle(
            objective_id=oid, strategy="First", goals_hash="g",
            constraints_hash="l", mesocycles=meso,
        )
        v2 = test_db.save_macrocycle(
            objective_id=oid, strategy="Second", goals_hash="g",
            constraints_hash="l", mesocycles=meso,
        )

        res = self.client.get("/api/plan/versions")
        self.assertEqual(res.status_code, 200)
        data = res.get_json()
        self.assertEqual(data["goal"]["id"], oid)
        versions = {v["id"]: v for v in data["versions"]}
        self.assertEqual(set(versions), {v1, v2})
        self.assertEqual(versions[v2]["status"], "active")
        self.assertEqual(versions[v1]["status"], "superseded")


class TestPlanDiffEndpoint(unittest.TestCase):
    """GET /api/plan/diff — the web face of `plan diff`. Both front-ends render the same
    stamind/plan_versions.py structure, so this asserts the payload, not the wording."""

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

    def _seed(self):
        oid = test_db.add_objective(
            title="Diff Goal", target_date=_goal_ahead(),
            sport_type="running",
        )
        v1 = test_db.save_macrocycle(
            objective_id=oid, strategy="Base first. Then sharpen.",
            goals_hash="g", constraints_hash="c",
            mesocycles=[
                {"name": "Base", "start_date": "2026-06-01",
                 "end_date": "2026-06-28", "focus": "Volume."},
                {"name": "Dropped", "start_date": "2026-06-29",
                 "end_date": "2026-07-12", "focus": "Filler."},
            ],
            config_snapshot=json.dumps({"ftp": 200.0}),
        )
        v2 = test_db.save_macrocycle(
            objective_id=oid, strategy="Base first. Then sharpen.",
            goals_hash="g", constraints_hash="c",
            mesocycles=[
                {"name": "Base", "start_date": "2026-06-01",
                 "end_date": "2026-07-05", "focus": "Volume."},
            ],
            config_snapshot=json.dumps({"ftp": 220.0}),
        )
        return oid, v1, v2

    def test_plan_diff_defaults_to_previous_vs_active(self):
        oid, v1, v2 = self._seed()

        res = self.client.get("/api/plan/diff")
        self.assertEqual(res.status_code, 200)
        data = res.get_json()
        self.assertEqual(data["goal"]["id"], oid)
        diff = data["diff"]
        self.assertEqual(diff["from"]["id"], v1)
        self.assertEqual(diff["to"]["id"], v2)
        self.assertFalse(diff["strategy"]["changed"])

        mesocycles = {m["change"]: m for m in diff["mesocycles"]}
        self.assertEqual(mesocycles["changed"]["name"], "Base")
        self.assertEqual(
            mesocycles["changed"]["dates"],
            {"from": {"start": "2026-06-01", "end": "2026-06-28"},
             "to": {"start": "2026-06-01", "end": "2026-07-05"}},
        )
        self.assertEqual(mesocycles["removed"]["name"], "Dropped")

        (drift,) = diff["thresholds"]["changed"]
        self.assertEqual(drift["key"], "ftp")
        self.assertAlmostEqual(drift["pct"], 10.0)
        # Neither version snapshotted its goals, which must not read as a deletion.
        self.assertEqual(diff["goals"]["missing"], "both")
        self.assertEqual(diff["goals"]["removed"], [])

    def test_plan_diff_explicit_versions_and_errors(self):
        oid, v1, v2 = self._seed()

        res = self.client.get(f"/api/plan/diff?from_version={v2}&to_version={v1}")
        self.assertEqual(res.status_code, 200)
        diff = res.get_json()["diff"]
        self.assertEqual((diff["from"]["id"], diff["to"]["id"]), (v2, v1))
        self.assertAlmostEqual(diff["thresholds"]["changed"][0]["to"], 200.0)

        res = self.client.get(f"/api/plan/diff?from_version={v1}&to_version={v1}")
        self.assertEqual(res.status_code, 400)
        self.assertEqual(res.get_json()["code"], "same_version")

        res = self.client.get("/api/plan/diff?from_version=9999")
        self.assertEqual(res.status_code, 404)
        self.assertEqual(res.get_json()["code"], "not_found")

    def test_plan_diff_single_version(self):
        test_db.add_objective(
            title="Lonely", target_date=_goal_ahead(), sport_type="running",
        )
        objectives = test_db.get_objectives(status='active')
        test_db.save_macrocycle(
            objective_id=objectives[0]['id'], strategy="Only", goals_hash="g",
            constraints_hash="c", mesocycles=[],
        )
        res = self.client.get("/api/plan/diff")
        self.assertEqual(res.status_code, 400)
        self.assertEqual(res.get_json()["code"], "single_version")


if __name__ == "__main__":
    unittest.main()
