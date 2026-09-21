"""Which plan a mesocycle walk reads, and the contiguity every plan is written
with.
"""
import os
import unittest
from datetime import datetime, timedelta, timezone

from tests.helpers import clear_all_tables, pin_clock, rebind_test_db
from tests import test_db_path

TEST_DB_PATH = test_db_path("test_periodization_lineage.db")


def _days_out(n: int) -> str:
    return (datetime.now(timezone.utc).date() + timedelta(days=n)).isoformat()


# Fixtures ride on today rather than on fixed dates; test_periodization.py says why.

from stamind.db import Database
from stamind.db.periodization import repair_mesocycle_contiguity

test_db = Database(db_path=TEST_DB_PATH)
rebind_test_db(test_db)


class TestPlanLineage(unittest.TestCase):
    """The retrospective mesocycle walk takes the previous *goal's* plan and never an earlier
    *version* of this goal's own (DESIGN_plan_rollback.md §6.1). `_mesocycles_in_window` used
    to call the version accessor, so `tm progress --mesocycles` reported every mesocycle twice
    after any regeneration — the two plans cover the same dates."""

    TODAY = "2026-08-05"

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
        pin_clock(self, self.TODAY)

    def _goal(self, title, target_date):
        return test_db.add_objective(
            title=title, target_date=target_date, sport_type="running",
        )

    def _plan(self, obj_id, strategy, mesocycles):
        return test_db.save_macrocycle(
            objective_id=obj_id, strategy=strategy, goals_hash="g", constraints_hash="c",
            mesocycles=[{"name": name, "start_date": start, "end_date": end,
                         "focus": "aerobic"} for name, start, end in mesocycles],
        )

    def test_regenerating_does_not_duplicate_the_mesocycles(self):
        """The regression: v1 and v2 span the same dates, so walking both reports every
        calendar period twice and counts each activity into two mesocycles."""
        from stamind.cli.progress_zones import _mesocycles_in_window

        obj = self._goal("Autumn Marathon", "2026-09-20")
        self._plan(obj, "v1", [("V1 Base", "2026-06-01", "2026-06-28"),
                               ("V1 Build", "2026-06-29", "2026-07-26")])
        v2 = self._plan(obj, "v2", [("V2 Base", "2026-06-01", "2026-06-28"),
                                    ("V2 Build", "2026-06-29", "2026-07-26")])

        mesocycles = _mesocycles_in_window(test_db, "2026-06-01", self.TODAY)
        self.assertEqual([b["name"] for b in mesocycles], ["V2 Base", "V2 Build"])
        self.assertEqual({b["macrocycle_id"] for b in mesocycles}, {v2})

    def test_the_previous_goals_plan_is_walked(self):
        """The other half: a window reaching back past the current plan's first mesocycle
        lands in the previous goal's plan, which nothing else supplies."""
        from stamind.cli.progress_zones import _mesocycles_in_window

        spring = self._goal("Spring 10k", "2026-05-31")
        self._plan(spring, "spring", [("Spring Base", "2026-04-06", "2026-05-31")])
        autumn = self._goal("Autumn Marathon", "2026-09-20")
        self._plan(autumn, "autumn", [("Autumn Base", "2026-06-01", "2026-06-28")])

        mesocycles = _mesocycles_in_window(test_db, "2026-04-06", self.TODAY)
        self.assertEqual([b["name"] for b in mesocycles], ["Spring Base", "Autumn Base"])

    def test_preceding_macrocycle_skips_superseded_versions(self):
        """`get_preceding_macrocycle` reaches the previous goal's *active* plan, not
        whichever version of it happens to be newest."""
        spring = self._goal("Spring 10k", "2026-05-31")
        self._plan(spring, "spring v1", [("Old", "2026-04-06", "2026-05-31")])
        spring_v2 = self._plan(spring, "spring v2", [("New", "2026-04-06", "2026-05-31")])
        autumn = self._goal("Autumn Marathon", "2026-09-20")

        preceding = test_db.get_preceding_macrocycle(autumn)
        self.assertEqual(preceding["id"], spring_v2)
        self.assertEqual(preceding["strategy"], "spring v2")

    def test_preceding_macrocycle_is_none_for_the_earliest_goal(self):
        first = self._goal("Spring 10k", "2026-05-31")
        self._plan(first, "spring", [("Base", "2026-04-06", "2026-05-31")])
        self.assertIsNone(test_db.get_preceding_macrocycle(first))

    def test_the_two_previous_plan_accessors_disagree_on_purpose(self):
        """The naming fix, pinned: same goal, two accessors, opposite answers."""
        spring = self._goal("Spring 10k", "2026-05-31")
        spring_macro = self._plan(spring, "spring", [("S", "2026-04-06", "2026-05-31")])
        autumn = self._goal("Autumn Marathon", "2026-09-20")
        autumn_v1 = self._plan(autumn, "autumn v1", [("A1", "2026-06-01", "2026-06-28")])
        self._plan(autumn, "autumn v2", [("A2", "2026-06-01", "2026-06-28")])

        self.assertEqual(
            test_db.get_previous_macrocycle_version(autumn)["id"], autumn_v1
        )
        self.assertEqual(test_db.get_preceding_macrocycle(autumn)["id"], spring_macro)


class TestMesocycleContiguityRepair(unittest.TestCase):
    """Within one plan, mesocycles are contiguous by construction: save_macrocycle repairs
    model-authored dates instead of trusting them (DOMAIN_MODEL.md §4). End dates stay
    authoritative; starts are re-derived, and a swallowed mesocycle is dropped."""

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

    def _save(self, mesocycles):
        obj = test_db.add_objective(
            title="Goal", target_date=_days_out(90), sport_type="running",
        )
        macro = test_db.save_macrocycle(
            objective_id=obj, strategy="s", goals_hash="g", constraints_hash="c",
            mesocycles=[{"name": name, "start_date": start, "end_date": end,
                         "focus": "f"} for name, start, end in mesocycles],
        )
        return test_db.get_mesocycles_for_macrocycle(macro)

    def test_contiguous_mesocycles_are_stored_untouched(self):
        stored = self._save([("Base", _days_out(0), _days_out(27)),
                             ("Build", _days_out(28), _days_out(55))])
        self.assertEqual([(b["start_date"], b["end_date"]) for b in stored],
                         [(_days_out(0), _days_out(27)), (_days_out(28), _days_out(55))])

    def test_a_gap_between_mesocycles_is_closed_at_save(self):
        stored = self._save([("Base", _days_out(0), _days_out(27)),
                             ("Build", _days_out(33), _days_out(55))])
        self.assertEqual(stored[1]["start_date"], _days_out(28))
        self.assertEqual(stored[1]["end_date"], _days_out(55))

    def test_overlapping_mesocycles_are_redated_at_save(self):
        stored = self._save([("Base", _days_out(0), _days_out(27)),
                             ("Build", _days_out(20), _days_out(55))])
        self.assertEqual(stored[1]["start_date"], _days_out(28))

    def test_a_mesocycle_its_predecessor_swallows_is_dropped(self):
        stored = self._save([("Base", _days_out(0), _days_out(27)),
                             ("Blip", _days_out(10), _days_out(20)),
                             ("Build", _days_out(28), _days_out(55))])
        self.assertEqual([b["name"] for b in stored], ["Base", "Build"])

    def test_repair_names_what_it_changed_and_is_idempotent(self):
        mesocycles = [
            {"name": "Base", "start_date": _days_out(0), "end_date": _days_out(27),
             "focus": "f"},
            {"name": "Build", "start_date": _days_out(33), "end_date": _days_out(55),
             "focus": "f"},
        ]
        repaired, notes = repair_mesocycle_contiguity(mesocycles)
        self.assertEqual(len(notes), 1)
        self.assertIn("Build", notes[0])
        self.assertIn("gap", notes[0])
        again, no_notes = repair_mesocycle_contiguity(repaired)
        self.assertEqual(no_notes, [])
        self.assertEqual(again, repaired)
        # The input list is not mutated: the caller may still display what the model said.
        self.assertEqual(mesocycles[1]["start_date"], _days_out(33))


if __name__ == "__main__":
    unittest.main()
