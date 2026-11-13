"""The calendar against what `workout generate` wrote (DESIGN_calendar_as_written.md): each
cell's fill and corner (§2), the day's sheet (§3), the week's numbers (§2) and `sm calendar`
(§4).

The weeks are the design's. It is Friday 13 November 2026. Wednesday 4's HIIT ride and
Thursday 5's yoga swapped days; Friday 6's light gym session was dropped for a rest day, the
athlete unwell; Saturday 7's 120-minute gravel ride went to Sunday 8, cut to 40 minutes, and
was ridden for 72. On Monday 9 the athlete asked for rest: the heavy gym session moved to
Friday 13 in place of the light one. Tuesday 10's easy ride moved to Thursday 12 and back.
Wednesday 11 became rest for a low HRV, its HIIT ride moved to Sunday 15, and Saturday 14's
long ride was cut.
"""
import os
import unittest
from datetime import datetime

from tests import test_db_path
from tests.helpers import clear_all_tables, pin_clock, rebind_test_db, run_cli

TEST_DB_PATH = test_db_path("test_calendar_as_written.db")

from stamind import calendar_days
from stamind.analytics.written_week import WrittenSession, graded_weeks
from stamind.cli.render import calendar_page
from stamind.clock import shift
from stamind.db import Database

if os.path.exists(TEST_DB_PATH):
    os.remove(TEST_DB_PATH)
test_db = Database(db_path=TEST_DB_PATH)
rebind_test_db(test_db)


def tearDownModule():
    try:
        os.remove(TEST_DB_PATH)
    except OSError:
        pass


TODAY = "2026-11-13"
AT = datetime(2026, 11, 13, 7, 2)
MON = "2026-11-02"
LIGHT, HEAVY = "Full-Body Strength (Light)", "Full-Body Strength (Heavy)"
GYM = "strength_training"


def _day(n: int) -> str:
    """Monday 2 November plus `n` days: 4 is Friday 6, 11 is Friday 13."""
    return shift(MON, n)


def _session(n, sport="cycling", title="Ride", minutes=60, tss=50, **extra):
    return dict(date=_day(n), sport_type=sport, title=title, description=title,
                duration_minutes=minutes, tss=tss, **extra)


def _write(kind, *sessions, voids=(), reason=None):
    """One change: the voids first, as apply writes them, then the sessions, every row with
    the change's reason."""
    with test_db.workout_change(kind=kind) as change:
        for n, sport in voids:
            change.void(date=_day(n), sport_type=sport, reason=reason)
        for session in sessions:
            change.append(**session, reason=reason)


def _lineage(n, sport="cycling"):
    return test_db.get_workout(_day(n), sport)["id"]


def _act(n, sport="cycling", minutes=60, tss=50.0):
    test_db.save_completed_activity(
        activity_id=f"{sport}-{n}", date=_day(n), start_time=f"{_day(n)}T07:00:00",
        activity_name="Session", activity_type=sport, duration_sec=minutes * 60.0,
        distance_km=0.0, elevation_gain_m=0.0, avg_hr=None, max_hr=None, rpe=None, tss=tss,
    )


def the_two_weeks():
    _write("generate",
           _session(2, title="HIIT ride", tss=70), _session(3, "yoga", "Yoga", 30, 10),
           _session(4, GYM, LIGHT, 45, 30), _session(5, title="Gravel ride", minutes=120,
                                                      tss=80),
           _session(6, "yoga", "Yoga", 30, 10))
    _write("generate",
           _session(7, GYM, HEAVY, 60, 45), _session(8, title="Easy ride", tss=40),
           _session(9, title="HIIT ride", tss=70), _session(10, "rest", "Rest", 0, 0),
           _session(11, GYM, LIGHT, 45, 30),
           _session(12, title="Long ride", minutes=150, tss=110))
    _write("adapt", _session(2, "yoga", "Yoga", 30, 10, lineage_id=_lineage(3, "yoga")),
           _session(3, title="HIIT ride", tss=70, lineage_id=_lineage(2)),
           voids=[(2, "cycling"), (3, "yoga")])
    _write("adapt", _session(4, "rest", "Rest Day — Unwell", 0, 0), voids=[(4, GYM)],
           reason="Unwell.")
    _write("adapt", _session(5, "yoga", "Yoga", 30, 10, lineage_id=_lineage(6, "yoga")),
           _session(6, title="Gravel ride", minutes=40, tss=27, lineage_id=_lineage(5)),
           voids=[(5, "cycling"), (6, "yoga")])
    _write("tweak", _session(7, "rest", "Rest", 0, 0),
           _session(11, GYM, HEAVY, 60, 45, lineage_id=_lineage(7, GYM)),
           voids=[(7, GYM), (11, GYM)], reason="As asked, today is rest.")
    easy = _lineage(8)
    _write("adapt", _session(10, title="Easy ride", tss=40, lineage_id=easy),
           voids=[(8, "cycling")])
    _write("adapt", _session(8, title="Easy ride", tss=40, lineage_id=easy),
           voids=[(10, "cycling")])
    _write("adapt", _session(9, "rest", "Rest", 0, 0),
           _session(13, title="HIIT ride", tss=70, lineage_id=_lineage(9)),
           _session(12, title="Long ride", minutes=90, tss=65),
           voids=[(9, "cycling")], reason="Low HRV.")
    _act(2, "yoga", 30, 10.0)
    _act(3, "cycling", 60, 70.0)
    _act(5, "yoga", 30, 10.0)
    _act(6, "cycling", 72, 35.0)
    _act(8, "cycling", 100, 75.0)
    _act(11, GYM, 60, 45.0)


class _Case(unittest.TestCase):
    def setUp(self):
        clear_all_tables(test_db)
        rebind_test_db(test_db)
        pin_clock(self, TODAY)

    def snapshot(self):
        start, end = calendar_page.window(TODAY)
        return calendar_page.snapshot(calendar_days.gather(test_db, start, end, TODAY), AT)

    def marks(self):
        return self.snapshot()[0]


def _fill(marks):
    """A cell's fill grades, the dropped ones after the sessions', as the page tints them."""
    grades = [{k: v for k, v in m.items() if k in ("g", "r")} for m in marks.get("x", [])]
    return [g for g in grades if g] + marks.get("d", [])


class TwoWeeksTest(_Case):
    """§2's table, row by row."""

    def setUp(self):
        super().setUp()
        the_two_weeks()
        self.days = self.marks()["days"]

    def cell(self, n):
        marks = self.days[_day(n)]
        return _fill(marks), marks.get("k")

    def test_a_swap_is_graded_as_written_on_both_days_with_a_corner(self):
        # Wednesday 4: the yoga, as written. Thursday 5: the HIIT ride, as written.
        self.assertEqual(self.cell(2), ([{"g": "ok"}], [{"g": "ok"}]))
        self.assertEqual(self.cell(3), ([{"g": "ok"}], [{"g": "ok"}]))

    def test_a_dropped_session_is_full_blue_and_the_added_rest_gives_no_fill(self):
        self.assertEqual(self.cell(4), ([{"g": "less"}], [{"g": "ok"}]))

    def test_a_ride_moved_and_cut_is_blue_against_what_was_written(self):
        self.assertEqual(self.cell(5), ([{"g": "ok"}], [{"g": "ok"}]))
        fill, coach = self.cell(6)
        self.assertEqual(fill, [{"g": "less", "r": 0.44}])
        self.assertEqual(coach[0]["g"], "more")

    def test_a_day_whose_session_moved_away_is_plain_with_a_corner(self):
        self.assertEqual(self.cell(7), ([], [{"g": "ok"}]))
        self.assertEqual(self.cell(9), ([], [{"g": "ok"}]))

    def test_moved_and_moved_back_is_as_today_with_no_corner(self):
        fill, coach = self.cell(8)
        self.assertEqual(fill[0]["g"], "more")
        self.assertIsNone(coach)

    def test_a_written_rest_kept_is_green_with_no_corner(self):
        self.assertEqual(self.cell(10), ([{"g": "ok"}], None))

    def test_a_session_replaced_by_one_of_its_sport_gives_no_colour(self):
        # Friday 13: the heavy session, done as written on Monday 9; the light one is gone.
        self.assertEqual(self.cell(11), ([{"g": "ok"}], [{"g": "ok"}]))

    def test_a_changed_day_still_ahead_has_no_corner_yet(self):
        self.assertEqual(self.cell(12), ([{"g": "ahead"}], None))
        self.assertEqual(self.cell(13), ([{"g": "ahead"}], None))

    def test_the_week_numbers_are_the_week_grades_and_none_for_the_week_under_way(self):
        weeks = self.marks()["weeks"]
        self.assertEqual(weeks, {MON: [["🚴", "70%", 1], ["🏋️", "0/1", 1]]})
        [(monday, grade)] = graded_weeks(test_db, MON, _day(13), TODAY)
        self.assertEqual(weeks[monday], calendar_page.week_marks(grade))


class SheetTest(_Case):
    """§3: a line for each written session the coach changed, in the month files only."""

    def setUp(self):
        super().setUp()
        the_two_weeks()
        cal = calendar_days.gather(test_db, "2026-11-01", "2026-11-30", TODAY)
        self.days = calendar_page.month_files(cal)["calendar/2026-11"]["days"]

    def planned(self, n):
        return dict(self.days[_day(n)]["sheet"])["Planned"]

    def line(self, n, title):
        # The change's own day is the wall clock's, so the line is read around it.
        [line] = [line for line in self.planned(n) if line.startswith(f"{title}: ")]
        self.assertTrue(line.endswith(': "As asked, today is rest."'), line)
        return line

    def test_a_session_moved_away_says_where_and_why(self):
        self.assertIn(": moved to Fri 13 Nov, changed ", self.line(7, HEAVY))

    def test_a_dropped_session_says_so_and_one_moved_in_adds_nothing(self):
        self.assertIn(": dropped, changed ", self.line(11, LIGHT))
        self.assertFalse(any(line.startswith(f"{HEAVY}:") for line in self.planned(11)))

    def test_moved_and_moved_back_adds_nothing(self):
        self.assertFalse(any("moved" in line for line in self.planned(8)))

    def test_the_address_has_no_such_line(self):
        sheets = self.snapshot()[1]
        self.assertFalse(any("moved to" in line for line in dict(sheets[_day(7)])["Planned"]))

    def test_each_month_file_carries_the_weeks_touching_it(self):
        # The week of Monday 26 October ends on Sunday 1 November: both months hold it.
        _write("generate", _session(-6, title="Tuesday ride"))
        cal = calendar_days.gather(test_db, "2026-09-01", "2026-11-30", TODAY)
        files = calendar_page.month_files(cal)
        self.assertEqual(sorted(files["calendar/2026-11"]["weeks"]), ["2026-10-26", MON])
        self.assertEqual(list(files["calendar/2026-10"]["weeks"]), ["2026-10-26"])
        self.assertEqual(files["calendar/2026-09"]["weeks"], {})


class MoreDaysTest(_Case):
    """§9's other rows, on Tuesday 3 November."""

    def tuesday(self):
        return self.marks()["days"][_day(1)]

    def test_a_missed_session_on_a_changed_day_has_a_red_corner(self):
        _write("generate", _session(1, minutes=90, tss=70))
        _write("adapt", _session(1, minutes=45, tss=35), reason="Tired.")
        self.assertEqual((_fill(self.tuesday()), self.tuesday()["k"]),
                         ([{"g": "miss"}], [{"g": "miss"}]))

    def test_a_training_session_added_on_an_empty_day_is_graded_against_the_ask(self):
        _write("adapt", _session(1, minutes=60, tss=50))
        _act(1, "cycling", 60, 50.0)
        self.assertEqual((_fill(self.tuesday()), self.tuesday()["k"]),
                         ([{"g": "ok"}], [{"g": "ok"}]))

    def test_a_written_rest_day_replaced_by_a_ride_is_graded_as_the_ride(self):
        # Friday 28 August, told on a Tuesday: never blue for the rest that went.
        _write("generate", _session(1, "rest", "Rest", 0, 0))
        _write("adapt", _session(1, title="Threshold ride", tss=60,
                                 lineage_id=_lineage(1, "rest")), voids=[(1, "rest")])
        _act(1, "cycling", 60, 60.0)
        self.assertEqual((_fill(self.tuesday()), self.tuesday()["k"]),
                         ([{"g": "ok"}], [{"g": "ok"}]))

    def test_two_sessions_with_one_dropped(self):
        _write("generate", _session(1, "running", "Easy run", 40, 30),
               _session(1, GYM, LIGHT, 45, 30))
        _write("adapt", voids=[(1, GYM)], reason="Short on time.")
        _act(1, "running", 40, 30.0)
        self.assertEqual(_fill(self.tuesday()), [{"g": "ok"}, {"g": "less"}])
        self.assertEqual(self.tuesday()["k"], [{"g": "ok"}])

    def test_a_session_whose_sport_the_coach_changed_counts_as_dropped(self):
        # The gym session's own lineage became a rest day, kept.
        _write("generate", _session(1, GYM, LIGHT, 45, 30))
        _write("adapt", _session(1, "rest", "Rest", 0, 0, lineage_id=_lineage(1, GYM)),
               voids=[(1, GYM)])
        self.assertEqual((_fill(self.tuesday()), self.tuesday()["k"]),
                         ([{"g": "less"}], [{"g": "ok"}]))

    def test_a_missed_session_keeps_its_red_outline_whatever_it_replaced(self):
        # The written ride's lineage became a circuit, and nothing was recorded (choice 12).
        _write("generate", _session(1, minutes=90, tss=70))
        _write("adapt", _session(1, GYM, "Circuit B", 40, 30, lineage_id=_lineage(1)),
               voids=[(1, "cycling")])
        self.assertEqual((_fill(self.tuesday()), self.tuesday()["k"]),
                         ([{"g": "miss"}, {"g": "less"}], [{"g": "miss"}]))
        code, out, err = run_cli(["calendar", TODAY, "--no-pull"])
        self.assertEqual(code, 0, err)
        self.assertIn("🏋️ 40′ ✗–*", out)

    def test_a_drop_turns_blue_only_once_the_day_is_over(self):
        _write("generate", _session(10), _session(11), _session(12))
        _write("adapt", voids=[(10, "cycling"), (11, "cycling"), (12, "cycling")])
        days = self.marks()["days"]
        self.assertEqual(days[_day(10)]["d"], [{"g": "less"}])
        self.assertNotIn("d", days.get(_day(11), {}))
        self.assertNotIn("d", days.get(_day(12), {}))

    def test_a_cut_session_says_so_and_a_lengthened_one_says_nothing(self):
        _write("generate", _session(1, title="Tempo", minutes=90, tss=70),
               _session(2, title="Easy", minutes=60, tss=40))
        _write("adapt", _session(1, title="Tempo", minutes=45, tss=35),
               _session(2, title="Easy", minutes=90, tss=60), reason="Swapped the load.")
        cal = calendar_days.gather(test_db, "2026-11-01", "2026-11-30", TODAY)
        days = calendar_page.month_files(cal)["calendar/2026-11"]["days"]
        [cut] = [line for line in dict(days[_day(1)]["sheet"])["Planned"]
                 if line.startswith("Tempo: ")]
        self.assertTrue(cut.startswith("Tempo: cut from 90 to 45 min, changed "), cut)
        self.assertFalse(any(line.startswith("Easy: ")
                             for line in dict(days[_day(2)]["sheet"])["Planned"]))
        # Both days were changed by the coach: both have a corner.
        self.assertIn("k", days[_day(1)])
        self.assertIn("k", days[_day(2)])

    def test_a_gym_session_graded_by_its_sets_keeps_the_coachs_grade(self):
        # Monday 2 November: 25 sets written, 27 asked, the sets logged on the phone
        # (choice 7). Without the log it would be graded against the written version.
        written = {"sport_type": GYM, "duration_minutes": 45, "tss": 30}
        live = {"sport_type": GYM, "duration_minutes": 60, "tss": 45}
        row = {"planned": live, "completed": {"gym_log": {"revision_id": 7}},
               "status": "partial"}
        fill = calendar_days._fill(row, WrittenSession(written, live, []), 25.0)
        self.assertEqual((fill["planned"], fill["status"]), (live, "partial"))


class CalendarCommandTest(_Case):
    """§4: the terminal's marks and the week's line."""

    def test_the_marks_and_the_line_under_an_ended_week(self):
        the_two_weeks()
        code, out, err = run_cli(["calendar", TODAY, "--no-pull"])
        self.assertEqual(code, 0, err)
        lines = out.splitlines()
        first = next(i for i, line in enumerate(lines) if line.startswith("  2 "))
        body = lines[first + 1]
        self.assertIn("🧘 30′ ✓*", body)
        self.assertIn("🛌 –*", body)
        self.assertIn("🚴 40′ ½*", body)
        self.assertEqual(lines[first + 2],
                         "── cycling 70%, short · strength_training 0 of 1, short")
        body = lines[first + 4]
        self.assertIn("🚴 60′ ½ ", body + " ")
        self.assertIn("🏋️ 60′ ✓*", body)
        self.assertNotIn("──", lines[first + 5])


if __name__ == "__main__":
    unittest.main()
