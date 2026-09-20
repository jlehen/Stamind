"""The confidence model behind a coach learning (trainmate/learning_confidence.py).

Pure rules over an evidence count and a timestamp: no database, no model. They lived
in `db/learnings.py` and were tested there, which is how the storage layer came to be
the place that decided what "established" means.
"""
import unittest
from datetime import datetime, timedelta, timezone

from trainmate.learning_confidence import (
    RETIRE_PROPOSAL, confidence_rank, derive_confidence, learning_is_dormant,
    normalize_sports, step_down, valid_confidence,
)


class TestTheConfidenceModel(unittest.TestCase):
    def test_derive_confidence_pure_function(self):
        # Defaults: moderate at 3 net weeks, established at 5.
        self.assertEqual(derive_confidence(0, 0), "tentative")   # no basis -> floor
        self.assertEqual(derive_confidence(2, 0), "tentative")
        self.assertEqual(derive_confidence(3, 0), "moderate")
        self.assertEqual(derive_confidence(5, 0), "established")
        self.assertEqual(derive_confidence(6, 1), "established")  # net 5
        # Contradiction nets down; only contradiction (not an empty basis) proposes retire.
        self.assertEqual(derive_confidence(2, 2), RETIRE_PROPOSAL)  # net 0, contradicted
        self.assertEqual(derive_confidence(5, 3), "tentative")      # net 2
        self.assertEqual(confidence_rank("tentative"), 1)
        self.assertEqual(step_down("established"), "moderate")
        self.assertEqual(step_down("tentative"), RETIRE_PROPOSAL)

    def test_learning_helpers(self):
        self.assertEqual(normalize_sports(None), "general")
        self.assertEqual(normalize_sports(""), "general")
        self.assertEqual(normalize_sports("Running, Cycling"), "running,cycling")
        self.assertEqual(normalize_sports(["Running", " Hiking "]), "running,hiking")

        self.assertEqual(valid_confidence("established"), "established")
        self.assertIsNone(valid_confidence("bogus"))

        base = datetime.now(timezone.utc)
        # Higher confidence survives longer: established budget is 180 days.
        fresh = {"confidence": "established",
                 "last_reinforced_at": (base - timedelta(days=100)).isoformat()}
        stale = {"confidence": "established",
                 "last_reinforced_at": (base - timedelta(days=200)).isoformat()}
        self.assertFalse(learning_is_dormant(fresh, base))
        self.assertTrue(learning_is_dormant(stale, base))


if __name__ == "__main__":
    unittest.main()
