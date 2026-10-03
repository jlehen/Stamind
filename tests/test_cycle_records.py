"""The date check creates the retrospective records and removes those that became wrong
(DESIGN_cycle_retrospective.md §3).
"""
import unittest
from unittest.mock import patch

from tests import test_db_path
from tests.helpers import bind_test_db, clear_all_tables, pin_clock

test_db = bind_test_db(test_db_path("test_cycle_records.db"))

from stamind import clock, cycle_records
from stamind.coach.service import coach_service
from stamind.db.retrospectives import CALLED_OFF, FINISHED, MESOCYCLE, REPLACED


def _meso(name: str, start: str, end: str) -> dict:
    return {"name": name, "start_date": start, "end_date": end, "focus": f"{name} focus"}


def _plan(goal_id: int, *mesocycles: dict) -> int:
    return test_db.save_macrocycle(goal_id, "strategy", "gh", "ch", list(mesocycles))


def _replaced_at(version_id: int, stamp: str) -> None:
    """Dates the moment a plan version was replaced."""
    with test_db._get_connection() as conn:
        conn.execute(
            "UPDATE macrocycles SET superseded_at = ? WHERE id = ?", (stamp, version_id)
        )
        conn.commit()


def _records(goal_id: int) -> list:
    return [
        (r["name"], r["start_date"], r["end_date"], r["ended_by"])
        for r in test_db.get_retrospectives(goal_id, MESOCYCLE)
    ]


class TestDateCheck(unittest.TestCase):
    def setUp(self):
        global test_db
        test_db = bind_test_db(test_db_path("test_cycle_records.db"), fresh=False)
        clear_all_tables(test_db)
        self.goal = test_db.add_objective("Alpe du Zwift", "2026-12-22", "cycling")

    def test_a_mesocycle_that_reached_its_end_gets_a_record_however_short(self):
        _plan(self.goal, _meso("Race week", "2026-10-20", "2026-10-25"),
              _meso("Base", "2026-10-26", "2026-11-15"))
        cycle_records.date_check(test_db, "2026-10-26")
        self.assertEqual(
            _records(self.goal), [("Race week", "2026-10-20", "2026-10-25", FINISHED)]
        )
        self.assertEqual(
            test_db.get_retrospectives(self.goal)[0]["intent"], "Race week focus"
        )

    def test_a_second_run_creates_nothing(self):
        _plan(self.goal, _meso("Base", "2026-10-05", "2026-10-25"))
        cycle_records.date_check(test_db, "2026-10-26")
        cycle_records.date_check(test_db, "2026-10-27")
        self.assertEqual(len(_records(self.goal)), 1)

    def test_a_dropped_mesocycle_is_recorded_as_cut_short(self):
        first = _plan(self.goal, _meso("Base", "2026-09-07", "2026-09-27"))
        _plan(self.goal, _meso("Rebuild", "2026-09-18", "2026-10-11"))
        _replaced_at(first, "2026-09-18T09:00:00+00:00")
        cycle_records.date_check(test_db, "2026-09-19")
        self.assertEqual(
            _records(self.goal), [("Base", "2026-09-07", "2026-09-17", REPLACED)]
        )

    def test_a_mesocycle_dropped_before_seven_trained_days_gets_none(self):
        first = _plan(self.goal, _meso("Base", "2026-09-07", "2026-09-27"))
        _plan(self.goal, _meso("Rebuild", "2026-09-13", "2026-10-11"))
        _replaced_at(first, "2026-09-13T09:00:00+00:00")
        cycle_records.date_check(test_db, "2026-09-14")
        self.assertEqual(_records(self.goal), [])

    def test_a_kept_mesocycle_creates_none(self):
        first = _plan(self.goal, _meso("Base", "2026-09-07", "2026-09-27"))
        _plan(self.goal, _meso("Base, reworded", "2026-09-07", "2026-09-27"))
        _replaced_at(first, "2026-09-18T09:00:00+00:00")
        cycle_records.date_check(test_db, "2026-09-19")
        self.assertEqual(_records(self.goal), [])

    def test_the_version_replaced_last_gives_the_end(self):
        first = _plan(self.goal, _meso("Base", "2026-09-07", "2026-09-27"))
        second = _plan(self.goal, _meso("Base", "2026-09-07", "2026-09-27"))
        _plan(self.goal, _meso("Rebuild", "2026-09-20", "2026-10-11"))
        _replaced_at(first, "2026-09-15T09:00:00+00:00")
        _replaced_at(second, "2026-09-20T09:00:00+00:00")
        cycle_records.date_check(test_db, "2026-09-21")
        self.assertEqual(
            _records(self.goal), [("Base", "2026-09-07", "2026-09-19", REPLACED)]
        )

    def test_a_version_replaced_at_half_past_midnight_counts_for_that_day(self):
        """00:30 on Monday 14 September in Paris is still Sunday in UTC. Read in UTC, six
        days were trained and the mesocycle gets no record."""
        test_db.set_setting(clock.TIMEZONE_SETTING, "Europe/Paris")
        clock.reset_cache()
        self.addCleanup(clock.reset_cache)
        first = _plan(self.goal, _meso("Base", "2026-09-07", "2026-09-27"))
        _plan(self.goal, _meso("Rebuild", "2026-09-14", "2026-10-11"))
        _replaced_at(first, "2026-09-13T22:30:00+00:00")
        cycle_records.date_check(test_db, "2026-09-14")
        self.assertEqual(
            _records(self.goal), [("Base", "2026-09-07", "2026-09-13", REPLACED)]
        )

    def test_a_record_the_current_plan_contradicts_is_removed(self):
        """`plan generate` drops the mesocycle, then `plan rollback` brings it back."""
        first = _plan(self.goal, _meso("Base", "2026-09-07", "2026-09-27"))
        second = _plan(self.goal, _meso("Rebuild", "2026-09-18", "2026-10-11"))
        _replaced_at(first, "2026-09-18T09:00:00+00:00")
        cycle_records.date_check(test_db, "2026-09-19")
        self.assertEqual(len(_records(self.goal)), 1)

        test_db.set_active_macrocycle(first)
        _replaced_at(second, "2026-09-20T09:00:00+00:00")
        cycle_records.date_check(test_db, "2026-09-21")
        self.assertEqual(_records(self.goal), [])
        cycle_records.date_check(test_db, "2026-09-28")
        self.assertEqual(
            _records(self.goal), [("Base", "2026-09-07", "2026-09-27", FINISHED)]
        )

    def test_a_record_the_current_plan_does_not_contradict_stays(self):
        """Two runs of `plan generate`, then a rollback of one step: the version that
        comes back does not hold the mesocycle either."""
        first = _plan(self.goal, _meso("Base", "2026-09-07", "2026-09-27"))
        second = _plan(self.goal, _meso("Rebuild", "2026-09-18", "2026-10-11"))
        third = _plan(self.goal, _meso("Rebuild again", "2026-09-18", "2026-10-04"))
        _replaced_at(first, "2026-09-18T09:00:00+00:00")
        _replaced_at(second, "2026-09-18T09:10:00+00:00")
        cycle_records.date_check(test_db, "2026-09-19")
        test_db.set_active_macrocycle(second)
        _replaced_at(third, "2026-09-20T09:00:00+00:00")
        cycle_records.date_check(test_db, "2026-09-21")
        self.assertEqual(
            _records(self.goal), [("Base", "2026-09-07", "2026-09-17", REPLACED)]
        )


class TestCallingAGoalOff(unittest.TestCase):
    def setUp(self):
        global test_db
        test_db = bind_test_db(test_db_path("test_cycle_records.db"), fresh=False)
        clear_all_tables(test_db)
        self.goal = test_db.add_objective("Alpe du Zwift", "2026-12-22", "cycling")
        _plan(self.goal, _meso("Base", "2026-09-07", "2026-09-27"),
              _meso("Build", "2026-09-28", "2026-10-18"),
              _meso("Peak", "2026-10-19", "2026-11-08"))

    def _call_off(self, day: str) -> None:
        pin_clock(self, day)
        test_db.update_objective(self.goal, status="archived")
        with patch("stamind.runtime.calendar_syncer"):
            coach_service.goal_archive(self.goal)

    def test_it_records_what_ended_and_the_mesocycle_under_way(self):
        self._call_off("2026-10-10")
        self.assertEqual(_records(self.goal), [
            ("Base", "2026-09-07", "2026-09-27", FINISHED),
            ("Build", "2026-09-28", "2026-10-09", CALLED_OFF),
        ])

    def test_a_called_off_goal_gets_no_later_record(self):
        self._call_off("2026-10-10")
        cycle_records.date_check(test_db, "2026-11-20")
        self.assertEqual(len(_records(self.goal)), 2)

    def test_a_goal_brought_back_loses_its_cut_short_record(self):
        self._call_off("2026-10-10")
        test_db.update_objective(self.goal, status="active")
        cycle_records.date_check(test_db, "2026-10-12")
        self.assertEqual(
            _records(self.goal), [("Base", "2026-09-07", "2026-09-27", FINISHED)]
        )


class TestRecordsGoWithTheirPlan(unittest.TestCase):
    def setUp(self):
        global test_db
        test_db = bind_test_db(test_db_path("test_cycle_records.db"), fresh=False)
        clear_all_tables(test_db)
        self.goal = test_db.add_objective("Alpe du Zwift", "2026-12-22", "cycling")
        _plan(self.goal, _meso("Base", "2026-10-05", "2026-10-25"))
        cycle_records.date_check(test_db, "2026-10-26")

    def test_plan_rm_deletes_the_goals_records(self):
        test_db.delete_macrocycle_for_objective(self.goal)
        self.assertEqual(test_db.get_retrospectives(), [])

    def test_plan_wipe_empties_the_table(self):
        test_db.wipe_plans()
        self.assertEqual(test_db.get_retrospectives(), [])

    def test_purging_the_goal_deletes_its_records(self):
        test_db.delete_objective(self.goal)
        self.assertEqual(test_db.get_retrospectives(), [])


if __name__ == "__main__":
    unittest.main()
