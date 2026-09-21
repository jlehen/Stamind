"""The sessions the athlete has already been told about, when
`workout generate` rewrites the horizon under them.
"""
import os
import unittest
from datetime import datetime, timedelta, timezone
from unittest.mock import patch

from tests.helpers import clear_all_tables, rebind_test_db, save_workout
from tests import test_db_path

TEST_DB_PATH = test_db_path("test_periodization_standing.db")


def _days_out(n: int) -> str:
    return (datetime.now(timezone.utc).date() + timedelta(days=n)).isoformat()


# Fixtures ride on today rather than on fixed dates; test_periodization.py says why.

from stamind.db import Database

test_db = Database(db_path=TEST_DB_PATH)
rebind_test_db(test_db)

from stamind.coach.service import coach_service


class TestTheStandingSessionsReachGeneration(unittest.TestCase):
    """`workout generate` rewrites the horizon, so the sessions the athlete has already
    been told about reach the prompt and the week planner must answer for each one
    (DESIGN_plan_change_continuity.md §4). Past the window they do not: out there the
    plan is the plan, and the run rebuilds freely."""

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
        obj_id = test_db.add_objective(
            title="Autumn Marathon", target_date=_days_out(90), sport_type="running",
        )
        test_db.save_macrocycle(
            objective_id=obj_id, strategy="build", goals_hash="g", constraints_hash="c",
            mesocycles=[{"name": "Base", "start_date": _days_out(0),
                         "end_date": _days_out(60), "focus": "aerobic"}],
        )

    # --- fixtures -----------------------------------------------------------------

    @staticmethod
    def _window(days):
        """The commitment window, as the operator's setting rather than a constant."""
        test_db.set_setting("workout_commitment_days", str(days))

    @staticmethod
    def _eased(date_str, **extra):
        """A session whose live numbers are the reduced form of an earlier prescription —
        `original_*` is what makes the helper write the adapt revision over a generate
        one, which is what the tally reads."""
        save_workout(
            test_db, date=date_str, sport_type="cycling", title="Easy Z2 Spin",
            description="[Easy Z2 Spin]\n40 min ERG-locked, no surges.",
            duration_minutes=40, rpe=3, tss=26,
            planned_zone_currency="power", planned_zone_sec=[600, 1800, 0, 0, 0, 0, 0],
            original_duration_minutes=90, original_rpe=7, original_tss=110,
            modification_reason="Cut to easy Z2 to shed intensity.", **extra,
        )

    @staticmethod
    def _untouched(date_str, **extra):
        save_workout(
            test_db, date=date_str, sport_type="running", title="Steady Run",
            description="[Steady Run]\n50 min", duration_minutes=50, rpe=5, tss=45,
            **extra,
        )

    @staticmethod
    def _keep(date_str, sport="cycling"):
        return {"date": date_str, "sport_type": sport, "keep": True}

    @staticmethod
    def _written(date_str, sport="running", title="Steady Run"):
        return {
            "date": date_str, "sport_type": sport, "title": title,
            "description": f"[{title}]\n50 min", "duration_minutes": 50,
            "rpe": 5, "tss": 45,
        }

    def _run(self, *entries, **response):
        """`workout generate` end to end against a fixed model response, as the CLI does
        on a `y`. Returns the proposal and the user content the model was sent."""
        with patch("stamind.runtime.calendar_syncer"), \
                patch("stamind.coach.engine.openrouter_client") as client:
            client.complete.return_value = {
                "reasoning": "why", "workouts": list(entries), **response,
            }
            proposal = coach_service.workout_generate()
            user = client.complete.call_args.args[1]
            coach_service.workout_generate_apply(proposal)
        return proposal, user

    # --- what reaches the prompt --------------------------------------------------

    def test_a_standing_session_reaches_the_prompt_with_its_first_form(self):
        self._eased(_days_out(3))
        _proposal, user = self._run()
        self.assertIn("## SESSIONS ALREADY STANDING", user)
        self.assertIn("Easy Z2 Spin", user)
        self.assertIn("first prescribed as 90m, RPE 7, TSS 110", user)
        self.assertIn("Cut to easy Z2 to shed intensity.", user)

    def test_the_intensity_target_reaches_the_prompt(self):
        """The zone columns are what let the model weigh a standing day against the week
        it is writing around it; duration and TSS cannot."""
        self._eased(_days_out(3))
        _proposal, user = self._run()
        self.assertIn("Target: ~10min recovery, ~30min endurance", user)

    def test_a_committed_session_ships_its_description(self):
        """Inside the window a revision should be minimal rather than re-invented, which
        needs the prose the session already carries (§4.6)."""
        self._eased(_days_out(3))
        _proposal, user = self._run()
        self.assertIn("ERG-locked, no surges.", user)

    def test_a_session_past_the_window_is_not_a_standing_session(self):
        """Out there the plan is the plan and the run rebuilds freely, so the week planner is
        not asked to account for the day (§4.2)."""
        self._window(3)
        self._eased(_days_out(1))
        self._untouched(_days_out(10))
        _proposal, user = self._run()
        self.assertIn("Easy Z2 Spin", user)
        self.assertNotIn("Steady Run", user)

    def test_an_empty_window_carries_nothing(self):
        """`0` protects nothing: today's session may change too (§4.1)."""
        self._window(0)
        self._eased(_days_out(3))
        _proposal, user = self._run()
        self.assertNotIn("SESSIONS ALREADY STANDING", user)

    def test_a_cancelled_session_is_not_a_standing_session(self):
        """A cancelled session has nothing standing to answer for."""
        self._eased(_days_out(3), removed=True, removed_reason="travelling")
        _proposal, user = self._run()
        self.assertNotIn("SESSIONS ALREADY STANDING", user)

    # --- what a KEEP does ---------------------------------------------------------

    def test_a_kept_session_is_left_exactly_as_it_stands(self):
        """The point of the action: no revision, so the prescription, the Calendar event
        and — via §7's tally — the session's standing as already-eased all survive. A
        rewrite that merely reproduced the load would reset the tally and the NEXT
        regeneration would restore it to full."""
        self._eased(_days_out(3))
        before = test_db.get_workout(_days_out(3), "cycling")
        self._run(self._keep(_days_out(3)))
        after = test_db.get_workout(_days_out(3), "cycling")
        self.assertEqual(after["revision_id"], before["revision_id"])
        self.assertEqual(after["title"], "Easy Z2 Spin")
        self.assertEqual(after["duration_minutes"], 40)
        self.assertEqual(after["planned_zone2_sec"], 1800)
        self.assertEqual(after["adaptation_count"], 1)

    def test_a_kept_session_survives_a_second_regeneration(self):
        """The durability the action buys, asserted rather than reasoned about."""
        self._eased(_days_out(3))
        before = test_db.get_workout(_days_out(3), "cycling")
        self._run(self._keep(_days_out(3)))
        _proposal, user = self._run(self._keep(_days_out(3)))
        self.assertIn("Easy Z2 Spin", user, "still standing on the second pass")
        after = test_db.get_workout(_days_out(3), "cycling")
        self.assertEqual(after["revision_id"], before["revision_id"])

    def test_a_session_the_coach_never_named_is_kept(self):
        """Silence is the ordinary way a JSON-mode model fails, and a cancellation has to
        be said (§4.5). The preview says the coach did not name it."""
        self._eased(_days_out(3))
        proposal, _user = self._run(self._written(_days_out(5)))
        after = test_db.get_workout(_days_out(3), "cycling")
        self.assertFalse(after["removed"])
        line = next(l for l in proposal.standing if l.date == _days_out(3))
        self.assertEqual(line.outcome, "kept")
        self.assertFalse(line.mentioned)

    def test_the_days_past_the_window_are_still_rewritten(self):
        """The window claims the near days, not the horizon."""
        self._window(3)
        self._eased(_days_out(1))
        self._untouched(_days_out(10))
        self._run(self._keep(_days_out(1)), self._written(_days_out(11)))
        self.assertTrue(test_db.get_workout(_days_out(10), "running")["removed"])
        self.assertIsNotNone(test_db.get_workout(_days_out(11), "running"))

    def test_writing_the_day_out_beats_keeping_it(self):
        """The model may decide the easing has served its purpose; an explicit session
        for the same slot is that decision, and it wins."""
        self._eased(_days_out(3))
        before = test_db.get_workout(_days_out(3), "cycling")
        self._run(
            self._keep(_days_out(3)),
            self._written(_days_out(3), sport="cycling", title="Threshold 2x20"),
        )
        after = test_db.get_workout(_days_out(3), "cycling")
        self.assertEqual(after["title"], "Threshold 2x20")
        self.assertNotEqual(after["revision_id"], before["revision_id"])

    def test_a_keep_naming_a_slot_nothing_stands_in_is_dropped(self):
        """It claims a slot nothing would then write. Dropping it archives the day like
        any other the new sessions do not fill — a silently blank day is the worse failure."""
        self._eased(_days_out(3))
        self._run(self._keep(_days_out(4), sport="running"))
        self.assertIsNone(test_db.get_workout(_days_out(4), "running"))

    def test_a_forced_rest_window_still_overrides_a_keep(self):
        """The deterministic rest pass runs after the answers are resolved, so a barred
        date is barred whatever the model asked to keep (DESIGN_constraints.md §6). The
        rest row continues the session it replaces, so the day keeps one event (§5.5)."""
        self._eased(_days_out(3))
        cycling_before = test_db.get_workout(_days_out(3), "cycling")
        test_db.add_constraint(
            title="Travel", start_date=_days_out(3), end_date=_days_out(3), rest=1,
        )
        self._run(self._keep(_days_out(3)))
        live = test_db.get_workouts(start_date=_days_out(3), end_date=_days_out(3))
        # The lineage now speaks through the rest row, so the day holds one session and
        # the ride's void is history rather than a second live row.
        self.assertEqual([w["sport_type"] for w in live], ["rest"])
        self.assertEqual(live[0]["id"], cycling_before["id"], "same lineage, one event")
        self.assertIn("Travel", live[0]["modification_reason"] or "")


if __name__ == "__main__":
    unittest.main()
