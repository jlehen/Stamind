"""The strength history and the rows behind it (DESIGN_strength_tracking.md §8, §9).

What the strength planner is shown of the athlete's lifting: one entry per exercise a
person named, what was prescribed beside what was done, and the days the prescription was
not followed. Plus the prescribed sets themselves, which ride on a revision and follow the
session across a restore and a swap.
"""
import os
import unittest
from datetime import datetime
from unittest.mock import patch

from tests import test_db_path
from tests.helpers import clear_all_tables, rebind_test_db

TEST_DB_PATH = test_db_path("test_strength_history.db")

from trainmate.db import Database
import trainmate_cli  # noqa: F401 — the CLI binds its handles at import, before the rebind

from trainmate import runtime, settings
from trainmate.strength import history, prescription, sets

if os.path.exists(TEST_DB_PATH):
    os.remove(TEST_DB_PATH)
test_db = Database(db_path=TEST_DB_PATH)
rebind_test_db(test_db)


def tearDownModule():
    try:
        os.remove(TEST_DB_PATH)
    except OSError:
        pass


TODAY = "2026-09-16"          # Wednesday
WEDNESDAY_8AM = datetime(2026, 9, 16, 8, 0).astimezone()


def lift(category, name=None, reps=10, kg=60.0):
    """One set as Garmin returns a person's pick: one candidate at 100%, weight in grams."""
    return {
        "setType": "ACTIVE", "repetitionCount": reps, "duration": 30.0,
        "weight": None if kg is None else kg * 1000.0,
        "exercises": [{"category": category, "name": name, "probability": 100.0}],
    }


def payload(*entries):
    listed = []
    for entry in entries:
        listed.append(entry)
        listed.append({"setType": "REST", "duration": 90.0, "exercises": [],
                       "repetitionCount": None, "weight": None})
    return {"exerciseSets": listed}


def row(exercise, count, low, high, load=None, light=False):
    return {"exercise": exercise, "sets": count, "reps_low": low, "reps_high": high,
            "load_kg": load, "light": light}


class FakeGarmin:
    def __init__(self):
        self.payloads = {}

    def get_activity_exercise_sets(self, activity_id):
        return self.payloads.get(activity_id, {"exerciseSets": []})


class _HistoryCase(unittest.TestCase):
    def setUp(self):
        rebind_test_db(test_db)
        clear_all_tables(test_db)
        moving_clock = patch("trainmate.clock.now", return_value=WEDNESDAY_8AM)
        moving_clock.start()
        self.addCleanup(moving_clock.stop)
        settings.write(settings.STRENGTH_SETS_SINCE, "2026-08-01")
        self.garmin = FakeGarmin()

    def lifted(self, day, *entries, activity_id=None, start="18:10:00", rpe=6, read=True):
        """One strength activity on `day`, its sets read and frozen."""
        activity_id = activity_id or f"{day}-{start[:2]}"
        test_db.save_completed_activity(
            activity_id=activity_id, date=day, start_time=f"{day} {start}",
            activity_name="Strength", activity_type="strength_training",
            duration_sec=3600.0, distance_km=0.0, elevation_gain_m=0.0,
            avg_hr=None, max_hr=None, rpe=rpe, tss=None,
        )
        if not read:
            return activity_id
        self.garmin.payloads[activity_id] = payload(*entries)
        sets.read_new_activities(self.garmin)
        return activity_id

    def planned(self, day, *rows, title="Full-Body Strength", brief="Heavy full-body.",
                duration=70):
        """One planned strength session with the strength planner's exercises on it."""
        description = prescription.render_description(
            f"[{title}]\n{brief}", rows, "2–3 min rests."
        )
        with test_db.workout_change(kind="generate") as change:
            change.append(
                date=day, sport_type="strength_training", title=title,
                description=description, duration_minutes=duration, rpe=7, tss=50,
                prescribed_sets=list(rows),
            )
        return test_db.get_workout(day, "strength_training")

    def text(self):
        return history.build(TODAY).text


class EntriesTest(_HistoryCase):
    def test_one_entry_per_exercise_with_what_was_prescribed_beside_what_was_done(self):
        self.planned(
            "2026-09-14",
            row("belt squat", 1, 5, 5, 120.0), row("belt squat", 3, 4, 6, 140.0),
            row("chin up", 3, 3, 5),
        )
        self.lifted(
            "2026-09-14",
            lift("SQUAT", "BELT_SQUAT", 5, 120), lift("SQUAT", "BELT_SQUAT", 6, 140),
            lift("SQUAT", "BELT_SQUAT", 6, 140), lift("SQUAT", "BELT_SQUAT", 6, 140),
            rpe=7,
        )
        self.assertEqual(self.text(), "\n".join([
            history.HEADING,
            "  belt squat (squat, machine)",
            "    Mon Sep 14, prescribed 1×5 @ 120, 3×4–6 @ 140: 1×5 @ 120, 3×6 @ 140 | RPE 7",
            "",
            "NOT DONE",
            "  Mon Sep 14: chin up 3×3–5",
        ]))

    def test_a_day_the_watch_split_in_two_shows_each_activity_on_its_own_line(self):
        """Merged, the evening's light work reads as the morning's fading (§8)."""
        self.planned("2026-09-15", row("goblet squat", 3, 8, 10, 44.0))
        self.lifted("2026-09-15", lift("SQUAT", "GOBLET_SQUAT", 10, 44),
                    lift("SQUAT", "GOBLET_SQUAT", 10, 44),
                    lift("SQUAT", "GOBLET_SQUAT", 10, 44), start="09:00:00", rpe=6)
        self.lifted("2026-09-15", lift("SQUAT", "GOBLET_SQUAT", 12, 16),
                    lift("SQUAT", "GOBLET_SQUAT", 12, 16), start="20:10:00", rpe=2)
        self.assertIn("\n".join([
            "    Tue Sep 15, prescribed 3×8–10 @ 44:",
            "      09:00: 3×10 @ 44 | RPE 6",
            "      20:10: 2×12 @ 16 | RPE 2",
        ]), self.text())

    def test_a_name_only_the_watch_guessed_is_not_an_entry(self):
        guessed = lift("DEADLIFT", "BARBELL_DEADLIFT", 12, 16)
        guessed["exercises"][0]["probability"] = 64.0
        guessed["exercises"].append({"category": "UNKNOWN", "name": None,
                                     "probability": 36.0})
        self.lifted("2026-09-14", lift("SQUAT", "BELT_SQUAT", 5, 140), guessed)
        text = self.text()
        self.assertIn("belt squat", text)
        self.assertNotIn("barbell deadlift", text)

    def test_a_discarded_activity_leaves_the_history(self):
        activity_id = self.lifted("2026-09-14", lift("SQUAT", "BELT_SQUAT", 5, 140))
        test_db.set_activity_discarded(activity_id, True)
        self.assertEqual(self.text(), "")

    def test_an_exercise_shows_three_days_and_the_light_ones_after_the_oldest(self):
        """A light week is not a step, so the day to resume from has to be on the page: an
        athlete who lifts three times a week would otherwise see only light days (§8)."""
        for day in ("2026-09-07", "2026-09-09", "2026-09-11"):
            self.planned(day, row("belt squat", 3, 4, 6, 140.0))
            self.lifted(day, lift("SQUAT", "BELT_SQUAT", 5, 140))
        for day in ("2026-09-14", "2026-09-15"):
            self.planned(day, row("belt squat", 2, 4, 6, 125.0, light=True))
            self.lifted(day, lift("SQUAT", "BELT_SQUAT", 6, 125))
        days = [line.strip().split(",")[0].split(":")[0]
                for line in self.text().splitlines() if line.startswith("    ")]
        self.assertEqual(days, ["Tue Sep 15", "Mon Sep 14", "Fri Sep 11", "Wed Sep 9",
                                "Mon Sep 7"])
        self.assertIn("Tue Sep 15, prescribed 2×4–6 @ 125 (light)", self.text())

    def test_only_the_last_eight_strength_days_decide_which_exercises_appear(self):
        for offset, day in enumerate([
            "2026-09-15", "2026-09-14", "2026-09-13", "2026-09-12", "2026-09-11",
            "2026-09-10", "2026-09-09", "2026-09-08",
        ]):
            self.lifted(day, lift("SQUAT", "BELT_SQUAT", 5, 140 - offset))
        self.lifted("2026-09-07", lift("ROW", "SEATED_CABLE_ROW", 10, 60))
        text = self.text()
        self.assertIn("belt squat", text)
        self.assertNotIn("seated cable row", text)


class NotDoneTest(_HistoryCase):
    def test_a_day_with_no_strength_activity_lists_the_whole_session(self):
        self.planned("2026-09-14", row("belt squat", 3, 4, 6, 145.0),
                     row("glute bridge", 4, 4, 6, 130.0))
        self.lifted("2026-09-13", lift("SQUAT", "BELT_SQUAT", 5, 140))
        self.lifted("2026-09-15", lift("SQUAT", "BELT_SQUAT", 5, 140))
        self.assertIn(
            "  Mon Sep 14: no strength activity "
            "(belt squat 3×4–6 @ 145, glute bridge 4×4–6 @ 130)",
            self.text(),
        )

    def test_today_is_never_on_the_list(self):
        """A session planned for today can still be done, whatever the hour (§8)."""
        self.planned(TODAY, row("belt squat", 3, 4, 6, 145.0))
        self.lifted("2026-09-14", lift("SQUAT", "BELT_SQUAT", 5, 140))
        self.assertNotIn("Sep 16", self.text())

    def test_a_day_whose_sets_are_not_read_yet_says_so(self):
        self.planned("2026-09-15", row("belt squat", 3, 4, 6, 145.0))
        self.lifted("2026-09-13", lift("SQUAT", "BELT_SQUAT", 5, 140))
        # Added after the read, so Tuesday's sets are still to come.
        self.lifted("2026-09-15", read=False)
        self.assertIn(f"  Tue Sep 15: {sets.SETS_NOT_READ}", self.text())
        self.assertNotIn("Tue Sep 15: no strength activity", self.text())

    def test_a_day_where_everything_prescribed_was_done_gets_no_line(self):
        self.planned("2026-09-14", row("belt squat", 3, 4, 6, 140.0))
        self.lifted("2026-09-14", lift("SQUAT", "BELT_SQUAT", 5, 140))
        self.assertNotIn(history.NOT_DONE_HEADING, self.text())


class PrescribedSetsTest(_HistoryCase):
    """The rows ride on a revision and follow the session (§9)."""

    def test_the_description_is_rendered_from_the_rows(self):
        workout = self.planned(
            "2026-09-14",
            row("belt squat", 1, 5, 5, 120.0), row("belt squat", 3, 4, 6, 140.0),
            row("chin up", 3, 3, 5),
        )
        self.assertEqual(workout["description"], "\n".join([
            "[Full-Body Strength]",
            "Heavy full-body.",
            "",
            "Belt squat 1×5 @ 120, 3×4–6 @ 140 kg",
            "Chin up 3×3–5",
            "2–3 min rests.",
        ]))
        self.assertEqual(len(workout["prescribed_sets"]), 3)

    def test_a_revision_that_continues_the_session_keeps_its_rows(self):
        self.planned("2026-09-14", row("belt squat", 3, 4, 6, 140.0))
        with test_db.workout_change(kind="adapt") as change:
            change.append(
                date="2026-09-14", sport_type="strength_training",
                title="Full-Body Strength", description="[Full-Body Strength]\nShorter.",
                duration_minutes=40,
            )
        workout = test_db.get_workout("2026-09-14", "strength_training")
        self.assertEqual(workout["duration_minutes"], 40)
        self.assertEqual([r["exercise"] for r in workout["prescribed_sets"]],
                         ["belt squat"])

    def test_a_swap_carries_the_rows_to_the_new_date(self):
        workout = self.planned("2026-09-17", row("belt squat", 3, 4, 6, 140.0))
        runtime.coach_service.workout_swap_apply(
            [{"id": workout["id"], "new_date": "2026-09-18"}], reason="Rain"
        )
        moved = test_db.get_workout("2026-09-18", "strength_training")
        self.assertEqual([r["load_kg"] for r in moved["prescribed_sets"]], [140.0])

    def test_a_restore_brings_back_the_rows_of_the_revision_it_copies(self):
        self.planned("2026-09-17", row("belt squat", 3, 4, 6, 140.0))
        first = test_db.get_workout("2026-09-17", "strength_training")["revision_id"]
        self.planned("2026-09-17", row("belt squat", 3, 4, 6, 145.0))
        with test_db.workout_change(kind="restore") as change:
            change.restore(test_db.get_workout_revision(first))
        back = test_db.get_workout("2026-09-17", "strength_training")
        self.assertEqual([r["load_kg"] for r in back["prescribed_sets"]], [140.0])

    def test_a_void_has_no_rows(self):
        self.planned("2026-09-17", row("belt squat", 3, 4, 6, 140.0))
        with test_db.workout_change(kind="rm") as change:
            change.void(date="2026-09-17", sport_type="strength_training", reason="Away")
        [voided] = test_db.get_workouts(
            start_date="2026-09-17", end_date="2026-09-17", include_removed=True
        )
        self.assertEqual(voided["prescribed_sets"], [])


class SeamTest(_HistoryCase):
    """The week planner is shown the brief and never a kilogram (§9)."""

    def test_the_week_planner_sees_the_title_and_the_brief_only(self):
        from trainmate.coach.formatting import (
            format_planned_workouts_detailed, format_standing_workouts,
        )
        self.planned("2026-09-17", row("belt squat", 3, 4, 6, 140.0))
        workout = test_db.get_workout("2026-09-17", "strength_training")
        for text in (
            format_planned_workouts_detailed([workout]),
            format_standing_workouts([workout], window_end="2026-09-20"),
        ):
            self.assertIn("Heavy full-body.", text)
            self.assertNotIn("140", text)

    def test_a_session_with_no_prescribed_sets_is_shown_whole(self):
        from trainmate.coach.formatting import format_planned_workouts_detailed
        with test_db.workout_change(kind="generate") as change:
            change.append(
                date="2026-09-17", sport_type="running", title="Tempo",
                description="[Tempo]\n40 min.\n\n4×5 min at threshold.",
                duration_minutes=40,
            )
        workout = test_db.get_workout("2026-09-17", "running")
        self.assertIn("4×5 min at threshold.",
                      format_planned_workouts_detailed([workout]))


class StampTest(_HistoryCase):
    """The evidence a kept session's kilograms may change on (§9)."""

    def test_reading_sets_moves_the_stamp_and_a_pass_that_reads_nothing_does_not(self):
        self.lifted("2026-09-14", lift("SQUAT", "BELT_SQUAT", 5, 140))
        stamp = test_db.strength_history_stamp()
        self.assertTrue(stamp)
        sets.read_new_activities(self.garmin)
        self.assertEqual(test_db.strength_history_stamp(), stamp)

    def test_naming_and_discarding_move_it(self):
        activity_id = self.lifted("2026-09-14", lift("SQUAT", "BELT_SQUAT", 5, 140))
        stamp = test_db.strength_history_stamp()
        test_db.set_activity_discarded(activity_id, True)
        self.assertGreater(test_db.strength_history_stamp(), stamp)

    def test_the_reconcile_deleting_a_strength_activity_moves_it(self):
        self.lifted("2026-09-14", lift("SQUAT", "BELT_SQUAT", 5, 140))
        stamp = test_db.strength_history_stamp()
        test_db.prune_completed_activities("2026-09-14", "2026-09-14", [])
        self.assertGreater(test_db.strength_history_stamp(), stamp)


if __name__ == "__main__":
    unittest.main()
