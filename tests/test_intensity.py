"""The zone model — see DESIGN_intensity_distribution.md.

What `analytics/intensity.py` computes from a set of activities: the zone
rows themselves, the coverage formula and the floor a session has to clear
to vote on it (§7, §11), the canonical `cycling` mapping that stops one
athlete's riding splitting across two rows (§6.1), which currency a sport is
read in, and the distribution the week planner states up front (§9.8).

The text tables built from these rows are `test_zone_tables.py`; the
mesocycle report that assembles them is `test_mesocycle_report.py`.
"""
import unittest

from tests.helpers import _hr, _m, _pwr, _zweek
from stamind.analytics import intensity
from stamind.analytics.intensity import (
    select_zone_sports, window_sport_stats, zone_currency,
)
from stamind.sports import canonical_sport


def act(date, sport, duration_sec, hr=None, power=None, rpe=None):
    """A completed-activity row, zone columns filled the way `garmin/sync.py` writes
    them: zeros for HR when nothing was recorded, not NULLs."""
    row = {
        "date": date, "activity_type": sport, "duration_sec": duration_sec, "rpe": rpe,
        "tss": None,
    }
    for i in range(1, 6):
        row[f"zone{i}_sec"] = (hr or [0] * 5)[i - 1]
    for i in range(1, 8):
        row[f"power_zone{i}_sec"] = (power or [0] * 7)[i - 1]
    return row


class TestCoverage(unittest.TestCase):
    """§7: one formula, both currencies, one shared denominator."""

    def test_meterless_ride_dilutes_power_coverage_not_hr(self):
        # Two hours of riding: both recorded HR, only one had a power meter. Power
        # coverage must be ~50% of BIKE TIME — deriving it against HR time instead
        # would put two different denominators under one word.
        acts = [
            act("2026-06-02", "cycling", 3600, hr=[0, 3600, 0, 0, 0],
                power=[0, 3600, 0, 0, 0, 0, 0]),
            act("2026-06-03", "cycling", 3600, hr=[0, 3600, 0, 0, 0]),
        ]
        rows = intensity.zone_rows(acts)
        by_currency = {r.currency: r for r in rows}
        self.assertAlmostEqual(by_currency["hr"].coverage, 1.0, places=3)
        self.assertAlmostEqual(by_currency["power"].coverage, 0.5, places=3)

    def test_no_currency_row_without_recorded_seconds(self):
        # Strength training never grows a `[pwr] 0%` row.
        rows = intensity.zone_rows(
            [act("2026-06-02", "strength_training", 3600, hr=[600, 2400, 300, 0, 0])]
        )
        self.assertEqual([r.currency for r in rows], ["hr"])

    def test_zero_zone_columns_do_not_invent_a_row(self):
        # sync.py writes zeros, not NULLs, when an activity has no average HR.
        self.assertEqual(intensity.zone_rows([act("2026-06-02", "hiking", 3600)]), [])


class TestJudgeableCoverage(unittest.TestCase):
    """§11: a session too short to hide load gets no vote on the undercount markers,
    but keeps its minutes everywhere."""

    def test_short_session_keeps_its_minutes_but_not_its_vote(self):
        # An hour ridden at full coverage plus a 5-minute session with a cold strap.
        # `coverage` sees both (it answers "how much of the riding did HR see");
        # `judged_coverage` sees only the hour (it answers "did the strap work").
        acts = [
            act("2026-06-02", "cycling", 3600, hr=[0, 3600, 0, 0, 0]),
            act("2026-06-03", "cycling", 300, hr=[30, 0, 0, 0, 0]),
        ]
        row = intensity.zone_rows(acts)[0]
        self.assertAlmostEqual(row.coverage, 3630 / 3900, places=3)
        self.assertAlmostEqual(row.judged_coverage, 1.0, places=3)
        self.assertFalse(row.undercounted)
        self.assertEqual(sum(row.seconds), 3630)  # the short session's minutes count

    def test_nothing_judgeable_leaves_coverage_unanswerable(self):
        row = intensity.zone_rows(
            [act("2026-06-02", "yoga", 300, hr=[30, 0, 0, 0, 0])]
        )[0]
        self.assertIsNone(row.judged_coverage)
        self.assertFalse(row.undercounted)  # unanswerable is not "failed"

    def test_the_bar_is_per_sport(self):
        # The same 0.5 coverage: a failure for running, normal for strength training,
        # where the uncovered half is the rest between sets (§11).
        def row_for(sport):
            return intensity.zone_rows(
                [act("2026-06-02", sport, 3600, hr=[1800, 0, 0, 0, 0])]
            )[0]
        self.assertTrue(row_for("running").undercounted)
        self.assertFalse(row_for("strength_training").undercounted)

    def test_config_overrides_the_shipped_per_sport_table(self):
        import unittest.mock
        from stamind.config import config
        with unittest.mock.patch.object(
            type(config), "zone_coverage_display_min_by_sport",
            new_callable=unittest.mock.PropertyMock,
            return_value={"strength_training": 0.9},
        ):
            self.assertTrue(intensity.zone_rows(
                [act("2026-06-02", "strength_training", 3600, hr=[1800, 0, 0, 0, 0])]
            )[0].undercounted)

    def test_every_per_sport_key_is_canonical(self):
        # `coverage_display_min` canonicalizes before the lookup, so an alias key is
        # unreachable and its sport silently falls back to the global 0.8 (§11 rev note
        # 2026-08-04). Guarding the whole table stops the class of bug coming back.
        for key in intensity.COVERAGE_MIN_BY_SPORT:
            self.assertEqual(canonical_sport(key), key)

    def test_resort_skiing_is_graded_against_the_lift_served_bar(self):
        # Garmin files resort skiing and snowboarding under `downhill_skiing`; the
        # chairlift back up is not a failed recording, so 0.26 coverage must not mark.
        self.assertEqual(intensity.coverage_display_min("resort_skiing"), 0.15)
        self.assertEqual(intensity.coverage_display_min("resort_snowboarding"), 0.15)
        row = intensity.zone_rows(
            [act("2026-06-02", "resort_skiing", 3600, hr=[900, 0, 0, 0, 0])]
        )[0]
        self.assertFalse(row.undercounted)

    def test_planned_rows_never_mark(self):
        # A prescription is not a recording, so it has no gap to report.
        rows = intensity.planned_zone_rows([{
            "date": "2026-06-02", "sport_type": "running", "duration_minutes": 60,
            "planned_zone_currency": "hr", "planned_zone1_sec": 600,
            "planned_zone2_sec": 0, "planned_zone3_sec": 0, "planned_zone4_sec": 0,
            "planned_zone5_sec": 0,
        }])
        self.assertFalse(rows[0].undercounted)


class TestCanonicalCycling(unittest.TestCase):
    """§6.1: one vocabulary, so an athlete's riding is not split across rows."""

    def test_every_bike_alias_folds_into_cycling(self):
        for alias in ("road_biking", "gravel_cycling", "cyclocross", "mountain_biking",
                      "bmx", "indoor_cycling", "virtual_ride", "road_cycling", "biking"):
            self.assertEqual(canonical_sport(alias), "cycling", alias)

    def test_gravel_and_road_share_one_row(self):
        rows = intensity.zone_rows([
            act("2026-06-02", "gravel_cycling", 3600, hr=[0, 3600, 0, 0, 0]),
            act("2026-06-03", "road_biking", 3600, hr=[0, 3600, 0, 0, 0]),
        ])
        self.assertEqual([r.sport for r in rows], ["cycling"])
        self.assertEqual(rows[0].seconds[1], 7200)

    def test_unknown_type_falls_through_as_its_own_row(self):
        # A miss is visible and repairable: you see the row and know what alias to add.
        rows = intensity.zone_rows(
            [act("2026-06-02", "e_bike_ride", 3600, hr=[0, 3600, 0, 0, 0])]
        )
        self.assertEqual(rows[0].sport, "e_bike_ride")


class TestPickCurrency(unittest.TestCase):
    def test_power_below_the_bar_loses_to_fuller_hr(self):
        self.assertEqual(
            intensity.pick_currency({"power": 0.6, "hr": 0.95}), "hr"
        )

    def test_power_at_the_bar_wins_even_against_fuller_hr(self):
        self.assertEqual(
            intensity.pick_currency({"power": 0.8, "hr": 0.99}), "power"
        )

    def test_power_wins_when_it_is_the_only_currency(self):
        self.assertEqual(intensity.pick_currency({"power": 0.4}), "power")

    def test_nothing_recorded_picks_nothing(self):
        self.assertIsNone(intensity.pick_currency({}))
        self.assertIsNone(intensity.pick_currency({"power": 0.0, "hr": 0.0}))


class TestSportDurations(unittest.TestCase):
    def test_a_sport_with_sessions_and_no_zone_rows_still_has_a_duration(self):
        acts = [act("2026-06-02", "yoga", 1800)]
        self.assertEqual(intensity.sport_durations(acts), {"yoga": 1800})
        self.assertEqual(intensity.zone_rows(acts), [])

    def test_aliases_fold_into_one_canonical_duration(self):
        acts = [act("2026-06-02", "gravel_cycling", 3600),
                act("2026-06-03", "road_biking", 1800)]
        self.assertEqual(intensity.sport_durations(acts), {"cycling": 5400})


class TestPlannedZones(unittest.TestCase):
    """§9.8: the week planner states the distribution as structured data while it still knows
    the intent, instead of the app parsing it back out of prose afterwards."""

    def test_parses_an_hr_prescription(self):
        currency, secs = intensity.parse_planned_zones({
            "planned_zone_currency": "hr",
            "planned_zone_sec": [300, 1800, 600, 0, 0],
        })
        self.assertEqual(currency, "hr")
        self.assertEqual(secs, [300, 1800, 600, 0, 0, None, None])

    def test_drops_entries_past_the_currencys_zone_count(self):
        # Five HR zones: a sixth and seventh value have no HR equivalent.
        _, secs = intensity.parse_planned_zones({
            "planned_zone_currency": "hr",
            "planned_zone_sec": [300, 1800, 600, 0, 0, 120, 60],
        })
        self.assertEqual(secs[5:], [None, None])

    def test_an_unknown_currency_yields_nothing(self):
        self.assertEqual(
            intensity.parse_planned_zones(
                {"planned_zone_currency": "rpe", "planned_zone_sec": [60]}
            ),
            (None, None),
        )

    def test_an_all_zero_distribution_is_no_prescription(self):
        self.assertEqual(
            intensity.parse_planned_zones(
                {"planned_zone_currency": "hr", "planned_zone_sec": [0, 0, 0, 0, 0]}
            ),
            (None, None),
        )

    def test_seconds_are_never_rescaled_to_the_duration(self):
        # A prescription, not an accounting identity: 40 minutes of zones under a
        # 60-minute session is stored as emitted.
        _, secs = intensity.parse_planned_zones({
            "planned_zone_currency": "hr", "planned_zone_sec": [600, 1200, 600, 0, 0],
            "duration_minutes": 60,
        })
        self.assertEqual(sum(s for s in secs if s), 2400)

    def test_renders_zone_names_not_indices(self):
        text = intensity.format_planned_zones({
            "planned_zone_currency": "hr",
            "planned_zone1_sec": 1500, "planned_zone2_sec": 1800,
            "planned_zone3_sec": 0, "planned_zone4_sec": 600, "planned_zone5_sec": 0,
        })
        self.assertEqual(text, "Target: ~25min recovery, ~30min aerobic, ~10min threshold")
        self.assertNotIn("Z1", text)

    def test_a_proposal_renders_from_the_week_planners_list(self):
        # Not written yet, so no columns: the list is read through the write's own check,
        # which drops the slots past the currency's five HR zones.
        text = intensity.format_planned_zones({
            "planned_zone_currency": "HR", "planned_zone_sec": [1500, 1800, 0, 600, 0, 900],
        })
        self.assertEqual(text, "Target: ~25min recovery, ~30min aerobic, ~10min threshold")
        self.assertIsNone(intensity.format_planned_zones({
            "planned_zone_currency": "hr", "planned_zone_sec": [0, 0, 0, 0, 0],
        }))

    def test_a_session_with_no_target_renders_nothing(self):
        self.assertIsNone(intensity.format_planned_zones({"title": "Rest"}))

    def test_planned_rows_sum_per_sport_and_currency(self):
        rows = intensity.planned_zone_rows([
            {"sport_type": "running", "planned_zone_currency": "hr",
             "planned_zone1_sec": 300, "planned_zone2_sec": 1800},
            {"sport_type": "running", "planned_zone_currency": "hr",
             "planned_zone2_sec": 1200, "planned_zone4_sec": 600},
            {"sport_type": "road_biking", "planned_zone_currency": "power",
             "planned_zone2_sec": 3600},
            {"sport_type": "rest"},
        ])
        by_key = {(r.sport, r.currency): r for r in rows}
        self.assertEqual(by_key[("running", "hr")].seconds, (300, 3000, 0, 600, 0))
        self.assertEqual(len(by_key[("cycling", "power")].seconds), 7)
        self.assertEqual(len(rows), 2)  # rest carries no target


class TestPlanningCurrency(unittest.TestCase):
    """§9.8: the planning currency is chosen by §9.6's rule — one rule applied twice, so
    the plan is never written in a currency the table cannot render."""

    def test_a_metered_cyclist_is_planned_in_power(self):
        acts = [act("2026-06-02", "cycling", 3600,
                    hr=[0, 3400, 0, 0, 0], power=[0, 3500, 0, 0, 0, 0, 0])]
        self.assertEqual(intensity.currency_by_sport(acts), {"cycling": "power"})

    def test_a_mixed_meter_cyclist_is_planned_in_hr(self):
        acts = [
            act("2026-06-02", "cycling", 3600,
                hr=[0, 3500, 0, 0, 0], power=[0, 3500, 0, 0, 0, 0, 0]),
            act("2026-06-03", "cycling", 3600, hr=[0, 3400, 0, 0, 0]),
        ]
        self.assertEqual(intensity.currency_by_sport(acts), {"cycling": "hr"})

    def test_a_sport_with_no_zone_model_gets_no_currency(self):
        acts = [act("2026-06-02", "yoga", 1800)]
        self.assertEqual(intensity.currency_by_sport(acts), {})


class TestZoneSportSelection(unittest.TestCase):
    def _stats(self):
        weeks = [_zweek(
            "2026-06-29",
            rows=[_hr("running", [50, 300, 35, 15, 5]),
                  _pwr("cycling", [40, 130, 25, 12, 6, 2, 1]),
                  _hr("cycling", [45, 140, 30, 14, 7])],
            seconds={"running": _m(405), "cycling": _m(216), "yoga": _m(30)},
        )]
        return window_sport_stats(weeks), weeks

    def test_coverage_shares_one_denominator_across_currencies(self):
        stats, _ = self._stats()
        cycling = stats["cycling"]
        self.assertAlmostEqual(
            cycling["coverage"]["power"], _m(216) / _m(216), places=6
        )
        self.assertAlmostEqual(
            cycling["coverage"]["hr"], _m(236) / _m(216), places=6
        )

    def test_default_keeps_config_order_not_volume_order(self):
        stats, _ = self._stats()
        sports, _, _ = select_zone_sports(None, ["cycling", "running"], stats)
        self.assertEqual(sports, ["cycling", "running"])

    def test_low_volume_sport_is_named_never_silently_dropped(self):
        stats, _ = self._stats()
        sports, low, no_data = select_zone_sports(
            None, ["running", "cycling", "yoga"], stats
        )
        self.assertEqual(sports, ["running", "cycling"])
        self.assertEqual(no_data, ["yoga"])  # 30 min and no zone rows at all
        self.assertEqual(low, [])

    def test_naming_a_sport_overrides_every_filter(self):
        stats, _ = self._stats()
        sports, low, no_data = select_zone_sports(["yoga"], ["running"], stats)
        self.assertEqual(sports, ["yoga"])
        self.assertEqual((low, no_data), ([], []))

    def test_explicit_names_are_canonicalised(self):
        stats, _ = self._stats()
        sports, _, _ = select_zone_sports(["Road_Biking"], [], stats)
        self.assertEqual(sports, ["cycling"])


class TestZoneCurrency(unittest.TestCase):
    def test_forcing_a_currency_the_sport_lacks_has_no_effect(self):
        stats = {"running": {
            "seconds": 100.0, "zone_seconds": {"hr": 95.0},
            "coverage": {"hr": 0.95},
        }}
        self.assertEqual(zone_currency(stats, "running", forced="power"), "hr")

    def test_forcing_a_currency_the_sport_has_wins_over_coverage(self):
        stats = {"cycling": {
            "seconds": 100.0, "zone_seconds": {"power": 60.0, "hr": 95.0},
            "coverage": {"power": 0.60, "hr": 0.95},
        }}
        self.assertEqual(zone_currency(stats, "cycling", forced="power"), "power")


if __name__ == "__main__":
    unittest.main()
