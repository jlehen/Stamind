"""`data reflect`: the run that reads past training into a reconstruction and
the learnings it writes.

The window a run reads is `test_analysis_window.py`; a reply that carries
nothing is `test_analysis_degenerate.py`; the weekly evidence the prompt is
built from is `test_analysis_evidence.py`; and the reconstruction that then
reaches `plan generate` is `test_analysis_prior_training.py`.
"""
import os
import unittest
from unittest.mock import patch

from tests.helpers import clear_all_tables, rebind_test_db
from stamind.db import Database
from tests import test_db_path

TEST_DB_PATH = test_db_path("test_stamind_analysis.db")
test_db = Database(db_path=TEST_DB_PATH)
rebind_test_db(test_db)

from stamind.coach.service import coach_service


class TestWorkoutAnalysis(unittest.TestCase):
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

    @patch("stamind.coach.engine.openrouter_client")
    def test_date_resolution_with_preceding_goal(self, mock_client):
        # Earliest objective: 2026-07-01
        test_db.add_objective(
            title="Goal A", target_date="2026-07-01",
            sport_type="running", status="active"
        )
        # Preceding objective: 2026-06-01
        test_db.add_objective(
            title="Goal Preceding", target_date="2026-06-01",
            sport_type="running", status="active"
        )

        mock_client.complete.return_value = {
            "macrocycle_summary": "Analysis summary",
            "inferred_macrocycle": {"overall_focus": "aerobic base"},
            "inferred_mesocycles": [],
            "physiological_insights": [],
            "learning_updates": []
        }

        # Analyze workouts without explicit range -> should start on 2026-06-02 (day after Goal Preceding)
        result = coach_service.data_bootstrap(until_date_str="2026-07-01")
        self.assertIsNotNone(result)

        # Inspect the start date passed to complete call
        summaries = mock_client.complete.call_args[0][1]
        self.assertIn("2026-06-01", summaries) # Monday of that week is 2026-06-01 (Tuesday 2026-06-02 is in it)

    @patch("builtins.input", return_value="y")
    @patch("stamind.coach.engine.openrouter_client")
    def test_date_resolution_explicit_window(self, mock_client, _mock_input):
        """The service takes a resolved window; turning '10d'/'4w' into one is the CLI
        selector's job (tests/test_cli_selectors.py)."""
        mock_client.complete.return_value = {
            "macrocycle_summary": "Analysis summary"
        }

        # The window a `-d 10d` ending 2026-06-15 resolves to.
        coach_service.data_bootstrap(
            from_date_str="2026-06-06", until_date_str="2026-06-15"
        )
        # The Monday of the start week is 2026-06-01.
        summaries = mock_client.complete.call_args[0][1]
        self.assertIn("2026-06-01", summaries)

        # The window a `-d 4w` ending 2026-06-15 resolves to.
        coach_service.data_bootstrap(
            from_date_str="2026-05-19", until_date_str="2026-06-15"
        )
        # The Monday of the start week is 2026-05-18.
        summaries = mock_client.complete.call_args[0][1]
        self.assertIn("2026-05-18", summaries)

    @patch("stamind.coach.engine.openrouter_client")
    def test_weekly_aggregation_logic(self, mock_client):
        # Setup completed activities in different weeks
        # Week commencing 2026-06-01
        test_db.save_completed_activity(
            activity_id="act_1", date="2026-06-03", start_time="08:00:00",
            activity_name="Base Ride", activity_type="cycling",
            duration_sec=7200.0, distance_km=50.0, elevation_gain_m=300.0,
            avg_hr=130, max_hr=150, rpe=5, tss=90.0,
            zone1_sec=3600, zone2_sec=3600
        )
        # Highlight workout in the same week
        test_db.save_completed_activity(
            activity_id="act_2", date="2026-06-05", start_time="09:00:00",
            activity_name="FTP Race Test", activity_type="running",
            duration_sec=3600.0, distance_km=12.0, elevation_gain_m=50.0,
            avg_hr=165, max_hr=180, rpe=9, tss=130.0,
            zone4_sec=1800, zone5_sec=1800
        )
        # Metric cache for that week
        test_db.save_metric_cache(
            date="2026-06-03", rhr=50, hrv=75, sleep_score=85, stress=20,
            ctl=60.0, atl=68.0, tsb=-8.0
        )

        mock_client.complete.return_value = {
            "macrocycle_summary": "Simulated aggregation summary",
            "learning_updates": [{"op": "add", "text": "Athlete responds well to FTP tests."}]
        }

        # Analyze the week
        result = coach_service.data_bootstrap(
            from_date_str="2026-06-01", until_date_str="2026-06-07"
        )
        self.assertEqual(result["macrocycle_summary"], "Simulated aggregation summary")

        # Verify learnings updated in learnings
        saved_learnings = test_db.get_learnings()
        self.assertEqual(len(saved_learnings), 1)
        self.assertEqual(saved_learnings[0]["text"], "Athlete responds well to FTP tests.")

        # Verify mock complete call payloads
        user_payload = mock_client.complete.call_args[0][1]
        self.assertIn("total_duration_hours\": 3.0", user_payload)
        self.assertIn("total_tss\": 220.0", user_payload)
        self.assertIn("FTP Race Test", user_payload)
        self.assertIn("avg_hrv\": 75.0", user_payload)

    @patch("stamind.coach.engine.openrouter_client")
    def test_bootstrap_derives_confidence_and_validates_weeks(self, mock_client):
        """The analysis flow passes the window's weeks to the merge layer: an observation
        cited across enough distinct in-window weeks is derived 'established', while a cited
        week outside the analysed window is dropped (DESIGN_evidence_based_confidence.md §6)."""
        # Window spans five Mondays: 2026-05-04 .. 2026-06-01 inclusive.
        in_window = ["2026-05-04", "2026-05-11", "2026-05-18", "2026-05-25", "2026-06-01"]
        mock_client.complete.return_value = {
            "macrocycle_summary": "s",
            "learning_updates": [
                {"op": "add", "text": "Strong aerobic base",
                 "evidence": in_window + ["2026-09-07"]},  # last week is outside the window
            ],
        }
        coach_service.data_bootstrap(
            from_date_str="2026-05-04", until_date_str="2026-06-07"
        )
        learning = test_db.get_learnings()[0]
        # Five in-window weeks -> established; the out-of-window week was dropped.
        self.assertEqual(learning["confidence"], "established")
        basis = test_db.get_learning_evidence(learning["id"])
        self.assertEqual(len(basis), 5)
        self.assertNotIn("2026-09-07", {e["week_commencing"] for e in basis})

    def _seed_activity(self):
        test_db.save_completed_activity(
            activity_id="a1", date="2026-06-03", start_time="08:00:00",
            activity_name="Ride", activity_type="cycling",
            duration_sec=3600.0, distance_km=20.0, elevation_gain_m=100.0,
            avg_hr=130, max_hr=150, rpe=5, tss=60.0,
        )

    @patch("builtins.input", return_value="y")
    @patch("stamind.coach.engine.openrouter_client")
    def test_reuse_skips_llm_when_evidence_unchanged(self, mock_client, _mock_input):
        """A second bootstrap over unchanged evidence reuses the cached reconstruction
        instead of calling the LLM again (DESIGN_backward_evaluation.md §5). The repeat
        prompts (bootstrap already ran); confirming proceeds into the reuse path."""
        self._seed_activity()
        mock_client.complete.return_value = {
            "macrocycle_summary": "summary",
            "inferred_macrocycle": {"overall_focus": "base"},
            "learning_updates": [],
        }
        coach_service.data_bootstrap(
            from_date_str="2026-06-01", until_date_str="2026-06-07"
        )
        reused = coach_service.data_bootstrap(
            from_date_str="2026-06-01", until_date_str="2026-06-07"
        )
        self.assertEqual(mock_client.complete.call_count, 1)
        self.assertEqual(reused["macrocycle_summary"], "summary")

    @patch("builtins.input", return_value="n")
    @patch("stamind.coach.engine.openrouter_client")
    def test_repeat_bootstrap_declined_is_a_noop(self, mock_client, _mock_input):
        """A second bootstrap detects the prior run and prompts; declining skips entirely —
        no extra LLM pass, no reflect-watermark reset."""
        self._seed_activity()
        mock_client.complete.return_value = {
            "macrocycle_summary": "summary", "learning_updates": [],
        }
        coach_service.data_bootstrap(
            from_date_str="2026-06-01", until_date_str="2026-06-07"
        )
        reflect_wm = test_db.get_sync_state("reflect")
        result = coach_service.data_bootstrap(
            from_date_str="2026-05-01", until_date_str="2026-05-07"
        )
        self.assertEqual(result, {})
        self.assertEqual(mock_client.complete.call_count, 1)  # second run never reached the LLM
        # The back-dated re-run did not rewind the reflect baseline.
        self.assertEqual(test_db.get_sync_state("reflect"), reflect_wm)

    @patch("builtins.input")
    @patch("stamind.coach.engine.openrouter_client")
    def test_repeat_bootstrap_under_auto_skips_without_prompting(self, mock_client, mock_input):
        """Under --auto (non-interactive) a repeat bootstrap skips silently rather than
        blocking on a prompt that can never be answered."""
        self._seed_activity()
        mock_client.complete.return_value = {
            "macrocycle_summary": "summary", "learning_updates": [],
        }
        coach_service.data_bootstrap(
            from_date_str="2026-06-01", until_date_str="2026-06-07", auto=True
        )
        result = coach_service.data_bootstrap(
            from_date_str="2026-06-01", until_date_str="2026-06-07", auto=True
        )
        self.assertEqual(result, {})
        self.assertEqual(mock_client.complete.call_count, 1)
        mock_input.assert_not_called()

    @patch("stamind.coach.engine.openrouter_client")
    @patch("builtins.input", return_value="s")
    def test_force_recompute_cannot_inflate_via_evidence_dedup(self, mock_input, mock_client):
        """--force recomputes over unchanged evidence, but re-citing an already-counted week
        is a structural no-op: confidence is not ratcheted and recency is not refreshed. The
        per-learning basis owns this (the old suppress_reinforcement flag is gone; §6, §8)."""
        self._seed_activity()  # activity in week commencing 2026-06-01
        mock_client.complete.return_value = {
            "macrocycle_summary": "s",
            "learning_updates": [
                {"op": "add", "text": "Observation", "evidence": ["2026-06-01"]}
            ],
        }
        coach_service.data_bootstrap(
            from_date_str="2026-06-01", until_date_str="2026-06-07"
        )
        lid = test_db.get_learnings()[0]["id"]
        # Backdate recency; a forced re-run re-citing the SAME week must leave it untouched.
        sentinel = "2000-01-01T00:00:00+00:00"
        with test_db._get_connection() as conn:
            conn.execute(
                "UPDATE coach_learnings SET last_reinforced_at=? WHERE id=?",
                (sentinel, lid),
            )
        mock_client.complete.return_value = {
            "macrocycle_summary": "s",
            "learning_updates": [
                {"op": "reinforce", "id": lid, "evidence": ["2026-06-01"]}
            ],
        }
        coach_service.data_bootstrap(
            from_date_str="2026-06-01", until_date_str="2026-06-07", force=True
        )
        self.assertEqual(mock_client.complete.call_count, 2)  # force recomputed
        learning = test_db.get_learnings()[0]
        self.assertEqual(learning["last_reinforced_at"], sentinel)  # no new week -> no refresh
        self.assertEqual(learning["confidence"], "tentative")        # still one week

    @patch("stamind.coach.engine.openrouter_client")
    def test_inspect_only_writes_nothing(self, mock_client):
        """--inspect-only renders but writes neither learnings nor the cache (§9)."""
        self._seed_activity()
        mock_client.complete.return_value = {
            "macrocycle_summary": "s",
            "learning_updates": [{"op": "add", "text": "New obs"}],
        }
        coach_service.data_bootstrap(
            from_date_str="2026-06-01", until_date_str="2026-06-07", inspect_only=True
        )
        self.assertEqual(len(test_db.get_learnings()), 0)
        self.assertIsNone(test_db.get_analysis_cache("long"))

    @patch("stamind.coach.engine.openrouter_client")
    def test_existing_learnings_injected_into_prompt(self, mock_client):
        # Existing observations must appear in the analysis prompt (with ids) so the
        # model can revise/reinforce them instead of only re-adding duplicates.
        lid = test_db.add_learning(
            "Recovers slowly after back-to-back hard days",
            sports="running", confidence="moderate"
        )
        mock_client.complete.return_value = {
            "macrocycle_summary": "x", "learning_updates": []
        }

        coach_service.data_bootstrap(
            from_date_str="2026-06-01", until_date_str="2026-06-07"
        )

        system_prompt = mock_client.complete.call_args[0][0]
        self.assertIn("COACH LEARNINGS", system_prompt)
        self.assertIn(f"[{lid}|running|moderate]", system_prompt)
        self.assertIn("Recovers slowly after back-to-back hard days", system_prompt)


if __name__ == "__main__":
    unittest.main()
