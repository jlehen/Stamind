"""Telling the athlete when the week changes out of their sight (DESIGN_change_heads_up.md).

The send rule and the notice's timing are pure and tested on fixed clocks. The rest runs
against a database, on a companion instance started from the terminal unless a test says
otherwise: which persona the operator's own config.yaml names must not decide these.
"""
import unittest
from contextlib import redirect_stdout
from datetime import datetime
from io import StringIO
from unittest.mock import patch

from tests.helpers import (
    as_instance, bind_test_db, clear_all_tables, pin_clock, rebind_test_db, run_cli,
)
from tests import test_db_path

test_db = bind_test_db(test_db_path("test_change_heads_up.db"))

from trainmate import heads_up, runtime
from trainmate.coach.proposals import RevisionProposal
from trainmate.clock import today_str


def _at(day: int, hour: int, minute: int = 0) -> datetime:
    """An instant in September 2026 on the local clock."""
    return datetime(2026, 9, day, hour, minute).astimezone()


def _waiting(change_id: int, made: datetime, touches_today: bool = False) -> dict:
    return {
        "id": change_id, "created_at": made.isoformat(), "touches_today": touches_today,
    }


class SendRuleTest(unittest.TestCase):
    """When the scheduler sends the waiting changes (§4). Morning time 08:00, and a change
    to today waits 20 minutes, the built-in default of the `change-delay` setting."""

    def due(self, waiting, now, notify_upto=None, delay=20):
        return heads_up.due(waiting, now, "08:00", notify_upto, delay)

    def test_nothing_waiting_sends_nothing(self):
        self.assertFalse(self.due([], _at(24, 8)))

    def test_a_change_to_another_day_waits_for_the_morning(self):
        """Wednesday 19:30 the test moves from Friday to Saturday."""
        change = [_waiting(7, _at(23, 19, 30))]
        self.assertFalse(self.due(change, _at(23, 20, 0)))
        self.assertFalse(self.due(change, _at(24, 7, 55)))
        self.assertTrue(self.due(change, _at(24, 8, 0)))

    def test_a_bot_down_at_the_morning_time_sends_when_it_comes_back(self):
        change = [_waiting(7, _at(23, 19, 30))]
        self.assertTrue(self.due(change, _at(24, 11, 40)))

    def test_nothing_is_sent_after_the_evening(self):
        change = [_waiting(7, _at(23, 19, 30))]
        self.assertFalse(self.due(change, _at(23, 21, 0)))

    def test_a_change_made_during_the_day_waits_for_the_next_morning(self):
        """12:30 Wednesday, Friday's session changes: only `workout notify` sends it
        sooner."""
        change = [_waiting(7, _at(23, 12, 30))]
        self.assertFalse(self.due(change, _at(23, 12, 50)))
        self.assertFalse(self.due(change, _at(23, 20, 55)))
        self.assertTrue(self.due(change, _at(24, 8, 0)))

    def test_a_change_to_today_goes_out_once_the_wait_is_up(self):
        """12:30 Wednesday, tonight's run is cut. Thursday 08:00 is after the run, so it
        goes out at 12:50 instead."""
        change = [_waiting(7, _at(23, 12, 30), touches_today=True)]
        self.assertFalse(self.due(change, _at(23, 12, 35)))
        self.assertTrue(self.due(change, _at(23, 12, 50)))

    def test_a_second_change_restarts_the_wait(self):
        """The operator is still working it out at 12:45, so nothing goes out at 12:50."""
        changes = [
            _waiting(7, _at(23, 12, 30), touches_today=True),
            _waiting(8, _at(23, 12, 45), touches_today=True),
        ]
        self.assertFalse(self.due(changes, _at(23, 12, 50)))
        self.assertTrue(self.due(changes, _at(23, 13, 5)))

    def test_a_delay_of_zero_sends_on_the_next_wake(self):
        change = [_waiting(7, _at(23, 12, 30), touches_today=True)]
        self.assertTrue(self.due(change, _at(23, 12, 31), delay=0))

    def test_a_change_to_today_still_stops_at_the_evening(self):
        """Past the evening the day is over, so it waits like any other change."""
        change = [_waiting(7, _at(23, 21, 30), touches_today=True)]
        self.assertFalse(self.due(change, _at(23, 21, 55)))
        self.assertTrue(self.due(change, _at(24, 8, 0)))

    def test_a_change_made_before_the_morning_time_goes_at_it(self):
        change = [_waiting(7, _at(23, 7, 50))]
        self.assertFalse(self.due(change, _at(23, 7, 55)))
        self.assertTrue(self.due(change, _at(23, 8, 0)))

    def test_a_later_change_goes_out_with_one_that_was_due(self):
        """The bot was down at 08:00; the operator changed something else at 10:00."""
        overnight = _waiting(6, _at(22, 22, 0))
        later = _waiting(7, _at(23, 10, 0))
        self.assertTrue(self.due([overnight, later], _at(23, 11, 0)))

    def test_notify_sends_at_once_whatever_the_hour_and_the_age(self):
        change = [_waiting(7, _at(23, 22, 0))]
        self.assertTrue(self.due(change, _at(23, 22, 2), notify_upto=7))

    def test_a_leftover_notify_does_not_send_a_newer_change_early(self):
        change = [_waiting(9, _at(23, 12, 0))]
        self.assertFalse(self.due(change, _at(23, 12, 30), notify_upto=7))


class NoticeTimingTest(unittest.TestCase):
    """What the terminal says about when the line goes out (§8)."""

    def test_after_the_morning_time_it_goes_tomorrow_morning(self):
        self.assertEqual(heads_up.sends_at(_at(23, 12, 30), "08:00"), _at(24, 8))
        self.assertEqual(heads_up.sends_at(_at(23, 22, 0), "08:00"), _at(24, 8))

    def test_before_the_morning_time_it_goes_this_morning(self):
        self.assertEqual(heads_up.sends_at(_at(23, 6, 0), "08:00"), _at(23, 8))

    def test_a_change_to_today_goes_out_after_the_wait(self):
        self.assertEqual(
            heads_up.sends_at(_at(23, 12, 30), "08:00", True, 20), _at(23, 12, 50)
        )

    def test_a_change_to_today_whose_wait_runs_past_the_evening_waits_for_the_morning(self):
        self.assertEqual(heads_up.sends_at(_at(23, 20, 50), "08:00", True, 20), _at(24, 8))

    def test_a_change_to_today_before_the_morning_time_goes_at_it(self):
        self.assertEqual(heads_up.sends_at(_at(23, 6, 0), "08:00", True, 20), _at(23, 8))


class _DbCase(unittest.TestCase):
    def setUp(self):
        rebind_test_db(test_db)
        clear_all_tables(test_db)
        pin_clock(self, "2026-09-23")
        calendar = patch("trainmate.runtime.calendar_syncer")
        calendar.start()
        self.addCleanup(calendar.stop)
        morning = patch("trainmate.settings.morning_time", return_value="08:00")
        morning.start()
        self.addCleanup(morning.stop)
        as_instance(self, "simple")

    def change(self, kind="generate", note="Friday's test moves to Saturday.",
               day=None, title="Ride"):
        """One change that wrote one session, and its id."""
        with test_db.workout_change(kind=kind, note=note, summary=note) as change:
            change.append(
                date=day or today_str(), sport_type="cycling", title=title,
                description="60 min.", duration_minutes=60,
            )
            return change.id


class WhoIsWatchingTest(_DbCase):
    """A change is told as it is written when the athlete watched the run (§6)."""

    def _adapt(self, reason="Friday becomes a rest day."):
        runtime.coach_service.workout_revision_apply(RevisionProposal(
            reason=reason, range_start=today_str(), range_end=today_str(),
            workouts=[{
                "date": today_str(), "sport_type": "running", "title": "Rest",
                "description": "Rest.", "modification_reason": "rain",
                "duration_minutes": 0, "rpe": 0, "tss": 0,
            }],
        ))

    def test_a_terminal_adapt_on_a_companion_instance_waits(self):
        self._adapt()
        [change] = test_db.waiting_changes()
        self.assertEqual((change["kind"], change["note"]), ("adapt", "Friday becomes a rest day."))

    def test_the_same_adapt_from_the_athletes_chat_is_told(self):
        as_instance(self, "simple", from_chat=True)
        self._adapt()
        self.assertEqual(test_db.waiting_changes(), [])

    def test_the_same_adapt_on_an_expert_instance_is_told(self):
        as_instance(self, "expert")
        self._adapt()
        self.assertEqual(test_db.waiting_changes(), [])
        self.assertEqual(heads_up.waiting(), [])

    def test_an_adapt_that_changed_nothing_has_no_line(self):
        proposal = RevisionProposal(
            reason="All green.", workouts=[], range_start=today_str(), range_end=today_str(),
        )
        runtime.coach_service.workout_revision_record_no_change(proposal)
        self.assertEqual(test_db.waiting_changes(), [])



class TouchesTodayTest(_DbCase):
    """`waiting()` marks the change that wrote one of today's sessions, which is what makes
    the scheduler send it without waiting for the next morning (§4)."""

    def test_only_the_change_that_wrote_today_is_marked(self):
        self.change(note="Tonight's lift is off.", day=today_str())
        self.change(note="Friday moves to Saturday.", day="2026-09-25", title="Long ride")
        marked = {c["note"]: c["touches_today"] for c in heads_up.waiting()}
        self.assertEqual(marked, {
            "Tonight's lift is off.": True, "Friday moves to Saturday.": False,
        })


class ReplaceQuestionTest(_DbCase):
    """A terminal run asks before building on an attempt the athlete never heard of (§5)."""

    def _answer(self, choice):
        prompt = patch.object(runtime.prompt, "choose", return_value=choice)
        self.choose = prompt.start()
        self.addCleanup(prompt.stop)

    def _run(self, skip=False, write=None, window=None):
        """A terminal run inside the question; `write` is what it writes, if anything.

        `window` is the days the run may write, open-ended from today by default, which is
        what `workout adapt` passes."""
        from trainmate.cli.workouts.heads_up import replacing_unsent
        out = StringIO()
        window = window or (today_str(), None)
        with redirect_stdout(out), replacing_unsent(skip, window) as replaced:
            if write:
                write()
        return replaced, out.getvalue()

    def test_replace_undoes_the_attempt_and_leaves_one_waiting_change(self):
        first = self.change(note="First attempt.")
        self._answer("replace")
        replaced, _out = self._run(
            write=lambda: self.change(note="Second attempt.", title="Long ride")
        )
        self.assertTrue(replaced)
        self.assertEqual(
            [c["note"] for c in test_db.waiting_changes()], ["Second attempt."]
        )
        self.assertFalse(test_db.change_has_live_revisions(first))

    def test_build_on_it_keeps_both(self):
        self.change(note="First attempt.")
        self._answer("build")
        self._run(write=lambda: self.change(note="Second attempt.", day="2026-09-25"))
        self.assertEqual(
            [c["note"] for c in test_db.waiting_changes()],
            ["First attempt.", "Second attempt."],
        )

    def test_a_run_that_then_writes_nothing_says_the_attempt_stays_undone(self):
        first = self.change(note="First attempt.")
        self._answer("replace")
        _replaced, out = self._run()
        self.assertIn("stays undone", out)
        self.assertIn("workout rollback", out)
        self.assertEqual(test_db.waiting_changes(), [])
        self.assertFalse(test_db.change_has_live_revisions(first))

    def test_a_run_that_fails_says_so_too(self):
        self.change(note="First attempt.")
        self._answer("replace")
        out = StringIO()
        from trainmate.cli.workouts.heads_up import replacing_unsent
        with self.assertRaises(RuntimeError), redirect_stdout(out):
            with replacing_unsent(False, (today_str(), None)):
                raise RuntimeError("LLM down")
        self.assertIn("stays undone", out.getvalue())

    def test_an_attempt_sent_while_the_question_waited_is_kept(self):
        first = self.change(note="First attempt.")

        def sent_meanwhile(*_args, **_kwargs):
            test_db.mark_changes_told([first])
            return "replace"

        prompt = patch.object(runtime.prompt, "choose", side_effect=sent_meanwhile)
        prompt.start()
        self.addCleanup(prompt.stop)
        replaced, out = self._run()
        self.assertFalse(replaced)
        self.assertIn("builds on it", out)
        self.assertTrue(test_db.change_has_live_revisions(first))

    def test_nothing_is_asked_with_yes(self):
        self.change()
        self._answer("replace")
        self._run(skip=True)
        self.choose.assert_not_called()

    def test_nothing_is_asked_on_an_expert_instance(self):
        self.change()
        as_instance(self, "expert")
        self._answer("replace")
        self._run()
        self.choose.assert_not_called()

    def test_nothing_is_asked_when_the_athletes_own_change_came_after(self):
        self.change(note="First attempt.")
        as_instance(self, "simple", from_chat=True)
        self.change(kind="adapt", note="Moved, as you asked.", day="2026-09-26")
        as_instance(self, "simple")
        self._answer("replace")
        self._run()
        self.choose.assert_not_called()

    def test_nothing_is_asked_once_the_attempt_was_sent(self):
        test_db.mark_changes_told([self.change()])
        self._answer("replace")
        self._run()
        self.choose.assert_not_called()

    def test_nothing_is_asked_when_the_run_leaves_the_unsent_days_alone(self):
        """The unsent adapt changed today. This run writes the mesocycle that opens
        tomorrow, so it overwrites nothing the adapt wrote and both lines are true."""
        self.change(kind="adapt", note="Today's lift is off.", day="2026-09-23")
        self._answer("replace")
        self._run(window=("2026-09-24", "2026-10-21"))
        self.choose.assert_not_called()

    def test_the_question_comes_back_once_the_run_reaches_those_days(self):
        self.change(kind="adapt", note="Today's lift is off.", day="2026-09-23")
        self._answer("build")
        self._run(window=("2026-09-23", "2026-10-21"))
        self.choose.assert_called_once()

    def test_the_question_names_the_change_by_kind_and_time(self):
        self.change(kind="adapt")
        self._answer("build")
        self._run()
        question = self.choose.call_args.args[0]
        self.assertIn("The newest change (adapt, ", question)
        self.assertNotIn("#", question)


class GenerateAfterReplaceTest(_DbCase):
    """`workout generate` around the replace question (§5)."""

    def setUp(self):
        super().setUp()
        goal = test_db.add_objective(
            title="Autumn Marathon", target_date="2026-12-20", sport_type="running",
        )
        test_db.save_macrocycle(
            objective_id=goal, strategy="build", goals_hash="g", constraints_hash="c",
            mesocycles=[{"name": "Base", "start_date": "2026-09-01",
                         "end_date": "2026-11-30", "focus": "aerobic"}],
        )
        for target in ("ensure_recent_data", "_confirm_out_of_date_plans"):
            patcher = patch(f"trainmate.cli.workouts.generate.{target}", return_value=True)
            patcher.start()
            self.addCleanup(patcher.stop)

    def test_it_never_claims_the_schedule_is_unchanged(self):
        first = self.change(note="First attempt.")
        reply = {"reasoning": "why", "workouts": [{
            "date": "2026-09-24", "sport_type": "running", "title": "Easy run",
            "description": "[Easy run]\n40 min easy.", "duration_minutes": 40,
            "rpe": 3, "tss": 30,
        }]}
        replace = patch.object(runtime.prompt, "choose", return_value="replace")
        with patch("trainmate.coach.engine.openrouter_client") as client, replace:
            client.complete.return_value = reply
            # The §5 choice gets "replace"; every confirm gets run_cli's "n".
            _code, out, _ = run_cli(["workout", "generate", "-d", "today..2026-09-27"])
        self.assertIn("Workouts discarded.", out)
        self.assertNotIn("unchanged", out)
        self.assertIn("stays undone", out)
        self.assertFalse(test_db.change_has_live_revisions(first))
        self.assertEqual(test_db.waiting_changes(), [])

    def test_a_span_that_opens_after_the_unsent_change_asks_nothing(self):
        """An unsent adapt changed today, and the operator then generates the sessions of
        the days after it. Nothing the adapt wrote is rewritten, so today's adaptation is
        never offered for undoing."""
        adapt = self.change(kind="adapt", note="Today's lift is off.", day="2026-09-23")
        reply = {"reasoning": "why", "workouts": [{
            "date": "2026-09-25", "sport_type": "running", "title": "Easy run",
            "description": "[Easy run]\n40 min easy.", "duration_minutes": 40,
            "rpe": 3, "tss": 30,
        }]}
        choose = patch.object(runtime.prompt, "choose", return_value="replace")
        with patch("trainmate.coach.engine.openrouter_client") as client, choose as ask:
            client.complete.return_value = reply
            run_cli(["workout", "generate", "-d", "2026-09-24..2026-09-27"])
        ask.assert_not_called()
        self.assertTrue(test_db.change_has_live_revisions(adapt))


class SendNoticeTest(_DbCase):
    """The line under the one the athlete will get (§8). The clock is pinned at 12:00."""

    def _notice(self, dates):
        from trainmate.cli.workouts.heads_up import print_send_notice
        out = StringIO()
        with redirect_stdout(out):
            print_send_notice(dates)
        return out.getvalue()

    def test_a_change_to_today_gives_the_hour_it_goes_out_at(self):
        """The clock is pinned at 12:00 and the wait is the default 20 minutes."""
        out = " ".join(self._notice({today_str(), "2026-09-25"}).split())
        self.assertIn("This changes today's session", out)
        self.assertIn("at 12:20 today, not tomorrow morning", out)
        self.assertIn("restarts those 20 minutes", out)
        self.assertIn("workout notify", out)

    def test_a_change_to_another_day_names_the_morning_time(self):
        out = " ".join(self._notice({"2026-09-25"}).split())
        self.assertIn("at 08:00 tomorrow", out)
        self.assertNotIn("today's session", out)

    def test_before_the_morning_time_a_change_to_today_goes_this_morning(self):
        with patch("trainmate.clock.now", return_value=_at(23, 6, 30)):
            out = " ".join(self._notice({"2026-09-23"}).split())
        self.assertIn("at 08:00 today", out)
        self.assertNotIn("today's session", out)

    def test_a_session_moved_out_of_today_counts_as_today(self):
        from trainmate.cli.workouts.heads_up import revision_dates
        from trainmate.coach.revisions import RevisionPair
        moved = {"date": "2026-09-26", "sport_type": "running"}
        proposal = RevisionProposal(
            reason="Rain.", workouts=[moved], range_start=today_str(),
            range_end="2026-09-30",
            pairs=(RevisionPair(proposal=moved, original={"date": today_str()},
                                is_swap=False),),
        )
        self.assertIn(today_str(), revision_dates(proposal))

    def test_nothing_on_an_expert_instance(self):
        as_instance(self, "expert")
        self.assertEqual(self._notice({today_str()}), "")

    def test_nothing_from_the_athletes_chat(self):
        as_instance(self, "simple", from_chat=True)
        self.assertEqual(self._notice({today_str()}), "")


class NotifyTest(_DbCase):
    """`workout notify` makes the scheduler send what waits on its next wake (§4)."""

    def test_it_lists_the_line_and_sends_on_the_next_wake(self):
        first = self.change(note="First.")
        second = self.change(note="Second.", day="2026-09-25")
        _code, out, _ = run_cli(["workout", "notify"], input_value="y")
        self.assertIn(f"{heads_up.CHANGE_LEAD} First.", out)
        self.assertIn(f"{heads_up.CHANGE_LEAD} Second.", out)
        self.assertEqual(test_db.get_setting(heads_up.NOTIFY_MARKER), str(second))
        self.assertLess(first, second)
        with patch("trainmate.clock.now", return_value=_at(23, 22, 30)):
            self.assertTrue(heads_up.changes_due())

    def test_declining_sends_nothing_early(self):
        self.change()
        run_cli(["workout", "notify"], input_value="n")
        self.assertIsNone(test_db.get_setting(heads_up.NOTIFY_MARKER))

    def test_nothing_waiting_says_so(self):
        _code, out, _ = run_cli(["workout", "notify"], input_value="y")
        self.assertIn("Nothing is waiting", out)
        self.assertIsNone(test_db.get_setting(heads_up.NOTIFY_MARKER))

    def test_an_expert_instance_says_so(self):
        as_instance(self, "expert")
        _code, out, _ = run_cli(["workout", "notify"], input_value="y")
        self.assertIn("not in companion mode", out)
        self.assertIsNone(test_db.get_setting(heads_up.NOTIFY_MARKER))

    def test_a_marker_left_by_a_rollback_does_not_send_the_next_change_early(self):
        undone = self.change(note="Undone before the wake.")
        run_cli(["workout", "notify"], input_value="y")
        test_db.rollback_to_change(undone, today_str(), summary="undo")
        self.change(note="The next change.", day="2026-09-25")
        with patch("trainmate.clock.now", return_value=_at(23, 22, 30)):
            self.assertFalse(heads_up.changes_due())


class BatchesTest(_DbCase):
    """`workout batches` says what each change was, and which ones wait (§8)."""

    def _rows(self):
        """Each listed change as (its row, the line under it)."""
        _code, out, _ = run_cli(["workout", "batches"])
        lines = out.splitlines()
        return [
            (line, lines[i + 1] if i + 1 < len(lines) else "")
            for i, line in enumerate(lines) if line.startswith("#")
        ]

    def test_each_row_says_what_the_change_was_and_whether_it_waits(self):
        test_db.mark_changes_told([self.change(note="Longer runs.")])
        self.change(note="Rest on Friday.", day="2026-09-25")
        (waiting, waiting_under), (told, told_under) = self._rows()
        self.assertIn("not sent yet", waiting)
        self.assertIn("Rest on Friday.", waiting_under)
        self.assertNotIn("not sent yet", told)
        self.assertIn("Longer runs.", told_under)

    def test_a_rollback_row_gets_no_description(self):
        undone = self.change(note="Rest on Friday.")
        test_db.rollback_to_change(undone, today_str(), summary="Undo of change #1 (generate).")
        (rollback, under), _undone = self._rows()
        self.assertIn("rollback", rollback)
        self.assertFalse(under.startswith(" "), under)
        self.assertNotIn("Undo of change", "\n".join(r + u for r, u in self._rows()))


if __name__ == "__main__":
    unittest.main()
