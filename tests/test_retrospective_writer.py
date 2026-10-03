"""The write step and the retrospective writer's prompt (DESIGN_cycle_retrospective.md
§4, §5).
"""
import re
import unittest
from unittest.mock import patch

from tests import test_db_path
from tests.helpers import bind_test_db, clear_all_tables, pin_clock, save_workout

test_db = bind_test_db(test_db_path("test_retrospective_writer.db"))

from stamind import cycle_records
from stamind.coach.service import coach_service
from stamind.db.retrospectives import MESOCYCLE

WRITTEN = {
    "record": "For: build easy volume.\nHappened: load on target.\nCame out: fitness rose.",
    "athlete_line": "You kept your training steady these three weeks.",
}


def _meso(name: str, start: str, end: str) -> dict:
    return {"name": name, "start_date": start, "end_date": end, "focus": f"{name} focus"}


def _activity(activity_id: str, day: str, minutes: int, tss: float) -> None:
    test_db.save_completed_activity(
        activity_id=activity_id, date=day, start_time="08:00:00", activity_name="Ride",
        activity_type="cycling", duration_sec=minutes * 60.0, distance_km=30.0,
        elevation_gain_m=100.0, avg_hr=130, max_hr=150, rpe=4, tss=tss,
    )


class WriterCase(unittest.TestCase):
    """A goal whose first mesocycle, 5 to 25 October, has a blank record."""

    def setUp(self):
        global test_db
        test_db = bind_test_db(test_db_path("test_retrospective_writer.db"), fresh=False)
        clear_all_tables(test_db)
        self.goal = test_db.add_objective("Alpe du Zwift", "2026-12-22", "cycling")
        test_db.save_macrocycle(self.goal, "strategy", "gh", "ch", [
            _meso("Base 1", "2026-09-14", "2026-10-04"),
            _meso("Base 2", "2026-10-05", "2026-10-25"),
            _meso("Build", "2026-10-26", "2026-11-15"),
        ])
        garmin = patch("stamind.runtime.garmin")
        self.garmin = garmin.start()
        self.addCleanup(garmin.stop)

    def _record(self, name: str) -> dict:
        return next(
            r for r in test_db.get_retrospectives(self.goal, MESOCYCLE) if r["name"] == name
        )


class TestWhenARecordIsDue(WriterCase):
    def setUp(self):
        super().setUp()
        cycle_records.date_check(test_db, "2026-10-26")
        self.record = self._record("Base 2")

    def test_it_is_due_seven_days_after_its_end(self):
        self.assertFalse(cycle_records.is_due(self.record, "2026-10-31"))
        self.assertTrue(cycle_records.is_due(self.record, "2026-11-01"))

    def test_it_is_due_sooner_when_it_holds_the_athletes_words(self):
        test_db.set_retrospective_words(self.record["id"], "felt fresh")
        record = test_db.get_retrospective(self.record["id"])
        self.assertTrue(cycle_records.is_due(record, "2026-10-27"))

    def test_a_written_record_is_never_due(self):
        test_db.write_retrospective(self.record["id"], {}, "For: x", "line")
        record = test_db.get_retrospective(self.record["id"])
        self.assertFalse(cycle_records.is_due(record, "2026-12-01"))


class TestTheWriteStep(WriterCase):
    def setUp(self):
        super().setUp()
        pin_clock(self, "2026-11-02")

    @patch("stamind.coach.engine.openrouter_client")
    def test_a_run_writes_one_record_the_oldest_first(self, client):
        client.complete.return_value = dict(WRITTEN)
        coach_service.retrospectives_step()
        self.assertEqual(client.complete.call_count, 1)
        self.assertEqual(self._record("Base 1")["body"], WRITTEN["record"])
        self.assertIsNone(self._record("Base 2")["body"])
        self.assertEqual(self._record("Base 1")["athlete_line"], WRITTEN["athlete_line"])

        coach_service.retrospectives_step()
        self.assertEqual(self._record("Base 2")["body"], WRITTEN["record"])
        coach_service.retrospectives_step()
        self.assertEqual(client.complete.call_count, 2)

    @patch("stamind.coach.engine.openrouter_client")
    def test_a_failed_write_is_tried_again_on_the_next_run(self, client):
        client.complete.side_effect = ValueError("no answer")
        coach_service.retrospectives_step()
        self.assertIsNone(self._record("Base 1")["body"])

        client.complete.side_effect = None
        client.complete.return_value = dict(WRITTEN)
        coach_service.retrospectives_step()
        self.assertEqual(self._record("Base 1")["body"], WRITTEN["record"])

    @patch("stamind.coach.engine.openrouter_client")
    def test_it_refreshes_garmin_for_the_days_of_the_record(self, client):
        client.complete.return_value = dict(WRITTEN)
        coach_service.retrospectives_step()
        self.garmin.ensure_data.assert_called_once_with("2026-09-14", "2026-10-04")

    @patch("stamind.coach.engine.openrouter_client")
    def test_the_numbers_are_totals_over_the_records_own_days(self, client):
        client.complete.return_value = dict(WRITTEN)
        save_workout(test_db, "2026-09-15", "cycling", "Easy ride", duration_minutes=60,
                     tss=40.0)
        save_workout(test_db, "2026-09-17", "cycling", "Long ride", duration_minutes=120,
                     tss=90.0)
        save_workout(test_db, "2026-10-06", "cycling", "Next mesocycle", duration_minutes=60,
                     tss=50.0)
        _activity("a1", "2026-09-15", 60, 42.0)
        _activity("a2", "2026-10-06", 60, 50.0)
        test_db.save_metric_cache("2026-09-14", None, None, None, None, ctl=48.25)
        test_db.save_metric_cache("2026-10-04", None, None, None, None, ctl=52.5)
        test_db.add_benchmark_result("2026-08-01", "cycling", "ftp", 250, "W")
        test_db.add_benchmark_result("2026-10-03", "cycling", "ftp", 262, "W")

        coach_service.retrospectives_step()
        numbers = self._record("Base 1")["numbers"]
        self.assertEqual((numbers["sessions_done"], numbers["sessions_planned"]), (1, 2))
        self.assertEqual(numbers["duration_sec"], 3600.0)
        self.assertEqual(numbers["load_planned"], 130.0)
        self.assertEqual(numbers["load_done"], 42.0)
        self.assertEqual((numbers["fitness_start"], numbers["fitness_end"]), (48.25, 52.5))
        self.assertEqual(
            numbers["benchmarks"], [{"kind": "ftp", "before": 250.0, "after": 262.0}]
        )
        self.assertEqual(
            cycle_records.numbers_line(numbers),
            "Sessions 1 of 2 · load 42 of 130 TSS · 1h00 · fitness 48 -> 52 · "
            "Functional Threshold Power (FTP) 250 W -> 262 W",
        )


class TestTheWritersPrompt(WriterCase):
    def setUp(self):
        super().setUp()
        pin_clock(self, "2026-11-02")
        ride = save_workout(test_db, "2026-09-19", "cycling", "Long ride",
                            duration_minutes=120, tss=90.0)
        test_db.add_session_note(ride, "I stopped at 12:30 in the second round, on purpose")
        _activity("a1", "2026-09-19", 100, 70.0)
        test_db.add_constraint("Work trip", "2026-09-22", "2026-09-25")

    def _prompts(self, client) -> tuple:
        client.complete.return_value = dict(WRITTEN)
        coach_service.retrospectives_step()
        (system, user), kwargs = client.complete.call_args
        self.assertEqual(kwargs["label"], "retrospective_writer")
        return system, user

    @patch("stamind.coach.engine.openrouter_client")
    def test_the_prompt_follows_the_section_rules(self, client):
        system, user = self._prompts(client)
        headings = [line for line in (system + user).splitlines() if line.startswith("#")]
        for heading in headings:
            self.assertRegex(heading, r"^## [A-Z' ]+$")
        self.assertEqual(
            [h for h in headings if h in system.splitlines()],
            ["## TASK", "## RESPONSE FORMAT"],
        )
        self.assertEqual(re.findall(r"^## .*$", user, flags=re.M), [
            "## THE MESOCYCLE", "## WHAT WAS MEASURED",
            "## CONSTRAINTS AND SIGNALS IN THOSE WEEKS",
            "## SESSIONS THE ATHLETE SPOKE ABOUT",
        ])
        self.assertNotIn("SPORTS SCIENCE GUIDELINES", system + user)

    @patch("stamind.coach.engine.openrouter_client")
    def test_a_session_the_athlete_spoke_about_reaches_the_prompt(self, client):
        _, user = self._prompts(client)
        self.assertIn("I stopped at 12:30 in the second round, on purpose", user)
        self.assertIn("Base 1 focus", user)
        self.assertIn("Work trip", user)
        self.assertIn("Volume and load (2026-09-14..2026-10-04)", user)

    @patch("stamind.coach.engine.openrouter_client")
    def test_the_athletes_words_get_their_own_section(self, client):
        cycle_records.date_check(test_db, "2026-11-02")
        test_db.set_retrospective_words(self._record("Base 1")["id"], "felt fresh")
        _, user = self._prompts(client)
        self.assertIn("## THE ATHLETE'S WORDS", user)
        self.assertIn("felt fresh", user)


if __name__ == "__main__":
    unittest.main()
