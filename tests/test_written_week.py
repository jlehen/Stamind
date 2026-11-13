"""A week against its sessions as `workout generate` wrote them (DESIGN_week_as_written.md):
the slot walk (§3), the grade (§2), the reason shown (§5), the switch to the live sessions at
this week's Monday (§4), the record's numbers (§4), D5 in apply, `sm progress weeks` and a
`workout compare` with no weeks (DESIGN_progress_page.md §6).

The week is Monday 2 November to Sunday 8 November 2026, graded on Tuesday 10 November.
"""
import os
import unittest
from unittest.mock import patch

from tests import test_db_path
from tests.helpers import clear_all_tables, pin_clock, rebind_test_db, run_cli

TEST_DB_PATH = test_db_path("test_written_week.db")

from stamind import runtime
from stamind.analytics.written_week import (
    LOAD, SESSIONS, WrittenSession, graded_weeks, graded_workouts, percent, week_grade,
    written_week,
)
from stamind.clock import shift
from stamind.coach.proposals import RevisionProposal
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


MON = "2026-11-02"
TODAY = "2026-11-10"


def _day(n: int) -> str:
    return shift(MON, n)


def _session(n, sport="cycling", title="Ride", minutes=60, tss=50, **extra):
    return dict(
        date=_day(n), sport_type=sport, title=title, description=title,
        duration_minutes=minutes, tss=tss, **extra,
    )


def _write(kind, *sessions, voids=(), reason=None):
    """One change: the voids first, as apply writes them, then the sessions."""
    with test_db.workout_change(kind=kind) as change:
        for n, sport in voids:
            change.void(date=_day(n), sport_type=sport, reason=reason)
        for session in sessions:
            change.append(**session)
    return change.id


def _lineage(n, sport="cycling"):
    return test_db.get_workout(_day(n), sport)["id"]


def _act(n, sport="cycling", minutes=60, tss=50.0, name=None):
    test_db.save_completed_activity(
        activity_id=name or f"{sport}-{n}-{minutes}", date=_day(n),
        start_time=f"{_day(n)}T07:00:00", activity_name="Session", activity_type=sport,
        duration_sec=minutes * 60.0, distance_km=0.0, elevation_gain_m=0.0, avg_hr=None,
        max_hr=None, rpe=None, tss=tss,
    )


def _grade(today=TODAY):
    weeks = dict(graded_weeks(test_db, MON, _day(6), today))
    return {sport.sport: sport for sport in weeks.get(MON, [])}


def _written():
    return [(s.written["date"], s.written["title"]) for s in written_week(test_db, MON, _day(6))]


class _Case(unittest.TestCase):
    def setUp(self):
        clear_all_tables(test_db)
        rebind_test_db(test_db)


class SlotWalkTest(_Case):
    """§3: what `workout generate` left in each slot."""

    def test_a_generate_version_is_written(self):
        _write("generate", _session(1, title="Easy ride"))
        self.assertEqual(_written(), [(_day(1), "Easy ride")])

    def test_an_adapt_that_drops_leaves_the_session_written_and_without_a_now(self):
        _write("generate", _session(1))
        _write("adapt", voids=[(1, "cycling")], reason="Tired.")
        [session] = written_week(test_db, MON, _day(6))
        self.assertEqual(session.written["date"], _day(1))
        self.assertIsNone(session.now)

    def test_a_move_keeps_the_written_day_and_its_now_is_the_new_day(self):
        _write("generate", _session(2, title="Intervals"))
        lineage = _lineage(2)
        _write("adapt", _session(3, title="Intervals", lineage_id=lineage),
               voids=[(2, "cycling")])
        [session] = written_week(test_db, MON, _day(6))
        self.assertEqual((session.written["date"], session.now["date"]), (_day(2), _day(3)))

    def test_a_rollback_of_a_move_onto_a_day_with_no_ride_keeps_one_session(self):
        # §3's first story: Wednesday's intervals moved to Thursday, then rolled back.
        _write("generate", _session(2, title="Intervals"))
        moved = _write("adapt", _session(3, title="Intervals", lineage_id=_lineage(2)),
                       voids=[(2, "cycling")])
        test_db.rollback_to_change(moved, MON)
        self.assertEqual(_written(), [(_day(2), "Intervals")])

    def test_a_rollback_of_a_generate_over_a_void_goes_back_to_nothing(self):
        # §3's second story, the void written by `workout generate` itself.
        _write("generate", _session(1, title="Old ride"))
        _write("generate", voids=[(1, "cycling")])
        newer = _write("generate", _session(1, title="New ride"))
        test_db.rollback_to_change(newer, MON)
        self.assertEqual(_written(), [])

    def test_a_rollback_that_copies_back_an_adapt_void_reads_as_written(self):
        _write("generate", _session(1, title="Old ride"))
        _write("adapt", voids=[(1, "cycling")])
        newer = _write("tweak", _session(1, title="New ride"))
        test_db.rollback_to_change(newer, MON)
        [session] = written_week(test_db, MON, _day(6))
        self.assertEqual(session.written["title"], "Old ride")
        self.assertIsNone(session.now)

    def test_a_stand_down_leaves_nothing_written(self):
        _write("generate", _session(1))
        _write("stand-down", voids=[(1, "cycling")])
        self.assertEqual(_written(), [])

    def test_a_session_an_adapt_created_is_not_written_but_its_load_counts(self):
        _write("generate", _session(0, tss=100))
        _write("adapt", _session(1, title="Extra ride", tss=50))
        _act(0, tss=100.0)
        _act(1, tss=50.0)
        self.assertEqual(_written(), [(_day(0), "Ride")])
        self.assertEqual((_grade()["cycling"].written, _grade()["cycling"].done), (100, 150))

    def test_a_cross_sport_swap_reads_as_replaced(self):
        _write("generate", _session(4, sport="strength_training", title="Light gym", tss=15))
        _write(
            "adapt",
            _session(4, sport="rest", title="Rest Day — Unwell", minutes=0, tss=0,
                     lineage_id=_lineage(4, "strength_training"), reason="Sick today."),
            voids=[(4, "strength_training")], reason="Sick today.",
        )
        [changed] = _grade()["strength_training"].changed
        self.assertEqual(changed.what, "replaced by Rest Day — Unwell")
        self.assertEqual(changed.reason, "Sick today.")


class GradeTest(_Case):
    """§2: per sport, by load or in sessions, short past the tolerance."""

    def test_a_ride_over_covers_a_ride_cut_in_the_same_week(self):
        _write("generate", _session(1, tss=100), _session(5, minutes=120, tss=100))
        _write("adapt", _session(5, minutes=80, tss=70))
        _act(1, tss=130.0)
        _act(5, minutes=80, tss=70.0)
        cycling = _grade()["cycling"]
        self.assertFalse(cycling.short)
        self.assertEqual(cycling.changed, [])

    def test_a_long_ride_does_not_cover_a_gym_session(self):
        _write("generate", _session(1, tss=100),
               _session(3, sport="strength_training", title="Gym", tss=30))
        _act(1, minutes=180, tss=200.0)
        grade = _grade()
        self.assertFalse(grade["cycling"].short)
        self.assertEqual(grade["strength_training"].measure, SESSIONS)
        self.assertTrue(grade["strength_training"].short)

    def test_hiit_is_added_up_by_load(self):
        _write("generate", _session(2, sport="hiit", title="Circuit", minutes=30, tss=40))
        _act(2, sport="hiit", minutes=30, tss=40.0)
        self.assertEqual(_grade()["hiit"].measure, LOAD)
        self.assertFalse(_grade()["hiit"].short)

    def test_a_seven_minute_strength_activity_is_not_a_session(self):
        _write("generate", _session(3, sport="strength_training", title="Gym", tss=30))
        _act(3, sport="strength_training", minutes=7, tss=5.0)
        self.assertEqual(_grade()["strength_training"].done, 0)

    def test_yoga_and_rest_are_not_graded(self):
        _write("generate", _session(3, sport="yoga", title="Yoga", tss=10),
               _session(4, sport="rest", title="Rest", minutes=0, tss=0))
        self.assertEqual(_grade(), {})

    def test_a_session_moved_into_the_next_week_is_moved_out(self):
        _write("generate", _session(6, title="Long ride", tss=100))
        _write("adapt", _session(7, title="Long ride", tss=100, lineage_id=_lineage(6)),
               voids=[(6, "cycling")], reason="Rain all Sunday.")
        [changed] = _grade()["cycling"].changed
        self.assertEqual(changed.what, "moved to Mon 9 Nov")
        # The void the move left in the week carries the move's reason (§5).
        self.assertEqual(changed.reason, "Rain all Sunday.")

    def test_the_tolerance_widens_at_a_low_planned_load(self):
        # 50% at a planned load of 20, 15% from 100 up (§2).
        self.assertFalse(self._load_grade(20, 11).short)
        self.assertTrue(self._load_grade(20, 9).short)
        self.assertFalse(self._load_grade(190, 162).short)
        self.assertTrue(self._load_grade(190, 161).short)

    def test_15_03_percent_under_reads_84_and_short(self):
        grade = self._load_grade(449, 381.5)
        self.assertEqual((percent(grade), grade.short), (84, True))

    def test_the_week_under_way_is_not_graded(self):
        _write("generate", _session(1, tss=100))
        self.assertEqual(_grade(today=_day(6)), {})

    @staticmethod
    def _load_grade(written, done):
        session = {"date": MON, "sport_type": "cycling", "tss": written, "title": "Ride"}
        [grade] = week_grade(
            [WrittenSession(session, session, [])],
            [{"date": MON, "activity_type": "cycling", "tss": done, "duration_sec": 3600}],
        )
        return grade


class ReasonTest(_Case):
    """§5: the newest version dated in the week that changed the day, sport or load."""

    def test_a_later_rewording_is_skipped(self):
        _write("generate", _session(5, minutes=120, tss=100))
        with test_db.workout_change(kind="adapt") as change:
            change.append(**_session(5, minutes=40, tss=35), reason="Cut for fatigue.")
        with test_db.workout_change(kind="adapt") as change:
            change.append(**dict(_session(5, minutes=40, tss=35), description="Reworded"),
                          reason="Reworded.")
        [changed] = _grade()["cycling"].changed
        self.assertEqual(changed.what, "cut from 120 to 40 min")
        self.assertEqual(changed.reason, "Cut for fatigue.")


class GradedWorkoutsTest(_Case):
    """§4: written versions before this week's Monday, live sessions from it."""

    def test_switches_from_written_to_live_at_this_monday(self):
        _write("generate", _session(0, title="Last week"), _session(7, title="This week"))
        _write("adapt", voids=[(0, "cycling"), (7, "cycling")])
        titles = [w["title"] for w in graded_workouts(test_db, MON, _day(13), _day(8))]
        self.assertEqual(titles, ["Last week"])


class RecordNumbersTest(_Case):
    """§4: the record plans from the written week and caps done per sport."""

    def _numbers(self, end, today=TODAY):
        return runtime.coach_service._retrospective_numbers(MON, end, today)

    def test_planned_is_the_written_week_for_a_mesocycle_ended_on_a_wednesday(self):
        _write("generate", _session(0, tss=100),
               _session(1, sport="strength_training", title="Gym", tss=30),
               _session(2, tss=50))
        _write("adapt", voids=[(2, "cycling")])
        numbers = self._numbers(_day(2), today=_day(6))
        self.assertEqual((numbers["sessions_planned"], numbers["load_planned"]), (3, 180))

    def test_a_session_moved_within_the_mesocycle_and_done_counts(self):
        _write("generate", _session(0))
        _write("adapt", _session(1, lineage_id=_lineage(0)), voids=[(0, "cycling")])
        _act(1)
        self.assertEqual(self._numbers(_day(6))["sessions_done"], 1)

    def test_a_gym_session_turned_into_yoga_is_not_gym_done(self):
        _write("generate", _session(1, sport="strength_training", title="Gym", tss=30))
        _write("adapt", _session(1, sport="yoga", title="Yoga", tss=20,
                                 lineage_id=_lineage(1, "strength_training")),
               voids=[(1, "strength_training")])
        _act(1, sport="yoga", tss=20.0)
        self.assertEqual(self._numbers(_day(6))["sessions_done"], 0)

    def test_a_lift_moved_by_two_sport_changes_counts_once(self):
        # 16–17 September: Wednesday's lift became rest and Thursday's ride became a lift.
        _write("generate", _session(2, sport="strength_training", title="Lift", tss=30),
               _session(3, title="Spin", tss=40))
        lift, spin = _lineage(2, "strength_training"), _lineage(3)
        _write("adapt",
               _session(2, sport="rest", title="Rest", minutes=0, tss=0, lineage_id=lift),
               _session(3, sport="strength_training", title="Lift", tss=30, lineage_id=spin),
               voids=[(2, "strength_training"), (3, "cycling")])
        _act(3, sport="strength_training", tss=30.0)
        self.assertEqual(self._numbers(_day(6))["sessions_done"], 1)

    def test_done_is_capped_per_sport_at_the_number_written(self):
        # Two gym sessions written, a third added; all three done count as two.
        _write("generate", _session(0, sport="strength_training", title="Gym A", tss=30),
               _session(2, sport="strength_training", title="Gym B", tss=30))
        _write("adapt", _session(1, sport="strength_training", title="Gym extra", tss=30))
        for n in (0, 1, 2):
            _act(n, sport="strength_training", tss=30.0)
        self.assertEqual(self._numbers(_day(6))["sessions_done"], 2)


class ApplyTest(_Case):
    """D5: an adapt or a tweak into a range with no session is stored as a generate."""

    def _apply(self, kind="adapt"):
        runtime.coach_service.workout_revision_apply(RevisionProposal(
            reason="Your new mesocycle.", range_start=_day(0), range_end=_day(6),
            kind=kind, workouts=[dict(_session(1), modification_reason="New.", rpe=5)],
        ))
        return test_db.get_workout_changes()[0]["kind"]

    def test_an_adapt_over_a_range_with_no_session_is_a_generate(self):
        self.assertEqual(self._apply(), "generate")
        self.assertEqual(_written(), [(_day(1), "Ride")])

    def test_so_is_a_tweak(self):
        self.assertEqual(self._apply(kind="tweak"), "generate")

    def test_an_adapt_over_a_range_holding_a_session_stays_an_adapt(self):
        _write("generate", _session(4, sport="yoga", title="Yoga", tss=10))
        self.assertEqual(self._apply(), "adapt")


class _ShortGymWeek(_Case):
    """The week of 2 November: the ride done, Thursday's gym replaced by a rest day."""

    def setUp(self):
        super().setUp()
        pin_clock(self, TODAY)
        _write("generate", _session(1, tss=100),
               _session(3, sport="strength_training", title="Light gym", tss=15))
        _write("adapt", _session(4, sport="rest", title="Rest Day", minutes=0, tss=0,
                                 lineage_id=_lineage(3, "strength_training"), reason="Sick."),
               voids=[(3, "strength_training")], reason="Sick.")
        _act(1, tss=100.0)


class ProgressWeeksTest(_ShortGymWeek):
    """`sm progress weeks`: the ended weeks, one line each, or one in full
    (DESIGN_progress_page.md §6)."""

    def _weeks(self, *extra):
        code, out, _ = run_cli(["progress", "weeks", *extra, "--no-pull"])
        self.assertEqual(code, 0)
        return out

    def test_one_line_per_ended_week_of_the_window_and_none_for_the_week_under_way(self):
        # Two weeks, this one counted: the week of 2 November, and the week under way.
        _write("generate", _session(8, tss=80))
        out = self._weeks("-w", "2")
        self.assertIn("WEEKS AS WRITTEN", out)
        self.assertIn("w/c 11-02  cycling 100% · strength_training 0 of 1, short\n", out)
        self.assertNotIn("w/c 11-09", out)

    def test_a_week_outside_the_window_is_not_listed(self):
        self.assertNotIn("w/c 11-02", self._weeks("-w", "1"))

    def test_a_day_of_the_week_prints_it_in_full(self):
        out = self._weeks(_day(4))
        self.assertIn("Week of Mon 2 Nov", out)
        self.assertIn("cycling: written 100, done 100 (100%)\n", out)
        self.assertIn("strength_training: written 1 session, done 0, short", out)
        self.assertIn('Thu 5 Nov Light gym: replaced by Rest Day, changed ', out)
        self.assertIn(': "Sick."', out)

    def test_the_week_under_way_is_never_graded(self):
        out = self._weeks(TODAY)
        self.assertIn("has not ended", out)
        self.assertNotIn("written", out)


class CompareTest(_ShortGymWeek):
    """`workout compare` and "✅ Done lately" are the days again (DESIGN_progress_page.md
    §5, §6)."""

    def _compare(self, render="expert"):
        with patch.dict(os.environ, {"STAMIND_RENDER": render}):
            return run_cli(["workout", "compare", "-d", f"{MON}..{_day(6)}", "--no-pull",
                            "--no-mark"])[1]

    def test_no_week_section_and_great_adherence_when_no_day_has_a_discrepancy(self):
        out = self._compare()
        self.assertNotIn("WEEKS AS WRITTEN", out)
        self.assertNotIn("written 1 session", out)
        self.assertIn("No discrepancies found. Great adherence!", out)

    def test_the_chat_adds_no_week_line_under_the_days(self):
        out = self._compare(render="simple")
        self.assertIn("Looking back", out)
        self.assertNotIn("as it was written", out)
        self.assertNotIn("Sick.", out)


if __name__ == "__main__":
    unittest.main()
