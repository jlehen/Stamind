"""`bot` command family tests: the read half — morning-push idempotency, adapt_first, the
messages the bot sends unasked, the companion lists and their pickers, and the free-text
router (DESIGN_bot_simple_frontend.md §4.2, §5.3, §5.5, §12.6). The write half,
`bot capture <intent>`, is in `test_cli_bot_capture.py`."""
import json
import os
import shutil
import tempfile
import unittest
from datetime import date, datetime, time, timedelta
from unittest.mock import MagicMock, patch

from tests.helpers import (
    clear_all_tables, run_cli, rebind_test_db, save_workout, started_from,
)
from tests import test_db_path

TEST_DB_PATH = test_db_path("test_stamind_cli_bot.db")

from stamind.db import Database
import stamind_cli

from stamind import clock, journal, runtime
from stamind.cli.bot.morning import (
    NIGHT_IN_LINE, PREPARING_LINE, PUSH_ALL_DONE_LINE, WAITING_LINE,
)
from stamind import morning_message
from stamind.settings import ADAPT_LAST_SEEN
from stamind.cli.workouts import proposal as saved_proposal
from stamind.cli.render.session_lines import SIMPLE_DONE_LINE
from stamind.coach import picture
from stamind.coach.proposals import RevisionProposal
from stamind.config import config
from stamind.heads_up import CHANGE_LEAD, UNDONE_ONE, UNDONE_PLAIN, UNDONE_SEVERAL
from stamind.sentinels import BUTTONS_SENTINEL, FLUSH_SENTINEL
from stamind.clock import shift, today_str

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
        # Run from the terminal: the athlete watches nothing here.
        started_from(self, "terminal")

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

    def test_a_change_the_athlete_watched_is_never_sent(self):
        started_from(self, "chat")
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

    def test_a_waiting_change_goes_just_before_the_morning_message_on_its_own(self):
        """The morning message does not carry the line: `bot morning` sends it first, as a
        message of its own, so a message sent before the morning time cannot overtake it
        (DESIGN_change_heads_up.md §4, §7; DESIGN_morning_waits_for_night.md §5)."""
        self._change(note="Four sessions a week now.")
        with patch.dict(config.data, {"telegram": {"push": {"adapt_first": False}}}), \
                patch.dict(os.environ, {"STAMIND_FRONTEND": "json"}):
            _code, out, _ = run_cli(["bot", "morning"])
        told, message = out.split(FLUSH_SENTINEL, 1)
        self.assertIn(f"{CHANGE_LEAD} Four sessions a week now.", told)
        self.assertNotIn(CHANGE_LEAD, message)
        self.assertIn("Ride", message)
        self.assertEqual(test_db.waiting_changes(), [])


# The words of the morning message's first button: the chat's button rows travel as JSON,
# which escapes the emoji.
GOT_IT = "Got it"


class MorningWaitTest(unittest.TestCase):
    """With `adapt-first` on, `bot morning` waits for Garmin to have the night, until two
    hours after morning-time, and "📅 Today" sends the message once it has
    (DESIGN_morning_waits_for_night.md §3, §4, §5)."""

    def setUp(self):
        rebind_test_db(test_db)
        clear_all_tables(test_db)
        garmin = patch.object(runtime, "garmin", MagicMock(), create=True)
        garmin.start()
        self.addCleanup(garmin.stop)
        # The one call a try makes after the login: no night yet.
        self.look = runtime.garmin.connect.return_value.get_sleep_score
        self.look.return_value = None
        coach = MagicMock()
        coach.workout_adapt.return_value = MagicMock(workouts=[], reason="", strength_notice=None)
        for patcher in (
            patch.dict(config.data, {
                "telegram": {"push": {"adapt_first": True, "morning_time": "08:00"}},
                "garmin": {"email": "athlete@example.com", "password": "secret"},
            }),
            patch.object(runtime, "coach_service", coach, create=True),
            patch("stamind.cli.bot.morning.ensure_recent_data"),
        ):
            patcher.start()
            self.addCleanup(patcher.stop)
        self.today = today_str()
        save_workout(test_db, self.today, "running", "Easy run", duration_minutes=40)

    def _in_chat_at(self, argv, hour, minute=0):
        """What `argv` sends into the chat when run at that local time today."""
        moment = datetime.combine(date.fromisoformat(self.today), time(hour, minute))
        with patch("stamind.clock.now", return_value=moment.astimezone()), \
                patch.dict(os.environ, {"STAMIND_FRONTEND": "json", "STAMIND_RENDER": "simple"}):
            return run_cli(argv)[1]

    def _morning_at(self, hour, minute=0, *flags):
        return self._in_chat_at(["bot", "morning", *flags], hour, minute)

    def _today_at(self, hour, minute=0):
        """A tap on "📅 Today" at that local time today."""
        return self._in_chat_at(["bot", "today"], hour, minute)

    def test_a_tap_once_the_night_is_in_sends_the_morning_message_once(self):
        """Tuesday of §3: 05:50, and the watch has synced."""
        self.look.return_value = 74
        out = self._today_at(5, 50)
        self.assertIn(NIGHT_IN_LINE, out)
        self.assertIn(GOT_IT, out)
        self.assertTrue(morning_message.sent_on(self.today))
        again = self._today_at(6)
        self.assertIn("Easy run", again)
        self.assertNotIn(PREPARING_LINE, again)
        self.assertNotIn(GOT_IT, again)
        self.assertEqual(self._morning_at(8).strip(), "")

    def test_a_tap_before_the_night_shows_the_sessions_and_says_when_the_message_comes(self):
        """Wednesday of §3: 06:10, and the watch has not synced."""
        out = self._today_at(6, 10)
        self.assertIn("Easy run", out)
        self.assertIn(WAITING_LINE.format(time="10:00"), " ".join(out.split()))
        self.assertNotIn(GOT_IT, out)
        self.assertFalse(morning_message.sent_on(self.today))

    def test_past_the_mark_a_tap_sends_the_message_without_claiming_the_night(self):
        """The bot was down all morning (§7 choice 6)."""
        out = self._today_at(14)
        self.assertIn(PREPARING_LINE, out)
        self.assertNotIn(NIGHT_IN_LINE, out)
        self.assertIn(GOT_IT, out)

    def test_with_adapt_first_off_a_tap_sends_the_message_at_once_and_says_nothing_first(self):
        with patch.dict(config.data, {"telegram": {"push": {"adapt_first": False}}}):
            out = self._today_at(6, 10)
        self.assertNotIn(PREPARING_LINE, out)
        self.assertIn(GOT_IT, out)
        self.look.assert_not_called()

    def test_with_the_push_off_a_tap_is_the_sessions_alone(self):
        with patch.dict(config.data, {"telegram": {"push": {"enabled": False}}}):
            out = self._today_at(6, 10)
        self.assertIn("Easy run", out)
        self.assertNotIn(GOT_IT, out)
        self.assertFalse(morning_message.sent_on(self.today))

    def test_in_a_terminal_bot_today_lists_the_sessions(self):
        morning_message.mark_sent()
        code, out, _ = run_cli(["bot", "today"])
        self.assertEqual(code, 0)
        self.assertIn("Easy run", out)

    def test_the_message_waits_while_garmin_has_no_night(self):
        self.assertEqual(self._morning_at(8).strip(), "")
        self.assertFalse(morning_message.sent_on(self.today))
        self.look.assert_called_once_with(self.today)
        runtime.coach_service.workout_adapt.assert_not_called()

    def test_the_try_after_the_watch_synced_sends_it(self):
        self._morning_at(8)
        self.look.return_value = 74
        self.assertIn("Easy run", self._morning_at(8, 15))
        self.assertTrue(morning_message.sent_on(self.today))

    def test_a_night_already_stored_needs_no_look(self):
        test_db.save_metric_cache(self.today, 50, 60, 80, 20, None, None, None)
        self.assertIn("Easy run", self._morning_at(8))
        self.look.assert_not_called()

    def test_at_the_two_hour_mark_it_goes_without_the_night(self):
        """Friday of §3: the watch is broken, and the 10:00 try sends."""
        self.assertIn("Easy run", self._morning_at(10))
        self.look.assert_not_called()

    def test_a_look_that_fails_counts_as_no_night_and_stays_out_of_the_chat(self):
        runtime.garmin.connect.side_effect = RuntimeError("Garmin down")
        self.assertEqual(self._morning_at(8).strip(), "")
        self.assertFalse(morning_message.sent_on(self.today))

    def test_a_try_that_waits_leaves_no_run_and_a_failed_look_a_named_one(self):
        """The failed look's warning is journalled, so its run is kept under its name."""
        def ends():
            return [r for r in journal.iter_records() if r["ev"] == "run.end"]

        before = len(ends())
        self._morning_at(8)
        self.assertEqual(len(ends()), before)
        runtime.garmin.connect.side_effect = RuntimeError("Garmin down")
        self._morning_at(8, 15)
        self.assertEqual([r["d"]["cmd"] for r in ends()[before:]], ["bot morning"])

    def test_a_message_that_breaks_half_way_is_not_tried_again(self):
        """It counts as sent from the moment it starts (§7 choice 16)."""
        self.look.return_value = 74
        with patch("stamind.cli.bot.morning._refresh_garmin", side_effect=RuntimeError("bug")):
            out = self._morning_at(8)
        self.assertNotIn("Easy run", out)
        self.assertTrue(morning_message.sent_on(self.today))

    def test_no_wait_without_garmin_with_adapt_first_off_or_with_force(self):
        for pinned, flags in (
            ({"garmin": {}}, ()),
            ({"telegram": {"push": {"adapt_first": False}}}, ()),
            ({}, ("--force",)),
        ):
            with patch.dict(config.data, pinned):
                self.assertIn("Easy run", self._morning_at(8, 0, *flags))
            test_db.clear_setting(morning_message.MARKER)
        self.look.assert_not_called()


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
        # The operator's config.yaml must not switch adapt-first on for these tests.
        telegram = {k: v for k, v in (config.data.get("telegram") or {}).items() if k != "push"}
        pinned = patch.dict(config.data, {"telegram": telegram})
        pinned.start()
        self.addCleanup(pinned.stop)

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
        self.assertTrue(morning_message.sent_on(today_str()))

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
        self.assertTrue(morning_message.sent_on(today_str()))

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

    def test_the_retrospectives_step_runs_once_a_day_even_on_a_silent_morning(self):
        """After the once-a-day test, and before the test that keeps the push silent once
        the schedule has run out (DESIGN_cycle_retrospective.md §3)."""
        ended = (clock.today_date() - timedelta(days=20)).isoformat()
        started = (clock.today_date() - timedelta(days=60)).isoformat()
        goal = test_db.add_objective("Zurich Marathon", ended, "running")
        test_db.save_macrocycle(goal, "Build.", "g", "c", [
            {"name": "Base", "start_date": started, "end_date": ended, "focus": "Endurance"},
        ])
        save_workout(test_db, ended, "running", "Race")
        with patch.object(runtime.coach_service, "retrospectives_step") as retrospectives:
            code, out, _ = run_cli(["bot", "morning"])
            run_cli(["bot", "morning"])
        self.assertEqual(code, 0)
        self.assertEqual(out.strip(), "")
        retrospectives.assert_called_once_with()

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
            patch("stamind.cli.bot.morning.ensure_recent_data"),
        )

    def test_adapt_first_writes_moved_kilograms_and_surfaces_the_reason(self):
        """Only the strength planner changed something, so the push writes it without
        asking. A session the week planner would change is saved as a proposal instead,
        which `test_waiting_proposal.py` covers (DESIGN_waiting_proposal.md §5, §7)."""
        save_workout(test_db, today_str(), "strength_training", "Gym")
        proposal = MagicMock(
            workouts=[{"date": today_str()}], reason="Belt squat goes up 5 kg.",
            strength_notice=None, week_planner_changed=False,
        )
        coach = MagicMock()
        coach.workout_adapt.return_value = proposal
        cfg, svc, pull = self._adapt_first_env(coach)
        with cfg, svc, pull:
            code, out, _ = run_cli(["bot", "morning"])
        self.assertEqual(code, 0)
        coach.workout_revision_apply.assert_called_once_with(proposal)
        self.assertIn("Belt squat goes up 5 kg.", out)

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

    def test_the_morning_calls_are_not_announced_in_the_chat(self):
        """The scheduler starts the push, so nobody is waiting on the week planner or the
        strength planner: no "Reviewing your coming sessions" (DESIGN_output_verbosity.md
        §8.4)."""
        from stamind.openrouter import openrouter_client
        announced = []

        def adapt(*_args, **_kwargs):
            announced.append(openrouter_client.announces_wait)
            return MagicMock(workouts=[], reason="", strength_notice=None)

        coach = MagicMock()
        coach.workout_adapt.side_effect = adapt
        cfg, svc, pull = self._adapt_first_env(coach)
        with cfg, svc, pull:
            run_cli(["bot", "morning"])
        self.assertEqual(announced, [False])
        self.assertTrue(openrouter_client.announces_wait)

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
        self.assertTrue(morning_message.sent_on(today_str()))

    def _adapt_first_run(self, coach):
        coach.workout_adapt.return_value = MagicMock(
            workouts=[], reason="All green.", strength_notice=None,
        )
        cfg, svc, pull = self._adapt_first_env(coach)
        with cfg, svc, pull as pulled:
            code, out, _ = run_cli(["bot", "morning"])
        self.assertEqual(code, 0)
        return out, pulled

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


class QuietMorningTest(unittest.TestCase):
    """With `adapt-first` on, the push asks the week planner only when something is new
    since the last run or a night since the last one in hand is not normal
    (DESIGN_quiet_morning.md §2–§6). Each case stores the last run's picture, changes one
    thing, and runs the push."""

    def setUp(self):
        rebind_test_db(test_db)
        clear_all_tables(test_db)
        garmin = patch.object(runtime, "garmin", MagicMock(), create=True)
        garmin.start()
        self.addCleanup(garmin.stop)
        # The picture hashes the profile and the science documents, so both are pinned
        # here rather than read off the operator's config.yaml.
        science = tempfile.mkdtemp(prefix="stamind-test-science-")
        self.addCleanup(shutil.rmtree, science, ignore_errors=True)
        pinned = patch.dict(config.data, {
            "telegram": {"push": {"adapt_first": True}},
            "coach": {"minor_activity_load_threshold": 25.0, "metrics_lookback_days": 15},
            "user_profile": {"name": "Test athlete", "lthr": 165},
            "science_dir": science,
        })
        pinned.start()
        self.addCleanup(pinned.stop)
        self.today = today_str()
        self.yesterday = shift(self.today, -1)

    def _remember(self, **overrides):
        """The last run's picture, taken now, with `overrides` on top."""
        taken = picture.take(test_db, self.today)
        taken.update(overrides)
        test_db.set_setting(ADAPT_LAST_SEEN, json.dumps(taken))
        return json.dumps(taken)

    def _push(self, pull=None):
        """One push with the week planner mocked to change nothing. Returns whether it
        asked the week planner, and the journal's lines."""
        coach = MagicMock()
        coach.workout_adapt.return_value = MagicMock(
            workouts=[], reason="All green.", strength_notice=None,
        )
        with patch.object(runtime, "coach_service", coach, create=True), \
                patch("stamind.cli.bot.morning.ensure_recent_data", side_effect=pull), \
                patch("stamind.journal.record") as journal, \
                patch.dict(os.environ, {"STAMIND_FRONTEND": "json"}):
            code, out, _ = run_cli(["bot", "morning", "--force"])
        self.assertEqual(code, 0)
        self.out = out
        lines = [(c.args[1], c.kwargs.get("lvl", "info")) for c in journal.call_args_list]
        return coach.workout_adapt.called, lines

    def _asked(self, lines, reason):
        """The push asked the week planner for `reason`, and not because the gate failed
        open: no warning in the journal."""
        self.assertEqual([line for line, lvl in lines if lvl == "warn"], [])
        self.assertTrue(
            any(line.startswith("Asking the week planner:") and reason in line
                for line, _lvl in lines),
            lines,
        )

    def _activity(self, day, tss, minutes=60, sport="cycling", name="Ride"):
        test_db.save_completed_activity(
            activity_id=f"a-{day}-{sport}", date=day, start_time=f"{day} 07:00:00",
            activity_name=name, activity_type=sport, duration_sec=minutes * 60,
            distance_km=10.0, elevation_gain_m=0.0, avg_hr=140, max_hr=160, rpe=None,
            tss=tss,
        )

    def _plan(self, goal=None):
        if goal is None:
            goal = test_db.add_objective("Race", shift(self.today, 60), "cycling")
        return test_db.save_macrocycle(goal, "Build.", "g", "c", [{
            "name": "Base", "start_date": shift(self.today, -10),
            "end_date": shift(self.today, 20), "focus": "Endurance",
        }])

    def _baseline(self):
        test_db.save_baseline(self.yesterday, 50.0, 2.0, 60.0, 5.0, 80.0, 5.0)

    # --- nothing new ---

    def test_a_normal_night_with_nothing_new_is_quiet(self):
        """It is Friday. Thursday's ride was done as planned and the night was normal."""
        test_db.add_constraint("Travel", self.today, shift(self.today, 3))
        test_db.add_objective("Race", shift(self.today, 60), "cycling")
        save_workout(test_db, self.yesterday, "cycling", "Ride", duration_minutes=60, tss=60)
        save_workout(test_db, shift(self.today, 1), "cycling", "Long ride")
        self._activity(self.yesterday, tss=60.0)
        self._baseline()
        stored = self._remember(date=self.yesterday, activities=[])
        test_db.save_metric_cache(self.today, 50, 60, 80, 20)
        asked, lines = self._push()
        self.assertFalse(asked)
        self.assertIn(("Quiet morning: the night is normal and nothing is new since "
                       f"{picture.taken(json.loads(stored))}", "info"), lines)
        # A quiet morning writes no picture and shows the schedule as a no-change run does.
        self.assertEqual(test_db.get_setting(ADAPT_LAST_SEEN), stored)
        self.assertIn("Rest day", self.out)

    def test_with_no_night_to_grade_the_quiet_line_says_so(self):
        self._remember()
        asked, lines = self._push()
        self.assertFalse(asked)
        self.assertTrue(any(line.startswith("Quiet morning: nothing is new since")
                            and line.endswith("no night since has a reading")
                            for line, _lvl in lines))

    # --- activities and sessions ---

    def test_a_missed_session_runs(self):
        save_workout(test_db, self.yesterday, "running", "Tempo run", duration_minutes=40)
        save_workout(test_db, shift(self.today, 1), "running", "Long run")
        self._remember(date=self.yesterday)
        asked, lines = self._push()
        self.assertTrue(asked)
        day = f"{datetime.strptime(self.yesterday, '%Y-%m-%d'):%A}"
        self.assertIn((f"Asking the week planner: {day}'s Tempo run is missed", "info"),
                      lines)

    def test_a_session_cut_short_runs_even_under_the_minor_threshold(self):
        save_workout(test_db, self.yesterday, "cycling", "Ride", duration_minutes=60, tss=60)
        save_workout(test_db, shift(self.today, 1), "cycling", "Long ride")
        self._remember(date=self.yesterday)
        self._activity(self.yesterday, tss=10.0, minutes=12)
        _asked, lines = self._push()
        self._asked(lines, "a new activity")

    def test_an_unmatched_minor_activity_is_quiet(self):
        self._remember(date=self.yesterday)
        self._activity(self.yesterday, tss=10.0, minutes=20, sport="walking", name="Walk")
        asked, _lines = self._push()
        self.assertFalse(asked)

    def test_an_unplanned_activity_runs(self):
        self._remember(date=self.yesterday)
        self._activity(self.yesterday, tss=80.0, minutes=180, sport="hiking", name="Hike")
        asked, lines = self._push()
        self.assertTrue(asked)
        self.assertTrue(any("a new activity" in line and "Hike" in line
                            for line, _lvl in lines))

    def test_this_mornings_activity_that_matched_todays_session_is_clean(self):
        save_workout(test_db, self.today, "swimming", "Swim", duration_minutes=45, tss=40)
        self._remember(date=self.yesterday)
        self._activity(self.today, tss=40.0, minutes=45, sport="swimming", name="Swim")
        asked, _lines = self._push()
        self.assertFalse(asked)

    def test_an_activity_synced_late_runs_unless_it_is_minor(self):
        """A ride from four days ago appears this morning: outside the window the verdicts
        grade, so it counts as unmatched."""
        late = shift(self.today, -4)
        self._remember(date=self.yesterday)
        self._activity(late, tss=10.0, minutes=15, sport="walking", name="Walk")
        asked, _lines = self._push()
        self.assertFalse(asked)
        self._activity(late, tss=80.0, minutes=120)
        _asked, lines = self._push()
        self._asked(lines, "a new activity")

    # --- what was written ---

    def test_a_session_written_since_runs_unless_the_week_planner_wrote_it(self):
        tomorrow = shift(self.today, 1)
        self._remember()
        save_workout(test_db, tomorrow, "running", "Easy run", kind="adapt")
        asked, _lines = self._push()
        self.assertFalse(asked)
        save_workout(test_db, tomorrow, "running", "Long run", kind="generate")
        asked, lines = self._push()
        self.assertTrue(asked)
        self.assertIn(("Asking the week planner: a session was written", "info"), lines)

    def test_a_tweak_writes_no_picture_and_its_change_is_news(self):
        self._remember()
        tweak = RevisionProposal(reason="", workouts=[], range_start=self.today,
                                 range_end=self.today, kind="tweak")
        stored = test_db.get_setting(ADAPT_LAST_SEEN)
        picture.remember(test_db, tweak)
        self.assertEqual(test_db.get_setting(ADAPT_LAST_SEEN), stored)
        save_workout(test_db, shift(self.today, 1), "running", "Easy run", kind="tweak")
        _asked, lines = self._push()
        self._asked(lines, "a session was written")

    # --- the hashed sources ---

    def test_a_constraint_change_runs(self):
        ended = test_db.add_constraint("Travel", self.today, shift(self.today, 5))
        self._remember()
        test_db.update_constraint(ended, end_date=shift(self.today, 1))
        asked, lines = self._push()
        self.assertTrue(asked)
        self.assertIn(("Asking the week planner: a constraint changed", "info"), lines)

    def test_a_goal_edit_runs(self):
        goal = test_db.add_objective("Race", shift(self.today, 60), "cycling")
        self._remember()
        test_db.update_objective(goal, title="Gran Fondo")
        _asked, lines = self._push()
        self._asked(lines, "a goal changed")

    def test_a_logged_benchmark_runs(self):
        self._remember()
        test_db.add_benchmark_result(self.today, "cycling", "ftp", 250.0, "W")
        _asked, lines = self._push()
        self._asked(lines, "a benchmark was logged")

    def test_a_profile_edit_runs(self):
        self._remember()
        with patch.dict(config.data, {"user_profile": {"name": "Someone else"}}):
            _asked, lines = self._push()
        self._asked(lines, "the profile changed")

    def test_a_science_edit_runs(self):
        self._remember()
        with patch("stamind.coach.picture.athlete_science_documents",
                   return_value={"strength.md": "Lift heavy."}):
            _asked, lines = self._push()
        self._asked(lines, "a science guideline changed")

    def test_a_new_plan_version_runs(self):
        goal = test_db.add_objective("Race", shift(self.today, 60), "cycling")
        self._plan(goal)
        self._remember()
        self._plan(goal)
        asked, lines = self._push()
        self.assertTrue(asked)
        self.assertIn(("Asking the week planner: the plan changed", "info"), lines)

    def test_a_new_mesocycle_runs(self):
        """Yesterday's run saw the Base mesocycle, which ended yesterday; this morning the
        Build mesocycle is the active one, under the same plan version."""
        goal = test_db.add_objective("Race", shift(self.today, 60), "cycling")
        macro = test_db.save_macrocycle(goal, "Build.", "g", "c", [
            {"name": "Base", "start_date": shift(self.today, -20),
             "end_date": self.yesterday, "focus": "Endurance"},
            {"name": "Build", "start_date": self.today,
             "end_date": shift(self.today, 20), "focus": "Threshold"},
        ])
        [base] = [m for m in test_db.get_mesocycles_for_macrocycle(macro)
                  if m["name"] == "Base"]
        self._remember(date=self.yesterday, plan=[macro, base["id"], base["end_date"]])
        _asked, lines = self._push()
        self._asked(lines, "the plan changed")

    # --- the strength planner's work test ---

    def test_the_strength_planners_work_alone_runs_the_morning(self):
        self._plan()
        gym = save_workout(test_db, shift(self.today, 2), "strength_training", "Gym",
                           prescribed_sets=[{"exercise": "SQUAT/BELT_SQUAT", "sets": 3,
                                             "reps_low": 4, "reps_high": 6,
                                             "load_kg": 140.0, "light": False}])
        test_db.record_strength_check(gym, test_db.strength_history_stamp())
        self._remember()
        asked, _lines = self._push()
        self.assertFalse(asked)
        test_db.bump_strength_history()
        asked, lines = self._push()
        self.assertTrue(asked)
        self.assertIn(("Asking the week planner: the strength planner has work", "info"),
                      lines)

    # --- the night ---

    def test_a_night_not_normal_after_the_last_one_in_hand_runs(self):
        self._baseline()
        self._remember()
        test_db.save_metric_cache(self.today, 50, 40, 80, 20)
        asked, lines = self._push()
        self.assertTrue(asked)
        day = f"{datetime.strptime(self.today, '%Y-%m-%d'):%A}"
        self.assertIn((f"Asking the week planner: {day}'s night is not normal: "
                       "HRV suppressed", "info"), lines)

    def test_a_poor_sleep_score_runs_without_a_baseline(self):
        self._remember()
        test_db.save_metric_cache(self.today, 50, 60, 41, 20)
        _asked, lines = self._push()
        self._asked(lines, "sleep poor")

    def test_a_night_the_last_run_had_in_hand_does_not_run(self):
        self._baseline()
        test_db.save_metric_cache(self.today, 50, 40, 80, 20)
        self._remember()
        asked, _lines = self._push()
        self.assertFalse(asked)

    def test_an_unknown_night_is_quiet(self):
        """No baseline to grade HRV against, and then a day whose sleep is not scored yet
        though its resting HR is in."""
        self._remember()
        test_db.save_metric_cache(self.today, 50, 40, 80, 20)
        asked, _lines = self._push()
        self.assertFalse(asked)
        self._baseline()
        test_db.save_metric_cache(self.today, 70, None, None, None)
        asked, _lines = self._push()
        self.assertFalse(asked)

    def test_the_night_is_graded_after_the_forced_pull(self):
        """At 08:00 the sleep score is not in; the forced pull brings a poor night."""
        self._remember()

        def pull(day, force_pull):
            self.assertTrue(force_pull)
            test_db.save_metric_cache(day, 50, 60, 41, 20)

        _asked, lines = self._push(pull=pull)
        self._asked(lines, "sleep poor")

    # --- the gate fails open ---

    def _warned(self, lines):
        return [line for line, lvl in lines if lvl == "warn"]

    def test_no_picture_runs_and_warns(self):
        asked, lines = self._push()
        self.assertTrue(asked)
        self.assertEqual(self._warned(lines),
                         ["Asking the week planner: no picture of the last run"])
        self.assertNotIn("picture", self.out)

    def test_a_broken_picture_runs_and_warns(self):
        test_db.set_setting(ADAPT_LAST_SEEN, "{not json")
        asked, lines = self._push()
        self.assertTrue(asked)
        self.assertTrue(self._warned(lines)[0].startswith(
            "Asking the week planner: the gate failed:"))

    def test_an_exception_in_the_gate_runs_and_warns(self):
        self._remember()
        with patch("stamind.coach.picture.take", side_effect=RuntimeError("boom")):
            asked, lines = self._push()
        self.assertTrue(asked)
        self.assertEqual(self._warned(lines),
                         ["Asking the week planner: the gate failed: boom"])

    def test_a_run_writes_the_picture_only_when_evaluated_on_today(self):
        service = runtime.coach_service
        seen = picture.take(test_db, self.today)
        service.workout_revision_record_no_change(RevisionProposal(
            reason="", workouts=[], range_start=self.yesterday, range_end=self.yesterday,
            seen={**seen, "date": self.yesterday},
        ))
        self.assertIsNone(test_db.get_setting(ADAPT_LAST_SEEN))
        service.workout_revision_record_no_change(RevisionProposal(
            reason="", workouts=[], range_start=self.today, range_end=self.today, seen=seen,
        ))
        self.assertEqual(json.loads(test_db.get_setting(ADAPT_LAST_SEEN)), seen)

    def test_an_apply_writes_the_picture(self):
        """The path of a terminal `y` and of kilograms that moved alone."""
        save_workout(test_db, self.today, "running", "Easy run", duration_minutes=40)
        seen = picture.take(test_db, self.today)
        runtime.coach_service.workout_revision_apply(RevisionProposal(
            reason="Ease it.", range_start=self.today, range_end=self.today, seen=seen,
            workouts=[{"date": self.today, "sport_type": "running", "title": "Easy run",
                       "description": "30 easy minutes.", "duration_minutes": 30}],
        ))
        self.assertEqual(test_db.get_workout(self.today, "running")["duration_minutes"], 30)
        self.assertEqual(json.loads(test_db.get_setting(ADAPT_LAST_SEEN)), seen)


class RouteCommandTest(unittest.TestCase):
    """`bot route` — §5.3/§5.4: intent validation, graceful degradation, and the
    fast-model role."""

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

    def test_the_router_reads_goal_and_constraint_titles_beside_the_message(self):
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

    def test_fast_model_role_pins_the_client(self):
        from stamind.openrouter import openrouter_client
        # The router picks from the same menu the thinking model does — one allowlist
        # (DESIGN_settings.md §4), so the cheap model is listed under `llm.models` too.
        with patch.dict(
            config.data,
            {"llm": {"models": ["main/model", "cheap/model"],
                     "fast_model": "cheap/model"}},
        ), patch(
            "stamind.openrouter.OpenRouterClient.complete",
            return_value={"intent": "help"},
        ):
            run_cli(["bot", "route", "hello"])
            self.assertEqual(openrouter_client.model, "cheap/model")

    def test_an_off_menu_role_is_ignored_and_the_thinking_model_routes(self):
        from stamind.openrouter import openrouter_client
        with patch.dict(
            config.data,
            {"llm": {"models": ["main/model"], "fast_model": "cheap/model"}},
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
        self._add("old constraint", start="2020-01-01", end="2020-01-02")
        _, out, _ = run_cli(["bot", "constraints"])
        self.assertNotIn("old constraint", out)
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


class SimpleListRenderTest(unittest.TestCase):
    """`workout list` under STAMIND_RENDER=simple: a single day renders as companion prose;
    multi-day ranges keep the expert listing (§6)."""

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

    def test_multi_day_range_renders_expert_schedule(self):
        save_workout(test_db, today_str(), "running", "Easy run", duration_minutes=40)
        _, out, _ = run_cli(["workout", "list"])
        self.assertIn("WORKOUT SCHEDULE", out)
        self.assertIn("Easy run", out)
        self.assertNotIn("Coming up", out)

    def test_expert_form_is_untouched_without_the_env(self):
        os.environ.pop("STAMIND_RENDER", None)
        save_workout(test_db, today_str(), "running", "Easy run")
        _, out, _ = run_cli(["workout", "list", "-d", "today"])
        self.assertIn("WORKOUT SCHEDULE", out)


class CompanionSurfaceRoutingTest(unittest.TestCase):
    """Companion surfaces and expert-only commands driven through the real CLI
    (DESIGN_render_persona.md §5).

    The line builders have their own unit tests; what these pin is the *routing* — that
    companion commands reach `runtime.render`, while `goal list` and `plan show` keep their
    expert output even under `STAMIND_RENDER=simple`."""

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

    def test_bot_goals_renders_companion_prose_and_picker(self):
        self._goal_with_plan()
        code, out, _ = run_cli(["bot", "goals"])
        self.assertEqual(code, 0)
        self.assertIn("What you're training for", out)
        self.assertIn("Zurich Marathon", out)
        self.assertIn(BUTTONS_SENTINEL, out)
        self.assertNotIn("=== GOALS ===", out)

    def test_plan_show_and_goal_list_keep_expert_output_under_simple(self):
        self._goal_with_plan()
        goals_code, goals_out, _ = run_cli(["goal", "list"])
        plan_code, plan_out, _ = run_cli(["plan", "show"])
        self.assertEqual(goals_code, 0)
        self.assertEqual(plan_code, 0)
        self.assertIn("=== GOALS ===", goals_out)
        self.assertNotIn("What you're training for", goals_out)
        self.assertIn("MACROCYCLE STRATEGY", plan_out)
        self.assertNotIn("The road to", plan_out)

    def test_progress_in_the_chat_prints_what_the_terminal_prints(self):
        # The Progress page holds the weeks; the chat's three sentences went
        # (DESIGN_progress_page.md §5).
        code, out, _ = run_cli(["progress", "--no-pull"])
        self.assertEqual(code, 0)
        self.assertIn("FORM today", out)
        self.assertNotIn("The chart shows your fitness", out)

    def test_the_expert_voice_is_what_the_same_commands_speak_without_the_env(self):
        """The other half of the switch: nothing above may leak into the default voice."""
        os.environ.pop("STAMIND_RENDER", None)
        code, out, _ = run_cli(["progress", "--no-pull"])
        self.assertEqual(code, 0)
        self.assertIn("FORM today", out)


if __name__ == "__main__":
    unittest.main()
