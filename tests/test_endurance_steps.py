"""A run, a ride or a swim written as steps (DESIGN_endurance_steps.md §11)."""
import copy
import unittest
from unittest.mock import patch

from tests.helpers import clear_all_tables, pin_clock, rebind_test_db, run_cli
from tests import test_db_path

from stamind.db import Database

test_db = Database(db_path=test_db_path("test_endurance_steps.db"))
rebind_test_db(test_db)

from stamind.coach import steps
from stamind.coach.engine.sessions import ask_week_planner
from stamind.coach.formatting import _for_the_week_planner

# Wednesday 4 November's ride (§2, §3).
WEDNESDAY = [
    {"phase": "warm-up", "seconds": 900, "zone": 1, "effort": "easy, building to a sweat",
     "note": "two 1-min lifts to about 93% FTP"},
    {"phase": "work", "repeat": 3, "seconds": 300, "zone": 5,
     "target": {"anchor": "ftp", "low": 106, "high": 112}, "effort": "8/10",
     "recovery": {"seconds": 150, "zone": 1, "effort": "easy"}},
    {"phase": "steady", "seconds": "remainder", "zone": 2,
     "target": {"anchor": "ftp", "low": 66, "high": 74}},
    {"phase": "cool-down", "seconds": 600, "zone": 1, "effort": "easy"},
]
POWER = {"cycling": "power"}

PRINTED = """[Deload HIIT — 3 x 5 min]
0:00     WARM-UP    15 min     easy, building to a sweat
                               two 1-min lifts to about 93% FTP
0:15     WORK       3 × 5 min  106–112% FTP (250–264 W), 8/10
                               2.5 min easy after each
0:37:30  STEADY     27.5 min   66–74% FTP (156–175 W), zone 2
1:05     COOL-DOWN  10 min     easy
                    ─────────
         TOTAL      75 min

Ride the efforts seated on a Zwift climb."""


def _ride(**changes):
    entry = {
        "date": "2026-11-04", "sport_type": "cycling", "title": "Deload HIIT — 3 x 5 min",
        "description": "[Deload HIIT — 3 x 5 min]\nRide the efforts seated on a Zwift climb.",
        "duration_minutes": 75, "steps": copy.deepcopy(WEDNESDAY),
    }
    entry.update(changes)
    return entry


class TestTheCheck(unittest.TestCase):
    def test_wednesday_passes_and_its_remainder_is_27_and_a_half_minutes(self):
        self.assertIsNone(steps.fault(_ride(), POWER))
        self.assertEqual(steps.resolve(WEDNESDAY, 75)[2]["seconds"], 1650)

    def test_a_shape_fault(self):
        two = copy.deepcopy(WEDNESDAY)
        two[0]["seconds"] = "remainder"
        self.assertIn("2 steps are the remainder", steps.fault(_ride(steps=two), POWER))
        self.assertIn("has no steps", steps.fault(_ride(steps=[]), POWER))

    def test_a_fit_fault(self):
        self.assertEqual(
            steps.fault(_ride(duration_minutes=50), POWER),
            "Wed 2026-11-04 cycling: the steps without the remainder take 47.5 of the 50 "
            "minutes, which leaves under 5 for the remainder",
        )
        fixed = [s for s in copy.deepcopy(WEDNESDAY) if s["seconds"] != "remainder"]
        self.assertIn("the steps take 47.5 of the 75 minutes",
                      steps.fault(_ride(steps=fixed), POWER))

    def test_a_zone_fault(self):
        no_zone = copy.deepcopy(WEDNESDAY)
        del no_zone[1]["recovery"]["zone"]
        self.assertIn("the recovery of step 2 has no power zone (1-7)",
                      steps.fault(_ride(steps=no_zone), POWER))
        # A sport with no zone type asks for none.
        self.assertIsNone(steps.fault(_ride(steps=no_zone), {}))

    def test_a_keep_or_a_drop_is_not_checked(self):
        self.assertFalse(steps.writes_steps({"sport_type": "cycling", "keep": True}))
        self.assertFalse(steps.writes_steps({"sport_type": "running", "drop": True}))
        self.assertFalse(steps.writes_steps({"sport_type": "strength_training"}))


class TestTheAsk(unittest.TestCase):
    def _ask(self, *replies):
        with patch("stamind.coach.engine.openrouter_client") as client:
            client.complete.side_effect = list(replies)
            reply = ask_week_planner(
                "system", "user", label="workout_generate", wait_notice="Writing",
                entries=lambda r: r.get("workouts") or [], zone_currencies=POWER,
                profile={"ftp": 236},
            )
        return client.complete, reply

    def test_a_fault_is_asked_once_more_and_the_second_answer_is_kept(self):
        complete, reply = self._ask(
            {"workouts": [_ride(duration_minutes=50)]}, {"workouts": [_ride()]},
        )
        self.assertEqual(complete.call_count, 2)
        again = complete.call_args_list[1].args[1]
        self.assertIn("## YOUR LAST ANSWER", again)
        self.assertIn("## WHAT TO FIX\nWed 2026-11-04 cycling: the steps without", again)
        [entry] = reply["workouts"]
        self.assertEqual(entry["description"], PRINTED)
        self.assertEqual(entry["planned_zone_currency"], "power")
        self.assertEqual(entry["planned_zone_sec"], [1950, 1650, 0, 0, 900, 0, 0])
        self.assertEqual(sum(entry["planned_zone_sec"]), 75 * 60)

    def test_steps_that_fail_twice_are_stored_and_printed_without_zone_minutes(self):
        complete, reply = self._ask(
            {"workouts": [_ride(duration_minutes=45)]},
            {"workouts": [_ride(duration_minutes=45)]},
        )
        self.assertEqual(complete.call_count, 2)
        [entry] = reply["workouts"]
        self.assertEqual(entry["steps"], WEDNESDAY)
        # The remainder gets no time and prints as nothing; the TOTAL is what the rest take.
        self.assertNotIn("STEADY", entry["description"])
        self.assertIn("TOTAL      47.5 min", entry["description"])
        self.assertIsNone(entry["planned_zone_sec"])

    def test_a_session_without_steps_gets_no_zone_minutes(self):
        gym = {"date": "2026-11-05", "sport_type": "strength_training", "title": "Gym",
               "description": "[Gym]", "duration_minutes": 60,
               "planned_zone_currency": "hr", "planned_zone_sec": [600] * 5}
        _, reply = self._ask({"workouts": [_ride(), gym]})
        self.assertIsNone(reply["workouts"][1]["planned_zone_currency"])
        self.assertIsNone(reply["workouts"][1]["planned_zone_sec"])

    def test_steps_that_cannot_be_printed_are_not_stored(self):
        _, reply = self._ask({"workouts": [_ride(steps=[])]}, {"workouts": [_ride(steps=[])]})
        [entry] = reply["workouts"]
        self.assertIsNone(entry["steps"])
        self.assertTrue(entry["description"].startswith("[Deload HIIT"))


class TestPrinting(unittest.TestCase):
    def test_a_heart_rate_target(self):
        run = [{"phase": "work", "seconds": 1200, "zone": 4,
                "target": {"anchor": "lthr", "low": 95, "high": 98}, "effort": "7/10"}]
        self.assertIn("95–98% LTHR (163–169 bpm), 7/10",
                      steps.block(run, "running", 20, {"lthr": 172}))

    def test_a_pace_target(self):
        run = [{"phase": "work", "seconds": 1200, "zone": 4,
                "target": {"anchor": "threshold_pace", "low": 10, "high": 20}}]
        self.assertIn("4:50–5:00/km (threshold + 10–20 s), zone 4",
                      steps.block(run, "running", 20, {"threshold_pace": 4 + 40 / 60}))

    def test_a_swim(self):
        swim = [
            {"phase": "warm-up", "seconds": 300, "metres": 200, "effort": "easy"},
            {"phase": "work", "repeat": 10, "seconds": 115, "metres": 100,
             "target": {"anchor": "css", "low": 5, "high": 5},
             "recovery": {"seconds": 20, "effort": "rest"}},
            {"phase": "cool-down", "seconds": 150, "metres": 100, "effort": "easy"},
        ]
        printed = steps.block(swim, "swimming", 30, {"css": 110})
        self.assertIn("10 × 100 m       1:55/100 m (CSS + 5 s)", printed)
        self.assertIn("20 s rest after each", printed)
        self.assertIn("TOTAL      1,300 m, 30 min", printed)
        # Metres missing on one step: the TOTAL gives the minutes alone.
        del swim[0]["metres"]
        self.assertIn("TOTAL      30 min", steps.block(swim, "swimming", 30, {"css": 110}))

    def test_a_threshold_not_on_record_prints_zone_and_effort(self):
        easy = [{"phase": "steady", "seconds": 600, "zone": 2, "effort": "easy, 3/10",
                 "target": {"anchor": "ftp", "low": 66, "high": 74}}]
        self.assertIn("zone 2, easy, 3/10", steps.block(easy, "cycling", 10, {}))

    def test_the_week_planner_is_shown_the_steps_and_no_watt(self):
        shown = _for_the_week_planner({"description": PRINTED, "steps": WEDNESDAY})
        self.assertNotIn(" W)", shown)
        self.assertTrue(shown.startswith(
            "[Deload HIIT — 3 x 5 min]\nRide the efforts seated on a Zwift climb.\nSteps: ["
        ))


class TestReprint(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        rebind_test_db(test_db)

    def setUp(self):
        clear_all_tables(test_db)
        pin_clock(self, "2026-11-02")
        with test_db.workout_change(kind="tweak", summary="Moved") as change:
            change.append(
                date="2026-11-04", sport_type="cycling", title="Deload HIIT — 3 x 5 min",
                description=PRINTED, duration_minutes=75, short_name="VO2",
                summary="Three hard efforts.", reason="Moved to Wednesday, as asked.",
                steps=WEDNESDAY,
            )
            hr_run = [{"phase": "steady", "seconds": 1800, "zone": 2,
                       "target": {"anchor": "lthr", "low": 80, "high": 85}}]
            change.append(
                date="2026-11-05", sport_type="running", title="Easy Run",
                description=steps.describe("[Easy Run]", "", hr_run, "running", 30, {}),
                duration_minutes=30, steps=hr_run,
            )
        run_cli(["benchmark", "record", "cycling", "--ftp", "236", "--yes"])

    def _ride(self):
        return test_db.get_workout("2026-11-04", "cycling")

    def test_a_new_ftp_reprints_the_ride_as_a_copy(self):
        before = test_db.get_workout("2026-11-05", "running")["description"]
        changes = len(test_db.get_workout_changes())
        run_cli(["benchmark", "record", "cycling", "--ftp", "245", "--yes"])
        ride = self._ride()
        self.assertIn("106–112% FTP (260–274 W)", ride["description"])
        self.assertTrue(ride["description"].endswith("Ride the efforts seated on a Zwift climb."))
        self.assertEqual(ride["modification_reason"], "Moved to Wednesday, as asked.")
        self.assertEqual(ride["short_name"], "VO2")
        self.assertEqual(ride["change_kind"], "tweak")
        newest = test_db.get_workout_changes()[0]
        self.assertEqual((newest["kind"], newest["summary"]),
                         ("reprint", "Your FTP is now 245 W."))
        self.assertEqual(len(test_db.get_workout_changes()), changes + 1)
        self.assertEqual(test_db.get_workout("2026-11-05", "running")["description"], before)

    def test_an_e1rm_writes_no_change(self):
        changes = len(test_db.get_workout_changes())
        run_cli(["benchmark", "record", "strength_training", "--e1rm", "140", "--yes"])
        self.assertEqual(len(test_db.get_workout_changes()), changes)

    def test_deleting_the_only_ftp_prints_zone_and_effort(self):
        [result] = test_db.get_benchmark_results()
        run_cli(["benchmark", "rm", str(result["id"])])
        self.assertIn("8/10", self._ride()["description"])
        self.assertIn("zone 5, 8/10", self._ride()["description"])
        self.assertNotIn(" W)", self._ride()["description"])


if __name__ == "__main__":
    unittest.main()
