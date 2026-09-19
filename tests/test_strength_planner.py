"""The strength planner (DESIGN_strength_tracking.md §9): the call that writes a strength
session's kilograms, and its place in `workout generate` and `workout adapt`.

The week below is the design's own. `workout generate` wrote the mesocycle on Sunday
September 13, the athlete lifts at the gym on Monday the 14th, Thursday the 17th holds both
the intervals and the next gym day, and `workout adapt` runs every morning.
"""
import os
import unittest
from datetime import datetime
from unittest.mock import patch

from tests import test_db_path
from tests.helpers import clear_all_tables, rebind_test_db, save_workout

TEST_DB_PATH = test_db_path("test_strength_planner.db")

from trainmate.db import Database
import trainmate_cli  # noqa: F401 — the CLI binds its handles at import, before the rebind

from trainmate import runtime, settings
from trainmate.coach import coach_service
from trainmate.strength import planner, prescription, sets

if os.path.exists(TEST_DB_PATH):
    os.remove(TEST_DB_PATH)
test_db = Database(db_path=TEST_DB_PATH)
rebind_test_db(test_db)


def tearDownModule():
    try:
        os.remove(TEST_DB_PATH)
    except OSError:
        pass


TODAY = "2026-09-15"          # Tuesday
MESO_END = "2026-10-11"
TUESDAY_8AM = datetime(2026, 9, 15, 8, 0).astimezone()

BRIEF = "[Full-Body Strength]\nHeavy full-body strength, second week of the build."


def row(exercise, count, low, high, load=None, light=False):
    return {"exercise": exercise, "sets": count, "reps_low": low, "reps_high": high,
            "load_kg": load, "light": light}


def answer(day, *exercises, keep=False, reason="", notes="2–3 min rests.", light=False):
    body = {"date": day, "keep": keep, "light": light, "notes": notes,
            "exercises": [
                {"exercise": e["exercise"], "sets": e["sets"], "reps_low": e["reps_low"],
                 "reps_high": e["reps_high"], "load_kg": e["load_kg"]}
                for e in exercises
            ]}
    if reason:
        body["reason"] = reason
    return body


class _PlannerCase(unittest.TestCase):
    def setUp(self):
        rebind_test_db(test_db)
        clear_all_tables(test_db)
        moving_clock = patch("trainmate.clock.now", return_value=TUESDAY_8AM)
        moving_clock.start()
        self.addCleanup(moving_clock.stop)
        settings.write(settings.STRENGTH_SETS_SINCE, "2026-08-01")
        self.replies = []
        self.asked = []
        call = patch.object(planner, "_complete", side_effect=self._complete)
        call.start()
        self.addCleanup(call.stop)

    def _complete(self, system, user):
        self.asked.append((system, user))
        reply = self.replies.pop(0)
        if isinstance(reply, Exception):
            raise reply
        return reply

    def gym(self, day, *rows, title="Full-Body Strength", brief=BRIEF, duration=70):
        """A planned strength session with the strength planner's exercises on it."""
        description = (
            prescription.render_description(brief, rows, "2–3 min rests.") if rows
            else brief
        )
        with test_db.workout_change(kind="generate") as change:
            change.append(
                date=day, sport_type="strength_training", title=title,
                description=description, duration_minutes=duration, rpe=7, tss=50,
                prescribed_sets=list(rows) or None,
            )
        saved = test_db.get_workout(day, "strength_training")
        self.gym_lineage = saved["id"]
        return saved

    def strength_pass(self, entries, **kwargs):
        live = test_db.get_workouts(start_date=TODAY, end_date=MESO_END)
        return planner.run(
            entries, live, TODAY, MESO_END, TODAY, kwargs.pop("profile", None),
            kwargs.pop("constraints", []), reason_key="modification_reason",
            write_again=kwargs.pop("write_again", False),
        )


class WhenItRunsTest(_PlannerCase):
    def test_a_week_with_no_lifting_costs_no_call(self):
        save_workout(test_db, "2026-09-17", "running", "Intervals", duration_minutes=60)
        self.assertIsNone(self.strength_pass([]))
        self.assertEqual(self.asked, [])

    def test_a_session_with_no_prescribed_sets_is_written(self):
        """A session written before phase 2 keeps its title line and loses the prose under
        it, which named sets and reps the exercise lines now replace (§9)."""
        self.gym("2026-09-17", brief="[Gym]\nSquat 4x4, RDL 4x4 at 8RM load. Press 3x5.")
        self.replies = [{"sessions": [answer("2026-09-17", row("belt squat", 3, 4, 6, 140.0))]}]
        result = self.strength_pass([])
        self.assertEqual(len(result.added), 1)
        self.assertEqual(result.added[0]["description"], "\n".join([
            "[Gym]", "", "Belt squat 3×4–6 @ 140 kg", "2–3 min rests.",
        ]))
        self.assertNotIn("8RM", result.added[0]["description"])

    def test_a_kept_session_is_not_asked_again_without_new_evidence(self):
        """Tuesday weighs Thursday and keeps it; Wednesday, with the stamp where it was,
        does not ask, so the randomness gets no second draw (§9)."""
        session = self.gym("2026-09-17", row("belt squat", 3, 4, 6, 140.0))
        test_db.bump_strength_history()
        self.replies = [{"sessions": [answer("2026-09-17", keep=True)]}]
        first = self.strength_pass([])
        self.assertEqual(first.checked, [("2026-09-17", "strength_training")])
        test_db.record_strength_check(session["id"], first.stamp)
        self.assertIsNone(self.strength_pass([]))
        self.assertEqual(len(self.asked), 1)

    def test_a_session_the_proposal_is_removing_is_left_alone(self):
        """The week planner moves Thursday's gym to Friday for the rain: it returns Thursday
        as rest and Friday as a gym day. Writing kilograms for Thursday would put the
        session the athlete was told had moved back on the calendar (§9)."""
        self.gym("2026-09-17", row("belt squat", 3, 4, 6, 140.0))
        test_db.bump_strength_history()
        thursday_rest = {"date": "2026-09-17", "sport_type": "rest", "title": "Rest Day",
                         "description": "[Rest Day]\nGym moved to Friday — rain."}
        friday = {"date": "2026-09-18", "sport_type": "strength_training", "title": "Gym",
                  "description": "[Gym]\nHeavy full-body, moved from Thursday.",
                  "duration_minutes": 70}
        self.replies = [{"sessions": [
            answer("2026-09-18", row("belt squat", 3, 4, 6, 140.0)),
        ]}]
        result = self.strength_pass([thursday_rest, friday])
        self.assertEqual(result.added, [])
        self.assertEqual(result.checked, [("2026-09-18", "strength_training")])
        self.assertIn("Belt squat 3×4–6 @ 140 kg", friday["description"])

    def test_a_session_that_says_where_it_came_from_keeps_its_kilograms(self):
        """The sets follow the lineage (§9). `workout adapt` now names the slot a moved
        session came from, so Friday opens with Thursday's kilograms rather than being
        written from scratch at the same numbers."""
        self.gym("2026-09-17", row("belt squat", 3, 4, 6, 140.0))
        test_db.bump_strength_history()
        thursday_rest = {"date": "2026-09-17", "sport_type": "rest", "title": "Rest Day",
                         "description": "[Rest Day]\nGym moved to Friday — rain."}
        friday = {"date": "2026-09-18", "sport_type": "strength_training", "title": "Gym",
                  "description": "[Gym]\nHeavy full-body, moved from Thursday.",
                  "duration_minutes": 70,
                  "replaces_slot": ("2026-09-17", "strength_training"),
                  "replaces_lineage": self.gym_lineage}
        self.replies = [{"sessions": [answer("2026-09-18", keep=True)]}]
        result = self.strength_pass([thursday_rest, friday])
        self.assertEqual(result.checked, [("2026-09-18", "strength_training")])
        self.assertIn("Belt squat 3×4–6 @ 140 kg", friday["description"])
        self.assertEqual([r["load_kg"] for r in friday["prescribed_sets"]], [140.0])

    def test_a_session_held_on_a_mentioned_date_is_still_checked(self):
        """The other half of the same rule: the week planner changed the run and kept the
        gym, so the gym stands and its kilograms are still weighed (§9)."""
        self.gym("2026-09-17", row("belt squat", 3, 4, 6, 140.0))
        test_db.bump_strength_history()
        run_entry = {"date": "2026-09-17", "sport_type": "running", "title": "Easy hour",
                     "description": "[Easy hour]\n60 min easy."}
        self.replies = [{"sessions": [answer("2026-09-17", keep=True)]}]
        result = planner.run(
            [run_entry], test_db.get_workouts(start_date=TODAY, end_date=MESO_END),
            TODAY, MESO_END, TODAY, None, [], reason_key="modification_reason",
            held=[("2026-09-17", "strength_training")],
        )
        self.assertEqual(result.checked, [("2026-09-17", "strength_training")])


class CheckingTest(_PlannerCase):
    def setUp(self):
        super().setUp()
        self.session = self.gym("2026-09-17", row("belt squat", 3, 4, 6, 140.0))
        test_db.bump_strength_history()

    def test_new_sets_move_the_load_and_the_reason_reaches_the_athlete(self):
        self.replies = [{"sessions": [
            answer("2026-09-17", row("belt squat", 3, 4, 6, 145.0),
                   reason="Monday's sets all reached 6 at 140; add 5."),
        ]}]
        result = self.strength_pass([])
        self.assertEqual(result.reasons, ["Monday's sets all reached 6 at 140; add 5."])
        [added] = result.added
        self.assertIn("Belt squat 3×4–6 @ 145 kg", added["description"])
        self.assertEqual(added["modification_reason"],
                         "Monday's sets all reached 6 at 140; add 5.")
        self.assertEqual(result.held_dates, ["2026-09-17"])

    def test_the_same_sets_back_are_a_keep_whatever_the_words_say(self):
        """Code decides whether an answer changes a session, from the sets and not from the
        words (§9)."""
        self.replies = [{"sessions": [
            answer("2026-09-17", row("belt squat", 3, 4, 6, 140.0),
                   reason="Holding at 140.", notes="Different wording entirely."),
        ]}]
        result = self.strength_pass([])
        self.assertEqual(result.added, [])
        self.assertEqual(result.checked, [("2026-09-17", "strength_training")])

    def test_a_shorter_session_is_rewritten_even_with_the_brief_unchanged(self):
        """The duration counts, with the brief, as what a session's sets were written
        under: Thursday cut from 70 to 40 minutes gets four exercises, not seven (§9)."""
        test_db.record_strength_check(self.session["id"],
                                      test_db.strength_history_stamp())
        entry = {"date": "2026-09-17", "sport_type": "strength_training",
                 "title": "Full-Body Strength", "description": BRIEF,
                 "duration_minutes": 40, "rpe": 7, "tss": 30}
        self.replies = [{"sessions": [
            answer("2026-09-17", row("belt squat", 3, 4, 6, 140.0),
                   row("chin up", 3, 3, 5), reason="Forty minutes: the two main lifts."),
        ]}]
        result = self.strength_pass([entry])
        # The strength planner is told, or it answers "keep" to a change code would apply.
        self.assertIn(planner.MOVED_ON, self.asked[0][1])
        self.assertEqual(result.added, [])
        self.assertIn("Chin up 3×3–5", entry["description"])
        self.assertEqual([r["exercise"] for r in entry["prescribed_sets"]],
                         ["belt squat", "chin up"])

    def test_a_revision_with_the_brief_and_duration_standing_keeps_its_sets(self):
        test_db.record_strength_check(self.session["id"],
                                      test_db.strength_history_stamp())
        entry = {"date": "2026-09-17", "sport_type": "strength_training",
                 "title": "Full-Body Strength",
                 "description": "[Full-Body Strength]\nHeavy full-body strength, second "
                                "week of the build.",
                 "duration_minutes": 70, "rpe": 7, "tss": 50}
        self.replies = [{"sessions": [
            answer("2026-09-17", row("belt squat", 3, 4, 6, 150.0), reason="Jump."),
        ]}]
        result = self.strength_pass([entry])
        self.assertNotIn(planner.MOVED_ON, self.asked[0][1])
        self.assertEqual(result.added, [])
        self.assertIn("Belt squat 3×4–6 @ 140 kg", entry["description"])
        self.assertEqual([r["load_kg"] for r in entry["prescribed_sets"]], [140.0])


class WriteAgainTest(_PlannerCase):
    """`workout generate --fresh-strength`: the athlete asks for Thursday to be written again
    though nothing was lifted since it was weighed (§9)."""

    def setUp(self):
        super().setUp()
        self.session = self.gym("2026-09-17", row("belt squat", 3, 4, 6, 140.0))
        test_db.record_strength_check(self.session["id"],
                                      test_db.strength_history_stamp())

    def test_without_it_a_weighed_session_costs_no_call(self):
        self.assertIsNone(self.strength_pass([]))
        self.assertEqual(self.asked, [])

    def test_it_is_asked_and_its_answer_is_written_with_the_reason(self):
        self.replies = [{"sessions": [
            answer("2026-09-17", row("belt squat", 3, 4, 6, 140.0),
                   row("barbell push press", 3, 5, 7, 50.0),
                   reason="Your gym days alternate the belt squat and the push press."),
        ]}]
        result = self.strength_pass([], write_again=True)
        self.assertIn(planner.ASKED_AGAIN, self.asked[0][1])
        [added] = result.added
        self.assertEqual([r["exercise"] for r in added["prescribed_sets"]],
                         ["belt squat", "barbell push press"])
        self.assertEqual(added["modification_reason"],
                         "Your gym days alternate the belt squat and the push press.")

    def test_the_same_sets_back_change_nothing(self):
        self.replies = [{"sessions": [
            answer("2026-09-17", row("belt squat", 3, 4, 6, 140.0), reason="Same."),
        ]}]
        result = self.strength_pass([], write_again=True)
        self.assertEqual(result.added, [])
        self.assertEqual(result.checked, [("2026-09-17", "strength_training")])


class OutputChecksTest(_PlannerCase):
    def test_an_unknown_name_drops_that_exercise_not_the_session(self):
        self.gym("2026-09-17")
        self.replies = [{"sessions": [{
            "date": "2026-09-17", "notes": "Rests 2 min.",
            "exercises": [
                {"exercise": "Nordic curl", "sets": 3, "reps_low": 6, "reps_high": 8,
                 "load_kg": None},
                {"exercise": "belt squat", "sets": 3, "reps_low": 4, "reps_high": 6,
                 "load_kg": 140},
            ],
        }]}]
        result = self.strength_pass([])
        self.assertEqual(result.dropped, [
            "2026-09-17: 'Nordic curl' is not an exercise TrainMate knows, left out"
        ])
        self.assertIn("Belt squat 3×4–6 @ 140 kg", result.added[0]["description"])

    def test_nonsense_numbers_drop_the_entry(self):
        for bad in (
            {"exercise": "belt squat", "sets": 0, "reps_low": 4, "reps_high": 6},
            {"exercise": "belt squat", "sets": 3, "reps_low": 6, "reps_high": 4},
            {"exercise": "belt squat", "sets": 3, "reps_low": 4, "reps_high": 6,
             "load_kg": -5},
        ):
            self.assertIsNone(planner._clean_exercise(bad), bad)

    def test_a_light_session_marks_every_row(self):
        self.gym("2026-09-17")
        self.replies = [{"sessions": [
            answer("2026-09-17", row("belt squat", 2, 4, 6, 125.0), light=True),
        ]}]
        result = self.strength_pass([])
        self.assertTrue(all(r["light"] for r in result.added[0]["prescribed_sets"]))


class FailureTest(_PlannerCase):
    def test_a_session_to_write_failing_twice_fails_the_proposal(self):
        self.gym("2026-09-17")
        self.replies = [RuntimeError("timeout"), RuntimeError("timeout")]
        with self.assertRaises(planner.StrengthPlannerFailed):
            self.strength_pass([])

    def test_the_call_is_tried_once_more(self):
        self.gym("2026-09-17")
        self.replies = [
            RuntimeError("timeout"),
            {"sessions": [answer("2026-09-17", row("belt squat", 3, 4, 6, 140.0))]},
        ]
        result = self.strength_pass([])
        self.assertEqual(len(self.asked), 2)
        self.assertEqual(len(result.added), 1)

    def test_only_sessions_to_check_keep_their_sets_and_tell_the_athlete(self):
        """Tuesday's easing reaches the athlete; nothing about Thursday's belt squat needed
        deciding before Thursday (§9)."""
        self.gym("2026-09-17", row("belt squat", 3, 4, 6, 140.0))
        test_db.bump_strength_history()
        self.replies = [RuntimeError("timeout"), RuntimeError("timeout")]
        result = self.strength_pass([])
        self.assertEqual(result.added, [])
        self.assertEqual(result.checked, [])
        self.assertEqual(
            result.notice,
            "I could not recheck Thursday's kilograms this morning. They stand as "
            "written, and I will look again tomorrow.",
        )

    def test_a_session_to_write_whose_every_exercise_fails_is_a_failed_call(self):
        self.gym("2026-09-17")
        unusable = {"sessions": [{
            "date": "2026-09-17",
            "exercises": [{"exercise": "Nordic curl", "sets": 3, "reps_low": 6,
                           "reps_high": 8}],
        }]}
        self.replies = [unusable, unusable]
        with self.assertRaises(planner.StrengthPlannerFailed):
            self.strength_pass([])


class InAdaptTest(_PlannerCase):
    """Where the pass sits inside `workout adapt` (§9)."""

    def test_a_kilogram_change_holds_the_days_other_sessions(self):
        """Thursday is a two-session day. Raising the belt squat names Thursday, and adapt
        reads a named date as holding only what is proposed for it — so the intervals would
        be voided over a kilogram (§9)."""
        save_workout(test_db, "2026-09-17", "running", "Intervals", duration_minutes=60)
        self.gym("2026-09-17", row("belt squat", 3, 4, 6, 140.0))
        test_db.bump_strength_history()
        held = coach_service._hold_around(
            ["2026-09-17"], test_db.get_workouts(start_date=TODAY, end_date=MESO_END)
        )
        self.assertEqual(held, [("2026-09-17", "running")])


class ThroughAdaptTest(_PlannerCase):
    """The whole path: the week planner holds everything, the strength planner raises
    Thursday, and the proposal the athlete meets says so (§9)."""

    def setUp(self):
        super().setUp()
        objective_id = test_db.add_objective(
            title="Race", target_date="2026-12-01", sport_type="cycling",
        )
        test_db.save_macrocycle(
            objective_id=objective_id, strategy="Build.", goals_hash="g",
            constraints_hash="c",
            mesocycles=[{"name": "Build", "start_date": "2026-09-01",
                         "end_date": MESO_END, "focus": "Build"}],
        )

    def test_only_the_strength_planner_changing_something_still_makes_a_proposal(self):
        save_workout(test_db, "2026-09-17", "running", "Intervals", duration_minutes=60)
        self.gym("2026-09-17", row("belt squat", 3, 4, 6, 140.0))
        test_db.bump_strength_history()
        self.replies = [{"sessions": [
            answer("2026-09-17", row("belt squat", 3, 4, 6, 145.0),
                   reason="Monday's sets all reached 6 at 140; add 5."),
        ]}]
        with patch("trainmate.coach.engine.openrouter_client") as week_planner:
            week_planner.complete.return_value = {
                "change_needed": False, "reason": "No adaptation needed.",
                "adapted_workouts": [],
            }
            proposal = coach_service.workout_adapt(TODAY)

        self.assertEqual(len(proposal.workouts), 1)
        self.assertEqual(proposal.reason, "Monday's sets all reached 6 at 140; add 5.")
        # Thursday's intervals are held, so applying the kilogram change does not void them.
        self.assertIn(("2026-09-17", "running"), proposal.held)

        coach_service.workout_revision_apply(proposal)
        gym = test_db.get_workout("2026-09-17", "strength_training")
        self.assertEqual([r["load_kg"] for r in gym["prescribed_sets"]], [145.0])
        self.assertIn("Belt squat 3×4–6 @ 145 kg", gym["description"])
        self.assertIsNotNone(test_db.get_workout("2026-09-17", "running"))
        self.assertEqual(test_db.get_strength_check(gym["id"]), proposal.strength_stamp)

    def test_the_preview_prints_the_kilograms(self):
        from trainmate.cli.workouts.generate import print_generate_preview
        from trainmate.coach.proposals import GenerateProposal
        session = self.gym("2026-09-17", row("belt squat", 3, 4, 6, 140.0))
        proposal = GenerateProposal(
            reasoning="Second week of the build.", workouts=(session,),
            strength_dropped=("2026-09-21: 'Nordic curl' is not an exercise TrainMate "
                              "knows, left out",),
        )
        with patch("builtins.print") as printed:
            print_generate_preview(proposal)
        shown = "\n".join(str(call.args[0]) if call.args else "" for call in printed.mock_calls)
        self.assertIn("Belt squat 3×4–6 @ 140 kg", shown)
        self.assertIn("Nordic curl", shown)


class ThroughGenerateTest(_PlannerCase):
    """`workout generate --fresh-strength` on Tuesday: the week planner keeps Thursday's gym,
    which is inside the commitment window, and the strength planner writes it again (§9)."""

    def setUp(self):
        super().setUp()
        objective_id = test_db.add_objective(
            title="Race", target_date="2026-12-01", sport_type="cycling",
        )
        test_db.save_macrocycle(
            objective_id=objective_id, strategy="Build.", goals_hash="g",
            constraints_hash="c",
            mesocycles=[{"name": "Build", "start_date": "2026-09-01",
                         "end_date": MESO_END, "focus": "Build"}],
        )
        gym = self.gym("2026-09-17", row("belt squat", 3, 4, 6, 140.0))
        test_db.record_strength_check(gym["id"], test_db.strength_history_stamp())

    def generate(self, **flags):
        with patch("trainmate.runtime.calendar_syncer"), \
                patch("trainmate.coach.engine.openrouter_client") as week_planner:
            week_planner.complete.return_value = {"reasoning": "Build.", "workouts": []}
            proposal = coach_service.workout_generate(**flags)
            coach_service.workout_generate_apply(proposal)
        return proposal

    def test_the_kept_session_gets_new_sets_and_the_reason(self):
        reason = "Your gym days alternate the belt squat and the push press."
        self.replies = [{"sessions": [
            answer("2026-09-17", row("belt squat", 3, 4, 6, 140.0),
                   row("barbell push press", 3, 5, 7, 50.0), reason=reason),
        ]}]
        proposal = self.generate(fresh_strength=True)
        line = next(l for l in proposal.standing if l.date == "2026-09-17")
        self.assertEqual((line.outcome, line.reason), ("revised", reason))
        gym = test_db.get_workout("2026-09-17", "strength_training")
        self.assertEqual([r["exercise"] for r in gym["prescribed_sets"]],
                         ["belt squat", "barbell push press"])
        self.assertEqual(gym["modification_reason"], reason)

    def test_without_it_the_kept_session_is_not_asked_about(self):
        proposal = self.generate()
        self.assertEqual(self.asked, [])
        line = next(l for l in proposal.standing if l.date == "2026-09-17")
        self.assertEqual(line.outcome, "kept")

    def test_fresh_implies_it(self):
        """The week planner writes Thursday again with the brief it had, so only the
        athlete's request makes the strength planner write it again."""
        self.replies = [{"sessions": [
            answer("2026-09-17", row("goblet squat", 3, 8, 10, 32.0), reason="New."),
        ]}]
        thursday = {"date": "2026-09-17", "sport_type": "strength_training",
                    "title": "Full-Body Strength", "description": BRIEF,
                    "duration_minutes": 70, "rpe": 7, "tss": 50}
        with patch("trainmate.runtime.calendar_syncer"), \
                patch("trainmate.coach.engine.openrouter_client") as week_planner:
            week_planner.complete.return_value = {"reasoning": "Build.",
                                                  "workouts": [thursday]}
            coach_service.workout_generate(fresh=True)
        self.assertIn(planner.ASKED_AGAIN, self.asked[0][1])


class RecordingTest(_PlannerCase):
    def test_the_check_row_holds_the_stamp_the_history_was_built_from(self):
        session = self.gym("2026-09-17", row("belt squat", 3, 4, 6, 140.0))
        test_db.bump_strength_history()
        self.replies = [{"sessions": [answer("2026-09-17", keep=True)]}]
        result = self.strength_pass([])

        class _Proposal:
            strength_checks = tuple(result.checked)
            strength_stamp = result.stamp

        # A read landing between building the history and applying is not weighed.
        test_db.bump_strength_history()
        planner.record_checks(test_db, _Proposal())
        self.assertEqual(test_db.get_strength_check(session["id"]), result.stamp)
        self.assertLess(test_db.get_strength_check(session["id"]),
                        test_db.strength_history_stamp())

    def test_a_declined_proposal_leaves_no_row(self):
        session = self.gym("2026-09-17", row("belt squat", 3, 4, 6, 140.0))
        test_db.bump_strength_history()
        self.replies = [{"sessions": [answer("2026-09-17", keep=True)]}]
        self.strength_pass([])
        self.assertIsNone(test_db.get_strength_check(session["id"]))


class PromptTest(_PlannerCase):
    def test_the_call_is_shown_the_history_the_science_and_the_days_equipment(self):
        entry = {"date": "2026-09-16", "sport_type": "strength_training", "title": "Gym",
                 "description": "[Gym]\n\nModerate full-body at home, 45 min.",
                 "duration_minutes": 45}
        self.replies = [{"sessions": [
            answer("2026-09-16", row("goblet squat", 3, 8, 10, 48.0)),
        ]}]
        profile = {"equipment": ["kettlebells up to 24 kg"],
                   "weekly_schedule": {"Wednesday": {"equipment": ["pull-up bar"]}}}
        constraints = [{"start_date": "2026-09-14", "end_date": "2026-09-20",
                        "title": "Hotel gym", "description": "dumbbells only"}]
        self.strength_pass([entry], profile=profile, constraints=constraints)
        system, user = self.asked[0]
        self.assertIn("START OF HOW TO PROGRESS", system)
        self.assertIn("Every exercise is written as a rep range at one load", system)
        self.assertIn("## EXERCISES TRAINMATE KNOWS", system)
        self.assertIn("belt squat (squat, machine)", system)
        self.assertIn("## STRENGTH HISTORY", user)
        self.assertIn("Equipment that day: pull-up bar, kettlebells up to 24 kg", user)
        self.assertIn("Constraints that day: Hotel gym — dumbbells only", user)
        # The brief is stored with its blank lines collapsed, so the first blank line of
        # the description is the seam whatever paragraphing the week planner gave it (§9).
        self.assertIn("      [Gym]\n      Moderate full-body at home, 45 min.", user)
        self.assertEqual(
            entry["description"].split("\n\n")[0],
            "[Gym]\nModerate full-body at home, 45 min.",
        )

    def test_the_accessory_names_shown_are_the_ones_the_athlete_does(self):
        """The full accessory list would double the region with names nobody lifts (§9)."""
        listed = planner._exercise_list({"cable biceps curl"})
        self.assertIn("cable biceps curl (accessory, cable)", listed)
        self.assertIn("belt squat (squat, machine)", listed)
        self.assertNotIn("barbell biceps curl (accessory", listed)


if __name__ == "__main__":
    unittest.main()
