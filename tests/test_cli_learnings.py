import os
import unittest

from tests.helpers import clear_all_tables, run_cli, rebind_test_db
from tests import test_db_path

TEST_DB_PATH = test_db_path("test_trainmate_cli_learnings.db")

from trainmate.db import Database
import trainmate.db
import trainmate_cli

test_db = Database(db_path=TEST_DB_PATH)
rebind_test_db(test_db)


class TestCliLearnings(unittest.TestCase):
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

    def run_cli(self, args, input_value="n"):
        return run_cli(args, input_value)

    def _propose_demotion(self, learning_id: int, target: str) -> None:
        """Arms the pending downgrade that `demote`/`keep` resolve."""
        with test_db._get_connection() as conn:
            conn.execute(
                "UPDATE coach_learnings SET proposed_confidence=? WHERE id=?",
                (target, learning_id),
            )
            conn.commit()

    def test_learning_edit_echoes_list_line(self):
        lid = test_db.add_learning(
            "Runs better on 8h sleep", sports="running", confidence="moderate"
        )
        exit_code, stdout, _ = self.run_cli(
            ["learnings", "edit", str(lid), "Runs much better on 8h sleep"]
        )
        self.assertEqual(exit_code, 0)
        self.assertIn(f"[{lid}|running|moderate]", stdout)
        self.assertIn("Runs much better on 8h sleep", stdout)
        self.assertIn("Learning updated successfully", stdout)

    def test_learning_demote_echoes_new_confidence(self):
        lid = test_db.add_learning(
            "Runs better on 8h sleep", sports="running", confidence="moderate"
        )
        self._propose_demotion(lid, "tentative")

        exit_code, stdout, _ = self.run_cli(["learnings", "demote", str(lid)])
        self.assertEqual(exit_code, 0)
        # The echo carries the post-demotion level, not the one it was called on.
        self.assertIn(f"[{lid}|running|tentative]", stdout)
        self.assertIn("Learning demoted to 'tentative'", stdout)

    def test_learning_keep_echoes_without_pending_marker(self):
        lid = test_db.add_learning(
            "Runs better on 8h sleep", sports="running", confidence="moderate"
        )
        self._propose_demotion(lid, "tentative")

        exit_code, stdout, _ = self.run_cli(["learnings", "keep", str(lid)])
        self.assertEqual(exit_code, 0)
        self.assertIn(f"[{lid}|running|moderate]", stdout)
        # The dismissed proposal is gone from the echoed line.
        self.assertNotIn("proposed demotion", stdout)
        self.assertIn("Learning kept; pending demotion dismissed", stdout)

    def test_a_retirement_archives_and_restore_brings_it_back(self):
        """Retiring archives the learning (DESIGN_learning_doubt_nudge.md §6)."""
        lid = test_db.add_learning(
            "Runs better on 8h sleep", sports="running", confidence="tentative"
        )
        self._propose_demotion(lid, "retire")

        exit_code, stdout, _ = self.run_cli(["learnings", "demote", str(lid)])
        self.assertEqual(exit_code, 0)
        self.assertIn(f"Learning with ID {lid} retired and archived", stdout)

        _, listed, _ = self.run_cli(["learnings", "list"])
        self.assertNotIn("Runs better on 8h sleep", listed)
        _, listed, _ = self.run_cli(["learnings", "list", "--all"])
        self.assertIn("Runs better on 8h sleep (archived)", listed)
        _, shown, _ = self.run_cli(["learnings", "show", str(lid)])
        self.assertIn("(archived)", shown)

        exit_code, stdout, _ = self.run_cli(["learnings", "restore", str(lid)])
        self.assertEqual(exit_code, 0)
        self.assertIn(f"[{lid}|running|tentative]", stdout)
        self.assertFalse(test_db.get_learning(lid)["archived"])

    def test_rm_archives_and_purge_deletes_for_good(self):
        lid = test_db.add_learning("Runs better on 8h sleep")
        exit_code, stdout, _ = self.run_cli(["learnings", "rm", str(lid)])
        self.assertEqual(exit_code, 0)
        self.assertIn(f"Learning with ID {lid} archived", stdout)
        self.assertTrue(test_db.get_learning(lid)["archived"])

        exit_code, _, _ = self.run_cli(["learnings", "rm", str(lid), "--purge"])
        self.assertEqual(exit_code, 0)
        self.assertIsNone(test_db.get_learning(lid))
        self.assertEqual(test_db.get_learning_evidence(lid), [])

    def test_show_prints_what_went_against_it(self):
        lid = test_db.add_learning("Absorbs doubles", sports="cycling", confidence="moderate")
        test_db.apply_learning_deltas([{
            "op": "contradict", "id": lid, "evidence": ["2026-09-07"],
            "reason": "The second session was cut short.",
        }])
        _, stdout, _ = self.run_cli(["learnings", "show", str(lid)])
        self.assertIn("contradicting (1 wk)", stdout)
        self.assertIn("2026-09-07: The second session was cut short.", stdout)


class TestLearningTuningKnobsAreDocumented(unittest.TestCase):
    """`config_template_full.yaml` is the discovery surface for the learning knobs
    (DESIGN_evidence_based_confidence.md §3): a loader with no commented example is
    invisible to the user it exists for. The short `config_template.yaml` carries only
    the keys an install must fill in, so the knobs are documented in the full one."""

    TEMPLATE = os.path.join(
        os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
        "config_template_full.yaml",
    )

    def test_both_learning_knobs_have_a_commented_example(self):
        with open(self.TEMPLATE) as fh:
            text = fh.read()
        for key in ("learning_staleness_days", "learning_confidence_thresholds"):
            self.assertIn(f"#{key}:", text, f"{key} has no commented example")


if __name__ == "__main__":
    unittest.main()
