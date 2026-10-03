"""A proposal that waits for the athlete's answer (DESIGN_waiting_proposal.md).

It is Thursday. A 90-minute ride is planned, and the week planner would cut it to 60 easy
minutes. Each case saves that proposal, or lets a run save it, and checks one rule.
"""
import json
import os
import unittest
from datetime import datetime, timedelta
from unittest.mock import MagicMock, patch

from tests.helpers import bind_test_db, clear_all_tables, rebind_test_db, run_cli, save_workout
from tests import test_db_path

test_db = bind_test_db(test_db_path("test_waiting_proposal.db"))

import stamind_cli  # noqa: F401 — the CLI binds its handles at import, before the rebind

from stamind import athlete_queue, runtime
from stamind.cli import queue as queue_cli
from stamind.cli.workouts import proposal as saved_proposal
from stamind.cli.workouts.adapt import WEEK_CHANGED_LINE
from stamind.cli.workouts.heads_up import newest_written
from stamind.coach.proposals import RevisionProposal
from stamind.coach.revisions import pair_revisions
from stamind.config import config
from stamind.sentinels import BUTTONS_SENTINEL, QUEUE_SENTINEL
from stamind.clock import today_str

THURSDAY_8AM = datetime(2026, 10, 8, 8, 0).astimezone()
THURSDAY, FRIDAY, SATURDAY = "2026-10-08", "2026-10-09", "2026-10-10"


def queue_lines(out):
    """The SM-QUEUE payloads a run wrote, in order."""
    return [json.loads(line[len(QUEUE_SENTINEL):]) for line in out.split("\n")
            if line.startswith(QUEUE_SENTINEL)]


class _Case(unittest.TestCase):
    """Thursday 08:00 in the athlete's chat, with the 90-minute ride planned for today."""

    def setUp(self):
        rebind_test_db(test_db)
        clear_all_tables(test_db)
        self.now = THURSDAY_8AM
        moving_clock = patch("stamind.clock.now", side_effect=lambda: self.now)
        moving_clock.start()
        self.addCleanup(moving_clock.stop)
        self.garmin = MagicMock()
        for patcher in (
            patch.object(runtime, "garmin", self.garmin, create=True),
            patch("stamind.runtime.calendar_syncer"),
            patch.dict(os.environ, {"STAMIND_FRONTEND": "json", "STAMIND_RENDER": "simple"}),
        ):
            patcher.start()
            self.addCleanup(patcher.stop)
        self.addCleanup(runtime.reset, "render", "prompt")
        runtime.reset("render")
        save_workout(test_db, THURSDAY, "cycling", "Intervals",
                     description="[Intervals]\n90 minutes with intervals.",
                     duration_minutes=90, rpe=7, tss=90)

    def at(self, hour, minute=0, days=0):
        self.now = THURSDAY_8AM.replace(hour=hour, minute=minute) + timedelta(days=days)

    def eased(self, day=THURSDAY, title="Easy ride", minutes=60, **fields):
        """The week planner's proposal: the ride of `day` becomes easy minutes."""
        workouts = [{
            "date": day, "sport_type": "cycling", "title": title,
            "description": f"[{title}]\n{minutes} easy minutes.",
            "modification_reason": "Rough night.", "duration_minutes": minutes,
            "rpe": 3, "tss": 30,
        }]
        pairs, removals = pair_revisions(
            workouts, test_db.get_workouts(start_date=day, end_date=day)
        )
        fields.setdefault("week_planner_changed", True)
        return RevisionProposal(
            reason="Rough night.", workouts=workouts, range_start=THURSDAY, range_end=day,
            pairs=pairs, removals=removals, sleep_seen=True, **fields,
        )

    def save(self, **kwargs):
        return saved_proposal.save(self.eased(**kwargs), newest_written())

    def tap(self, item, action="a1"):
        token = queue_cli.since_token(self.now, single=True)
        _code, out, _err = run_cli(["bot", "queue", str(item["id"]), action, "--since", token])
        return out

    def ride(self, day=THURSDAY):
        return test_db.get_workout(day, "cycling")

    def outcome(self, item):
        return test_db.get_queue_item(item["id"])["outcome"]

    def trained_at_noon(self):
        test_db.save_completed_activity(
            activity_id="a-ride", date=THURSDAY, start_time=f"{THURSDAY} 12:00:00",
            activity_name="Ride", activity_type="cycling", duration_sec=5400,
            distance_km=40.0, elevation_gain_m=0.0, avg_hr=140, max_hr=160, rpe=None,
            tss=90.0,
        )


class AnswerTest(_Case):
    """What each answer does (§4)."""

    def test_change_it_writes_what_was_saved_and_asks_nobody_again(self):
        item = self.save()
        with patch.object(runtime.coach_service, "workout_adapt",
                          side_effect=AssertionError("the week planner was asked again")):
            out = self.tap(item)
        self.assertIn(saved_proposal.APPLIED_LINE, out)
        self.assertEqual((self.ride()["title"], self.ride()["duration_minutes"]),
                         ("Easy ride", 60))
        self.assertEqual(self.outcome(item), athlete_queue.ANSWERED)
        # The athlete watched it happen, so no heads-up line waits (§4).
        self.assertEqual(test_db.waiting_changes(), [])

    def test_a_taps_change_never_carries_the_sleep_mark(self):
        """Thursday evening's proposal read Thursday's night. Accepted on Friday at 07:00,
        its change must not tell the 08:00 push that Friday's night was read (§5)."""
        self.tap(self.save())
        self.assertIsNone(test_db.newest_adapt()["sleep_seen"])

    def test_keep_it_as_planned_writes_nothing_and_pulls_nothing(self):
        item = self.save()
        out = self.tap(item, "a2")
        self.assertIn(saved_proposal.KEPT_LINE, out)
        self.assertEqual(self.ride()["duration_minutes"], 90)
        self.assertEqual(self.outcome(item), athlete_queue.ANSWERED)
        self.garmin.ensure_data.assert_not_called()


class OutOfDateTest(_Case):
    """A tap that comes too late writes nothing (§4)."""

    def refused(self, item):
        out = self.tap(item)
        self.assertIn(saved_proposal.OUT_OF_DATE_LINE, out)
        self.assertEqual(self.ride()["duration_minutes"], 90)
        self.assertEqual(self.outcome(item), athlete_queue.STALE)

    def test_rule_1_a_later_change_wrote_a_session(self):
        item = self.save()
        save_workout(test_db, SATURDAY, "running", "Long run", duration_minutes=100)
        self.refused(item)

    def test_a_run_that_changed_nothing_does_not_put_it_out_of_date(self):
        item = self.save()
        with test_db.workout_change(kind="adapt", summary="held"):
            pass
        self.assertIn(saved_proposal.APPLIED_LINE, self.tap(item))

    def test_rule_2_a_day_it_changes_is_over(self):
        item = self.save()
        self.at(7, days=1)
        self.refused(item)

    def test_rule_3_the_ride_was_done_after_the_proposal_was_made(self):
        """08:00 the proposal, 12:00 the ride, 15:00 the tap. The tap pulls today's
        activities past the throttle before it decides."""
        item = self.save()
        self.garmin.ensure_data.side_effect = lambda *args, **kwargs: self.trained_at_noon()
        self.at(15)
        self.refused(item)
        self.garmin.ensure_data.assert_called_once_with(THURSDAY, THURSDAY, force=True)

    def test_garmin_out_of_reach_uses_what_is_stored(self):
        item = self.save()
        self.garmin.ensure_data.side_effect = RuntimeError("Garmin down")
        self.at(15)
        self.assertIn(saved_proposal.APPLIED_LINE, self.tap(item))

    def test_a_proposal_about_another_day_pulls_nothing(self):
        save_workout(test_db, SATURDAY, "cycling", "Long ride", duration_minutes=180)
        item = self.save(day=SATURDAY)
        self.assertIn(saved_proposal.APPLIED_LINE, self.tap(item))
        self.garmin.ensure_data.assert_not_called()

    def test_a_tap_on_a_closed_proposal_gets_the_same_line(self):
        item = self.save()
        self.tap(item, "a2")
        self.assertIn(saved_proposal.OUT_OF_DATE_LINE, self.tap(item))
        self.assertEqual(self.ride()["duration_minutes"], 90)


class StandAloneTest(_Case):
    """A proposal is sent when saved, is in no round and has no "Not now" (§3)."""

    def test_saving_a_proposal_closes_the_others_that_wait(self):
        first = self.save()
        self.at(8, 5)
        second = self.save(minutes=45)
        self.assertEqual(self.outcome(first), athlete_queue.STALE)
        self.assertEqual([item["id"] for item in saved_proposal.waiting()], [second["id"]])

    def test_it_is_in_no_round_and_not_counted(self):
        self.save()
        self.assertEqual(athlete_queue.walk(self.now), [])
        self.assertEqual(athlete_queue.waiting_counts(), (0, 0))
        _code, out, _err = run_cli(["queue", "answer"])
        self.assertEqual(queue_lines(out), [])

    def test_it_goes_out_as_text_then_a_message_with_two_answers(self):
        item = self.save()
        _code, out, _err = run_cli(["queue", "answer", str(item["id"])])
        [sent] = queue_lines(out)
        self.assertEqual(sent["text"], saved_proposal.QUESTION_LINE)
        self.assertEqual([b["label"] for b in sent["buttons"]],
                         ["✅ Change it", "💪 Keep it as planned"])
        text = out[:out.index(QUEUE_SENTINEL)]
        self.assertIn("Rough night.", text)
        self.assertIn("Here's what I'd change:", text)
        self.assertIn("Easy ride", text)

    def test_a_tap_on_it_does_not_go_on_to_the_next_question(self):
        athlete_queue.tell("Charge your watch tonight.")
        _code, out, _err = run_cli(["queue", "answer", str(self.save()["id"])])
        [sent] = queue_lines(out)
        _code, out, _err = run_cli(
            ["bot", "queue", str(sent["id"]), "a2", "--since", sent["since"]]
        )
        self.assertEqual(queue_lines(out), [])

    def test_the_terminal_lists_it_and_answers_it_by_id(self):
        item = self.save()
        with patch.dict(os.environ, {"STAMIND_FRONTEND": "", "STAMIND_RENDER": ""}):
            _code, listed, _err = run_cli(["queue", "list"])
            prompt = MagicMock()
            prompt.choose.return_value = "a1"
            with patch.object(runtime, "prompt", prompt, create=True):
                run_cli(["queue", "answer", str(item["id"])])
        self.assertIn(f"#{item['id']}", listed)
        self.assertIn("Rough night.", listed)
        self.assertNotIn("Go through them", listed)
        self.assertIn("queue answer <id>", listed)
        _message, choices = prompt.choose.call_args.args
        self.assertEqual([c.value for c in choices], ["a1", "a2", athlete_queue.SKIP])
        self.assertEqual(self.ride()["duration_minutes"], 60)


class MorningPushTest(_Case):
    """With `adapt-first` on, the push proposes and writes no session change (§5, §7)."""

    def push(self, proposal):
        coach = MagicMock()
        coach.workout_adapt.return_value = proposal
        with patch.dict(config.data, {"telegram": {"push": {"adapt_first": True}}}), \
                patch.object(runtime, "coach_service", coach, create=True), \
                patch("stamind.cli.bot.views.ensure_recent_data"):
            code, out, _err = run_cli(["bot", "morning", "--force"])
        self.assertEqual(code, 0)
        return coach, out

    def test_a_session_that_would_change_is_proposed_and_nothing_is_written(self):
        coach, out = self.push(self.eased())
        coach.workout_revision_apply.assert_not_called()
        self.assertEqual(self.ride()["duration_minutes"], 90)
        self.assertIsNone(test_db.newest_adapt())
        # The briefing shows today as planned, with no reason line, then the proposal.
        briefing, proposal = out.split(BUTTONS_SENTINEL)
        self.assertIn("Intervals — 90 min", briefing)
        self.assertNotIn("Rough night.", briefing)
        self.assertIn("Rough night.", proposal)
        [sent] = queue_lines(out)
        self.assertEqual(sent["text"], saved_proposal.QUESTION_LINE)
        [item] = saved_proposal.waiting()
        self.assertEqual(item["payload"]["dates"], [THURSDAY])

    def test_the_proposal_comes_before_the_round_of_queued_questions(self):
        athlete_queue.tell("Charge your watch tonight.")
        _coach, out = self.push(self.eased())
        proposal, message = queue_lines(out)
        self.assertEqual(proposal["text"], saved_proposal.QUESTION_LINE)
        self.assertIn("Charge your watch tonight.", message["text"])

    def test_kilograms_that_moved_alone_are_written_at_once(self):
        proposal = self.eased(title="Intervals", minutes=90, week_planner_changed=False)
        coach, out = self.push(proposal)
        coach.workout_revision_apply.assert_called_once_with(proposal)
        self.assertIn("Rough night.", out)
        self.assertEqual(saved_proposal.waiting(), [])

    def test_a_saved_proposal_counts_as_this_mornings_run_whatever_its_answer(self):
        self.push(self.eased())
        [item] = saved_proposal.waiting()
        self.tap(item, "a2")
        self.at(8, 30)
        coach, _out = self.push(self.eased())
        coach.workout_adapt.assert_not_called()

    def test_a_proposal_made_without_the_sleep_score_does_not_count(self):
        saved_proposal.save(
            RevisionProposal(**{**self.eased().__dict__, "sleep_seen": False}),
            newest_written(),
        )
        self.at(8, 30)
        coach, _out = self.push(self.eased())
        coach.workout_adapt.assert_called_once()

    def test_the_push_is_shown_the_open_proposal_and_replaces_it(self):
        """Thursday evening's proposal about Saturday is still open on Friday at 08:00."""
        save_workout(test_db, SATURDAY, "cycling", "Long ride", duration_minutes=180)
        self.at(21)
        evening = self.save(day=SATURDAY)
        self.at(8, days=1)
        coach, _out = self.push(self.eased(day=SATURDAY, minutes=120))
        shown = coach.workout_adapt.call_args.kwargs
        self.assertTrue(shown["open_proposal"].startswith(
            f"Proposed on {THURSDAY}. The days it changes: {SATURDAY}.\n"
        ))
        self.assertEqual(shown["open_dates"], (SATURDAY,))
        self.assertEqual(self.outcome(evening), athlete_queue.STALE)
        [item] = saved_proposal.waiting()
        self.assertTrue(item["payload"]["text"].startswith(saved_proposal.REPLACES_LINE))


class ChatRunTest(_Case):
    """A run started from the chat saves its proposal and never asks (§2, §6.2, §7)."""

    def coach_run(
        self, proposal, argv=("workout", "adapt", "-m", "I'm tired"), on_confirm=None,
        think=None,
    ):
        """One run of the coach. `on_confirm` answers its questions, and `think` stands in
        for the week planner when something must happen while it thinks."""
        coach, prompt = MagicMock(), MagicMock()
        self.coach = coach
        coach.workout_adapt.return_value = proposal
        coach.workout_adapt.side_effect = think
        coach.workout_tweak.return_value = proposal
        coach.capture_message_constraint.return_value = (None, None)
        prompt.confirm.side_effect = on_confirm
        with patch.object(runtime, "coach_service", coach, create=True), \
                patch.object(runtime, "prompt", prompt, create=True), \
                patch("stamind.cli.workouts.adapt.ensure_recent_data"):
            code, out, _err = run_cli(list(argv))
        self.assertEqual(code, 0)
        return coach, prompt, out

    def nothing_to_change(self):
        return RevisionProposal(
            reason="All fine.", workouts=[], range_start=THURSDAY, range_end=THURSDAY,
        )

    def test_a_chat_run_saves_its_proposal_and_asks_nothing(self):
        coach, prompt, out = self.coach_run(self.eased())
        prompt.confirm.assert_not_called()
        coach.workout_revision_apply.assert_not_called()
        [sent] = queue_lines(out)
        self.assertEqual(sent["text"], saved_proposal.QUESTION_LINE)
        text = out[:out.index(QUEUE_SENTINEL)]
        self.assertEqual(text.count("Rough night."), 1)
        self.assertIn("Easy ride", text)
        [item] = saved_proposal.waiting()
        self.assertEqual(item["id"], sent["id"])

    def test_a_terminal_run_still_asks_and_writes(self):
        with patch.dict(os.environ, {"STAMIND_FRONTEND": "", "STAMIND_RENDER": ""}):
            coach, prompt, _out = self.coach_run(self.eased())
        prompt.confirm.assert_called_once()
        coach.workout_revision_apply.assert_called_once()
        self.assertEqual(saved_proposal.waiting(), [])

    def test_yes_writes_without_asking_wherever_it_was_typed(self):
        coach, prompt, _out = self.coach_run(self.eased(), ("workout", "adapt", "-y"))
        prompt.confirm.assert_not_called()
        coach.workout_revision_apply.assert_called_once()
        self.assertEqual(saved_proposal.waiting(), [])

    def test_kilograms_that_moved_alone_are_written_at_once(self):
        proposal = self.eased(title="Intervals", minutes=90, week_planner_changed=False)
        coach, prompt, out = self.coach_run(proposal)
        prompt.confirm.assert_not_called()
        coach.workout_revision_apply.assert_called_once_with(proposal)
        self.assertIn("Rough night.", out)
        self.assertEqual(saved_proposal.waiting(), [])

    def test_a_run_with_a_proposal_open_is_shown_it_and_replaces_it(self):
        """07:07 the coach proposes 60 easy minutes. 07:30: "no, shorten it instead"."""
        first = self.save()
        self.at(8, 30)
        coach, _prompt, out = self.coach_run(
            self.eased(title="Short intervals", minutes=45),
            ("workout", "tweak", "no, shorten it instead"),
        )
        shown = coach.workout_tweak.call_args.kwargs
        self.assertEqual(shown["open_proposal"], (
            f"Proposed on {THURSDAY}. The days it changes: {THURSDAY}.\n"
            + first["payload"]["text"]
        ))
        self.assertEqual(shown["open_dates"], (THURSDAY,))
        self.assertEqual(self.outcome(first), athlete_queue.STALE)
        [item] = saved_proposal.waiting()
        self.assertTrue(item["payload"]["text"].startswith(saved_proposal.REPLACES_LINE))
        self.assertIn(saved_proposal.REPLACES_LINE, out)

    def test_a_run_that_proposes_nothing_leaves_it_open(self):
        """"What's tomorrow's swim about?" must not withdraw the offer to ease today."""
        first = self.save()
        self.at(8, 30)
        self.coach_run(self.nothing_to_change())
        self.assertEqual([item["id"] for item in saved_proposal.waiting()], [first["id"]])

    RULE = ({"title": "no run on Fridays", "start_date": FRIDAY, "end_date": FRIDAY},)

    def test_in_the_chat_the_rule_question_comes_after_the_proposal(self):
        """A question nobody answers must not hold the proposal back (§6.1)."""
        waiting_when_asked = []

        def decline(*_args, **_kwargs):
            waiting_when_asked.append(len(saved_proposal.waiting()))
            return False

        self.coach_run(self.eased(new_constraints=self.RULE), on_confirm=decline)
        self.assertEqual(waiting_when_asked, [1])

    def test_with_nothing_to_change_the_rule_question_comes_after_that_line(self):
        recorded_when_asked = []

        def decline(*_args, **_kwargs):
            recorded_when_asked.append(self.coach.workout_revision_record_no_change.called)
            return False

        proposal = RevisionProposal(**{
            **self.nothing_to_change().__dict__, "new_constraints": self.RULE,
        })
        self.coach_run(proposal, on_confirm=decline)
        self.assertEqual(recorded_when_asked, [True])

    def test_a_terminal_run_keeps_the_rule_question_before_the_preview(self):
        with patch.dict(os.environ, {"STAMIND_FRONTEND": "", "STAMIND_RENDER": ""}):
            _coach, prompt, _out = self.coach_run(
                self.eased(new_constraints=self.RULE), on_confirm=lambda *a, **k: False
            )
        rule_question, apply_question = prompt.confirm.call_args_list
        self.assertIn("no run on Fridays", rule_question.args[0])
        self.assertNotIn("no run on Fridays", apply_question.args[0])

    def test_a_week_that_changed_while_the_coach_was_thinking_saves_nothing(self):
        """07:30 "also move Saturday's ride". At 07:30:30, while that run thinks, a tap on
        the 07:07 proposal writes a session (§6.2)."""
        def think(*_args, **_kwargs):
            save_workout(test_db, SATURDAY, "running", "Long run", duration_minutes=100)
            return self.eased()

        coach, _prompt, out = self.coach_run(None, think=think)
        self.assertIn(WEEK_CHANGED_LINE, out)
        self.assertEqual(saved_proposal.waiting(), [])
        coach.workout_revision_apply.assert_not_called()

    def test_kilograms_are_not_written_either_when_the_week_changed(self):
        def think(*_args, **_kwargs):
            save_workout(test_db, SATURDAY, "running", "Long run", duration_minutes=100)
            return self.eased(title="Intervals", minutes=90, week_planner_changed=False)

        coach, _prompt, out = self.coach_run(None, think=think)
        self.assertIn(WEEK_CHANGED_LINE, out)
        coach.workout_revision_apply.assert_not_called()

    def test_a_proposal_out_of_date_is_closed_and_not_shown(self):
        first = self.save()
        save_workout(test_db, SATURDAY, "running", "Long run", duration_minutes=100)
        self.at(8, 30)
        coach, _prompt, _out = self.coach_run(self.eased())
        self.assertNotIn("open_proposal", coach.workout_adapt.call_args.kwargs)
        self.assertEqual(self.outcome(first), athlete_queue.STALE)
        [item] = saved_proposal.waiting()
        self.assertFalse(item["payload"]["text"].startswith(saved_proposal.REPLACES_LINE))


if __name__ == "__main__":
    unittest.main()
