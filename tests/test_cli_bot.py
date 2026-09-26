"""`bot` command family tests: the read half — morning-push idempotency, adapt_first, the
messages the bot sends unasked, the companion lists and their pickers, and the free-text
router (DESIGN_bot_simple_frontend.md §4.2, §5.3, §5.5, §11.2, §12.6). The write half,
`bot capture <intent>`, is in `test_cli_bot_capture.py`."""
import json
import os
import unittest
from datetime import datetime, timedelta, timezone
from unittest.mock import MagicMock, patch

from tests.helpers import (
    as_instance, clear_all_tables, run_cli, rebind_test_db, save_workout,
)
from tests import test_db_path

TEST_DB_PATH = test_db_path("test_stamind_cli_bot.db")

from stamind.db import Database
import stamind_cli

from stamind import clock, runtime
from stamind.cli.bot.views import MORNING_MARKER, PUSH_ALL_DONE_LINE
from stamind.cli.render.session_lines import SIMPLE_DONE_LINE
from stamind.config import config
from stamind.heads_up import CHANGE_LEAD, UNDONE_ONE, UNDONE_PLAIN, UNDONE_SEVERAL
from stamind.sentinels import BUTTONS_SENTINEL, FLUSH_SENTINEL
from stamind.clock import today_str

# One database for the whole module: the three test classes below share it and
# clear its tables per test, so its lifecycle is module-level, not per-class.
if os.path.exists(TEST_DB_PATH):
    os.remove(TEST_DB_PATH)
test_db = Database(db_path=TEST_DB_PATH)
rebind_test_db(test_db)


def tearDownModule():
    try:
        os.remove(TEST_DB_PATH)
    except OSError:
        pass


class ChangesCommandTest(unittest.TestCase):
    """`bot changes` tells the athlete about the changes made out of their sight, and a
    rollback of a change they were told about says so (DESIGN_change_heads_up.md §3, §6)."""

    def setUp(self):
        rebind_test_db(test_db)
        clear_all_tables(test_db)
        garmin = patch.object(runtime, "garmin", MagicMock(), create=True)
        garmin.start()
        self.addCleanup(garmin.stop)
        calendar = patch("stamind.runtime.calendar_syncer")
        calendar.start()
        self.addCleanup(calendar.stop)
        # A companion instance, run from the terminal: the athlete watches nothing here.
        as_instance(self, "simple")

    def _change(self, kind="generate", note="Four sessions a week now.", day=None,
                sport="cycling", title="Ride"):
        """One change that wrote one session, and its id."""
        with test_db.workout_change(kind=kind, note=note) as change:
            change.append(
                date=day or today_str(), sport_type=sport, title=title,
                description="60 min.", duration_minutes=60,
            )
            return change.id

    def _told(self, **kwargs):
        change_id = self._change(**kwargs)
        test_db.mark_changes_told([change_id])
        return change_id

    def test_each_waiting_change_goes_once_oldest_first(self):
        self._change(note="Friday's test moves to Saturday.")
        self._change(kind="adapt", note="Friday becomes a rest day.", sport="running")
        _code, out, _ = run_cli(["bot", "changes"])
        self.assertIn(f"{CHANGE_LEAD} Friday's test moves to Saturday.", out)
        self.assertIn(f"{CHANGE_LEAD} Friday becomes a rest day.", out)
        self.assertLess(out.index("moves to Saturday"), out.index("rest day"))
        _code, again, _ = run_cli(["bot", "changes"])
        self.assertEqual(again.strip(), "")

    def test_one_message_per_change_in_the_chat(self):
        self._change(note="First.")
        self._change(note="Second.", sport="running")
        with patch.dict(os.environ, {"STAMIND_FRONTEND": "json"}):
            _code, out, _ = run_cli(["bot", "changes"])
        first, second = out.split(FLUSH_SENTINEL)
        self.assertIn("First.", first)
        self.assertIn("Second.", second)
        self.assertIn('"wait": false', second)

    def test_nothing_goes_out_on_an_expert_instance(self):
        self._change()
        as_instance(self, "expert")
        _code, out, _ = run_cli(["bot", "changes"])
        self.assertEqual(out.strip(), "")

    def test_a_change_the_athlete_watched_is_never_sent(self):
        as_instance(self, "simple", from_chat=True)
        self._change()
        self.assertEqual(test_db.waiting_changes(), [])

    def test_a_change_rolled_back_before_it_was_told_is_never_sent(self):
        change_id = self._change()
        test_db.rollback_to_change(change_id, today_str(), summary="undo")
        _code, out, _ = run_cli(["bot", "changes"])
        self.assertEqual(out.strip(), "")

    def test_a_rollback_quotes_the_line_of_a_change_that_was_told(self):
        change_id = self._told(note="Friday's test moves to Saturday.")
        test_db.rollback_to_change(change_id, today_str(), summary="undo")
        _code, out, _ = run_cli(["bot", "changes"])
        self.assertIn(f"{UNDONE_ONE} Friday's test moves to Saturday.", out)
        self.assertNotIn(CHANGE_LEAD, out)

    def test_several_told_changes_are_quoted_oldest_first(self):
        first = self._told(note="Longer runs.")
        self._told(kind="adapt", note="Rest on Friday.", sport="running")
        test_db.rollback_to_change(first, today_str(), summary="undo")
        _code, out, _ = run_cli(["bot", "changes"])
        self.assertIn(UNDONE_SEVERAL, out)
        self.assertLess(out.index("Longer runs."), out.index("Rest on Friday."))

    def test_a_told_change_without_a_line_gives_the_plain_sentence(self):
        change_id = self._told(kind="tweak", note=None)
        test_db.rollback_to_change(change_id, today_str(), summary="undo")
        _code, out, _ = run_cli(["bot", "changes"])
        self.assertIn(UNDONE_PLAIN, out)

    def test_a_told_adaptation_that_changed_nothing_gives_no_message(self):
        with test_db.workout_change(kind="adapt", summary="All green.") as change:
            held = change.id
        test_db.mark_changes_told([held])
        test_db.rollback_to_change(held, today_str(), summary="undo")
        _code, out, _ = run_cli(["bot", "changes"])
        self.assertEqual(out.strip(), "")

    def test_an_overwritten_change_waits_again_once_the_overwrite_is_undone(self):
        """§6's story: attempt 5 waits, attempt 6 rewrites every day it wrote, and the
        operator then rolls attempt 6 back."""
        first = self._change(note="The first attempt.")
        second = self._change(note="The second attempt.", title="Long ride")
        self.assertEqual([c["id"] for c in test_db.waiting_changes()], [second])
        test_db.rollback_to_change(second, today_str(), summary="undo")
        self.assertEqual([c["id"] for c in test_db.waiting_changes()], [first])
        _code, out, _ = run_cli(["bot", "changes"])
        self.assertIn("The first attempt.", out)
        self.assertNotIn("The second attempt.", out)

    def test_the_morning_message_no_longer_carries_the_line(self):
        self._change(note="Four sessions a week now.")
        _code, out, _ = run_cli(["bot", "morning"])
        self.assertNotIn(CHANGE_LEAD, out)
        self.assertEqual(len(test_db.waiting_changes()), 1)


class MorningPushTest(unittest.TestCase):
    """`bot morning` — §4.1 rendering and the §4.2 settings-marker idempotency."""

    def setUp(self):
        rebind_test_db(test_db)  # an earlier module may have rebound the handles
        clear_all_tables(test_db)
        # The push grades today before it briefs it (§4.1), which freshens the cache
        # first; the activities each test wants are written to the db directly.
        garmin = patch.object(runtime, "garmin", MagicMock(), create=True)
        garmin.start()
        self.addCleanup(garmin.stop)

    def _trained(self, sport="running", duration_min=40):
        """One completed activity for today, the shape the Garmin pull would have left."""
        test_db.save_completed_activity(
            activity_id=f"a-{sport}", date=today_str(),
            start_time=f"{today_str()} 07:00:00", activity_name=f"Morning {sport}",
            activity_type=sport, duration_sec=duration_min * 60, distance_km=8.0,
            elevation_gain_m=0.0, avg_hr=140, max_hr=160, rpe=None, tss=45.0,
        )

    def test_rest_day_gets_one_line_and_no_buttons(self):
        code, out, _ = run_cli(["bot", "morning"])
        self.assertEqual(code, 0)
        self.assertIn("Rest day", out)
        self.assertNotIn(BUTTONS_SENTINEL, out)
        self.assertEqual(test_db.get_setting(MORNING_MARKER), today_str())

    def test_a_planned_rest_day_gets_no_buttons(self):
        """The week planner writes rest as a session row, graded rest_ok rather than done; "Can't
        today" would offer to move it."""
        save_workout(test_db, today_str(), "rest", "Rest day")
        code, out, _ = run_cli(["bot", "morning"])
        self.assertEqual(code, 0)
        self.assertIn("Rest day", out)
        self.assertNotIn(BUTTONS_SENTINEL, out)

    def test_session_day_renders_line_description_and_buttons(self):
        save_workout(
            test_db, today_str(), "running", "Easy run",
            description="Conversational pace, HR under 145.", duration_minutes=40,
        )
        code, out, _ = run_cli(["bot", "morning"])
        self.assertEqual(code, 0)
        self.assertIn("🏃 Today: Easy run — 40 min", out)
        self.assertIn("Conversational pace", out)
        self.assertIn(BUTTONS_SENTINEL, out)

    def test_a_day_already_trained_is_congratulated_not_briefed(self):
        save_workout(
            test_db, today_str(), "running", "Easy run",
            description="Conversational pace, HR under 145.", duration_minutes=40,
        )
        self._trained()
        code, out, _ = run_cli(["bot", "morning"])
        self.assertEqual(code, 0)
        self.assertIn(PUSH_ALL_DONE_LINE, out)
        self.assertNotIn("Easy run", out)
        self.assertNotIn("Conversational pace", out)
        self.assertNotIn(BUTTONS_SENTINEL, out)
        self.assertEqual(test_db.get_setting(MORNING_MARKER), today_str())

    def test_the_session_still_ahead_is_briefed_and_keeps_the_buttons(self):
        save_workout(test_db, today_str(), "running", "Easy run", duration_minutes=40)
        save_workout(test_db, today_str(), "strength", "Core work", duration_minutes=30)
        self._trained()
        code, out, _ = run_cli(["bot", "morning"])
        self.assertEqual(code, 0)
        self.assertNotIn(PUSH_ALL_DONE_LINE, out)
        self.assertIn(SIMPLE_DONE_LINE, out)     # the run, acknowledged
        self.assertIn("Core work", out)          # the session left, still briefed
        self.assertIn(BUTTONS_SENTINEL, out)

    def test_an_ungraded_day_falls_back_to_the_briefing(self):
        save_workout(test_db, today_str(), "running", "Easy run", duration_minutes=40)
        self._trained()
        runtime.garmin.ensure_data.side_effect = RuntimeError("Garmin down")
        with patch.dict(os.environ, {"STAMIND_FRONTEND": "json"}):
            code, out, _ = run_cli(["bot", "morning"])
        self.assertEqual(code, 0)
        self.assertIn("Easy run", out)
        self.assertNotIn("Garmin down", out)
        self.assertIn(BUTTONS_SENTINEL, out)

    def test_second_run_same_day_is_silent(self):
        save_workout(test_db, today_str(), "running", "Easy run")
        run_cli(["bot", "morning"])
        code, out, _ = run_cli(["bot", "morning"])
        self.assertEqual(code, 0)
        self.assertEqual(out.strip(), "")

    def test_force_resends_despite_the_marker(self):
        run_cli(["bot", "morning"])
        code, out, _ = run_cli(["bot", "morning", "--force"])
        self.assertEqual(code, 0)
        self.assertIn("Rest day", out)

    def test_adapt_first_off_never_touches_the_coach(self):
        coach = MagicMock()
        with patch.object(runtime, "coach_service", coach, create=True):
            run_cli(["bot", "morning"])
        coach.workout_adapt.assert_not_called()

    def _adapt_first_env(self, coach):
        return (
            patch.dict(config.data, {"telegram": {"push": {"adapt_first": True}}}),
            patch.object(runtime, "coach_service", coach, create=True),
            patch("stamind.cli.bot.views.ensure_recent_data"),
        )

    def test_adapt_first_applies_and_surfaces_the_reason(self):
        save_workout(test_db, today_str(), "running", "Easy run")
        proposal = MagicMock(
            workouts=[{"date": today_str()}], reason="Eased today — rough night.",
            strength_notice=None,
        )
        coach = MagicMock()
        coach.workout_adapt.return_value = proposal
        cfg, svc, pull = self._adapt_first_env(coach)
        with cfg, svc, pull:
            code, out, _ = run_cli(["bot", "morning"])
        self.assertEqual(code, 0)
        coach.workout_revision_apply.assert_called_once_with(proposal)
        self.assertIn("Eased today", out)

    def test_adapt_first_no_change_records_and_adds_no_reason(self):
        proposal = MagicMock(workouts=[], reason="All green.", strength_notice=None)
        coach = MagicMock()
        coach.workout_adapt.return_value = proposal
        cfg, svc, pull = self._adapt_first_env(coach)
        with cfg, svc, pull:
            code, out, _ = run_cli(["bot", "morning"])
        self.assertEqual(code, 0)
        coach.workout_revision_record_no_change.assert_called_once_with(proposal)
        coach.workout_revision_apply.assert_not_called()
        self.assertNotIn("All green.", out)

    def test_adapt_failure_does_not_sink_the_push(self):
        save_workout(test_db, today_str(), "running", "Easy run")
        coach = MagicMock()
        coach.workout_adapt.side_effect = RuntimeError("LLM down")
        cfg, svc, pull = self._adapt_first_env(coach)
        # The failure surfaces only as a terminal aside; under the bot's json
        # frontend (asides off) it must never reach the athlete's chat.
        with cfg, svc, pull, patch.dict(os.environ, {"STAMIND_FRONTEND": "json"}):
            code, out, _ = run_cli(["bot", "morning"])
        self.assertEqual(code, 0)
        self.assertIn("Easy run", out)
        self.assertNotIn("LLM down", out)
        self.assertEqual(test_db.get_setting(MORNING_MARKER), today_str())

    # --- §4.2: the push does not run an adaptation that already ran this morning ---

    def _adapted(self, sleep_seen, created_at=None):
        """An adapt row as the dawn run leaves it; `created_at` (UTC ISO) backdates it."""
        with test_db.workout_change(kind="adapt", summary="held", sleep_seen=sleep_seen):
            pass
        if created_at is None:
            return
        with test_db.transaction() as conn:
            conn.execute("UPDATE workout_changes SET created_at = ?", (created_at,))

    def _adapt_first_run(self, coach):
        coach.workout_adapt.return_value = MagicMock(
            workouts=[], reason="All green.", strength_notice=None,
        )
        cfg, svc, pull = self._adapt_first_env(coach)
        with cfg, svc, pull as pulled:
            code, out, _ = run_cli(["bot", "morning"])
        self.assertEqual(code, 0)
        return out, pulled

    def test_adapt_first_skips_a_run_that_already_saw_the_night(self):
        """The dawn run read last night's sleep score, so the push spends neither a second
        LLM call nor a Garmin pull on the same morning."""
        self._adapted(sleep_seen=True)
        coach = MagicMock()
        out, pull = self._adapt_first_run(coach)
        coach.workout_adapt.assert_not_called()
        pull.assert_not_called()
        self.assertIn("Rest day", out)

    def test_adapt_first_runs_again_after_a_run_that_missed_the_night(self):
        self._adapted(sleep_seen=False)
        coach = MagicMock()
        self._adapt_first_run(coach)
        coach.workout_adapt.assert_called_once()

    def test_adapt_first_runs_again_after_a_session_trained_since(self):
        self._adapted(sleep_seen=True)
        later = (clock.now() + timedelta(hours=1)).strftime("%Y-%m-%d %H:%M:%S")
        test_db.save_completed_activity(
            activity_id="a-ride", date=today_str(), start_time=later, activity_name="Ride",
            activity_type="cycling", duration_sec=3600, distance_km=30.0,
            elevation_gain_m=0.0, avg_hr=140, max_hr=160, rpe=None, tss=60.0,
        )
        coach = MagicMock()
        self._adapt_first_run(coach)
        coach.workout_adapt.assert_called_once()

    def test_adapt_first_ignores_yesterdays_run(self):
        yesterday = (datetime.now(timezone.utc) - timedelta(days=1)).isoformat()
        self._adapted(sleep_seen=True, created_at=yesterday)
        coach = MagicMock()
        self._adapt_first_run(coach)
        coach.workout_adapt.assert_called_once()

    def test_adapt_first_pulls_past_the_throttle_while_the_night_is_missing(self):
        """A pull that found no sleep score yet leaves a row the refresh throttle would
        keep, so the push forces the next one."""
        coach = MagicMock()
        _, pull = self._adapt_first_run(coach)
        pull.assert_called_once_with(today_str(), force_pull=True)

    def test_adapt_first_pulls_normally_once_the_night_is_in(self):
        test_db.save_metric_cache(today_str(), 50, 60, 80, 20, None, None, None)
        coach = MagicMock()
        _, pull = self._adapt_first_run(coach)
        pull.assert_called_once_with(today_str(), force_pull=False)


class RouteCommandTest(unittest.TestCase):
    """`bot route` — §5.3/§5.4: intent validation, graceful degradation, and the
    router-model role."""

    def setUp(self):
        rebind_test_db(test_db)  # an earlier module may have rebound the handles
        from stamind.openrouter import openrouter_client
        clear_all_tables(test_db)
        openrouter_client.reset_model()
        self.addCleanup(openrouter_client.reset_model)

    def _intent(self, out):
        return json.loads(out.strip().splitlines()[-1])["intent"]

    def test_valid_intent_passes_through(self):
        with patch(
            "stamind.openrouter.OpenRouterClient.complete",
            return_value={"intent": "show_week"},
        ):
            code, out, _ = run_cli(["bot", "route", "what's on this week?"])
        self.assertEqual(code, 0)
        self.assertEqual(self._intent(out), "show_week")

    def test_unknown_intent_degrades_to_unclear(self):
        with patch(
            "stamind.openrouter.OpenRouterClient.complete",
            return_value={"intent": "rm -rf"},
        ):
            _, out, _ = run_cli(["bot", "route", "hello"])
        self.assertEqual(self._intent(out), "unclear")

    def test_llm_failure_degrades_to_unclear(self):
        with patch(
            "stamind.openrouter.OpenRouterClient.complete",
            side_effect=ValueError("no api key"),
        ):
            code, out, _ = run_cli(["bot", "route", "hello"])
        self.assertEqual(code, 0)
        self.assertEqual(self._intent(out), "unclear")

    def test_the_router_reads_goal_and_rule_titles_beside_the_message(self):
        from datetime import date, timedelta
        soon = (date.fromisoformat(today_str()) + timedelta(days=4)).isoformat()
        test_db.add_objective(
            title="Spring 10k", target_date=soon, sport_type="running", status="active",
        )
        test_db.add_constraint(
            title="Klausenpass", start_date=soon, end_date=soon,
            description="Riding both passes in a day",
        )
        with patch(
            "stamind.openrouter.OpenRouterClient.complete",
            return_value={"intent": "coach_message"},
        ) as complete:
            run_cli(["bot", "route", "the Klausen ride got bigger"])
        system, user = complete.call_args.args[:2]
        # Titles and dates ride with the message; the system prompt stays static, and
        # ids and descriptions stay the capture call's business (§5.3).
        self.assertIn('"Spring 10k" on ' + soon, user)
        self.assertIn('"Klausenpass" from ' + soon, user)
        self.assertNotIn("Riding both passes", user)
        self.assertNotIn("Klausenpass", system)
        self.assertTrue(user.rstrip().endswith("the Klausen ride got bigger"))

    def test_an_empty_database_still_routes(self):
        with patch(
            "stamind.openrouter.OpenRouterClient.complete",
            return_value={"intent": "show_week"},
        ) as complete:
            _, out, _ = run_cli(["bot", "route", "what's on?"])
        self.assertEqual(self._intent(out), "show_week")
        self.assertIn("(none)", complete.call_args.args[1])

    def test_router_model_role_pins_the_client(self):
        from stamind.openrouter import openrouter_client
        # The router picks from the same menu the coach model does — one allowlist
        # (DESIGN_settings.md §4), so the cheap model is listed under `llm.models` too.
        with patch.dict(
            config.data,
            {"llm": {"models": ["main/model", "cheap/model"],
                     "router_model": "cheap/model"}},
        ), patch(
            "stamind.openrouter.OpenRouterClient.complete",
            return_value={"intent": "help"},
        ):
            run_cli(["bot", "route", "hello"])
            self.assertEqual(openrouter_client.model, "cheap/model")

    def test_an_off_menu_role_is_ignored_and_the_coach_model_routes(self):
        from stamind.openrouter import openrouter_client
        with patch.dict(
            config.data,
            {"llm": {"models": ["main/model"], "router_model": "cheap/model"}},
        ), patch(
            "stamind.openrouter.OpenRouterClient.complete",
            return_value={"intent": "help"},
        ):
            run_cli(["bot", "route", "hello"])
            self.assertEqual(openrouter_client.model, "main/model")

    def test_absent_role_leaves_the_active_model(self):
        from stamind.openrouter import openrouter_client
        with patch.dict(
            config.data, {"llm": {"models": ["main/model"]}}
        ), patch(
            "stamind.openrouter.OpenRouterClient.complete",
            return_value={"intent": "help"},
        ):
            run_cli(["bot", "route", "hello"])
            self.assertEqual(openrouter_client.model, "main/model")


class ConstraintsViewTest(unittest.TestCase):
    """`bot constraints` — §5.5: the companion list plus the remove picker, whose
    leaves stay pinned to single-ID `constraint rm` (the §7 guardrail's one
    routable-by-tap mutation)."""

    def setUp(self):
        rebind_test_db(test_db)  # an earlier module may have rebound the handles
        clear_all_tables(test_db)

    def _add(self, title, start=None, end=None, rest=0):
        start = start or today_str()
        return test_db.add_constraint(
            title=title, start_date=start, end_date=end or start,
            rest=rest, description=None, replan=0, source="manual",
        )

    def test_empty_list_is_a_clean_slate_without_buttons(self):
        code, out, _ = run_cli(["bot", "constraints"])
        self.assertEqual(code, 0)
        self.assertIn("Nothing on the list", out)
        self.assertNotIn(BUTTONS_SENTINEL, out)

    def test_lists_titles_and_offers_the_picker(self):
        cid = self._add("no run Thursday")
        code, out, _ = run_cli(["bot", "constraints"])
        self.assertEqual(code, 0)
        self.assertIn("no run Thursday", out)
        self.assertIn(BUTTONS_SENTINEL, out)
        self.assertIn(f"constraint rm {cid}", out)

    def test_past_constraints_stay_out_of_the_view(self):
        self._add("old rule", start="2020-01-01", end="2020-01-02")
        _, out, _ = run_cli(["bot", "constraints"])
        self.assertNotIn("old rule", out)
        self.assertIn("Nothing on the list", out)

    def test_picker_leaves_reach_only_single_id_rm(self):
        from stamind.cli.bot.views import constraint_rm_buttons

        def leaves(buttons):
            for b in buttons:
                if b.get("menu"):
                    yield from leaves(b["menu"])
                else:
                    yield b

        today = today_str()
        buttons = constraint_rm_buttons([
            {"id": 7, "title": "x" * 60, "start_date": today, "end_date": today},
            {"id": 9, "title": "short", "start_date": today, "end_date": today},
        ])
        sends = [b["send"] for b in leaves(buttons) if b.get("send")]
        self.assertEqual(sends, ["constraint rm 7", "constraint rm 9"])
        # Long titles shrink to a recognisable label, never a truncated utterance.
        self.assertTrue(all(len(b["label"]) <= 32 for b in leaves(buttons)))

    def test_rm_in_simple_render_stays_companion_prose(self):
        cid = self._add("no run Thursday")
        with patch.dict(os.environ, {"STAMIND_RENDER": "simple"}):
            code, out, _ = run_cli(["constraint", "rm", str(cid)])
        self.assertEqual(code, 0)
        self.assertIn("dropped", out)
        self.assertNotIn(f"Constraint [{cid}]", out)

class GoalsViewTest(unittest.TestCase):
    """`bot goals` — §12.6: the companion list plus the call-off picker, whose leaves
    reach `goal rm <id>` and therefore archive, never purge."""

    def setUp(self):
        rebind_test_db(test_db)
        clear_all_tables(test_db)

    def _goal(self, title, days_out=30, status="active"):
        from datetime import date, timedelta
        target = (date.fromisoformat(today_str()) + timedelta(days=days_out)).isoformat()
        return test_db.add_objective(
            title=title, target_date=target, sport_type="running", status=status,
        )

    def test_empty_active_list_invites_and_offers_no_picker(self):
        code, out, _ = run_cli(["bot", "goals"])
        self.assertEqual(code, 0)
        self.assertIn("No goal on the horizon", out)
        self.assertNotIn(BUTTONS_SENTINEL, out)

    def test_lists_goals_and_offers_the_call_off_picker(self):
        gid = self._goal("Zurich Marathon")
        code, out, _ = run_cli(["bot", "goals"])
        self.assertEqual(code, 0)
        self.assertIn("Zurich Marathon", out)
        self.assertIn(BUTTONS_SENTINEL, out)
        self.assertIn(f"goal rm {gid}", out)
        # No IDs or state tags in the prose itself (§6).
        self.assertNotIn("[UPCOMING]", out)

    def test_a_called_off_goal_is_neither_shown_nor_offered(self):
        self._goal("Old 10k", status="archived")
        _, out, _ = run_cli(["bot", "goals"])
        self.assertNotIn("Old 10k", out)
        self.assertNotIn(BUTTONS_SENTINEL, out)

    def test_picker_leaves_reach_only_the_archiving_rm(self):
        from stamind.cli.bot.views import goal_rm_buttons

        def leaves(buttons):
            for b in buttons:
                if b.get("menu"):
                    yield from leaves(b["menu"])
                else:
                    yield b

        buttons = goal_rm_buttons([{"id": 4, "title": "x" * 60}, {"id": 6, "title": "10k"}])
        sends = [b["send"] for b in leaves(buttons) if b.get("send")]
        self.assertEqual(sends, ["goal rm 4", "goal rm 6"])
        # `--purge` is unreachable from chat: the one goal mutation a tap fires is the
        # reversible call-off (§12.6).
        self.assertFalse(any("purge" in s for s in sends))

    def test_calling_a_goal_off_reads_as_prose_and_names_no_command(self):
        gid = self._goal("Spring 10k")
        with patch.dict(os.environ, {"STAMIND_RENDER": "simple"}):
            code, out, _ = run_cli(["goal", "rm", str(gid)])
        self.assertEqual(code, 0)
        self.assertIn("Spring 10k is off the list", out)
        self.assertNotIn("goal edit", out)
        self.assertNotIn("[ARCHIVED]", out)


class MesocycleViewTest(unittest.TestCase):
    """`bot mesocycle` — §11.2: one mesocycle as its stanza plus the whole focus, and a stale
    tap after a replan lands softly."""

    def setUp(self):
        rebind_test_db(test_db)
        clear_all_tables(test_db)

    def _mesocycle(self):
        """A goal 45 days out, one mesocycle from last week to the goal; returns its id."""
        from datetime import date, timedelta
        today = date.fromisoformat(today_str())
        out = lambda days: (today + timedelta(days=days)).isoformat()  # noqa: E731
        goal_id = test_db.add_objective(
            title="Zurich Marathon", target_date=out(45), sport_type="running",
        )
        test_db.save_macrocycle(
            objective_id=goal_id, strategy="Build then sharpen.",
            goals_hash="g", constraints_hash="c",
            mesocycles=[{"name": "Base", "start_date": out(-7), "end_date": out(45),
                         "focus": "Purpose: aerobic endurance, easy volume. "
                                  "Long runs grow weekly."}],
        )
        macro = test_db.get_macrocycle_for_objective(goal_id)
        return test_db.get_mesocycles_for_macrocycle(macro["id"])[0]["id"]

    def test_renders_the_stanza_and_the_whole_focus(self):
        mid = self._mesocycle()
        code, out, _ = run_cli(["bot", "mesocycle", str(mid)])
        self.assertEqual(code, 0)
        self.assertIn("📍 Base", out)
        self.assertIn("you're in week 2 of 8", out)
        self.assertIn("Long runs grow weekly.", out)  # past the first sentence
        self.assertNotIn("Mesocycle ID", out)

    def test_an_unknown_mesocycle_lands_softly(self):
        code, out, _ = run_cli(["bot", "mesocycle", "999"])
        self.assertEqual(code, 0)
        self.assertIn("isn't on your plan any more", out)


class SimpleListRenderTest(unittest.TestCase):
    """`workout list` under STAMIND_RENDER=simple: companion prose, expert form
    untouched otherwise (§6)."""

    def setUp(self):
        rebind_test_db(test_db)  # an earlier module may have rebound the handles
        clear_all_tables(test_db)
        patcher = patch.dict(os.environ, {"STAMIND_RENDER": "simple"})
        patcher.start()
        self.addCleanup(patcher.stop)

    def test_today_view_reads_as_the_day(self):
        save_workout(
            test_db, today_str(), "cycling", "Endurance ride", duration_minutes=60
        )
        _, out, _ = run_cli(["workout", "list", "-d", "today"])
        self.assertIn("🚴 Today: Endurance ride — 60 min", out)
        self.assertNotIn("WORKOUT SCHEDULE", out)

    def test_empty_today_is_a_rest_day(self):
        _, out, _ = run_cli(["workout", "list", "-d", "today"])
        self.assertIn("Rest day", out)

    def test_week_view_lists_and_counts(self):
        save_workout(test_db, today_str(), "running", "Easy run", duration_minutes=40)
        _, out, _ = run_cli(["workout", "list"])
        self.assertIn("Coming up", out)
        self.assertIn("1 session planned", out)

    def test_expert_form_is_untouched_without_the_env(self):
        os.environ.pop("STAMIND_RENDER", None)
        save_workout(test_db, today_str(), "running", "Easy run")
        _, out, _ = run_cli(["workout", "list", "-d", "today"])
        self.assertIn("WORKOUT SCHEDULE", out)


class CompanionSurfaceRoutingTest(unittest.TestCase):
    """Every companion surface, driven through the real CLI (DESIGN_render_persona.md §5).

    The line builders have their own unit tests; what these pin is the *routing* — that
    the command reaches `runtime.render` and that the renderer built for this process is
    the companion one. A wrong argument order or a stale singleton is invisible to a
    builder test and changes every one of these."""

    def setUp(self):
        rebind_test_db(test_db)
        clear_all_tables(test_db)
        patcher = patch.dict(os.environ, {"STAMIND_RENDER": "simple"})
        patcher.start()
        self.addCleanup(patcher.stop)

    def _goal_with_plan(self):
        """A goal 45 days out, with one mesocycle running from last week to the goal."""
        from datetime import date, timedelta
        today = date.fromisoformat(today_str())
        out = lambda days: (today + timedelta(days=days)).isoformat()  # noqa: E731
        goal_id = test_db.add_objective(
            title="Zurich Marathon", target_date=out(45), sport_type="running",
        )
        test_db.save_macrocycle(
            objective_id=goal_id, strategy="Build then sharpen.",
            goals_hash="g", constraints_hash="c",
            mesocycles=[{"name": "Base", "start_date": out(-7), "end_date": out(45),
                         "focus": "Aerobic endurance, easy volume."}],
        )
        return goal_id

    def test_goal_list_reads_as_what_youre_training_for(self):
        self._goal_with_plan()
        code, out, _ = run_cli(["goal", "list"])
        self.assertEqual(code, 0)
        self.assertIn("What you're training for", out)
        self.assertIn("Zurich Marathon", out)
        # No IDs, no state tags, no expert header (§11).
        self.assertNotIn("=== GOALS ===", out)
        self.assertNotIn("[UPCOMING]", out)

    def test_plan_show_reads_as_the_road_to_the_goal(self):
        self._goal_with_plan()
        code, out, _ = run_cli(["plan", "show"])
        self.assertEqual(code, 0)
        self.assertIn("The road to Zurich Marathon", out)
        self.assertIn("you're in week", out)
        self.assertNotIn("MACROCYCLE STRATEGY", out)
        self.assertNotIn("Macrocycle ID", out)

    def test_plan_show_offers_the_door_to_a_mesocycle(self):
        """The road names the mesocycles; the button is how she reads one in full (§11.2)."""
        self._goal_with_plan()
        code, out, _ = run_cli(["plan", "show"])
        self.assertEqual(code, 0)
        self.assertIn(BUTTONS_SENTINEL, out)
        self.assertIn("bot mesocycle ", out)

    def test_plan_show_without_a_goal_invites_instead_of_naming_a_command(self):
        """The athlete cannot run `plan generate`, so the empty state must not name it
        (DESIGN_bot_simple_frontend.md §11)."""
        code, out, _ = run_cli(["plan", "show"])
        self.assertEqual(code, 0)
        self.assertIn("once your goal is set up", out)
        self.assertNotIn("plan generate", out)

    def test_progress_reads_as_a_summary_not_a_table(self):
        code, out, _ = run_cli(["progress", "--no-pull"])
        self.assertEqual(code, 0)
        self.assertIn("The chart shows your fitness", out)
        self.assertNotIn("FORM today", out)

    def test_the_expert_voice_is_what_the_same_commands_speak_without_the_env(self):
        """The other half of the switch: nothing above may leak into the default voice."""
        os.environ.pop("STAMIND_RENDER", None)
        self._goal_with_plan()
        _, goals_out, _ = run_cli(["goal", "list"])
        _, plan_out, _ = run_cli(["plan", "show"])
        self.assertIn("=== GOALS ===", goals_out)
        self.assertIn("MACROCYCLE STRATEGY", plan_out)


if __name__ == "__main__":
    unittest.main()
