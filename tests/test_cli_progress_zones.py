"""Pure formatting-helper tests for the zone half of `tm progress`
(trainmate/cli/progress_zones.py): the weekly time-in-zone grid and the per-mesocycle
report. No DB, no CLI dispatch — `_StubDb` below stands in for the five accessors the
mesocycle walk reads.

The load table's own tests are tests/test_cli_progress.py.
"""
import os
import unittest

os.environ.setdefault("NO_COLOR", "1")  # keep assertions ANSI-free

from tests.helpers import _hr, _m, _pwr, _zweek

from trainmate.plan_versions import delta_baseline
from trainmate.text import visible_len
from trainmate.analytics.intensity import window_sport_stats, zone_currency
from trainmate.cli.progress_load import TABLE_WIDTH, WEEK_COL_WIDTH
from trainmate.cli.progress_zones import (
    _orphan_week_note, fmt_zone_cell, render_mesocycle_section, unknown_sport_preferences,
    zone_section, zone_table, zone_week_cells,
)


# ---------------------------------------------------------------- zone tables
# DESIGN_intensity_distribution.md §9.6.


class TestZoneCell(unittest.TestCase):
    def test_under_an_hour_is_three_characters(self):
        self.assertEqual(fmt_zone_cell(_m(55)), "55m")

    def test_hours_render_four_characters(self):
        self.assertEqual(fmt_zone_cell(_m(300)), "5h00")

    def test_ten_hours_and_up_drop_the_minutes_to_stay_inside_the_budget(self):
        self.assertEqual(fmt_zone_cell(_m(12 * 60 + 30)), "12h")
        self.assertLessEqual(len(fmt_zone_cell(_m(99 * 60))), 4)

    def test_no_seconds_is_a_dash_not_a_zero(self):
        self.assertEqual(fmt_zone_cell(0), "—")


class TestZoneWeekCells(unittest.TestCase):
    """`—`, `!` and a plain row are three different facts (§9.6)."""

    def test_sport_not_trained_renders_dashes_and_takes_no_marker(self):
        week = _zweek("2026-06-29", rows=[], seconds={"cycling": _m(120)})
        cells, undercounted = zone_week_cells(week, "running", "hr", 5)
        self.assertEqual(cells, ["—"] * 5)
        self.assertFalse(undercounted)

    def test_trained_but_unrecorded_renders_dashes_and_takes_the_marker(self):
        week = _zweek("2026-06-29", rows=[], seconds={"running": _m(120)})
        cells, undercounted = zone_week_cells(week, "running", "hr", 5)
        self.assertEqual(cells, ["—"] * 5)
        self.assertTrue(undercounted)

    def test_a_too_short_unrecorded_session_does_not_light_the_week(self):
        # §11's floor applies to this branch too: 5 minutes of unrecorded training is
        # not evidence that the week's zone minutes are undercounted.
        week = _zweek("2026-06-29", rows=[], seconds={"running": _m(5)}, judged={})
        cells, undercounted = zone_week_cells(week, "running", "hr", 5)
        self.assertEqual(cells, ["—"] * 5)
        self.assertFalse(undercounted)

    def test_no_data_in_the_chosen_currency_does_not_fall_back_to_the_other(self):
        week = _zweek(
            "2026-06-29", rows=[_hr("cycling", [10, 60, 5, 2, 1])],
            seconds={"cycling": _m(78)},
        )
        cells, _ = zone_week_cells(week, "cycling", "power", 7)
        self.assertEqual(cells, ["—"] * 7)

    def test_marker_fires_at_the_display_bar_not_the_load_bar(self):
        # 0.55 clears `hr_zone_coverage_min` (0.5) and still misses nearly half the
        # recorded time, so the row must admit it.
        week = _zweek(
            "2026-06-29", rows=[_hr("running", [10, 60, 5, 2, 1], coverage=0.55)],
            seconds={"running": _m(140)},
        )
        _, undercounted = zone_week_cells(week, "running", "hr", 5)
        self.assertTrue(undercounted)


class TestZoneTableWidth(unittest.TestCase):
    def test_seven_zone_power_table_fits_48_columns_with_a_ten_hour_z2(self):
        weeks = [_zweek(
            "2026-06-29",
            rows=[_pwr("cycling", [90, 11 * 60, 70, 35, 15, 5, 3])],
            seconds={"cycling": _m(878)},
        )]
        lines, _ = zone_table(weeks, "cycling", "power", _m(878), _m(878), 0.9)
        for line in lines:
            self.assertLessEqual(visible_len(line), TABLE_WIDTH, msg=repr(line))
        row = next(l for l in lines if l.startswith("w/c"))
        self.assertEqual(visible_len(row), TABLE_WIDTH)
        self.assertIn("11h", row)

    def test_five_zone_hr_table_is_38_columns(self):
        weeks = [_zweek(
            "2026-06-29", rows=[_hr("running", [50, 300, 35, 15, 5])],
            seconds={"running": _m(405)},
        )]
        lines, _ = zone_table(weeks, "running", "hr", _m(405), _m(405), 0.94)
        row = next(l for l in lines if l.startswith("w/c"))
        self.assertEqual(visible_len(row), 38)

    def test_in_progress_and_undercounted_both_fit_the_week_column(self):
        weeks = [_zweek(
            "2026-07-06", rows=[_hr("running", [22, 82, 38, 7, 3], coverage=0.4)],
            seconds={"running": _m(400)}, in_progress=True,
        )]
        lines, markers = zone_table(weeks, "running", "hr", _m(400), _m(400), 0.4)
        row = next(l for l in lines if l.startswith("w/c"))
        self.assertTrue(row.startswith("w/c 07-06*!"))
        self.assertEqual(len("w/c 07-06*!"), WEEK_COL_WIDTH)
        self.assertIn("!", markers)


class TestZoneSection(unittest.TestCase):
    def _weeks(self):
        return [
            _zweek("2026-06-22",
                   rows=[_hr("running", [55, 258, 62, 17, 7]),
                         _pwr("cycling", [45, 140, 30, 15, 7, 3, 1])],
                   seconds={"running": _m(399), "cycling": _m(241)}),
            _zweek("2026-06-29",
                   rows=[_pwr("cycling", [90, 570, 70, 35, 15, 5, 3])],
                   seconds={"cycling": _m(788)}, label="Base 2"),
        ]

    def test_one_table_per_sport_so_a_swap_reads_as_a_swap(self):
        lines = zone_section(self._weeks(), ["running", "cycling"])
        text = "\n".join(lines)
        self.assertIn("ZONES running", text)
        self.assertIn("ZONES cycling", text)
        # Running absent in 06-29 while cycling Z2 climbs: one table alone would have
        # called that a collapsed aerobic base.
        self.assertIn("—", text)

    def test_header_carries_the_sport_share_of_the_window(self):
        lines = zone_section(self._weeks(), ["running"])
        header = next(l for l in lines if l.startswith("ZONES"))
        self.assertIn(" of ", header)
        self.assertIn("[HR", header)

    def test_hidden_weeks_are_named_in_the_footer(self):
        lines = zone_section(self._weeks(), ["running"], hidden_weeks=3)
        self.assertIn("+3 more weeks (--weeks all)", "\n".join(lines))

    def test_a_named_sport_with_no_rows_lists_the_sports_that_have_them(self):
        lines = zone_section(self._weeks(), [], explicit=["swimming"])
        text = "\n".join(lines)
        self.assertIn("No zone data for swimming", text)
        self.assertIn("cycling", text)
        self.assertIn("running", text)

    def test_every_line_stays_inside_the_column_budget(self):
        for line in zone_section(self._weeks(), ["running", "cycling"], hidden_weeks=3):
            self.assertLessEqual(visible_len(line), TABLE_WIDTH, msg=repr(line))


class TestZoneTableFutureHalf(unittest.TestCase):
    """§9.8: ghost rows under today, exactly like the load table's ghost bars — which
    closes §9.6's one asymmetry."""

    TODAY = "2026-06-24"

    def _weeks(self):
        past = _zweek("2026-06-22",
                      rows=[_hr("running", [55, 258, 62, 17, 7])],
                      seconds={"running": _m(399)}, in_progress=True)
        future = _zweek("2026-06-29", seconds={})
        future["planned_zone_rows"] = [_hr("running", [20, 240, 30, 20, 5], 1.0)]
        return [past, future]

    def test_future_weeks_render_the_plan_and_are_marked(self):
        lines, markers = zone_table(
            self._weeks(), "running", "hr", _m(399), _m(399), 0.94, today=self.TODAY
        )
        rows = [l for l in lines if l.startswith("w/c")]
        self.assertTrue(rows[0].startswith("w/c 06-22*"))   # measured, in progress
        self.assertTrue(rows[1].startswith("w/c 06-29+"))   # prescribed
        self.assertIn("4h00", rows[1])                      # 240 min of planned Z2
        self.assertIn("+", markers)

    def test_a_future_week_with_no_plan_renders_dashes_not_the_past(self):
        weeks = self._weeks()
        weeks[1]["planned_zone_rows"] = []
        lines, _ = zone_table(
            weeks, "running", "hr", _m(399), _m(399), 0.94, today=self.TODAY
        )
        future = [l for l in lines if l.startswith("w/c 06-29")][0]
        self.assertNotIn("+", future)
        self.assertEqual(future.count("—"), 5)

    def test_a_plan_in_the_other_currency_is_declared_never_converted(self):
        # Power Z6/Z7 have no HR equivalent, so collapsing seven onto five would be
        # banding by the back door and §5 forbids it.
        weeks = self._weeks()
        weeks[1]["planned_zone_rows"] = [_pwr("running", [20, 240, 30, 20, 5, 2, 1], 1.0)]
        lines, markers = zone_table(
            weeks, "running", "hr", _m(399), _m(399), 0.94, today=self.TODAY
        )
        future = [l for l in lines if l.startswith("w/c 06-29")][0]
        self.assertEqual(future.count("—"), 5)
        self.assertIn("~mismatch", markers)

    def test_the_mismatch_is_explained_in_the_section_footer(self):
        weeks = self._weeks()
        weeks[1]["planned_zone_rows"] = [_pwr("running", [20, 240, 30, 20, 5, 2, 1], 1.0)]
        text = " ".join(
            l.strip() for l in
            zone_section(weeks, ["running"], today=self.TODAY, stats_weeks=weeks[:1])
        )
        self.assertIn("written in the other currency", text)

    def test_the_currency_choice_still_reads_measured_coverage_only(self):
        # A future week's planned rows must not vote on which column the table is drawn
        # in — coverage is a property of recordings.
        weeks = self._weeks()
        stats = window_sport_stats(weeks[:1])
        self.assertEqual(zone_currency(stats, "running"), "hr")


class TestUnknownSportPreferences(unittest.TestCase):
    def test_a_canonical_sport_warns_about_nothing(self):
        self.assertEqual(unknown_sport_preferences(["cycling", "running"]), [])

    def test_a_free_text_entry_warns_and_suggests(self):
        [warning] = unknown_sport_preferences(["Road cycling"])
        self.assertIn("'Road cycling' is not a known sport", warning)
        self.assertIn("cycling", warning)

    def test_a_genuinely_new_sport_warns_without_a_suggestion(self):
        [warning] = unknown_sport_preferences(["swimming"])
        self.assertIn("not a known sport", warning)
        self.assertNotIn("Did you mean", warning)

    def test_an_alias_is_not_a_warning(self):
        self.assertEqual(unknown_sport_preferences(["road_biking"]), [])


class TestOrphanWeekNote(unittest.TestCase):
    MESOCYCLES = [{"start_date": "2026-05-25", "end_date": "2026-06-14"},
              {"start_date": "2026-06-29", "end_date": "2026-07-26"}]

    def test_weeks_belonging_to_no_mesocycle_are_named(self):
        weeks = [_zweek(d) for d in
                 ("2026-06-01", "2026-06-15", "2026-06-22", "2026-06-29")]
        lines = _orphan_week_note(weeks, self.MESOCYCLES)
        note = " ".join(l.strip() for l in lines)
        self.assertIn("2 weeks", note)
        self.assertIn("06-15", note)
        self.assertIn("06-22", note)
        self.assertIn("partial week is excluded", note)
        self.assertIn("without --mesocycles", note)
        for line in lines:
            self.assertLessEqual(visible_len(line), TABLE_WIDTH, msg=repr(line))

    def test_a_long_orphan_list_is_capped(self):
        weeks = [_zweek(f"2026-06-{d:02d}") for d in (15, 22)] + [
            _zweek("2026-08-03"), _zweek("2026-08-10")
        ]
        note = "\n".join(_orphan_week_note(weeks, self.MESOCYCLES))
        self.assertIn("+2 more", note)

    def test_full_coverage_says_nothing(self):
        self.assertEqual(_orphan_week_note([_zweek("2026-06-29")], self.MESOCYCLES), [])


class _StubDb:
    """The five accessors `render_mesocycle_section` reads, and nothing else — it takes a
    `dbh` precisely so the mesocycle walk stays testable without a database.

    `preceding` is `(macro, mesocycles)` for the previous *goal's* plan, the only other
    lineage the walk pulls in; there is deliberately no way to hand it a superseded
    version of the governing plan (DESIGN_plan_rollback.md §6.1)."""

    def __init__(self, mesos, activities, preceding=None, governing_id=1):
        self._mesos, self._activities = mesos, activities
        self._governing_id = governing_id
        self._preceding_macro, self._preceding_mesos = preceding or (None, [])

    def get_governing_macrocycle(self):
        return {"id": self._governing_id, "objective_id": 1}

    def get_preceding_macrocycle(self, objective_id):
        return self._preceding_macro

    def get_mesocycles_for_macrocycle(self, macrocycle_id):
        if self._preceding_macro and macrocycle_id == self._preceding_macro["id"]:
            return self._preceding_mesos
        return self._mesos

    def get_benchmark_results(self):
        return []

    def get_completed_activities(self, start_date=None, end_date=None):
        return [a for a in self._activities if start_date <= a["date"] <= end_date]


def _run_act(date, minutes, z2_minutes):
    row = {"date": date, "activity_type": "running", "duration_sec": minutes * 60,
           "rpe": None, "tss": None}
    for i in range(1, 6):
        row[f"zone{i}_sec"] = z2_minutes * 60 if i == 2 else 0
    for i in range(1, 8):
        row[f"power_zone{i}_sec"] = 0
    return row


class TestMesocycleSection(unittest.TestCase):
    """`--mesocycles` reproduces the very loss §9.6 exists to prevent, by more than one
    route, so it must name both."""

    TODAY = "2026-07-09"
    MESOS = [
        {"id": 1, "macrocycle_id": 1, "name": "Base 1", "focus": "aerobic volume",
         "start_date": "2026-05-25", "end_date": "2026-06-14"},
        {"id": 2, "macrocycle_id": 1, "name": "Base 2",
         "focus": "aerobic consolidation",
         "start_date": "2026-06-29", "end_date": "2026-07-26"},
    ]

    def _payload_weeks(self):
        mondays = ["2026-06-01", "2026-06-08", "2026-06-15", "2026-06-22",
                   "2026-06-29", "2026-07-06"]
        return [_zweek(m, seconds={"running": _m(300)},
                       rows=[_hr("running", [10, 250, 30, 8, 2])]) for m in mondays]

    def _section(self):
        acts = [_run_act(d, 300, 250) for d in
                ("2026-06-02", "2026-06-09", "2026-06-16", "2026-06-23",
                 "2026-06-30", "2026-07-07")]
        return render_mesocycle_section(
            _StubDb(self.MESOS, acts), {"weeks": self._payload_weeks()},
            8, self.TODAY, [], ["running"],
        )

    def test_reports_each_mesocycle_overlapping_the_window(self):
        text = "\n".join(self._section())
        self.assertIn("ZONES BY MESOCYCLE — running", text)
        self.assertIn("Base 1", text)
        self.assertIn("Base 2", text)
        self.assertIn("aerobic volume", text)  # the stated focus, to be graded against

    def test_names_the_weeks_that_belong_to_no_mesocycle(self):
        text = " ".join(l.strip() for l in self._section())
        self.assertIn("belong to no mesocycle", text)
        self.assertIn("06-15", text)
        self.assertIn("06-22", text)

    def test_names_the_excluded_partial_tails(self):
        text = " ".join(l.strip() for l in self._section())
        self.assertIn("final partial week is excluded", text)

    def test_the_caveats_are_emitted_once_not_once_per_mesocycle(self):
        text = "\n".join(self._section())
        self.assertEqual(text.count("interval work with rest"), 1)

    def test_every_line_stays_inside_the_column_budget(self):
        for line in self._section():
            self.assertLessEqual(visible_len(line), TABLE_WIDTH, msg=repr(line))


class TestDeltaStopsAtThePlanBoundary(unittest.TestCase):
    """A long window reaches back into the previous goal's plan. Those mesocycles are worth
    reporting; the change *against* them is not — it spans a taper, a race and an
    off-season (DESIGN_plan_rollback.md §6.1)."""

    TODAY = "2026-07-09"
    # The governing plan (macro 2), and last season's (macro 1) before it.
    THIS_SEASON = [
        {"id": 3, "macrocycle_id": 2, "name": "Base 1", "focus": "aerobic volume",
         "start_date": "2026-05-25", "end_date": "2026-06-21"},
        {"id": 4, "macrocycle_id": 2, "name": "Base 2",
         "focus": "aerobic consolidation",
         "start_date": "2026-06-22", "end_date": "2026-07-19"},
    ]
    LAST_SEASON = [
        {"id": 1, "macrocycle_id": 1, "name": "Spring Peak", "focus": "race sharpening",
         "start_date": "2026-04-06", "end_date": "2026-05-03"},
    ]

    def _section(self):
        mondays = ["2026-04-06", "2026-04-13", "2026-04-20", "2026-04-27",
                   "2026-05-25", "2026-06-01", "2026-06-08", "2026-06-15",
                   "2026-06-22", "2026-06-29", "2026-07-06"]
        weeks = [_zweek(m, seconds={"running": _m(300)},
                        rows=[_hr("running", [10, 250, 30, 8, 2])]) for m in mondays]
        acts = [_run_act(f"{m[:8]}{int(m[8:]) + 1:02d}", 300, 250) for m in mondays]
        db = _StubDb(self.THIS_SEASON, acts, governing_id=2,
                     preceding=({"id": 1, "objective_id": 1}, self.LAST_SEASON))
        return "\n".join(render_mesocycle_section(
            db, {"weeks": weeks}, "all", self.TODAY, [], ["running"],
        ))

    def test_last_seasons_mesocycle_is_still_reported(self):
        self.assertIn("Spring Peak", self._section())

    def test_no_delta_is_drawn_across_the_boundary(self):
        self.assertNotIn("Change vs Spring Peak", self._section())

    def test_the_within_plan_delta_survives(self):
        self.assertIn("Change vs Base 1", self._section())


class TestDeltaBaseline(unittest.TestCase):
    """`delta_baseline` on its own — the rule both the CLI section and the strategy
    prompt read it from."""

    MESOCYCLES = [
        {"name": "Spring Peak", "macrocycle_id": 1},
        {"name": "Base 1", "macrocycle_id": 2},
        {"name": "Base 2", "macrocycle_id": 2},
    ]

    def test_the_first_mesocycle_has_no_baseline(self):
        self.assertIsNone(delta_baseline(self.MESOCYCLES, 0))

    def test_a_plan_boundary_has_no_baseline(self):
        self.assertIsNone(delta_baseline(self.MESOCYCLES, 1))

    def test_within_a_plan_the_baseline_is_the_mesocycle_before(self):
        self.assertEqual(delta_baseline(self.MESOCYCLES, 2)["name"], "Base 1")

    def test_mesocycles_predating_the_column_still_compare(self):
        """Legacy rows carry no `macrocycle_id`; None == None, so they keep their delta
        rather than silently losing it."""
        legacy = [{"name": "A"}, {"name": "B"}]
        self.assertEqual(delta_baseline(legacy, 1)["name"], "A")

if __name__ == "__main__":
    unittest.main()
