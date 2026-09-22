"""The report for one mesocycle — see DESIGN_intensity_distribution.md.

The window the report divides and the completed-weeks divisor at a
mesocycle's first six days and across a partial tail (§4), the current week
stated as raw minutes rather than extrapolated (§9.3), the per-sport delta
suppression that keeps a changed sport mix from reading as a -100% swing
(§4.1), the structural row beside the zone rows (§6), what the plan asked beside what
the athlete produced (§9.2a), and the width the whole report has to fit inside a prompt.
"""
import unittest

from stamind.analytics.mesocycle_report import (
    current_week_window, measured_window, mesocycle_report, rate_window,
)


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


def fetch_from(activities):
    def fetch(start, end):
        return [a for a in activities if start <= a["date"] <= end]
    return fetch


def flat(text):
    """Whitespace-collapsed, so an assertion on a phrase doesn't depend on where the
    renderer chose to wrap it."""
    return " ".join(text.split())


MESOCYCLE = {
    "name": "Base 2", "focus": "aerobic volume",
    "start_date": "2026-06-01", "end_date": "2026-06-28",
}


def planned(date, sport, currency, secs):
    """A planned-workout row carrying §9.8's intensity target, as `save_workout` stores it."""
    row = {"date": date, "sport_type": sport, "planned_zone_currency": currency}
    for i, s in enumerate(secs, start=1):
        row[f"planned_zone{i}_sec"] = s
    return row


class TestCompletedWeeksDivisor(unittest.TestCase):
    """§4: only whole 7-day weeks from the mesocycle's own start divide a rate, and the
    partial tail is excluded from BOTH sides of the division."""

    def test_first_six_days_have_no_rate(self):
        # Day 6 of the mesocycle: nothing has completed a week, so there is no divisor.
        self.assertIsNone(
            rate_window("2026-06-01", "2026-06-28", "2026-06-06")
        )

    def test_seventh_day_yields_exactly_one_week(self):
        window = rate_window("2026-06-01", "2026-06-28", "2026-06-08")
        self.assertEqual(window, ("2026-06-01", "2026-06-07", 1))

    def test_partial_tail_is_excluded_from_the_window(self):
        # 16 days elapsed -> 2 completed weeks, and the window STOPS at day 14. The
        # numerator must drop the tail too, or the rate divides 16 days of work by 2.
        window = rate_window("2026-06-01", "2026-06-28", "2026-06-17")
        self.assertEqual(window, ("2026-06-01", "2026-06-14", 2))

    def test_finished_mesocycle_counts_its_last_day(self):
        # Measured one day past the end, all 28 days are over -> 4 weeks, not 3.
        window = rate_window("2026-06-01", "2026-06-28", "2026-06-29")
        self.assertEqual(window, ("2026-06-01", "2026-06-28", 4))

    def test_weeks_run_from_the_mesocycle_start_not_calendar_mondays(self):
        # 2026-06-04 is a Thursday; its weeks are Thursday-to-Wednesday.
        window = rate_window("2026-06-04", "2026-07-01", "2026-06-12")
        self.assertEqual(window, ("2026-06-04", "2026-06-10", 1))

    def test_too_young_mesocycle_reports_raw_minutes_and_says_so(self):
        acts = [act("2026-06-02", "running", 3600, hr=[300, 3000, 200, 100, 0])]
        text = mesocycle_report(MESOCYCLE, "2026-06-05", fetch_from(acts))
        self.assertIn("RAW minutes", text)
        self.assertIn("too young for a per-week rate", flat(text))
        self.assertNotIn("per week over", text)

    def test_mesocycle_that_has_not_started_reports_nothing(self):
        # get_active_mesocycle falls back to the next FUTURE mesocycle; the helper must not
        # render an empty table for training that has not happened (§8).
        self.assertIsNone(
            mesocycle_report(MESOCYCLE, "2026-05-20", fetch_from([]))
        )

    def test_a_mesocycle_is_fetched_once_not_once_per_window(self):
        """The report asks for elapsed, the rate window and the current week — all
        sub-ranges of the mesocycle. Against the database each was its own query, and
        `progress --mesocycles` multiplied that by the number of mesocycles."""
        acts = [
            act("2026-06-03", "running", 7200, hr=[0, 7200, 0, 0, 0]),
            act("2026-06-10", "running", 7200, hr=[0, 7200, 0, 0, 0]),
            act("2026-06-16", "running", 7200, hr=[0, 7200, 0, 0, 0]),
        ]
        calls = []

        def counting_fetch(start, end):
            calls.append((start, end))
            return [a for a in acts if start <= a["date"] <= end]

        text = mesocycle_report(
            MESOCYCLE, "2026-06-17", counting_fetch, current_week=True
        )
        self.assertIsNotNone(text)
        self.assertEqual(len(calls), 1, calls)

        # Same numbers as the uncached path, so this is caching and not a shortcut.
        self.assertEqual(
            text, mesocycle_report(
                MESOCYCLE, "2026-06-17", fetch_from(acts), current_week=True
            )
        )

    def test_a_window_outside_the_mesocycle_still_reaches_the_fetcher(self):
        """The previous mesocycle sits before this one's span, so it cannot be served from
        the cached rows."""
        acts = [act("2026-06-03", "running", 7200, hr=[0, 7200, 0, 0, 0])]
        calls = []

        def counting_fetch(start, end):
            calls.append((start, end))
            return [a for a in acts if start <= a["date"] <= end]

        mesocycle_report(
            MESOCYCLE, "2026-06-29", counting_fetch,
            previous={"name": "Prep", "start_date": "2026-05-01",
                      "end_date": "2026-05-28"},
        )
        self.assertTrue(any(start < MESOCYCLE["start_date"] for start, _ in calls), calls)

    def test_rate_divides_by_completed_weeks_only(self):
        # 4h of Z2 inside the first two complete weeks, plus 2h in the partial tail that
        # must not enter the numerator: the rate is 2h/wk, not 3h/wk.
        acts = [
            act("2026-06-03", "running", 7200, hr=[0, 7200, 0, 0, 0]),
            act("2026-06-10", "running", 7200, hr=[0, 7200, 0, 0, 0]),
            act("2026-06-16", "running", 7200, hr=[0, 7200, 0, 0, 0]),
        ]
        text = mesocycle_report(MESOCYCLE, "2026-06-17", fetch_from(acts))
        self.assertIn("Z2 aerobic 2h00", text)


class TestCurrentWeek(unittest.TestCase):
    """§9.3: raw minutes with the elapsed fraction, never extrapolated."""

    def test_current_week_is_raw_and_states_the_elapsed_fraction(self):
        acts = [
            act("2026-06-02", "running", 3600, hr=[0, 2400, 1200, 0, 0]),
            act("2026-06-16", "running", 1800, hr=[0, 600, 1200, 0, 0]),
        ]
        text = mesocycle_report(
            MESOCYCLE, "2026-06-16", fetch_from(acts), current_week=True
        )
        self.assertIn("day 2 of 7 (29% elapsed)", flat(text))
        self.assertIn("NOT extrapolated", flat(text))
        # The week's own line is raw minutes — no percentages, nothing scaled up.
        week_line = [
            l for l in text.split("\n")
            if "Z3 tempo 20m" in l and "%" not in l
        ]
        self.assertTrue(week_line, text)

    def test_too_young_mesocycle_does_not_print_the_week_twice(self):
        # With no completed week the raw table IS the current week — same window, same
        # numbers.
        acts = [act("2026-06-02", "running", 3600, hr=[0, 3600, 0, 0, 0])]
        text = mesocycle_report(
            MESOCYCLE, "2026-06-04", fetch_from(acts), current_week=True
        )
        self.assertIn("RAW minutes", text)
        self.assertNotIn("Current week so far", text)

    def test_current_week_window_tracks_the_mesocycle_grid(self):
        self.assertEqual(
            current_week_window("2026-06-01", "2026-06-28", "2026-06-16"),
            ("2026-06-15", "2026-06-16", 2),
        )


class TestDelta(unittest.TestCase):
    """§4.1: mesocycle-over-mesocycle change, suppressed per sport rather than globally."""

    PREV = {
        "name": "Base 1", "focus": "aerobic base",
        "start_date": "2026-05-04", "end_date": "2026-05-31",
    }

    def _report(self, acts):
        return mesocycle_report(
            MESOCYCLE, "2026-06-29", fetch_from(acts), previous=self.PREV
        )

    def test_intensity_creep_shows_as_z2_down_and_z3_up(self):
        # The failure mode the feature exists for: same weekly load, easy volume traded
        # for tempo. Both mesocycles are 4 weeks, so per-week rates compare directly.
        acts = []
        for week in range(4):
            acts.append(act(f"2026-05-{4 + week * 7:02d}", "running", 20700,
                            hr=[3000, 18000, 2100, 900, 300]))
            acts.append(act(f"2026-06-{1 + week * 7:02d}", "running", 20700,
                            hr=[3300, 13140, 4800, 1080, 420]))
        text = self._report(acts)
        self.assertIn("Change vs Base 1", text)
        delta = "\n".join(
            text.split("Change vs Base 1")[1].split("Structural work")[0].split("\n")
        )
        self.assertIn("Z2 aerobic -1h21 (-27%)", delta)
        self.assertIn("Z3 tempo +45m (+129%)", delta)

    def test_a_sport_absent_before_is_reported_absent_not_as_a_swing(self):
        acts = [
            act("2026-05-06", "running", 3600, hr=[0, 3600, 0, 0, 0]),
            act("2026-06-03", "running", 3600, hr=[0, 3600, 0, 0, 0]),
            act("2026-06-05", "cycling", 3600, hr=[0, 3600, 0, 0, 0]),
        ]
        text = self._report(acts)
        self.assertIn("not trained in Base 1, no comparison", text)
        self.assertNotIn("-100%", text)

    def test_a_sport_dropped_since_is_reported_absent(self):
        acts = [
            act("2026-05-06", "running", 3600, hr=[0, 3600, 0, 0, 0]),
            act("2026-05-08", "cycling", 3600, hr=[0, 3600, 0, 0, 0]),
            act("2026-06-03", "running", 3600, hr=[0, 3600, 0, 0, 0]),
        ]
        text = self._report(acts)
        self.assertIn("present in Base 1, not trained here", text)

    def test_no_delta_when_the_current_mesocycle_has_no_completed_week(self):
        acts = [act("2026-05-06", "running", 3600, hr=[0, 3600, 0, 0, 0])]
        text = mesocycle_report(
            MESOCYCLE, "2026-06-04", fetch_from(acts + [
                act("2026-06-02", "running", 3600, hr=[0, 3600, 0, 0, 0])
            ]), previous=self.PREV
        )
        self.assertNotIn("Change vs", text)


class TestStructural(unittest.TestCase):
    """§6: no sport is routed away — the structural row sits beside the zone rows."""

    def test_hiit_strength_keeps_its_hard_minutes_in_the_zone_table(self):
        # Garmin files a HIIT kettlebell activity as `indoor_cardio`, which folds into
        # strength_training. Routing it away would report ZERO hard minutes for a mesocycle
        # containing four of them.
        acts = [
            act("2026-06-02", "indoor_cardio", 3600, hr=[300, 1200, 900, 1100, 100],
                rpe=8),
        ]
        text = mesocycle_report(MESOCYCLE, "2026-06-09", fetch_from(acts))
        self.assertIn("strength_training", text)
        self.assertIn("Z4 threshold 18m", text)
        self.assertIn("avg RPE 8.0", text)

    def test_benchmark_movement_inside_the_window_is_reported(self):
        acts = [act("2026-06-02", "cycling", 3600, hr=[0, 3600, 0, 0, 0], rpe=5)]
        benchmarks = [
            {"anchor_kind": "ftp", "date": "2026-04-01", "value": 240.0, "id": 1},
            {"anchor_kind": "ftp", "date": "2026-06-10", "value": 252.0, "id": 2},
        ]
        text = mesocycle_report(
            MESOCYCLE, "2026-06-20", fetch_from(acts), benchmarks=benchmarks
        )
        self.assertIn("240 W -> 252 W (+5.0%)", text)

    def test_volume_and_load_line_survives_the_zone_table(self):
        acts = [act("2026-06-02", "running", 3600, hr=[0, 3600, 0, 0, 0])]
        text = mesocycle_report(MESOCYCLE, "2026-06-09", fetch_from(acts))
        self.assertIn("Volume and load", text)
        self.assertIn("1 activity, 1h00", text)

    def test_mesocycle_with_no_activities_says_so_once(self):
        text = mesocycle_report(MESOCYCLE, "2026-06-09", fetch_from([]))
        self.assertIn("No completed activities recorded", text)
        self.assertNotIn("Coverage:", text)


class TestMeasuredWindow(unittest.TestCase):
    """§4: the window the zone table divides, shared so a caller asking "will this table
    have rows?" asks about the same window the table is built from."""

    def test_whole_weeks_where_a_rate_window_exists(self):
        self.assertEqual(
            measured_window("2026-06-01", "2026-06-28", "2026-06-17"),
            ("2026-06-01", "2026-06-14", 2),
        )

    def test_falls_back_to_the_raw_elapsed_span_with_no_divisor(self):
        # Six days in: too young for a per-week rate, so weeks is 0 and the span is raw.
        self.assertEqual(
            measured_window("2026-06-01", "2026-06-28", "2026-06-06"),
            ("2026-06-01", "2026-06-06", 0),
        )

    def test_never_runs_past_the_mesocycle(self):
        _, end, _ = measured_window("2026-06-01", "2026-06-28", "2026-09-01")
        self.assertLessEqual(end, "2026-06-28")


class TestPrescribedTable(unittest.TestCase):
    """§9.2a: what the plan asked, beside what the athlete produced — the pair that tells a
    mis-designed mesocycle from a mis-executed one."""

    ACTS = [
        act("2026-06-02", "running", 3600, hr=[0, 1200, 2400, 0, 0]),
        act("2026-06-09", "running", 3600, hr=[0, 1200, 2400, 0, 0]),
    ]
    PLAN = [
        planned("2026-06-02", "running", "hr", [0, 3000, 600, 0, 0]),
        planned("2026-06-09", "running", "hr", [0, 3000, 600, 0, 0]),
    ]

    def test_absent_unless_asked_for(self):
        """Only the periodization consumer passes `fetch_workouts`; adapt must not grow
        this table, since measured-vs-prescribed divergence is an execution question."""
        text = mesocycle_report(MESOCYCLE, "2026-06-17", fetch_from(self.ACTS))
        self.assertNotIn("PRESCRIBED", text)

    def test_rendered_in_the_same_units_as_the_measured_table(self):
        text = mesocycle_report(
            MESOCYCLE, "2026-06-17", fetch_from(self.ACTS),
            fetch_workouts=fetch_from(self.PLAN),
        )
        self.assertIn("What the plan PRESCRIBED over the same weeks, per week", flat(text))
        # Measured 40m of Z3 per week against 10m prescribed — the divergence is legible
        # because both tables are the same renderer at the same divisor.
        self.assertIn("Z3 tempo 40m", flat(text))
        self.assertIn("Z3 tempo 10m", flat(text))

    def test_silent_when_no_session_carries_a_target(self):
        """Sessions predating §9.8, or a sport with no zone model: an empty table would
        read as "the plan asked for nothing"."""
        bare = [{"date": "2026-06-02", "sport_type": "running"}]
        text = mesocycle_report(
            MESOCYCLE, "2026-06-17", fetch_from(self.ACTS), fetch_workouts=fetch_from(bare),
        )
        self.assertNotIn("PRESCRIBED", text)

    def test_it_divides_the_same_window_the_measured_table_does(self):
        """A prescription and a recording must divide the same weeks to be comparable, so
        a session in the excluded partial tail must not inflate the prescribed rate."""
        tail = self.PLAN + [planned("2026-06-16", "running", "hr", [0, 0, 3600, 0, 0])]
        text = mesocycle_report(
            MESOCYCLE, "2026-06-17", fetch_from(self.ACTS), fetch_workouts=fetch_from(tail),
        )
        # Still 1200s/2 weeks = 10m, not (1200s + 3600s)/2 = 40m.
        self.assertIn("Z3 tempo 10m", flat(text))
        self.assertNotIn("Z3 tempo 40m", flat(text).split("PRESCRIBED")[1])


class TestPromptWidthContract(unittest.TestCase):
    def test_mesocycle_report_prose_respects_the_width_it_is_given(self):
        # §9.6: `format_header` and the `Change vs` header were bare appends measuring
        # 57 and 84 characters at width=48, so the column contract was false there.
        acts = [act("2026-06-02", "running", 3600, hr=[0, 3600, 0, 0, 0]),
                act("2026-05-06", "running", 3600, hr=[0, 3000, 600, 0, 0])]
        previous = {"name": "Base 1 — Aerobic Volume Accumulation",
                    "focus": "aerobic volume accumulation across a long base",
                    "start_date": "2026-05-04", "end_date": "2026-05-31"}
        text = mesocycle_report(
            MESOCYCLE, "2026-06-16", fetch_from(acts), previous=previous,
            notes=False, indent="", width=48,
        )
        for line in text.split("\n"):
            self.assertLessEqual(len(line), 48, msg=repr(line))
        self.assertIn("Change vs", flat(text))


if __name__ == "__main__":
    unittest.main()
