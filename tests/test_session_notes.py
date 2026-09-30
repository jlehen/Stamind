"""What the athlete says about a session (DESIGN_session_notes.md): kept with the session by
`workout adapt -m`, carried by every read of the session, and printed under it in the
prompts and the views.
"""
import os
import unittest
from unittest.mock import patch

from tests import test_db_path
from tests.helpers import clear_all_tables, pin_clock, rebind_test_db, run_cli, save_workout

TEST_DB_PATH = test_db_path("test_session_notes.db")

from stamind.db import Database
from stamind.coach.formatting import format_planned_workouts_detailed
from stamind.coach.proposals import RevisionProposal
from stamind.cli.render.session_lines import simple_day_lines

if os.path.exists(TEST_DB_PATH):
    os.remove(TEST_DB_PATH)
test_db = Database(db_path=TEST_DB_PATH)
rebind_test_db(test_db)


def tearDownModule():
    try:
        os.remove(TEST_DB_PATH)
    except OSError:
        pass


TODAY = "2026-09-30"
WORDS = "This was tough. ERG at 235w,\nstopped at ~12:30 of rep 2."


def _proposal():
    return RevisionProposal(
        reason="Stopping early was sensible.", workouts=[], new_constraints=[],
        range_start=TODAY, range_end="2026-10-04", pairs=(),
    )


class _Case(unittest.TestCase):
    def setUp(self):
        rebind_test_db(test_db)
        clear_all_tables(test_db)
        pin_clock(self, TODAY)

    def notes(self, lineage_id):
        head = test_db.get_lineage_head(lineage_id)
        return [note["text"] for note in head["athlete_notes"]]


class TestTheNoteFollowsTheSession(_Case):
    def test_a_note_is_kept_word_for_word_and_read_with_the_session(self):
        ride = save_workout(test_db, TODAY, "cycling", "Climb-Pace 2x15")
        test_db.add_session_note(ride, WORDS)
        self.assertEqual(self.notes(ride), [WORDS])
        self.assertTrue(test_db.get_workout(TODAY, "cycling")["athlete_notes"][0]["sent_at"])

    def test_a_new_revision_of_the_session_keeps_its_notes(self):
        ride = save_workout(test_db, TODAY, "cycling", "Climb-Pace 2x15")
        test_db.add_session_note(ride, "first")
        test_db.add_session_note(ride, "second")
        save_workout(test_db, TODAY, "cycling", "Climb-Pace 2x15 — trimmed",
                     modification_reason="Eased.")
        head = test_db.get_workout(TODAY, "cycling")
        self.assertEqual(head["id"], ride)
        self.assertEqual([n["text"] for n in head["athlete_notes"]], ["first", "second"])

    def test_a_session_nobody_spoke_about_has_none(self):
        save_workout(test_db, TODAY, "cycling", "Easy Spin")
        self.assertEqual(test_db.get_workout(TODAY, "cycling")["athlete_notes"], [])

    def test_wiping_the_sessions_wipes_their_notes(self):
        ride = save_workout(test_db, TODAY, "cycling", "Climb-Pace 2x15")
        test_db.add_session_note(ride, WORDS)
        test_db.wipe_workouts()
        with test_db._get_connection() as conn:
            self.assertEqual(conn.execute("SELECT COUNT(*) FROM session_notes").fetchone()[0], 0)


@patch("stamind.runtime.garmin")
@patch("stamind.runtime.coach_service")
class TestWorkoutAdaptKeepsTheNote(_Case):
    """The date rule of §3, on the terminal: `--auto`, so the only question asked is which
    session the note is about."""

    def adapt(self, mock_coach, answer="n", words=WORDS):
        mock_coach.workout_adapt.return_value = _proposal()
        return run_cli(["workout", "adapt", "--auto", "-m", words], answer)

    def test_the_days_only_session_gets_the_note_and_the_line_says_so(self, mock_coach, _g):
        ride = save_workout(test_db, TODAY, "cycling", "Climb-Pace 2x15")
        save_workout(test_db, TODAY, "rest", "Rest")
        exit_code, stdout, _ = self.adapt(mock_coach)
        self.assertEqual(exit_code, 0)
        self.assertEqual(self.notes(ride), [WORDS])
        self.assertIn(f"Note kept with session {ride}, “Climb-Pace 2x15” ({TODAY}).", stdout)
        self.assertNotIn("Which session is this about?", stdout)
        # The note still reaches this run's coach, as it always did.
        self.assertEqual(mock_coach.workout_adapt.call_args.kwargs["message"], WORDS)

    def test_two_sessions_ask_which_one(self, mock_coach, _g):
        ride = save_workout(test_db, TODAY, "cycling", "Climb-Pace 2x15")
        lift = save_workout(test_db, TODAY, "strength_training", "Full-Body Strength")
        _, stdout, _ = self.adapt(mock_coach, answer="2")
        self.assertIn("Which session is this about?", stdout)
        self.assertIn("Not about a session", stdout)
        self.assertEqual(self.notes(ride), [])
        self.assertEqual(self.notes(lift), [WORDS])

    def test_not_about_a_session_keeps_nothing(self, mock_coach, _g):
        ride = save_workout(test_db, TODAY, "cycling", "Climb-Pace 2x15")
        lift = save_workout(test_db, TODAY, "strength_training", "Full-Body Strength")
        _, stdout, _ = self.adapt(mock_coach, answer="3")
        self.assertEqual(self.notes(ride) + self.notes(lift), [])
        self.assertNotIn("Note kept", stdout)

    def test_a_day_with_no_session_keeps_nothing(self, mock_coach, _g):
        rest = save_workout(test_db, TODAY, "rest", "Rest")
        _, stdout, _ = self.adapt(mock_coach)
        self.assertEqual(self.notes(rest), [])
        self.assertNotIn("Note kept", stdout)

    def test_a_run_without_a_note_asks_nothing(self, mock_coach, _g):
        save_workout(test_db, TODAY, "cycling", "Climb-Pace 2x15")
        save_workout(test_db, TODAY, "strength_training", "Full-Body Strength")
        mock_coach.workout_adapt.return_value = _proposal()
        _, stdout, _ = run_cli(["workout", "adapt", "--auto"])
        self.assertNotIn("Which session is this about?", stdout)

    def test_a_coach_call_that_fails_keeps_nothing(self, mock_coach, _g):
        """Kept only once the coach answered, so a message sent again is not kept twice."""
        ride = save_workout(test_db, TODAY, "cycling", "Climb-Pace 2x15")
        mock_coach.workout_adapt.side_effect = ValueError("No active periodization strategy")
        run_cli(["workout", "adapt", "--auto", "-m", WORDS])
        self.assertEqual(self.notes(ride), [])

    def test_a_tweak_request_is_not_kept(self, mock_coach, _g):
        ride = save_workout(test_db, TODAY, "cycling", "Climb-Pace 2x15")
        mock_coach.workout_tweak.return_value = _proposal()
        run_cli(["workout", "tweak", "--auto", "make today's ride 45 minutes"])
        mock_coach.workout_tweak.assert_called_once()
        self.assertEqual(self.notes(ride), [])

    def test_the_companion_says_which_session_in_day_words(self, mock_coach, _g):
        save_workout(test_db, TODAY, "cycling", "Climb-Pace 2x15")
        with patch.dict(os.environ, {"STAMIND_RENDER": "simple"}):
            _, stdout, _ = self.adapt(mock_coach)
        self.assertIn("Kept with today's “Climb-Pace 2x15”.", stdout)


class TestTheWordsAreShownUnderTheSession(unittest.TestCase):
    NOTE = {"sent_at": "2026-09-30T09:53:00+00:00", "text": WORDS}
    RIDE = {
        "date": TODAY, "sport_type": "cycling", "title": "Climb-Pace 2x15",
        "description": "[Climb-Pace 2x15]\n2x15 min at 232-242 W.",
        "duration_minutes": 90, "rpe": 7, "tss": 95, "athlete_notes": [NOTE],
    }

    def test_the_prompt_line_comes_after_the_prescription_on_one_line(self):
        text = format_planned_workouts_detailed([self.RIDE], eval_date=TODAY)
        last = text.splitlines()[-1]
        self.assertIn("2x15 min at 232-242 W.", text)
        self.assertTrue(last.startswith("  The athlete said (2026-09-30 Wed "), last)
        self.assertTrue(
            last.endswith('"This was tough. ERG at 235w, stopped at ~12:30 of rep 2."'), last
        )

    def test_the_companion_day_shows_what_the_athlete_said(self):
        text = "\n".join(simple_day_lines([self.RIDE], TODAY))
        self.assertIn("You said: “This was tough.", text)

    def test_the_calendar_sheet_keeps_to_the_session_lines(self):
        text = "\n".join(simple_day_lines([self.RIDE], TODAY, descriptions=False))
        self.assertNotIn("You said", text)


if __name__ == "__main__":
    unittest.main()
