"""A past strength session, planned against done (DESIGN_strength_planned_vs_done.md): which
sets count (§3), the logged activity pairing first (§5), the verdict by sets (§6), and the
table and the companion lines (§2, §7). Thursday 24 September is the design's logged day."""
import json
import os
import shutil
import tempfile
import unittest
from datetime import datetime
from unittest.mock import patch

from tests import test_db_path
from tests.helpers import clear_all_tables, rebind_test_db, run_cli, save_workout

TEST_DB_PATH = test_db_path("test_strength_comparison.db")

from stamind.db import Database
import stamind_cli  # noqa: F401 — the CLI binds its handles at import, before the rebind

from stamind import settings
from stamind.analytics.adherence import analyze_adherence, classify_adherence
from stamind.cli.common import strength_table
from stamind.cli.render import session_lines
from stamind.db.strength import logged_sets
from stamind.strength import comparison, sets

if os.path.exists(TEST_DB_PATH):
    os.remove(TEST_DB_PATH)
test_db = Database(db_path=TEST_DB_PATH)
rebind_test_db(test_db)


def tearDownModule():
    try:
        os.remove(TEST_DB_PATH)
    except OSError:
        pass


GYM_DAY = "2026-09-24"
REVISION = 744


def line(position, exercise, count, low, high, load_kg):
    return {"position": position, "exercise": exercise, "sets": count, "reps_low": low,
            "reps_high": high, "load_kg": load_kg}


# Thursday's session: 7 exercises in 17 sets (§2).
THURSDAY = [
    line(1, "barbell push press", 1, 5, 5, 55.0),
    line(2, "barbell push press", 2, 4, 6, 67.5),
    line(3, "lat pulldown", 1, 6, 6, 100.0),
    line(4, "lat pulldown", 2, 4, 6, 110.0),
    line(5, "seated barbell shoulder press", 2, 4, 6, 40.0),
    line(6, "row", 2, 4, 6, 110.0),
    line(7, "chest fly", 3, 5, 5, 55.0),
    line(8, "glute bridge", 2, 4, 6, 115.0),
    line(9, "ab twist", 2, 20, 20, 30.0),
]

# What the athlete ticked on the logger page that Thursday: the chest press on both push
# press cards, a light first set on the shoulder press and the row, and a plank no card
# asked for.
THURSDAY_LOG = {
    "v": 1, "r": REVISION, "d": GYM_DAY, "st": "10:03", "en": "10:41",
    "x": [
        {"n": "chest press", "p": 1, "sets": [[5, 55, None]]},
        {"n": "chest press", "p": 2, "sets": [[7, 65, None], [7, 65, None]]},
        {"n": "lat pulldown", "p": 3, "sets": [[6, 100, None]]},
        {"n": "lat pulldown", "p": 4, "sets": [[6, 110, None], [6, 110, None]]},
        {"n": "seated barbell shoulder press", "p": 5,
         "sets": [[6, 30, None], [6, 40, None], [5, 40, None]]},
        {"n": "row", "p": 6, "sets": [[6, 95, None], [6, 110, None], [6, 110, None]]},
        {"n": "chest fly", "p": 7, "sets": [[5, 50, None]] * 3},
        {"n": "glute bridge", "p": 8,
         "sets": [[6, 110, None], [6, 115, None], [6, 115, None]]},
        {"n": "ab twist", "p": 9, "sets": [[20, 15, None], [20, 20, None]]},
        {"n": "plank", "sets": [[120, None, None]]},
    ],
}


def watched(exercise, reps, load_kg, named_by="garmin"):
    """A set the watch recorded: no card."""
    return {"exercise": exercise, "reps": reps, "load_kg": load_kg, "duration_sec": None,
            "named_by": named_by, "card": None}


def thursday_session(**changes):
    return {"date": GYM_DAY, "sport_type": "strength_training",
            "title": "Strength — Light, Legs Fresh", "duration_minutes": 50, "tss": 20,
            "rpe": 4, "prescribed_sets": THURSDAY, "revision_id": REVISION, "id": 439,
            **changes}


def thursday_activity(**changes):
    """Garmin's activity once it took the log: heart rate covered little of it, so its
    load reads 7 against 20 planned."""
    return {"activity_id": "g744", "date": GYM_DAY, "start_time": f"{GYM_DAY} 10:03:00",
            "activity_name": "Strength", "activity_type": "strength_training",
            "duration_sec": 38 * 60.0, "tss": 7.0, "rpe": None,
            "lifted": logged_sets(json.dumps(THURSDAY_LOG)),
            "gym_log": {"revision_id": REVISION}, **changes}


def by_exercise(compared):
    return {row.exercise: row for row in compared.rows}


class CountTest(unittest.TestCase):
    """Which sets count (§3)."""

    def setUp(self):
        self.compared = comparison.compare(THURSDAY, logged_sets(json.dumps(THURSDAY_LOG)))
        self.rows = by_exercise(self.compared)

    def test_thursday_counts_15_of_17(self):
        self.assertEqual((self.compared.counted, self.compared.planned), (15, 17))
        self.assertEqual(self.compared.lifted, 21)

    def test_each_exercise_gets_its_mark(self):
        marks = {name: row.mark for name, row in self.rows.items()}
        self.assertEqual(marks, {
            "barbell push press": comparison.SWAPPED,
            "lat pulldown": comparison.DONE,
            "seated barbell shoulder press": comparison.DONE,
            "row": comparison.DONE,
            "chest fly": comparison.DONE,
            "glute bridge": comparison.DONE,
            "ab twist": comparison.LIGHTER,
            "plank": comparison.NOT_PLANNED,
        })

    def test_the_planned_exercises_come_first_in_the_sessions_order(self):
        self.assertEqual([row.exercise for row in self.compared.rows][-2:],
                         ["ab twist", "plank"])

    def test_a_light_first_set_is_an_extra_not_a_miss(self):
        """95 kg is not near 110 (the limit is 99); the two sets at 110 fill the line."""
        row = self.rows["row"]
        self.assertEqual((len(row.sets), row.counted, row.planned), (3, 2, 2))

    def test_a_swap_counts_on_its_cards_with_no_load_check(self):
        row = self.rows["barbell push press"]
        self.assertEqual((row.counted, row.planned), (3, 3))
        self.assertTrue(row.swapped)

    def test_nine_percent_under_counts(self):
        self.assertEqual(self.rows["chest fly"].counted, 3)

    def test_more_than_ten_percent_under_does_not(self):
        row = self.rows["ab twist"]
        self.assertEqual((row.counted, row.planned), (0, 2))

    def test_a_set_with_no_card_counts_by_name_heaviest_first(self):
        """Monday's belt squat: the two sets at 130 fill the working line, and 110, not
        near 125, falls to the warm-up line (§3)."""
        lines = [line(1, "belt squat", 1, 5, 5, 110.0), line(2, "belt squat", 2, 4, 6, 125.0)]
        lifted = [watched("belt squat", 5, 110.0), watched("belt squat", 6, 130.0),
                  watched("belt squat", 6, 130.0)]
        row = comparison.compare(lines, lifted).rows[0]
        self.assertEqual((row.counted, row.mark), (3, comparison.DONE))

    def test_a_set_with_no_load_recorded_counts(self):
        compared = comparison.compare([line(1, "row", 2, 4, 6, 110.0)],
                                      [watched("row", 6, None), watched("row", 6, None)])
        self.assertEqual(compared.counted, 2)

    def test_fewer_sets_than_planned_is_marked_sets(self):
        compared = comparison.compare([line(1, "row", 2, 4, 6, 110.0)],
                                      [watched("row", 6, 110.0)])
        self.assertEqual(compared.rows[0].mark, comparison.SHORT)

    def test_nothing_lifted_is_not_done(self):
        compared = comparison.compare([line(1, "row", 2, 4, 6, 110.0)], [])
        self.assertEqual(compared.rows[0].mark, comparison.NOT_DONE)

    def test_unnamed_sets_are_kept_by_their_position(self):
        compared = comparison.compare([line(1, "row", 1, 4, 6, 110.0)], [
            watched("row", 6, 110.0), watched(None, 8, 40.0), watched(None, 8, 40.0),
        ])
        self.assertEqual(compared.unnamed, [2, 3])

    def test_a_log_against_another_revision_counts_by_name(self):
        """The session was rewritten after the page was opened: the cards point at lines of
        an older revision, so the chest press no longer stands for the push press."""
        compared = comparison.compare_session(thursday_session(revision_id=745),
                                              thursday_activity())
        rows = by_exercise(compared)
        self.assertEqual(rows["barbell push press"].mark, comparison.NOT_DONE)
        self.assertEqual(rows["chest press"].mark, comparison.NOT_PLANNED)
        self.assertEqual(compared.counted, 12)

    def test_the_totals_line(self):
        self.assertEqual(comparison.totals_line(self.compared, by_sets=True),
                         "15 of 17 planned sets · 6 of 7 exercises")
        self.assertEqual(comparison.totals_line(self.compared, by_sets=False),
                         "15 of 17 planned sets · 6 of 7 exercises · graded by time and load")


class VerdictTest(unittest.TestCase):
    """The verdict (§6) and the pairing (§5)."""

    def test_a_logged_session_at_88_percent_is_done_whatever_its_load(self):
        verdict = classify_adherence(thursday_session(), thursday_activity())
        self.assertEqual(verdict, {"status": "done", "reasons": []})

    def test_a_logged_session_below_80_percent_is_partial_with_one_reason(self):
        light = [dict(watched(row["exercise"], 5, 1.0), card=row["position"])
                 for row in THURSDAY for _ in range(row["sets"])]
        verdict = classify_adherence(thursday_session(), thursday_activity(lifted=light))
        self.assertEqual(verdict["status"], "partial")
        self.assertEqual(verdict["reasons"], [
            "sets: 0 of 17 planned sets near their load (0%, below 80%); 17 lifted",
        ])

    def test_a_session_the_watch_recorded_alone_keeps_the_time_and_load_verdict(self):
        verdict = classify_adherence(thursday_session(), thursday_activity(gym_log=None))
        self.assertEqual(verdict["status"], "partial")
        self.assertTrue(verdict["reasons"][0].startswith("workload mismatch"))

    def _pair(self, activities):
        _, results, _ = analyze_adherence(
            [thursday_session()], activities, datetime(2026, 9, 24).date(), 1,
            minor_activity_load_threshold=25.0,
        )
        return results[0]

    def test_the_logged_activity_pairs_before_a_heavier_warm_up(self):
        """The placeholder costs 0 and the indoor cardio warm-up more; the log wins."""
        warm_up = {"activity_id": "w1", "date": GYM_DAY, "activity_type": "indoor_cardio",
                   "activity_name": "Warm-up", "duration_sec": 8 * 60.0, "tss": None,
                   "rpe": 3}
        placeholder = thursday_activity(activity_id="log:" + GYM_DAY, tss=None,
                                        duration_sec=10 * 60.0)
        result = self._pair([warm_up, placeholder])
        self.assertEqual(result["completed"]["activity_id"], "log:" + GYM_DAY)
        self.assertFalse(result["ambiguous"])

    def test_a_short_activity_with_no_log_is_still_a_question(self):
        result = self._pair([thursday_activity(gym_log=None, duration_sec=10 * 60.0)])
        self.assertTrue(result["ambiguous"])


class RenderTest(unittest.TestCase):
    """The table and the companion lines (§2)."""

    def test_the_table_has_one_row_per_exercise_then_the_totals(self):
        with patch("stamind.text.is_narrow_client", return_value=False):
            table = strength_table(thursday_session(), thursday_activity())
        self.assertEqual([cell.strip() for cell in table[0].split(" | ")][:3],
                         ["Exercise", "Planned", "Done"])
        rows = [[cell.strip() for cell in text.split(" | ")] for text in table[2:-1]]
        self.assertEqual(rows[0], [
            "barbell push press", "1×5 @ 55, 2×4–6 @ 67.5",
            "chest press 1×5 @ 55, 2×7 @ 65", "swapped",
        ])
        self.assertEqual(rows[3], ["row", "2×4–6 @ 110", "1×6 @ 95, 2×6 @ 110", "✓"])
        self.assertEqual(rows[6][3], "lighter 0/2")
        self.assertEqual(rows[7], ["plank", "", "1×120", "not planned"])
        self.assertEqual(table[-1], "15 of 17 planned sets · 6 of 7 exercises")

    def test_a_session_with_no_planned_lines_has_no_table(self):
        self.assertEqual(
            strength_table(thursday_session(prescribed_sets=[]), thursday_activity()), []
        )

    def test_done_lately_lists_what_differed(self):
        result = {"date": GYM_DAY, "planned": thursday_session(),
                  "completed": thursday_activity(), "pending": False}
        lines = session_lines.simple_compare_lines(
            [(GYM_DAY, [result], [])], GYM_DAY, GYM_DAY, "2026-09-26",
        )
        self.assertEqual(lines[1:7], [
            "Thu 24 · ✅ 🏋️ Strength — Light, Legs Fresh — 50 min (you did 38 min)",
            "      15 of 17 planned sets · 6 of 7 exercises",
            "      ✅ Lat pulldown, seated barbell shoulder press, row, chest fly, glute bridge",
            "      ✅ Chest press instead of barbell push press",
            "      ❌ Ab twist, lighter: 1×20 @ 15, 1×20 @ 20 (planned 2×20 @ 30)",
            "      ➕ Plank 1×120",
        ])

    def test_the_companion_names_a_short_exercise_with_its_sets(self):
        compared = comparison.compare([line(1, "row", 2, 4, 6, 110.0)],
                                      [watched("row", 6, 110.0)])
        self.assertEqual(session_lines.simple_comparison_lines(compared, by_sets=False)[1:],
                         ["❌ Row, 1 of 2 sets: 1×6 @ 110"])


class _DatabaseCase(unittest.TestCase):
    """Thursday in the database: the session, the log ingested at 10:41, and the clock."""

    def setUp(self):
        rebind_test_db(test_db)
        clear_all_tables(test_db)
        self.now = datetime(2026, 9, 24, 20, 0).astimezone()
        clock = patch("stamind.clock.now", side_effect=lambda: self.now)
        clock.start()
        self.addCleanup(clock.stop)
        settings.write(settings.STRENGTH_SETS_SINCE, "2026-09-01")
        self.directory = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, self.directory, True)
        save_workout(
            test_db, date=GYM_DAY, sport_type="strength_training",
            title="Strength — Light, Legs Fresh", duration_minutes=50, tss=20,
            description="Light upper body, legs fresh.",
            prescribed_sets=[{k: v for k, v in row.items() if k != "position"}
                             for row in THURSDAY],
        )
        self.workout = test_db.get_workout(GYM_DAY, "strength_training")

    def ingest(self):
        path = os.path.join(self.directory, "log.json")
        with open(path, "w", encoding="utf-8") as handle:
            json.dump({**THURSDAY_LOG, "r": self.workout["revision_id"]}, handle)
        code, out, err = run_cli(["strength", "ingest", path])
        self.assertEqual(code, 0, err)
        return out

    def garmin_activity(self, activity_id="g744", tss=7.0):
        test_db.save_completed_activity(
            activity_id=activity_id, date=GYM_DAY, start_time=f"{GYM_DAY} 10:03:00",
            activity_name="Strength", activity_type="strength_training",
            duration_sec=38 * 60.0, distance_km=0.0, elevation_gain_m=0.0,
            avg_hr=None, max_hr=None, rpe=None, tss=tss,
        )


class NoGarmin:
    def get_activity_exercise_sets(self, activity_id):
        raise AssertionError(f"asked Garmin for {activity_id}")


class DatabaseTest(_DatabaseCase):
    """The lifted sets on the activity (§8) and the takeover on the day itself (§5)."""

    def test_the_log_reaches_the_activity_with_its_cards(self):
        self.ingest()
        activity = test_db.get_completed_activities(GYM_DAY, GYM_DAY)[0]
        self.assertEqual(activity["gym_log"], {"revision_id": self.workout["revision_id"]})
        self.assertEqual(activity["lifted"][0], {
            "exercise": "chest press", "reps": 5, "load_kg": 55.0, "duration_sec": None,
            "named_by": "athlete", "card": 1,
        })
        self.assertIsNone(activity["lifted"][-1]["card"])

    def test_a_watch_only_activity_carries_its_rows_and_no_log(self):
        self.garmin_activity()
        test_db.store_exercise_sets("g744", [
            {"seq": 1, "set_type": "active", "exercise": "row", "reps": 6, "load_kg": 110.0,
             "named_by": "watch"},
            {"seq": 2, "set_type": "rest", "duration_sec": 90.0},
        ], self.now, self.now)
        activity = test_db.get_completed_activities(GYM_DAY, GYM_DAY)[0]
        self.assertIsNone(activity["gym_log"])
        self.assertEqual(activity["lifted"], [
            {"exercise": "row", "reps": 6, "load_kg": 110.0, "duration_sec": None,
             "named_by": "watch", "card": None},
        ])

    def test_an_activity_whose_sets_are_not_read_carries_nothing(self):
        self.garmin_activity()
        self.assertNotIn("lifted", test_db.get_completed_activities(GYM_DAY, GYM_DAY)[0])

    def test_garmins_activity_takes_the_log_the_same_evening(self):
        self.ingest()
        self.garmin_activity()
        sets.read_new_activities(NoGarmin())
        self.assertIsNone(test_db.get_completed_activity("log:" + GYM_DAY))
        activity = test_db.get_completed_activities(GYM_DAY, GYM_DAY)[0]
        self.assertEqual(activity["activity_id"], "g744")
        self.assertIsNotNone(activity["gym_log"])


class CommandTest(_DatabaseCase):
    """Saturday: the screens that show Thursday (§7)."""

    def setUp(self):
        super().setUp()
        self.ingest()
        self.garmin_activity()
        sets.read_new_activities(NoGarmin())
        self.now = datetime(2026, 9, 26, 9, 0).astimezone()

    def test_workout_show_draws_the_table_under_the_actual_line(self):
        code, out, err = run_cli(["workout", "show", str(self.workout["id"]), "--no-pull"])
        self.assertEqual(code, 0, err)
        self.assertIn("[DONE]", out)
        self.assertIn("15 of 17 planned sets · 6 of 7 exercises", out)
        self.assertNotIn("Discrepancy:", out)
        self.assertLess(out.index("Actual:"), out.index("barbell push press"))

    def test_workout_compare_draws_the_table_in_place_of_the_set_lines(self):
        code, out, err = run_cli(
            ["workout", "compare", "-d", GYM_DAY, "--no-pull", "--no-mark"]
        )
        self.assertEqual(code, 0, err)
        self.assertIn("15 of 17 planned sets · 6 of 7 exercises", out)
        self.assertNotIn("chest press 1×5 @ 55, 2×7 @ 65 ", out.split("ACTUAL")[0])
        self.assertIn("No discrepancies found", out)


if __name__ == "__main__":
    unittest.main()
