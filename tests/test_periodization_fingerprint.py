"""What a plan's inputs hash over, and what survives save and reload: the goal
and constraint hashes, the config hash, the snapshots the reason is later
read out of, and the database columns that hold them.
"""
import os
import unittest
from datetime import datetime, timedelta, timezone
from unittest.mock import patch

from tests.helpers import clear_all_tables, rebind_test_db
from tests import test_db_path

TEST_DB_PATH = test_db_path("test_periodization_fingerprint.db")


def _days_out(n: int) -> str:
    return (datetime.now(timezone.utc).date() + timedelta(days=n)).isoformat()


# Fixtures ride on today rather than on fixed dates; test_periodization.py says why.
GOAL_DATE = _days_out(71)

from stamind import plan_inputs
import stamind.config
from stamind.db import Database

test_db = Database(db_path=TEST_DB_PATH)
rebind_test_db(test_db)

from stamind.coach.service import coach_service


class TestPlanFingerprint(unittest.TestCase):
    """A fingerprint answers "did something change"; the snapshot beside it
    answers "what", so both are stamped when a plan is written."""

    @classmethod
    def setUpClass(cls):
        if os.path.exists(TEST_DB_PATH):
            os.remove(TEST_DB_PATH)
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

    def test_hashing_helpers(self):
        hash1 = plan_inputs.goals_hash([])
        hash2 = plan_inputs.constraints_hash([])
        hash3 = plan_inputs.plan_config_hash()
        self.assertIsNotNone(hash1)
        self.assertIsNotNone(hash2)
        self.assertIsNotNone(hash3)

        obj = {
            "id": 1, "title": "Test Goal", "target_date": "2026-10-15",
            "sport_type": "running", "description": "sub 3hr", "status": "active",
        }
        hash1_with_obj = plan_inputs.goals_hash([obj])
        self.assertNotEqual(hash1, hash1_with_obj)

        obj["description"] = "sub 2:50"
        self.assertNotEqual(hash1_with_obj, plan_inputs.goals_hash([obj]))

        c = {
            "id": 1, "title": "Spain Trip", "start_date": "2026-07-01",
            "end_date": "2026-07-08", "rest": 0, "description": "easy",
        }
        self.assertNotEqual(hash2, plan_inputs.constraints_hash([c]))

    @patch("stamind.coach.engine.openrouter_client")
    def test_plan_snapshots_goals_and_constraints(self, mock_client):
        import json
        obj_id = test_db.add_objective(
            title="Berlin Marathon", target_date=GOAL_DATE,
            sport_type="running", description="sub-3 attempt",
        )
        # A plan-shaping (replan=1) constraint the plan should snapshot. A tactical one
        # is excluded because only plan-shaping constraints fingerprint/snapshot the plan.
        test_db.add_constraint(
            title="Work trip", start_date=_days_out(1), end_date=_days_out(10),
            description="limited training time", replan=1,
        )
        test_db.add_constraint(
            title="no run Thursday", start_date=_days_out(6), end_date=_days_out(6),
            replan=0,
        )

        mock_client.complete.return_value = {
            "strategy": "Snapshot strategy",
            "mesocycles": [{
                "name": "Base Phase", "start_date": "2026-06-01",
                "end_date": "2026-06-28", "focus": "Base",
            }],
        }

        coach_service.plan_generate(force=True, objective_id=obj_id)

        macro = test_db.get_macrocycle_for_objective(obj_id)
        self.assertIsNotNone(macro["goals_snapshot"])
        self.assertIsNotNone(macro["constraints_snapshot"])
        self.assertIsNotNone(macro["all_constraints_snapshot"])

        goals = json.loads(macro["goals_snapshot"])
        events = json.loads(macro["constraints_snapshot"])
        all_events = json.loads(macro["all_constraints_snapshot"])
        self.assertEqual([g["title"] for g in goals], ["Berlin Marathon"])
        # Only the plan-shaping constraint is snapshotted, not the tactical one.
        self.assertEqual([e["title"] for e in events], ["Work trip"])
        # But the display-only "all" snapshot carries both, tagged with `replan`, since
        # the prompt is built from every active constraint (DESIGN_constraints.md §7).
        self.assertEqual(
            sorted((e["title"], e["replan"]) for e in all_events),
            [("Work trip", 1), ("no run Thursday", 0)],
        )

        # The snapshot must serialize exactly the data the hash fingerprints, so the
        # two never disagree about what the plan was built on.
        self.assertEqual(
            plan_inputs.goals_hash(goals), macro["goals_hash"]
        )
        self.assertEqual(
            plan_inputs.constraints_hash(events), macro["constraints_hash"]
        )

    def test_config_hash_logic(self):
        initial_hash = plan_inputs.plan_config_hash()
        self.assertIsNotNone(initial_hash)

        original_profile = dict(stamind.config.config.data["user_profile"])
        original_coach = dict(stamind.config.config.data.get("coach") or {})
        try:
            stamind.config.config.data["user_profile"]["weekly_target_hours"] = 20.0
            self.assertNotEqual(initial_hash, plan_inputs.plan_config_hash())
            stamind.config.config.data["user_profile"] = dict(original_profile)

            # Physiological thresholds are tolerance-checked via the snapshot, not
            # fingerprinted — editing one must not shift the hash.
            stamind.config.config.data["user_profile"]["ftp"] = 999
            self.assertEqual(initial_hash, plan_inputs.plan_config_hash())
            stamind.config.config.data["user_profile"] = dict(original_profile)

            # Prompt-context knobs are not plan-shaping.
            stamind.config.config.data["coach"] = dict(original_coach)
            stamind.config.config.data["coach"]["metrics_lookback_days"] = 99
            self.assertEqual(initial_hash, plan_inputs.plan_config_hash())
        finally:
            stamind.config.config.data["user_profile"] = original_profile
            stamind.config.config.data["coach"] = original_coach

    def test_profile_snapshot_round_trips_through_the_database(self):
        """The reason can only name fields if the snapshot survives save and reload."""
        original_profile = dict(stamind.config.config.data["user_profile"])
        try:
            profile = stamind.config.config.data["user_profile"]
            profile["sport_preferences"] = ["cycling"]
            obj_id = test_db.add_objective(
                title="Snapshot round trip", target_date=GOAL_DATE,
                sport_type="cycling",
            )
            # Real fingerprints: goals and the plan-shaping constraints flag the plan
            # too now, so a placeholder hash would read as a moved goal
            # (DESIGN_plan_change_continuity.md §6.5).
            test_db.save_macrocycle(
                objective_id=obj_id, strategy="Build",
                goals_hash=plan_inputs.goals_hash(
                    test_db.upcoming_objectives()
                ),
                constraints_hash=plan_inputs.constraints_hash([]),
                mesocycles=[],
                config_hash=plan_inputs.plan_config_hash(),
                config_snapshot=coach_service._get_config_snapshot(),
                profile_snapshot=coach_service._get_profile_snapshot(),
            )
            macro = test_db.get_macrocycle_for_objective(obj_id)
            self.assertIsNone(coach_service.config_changed(macro))

            profile["sport_preferences"] = ["cycling", "hiking"]
            self.assertEqual(
                coach_service.config_changed(macro),
                "athlete profile changed: sport_preferences",
            )
        finally:
            stamind.config.config.data["user_profile"] = original_profile

    def test_db_config_hash_operations(self):
        obj_id = test_db.add_objective(
            title="Zurich Marathon", target_date=GOAL_DATE,
            sport_type="running",
        )
        macro_id = test_db.save_macrocycle(
            objective_id=obj_id,
            strategy="Long runs",
            goals_hash="ghash",
            constraints_hash="lehash",
            config_hash="confhash123",
            mesocycles=[],
        )

        macro = test_db.get_macrocycle_for_objective(obj_id)
        self.assertEqual(macro["config_hash"], "confhash123")

        test_db.update_macrocycle_config_hash(macro_id, "newconfhash456")
        macro = test_db.get_macrocycle_for_objective(obj_id)
        self.assertEqual(macro["config_hash"], "newconfhash456")
        self.assertIsNone(macro["config_snapshot"])

        test_db.update_macrocycle_config_hash(
            macro_id, "confhash789", '{"ftp": 220.0}'
        )
        macro = test_db.get_macrocycle_for_objective(obj_id)
        self.assertEqual(macro["config_hash"], "confhash789")
        self.assertEqual(macro["config_snapshot"], '{"ftp": 220.0}')

        test_db.update_macrocycle_config_hash(
            macro_id, "confhashABC", '{"ftp": 230.0}', '{"birth_year": 1986}'
        )
        macro = test_db.get_macrocycle_for_objective(obj_id)
        self.assertEqual(macro["profile_snapshot"], '{"birth_year": 1986}')

        # Re-stamping only the hash leaves both snapshots standing, so the plan never
        # loses what it was generated against.
        test_db.update_macrocycle_config_hash(macro_id, "confhashDEF")
        macro = test_db.get_macrocycle_for_objective(obj_id)
        self.assertEqual(macro["config_hash"], "confhashDEF")
        self.assertEqual(macro["config_snapshot"], '{"ftp": 230.0}')
        self.assertEqual(macro["profile_snapshot"], '{"birth_year": 1986}')


if __name__ == "__main__":
    unittest.main()
