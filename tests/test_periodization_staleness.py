"""Which changed input makes a plan stale, and which does not.

The partition matters in both directions: `name`, `equipment` and
`preferences` reach every prompt but cannot shape the periodization, while
narrowing what triggers a replan must not let a real shaping field through.
"""
import os
import unittest

from tests.helpers import clear_all_tables, rebind_test_db
from tests import test_db_path

TEST_DB_PATH = test_db_path("test_periodization_staleness.db")


# Fixtures ride on today rather than on fixed dates; test_periodization.py says why.

from trainmate import plan_inputs
import trainmate.config
from trainmate.db import Database

test_db = Database(db_path=TEST_DB_PATH)
rebind_test_db(test_db)

from trainmate.coach.service import coach_service


class TestPlanStaleness(unittest.TestCase):
    """What a changed profile field, weekly-schedule sub-key or threshold does to
    the plan's freshness, and the reason the athlete is shown for it."""

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

    def test_non_plan_shaping_profile_fields_do_not_flag_the_plan_stale(self):
        """`name`, `equipment` and `preferences` reach every prompt but cannot shape the
        periodization, so editing one must not propose a replan (DESIGN_plan_staleness.md
        §3, §11: structure lives in the science documents, which flag on their own)."""
        original_profile = dict(trainmate.config.config.data["user_profile"])
        try:
            profile = trainmate.config.config.data["user_profile"]
            profile["name"] = "Sam"
            profile["equipment"] = ["carbon road bike"]
            profile["preferences"] = "Zwift on weekdays"
            baseline = plan_inputs.plan_config_hash()

            profile["name"] = "Alex"
            self.assertEqual(baseline, plan_inputs.plan_config_hash())

            profile["equipment"] = ["carbon road bike", "rowing machine"]
            self.assertEqual(baseline, plan_inputs.plan_config_hash())

            profile["preferences"] = "Zwift on weekdays, gravel bike in winter"
            self.assertEqual(baseline, plan_inputs.plan_config_hash())
        finally:
            trainmate.config.config.data["user_profile"] = original_profile

    def test_weekly_schedule_is_fingerprinted_per_sub_key(self):
        """A day's kit shapes that day's session; its hours, session cap and certainty
        are load structure (DESIGN_plan_staleness.md §4)."""
        original_profile = dict(trainmate.config.config.data["user_profile"])
        try:
            profile = trainmate.config.config.data["user_profile"]
            profile["weekly_schedule"] = {
                "Monday": {
                    "total_available_hours": 1.5, "max_sessions": 1,
                    "certainty_percent": 100, "equipment": ["office gym"],
                }
            }
            monday = profile["weekly_schedule"]["Monday"]
            baseline = plan_inputs.plan_config_hash()

            monday["equipment"] = ["rowing machine"]
            self.assertEqual(baseline, plan_inputs.plan_config_hash())

            for key, value in (("total_available_hours", 2.5),
                               ("max_sessions", 2),
                               ("certainty_percent", 50)):
                with self.subTest(sub_key=key):
                    restore = monday[key]
                    monday[key] = value
                    self.assertNotEqual(baseline, plan_inputs.plan_config_hash())
                    monday[key] = restore
        finally:
            trainmate.config.config.data["user_profile"] = original_profile

    def test_plan_shaping_profile_fields_still_flag_the_plan_stale(self):
        """The other side of the partition — narrowing what triggers a replan must not
        have cost us the fields that genuinely reshape a periodization (§3)."""
        original_profile = dict(trainmate.config.config.data["user_profile"])
        try:
            profile = trainmate.config.config.data["user_profile"]
            profile.update({
                "birth_year": 1986, "weekly_target_hours": 8.0,
                "sport_preferences": ["cycling"], "chronic_injuries": "none",
            })
            baseline = plan_inputs.plan_config_hash()

            for key, value in (("birth_year", 1956),
                               ("weekly_target_hours", 20.0),
                               ("sport_preferences", ["cycling", "swimming"]),
                               ("chronic_injuries", "left ACL reconstructed")):
                with self.subTest(field=key):
                    restore = profile[key]
                    profile[key] = value
                    self.assertNotEqual(baseline, plan_inputs.plan_config_hash())
                    profile[key] = restore
        finally:
            trainmate.config.config.data["user_profile"] = original_profile

    def test_stale_reason_names_the_profile_fields_that_moved(self):
        """config_hash answers "did something change", the snapshot answers "what" — so
        the athlete can judge the proposal without diffing config.yaml by hand (§5)."""
        original_profile = dict(trainmate.config.config.data["user_profile"])
        try:
            profile = trainmate.config.config.data["user_profile"]
            profile["sport_preferences"] = ["cycling"]
            profile["chronic_injuries"] = "none"
            profile["weekly_target_hours"] = 8.0
            macro = {
                "config_hash": plan_inputs.plan_config_hash(),
                "config_snapshot": coach_service._get_config_snapshot(),
                "profile_snapshot": coach_service._get_profile_snapshot(),
            }
            self.assertIsNone(coach_service.config_changed(macro))

            profile["sport_preferences"] = ["cycling", "swimming"]
            self.assertEqual(
                coach_service.config_changed(macro),
                "athlete profile changed: sport_preferences",
            )

            # Several at once are all named, in a stable order.
            profile["weekly_target_hours"] = 12.0
            self.assertEqual(
                coach_service.config_changed(macro),
                "athlete profile changed: sport_preferences, weekly_target_hours",
            )

            # A field that disappears is named the same way as one that was edited —
            # the other two are put back so only the removal is left to report.
            profile["sport_preferences"] = ["cycling"]
            profile["weekly_target_hours"] = 8.0
            del profile["chronic_injuries"]
            self.assertEqual(
                coach_service.config_changed(macro),
                "athlete profile changed: chronic_injuries",
            )

            # A snapshot taken before a field left the partition still carries it; it
            # is read through the current partition, so the field is not reported as
            # deleted — only what really moved is named (§7).
            profile["chronic_injuries"] = "none"
            import json
            stale_partition = dict(json.loads(macro["profile_snapshot"]))
            stale_partition["preferences"] = "long prose that no longer shapes the plan"
            older = dict(macro, profile_snapshot=json.dumps(stale_partition))
            self.assertIsNone(coach_service.config_changed(older))
            profile["weekly_target_hours"] = 12.0
            self.assertEqual(
                coach_service.config_changed(older),
                "athlete profile changed: weekly_target_hours",
            )
            self.assertNotIn("preferences", coach_service.profile_diff(older))
            profile["weekly_target_hours"] = 8.0
            del profile["chronic_injuries"]

            # A plan predating the snapshot column — or carrying an unreadable one —
            # cannot attribute the change, so it says only that there was one (§5).
            for snapshot in (None, "", "{not json"):
                with self.subTest(snapshot=snapshot):
                    self.assertEqual(
                        coach_service.config_changed(
                            dict(macro, profile_snapshot=snapshot)
                        ),
                        "athlete profile changed",
                    )
        finally:
            trainmate.config.config.data["user_profile"] = original_profile

    def test_config_changed_threshold_tolerance(self):
        # FTP now lives in the benchmark logbook, not config (DESIGN_benchmark_workouts
        # §3.4); drift is driven by recording newer results (latest row wins).
        original_profile = dict(trainmate.config.config.data["user_profile"])
        try:
            test_db.add_benchmark_result(
                date="2026-06-01", sport_type="cycling",
                anchor_kind="ftp", value=220, unit="W",
            )
            macro = {
                "config_hash": plan_inputs.plan_config_hash(),
                "config_snapshot": coach_service._get_config_snapshot(),
            }
            self.assertIsNone(coach_service.config_changed(macro))

            # Within the default 5% band: still current.
            test_db.add_benchmark_result(
                date="2026-06-15", sport_type="cycling",
                anchor_kind="ftp", value=228, unit="W",
            )
            self.assertIsNone(coach_service.config_changed(macro))

            # Past the band: stale, with the threshold named in the reason.
            test_db.add_benchmark_result(
                date="2026-07-01", sport_type="cycling",
                anchor_kind="ftp", value=250, unit="W",
            )
            reason = coach_service.config_changed(macro)
            self.assertIsNotNone(reason)
            self.assertIn("ftp", reason)

            # A newly recorded kind absent from the old snapshot is skipped (§3.5), not
            # read as instant drift — restore ftp to baseline first so it isn't the cause.
            test_db.add_benchmark_result(
                date="2026-07-02", sport_type="cycling",
                anchor_kind="ftp", value=220, unit="W",
            )
            test_db.add_benchmark_result(
                date="2026-07-03", sport_type="swimming",
                anchor_kind="css", value=95, unit="sec/100m",
            )
            self.assertIsNone(coach_service.config_changed(macro))

            # Non-threshold profile edits still trip the fingerprint.
            trainmate.config.config.data["user_profile"]["weekly_target_hours"] = 20.0
            self.assertEqual(
                coach_service.config_changed(macro), "athlete profile changed"
            )

            # Legacy macrocycle without a snapshot: fingerprint alone decides.
            trainmate.config.config.data["user_profile"] = dict(original_profile)
            legacy = {"config_hash": plan_inputs.plan_config_hash(),
                      "config_snapshot": None}
            self.assertIsNone(coach_service.config_changed(legacy))
        finally:
            trainmate.config.config.data["user_profile"] = original_profile

    def test_e1rm_never_invalidates_a_periodization(self):
        """e1rm collides across lifts — the logbook has no per-exercise field, so a
        deadlift PR logged after a squat PR is one value jumping 70%. It must not trip a
        replan (DESIGN_intensity_distribution.md §10)."""
        test_db.add_benchmark_result(
            date="2026-06-01", sport_type="strength_training",
            anchor_kind="e1rm", value=102, unit="kg",
        )
        macro = {
            "config_hash": plan_inputs.plan_config_hash(),
            "config_snapshot": coach_service._get_config_snapshot(),
        }
        self.assertIsNone(coach_service.config_changed(macro))

        # A different lift entirely — a 70% jump that would otherwise read as drift.
        test_db.add_benchmark_result(
            date="2026-07-01", sport_type="strength_training",
            anchor_kind="e1rm", value=175, unit="kg",
        )
        self.assertIsNone(coach_service.config_changed(macro))
        # It still reaches the coaching prompt; it just never invalidates the plan.
        self.assertEqual(coach_service.effective_thresholds()["e1rm"], 175.0)


if __name__ == "__main__":
    unittest.main()
