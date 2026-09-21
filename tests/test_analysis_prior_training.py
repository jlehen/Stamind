"""The cached reconstruction fed read-only into the `plan generate` strategy
prompt.
"""
import os
import unittest

from tests.helpers import clear_all_tables, rebind_test_db, save_workout
from trainmate.db import Database
from tests import test_db_path

TEST_DB_PATH = test_db_path("test_analysis_prior_training.db")
test_db = Database(db_path=TEST_DB_PATH)
rebind_test_db(test_db)

from trainmate.coach.service import coach_service


class TestPriorTrainingContext(unittest.TestCase):
    """The cached reconstruction is fed read-only into the plan-generate strategy prompt
    (DESIGN_backward_evaluation.md §6)."""

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

    def test_inferred_mesocycles_reach_the_context(self):
        """The reverse-engineered macro focus and mesocycles from a bootstrap
        reconstruction are rendered into the prior-training context, not just the summary."""
        test_db.save_analysis_cache(
            "long", "fp", "2026-03-01", "2026-05-31",
            {
                "macrocycle_summary": "Built a solid aerobic base.",
                "inferred_macrocycle": {
                    "overall_focus": "Marathon base prep",
                    "start_date": "2026-03-01",
                    "end_date": "2026-05-31",
                },
                "inferred_mesocycles": [
                    {
                        "name": "Base Building",
                        "start_date": "2026-03-01",
                        "end_date": "2026-04-15",
                        "focus_detected": "Aerobic volume",
                        "average_weekly_tss": 380.0,
                        "estimated_consistency": "High",
                    },
                ],
                "physiological_insights": ["RHR trended down as volume rose."],
            },
        )

        text = coach_service._build_prior_training_context([], "2026-06-15")

        self.assertIsNotNone(text)
        self.assertIn("Reconstructed macrocycle focus", text)
        self.assertIn("Marathon base prep", text)
        self.assertIn("Base Building", text)
        self.assertIn("Aerobic volume", text)
        self.assertIn("380 TSS/wk", text)
        self.assertIn("High consistency", text)
        self.assertIn("RHR trended down", text)

    # ------------------------------------------------- which caches get replayed

    @staticmethod
    def _cache(horizon: str, start: str, end: str, summary: str) -> None:
        test_db.save_analysis_cache(
            horizon, f"fp-{horizon}", start, end, {"macrocycle_summary": summary}
        )

    def test_the_latest_reflection_joins_the_bootstrap_reconstruction(self):
        """`data reflect` used to write a cache slot nothing ever read, so everything it
        learned after onboarding was invisible to planning (§10.2)."""
        self._cache("long", "2026-01-01", "2026-05-31", "Winter base rebuilt.")
        self._cache("short", "2026-06-01", "2026-07-15", "Threshold work started.")

        text = coach_service._build_prior_training_context([], "2026-07-20")

        self.assertIn("full history reconstruction", text)
        self.assertIn("Winter base rebuilt.", text)
        self.assertIn("most recent reflection", text)
        self.assertIn("Threshold work started.", text)

    def test_a_reflection_no_later_than_bootstrap_is_not_replayed(self):
        """Ground bootstrap already covered: replaying it would put two accounts of the
        same weeks in front of the model."""
        self._cache("long", "2026-01-01", "2026-05-31", "Winter base rebuilt.")
        self._cache("short", "2026-04-01", "2026-05-31", "Same weeks, second opinion.")

        text = coach_service._build_prior_training_context([], "2026-07-20")

        self.assertIn("Winter base rebuilt.", text)
        self.assertNotIn("Same weeks, second opinion.", text)

    def test_a_reflection_overlapping_bootstrap_is_not_replayed(self):
        """Ending later is not enough: a window that RE-READS bootstrap's weeks on its way
        past them still puts one body of evidence in front of the model twice (§10.2)."""
        self._cache("long", "2026-01-01", "2026-05-31", "Winter base rebuilt.")
        self._cache("short", "2026-04-01", "2026-07-15", "Overlaps, then runs past.")

        text = coach_service._build_prior_training_context([], "2026-07-20")

        self.assertIn("Winter base rebuilt.", text)
        self.assertNotIn("Overlaps, then runs past.", text)

    def test_reflection_alone_is_replayed_when_bootstrap_never_ran(self):
        self._cache("short", "2026-06-01", "2026-07-15", "Threshold work started.")

        text = coach_service._build_prior_training_context([], "2026-07-20")

        self.assertIn("most recent reflection", text)
        self.assertIn("Threshold work started.", text)

    # ------------------------------------------------------- planned vs actual load

    # Two whole Monday-weeks, so the week buckets line up with the mesocycle and no edge week
    # is partial by accident.
    MESOCYCLE_START, MESOCYCLE_END = "2026-06-08", "2026-06-21"
    ZONES = [600, 1800, 900, 300, 0]

    def _plan(
        self, name: str = "Base 3", start: str = MESOCYCLE_START, end: str = MESOCYCLE_END,
        goal: str = "Gran Fondo", target: str = "2026-10-15",
    ) -> int:
        obj_id = test_db.add_objective(
            title=goal, target_date=target, sport_type="cycling"
        )
        return test_db.save_macrocycle(
            objective_id=obj_id, strategy="Build", goals_hash="g", constraints_hash="c",
            mesocycles=[{
                "name": name, "start_date": start, "end_date": end,
                "focus": "aerobic volume",
            }],
        )

    def _planned_session(self, macro_id: int, date: str, tss: float) -> None:
        save_workout(test_db,
            date=date, sport_type="cycling", title="Endurance",
            description="[Endurance]\n2h steady", duration_minutes=120, rpe=5, tss=tss,
            macrocycle_id=macro_id,
            planned_zone_currency="hr", planned_zone_sec=self.ZONES,
        )

    @staticmethod
    def _completed(date: str, tss: float, activity_id: str) -> None:
        test_db.save_completed_activity(
            activity_id=activity_id, date=date, start_time=f"{date}T07:00:00",
            activity_name="Ride", activity_type="cycling", duration_sec=3600,
            distance_km=30.0, elevation_gain_m=200.0, avg_hr=140, max_hr=170, rpe=5,
            tss=tss, zone1_sec=600, zone2_sec=1800, zone3_sec=900, zone4_sec=300,
            zone5_sec=0,
        )

    def _half_missed_mesocycle(self) -> None:
        """Both weeks asked for 100; only the first was trained."""
        macro_id = self._plan()
        self._planned_session(macro_id, "2026-06-09", 100.0)
        self._planned_session(macro_id, "2026-06-16", 100.0)
        self._completed("2026-06-09", 100.0, "w1")

    def test_elapsed_mesocycles_report_each_week_planned_against_actual(self):
        """Without this a half-missed mesocycle reads exactly like a completed one, and the
        next macrocycle ramps from a load the athlete never reached."""
        self._half_missed_mesocycle()

        text = coach_service._build_prior_training_context([], "2026-07-20")

        self.assertIn("Weekly load (what the plan asked -> what was produced)", text)
        self.assertIn("week of 2026-06-08: planned 100, actual 100 (100%)", text)
        self.assertIn("week of 2026-06-15: planned 100, actual 0 (0%)", text)

    def test_elapsed_mesocycles_show_what_the_plan_prescribed(self):
        """Measured beside prescribed is what separates a mis-designed mesocycle from a
        mis-executed one (DESIGN_intensity_distribution.md §9.2a)."""
        self._half_missed_mesocycle()

        text = coach_service._build_prior_training_context([], "2026-07-20")

        self.assertIn("What the plan PRESCRIBED over the same weeks", text)

    # --------------------------------------------------- ordering across macrocycles

    def _two_plans(self):
        """An earlier macrocycle and a later one, each two whole weeks, both trained."""
        early = self._plan(
            name="Base 3", start="2026-06-08", end="2026-06-21",
            goal="Spring Hill Climb", target="2026-06-21",
        )
        late = self._plan(
            name="Build 1", start="2026-06-22", end="2026-07-05",
            goal="Gran Fondo", target="2026-10-15",
        )
        for i, day in enumerate(("2026-06-09", "2026-06-16")):
            self._planned_session(early, day, 100.0)
            self._completed(day, 100.0, f"e{i}")
        for i, day in enumerate(("2026-06-23", "2026-06-30")):
            self._planned_session(late, day, 100.0)
            self._completed(day, 100.0, f"l{i}")
        return (
            test_db.get_macrocycle(early), test_db.get_macrocycle(late)
        )

    def test_mesocycles_are_ordered_by_when_they_were_trained(self):
        """The caller's argument order is not chronological — the plan being replaced can
        be for a later goal than the governing one — and each mesocycle's delta baseline is
        the mesocycle before it in the flattened list (§6.1)."""
        early, late = self._two_plans()

        text = coach_service._build_prior_training_context([late, early], "2026-07-20")

        # Build 1 came after Base 3, so that is what it is compared against.
        self.assertIn("Change vs Base 3", text)
        self.assertNotIn("Change vs Build 1", text)
        self.assertLess(text.index("Base 3 —"), text.index("Build 1 —"))


if __name__ == "__main__":
    unittest.main()
