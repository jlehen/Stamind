"""The calendar: its list of days, the page's snapshot, and `sm calendar`
(DESIGN_calendar_miniapp.md §4, §5, §7).

The week is the design's. It is Friday 25 September 2026. One plan ends on 30 September
and the next starts on 1 October. Tuesday's run was cut short but counts as done, Wednesday
holds a run that was done and a gym session that was missed, Saturday's run was skipped,
and on Sunday a two-hour hike nothing planned sits beside the planned run, with a ten-minute
walk too small to mention.
"""
import hashlib
import os
import unittest
from datetime import datetime
from unittest.mock import patch

from tests import test_db_path
from tests.helpers import clear_all_tables, pin_clock, rebind_test_db, run_cli, save_workout

from stamind import calendar_days
from stamind.cli.render import calendar_grid
from stamind.cli.render import calendar_page
from stamind.cli.render.plan_lines import SIMPLE_END_NOTE
from stamind.db import Database

TEST_DB_PATH = test_db_path("test_calendar.db")
test_db = Database(db_path=TEST_DB_PATH)
rebind_test_db(test_db)

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
TODAY = "2026-09-25"
AT = datetime(2026, 9, 25, 7, 2)


def _activity(activity_id, day, kind, minutes, tss, name):
    test_db.save_completed_activity(
        activity_id=activity_id, date=day, start_time=f"{day} 08:00:00",
        activity_name=name, activity_type=kind, duration_sec=minutes * 60.0,
        distance_km=5.0, elevation_gain_m=10.0, avg_hr=140, max_hr=160, rpe=4, tss=tss,
    )


def _plan(title, target, meso_name, start, end):
    goal_id = test_db.add_objective(title=title, target_date=target, sport_type="running")
    test_db.save_macrocycle(
        objective_id=goal_id, strategy="s", goals_hash=title, constraints_hash="c",
        mesocycles=[{"name": meso_name, "start_date": start, "end_date": end, "focus": "f"}],
    )


def the_week():
    """The design's week, written into the test database."""
    _plan("Autumn 10k", "2026-09-30", "Build", "2026-09-01", "2026-09-30")
    _plan("Sylvesterlauf", "2026-12-13", "Aerobic base", "2026-10-01", "2026-10-18")
    save_workout(test_db, date="2026-09-19", sport_type="running", title="Tempo run",
                 duration_minutes=45, tss=50)
    save_workout(test_db, date="2026-09-20", sport_type="running", title="Long run",
                 duration_minutes=120, tss=90)
    save_workout(test_db, date="2026-09-22", sport_type="running", title="Easy run",
                 description="Easy run in zone 2.", duration_minutes=50, tss=40)
    save_workout(test_db, date="2026-09-23", sport_type="running", title="Easy run",
                 duration_minutes=40, tss=30)
    save_workout(test_db, date="2026-09-23", sport_type="strength_training",
                 title="Gym: lower body", duration_minutes=60, tss=40)
    save_workout(test_db, date="2026-09-25", sport_type="cycling", title="Hills",
                 duration_minutes=90, tss=80)
    save_workout(test_db, date="2026-09-27", sport_type="rest", title="Rest")
    _activity("a22", "2026-09-22", "running", 32, 25.0, "Tuesday Run")
    _activity("a23", "2026-09-23", "running", 40, 30.0, "Wednesday Run")
    _activity("a20run", "2026-09-20", "running", 120, 90.0, "Long Run")
    _activity("a20hike", "2026-09-20", "hiking", 120, 80.0, "Hike")
    _activity("a20walk", "2026-09-20", "walking", 10, 3.0, "Walk to the shops")
    test_db.add_constraint("Wedding", "2026-09-26", "2026-09-27",
                           description="Away, no training")
    test_db.upsert_daily_signal_by_event("ev1", "2026-09-22", "alcohol", 2.0,
                                         "Two drinks the evening before")


class CalendarTestCase(unittest.TestCase):

    def setUp(self):
        rebind_test_db(test_db)
        clear_all_tables(test_db)
        pin_clock(self, TODAY)
        the_week()

    def gather(self, start="2026-09-19", end="2026-09-27"):
        return calendar_days.gather(test_db, start, end, TODAY)


class DaysTest(CalendarTestCase):
    """The list of days on a fixed week (§4)."""

    def test_every_date_gets_a_day_in_order(self):
        cal = self.gather()
        self.assertEqual([d.date for d in cal.days][0], "2026-09-19")
        self.assertEqual(len(cal.days), 9)

    def test_a_day_with_two_sessions_keeps_both_grades(self):
        day = {d.date: d for d in self.gather().days}["2026-09-23"]
        statuses = sorted(r["status"] for r in day.results)
        self.assertEqual(statuses, ["done", "missed"])

    def test_an_unplanned_activity_carries_its_kind_and_a_minor_one_is_not_shown(self):
        day = {d.date: d for d in self.gather().days}["2026-09-20"]
        kinds = {act["activity_id"]: kind for act, kind in day.unplanned}
        self.assertEqual(kinds, {"a20hike": "unplanned", "a20walk": "minor"})
        self.assertEqual([a["activity_id"] for a in day.worth_showing()], ["a20hike"])

    def test_constraints_and_signals_land_on_the_days_they_cover(self):
        days = {d.date: d for d in self.gather().days}
        self.assertEqual([c["title"] for c in days["2026-09-26"].constraints], ["Wedding"])
        self.assertEqual([c["title"] for c in days["2026-09-27"].constraints], ["Wedding"])
        self.assertEqual(days["2026-09-25"].constraints, [])
        self.assertEqual([s["metric"] for s in days["2026-09-22"].signals], ["alcohol"])

    def test_two_plans_back_to_back_give_one_list_of_mesocycles(self):
        cal = self.gather("2026-09-19", "2026-10-06")
        self.assertEqual([m["name"] for m in cal.mesocycles], ["Build", "Aerobic base"])

    def test_the_goals_and_the_end_of_the_schedule(self):
        cal = self.gather()
        self.assertEqual([g["title"] for g in cal.goals], ["Autumn 10k", "Sylvesterlauf"])
        self.assertEqual(cal.schedule_end, "2026-09-27")
        self.assertEqual(calendar_days.next_goal(cal.goals, TODAY)["title"], "Autumn 10k")


class LabelTest(unittest.TestCase):
    """What a cell writes under its icon (§3.1)."""

    def test_the_short_name_wins(self):
        run = {"sport_type": "running", "short_name": "Hills", "duration_minutes": 90}
        self.assertEqual(calendar_page.session_label([run]), "Hills")

    def test_without_one_the_planned_length(self):
        self.assertEqual(calendar_page.session_label(
            [{"sport_type": "running", "duration_minutes": 90}]), "90′")
        self.assertEqual(calendar_page.session_label(
            [{"sport_type": "cycling", "duration_minutes": 150}]), "2h30")
        self.assertEqual(calendar_page.session_label(
            [{"sport_type": "cycling", "duration_minutes": 120}]), "2h")

    def test_rest_two_sessions_and_nothing_have_no_label(self):
        self.assertIsNone(calendar_page.session_label([{"sport_type": "rest"}]))
        self.assertIsNone(calendar_page.session_label([{"sport_type": "running"}]))
        two = [{"sport_type": "running", "short_name": "Easy"},
               {"sport_type": "cycling", "short_name": "Z2"}]
        self.assertIsNone(calendar_page.session_label(two))


class SnapshotTest(CalendarTestCase):
    """What the page is sent (§5)."""

    def snapshot(self):
        start, end = calendar_page.window(TODAY)
        return calendar_page.snapshot(calendar_days.gather(test_db, start, end, TODAY), AT)

    def test_the_window_is_four_weeks_back_and_six_ahead(self):
        self.assertEqual(calendar_page.window(TODAY), ("2026-08-28", "2026-11-06"))

    def test_the_packing_survives_a_round_trip(self):
        payload, _sheets = self.snapshot()
        self.assertEqual(calendar_page.unpack(calendar_page.pack(payload)), payload)

    def test_the_url_carries_the_snapshot_after_c(self):
        start, end = calendar_page.window(TODAY)
        url = calendar_page.calendar_url(
            calendar_days.gather(test_db, start, end, TODAY), AT)
        head, packed = url.split("#c=")
        self.assertEqual(head, calendar_page.PAGE_URL)
        payload = calendar_page.unpack(packed)
        self.assertEqual((payload["v"], payload["at"], payload["today"]),
                         (1, "2026-09-25T07:02", TODAY))
        self.assertTrue(payload["goal"].startswith("🏃 Autumn 10k — on "), payload["goal"])
        self.assertEqual([m["n"] for m in payload["meso"]], ["Build", "Aerobic base"])
        self.assertEqual(payload["end"], "2026-09-27")
        self.assertEqual(payload["fit"], ["2026-08-28", "2026-11-06"])
        self.assertIn("sheet", payload["days"]["2026-09-22"])

    def test_the_marks(self):
        days = self.snapshot()[0]["days"]
        self.assertEqual(days["2026-09-22"]["x"], [{"i": "🏃", "l": "50′", "g": "ok"}])
        self.assertEqual(days["2026-09-22"]["s"], 1)
        self.assertEqual(days["2026-09-19"]["x"][0]["g"], "miss")
        self.assertEqual(days["2026-09-25"]["x"], [{"i": "🚴", "l": "90′", "g": "ahead"}])
        self.assertEqual(days["2026-09-27"]["x"], [{"i": "🛌", "g": "ahead"}])
        self.assertEqual(days["2026-09-27"]["c"], 1)

    def test_two_sessions_show_two_icons_and_no_label(self):
        marks = self.snapshot()[0]["days"]["2026-09-23"]["x"]
        self.assertEqual(sorted((m["i"], m["g"]) for m in marks),
                         [("🏃", "ok"), ("🏋️", "miss")])
        self.assertTrue(all("l" not in m for m in marks))

    def test_an_unplanned_hike_is_faded_and_the_walk_is_nowhere(self):
        self.assertEqual(self.snapshot()[0]["days"]["2026-09-20"]["u"], ["🥾"])

    def test_the_sheet_is_built_from_the_chat_lines(self):
        sheet = dict((h, lines) for h, lines in self.snapshot()[1]["2026-09-22"])
        self.assertEqual(sheet["Planned"][0], "🏃 2026-09-22 Tue: Easy run — 50 min")
        self.assertEqual(sheet["Planned"][1], "Easy run in zone 2.")
        self.assertEqual(sheet["Done"], ["✅ 🏃 Easy run — 50 min (you did 32 min)"])
        self.assertEqual(sheet["Signals and constraints"],
                         ["alcohol: 2 — Two drinks the evening before"])

    def test_a_day_ahead_has_no_done_part_and_an_empty_scheduled_day_says_rest(self):
        sheets = self.snapshot()[1]
        self.assertEqual([h for h, _ in sheets["2026-09-25"]], ["Planned"])
        self.assertEqual(sheets["2026-09-24"], [["Planned", ["Rest day — enjoy it 🎉"]]])
        self.assertNotIn("2026-10-20", sheets)

    def test_the_page_prints_the_end_note_word_for_word(self):
        with open(os.path.join(REPO, "miniapp", "calendar_logic.js"), encoding="utf-8") as handle:
            self.assertIn(SIMPLE_END_NOTE, handle.read())


class BudgetTest(unittest.TestCase):
    """The sheets go in nearest today first, until the next would pass the budget (§5)."""

    def payload(self):
        start, end = calendar_page.window(TODAY)
        return {"v": 1, "today": TODAY, "from": start, "to": end, "days": {}}

    def sheets(self):
        # Text that does not compress, so each sheet costs about the same.
        start, end = calendar_page.window(TODAY)
        return {day: [["Planned", ["".join(hashlib.sha256(f"{day}{i}".encode()).hexdigest()
                                           for i in range(6))]]]
                for day in calendar_page.outward(TODAY, start, end)}

    def test_the_outward_order(self):
        self.assertEqual(calendar_page.outward(TODAY, "2026-09-23", "2026-09-26"),
                         ["2026-09-25", "2026-09-26", "2026-09-24", "2026-09-23"])

    def test_the_budget_keeps_the_sheets_nearest_today(self):
        packed = calendar_page.fit(self.payload(), self.sheets(), budget=4000)
        self.assertLessEqual(len(packed), 4000)
        payload = calendar_page.unpack(packed)
        kept = sorted(day for day, marks in payload["days"].items() if "sheet" in marks)
        first, last = payload["fit"]
        self.assertEqual(kept[0], first)
        self.assertEqual(kept[-1], last)
        self.assertLessEqual(first, TODAY)
        self.assertLessEqual(TODAY, last)
        self.assertLess(len(kept), 20)
        # Outward means balanced: the two sides differ by at most a day.
        before = len([d for d in kept if d < TODAY])
        after = len([d for d in kept if d > TODAY])
        self.assertIn(after - before, (0, 1))

    def test_everything_fits_under_a_big_budget(self):
        payload = calendar_page.unpack(
            calendar_page.fit(self.payload(), self.sheets(), budget=10 ** 6))
        self.assertEqual(payload["fit"], [payload["from"], payload["to"]])
        self.assertEqual(len(payload["days"]), 71)

    def test_not_even_today_fits(self):
        payload = calendar_page.unpack(
            calendar_page.fit(self.payload(), self.sheets(), budget=10))
        self.assertIsNone(payload["fit"])
        self.assertEqual(payload["days"], {})


class CalendarCommandTest(CalendarTestCase):
    """`sm calendar` on a fixed month (§7)."""

    def test_the_month_grid(self):
        code, out, err = run_cli(["calendar", "2026-09-10", "--no-pull"])
        self.assertEqual(code, 0, err)
        lines = out.splitlines()
        self.assertIn("September 2026", lines[0])
        self.assertIn("Next goal: Autumn 10k (2026-09-30 Wed)", lines[1])
        self.assertTrue(lines[2].startswith(" Mon        Tue"), lines[2])
        self.assertIn("── Build starts Tue 1 Sep", out)
        week = next(i for i, line in enumerate(lines) if line.startswith("             1"))
        self.assertNotIn("──", lines[week])
        # The week of 21 to 27 September: its numbers line, then its sessions.
        numbers = next(line for line in lines if " 21 " in line and " 27" in line)
        body = lines[lines.index(numbers) + 1]
        self.assertIn(" 22 •", numbers)
        self.assertIn(" 26 ◆", numbers)
        self.assertIn("🏃 50′ ✓", body)
        self.assertIn("🏃🏋️ ✓✗", body)
        self.assertIn("🚴 90′", body)
        # The week before: Sunday's run gives its label up to the hike nothing planned.
        previous = lines[lines.index(numbers) - 1]
        self.assertTrue(previous.endswith("🏃 ✓ +🥾"), previous)

    def test_it_pulls_the_month_up_to_today(self):
        with patch("stamind.runtime.garmin") as garmin:
            code, _out, err = run_cli(["calendar"])
        self.assertEqual(code, 0, err)
        garmin.ensure_data.assert_called_once_with("2026-09-01", TODAY, force=False)

    def test_a_month_ahead_pulls_nothing(self):
        with patch("stamind.runtime.garmin") as garmin:
            code, out, err = run_cli(["calendar", "2026-10-03"])
        self.assertEqual(code, 0, err)
        garmin.ensure_data.assert_not_called()
        self.assertIn("── Aerobic base starts Thu 1 Oct", out)

    def test_the_cell_is_eleven_columns(self):
        self.assertEqual(calendar_grid.columns(calendar_grid.fit_cell(" 🏋️ Gym ✓")), 11)
        self.assertEqual(calendar_grid.columns("🏃"), 2)


if __name__ == "__main__":
    unittest.main()
