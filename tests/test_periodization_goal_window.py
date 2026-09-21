"""Which goal a plan is for, and which days it opens and closes on
(DESIGN_cli_selectors.md, "A named goal is bounded to its own span").
"""
import io
import os
import unittest
from datetime import datetime, timedelta, timezone
from unittest.mock import patch

from tests.helpers import clear_all_tables, pin_clock, rebind_test_db
from tests import test_db_path

TEST_DB_PATH = test_db_path("test_periodization_goal_window.db")


def _days_out(n: int) -> str:
    return (datetime.now(timezone.utc).date() + timedelta(days=n)).isoformat()


# Fixtures ride on today rather than on fixed dates; test_periodization.py says why.

from trainmate.db import Database

test_db = Database(db_path=TEST_DB_PATH)
rebind_test_db(test_db)

from trainmate.coach.service import coach_service


class TestPlanGoalWindow(unittest.TestCase):
    """`-g N` bounds the plan to N's own span whether or not the goal before it
    has a plan, and a goal whose date has passed is no longer the next one."""

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

    @patch("trainmate.coach.engine.openrouter_client")
    def test_a_named_goal_bounds_the_plan_to_its_own_span(self, mock_client):
        """`plan generate -g N` opens N's plan after the goal before it, even when that
        goal has no plan of its own yet — and says so, because the reading it replaces
        swallowed those days into N's plan (DESIGN_cli_selectors.md §9)."""
        pin_clock(self, "2026-08-23")
        test_db.add_objective(
            title="Tune-up 10k", target_date="2026-09-15", sport_type="running",
        )
        obj_id = test_db.add_objective(
            title="Autumn Marathon", target_date="2026-12-06", sport_type="running",
        )
        mock_client.complete.return_value = {"strategy": "s", "mesocycles": []}

        with patch("sys.stdout", new_callable=io.StringIO) as out:
            coach_service.plan_generate(
                force=True, objective_id=obj_id, auto_apply=False,
                start_date="2026-09-16",
            )
        prompt = mock_client.complete.call_args_list[0][0][0]
        self.assertIn(
            "The first mesocycle must start on the start date (2026-09-16).", prompt
        )
        # The two readings differ here, so the run names both.
        said = " ".join(out.getvalue().split())
        self.assertIn("now plans this goal's own span", said)
        self.assertIn("2026-09-16", said)
        self.assertIn("2026-08-23", said)

        # Unbounded, the tune-up's days are still swallowed — the old reading, which
        # `-g ..N` keeps spellable.
        mock_client.complete.reset_mock()
        coach_service.plan_generate(
            force=True, objective_id=obj_id, auto_apply=False
        )
        prompt = mock_client.complete.call_args_list[0][0][0]
        self.assertIn(
            "The first mesocycle must start on the start date (2026-08-23).", prompt
        )

    @patch("trainmate.coach.engine.openrouter_client")
    def test_a_bound_the_derivation_already_agrees_with_says_nothing(self, mock_client):
        """The notice is transitional, so it stays quiet when both readings pick the same
        first day."""
        pin_clock(self, "2026-08-23")
        obj_id = test_db.add_objective(
            title="Autumn Marathon", target_date="2026-12-06", sport_type="running",
        )
        mock_client.complete.return_value = {"strategy": "s", "mesocycles": []}

        with patch("sys.stdout", new_callable=io.StringIO) as out:
            coach_service.plan_generate(
                force=True, objective_id=obj_id, auto_apply=False,
                start_date="2026-08-23",
            )
        self.assertNotIn("own span", out.getvalue())

    @patch("trainmate.coach.engine.openrouter_client")
    def test_plans_a_goal_only_weeks_away(self, mock_client):
        # No lower bound on the plan window: a near goal gets a short macrocycle rather
        # than a refusal — how to periodize three weeks is the science docs' call.
        today = datetime.now(timezone.utc).date()
        target_date_str = (today + timedelta(weeks=3)).strftime("%Y-%m-%d")
        obj_id = test_db.add_objective(
            title="Short Goal", target_date=target_date_str,
            sport_type="running",
        )
        mock_client.complete.return_value = {
            "strategy": "Sharpen and taper",
            "mesocycles": [{
                "name": "Race Prep", "start_date": today.strftime("%Y-%m-%d"),
                "end_date": target_date_str, "focus": "Freshness",
            }],
        }

        proposal = coach_service.plan_generate(force=True)
        self.assertEqual(proposal["strategy"], "Sharpen and taper")
        self.assertIsNotNone(test_db.get_macrocycle_for_objective(obj_id))

    def test_a_goal_whose_date_has_passed_is_no_longer_the_next_goal(self):
        """It used to stay "the next goal" forever, so `plan generate` refused with "no
        window to plan in" until the athlete marked it completed by hand. Completion is
        now the date's verdict (§12)."""
        pin_clock(self, "2026-07-31")
        past = test_db.add_objective(
            title="Yesterday's Race", target_date="2026-07-30",
            sport_type="running",
        )
        ahead = test_db.add_objective(
            title="Autumn Marathon", target_date="2026-10-30",
            sport_type="running",
        )

        self.assertEqual(test_db.get_active_objective()['id'], ahead)
        self.assertEqual([o['id'] for o in test_db.upcoming_objectives()], [ahead])
        # Still reachable by id — it just is not a planning target any more.
        self.assertIsNotNone(test_db.get_active_objective(past))

    def test_rejects_goal_on_or_before_plan_start(self):
        """Targeting the passed goal explicitly still gives the window error rather than a
        goal-not-found: the row is there, the window is not."""
        pin_clock(self, "2026-07-31")
        obj_id = test_db.add_objective(
            title="Yesterday's Race", target_date="2026-07-30",
            sport_type="running",
        )

        with self.assertRaises(ValueError) as ctx:
            coach_service.plan_generate(objective_id=obj_id)
        self.assertIn("no window to plan in", str(ctx.exception))

    @patch("trainmate.coach.engine.openrouter_client")
    def test_far_goal_plans_one_macrocycle_to_the_goal(self, mock_client):
        # A 30-week horizon is no longer split into interim goals: one macrocycle runs to
        # the goal itself, and the athlete's goal list is left alone.
        # The whole clock, not one alias: the goal below is dated, and a site left live
        # would read it as behind us once the real calendar passed it.
        pin_clock(self, "2026-07-31")
        obj_id = test_db.add_objective(
            title="Ultra Marathon", target_date="2027-02-26",
            sport_type="running",
        )
        mock_client.complete.return_value = {
            "strategy": "Long build",
            "mesocycles": [{
                "name": "Base Building", "start_date": "2026-07-31",
                "end_date": "2027-02-26", "focus": "Aerobic conditioning",
            }],
        }

        coach_service.plan_generate(force=True)
        prompt = mock_client.complete.call_args[0][0]
        self.assertIn("until the target\ngoal (2027-02-26)", prompt)
        self.assertNotIn("intermediate_goals", prompt)
        # No goals were invented along the way.
        self.assertEqual(len(test_db.get_objectives(status="active")), 1)
        self.assertIsNotNone(test_db.get_macrocycle_for_objective(obj_id))

    @patch("trainmate.coach.engine.openrouter_client")
    def test_multi_goal_planning_and_deletion(self, mock_client):
        # Goal A must stay inside `goals_lookback_days` of today for B's plan to chain
        # off it, so both goals ride on today rather than on fixed dates.
        goal_a, goal_b = _days_out(61), _days_out(153)
        obj1_id = test_db.add_objective(
            title="Goal A", target_date=goal_a,
            sport_type="running",
        )
        obj2_id = test_db.add_objective(
            title="Goal B", target_date=goal_b,
            sport_type="running",
        )

        mock_client.complete.side_effect = [
            {
                "strategy": "Plan A strategy",
                "mesocycles": [{
                    "name": "Base Building A", "start_date": _days_out(4),
                    "end_date": goal_a, "focus": "Aerobic conditioning",
                }],
            },
            {
                "strategy": "Plan B strategy",
                "mesocycles": [{
                    "name": "Base Building B", "start_date": _days_out(62),
                    "end_date": goal_b, "focus": "Aerobic threshold",
                }],
            },
        ]

        proposal_a = coach_service.plan_generate(force=True, objective_id=obj1_id)
        strategy_a, mesos_a = proposal_a['strategy'], proposal_a['mesocycles']
        self.assertEqual(strategy_a, "Plan A strategy")
        self.assertEqual(mesos_a[0]["start_date"], _days_out(4))

        proposal_b = coach_service.plan_generate(force=True, objective_id=obj2_id)
        strategy_b, mesos_b = proposal_b['strategy'], proposal_b['mesocycles']
        self.assertEqual(strategy_b, "Plan B strategy")
        # Plan B starts the day after Goal A, not today: it chains off the earlier goal.
        self.assertIn(f"from {_days_out(62)} until",
                      mock_client.complete.call_args_list[1][0][0])

        self.assertIsNotNone(test_db.get_macrocycle_for_objective(obj1_id))
        self.assertIsNotNone(test_db.get_macrocycle_for_objective(obj2_id))

        coach_service.plan_rm(obj1_id)
        self.assertIsNone(test_db.get_macrocycle_for_objective(obj1_id))
        self.assertIsNotNone(test_db.get_macrocycle_for_objective(obj2_id))


if __name__ == "__main__":
    unittest.main()
