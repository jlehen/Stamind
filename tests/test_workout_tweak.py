"""`workout tweak`: the athlete decides the change, the week planner writes it, and only
the days the request is about may change (DESIGN_workout_tweak.md §3, §4).

The week is the design's own. It is Monday 21 September. Thursday holds intervals on the
bike, Friday an endurance ride, Saturday the long ride. The mesocycle ends on Sunday 4
October. Everything goes through the real propose/apply pair against a canned week planner
reply, because what matters is what lands in the log.
"""
import io
import os
import unittest
from contextlib import redirect_stdout
from unittest.mock import patch

from tests import test_db_path
from tests.helpers import (
    clear_all_tables, pin_clock, rebind_test_db, run_cli, save_workout,
    skip_strength_planner,
)

TEST_DB_PATH = test_db_path("test_workout_tweak.db")

from trainmate.db import Database
import trainmate_cli  # noqa: F401 — the CLI binds its handles at import, before the rebind

from trainmate import settings
from trainmate.coach.service import coach_service
from trainmate.strength import planner, prescription

if os.path.exists(TEST_DB_PATH):
    os.remove(TEST_DB_PATH)
test_db = Database(db_path=TEST_DB_PATH)
rebind_test_db(test_db)


def tearDownModule():
    try:
        os.remove(TEST_DB_PATH)
    except OSError:
        pass


TODAY = "2026-09-21"      # Monday
TUESDAY, THURSDAY, FRIDAY, SATURDAY, SUNDAY = (
    "2026-09-22", "2026-09-24", "2026-09-25", "2026-09-26", "2026-09-27",
)
MESO_END = "2026-10-04"
PAST_THE_MESOCYCLE = "2026-10-10"

HIKE = {
    "date": SATURDAY, "sport_type": "hiking", "title": "Hike with friends",
    "description": "[Hike with friends]\n4 hours at an easy pace.",
    "duration_minutes": 240, "rpe": 3, "tss": 120,
    "change_reason": "On request: hike with friends in place of the long ride.",
    "replaces": {"date": SATURDAY, "sport_type": "cycling"},
}
SHORTER_THURSDAY = {
    "date": THURSDAY, "sport_type": "cycling", "title": "Intervals",
    "description": "[Intervals]\n45 min, 4x4 at threshold.",
    "duration_minutes": 45, "rpe": 7, "tss": 55,
    "change_reason": "On request: 45 minutes.",
}


def reply(*entries, days=(), change=True):
    return {
        "change_needed": change, "reason": "Done as asked.",
        "adapted_workouts": list(entries), "tweak_dates": list(days),
    }


class _TweakCase(unittest.TestCase):
    def setUp(self):
        rebind_test_db(test_db)
        clear_all_tables(test_db)
        pin_clock(self, TODAY)
        objective = test_db.add_objective(
            title="Autumn gran fondo", target_date="2026-11-15", sport_type="cycling",
        )
        test_db.save_macrocycle(
            objective_id=objective, strategy="Build.", goals_hash="g",
            constraints_hash="c",
            mesocycles=[{"name": "Build 2", "start_date": "2026-09-14",
                         "end_date": MESO_END, "focus": "Threshold"}],
        )
        self.ride(THURSDAY, "Intervals", 60, 70)
        self.ride(FRIDAY, "Endurance ride", 90, 80)
        self.ride(SATURDAY, "Long ride", 180, 160)

    @staticmethod
    def ride(day, title, minutes, load):
        return save_workout(
            test_db, day, "cycling", title, f"[{title}]\n{minutes} min.",
            duration_minutes=minutes, rpe=5, tss=load,
        )

    def tweak(self, answer, days=(), message="Saturday: a 4 hour hike instead of the ride"):
        """The proposal a tweak makes against `answer`, and the week planner's client."""
        with patch("trainmate.coach.engine.openrouter_client") as client, \
                redirect_stdout(io.StringIO()):
            client.complete.return_value = answer
            self.client = client
            return coach_service.workout_tweak(message, tweak_dates=days, today_str=TODAY)

    @staticmethod
    def apply(proposal):
        with patch("trainmate.runtime.calendar_syncer"), redirect_stdout(io.StringIO()):
            coach_service.workout_revision_apply(proposal)

    @staticmethod
    def written(proposal):
        return sorted((w["date"], w["sport_type"]) for w in proposal.workouts)


class CommandTest(_TweakCase):
    @patch("trainmate.cli.workouts.generate.ensure_recent_data")
    @patch("trainmate.runtime.coach_service")
    def test_every_d_reaches_the_service_with_the_message(self, service, _pull):
        from trainmate.coach.proposals import RevisionProposal
        service.workout_tweak.return_value = RevisionProposal(
            reason="Swapped.", workouts=[], range_start=TODAY, range_end=MESO_END,
            kind="tweak",
        )
        exit_code, _out, _err = run_cli(
            ["workout", "tweak", "-y", "-d", THURSDAY, "-d", FRIDAY, "swap them"]
        )
        self.assertEqual(exit_code, 0)
        args, kwargs = service.workout_tweak.call_args
        self.assertEqual(args[0], "swap them")
        self.assertEqual(kwargs["tweak_dates"], [THURSDAY, FRIDAY])


class WhichDaysTest(_TweakCase):
    """§3.1 and §3.2: the days are the ones given with -d, else the ones the week planner
    read off the message, and a reply is cut down to them."""

    def setUp(self):
        super().setUp()
        skip_strength_planner(self)

    def test_the_days_given_with_d_are_the_only_ones_written(self):
        proposal = self.tweak(reply(HIKE, SHORTER_THURSDAY), days=[SATURDAY])
        self.assertEqual(self.written(proposal), [(SATURDAY, "hiking")])
        self.assertEqual(proposal.kind, "tweak")

    def test_without_d_the_days_come_from_the_reply(self):
        proposal = self.tweak(reply(HIKE, SHORTER_THURSDAY, days=[SATURDAY]))
        self.assertEqual(self.written(proposal), [(SATURDAY, "hiking")])

    def test_a_reply_that_changes_sessions_and_names_no_day_stops_the_run(self):
        with self.assertRaises(ValueError) as refused:
            self.tweak(reply(HIKE))
        self.assertIn("-d DATE", str(refused.exception))

    def test_a_reply_that_changes_nothing_needs_no_day(self):
        """The week planner could not tell the day and said so in its reason."""
        proposal = self.tweak(reply(change=False))
        self.assertEqual(proposal.workouts, [])

    def test_a_day_past_the_mesocycle_is_refused_before_the_call(self):
        with self.assertRaises(ValueError) as refused:
            self.tweak(reply(HIKE), days=[PAST_THE_MESOCYCLE])
        self.assertIn("2026-10-10", str(refused.exception))
        self.client.complete.assert_not_called()

    def test_a_day_past_the_mesocycle_named_by_the_reply_is_refused(self):
        with self.assertRaises(ValueError):
            self.tweak(reply(HIKE, days=[SATURDAY, PAST_THE_MESOCYCLE]))

    def test_a_move_to_another_date_is_dropped_and_leaves_no_rest_day(self):
        """The athlete asked about Thursday. A reply that carries Thursday's ride to
        Sunday is half outside, so neither half is written — not even the rest day a move
        leaves behind, whose reason would name a move that never happens."""
        to_sunday = dict(
            SHORTER_THURSDAY, date=SUNDAY,
            replaces={"date": THURSDAY, "sport_type": "cycling"},
        )
        proposal = self.tweak(reply(to_sunday), days=[THURSDAY])
        self.assertEqual(proposal.workouts, [])
        self.assertEqual(proposal.removals, ())


class WhatItWritesTest(_TweakCase):
    def setUp(self):
        super().setUp()
        skip_strength_planner(self)

    def test_two_rides_swap_days_and_each_keeps_its_id(self):
        """"Swap Thursday and Friday, it rains on Thursday." Both are rides: each lands
        where the other stood, which the move check used to refuse (§3.1)."""
        intervals = test_db.get_workout(THURSDAY, "cycling")["id"]
        endurance = test_db.get_workout(FRIDAY, "cycling")["id"]
        answer = reply(
            {"date": THURSDAY, "sport_type": "cycling", "title": "Endurance ride",
             "description": "[Endurance ride]\n90 min.", "duration_minutes": 90,
             "rpe": 5, "tss": 80, "change_reason": "On request: swapped with Friday.",
             "replaces": {"date": FRIDAY, "sport_type": "cycling"}},
            {"date": FRIDAY, "sport_type": "cycling", "title": "Intervals",
             "description": "[Intervals]\n60 min.", "duration_minutes": 60,
             "rpe": 5, "tss": 70, "change_reason": "On request: swapped with Thursday.",
             "replaces": {"date": THURSDAY, "sport_type": "cycling"}},
            days=[THURSDAY, FRIDAY],
        )
        self.apply(self.tweak(answer, message="swap Thursday and Friday, rain Thursday"))

        thursday = test_db.get_workout(THURSDAY, "cycling")
        friday = test_db.get_workout(FRIDAY, "cycling")
        self.assertEqual((thursday["title"], thursday["id"]), ("Endurance ride", endurance))
        self.assertEqual((friday["title"], friday["id"]), ("Intervals", intervals))

    def test_a_tweak_is_its_own_kind_and_a_rollback_undoes_it(self):
        self.apply(self.tweak(reply(HIKE, days=[SATURDAY])))
        hike = test_db.get_workout(SATURDAY, "hiking")
        self.assertEqual(hike["title"], "Hike with friends")
        # The line a later `workout adapt` reads to know the athlete asked (§3.3).
        self.assertEqual(hike["modification_reason"], HIKE["change_reason"])
        change = test_db.get_workout_changes()[0]
        self.assertEqual(change["kind"], "tweak")

        with patch("trainmate.runtime.calendar_syncer"):
            test_db.rollback_to_change(change["id"], TODAY)

        saturday = test_db.get_workouts(start_date=SATURDAY, end_date=SATURDAY)
        self.assertEqual([w["title"] for w in saturday], ["Long ride"])

    def test_a_tweak_marks_no_constraint_honoured(self):
        """A tweak had authority over a few days, not over the whole range (§3.2)."""
        test_db.add_constraint(title="Away", start_date=TUESDAY, end_date=TUESDAY, rest=1)
        proposal = self.tweak(reply(HIKE, days=[SATURDAY]))
        self.assertEqual(proposal.covered_constraint_ids, ())

    def test_a_tweak_starts_the_count_of_easings_again(self):
        """A ride the athlete lengthened is no longer the one the morning eased (§3.3)."""
        save_workout(
            test_db, THURSDAY, "cycling", "Intervals", "[Intervals]\n40 min.",
            duration_minutes=40, rpe=5, tss=45, original_duration_minutes=60,
            original_tss=70, modification_reason="Eased: HRV down.",
        )
        self.assertEqual(test_db.get_workout(THURSDAY, "cycling")["adaptation_count"], 1)
        longer = dict(SHORTER_THURSDAY, duration_minutes=75, tss=85,
                      description="[Intervals]\n75 min, 5x5 at threshold.")
        self.apply(self.tweak(reply(longer), days=[THURSDAY]))

        from trainmate.workout_state import modification_markers
        thursday = test_db.get_workout(THURSDAY, "cycling")
        self.assertEqual(thursday["adaptation_count"], 0)
        self.assertEqual(modification_markers(thursday), ["TWEAKED"])


class CancelledSessionsTest(_TweakCase):
    """"Put Saturday's ride back" needs the ride's line in the prompt, whoever dropped it
    (§3.1)."""

    def setUp(self):
        super().setUp()
        skip_strength_planner(self)

    def test_a_ride_dropped_to_a_rest_day_is_listed(self):
        """The rest day carries the ride's history, which hides the ride from the usual
        read of removed sessions. It is still gone from the schedule."""
        rest = {"date": SATURDAY, "sport_type": "rest", "title": "Rest Day",
                "description": "[Rest Day]\nNo training.", "duration_minutes": 0,
                "rpe": 0, "tss": 0, "change_reason": "On request: dropped."}
        self.apply(self.tweak(reply(rest, days=[SATURDAY]), message="drop Saturday"))

        cancelled = test_db.get_cancelled_workouts(TODAY, MESO_END)
        self.assertEqual([(w["date"], w["title"]) for w in cancelled],
                         [(SATURDAY, "Long ride")])

        self.tweak(reply(change=False), message="put Saturday's ride back")
        user = self.client.complete.call_args.args[1]
        self.assertIn("## SESSIONS NO LONGER ON THE SCHEDULE", user)
        self.assertIn("Long ride", user.split("## SESSIONS NO LONGER ON THE SCHEDULE")[1])

    def test_a_moved_session_is_not_listed(self):
        """It moved; it was not cancelled."""
        to_sunday = dict(
            SHORTER_THURSDAY, date=SUNDAY,
            replaces={"date": THURSDAY, "sport_type": "cycling"},
        )
        self.apply(self.tweak(reply(to_sunday, days=[THURSDAY, SUNDAY])))
        self.assertEqual(test_db.get_workout(SUNDAY, "cycling")["title"], "Intervals")
        self.assertEqual(test_db.get_cancelled_workouts(TODAY, MESO_END), [])


class StrengthRequestTest(_TweakCase):
    """§4: the request travels in Friday's brief, and the strength planner is shown the
    tweak's days only."""

    BELT_SQUAT = {"exercise": "belt squat", "sets": 3, "reps_low": 4, "reps_high": 6,
                  "load_kg": 140.0, "light": False}

    def setUp(self):
        super().setUp()
        settings.write(settings.STRENGTH_SETS_SINCE, "2026-08-01")
        description = prescription.render_description(
            "[Lower-Body Strength]\nHeavy, low in volume.", [self.BELT_SQUAT],
            "2–3 min rests.",
        )
        with test_db.workout_change(kind="generate") as change:
            change.append(
                date=FRIDAY, sport_type="strength_training", title="Lower-Body Strength",
                description=description, duration_minutes=70, rpe=7, tss=50,
                prescribed_sets=[self.BELT_SQUAT],
            )
        self.friday_gym = {
            "date": FRIDAY, "sport_type": "strength_training",
            "title": "Lower-Body Strength",
            "description": (
                "[Lower-Body Strength]\nHeavy, low in volume. Barbell step-ups take the "
                "place of belt squats, as requested: the machine is broken."
            ),
            "duration_minutes": 70, "rpe": 7, "tss": 50,
            "change_reason": "On request: step-ups in place of belt squats.",
        }

    def test_a_brief_that_names_the_request_is_written_again(self):
        asked = []

        def strength_planner_reply(system, user):
            asked.append(user)
            return {"sessions": [{
                "date": FRIDAY, "keep": False, "light": False,
                "notes": "Step-ups start light.",
                "exercises": [{"exercise": "barbell step up", "sets": 3, "reps_low": 6,
                               "reps_high": 8, "load_kg": 40.0}],
            }]}

        with patch.object(planner, "_complete", side_effect=strength_planner_reply):
            proposal = self.tweak(
                reply(self.friday_gym, days=[FRIDAY]),
                message="Friday: step-ups instead of belt squats, the machine is broken",
            )
        self.assertEqual(len(asked), 1)
        self.assertIn("take the place of belt squats", asked[0])
        [friday] = proposal.workouts
        self.assertIn("Barbell step up", friday["description"])
        self.assertNotIn("Belt squat", friday["description"])

    def test_a_request_about_another_day_never_reaches_fridays_session(self):
        """The athlete asked about Thursday. A reply that also rewrote Friday's brief is
        cut back to Thursday, and the strength planner is shown Thursday only."""
        with patch.object(planner, "run", return_value=None) as run:
            proposal = self.tweak(
                reply(SHORTER_THURSDAY, self.friday_gym, days=[THURSDAY]),
                message="make Thursday's ride 45 minutes",
            )
        self.assertEqual(self.written(proposal), [(THURSDAY, "cycling")])
        entries, live, span_start, span_end = run.call_args.args[:4]
        self.assertEqual({e["date"] for e in entries}, {THURSDAY})
        self.assertEqual({w["date"] for w in live}, {THURSDAY})
        self.assertEqual((span_start, span_end), (THURSDAY, THURSDAY))


if __name__ == "__main__":
    unittest.main()
