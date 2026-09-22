import os
import unittest
from datetime import date, timedelta

from tests.helpers import rebind_test_db
from stamind.db import Database
import stamind.garmin as garmin
from tests import test_db_path

TEST_DB_PATH = test_db_path("test_stamind_timeline.db")
test_db = Database(db_path=TEST_DB_PATH)
rebind_test_db(test_db)

from stamind.analytics import timeline  # noqa: E402


def tearDownModule():
    if os.path.exists(TEST_DB_PATH):
        try:
            os.remove(TEST_DB_PATH)
        except OSError:
            pass


def _d(offset: int) -> str:
    """A YYYY-MM-DD string `offset` days from a fixed anchor (2026-07-03, a Friday)."""
    anchor = date(2026, 7, 3)
    return (anchor + timedelta(days=offset)).isoformat()


TODAY = _d(0)  # 2026-07-03, Friday; its week commences 2026-06-29 (Monday)
CTL_DAYS, ATL_DAYS = 42, 7


def _act(offset, tss=None, rpe=None, duration_sec=3600.0, activity_id=None,
         activity_type="cycling"):
    return {
        "activity_id": activity_id or f"act-{offset}-{tss}-{rpe}",
        "date": _d(offset),
        "tss": tss,
        "rpe": rpe,
        "duration_sec": duration_sec,
        "activity_type": activity_type,
    }


def _w(offset, sport_type="running", tss=None, rpe=None, duration_minutes=None,
       removed=False):
    return {
        "date": _d(offset),
        "sport_type": sport_type,
        "tss": tss,
        "rpe": rpe,
        "duration_minutes": duration_minutes,
        "removed": removed,
    }


def _m(offset, ctl, atl, tsb=0.0):
    return {"date": _d(offset), "ctl": ctl, "atl": atl, "tsb": tsb}


def _dp(offset, load, source="actual"):
    return {"date": _d(offset), "load": float(load), "source": source}


class TestZeroLoadWorkoutCount(unittest.TestCase):
    def test_counts_only_non_rest_workouts_with_no_valuation(self):
        workouts = [
            _w(1, sport_type="rest"),
            _w(2, tss=None, rpe=None, duration_minutes=None),   # counted
            _w(3, tss=50),
            _w(4, rpe=5, duration_minutes=30),
            _w(5, tss=None, rpe=None, duration_minutes=None, removed=True),
        ]
        self.assertEqual(timeline.zero_load_workout_count(workouts, TODAY), 1)


class TestMesoBands(unittest.TestCase):
    def test_orders_inferred_and_plan_and_prefixes_label(self):
        inferred = [{"name": "Base", "start_date": _d(-60), "end_date": _d(-30)}]
        real = [{"name": "Build 2", "start_date": _d(-10), "end_date": _d(10)}]
        bands = timeline.meso_bands(real, inferred)
        labels = {b["label"]: b for b in bands}
        self.assertEqual(labels["~Base"]["source"], "inferred")
        self.assertEqual(labels["Build 2"]["source"], "plan")

    def test_inferred_band_trimmed_where_plan_covers(self):
        inferred = [{"name": "Base", "start_date": _d(-60), "end_date": _d(0)}]
        plan = [{"name": "Build", "start_date": _d(-10), "end_date": _d(10)}]
        bands = timeline.meso_bands(plan, inferred)
        inf = next(b for b in bands if b["source"] == "inferred")
        self.assertEqual(inf["end_date"], _d(-11))  # trimmed to the day before plan
        # No two bands overlap.
        self.assertFalse(self._any_overlap(bands))

    def test_fully_covered_inferred_band_dropped(self):
        inferred = [{"name": "X", "start_date": _d(-5), "end_date": _d(5)}]
        plan = [{"name": "P", "start_date": _d(-10), "end_date": _d(10)}]
        bands = timeline.meso_bands(plan, inferred)
        self.assertEqual([b["source"] for b in bands], ["plan"])

    @staticmethod
    def _any_overlap(bands):
        s = sorted(bands, key=lambda b: b["start_date"])
        return any(s[i]["end_date"] >= s[i + 1]["start_date"] for i in range(len(s) - 1))


class TestAssembleTimeline(unittest.TestCase):
    def _assemble(self, activities=None, workouts=None, metrics=None,
                  mesocycles=None, inferred=None, objectives=None, cutoff=None):
        return timeline.assemble_timeline(
            activities or [], workouts or [], metrics or [], mesocycles or [],
            inferred or [], objectives or [], TODAY, CTL_DAYS, ATL_DAYS, cutoff,
        )

    @staticmethod
    def _codes(payload):
        return {w["code"] for w in payload["warnings"]}

    def test_payload_shape(self):
        p = self._assemble(activities=[_act(-2, tss=30.0)], workouts=[_w(2, tss=50)])
        self.assertEqual(
            set(p.keys()),
            {"today", "plan_start", "plan_end", "days", "weeks", "meso_bands",
             "objectives", "plan_gap", "warnings"},
        )
        self.assertEqual(p["plan_end"], _d(2))

    def test_warnings_carry_a_code_and_text(self):
        # Renderers dispatch on `code`, never on the prose (§6.0).
        p = self._assemble(workouts=[_w(1, tss=50)])
        w = next(w for w in p["warnings"] if w["code"] == "no_history")
        self.assertIn("no activity history", w["text"])
        self.assertEqual(w["command"], "data pull")

    def test_no_activity_state_warns_and_still_has_weeks(self):
        p = self._assemble(workouts=[_w(1, tss=50)])
        self.assertIn("no_history", self._codes(p))
        self.assertTrue(p["weeks"])  # planned bars still render

    def test_plan_gap_is_structured_not_a_warning_string(self):
        objectives = [{"id": 1, "title": "Marathon", "target_date": _d(60), "status": "active"}]
        p = self._assemble(activities=[_act(-1, tss=30.0)],
                           workouts=[_w(2, tss=50)], objectives=objectives)
        self.assertEqual(p["plan_gap"]["objective"]["id"], 1)
        self.assertEqual(p["plan_gap"]["plan_end"], _d(2))
        self.assertGreater(p["plan_gap"]["weeks_before"], 0)
        self.assertNotIn("plan_gap", self._codes(p))

    def test_no_plan_gap_when_every_objective_is_reached(self):
        objectives = [{"id": 1, "title": "Marathon", "target_date": _d(1), "status": "active"}]
        p = self._assemble(activities=[_act(-1, tss=30.0)],
                           workouts=[_w(2, tss=50)], objectives=objectives)
        self.assertIsNone(p["plan_gap"])

    def test_zero_load_warning_ignores_past_workouts(self):
        # A past row nobody can fix must not keep the banner permanently lit.
        p = self._assemble(activities=[_act(-1, tss=30.0)],
                           workouts=[_w(-3, tss=None), _w(2, tss=50)])
        self.assertNotIn("zero_load_workouts", self._codes(p))
        p = self._assemble(activities=[_act(-1, tss=30.0)],
                           workouts=[_w(1, tss=None), _w(2, tss=50)])
        self.assertIn("zero_load_workouts", self._codes(p))

    def test_young_db_caveat_in_warnings(self):
        # History starts today -> n_days small -> caveat fires.
        p = self._assemble(activities=[_act(0, tss=30.0)], workouts=[_w(1, tss=50)])
        self.assertIn("pmc_warming", self._codes(p))

    def test_unparseable_inferred_mesocycle_skipped_and_warned(self):
        inferred = [{"name": "Bad", "start_date": "not-a-date", "end_date": _d(0)}]
        p = self._assemble(activities=[_act(-1, tss=30.0)], workouts=[_w(2, tss=50)],
                           inferred=inferred)
        self.assertIn("bootstrap_dates", self._codes(p))
        self.assertFalse(any(b["source"] == "inferred" for b in p["meso_bands"]))


class TestClipPayload(unittest.TestCase):
    def test_straddling_week_returned_whole(self):
        payload = {
            "days": [{"date": _d(-10), "load": 1}, {"date": _d(-2), "load": 1}],
            "weeks": [{"week_commencing": _d(-4)}],  # Mon..Sun spans the edge
            "meso_bands": [{"start_date": _d(-40), "end_date": _d(-1)}],
            "objectives": [],
        }
        clipped = timeline.clip_payload(payload, _d(-3), _d(0))
        # The week starting _d(-4) straddles the _d(-3) window start -> kept whole.
        self.assertEqual(len(clipped["weeks"]), 1)
        # Days clip by date.
        self.assertEqual([d["date"] for d in clipped["days"]], [_d(-2)])
        # Bands overlapping the window are kept.
        self.assertEqual(len(clipped["meso_bands"]), 1)


class TestClipPayloadForWeeks(unittest.TestCase):
    """`cap_future` is what keeps `sm progress --chart` framing the same span its
    text table does (DESIGN_progress_timeline.md §7.1)."""

    def _payload(self, plan_end):
        days = [{"date": _d(offset), "load": 0.0, "source": "planned",
                 "ctl": 1.0, "atl": 1.0, "tsb": 0.0}
                for offset in range(-40, 90)]
        # Real weeks: the cap is derived from `select_weeks`, the same choice the text
        # table makes, so the fixture has to carry the weeks it chooses from.
        weeks = [{"week_commencing": _d(offset), "actual_load": 0.0,
                  "planned_load": None}
                 for offset in range(-39, 90, 7)]  # _d(-39) is a Monday
        return {"today": TODAY, "plan_end": plan_end, "days": days, "weeks": weeks,
                "objectives": [], "warnings": [], "meso_bands": []}

    def test_default_keeps_the_whole_projection(self):
        payload = self._payload(plan_end=_d(80))
        clipped = timeline.clip_payload_for_weeks(payload, 2, TODAY)
        self.assertEqual(clipped["days"][-1]["date"], _d(80))

    def test_cap_future_cuts_the_projection_to_the_window(self):
        payload = self._payload(plan_end=_d(80))
        clipped = timeline.clip_payload_for_weeks(
            payload, 2, TODAY, cap_future=True)
        # Sunday of the 2nd whole week after the one containing today.
        self.assertLess(clipped["days"][-1]["date"], _d(80))
        self.assertGreater(clipped["days"][-1]["date"], TODAY)

    def test_cap_future_never_extends_a_short_plan(self):
        payload = self._payload(plan_end=_d(3))
        clipped = timeline.clip_payload_for_weeks(
            payload, 8, TODAY, cap_future=True)
        self.assertEqual(clipped["days"][-1]["date"], _d(3))

    def test_cap_future_is_a_no_op_under_weeks_all(self):
        payload = self._payload(plan_end=_d(80))
        capped = timeline.clip_payload_for_weeks(
            payload, "all", TODAY, cap_future=True)
        self.assertEqual(capped["days"][-1]["date"], _d(80))


if __name__ == "__main__":
    unittest.main()
