"""The Progress page's file (DESIGN_progress_page.md §4.1): its keys, an ended week's grade,
the records, the same content at any width, each sport's time in zone by week and by
mesocycle, the upload after a command, and the button's bytes. The bucket and the month the
file is built in are `tests/test_page_files.py`'s, whose `FilesTestCase` it shares.
"""
import os
import unittest
from unittest.mock import patch

from tests.helpers import run_cli
from tests.test_page_files import (
    BUCKET, FOLDER, KEY, TOKEN, TODAY, FakeBucket, FilesTestCase, test_db, use_storage,
)

from stamind.cli.render import calendar_page, progress_page
from stamind.config import config
from stamind.page_files import recipe, sync


# A reason longer than any terminal line, so a wrapped copy would differ by width.
REASON = ("Your resting heart rate is raised after Friday's illness, so the long ride becomes "
          "an easy spin of forty minutes and the rest of the week stays as it is.")


def _short_ride_week():
    """The week of 21 September: a 120-minute ride written, cut to 40 by an adapt, and a
    40-minute ride done."""
    with test_db.workout_change(kind="generate") as change:
        change.append(date="2026-09-22", sport_type="cycling", title="Long ride",
                      description="Long ride", duration_minutes=120, tss=100)
    lineage = test_db.get_workout("2026-09-22", "cycling")["id"]
    with test_db.workout_change(kind="adapt") as change:
        change.append(date="2026-09-22", sport_type="cycling", title="Long ride",
                      description="Easy spin", duration_minutes=40, tss=30,
                      lineage_id=lineage, reason=REASON)
    test_db.save_completed_activity(
        activity_id="r0922", date="2026-09-22", start_time="2026-09-22 08:00:00",
        activity_name="Ride", activity_type="cycling", duration_sec=2400.0, distance_km=15.0,
        elevation_gain_m=0.0, avg_hr=120, max_hr=140, rpe=3, tss=30.0,
    )


def _records():
    """Build, finished and written with the athlete's answer; Summer, not written yet."""
    goal = test_db.get_objectives()[0]["id"]
    build = test_db.add_retrospective(goal, "mesocycle", "Build", "2026-09-02",
                                      "2026-09-27", "finished", "Build the engine.")
    test_db.write_retrospective(
        build, {"sessions_done": 5, "sessions_planned": 9, "load_done": 237.0,
                "load_planned": 275.0, "duration_sec": 21060.0, "fitness_start": 16.2,
                "fitness_end": 18.4, "benchmarks": []},
        "The athlete completed 5 of 9 sessions.\nThe long rides grew.",
        "You kept your rides going.")
    test_db.set_retrospective_words(build, "felt   fresh")
    test_db.add_retrospective(goal, "mesocycle", "Summer", "2026-08-01", "2026-09-01",
                              "finished", "Keep moving.")


def _ride(day, seconds, **zones):
    test_db.save_completed_activity(
        activity_id=f"ride-{day}", date=day, start_time=f"{day} 08:00:00",
        activity_name="Ride", activity_type="cycling", duration_sec=float(seconds),
        distance_km=30.0, elevation_gain_m=100.0, avg_hr=130, max_hr=160, rpe=4, tss=50.0,
        **zones,
    )


def _zone_history():
    """Five rides in June in heart rate only, a run in June, then three rides with power:
    two in Summer's first weeks, one in Build's."""
    for day in ("2026-06-01", "2026-06-03", "2026-06-05", "2026-06-08", "2026-06-10"):
        _ride(day, 3600, zone1_sec=600, zone2_sec=3000)
    test_db.save_completed_activity(
        activity_id="run-0612", date="2026-06-12", start_time="2026-06-12 08:00:00",
        activity_name="Run", activity_type="running", duration_sec=2400.0, distance_km=6.0,
        elevation_gain_m=10.0, avg_hr=140, max_hr=160, rpe=4, tss=30.0, zone2_sec=2400,
    )
    for day in ("2026-08-05", "2026-08-12"):
        _ride(day, 3600, power_zone2_sec=3000, power_zone3_sec=600)
    _ride("2026-09-08", 3600, power_zone2_sec=2400, power_zone4_sec=1200)


class ProgressFileTest(FilesTestCase):
    """The Progress page's file (DESIGN_progress_page.md §4.1)."""

    def progress(self):
        return sync.build(test_db, TODAY)[sync.PROGRESS]

    def test_the_keys_of_the_file(self):
        file = self.progress()
        self.assertEqual(set(file), {"v", "at", "today", "days", "weeks", "records", "goals",
                                     "mesocycles", "zones"})
        # No sport of the profile has zone data: the Intensity tab's empty state.
        self.assertEqual(file["zones"], [])
        self.assertEqual((file["v"], file["today"]), (1, TODAY))
        self.assertEqual(file["days"][0]["date"], "2026-05-10")
        self.assertEqual(file["days"][-1]["date"], "2026-10-02")
        self.assertEqual(file["goals"], [{"title": "Autumn 10k", "date": "2026-10-18"}])
        self.assertEqual([m["label"] for m in file["mesocycles"]], ["Summer", "Build", "Taper"])
        this_week = next(w for w in file["weeks"] if w["monday"] == "2026-09-28")
        self.assertTrue(this_week["under_way"])
        self.assertNotIn("grade", this_week)

    def test_an_ended_week_carries_its_grade_in_the_terminals_words(self):
        _short_ride_week()
        week = next(w for w in self.progress()["weeks"] if w["monday"] == "2026-09-21")
        self.assertEqual(week["planned"], 100.0)
        self.assertFalse(week["under_way"] or week["ahead"])
        [ride] = week["grade"]
        self.assertEqual((ride["icon"], ride["percent"], ride["short"]), ("🚴", 30, True))
        self.assertEqual(ride["line"], "cycling: written 100, done 30 (30%), short")
        [changed] = ride["changed"]
        self.assertTrue(changed.startswith("Tue 22 Sep Long ride: cut from 120 to 40 min, "))
        self.assertIn(REASON, changed)

    def test_the_file_is_the_same_built_at_80_and_at_900_columns(self):
        _short_ride_week()
        _records()
        built = []
        for width in ("80", "900"):
            with patch.dict(os.environ, {"STAMIND_WRAP_WIDTH": width}):
                built.append(sync.fingerprint(self.progress()))
        self.assertEqual(built[0], built[1])

    def test_a_record_with_the_athletes_answer_and_one_not_written_yet(self):
        _records()
        build, summer = self.progress()["records"]
        self.assertEqual(build["name"], "Build")
        self.assertEqual(build["first"], "Sessions 5 of 9 · load 237 of 275 TSS · 5h51 · "
                                         "fitness 16 -> 18 · no test")
        self.assertEqual(build["lines"], ["The athlete completed 5 of 9 sessions.",
                                          "The long rides grew."])
        self.assertEqual(build["said"], "You kept your rides going.")
        self.assertEqual(build["answer"], 'Athlete: "felt fresh"')
        self.assertEqual(summer, {"name": "Summer", "start": "2026-08-01",
                                  "end": "2026-09-01", "ended": "finished"})

    def test_a_record_without_an_answer_has_none(self):
        _records()
        build = self.progress()["records"][0]
        test_db.set_retrospective_words(test_db.get_retrospectives()[-1]["id"], None)
        self.assertNotIn("answer", self.progress()["records"][0])
        self.assertIn("answer", build)

    def test_built_after_a_command_and_uploaded_only_when_it_changed(self):
        use_storage(self)
        run_cli(["data", "publish"])
        FakeBucket.uploads.clear()
        key = recipe.page_key(TOKEN)
        sync.after_command()
        self.assertEqual(FakeBucket.uploads, [])
        _records()
        sync.after_command()
        self.assertEqual(FakeBucket.uploads, [recipe.file_name(key, sync.PROGRESS)])

    def test_intensity_zones_come_from_the_last_8_weeks_and_a_sport_from_before_them_stays(self):
        # Rides in June in heart rate only, then rides with a power meter from August: over
        # the whole history heart rate covers more, over the last 8 weeks power does
        # (choice 16). A run in June only still has its chart.
        _zone_history()
        profile = {**config.user_profile, "sport_preferences": ["cycling", "running", "yoga"]}
        with patch.dict(config.data, {"user_profile": profile}):
            zones = self.progress()["zones"]
        self.assertEqual([(z["sport"], z["currency"]) for z in zones],
                         [("cycling", "power"), ("running", "hr")])
        ride = next(w for w in zones[0]["weeks"] if w["week_commencing"] == "2026-08-10")
        self.assertEqual(ride["seconds"], [0, 3000, 600, 0, 0, 0, 0])
        june = next(w for w in zones[0]["weeks"] if w["week_commencing"] == "2026-06-01")
        self.assertEqual((june["seconds"], june["undercounted"]), (None, True))

    def test_each_mesocycles_average_week_in_zone(self):
        # Summer's rate window is its first four whole weeks, Build's its first three; Taper
        # has run two days and holds no ride.
        _zone_history()
        profile = {**config.user_profile, "sport_preferences": ["cycling"]}
        with patch.dict(config.data, {"user_profile": profile}):
            [cycling] = self.progress()["zones"]
        rates = {m["name"]: (m["weeks"], m["seconds"]) for m in cycling["mesocycles"]}
        self.assertEqual(rates["Summer"], (4, [0, 1500, 300, 0, 0, 0, 0]))
        self.assertEqual(rates["Build"], (3, [0, 800, 0, 400, 0, 0, 0]))
        self.assertEqual(rates["Taper"], (0, None))
        self.assertEqual(cycling["mesocycles"][1]["focus"], "Build the engine.\n\nMost of it "
                                                            "easy, one quality day a week.")

    def test_the_button_fits_the_256_bytes_taken_from_the_calendar(self):
        # DESIGN_progress_page.md §5: the keyboard's worst case does not grow.
        use_storage(self)
        run_cli(["data", "publish"])
        url = progress_page.progress_url(sync.button_params(test_db))
        self.assertEqual(url, f"{progress_page.PAGE_URL}#k={KEY}&b={BUCKET}&f={FOLDER}")
        self.assertLessEqual(len(url.encode()) + len("📈 Progress".encode()), 256)
        self.assertEqual(calendar_page.BUDGET_BYTES, 5 * 1024 - 256)


if __name__ == "__main__":
    unittest.main()
