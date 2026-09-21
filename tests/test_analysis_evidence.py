"""The weekly evidence the reflect prompt is built from: the per-week body
response features, the quantitative signal-impact alignment and the
constraint bucketing — each pure, with no database and no model call — and
then the same three reaching a real run.
"""
import os
import unittest
from datetime import datetime
from unittest.mock import patch

from tests.helpers import clear_all_tables, rebind_test_db
from trainmate.analytics import weekly_evidence
from trainmate.db import Database
from tests import test_db_path

TEST_DB_PATH = test_db_path("test_analysis_evidence.db")
test_db = Database(db_path=TEST_DB_PATH)
rebind_test_db(test_db)

from trainmate.coach.service import coach_service


class TestWeekResponseFeatures(unittest.TestCase):
    """Pure unit tests for the deterministic per-week body-response features (no DB)."""

    BASELINE = {
        "rhr_baseline_mean": 50.0, "rhr_baseline_std": 4.0,
        "hrv_baseline_mean": 80.0, "hrv_baseline_std": 10.0,
        "sleep_baseline_mean": 70.0, "sleep_baseline_std": 8.0,
    }

    def test_z_scores_and_sign_convention(self):
        # Elevated RHR (worse) -> +z; suppressed HRV (worse) -> -z.
        metrics = [
            {"rhr": 54, "hrv": 70, "sleep_score": 66, "stress": 40},
            {"rhr": 58, "hrv": 70, "sleep_score": 66, "stress": 30},
        ]
        f = weekly_evidence.week_response_features(metrics, self.BASELINE)
        self.assertEqual(f["avg_stress"], 35.0)
        self.assertEqual(f["avg_sleep_score"], 66.0)
        self.assertEqual(f["vs_baseline_z"]["rhr"], 1.5)    # ((54-50)+(58-50))/2 /4 = 1.5
        self.assertEqual(f["vs_baseline_z"]["hrv"], -1.0)   # (70-80)/10
        self.assertEqual(f["vs_baseline_z"]["sleep"], -0.5) # (66-70)/8

    def test_zero_std_and_missing_baseline_yield_none(self):
        metrics = [{"rhr": 54, "hrv": 70, "sleep_score": 66}]
        flat = dict(self.BASELINE, rhr_baseline_std=0.0)  # undefined -> None
        self.assertIsNone(
            weekly_evidence.week_response_features(metrics, flat)["vs_baseline_z"]["rhr"]
        )
        # No baseline at all: vs_baseline_z omitted entirely, means still computed.
        f = weekly_evidence.week_response_features(metrics, None)
        self.assertNotIn("vs_baseline_z", f)
        self.assertEqual(f["avg_sleep_score"], 66.0)

    def test_no_metric_days_means_none(self):
        f = weekly_evidence.week_response_features([], self.BASELINE)
        self.assertIsNone(f["avg_sleep_score"])
        self.assertIsNone(f["avg_stress"])
        self.assertNotIn("vs_baseline_z", f)  # no values -> all None -> omitted


class TestSignalDays(unittest.TestCase):
    """Pure unit tests for the quantitative signal-impact alignment (no DB, no LLM):
    episode grouping, the bracketing morning strip, load attribution, channel exclusion,
    and the inclusion floor (DESIGN_quantitative_signal_impact.md §3–§5)."""

    BASELINE = {
        "rhr_baseline_mean": 50.0, "rhr_baseline_std": 4.0,
        "hrv_baseline_mean": 80.0, "hrv_baseline_std": 10.0,
        "sleep_baseline_mean": 70.0, "sleep_baseline_std": 8.0,
    }

    def _baseline_for(self, _date):  # baseline is flat across the test window
        return self.BASELINE

    @staticmethod
    def _act(date, tss):
        # rpe=None makes activity_load return the raw tss (no fallback path), so load is
        # deterministic regardless of HR-coverage heuristics.
        return {"date": date, "activity_type": "Run", "tss": tss, "rpe": None,
                "duration_sec": 3600}

    def test_day_response_z_sign_convention(self):
        z = weekly_evidence.day_response_z(
            {"rhr": 54, "hrv": 70, "sleep_score": 66}, self.BASELINE
        )
        self.assertEqual(z["rhr"], 1.0)    # (54-50)/4 elevated -> +z (worse)
        self.assertEqual(z["hrv"], -1.0)   # (70-80)/10 suppressed -> -z (worse)
        self.assertEqual(z["sleep"], -0.5)
        # Missing value / zero std / no baseline -> None.
        self.assertIsNone(weekly_evidence.day_response_z({"hrv": 70}, self.BASELINE)["rhr"])
        flat = dict(self.BASELINE, hrv_baseline_std=0.0)
        self.assertIsNone(weekly_evidence.day_response_z({"hrv": 70}, flat)["hrv"])
        self.assertIsNone(weekly_evidence.day_response_z({"hrv": 70}, None)["hrv"])

    def test_single_signal_day_episode_shape(self):
        ctx = [{"date": "2026-05-10", "metric": "alcohol", "value": 4.0}]
        metrics = [{"date": "2026-05-11", "rhr": 58, "hrv": 70, "sleep_score": 62}]
        acts = [self._act("2026-05-10", 85)]
        out = weekly_evidence.signal_days(
            ctx, metrics, acts, self._baseline_for, k=3, min_signal_days=1
        )
        eps = out["alcohol"]
        self.assertEqual(len(eps), 1)
        self.assertEqual(eps[0]["days"], [
            {"date": "2026-05-10", "value": 4, "load_tss": 85}  # 4.0 normalized to int 4
        ])
        # Strip spans (first-k+1)..(last+k) = 05-08 .. 05-13 -> 6 mornings.
        mornings = eps[0]["surrounding_mornings"]
        self.assertEqual([m["morning"] for m in mornings],
                         ["2026-05-08", "2026-05-09", "2026-05-10",
                          "2026-05-11", "2026-05-12", "2026-05-13"])
        # The morning AFTER the drink carries the drink-day's load as prev_day_load_tss.
        m11 = next(m for m in mornings if m["morning"] == "2026-05-11")
        self.assertEqual(m11["prev_day_load_tss"], 85)
        self.assertEqual(m11["vs_normal"], {"rhr": 2.0, "hrv": -1.0, "sleep": -1.0})
        # A morning with no metric row shows load context but an empty vs_normal (no data).
        m08 = next(m for m in mornings if m["morning"] == "2026-05-08")
        self.assertEqual(m08["vs_normal"], {})

    def test_consecutive_and_near_days_merge_one_episode(self):
        # 05-10, 05-11 (adjacent) and 05-14 (gap_free=2 < k=3) all merge into one episode;
        # the interior dry day 05-12/13 is NOT in days but its mornings still appear.
        ctx = [
            {"date": "2026-05-10", "metric": "alcohol", "value": 2},
            {"date": "2026-05-11", "metric": "alcohol", "value": 3},
            {"date": "2026-05-14", "metric": "alcohol", "value": 1},
        ]
        out = weekly_evidence.signal_days(
            ctx, [], [], self._baseline_for, k=3, min_signal_days=1
        )
        eps = out["alcohol"]
        self.assertEqual(len(eps), 1)
        self.assertEqual([d["date"] for d in eps[0]["days"]],
                         ["2026-05-10", "2026-05-11", "2026-05-14"])
        # Strip spans 05-08 .. 05-17, and 05-13 (a dry gap morning) is present.
        days_in_strip = {m["morning"] for m in eps[0]["surrounding_mornings"]}
        self.assertIn("2026-05-13", days_in_strip)
        self.assertNotIn("2026-05-13", {d["date"] for d in eps[0]["days"]})

    def test_large_gap_splits_into_two_episodes(self):
        # 4 days apart -> gap_free=3, not < k=3 -> separate episodes.
        ctx = [
            {"date": "2026-05-10", "metric": "alcohol", "value": 2},
            {"date": "2026-05-14", "metric": "alcohol", "value": 2},
        ]
        out = weekly_evidence.signal_days(
            ctx, [], [], self._baseline_for, k=3, min_signal_days=1
        )
        self.assertEqual(len(out["alcohol"]), 2)

    def test_min_signal_days_floor_omits_category(self):
        ctx = [{"date": "2026-05-10", "metric": "alcohol", "value": 2}]
        out = weekly_evidence.signal_days(
            ctx, [], [], self._baseline_for, k=3, min_signal_days=2
        )
        self.assertNotIn("alcohol", out)

    def test_sleep_construct_excludes_sleep_channel(self):
        ctx = [{"date": "2026-05-10", "metric": "poor_sleep", "value": 1}]
        metrics = [{"date": "2026-05-11", "rhr": 58, "hrv": 70, "sleep_score": 62}]
        out = weekly_evidence.signal_days(
            ctx, metrics, [], self._baseline_for, k=3, min_signal_days=1
        )
        m11 = next(
            m for m in out["poor_sleep"][0]["surrounding_mornings"]
            if m["morning"] == "2026-05-11"
        )
        self.assertNotIn("sleep", m11["vs_normal"])  # would be an echo, not an impact
        self.assertIn("hrv", m11["vs_normal"])
        self.assertIn("rhr", m11["vs_normal"])

    def test_presence_only_value_stays_none(self):
        ctx = [{"date": "2026-05-10", "metric": "big_meal", "value": None}]
        out = weekly_evidence.signal_days(
            ctx, [], [], self._baseline_for, k=3, min_signal_days=1
        )
        self.assertIsNone(out["big_meal"][0]["days"][0]["value"])

    def test_same_day_values_combine(self):
        ctx = [
            {"date": "2026-05-10", "metric": "alcohol", "value": 2},
            {"date": "2026-05-10", "metric": "alcohol", "value": 3},
        ]
        out = weekly_evidence.signal_days(
            ctx, [], [], self._baseline_for, k=3, min_signal_days=1
        )
        self.assertEqual(out["alcohol"][0]["days"][0]["value"], 5)


class TestWeekLifeEvents(unittest.TestCase):
    """Pure unit tests for per-week constraint bucketing (no DB)."""

    @staticmethod
    def _d(s):
        return datetime.strptime(s, "%Y-%m-%d").date()

    def test_full_partial_and_non_overlap(self):
        constraints = [
            {"title": "Flu", "start_date": "2026-06-01", "end_date": "2026-06-07",
             "type": "illness", "description": "bed-bound"},
            {"title": "Trip", "start_date": "2026-06-05", "end_date": "2026-06-10",
             "type": "travel", "description": ""},
            {"title": "Later", "start_date": "2026-06-20", "end_date": "2026-06-21",
             "type": "stress", "description": ""},
        ]
        out = weekly_evidence.week_constraints(
            constraints, self._d("2026-06-01"), self._d("2026-06-07")
        )
        titles = {e["title"]: e["coverage"] for e in out}
        self.assertEqual(titles, {"Flu": "full", "Trip": "partial"})  # "Later" excluded
        self.assertEqual(out[0]["impact"], "bed-bound")

    def test_multiweek_event_buckets_into_each_week(self):
        constraint = [{"title": "Long", "start_date": "2026-06-01", "end_date": "2026-06-14",
                       "type": "injury", "description": ""}]
        wk1 = weekly_evidence.week_constraints(
            constraint, self._d("2026-06-01"), self._d("2026-06-07")
        )
        wk2 = weekly_evidence.week_constraints(
            constraint, self._d("2026-06-08"), self._d("2026-06-14")
        )
        self.assertEqual([e["coverage"] for e in wk1], ["full"])
        self.assertEqual([e["coverage"] for e in wk2], ["full"])


class TestRicherEvidenceIntegration(unittest.TestCase):
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

    def _seed_week(self):
        test_db.save_completed_activity(
            activity_id="a1", date="2026-06-03", start_time="08:00:00",
            activity_name="Ride", activity_type="cycling",
            duration_sec=3600.0, distance_km=20.0, elevation_gain_m=100.0,
            avg_hr=130, max_hr=150, rpe=5, tss=60.0,
        )
        test_db.save_metric_cache("2026-06-03", rhr=58, hrv=68, sleep_score=60, stress=45)
        test_db.save_baseline(
            "2026-06-01", rhr_mean=50.0, rhr_std=4.0, hrv_mean=80.0,
            hrv_std=10.0, sleep_mean=70.0, sleep_std=8.0,
        )
        test_db.add_constraint(
            title="Work crunch", start_date="2026-06-01", end_date="2026-06-07",
            description="long hours, poor sleep",
        )

    @patch("trainmate.coach.engine.openrouter_client")
    def test_features_and_events_reach_the_prompt(self, mock_client):
        self._seed_week()
        mock_client.complete.return_value = {"macrocycle_summary": "s", "learning_updates": []}
        coach_service.data_bootstrap(
            from_date_str="2026-06-01", until_date_str="2026-06-07", no_pull=True
        )
        user_content = mock_client.complete.call_args[0][1]
        self.assertIn("constraints", user_content)
        self.assertIn("Work crunch", user_content)
        self.assertIn("vs_baseline_z", user_content)
        self.assertIn("avg_stress", user_content)

    @patch("trainmate.coach.engine.openrouter_client")
    def test_signal_days_reaches_the_prompt(self, mock_client):
        """A logged external signal (alcohol) surfaces as an episode-aligned signal_days
        section in the analysis user content (DESIGN_quantitative_signal_impact.md §4)."""
        self._seed_week()
        test_db.upsert_daily_signal_by_event(
            "evt1", "2026-06-02", "alcohol", value=4.0, text="Alcohol: 4 drinks"
        )
        mock_client.complete.return_value = {"macrocycle_summary": "s", "learning_updates": []}
        coach_service.data_bootstrap(
            from_date_str="2026-06-01", until_date_str="2026-06-07", no_pull=True
        )
        user_content = mock_client.complete.call_args[0][1]
        self.assertIn("QUANTITATIVE SIGNAL IMPACT", user_content)
        self.assertIn("surrounding_mornings", user_content)
        self.assertIn("alcohol", user_content)

    @patch("trainmate.coach.engine.openrouter_client")
    def test_editing_a_life_event_invalidates_the_cache(self, mock_client):
        """A constraint change shifts the evidence fingerprint, so the next run recomputes
        rather than reusing the cached reconstruction."""
        self._seed_week()
        mock_client.complete.return_value = {"macrocycle_summary": "s", "learning_updates": []}
        coach_service.data_bootstrap(
            from_date_str="2026-06-01", until_date_str="2026-06-07", no_pull=True
        )
        eid = test_db.get_constraints()[0]["id"]
        test_db.update_constraint(eid, description="changed")
        # Confirm + recompute (bootstrap already ran).
        with patch("builtins.input", return_value="y"):
            coach_service.data_bootstrap(
                from_date_str="2026-06-01", until_date_str="2026-06-07", no_pull=True
            )
        self.assertEqual(mock_client.complete.call_count, 2)  # not reused

    @patch("trainmate.coach.engine.openrouter_client")
    def test_out_of_window_constraint_does_not_invalidate_the_cache(self, mock_client):
        """Constraints are fetched windowed, so one lying entirely outside [from,until]
        never reaches the fingerprint and the reconstruction stays reusable
        (DESIGN_richer_analysis_evidence.md §5, §8)."""
        self._seed_week()
        mock_client.complete.return_value = {"macrocycle_summary": "s", "learning_updates": []}
        coach_service.data_bootstrap(
            from_date_str="2026-06-01", until_date_str="2026-06-07", no_pull=True
        )
        test_db.add_constraint(
            title="Later trip", start_date="2026-07-01", end_date="2026-07-05",
            description="out of window",
        )
        with patch("builtins.input", return_value="y"):
            coach_service.data_bootstrap(
                from_date_str="2026-06-01", until_date_str="2026-06-07", no_pull=True
            )
        self.assertEqual(mock_client.complete.call_count, 1)  # cached reconstruction reused

    @patch("trainmate.coach.engine.openrouter_client")
    def test_out_of_window_signal_invalidates_the_cache(self, mock_client):
        """`signal_days` is built full-history, so a signal logged OUTSIDE [from,until]
        still changes the prompt — and must therefore shift the fingerprint
        (DESIGN_quantitative_signal_impact.md §8)."""
        self._seed_week()
        mock_client.complete.return_value = {"macrocycle_summary": "s", "learning_updates": []}
        coach_service.data_bootstrap(
            from_date_str="2026-06-01", until_date_str="2026-06-07", no_pull=True
        )
        # Two months before the analysis window: invisible to the windowed evidence, but
        # it adds a whole episode to the signal_days section the LLM is shown.
        test_db.upsert_daily_signal_by_event(
            "evt-old", "2026-04-02", "alcohol", value=4.0, text="Alcohol: 4 drinks"
        )
        with patch("builtins.input", return_value="y"):
            coach_service.data_bootstrap(
                from_date_str="2026-06-01", until_date_str="2026-06-07", no_pull=True
            )
        self.assertEqual(mock_client.complete.call_count, 2)  # not reused
        self.assertIn("2026-04-02", mock_client.complete.call_args[0][1])


if __name__ == "__main__":
    unittest.main()
