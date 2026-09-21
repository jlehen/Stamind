"""The training behind the athlete, as `plan generate` is told about it: the
planned-versus-actual review, how each threshold was obtained, the seasons
already finished, the coach's learnings, and the warning when the cached
reconstruction is older than the evidence.
"""
import io
import os
import unittest
from datetime import datetime, timedelta, timezone
from unittest.mock import patch

from tests.helpers import clear_all_tables, pin_clock, rebind_test_db, save_workout
from tests import test_db_path

TEST_DB_PATH = test_db_path("test_periodization_review.db")


def _days_out(n: int) -> str:
    return (datetime.now(timezone.utc).date() + timedelta(days=n)).isoformat()


# Fixtures ride on today rather than on fixed dates; test_periodization.py says why.
GOAL_DATE = _days_out(71)

from trainmate.db import Database

test_db = Database(db_path=TEST_DB_PATH)
rebind_test_db(test_db)

from trainmate.coach.service import coach_service


class TestPriorTrainingReview(unittest.TestCase):
    """The review is built for the prompt, not for the caller: it is withheld
    unless asked for, and its display copy is built only when it is shown."""

    @classmethod
    def setUpClass(cls):
        if os.path.exists(TEST_DB_PATH):
            os.remove(TEST_DB_PATH)
        global test_db
        test_db = Database(db_path=TEST_DB_PATH)
        rebind_test_db(test_db)

    @classmethod
    def tearDownClass(cls):
        if os.path.exists(TEST_DB_PATH):
            try:
                os.remove(TEST_DB_PATH)
            except OSError:
                pass

    def setUp(self):
        clear_all_tables(test_db)

    def _prior_training_fixture(self, mock_client) -> int:
        """A goal whose plan has one elapsed mesocycle with a session trained inside it —
        the least that gives `_build_prior_training_context` something to say. Returns
        the goal's ID."""
        obj_id = test_db.add_objective(
            title="Zurich Marathon", target_date=GOAL_DATE,
            sport_type="running",
        )
        test_db.save_macrocycle(
            objective_id=obj_id, strategy="Old strategy",
            goals_hash="g", constraints_hash="l",
            mesocycles=[{
                "name": "Base Building", "start_date": "2026-06-01",
                "end_date": "2026-06-28", "focus": "Aerobic conditioning",
            }],
        )
        # A completed session inside that elapsed mesocycle.
        test_db.save_completed_activity(
            activity_id="a1", date="2026-06-01", start_time="08:00:00",
            activity_name="Base Run", activity_type="running",
            duration_sec=3600.0, distance_km=10.0, elevation_gain_m=50.0,
            avg_hr=140, max_hr=160, rpe=5, tss=60.0,
            zone1_sec=300, zone2_sec=2700, zone3_sec=400, zone4_sec=200, zone5_sec=0,
        )
        mock_client.complete.return_value = {
            "strategy": "New strategy", "mesocycles": [{
                "name": "Build", "start_date": "2026-06-08",
                "end_date": "2026-10-15", "focus": "Threshold",
            }],
        }
        return obj_id

    @patch("trainmate.coach.engine.openrouter_client")
    def test_plan_generate_injects_planned_vs_actual(self, mock_client):
        # Option A (DESIGN_backward_evaluation.md §6): the prior plan's elapsed mesocycles are
        # compared against what was actually completed, and fed into the strategy prompt.
        obj_id = self._prior_training_fixture(mock_client)
        coach_service.plan_generate(force=True, objective_id=obj_id)
        system_prompt = mock_client.complete.call_args[0][0]
        self.assertIn("## PRIOR TRAINING REVIEW", system_prompt)
        self.assertIn("PLANNED vs ACTUAL", system_prompt)
        self.assertIn("Aerobic conditioning", system_prompt)
        self.assertIn("1 activity", system_prompt)
        # The review now carries the per-sport, per-zone distribution as a per-week rate
        # over completed weeks, not a Z1-2/Z3/Z4-5 rollup
        # (DESIGN_intensity_distribution.md §5/§9).
        self.assertIn("Intensity distribution, per week over 4 completed weeks",
                      " ".join(system_prompt.split()))
        self.assertIn("Z2 aerobic", system_prompt)
        self.assertNotIn("HR zones Z1-2/Z3/Z4-5", system_prompt)

    @patch("trainmate.coach.engine.openrouter_client")
    def test_plan_generate_sees_how_each_threshold_was_obtained(self, mock_client):
        """A recorded test reaches the strategy prompt as a test, with the athlete's note.
        Given only the profile's bare value, the model called a 20-min test "modelled"
        (DESIGN_benchmark_workouts.md Rev. 5)."""
        pin_clock(self, "2026-09-18")
        test_db.add_objective(
            title="Alpe du Zwift", target_date="2026-12-22", sport_type="cycling",
        )
        test_db.add_benchmark_result(
            date="2026-09-05", sport_type="cycling", anchor_kind="ftp", value=235.0,
            unit="W", source="test", note="Zwift 20 min FTP test",
        )
        mock_client.complete.return_value = {"strategy": "s", "mesocycles": []}

        coach_service.plan_generate(force=True)

        prompt = mock_client.complete.call_args_list[0][0][0]
        section = prompt.split("## ANCHORS ON RECORD", 1)[1]
        self.assertIn("235 W — recorded 2026-09-05 (test); last tested 2026-09-05", section)
        self.assertIn("athlete's note: \"Zwift 20 min FTP test\"", section)
        self.assertLess(
            prompt.index("## ATHLETE PROFILE & PREFERENCES"),
            prompt.index("## ANCHORS ON RECORD"),
        )

    @patch("trainmate.coach.engine.openrouter_client")
    def test_the_review_is_withheld_from_the_caller_by_default(self, mock_client):
        # It is the longest thing this command can print, and it would land above the
        # strategy the athlete actually asked for (DESIGN_output_verbosity.md §7). What
        # the model is shown does not change — only what the caller is handed.
        obj_id = self._prior_training_fixture(mock_client)
        proposal = coach_service.plan_generate(force=True, objective_id=obj_id)
        self.assertIsNone(proposal["prior_training_review"])
        # But the caller is told one exists, so it can name the flag that reveals it.
        self.assertTrue(proposal["has_prior_training"])
        self.assertIn("## PRIOR TRAINING REVIEW", mock_client.complete.call_args[0][0])

    @patch("trainmate.coach.engine.openrouter_client")
    def test_show_context_hands_the_review_back(self, mock_client):
        obj_id = self._prior_training_fixture(mock_client)
        proposal = coach_service.plan_generate(
            force=True, objective_id=obj_id, show_context=True
        )
        self.assertIn("PLANNED vs ACTUAL", proposal["prior_training_review"])

    @patch("trainmate.coach.engine.openrouter_client")
    def test_the_display_copy_is_built_only_when_it_is_shown(self, mock_client):
        # Showing it costs a second full pass over the same plans, re-laid-out at the
        # terminal's width. Off the flag that pass buys nothing (§7).
        obj_id = self._prior_training_fixture(mock_client)
        # auto_apply=False on both, as the CLI does: saving between the two runs would
        # change what the second one has to review.
        with patch.object(
            coach_service, "_build_prior_training_context",
            wraps=coach_service._build_prior_training_context,
        ) as spy, patch("sys.stdout", new_callable=io.StringIO):
            coach_service.plan_generate(
                force=True, objective_id=obj_id, auto_apply=False
            )
            self.assertEqual(spy.call_count, 1)
            spy.reset_mock()
            coach_service.plan_generate(
                force=True, objective_id=obj_id, auto_apply=False, show_context=True
            )
            self.assertEqual(spy.call_count, 2)


class TestCompletedSeasonsReachTheReview(unittest.TestCase):
    """A goal whose date has passed keeps contributing its plan to the prior-training
    review. It used to be marked `completed` by hand — the one action that both unblocked
    planning and hid the season from it (DESIGN_backward_evaluation.md §12)."""

    TODAY = "2026-08-05"

    @classmethod
    def setUpClass(cls):
        if os.path.exists(TEST_DB_PATH):
            os.remove(TEST_DB_PATH)
        global test_db
        test_db = Database(db_path=TEST_DB_PATH)
        rebind_test_db(test_db)

    @classmethod
    def tearDownClass(cls):
        if os.path.exists(TEST_DB_PATH):
            try:
                os.remove(TEST_DB_PATH)
            except OSError:
                pass

    def setUp(self):
        clear_all_tables(test_db)
        pin_clock(self, self.TODAY)

    def _last_season(self) -> None:
        """A goal raced on 2026-07-04, its plan, and the training that went into it."""
        obj_id = test_db.add_objective(
            title="Spring Hill Climb", target_date="2026-07-04",
            sport_type="cycling",
        )
        macro_id = test_db.save_macrocycle(
            objective_id=obj_id, strategy="Spring build", goals_hash="g",
            constraints_hash="c",
            mesocycles=[{"name": "Spring Base", "start_date": "2026-06-08",
                         "end_date": "2026-07-04", "focus": "aerobic volume"}],
        )
        for i, day in enumerate(("2026-06-09", "2026-06-16")):
            save_workout(test_db,
                date=day, sport_type="cycling", title="Endurance",
                description="[Endurance]\n2h", duration_minutes=120, rpe=5, tss=100.0,
                macrocycle_id=macro_id,
            )
            test_db.save_completed_activity(
                activity_id=f"s{i}", date=day, start_time=f"{day}T07:00:00",
                activity_name="Ride", activity_type="cycling", duration_sec=3600,
                distance_km=30.0, elevation_gain_m=200.0, avg_hr=140, max_hr=170,
                rpe=5, tss=100.0, zone1_sec=600, zone2_sec=3000,
            )

    @patch("trainmate.runtime.calendar_syncer")
    @patch("trainmate.coach.engine.openrouter_client")
    def test_last_seasons_mesocycles_are_in_the_next_plans_prompt(
        self, mock_client, mock_calendar
    ):
        self._last_season()
        test_db.add_objective(
            title="Autumn Gran Fondo", target_date="2026-10-15",
            sport_type="cycling",
        )
        mock_client.complete.return_value = {
            "strategy": "Autumn build", "mesocycles": [
                {"name": "Base", "start_date": "2026-08-05", "end_date": "2026-09-01",
                 "focus": "volume"},
            ],
        }

        proposal = coach_service.plan_generate(force=True)

        self.assertEqual(proposal["goal"]["title"], "Autumn Gran Fondo")
        prompt = mock_client.complete.call_args_list[0][0][0]
        self.assertIn("Spring Base", prompt)
        self.assertIn('focus "aerobic volume"', prompt)
        self.assertIn("Weekly load", prompt)

    @patch("trainmate.runtime.calendar_syncer")
    @patch("trainmate.coach.engine.openrouter_client")
    def test_an_archived_season_stays_out(self, mock_client, mock_calendar):
        """`archived` is the athlete saying it did not happen — the one thing the date
        cannot know, and the only reason the column still exists."""
        self._last_season()
        test_db.update_objective(1, status="archived")
        test_db.add_objective(
            title="Autumn Gran Fondo", target_date="2026-10-15",
            sport_type="cycling",
        )
        mock_client.complete.return_value = {
            "strategy": "Autumn build", "mesocycles": [
                {"name": "Base", "start_date": "2026-08-05", "end_date": "2026-09-01",
                 "focus": "volume"},
            ],
        }

        coach_service.plan_generate(force=True)

        self.assertNotIn("Spring Base", mock_client.complete.call_args_list[0][0][0])


class TestLearningsReachTheStrategyPrompt(unittest.TestCase):
    """`plan generate` builds its own system prompt rather than calling
    `_build_system_prompt`, and so was the one coach call that never saw the observations
    the analysis flow authors (DESIGN_backward_evaluation.md §10.1)."""

    @classmethod
    def setUpClass(cls):
        if os.path.exists(TEST_DB_PATH):
            os.remove(TEST_DB_PATH)
        global test_db
        test_db = Database(db_path=TEST_DB_PATH)
        rebind_test_db(test_db)

    @classmethod
    def tearDownClass(cls):
        if os.path.exists(TEST_DB_PATH):
            try:
                os.remove(TEST_DB_PATH)
            except OSError:
                pass

    def setUp(self):
        clear_all_tables(test_db)

    @staticmethod
    def _strategy_prompt(mock_client) -> str:
        """The system prompt of the plan call — the first of the two `replan` makes."""
        return mock_client.complete.call_args_list[0][0][0]

    @patch("trainmate.runtime.calendar_syncer")
    @patch("trainmate.coach.engine.openrouter_client")
    def _generate(self, learning, mock_client, mock_calendar):
        # The whole clock, not one alias: pinning only `service._today_str` left the goal
        # date below to be judged against the real one, so these expired on 2026-09-27.
        pin_clock(self, "2026-06-01")
        test_db.add_objective(
            title="Berlin Marathon", target_date="2026-09-27", sport_type="running",
        )
        if learning:
            test_db.add_learning(**learning)
        mock_client.complete.return_value = {
            "strategy": "Simulated", "mesocycles": [
                {"name": "Base", "start_date": "2026-06-01", "end_date": "2026-06-28",
                 "focus": "Endurance"},
            ],
        }
        coach_service.plan_generate(force=True)
        return self._strategy_prompt(mock_client)

    def test_active_observations_are_rendered_with_their_tags(self):
        prompt = self._generate({
            "text": "Responds poorly to back-to-back threshold days",
            "sports": "running", "confidence": "established",
        })
        self.assertIn("ATHLETE-SPECIFIC OBSERVATIONS", prompt)
        self.assertIn("Responds poorly to back-to-back threshold days", prompt)
        self.assertIn("running", prompt)
        self.assertIn("established", prompt)

    def test_the_section_says_they_are_input_only(self):
        """Authoring stays with the analysis flow; nothing here may revise them (§11)."""
        prompt = self._generate({"text": "Sleeps badly after evening intensity"})
        self.assertIn("input only", prompt)

    def test_the_cold_start_placeholder_still_reaches_the_prompt(self):
        """No learnings yet renders the 'observe over time' placeholder, not an empty
        section — same text every other coach prompt gets."""
        prompt = self._generate(None)
        self.assertIn("ATHLETE-SPECIFIC OBSERVATIONS", prompt)
        self.assertIn("No observations yet", prompt)


class TestStaleAnalysisWarning(unittest.TestCase):
    """`plan generate` feeds the cached reconstruction to the strategy prompt but never
    recomputes it, so a stale cache shapes the plan silently unless it says so (§5)."""

    @classmethod
    def setUpClass(cls):
        if os.path.exists(TEST_DB_PATH):
            os.remove(TEST_DB_PATH)
        global test_db
        test_db = Database(db_path=TEST_DB_PATH)
        rebind_test_db(test_db)

    @classmethod
    def tearDownClass(cls):
        if os.path.exists(TEST_DB_PATH):
            try:
                os.remove(TEST_DB_PATH)
            except OSError:
                pass

    def setUp(self):
        clear_all_tables(test_db)

    def _cache_ending(
        self, window_end: str, horizon: str = "long", window_start: str = "2026-01-01"
    ) -> None:
        # A reflect row must start past bootstrap's end to be read forward at all (§10.2),
        # so its start is explicit here rather than shared with bootstrap's.
        test_db.save_analysis_cache(
            horizon=horizon, fingerprint=f"fp-{horizon}", window_start=window_start,
            window_end=window_end, reconstruction={"macrocycle_summary": "Base build."},
        )

    def _warn(self, today: str) -> str:
        with patch("builtins.print") as mock_print:
            coach_service._maybe_warn_stale_analysis(today)
        return "\n".join(str(c[0][0]) for c in mock_print.call_args_list if c[0])

    def test_warns_once_the_lag_exceeds_the_configured_budget(self):
        self._cache_ending("2026-06-01")
        out = self._warn("2026-07-01")          # 30 days > the 14-day default
        self.assertIn("2026-06-01", out)
        self.assertIn("30 days ago", out)
        self.assertIn("data reflect", out)

    def test_quiet_while_the_cache_is_current(self):
        self._cache_ending("2026-06-25")
        self.assertEqual(self._warn("2026-07-01"), "")    # 6 days, inside the budget

    def test_quiet_when_there_is_nothing_cached(self):
        """A cold start is the bootstrap nudge's job, not this one's."""
        self.assertEqual(self._warn("2026-07-01"), "")

    def test_a_current_reflection_clears_a_stale_bootstrap(self):
        """The warning names `data reflect`, so it has to be judged over a window that
        `data reflect` can actually move — otherwise it repeats forever however diligently
        the athlete runs it (§10.2)."""
        self._cache_ending("2026-01-31")                     # bootstrap, months behind
        self._cache_ending("2026-06-25", horizon="short",    # reflect, caught up
                           window_start="2026-02-01")
        self.assertEqual(self._warn("2026-07-01"), "")

    def test_a_stale_reflection_still_warns_from_the_later_window(self):
        self._cache_ending("2026-01-31")
        self._cache_ending("2026-06-01", horizon="short", window_start="2026-02-01")
        out = self._warn("2026-07-01")
        self.assertIn("2026-06-01", out)                     # the later of the two
        self.assertNotIn("2026-01-31", out)


if __name__ == "__main__":
    unittest.main()
