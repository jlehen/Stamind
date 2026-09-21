"""Which evidence one `data reflect` run reads: the watermark it starts after
and advances, the horizon that chooses the question, and the snap to the
last completed week that makes a daily invocation harmless.
"""
import os
import unittest
from datetime import datetime
from unittest.mock import patch

from tests.helpers import clear_all_tables, rebind_test_db
from trainmate.db import Database
from tests import test_db_path

TEST_DB_PATH = test_db_path("test_analysis_window.db")
test_db = Database(db_path=TEST_DB_PATH)
rebind_test_db(test_db)

from trainmate.coach.service import coach_service


class TestReflectWatermark(unittest.TestCase):
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

    @patch("trainmate.coach.engine.openrouter_client")
    def test_bootstrap_establishes_watermark(self, mock_client):
        mock_client.complete.return_value = {"macrocycle_summary": "s", "learning_updates": []}
        coach_service.data_bootstrap(
            from_date_str="2026-06-01", until_date_str="2026-06-07", no_pull=True
        )
        wm = test_db.get_sync_state("reflect")
        self.assertEqual(wm["through_date"], "2026-06-07")

    @patch("trainmate.coach.engine.openrouter_client")
    def test_reflect_starts_after_watermark(self, mock_client):
        """Reflect ingests only evidence newer than the watermark, so overlapping history
        is never re-counted (the source of confidence converging to 'established')."""
        test_db.set_sync_state(
            through_date="2026-06-07", last_pull_utc="2026-06-07T00:00:00+00:00", key="reflect"
        )
        mock_client.complete.return_value = {"macrocycle_summary": "s", "learning_updates": []}
        coach_service.data_reflect(until_date_str="2026-06-21", no_pull=True)
        # Window starts the day after the watermark: Monday of 2026-06-08's week is 2026-06-08.
        summaries = mock_client.complete.call_args[0][1]
        self.assertIn("2026-06-08", summaries)
        self.assertNotIn("2026-06-01", summaries)
        # Watermark advanced to the new through-date.
        self.assertEqual(test_db.get_sync_state("reflect")["through_date"], "2026-06-21")

    @patch("trainmate.coach.engine.openrouter_client")
    def test_reflect_no_new_evidence_skips_llm(self, mock_client):
        """With nothing new since the watermark, reflect makes no LLM call."""
        test_db.set_sync_state(
            through_date="2026-06-21", last_pull_utc="2026-06-21T00:00:00+00:00", key="reflect"
        )
        result = coach_service.data_reflect(until_date_str="2026-06-21", no_pull=True)
        self.assertEqual(result, {})
        mock_client.complete.assert_not_called()

    @patch("trainmate.coach.engine.openrouter_client")
    def test_short_horizon_asks_for_response_not_cycles(self, mock_client):
        """Horizon selects the question, not just the window: a few weeks cannot support a
        periodization claim, so reflect is never asked for one (§10.3)."""
        test_db.set_sync_state(
            through_date="2026-06-07", last_pull_utc="2026-06-07T00:00:00+00:00", key="reflect"
        )
        mock_client.complete.return_value = {"macrocycle_summary": "s", "learning_updates": []}
        coach_service.data_reflect(until_date_str="2026-06-21", no_pull=True)
        prompt = mock_client.complete.call_args[0][0]
        self.assertNotIn("inferred_macrocycle", prompt)
        self.assertNotIn("inferred_mesocycles", prompt)
        self.assertIn("do not infer macro/mesocycles", prompt)
        # The half reflect exists for is untouched.
        self.assertIn("physiological_insights", prompt)
        self.assertIn("learning_updates", prompt)

    @patch("trainmate.coach.engine.openrouter_client")
    def test_long_horizon_still_asks_for_cycles(self, mock_client):
        mock_client.complete.return_value = {"macrocycle_summary": "s", "learning_updates": []}
        coach_service.data_bootstrap(
            from_date_str="2026-06-01", until_date_str="2026-06-21", no_pull=True
        )
        prompt = mock_client.complete.call_args[0][0]
        self.assertIn("inferred_macrocycle", prompt)
        self.assertIn("inferred_mesocycles", prompt)
        self.assertIn("physiological_insights", prompt)

    @patch("trainmate.coach.service.analysis._today_date")
    @patch("trainmate.coach.engine.openrouter_client")
    def test_reflect_ends_on_the_last_completed_week(self, mock_client, mock_today):
        """Weeks are the unit of evidence, so a window may not end mid-week — a part-week
        would otherwise be cited as a whole one and could never be topped up (§10.4)."""
        mock_today.return_value = datetime(2026, 6, 24).date()      # a Wednesday
        test_db.set_sync_state(
            through_date="2026-06-14", last_pull_utc="2026-06-14T00:00:00+00:00", key="reflect"
        )
        mock_client.complete.return_value = {"macrocycle_summary": "s", "learning_updates": []}
        coach_service.data_reflect(no_pull=True)
        # Through Sunday 06-21, not Wednesday 06-24.
        self.assertEqual(test_db.get_sync_state("reflect")["through_date"], "2026-06-21")

    @patch("trainmate.coach.service.analysis._today_date")
    @patch("trainmate.coach.engine.openrouter_client")
    def test_reflect_midweek_with_no_completed_week_is_free(self, mock_client, mock_today):
        """What makes a daily invocation harmless: no completed week, no LLM call."""
        mock_today.return_value = datetime(2026, 6, 24).date()      # Wednesday
        test_db.set_sync_state(
            through_date="2026-06-21", last_pull_utc="2026-06-21T00:00:00+00:00", key="reflect"
        )
        result = coach_service.data_reflect(no_pull=True)
        self.assertEqual(result, {})
        mock_client.complete.assert_not_called()

    @patch("trainmate.coach.service.analysis._today_date")
    @patch("trainmate.coach.engine.openrouter_client")
    def test_an_explicit_end_date_is_taken_as_given(self, mock_client, mock_today):
        """The snap is a default, not a policy: a named end date is the caller's call."""
        mock_today.return_value = datetime(2026, 6, 24).date()
        test_db.set_sync_state(
            through_date="2026-06-14", last_pull_utc="2026-06-14T00:00:00+00:00", key="reflect"
        )
        mock_client.complete.return_value = {"macrocycle_summary": "s", "learning_updates": []}
        coach_service.data_reflect(until_date_str="2026-06-24", no_pull=True)
        self.assertEqual(test_db.get_sync_state("reflect")["through_date"], "2026-06-24")

    @patch("trainmate.coach.engine.openrouter_client")
    def test_reflect_watermark_never_rewinds(self, mock_client):
        """A back-dated explicit window must not rewind the watermark."""
        test_db.set_sync_state(
            through_date="2026-06-21", last_pull_utc="2026-06-21T00:00:00+00:00", key="reflect"
        )
        mock_client.complete.return_value = {"macrocycle_summary": "s", "learning_updates": []}
        coach_service.data_reflect(
            from_date_str="2026-06-01", until_date_str="2026-06-07", no_pull=True
        )
        self.assertEqual(test_db.get_sync_state("reflect")["through_date"], "2026-06-21")


if __name__ == "__main__":
    unittest.main()
