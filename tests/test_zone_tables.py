"""The zone tables and the caveats printed under them
(DESIGN_intensity_distribution.md §5, §9.6).

Both classes reach into the mesocycle report as well, because a table is
only ever drawn from one: the assertion is on the text, not on the report.
"""
import unittest

from trainmate.analytics import intensity, zone_tables
from trainmate.analytics.mesocycle_report import mesocycle_report


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


class TestZonesAndRendering(unittest.TestCase):
    """§5: every zone separately, named, with the percentage of RECORDED seconds."""

    def test_every_zone_is_reported_separately_and_named(self):
        acts = [act("2026-06-02", "running", 3600, hr=[600, 1800, 600, 480, 120])]
        text = mesocycle_report(MESOCYCLE, "2026-06-09", fetch_from(acts))
        for label in ("Z1 recovery", "Z2 aerobic", "Z3 tempo", "Z4 threshold",
                      "Z5 VO2max+"):
            self.assertIn(label, text)
        self.assertNotIn("Z1-2", text)
        self.assertNotIn("Z4-5", text)

    def test_power_reports_all_seven_zones(self):
        acts = [act("2026-06-02", "cycling", 3600,
                    power=[300, 1800, 600, 480, 300, 100, 20])]
        text = mesocycle_report(MESOCYCLE, "2026-06-09", fetch_from(acts))
        for label in ("Z5 VO2max", "Z6 anaerobic", "Z7 neuromuscular"):
            self.assertIn(label, text)

    def test_percentages_are_of_recorded_seconds_not_duration(self):
        # Half the hour was below Z1; the two recorded halves are still 50/50.
        rows = intensity.zone_rows(
            [act("2026-06-02", "running", 3600, hr=[0, 900, 900, 0, 0])]
        )
        cells = zone_tables._zone_cells(rows[0], divisor=1, with_pct=True)
        self.assertIn("(50%)", cells[1])
        self.assertIn("(50%)", cells[2])

    def test_hr_and_power_rows_carry_the_never_sum_warning(self):
        acts = [act("2026-06-02", "cycling", 3600, hr=[0, 3600, 0, 0, 0],
                    power=[0, 3600, 0, 0, 0, 0, 0])]
        text = mesocycle_report(MESOCYCLE, "2026-06-09", fetch_from(acts))
        self.assertIn("never a total", text)

    def test_every_line_stays_inside_the_prompt_width(self):
        acts = [
            act("2026-06-02", "cycling", 5400, hr=[600, 3600, 700, 400, 100],
                power=[500, 3200, 800, 500, 200, 80, 20], rpe=6),
            act("2026-06-04", "strength_training", 3600, hr=[300, 2000, 600, 500, 30],
                rpe=8),
            act("2026-06-06", "trail_running", 7200, hr=[600, 5400, 900, 200, 60]),
        ]
        text = mesocycle_report(
            MESOCYCLE, "2026-06-20", fetch_from(acts), current_week=True
        )
        for line in text.split("\n"):
            self.assertLessEqual(len(line), zone_tables.PROMPT_WIDTH, line)


class TestNotes(unittest.TestCase):
    """§9.6: `HR_REST_NOTE` held two claims with different scopes joined by an 'and'.
    Strength is a property of the sport and is suppressed when that sport is off screen;
    interval work with rest happens in running, cycling and rowing alike and is not."""

    def _rows(self, *acts):
        return intensity.zone_rows(list(acts))

    def test_interval_note_travels_with_any_hr_row(self):
        rows = self._rows(act("2026-06-02", "running", 3600, hr=[0, 3600, 0, 0, 0]))
        text = flat("\n".join(zone_tables.format_notes(rows)))
        self.assertIn("interval work with rest", text)
        self.assertNotIn("rest between sets", text)

    def test_strength_note_only_when_a_strength_sport_is_on_screen(self):
        rows = self._rows(
            act("2026-06-02", "strength_training", 3600, hr=[0, 1800, 1800, 0, 0])
        )
        text = flat("\n".join(zone_tables.format_notes(rows)))
        self.assertIn("rest between sets", text)
        self.assertIn("interval work with rest", text)

    def test_power_only_rows_carry_neither_hr_note(self):
        rows = self._rows(
            act("2026-06-02", "cycling", 3600, power=[0, 3600, 0, 0, 0, 0, 0])
        )
        text = flat("\n".join(zone_tables.format_notes(rows)))
        self.assertNotIn("interval work with rest", text)
        self.assertNotIn("rest between sets", text)

    def test_mesocycle_report_can_leave_the_notes_to_its_caller(self):
        acts = [act("2026-06-02", "running", 3600, hr=[0, 3600, 0, 0, 0])]
        with_notes = mesocycle_report(MESOCYCLE, "2026-06-09", fetch_from(acts))
        without = mesocycle_report(
            MESOCYCLE, "2026-06-09", fetch_from(acts), notes=False
        )
        self.assertIn("interval work with rest", flat(with_notes))
        self.assertNotIn("interval work with rest", flat(without))
        # Everything else is unchanged: only the caveats move.
        self.assertIn("Coverage:", without)


if __name__ == "__main__":
    unittest.main()
