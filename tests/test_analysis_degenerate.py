"""A reflect response that parses as JSON but carries nothing the app reads.
"""
import os
import unittest
from unittest.mock import patch

from tests.helpers import clear_all_tables, rebind_test_db
from trainmate.db import Database
from tests import test_db_path

TEST_DB_PATH = test_db_path("test_analysis_degenerate.db")
test_db = Database(db_path=TEST_DB_PATH)
rebind_test_db(test_db)

from trainmate.coach.service import coach_service


class TestDegenerateAnalysisResponse(unittest.TestCase):
    """A response that parses as JSON but carries nothing the app reads
    (DESIGN_backward_evaluation.md §13).

    Drawn from the 2026-08-18 model comparison: moonshotai/kimi-k3 prefixed every NESTED
    key with '>', so `{">overall_focus": ...}` parsed cleanly and every `.get()` missed —
    empty report mesocycles, zero learnings, and a watermark that moved as if history had been
    read.
    """

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

    # The kimi-k3 shape: top-level keys intact, every nested key prefixed.
    MANGLED = {
        "macrocycle_summary": "",
        "inferred_macrocycle": {
            ">overall_focus": "Summer aerobic base", ">start_date": "2026-06-01",
        },
        "inferred_mesocycles": [{">name": "Transitional Base", ">average_weekly_tss": 260.2}],
        "physiological_insights": [],
        "learning_updates": [
            {">op": "add", ">text": "Absorbs volume well", ">evidence": ["2026-06-01"]},
        ],
    }

    @patch("trainmate.coach.engine.openrouter_client")
    def test_an_unreadable_response_fails_instead_of_saving_emptiness(self, mock_client):
        mock_client.complete.return_value = dict(self.MANGLED)

        with self.assertRaises(ValueError) as caught:
            coach_service.data_bootstrap(
                from_date_str="2026-06-01", until_date_str="2026-06-07"
            )
        self.assertIn("none of the requested content", str(caught.exception))

        # Nothing persisted: no cache to pin the emptiness behind the fingerprint, no
        # watermark, and no bootstrap record to gate the next run behind a prompt.
        self.assertIsNone(test_db.get_analysis_cache("long"))
        self.assertIsNone(test_db.get_sync_state("reflect"))
        self.assertIsNone(test_db.get_sync_state("bootstrap"))
        self.assertEqual(test_db.get_learnings(), [])

    @patch("trainmate.coach.engine.openrouter_client")
    def test_a_failed_bootstrap_leaves_the_next_one_free_to_retry(self, mock_client):
        """No bootstrap record means the retry is not gated behind the repeat prompt, and
        no cache means it actually reaches the LLM."""
        mock_client.complete.return_value = dict(self.MANGLED)
        with self.assertRaises(ValueError):
            coach_service.data_bootstrap(
                from_date_str="2026-06-01", until_date_str="2026-06-07"
            )

        mock_client.complete.return_value = {
            "macrocycle_summary": "A real reconstruction",
            "learning_updates": [{"op": "add", "text": "Absorbs volume well"}],
        }
        result = coach_service.data_bootstrap(
            from_date_str="2026-06-01", until_date_str="2026-06-07"
        )
        self.assertEqual(mock_client.complete.call_count, 2)
        self.assertEqual(result["macrocycle_summary"], "A real reconstruction")
        self.assertEqual(len(test_db.get_learnings()), 1)

    @patch("trainmate.coach.engine.openrouter_client")
    def test_a_partly_readable_response_warns_and_still_saves(self, mock_client):
        """One good part is a result worth keeping — but the unreadable ones are named
        rather than left to render as blank sections."""
        mock_client.complete.return_value = {
            "macrocycle_summary": "A real reconstruction",
            "inferred_macrocycle": {">overall_focus": "Summer aerobic base"},
            "inferred_mesocycles": [{">name": "Transitional Base"}],
            "learning_updates": [],
        }
        with patch("builtins.print") as mock_print:
            coach_service.data_bootstrap(
                from_date_str="2026-06-01", until_date_str="2026-06-07"
            )
        printed = " ".join(str(c.args[0]) for c in mock_print.call_args_list if c.args)
        self.assertIn("unreadable", printed)
        self.assertIn("macrocycle", printed)
        self.assertIn("mesocycles", printed)
        self.assertIsNotNone(test_db.get_analysis_cache("long"))

    @patch("trainmate.coach.engine.openrouter_client")
    def test_deltas_the_app_cannot_read_are_reported_not_silently_dropped(self, mock_client):
        mock_client.complete.return_value = {
            "macrocycle_summary": "A real reconstruction",
            "learning_updates": [
                {">op": "add", ">text": "Absorbs volume well"},   # mangled keys
                {"op": "reinforce", "id": 999},                    # hallucinated id
                {"op": "add", "text": "Recovers fast"},            # the one good delta
            ],
        }
        with patch("builtins.print") as mock_print:
            coach_service.data_bootstrap(
                from_date_str="2026-06-01", until_date_str="2026-06-07"
            )
        printed = " ".join(str(c.args[0]) for c in mock_print.call_args_list if c.args)
        self.assertIn("2 coach-learning updates", printed)
        self.assertEqual(len(test_db.get_learnings()), 1)

    @patch("trainmate.coach.engine.openrouter_client")
    def test_a_bootstrap_that_seeds_nothing_says_so(self, mock_client):
        """The gpt-5.6-terra case: a clean reconstruction with `learning_updates: []`. The
        run succeeded, so only naming the empty outcome stops the next command's cold-start
        nudge from reading as if bootstrap had never run."""
        mock_client.complete.return_value = {
            "macrocycle_summary": "A real reconstruction", "learning_updates": [],
        }
        with patch("builtins.print") as mock_print:
            coach_service.data_bootstrap(
                from_date_str="2026-06-01", until_date_str="2026-06-07"
            )
        printed = " ".join(str(c.args[0]) for c in mock_print.call_args_list if c.args)
        self.assertIn("no active coach observations on record", printed)

    @patch("trainmate.coach.engine.openrouter_client")
    def test_the_cold_start_nudge_stops_pointing_at_a_command_already_run(self, mock_client):
        mock_client.complete.return_value = {
            "macrocycle_summary": "A real reconstruction", "learning_updates": [],
        }
        coach_service.data_bootstrap(
            from_date_str="2026-06-01", until_date_str="2026-06-07"
        )
        with patch("builtins.print") as mock_print:
            coach_service._maybe_nudge_bootstrap()
        printed = " ".join(str(c.args[0]) for c in mock_print.call_args_list if c.args)
        self.assertIn("bootstrap ran on", printed)
        self.assertIn("--force", printed)

    def test_the_cold_start_nudge_is_unchanged_before_any_bootstrap(self):
        with patch("builtins.print") as mock_print:
            coach_service._maybe_nudge_bootstrap()
        printed = " ".join(str(c.args[0]) for c in mock_print.call_args_list if c.args)
        self.assertIn("No coach learnings yet. Run", printed)
        self.assertNotIn("--force", printed)


if __name__ == "__main__":
    unittest.main()
