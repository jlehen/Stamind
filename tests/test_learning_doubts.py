"""The coach asks before it stops trusting what it learned (DESIGN_learning_doubt_nudge.md):
what a reflect run queues, the question's check, its answers, the switch that stops the
questions, and the sentence call."""
import os
import unittest
from datetime import datetime, timedelta, timezone
from unittest.mock import patch

from tests import test_db_path
from tests.helpers import clear_all_tables, rebind_test_db, run_cli

TEST_DB_PATH = test_db_path("test_learning_doubts.db")

from trainmate.db import Database
import trainmate_cli  # noqa: F401 — the CLI binds its handles at import, before the rebind

from trainmate import athlete_queue, learning_doubts, runtime, settings
from trainmate.cli import queue as queue_cli
from trainmate.cli.render import simple_queue_message
from trainmate.coach.service import coach_service
from trainmate.coach.service import CoachService
from trainmate.prompt import QUEUE_LATER_BACK, QUEUE_LATER_DAY, QUEUE_LATER_HOUR, QUEUE_SENTINEL

if os.path.exists(TEST_DB_PATH):
    os.remove(TEST_DB_PATH)
test_db = Database(db_path=TEST_DB_PATH)
rebind_test_db(test_db)


def tearDownModule():
    try:
        os.remove(TEST_DB_PATH)
    except OSError:
        pass


TEXT = "Responds well to back-to-back hard days."
STATEMENT = "You bounce back fine from two hard days in a row."
SAW = "But the last two times you had hard days back to back, you cut the second one short."
REASON = "HRV fell after both doubles and the second session was cut short."
WEEKS = ("2026-08-31", "2026-09-07")


def ids(items):
    return [item["id"] for item in items]


class _NoPrompt:
    """A run that queues its doubts asks nothing on the spot (§3.2)."""

    def choose(self, *args, **kwargs):
        raise AssertionError("asked on the spot")

    confirm = ask_text = choose


class _Picks:
    def __init__(self, picks):
        self.picks = list(picks)

    def choose(self, message, choices, *, default=None):
        return self.picks.pop(0) if self.picks else default


class _DoubtCase(unittest.TestCase):
    """A clean database, a clock the test moves, and the coach's sentences stubbed."""

    def setUp(self):
        rebind_test_db(test_db)
        clear_all_tables(test_db)
        self.now = datetime(2026, 9, 16, 3, 0).astimezone()
        moving_clock = patch("trainmate.clock.now", side_effect=lambda: self.now)
        moving_clock.start()
        self.addCleanup(moving_clock.stop)
        self.asked = []
        sentences = patch.object(coach_service, "learning_question", side_effect=self._sentences)
        sentences.start()
        self.addCleanup(sentences.stop)
        self.addCleanup(runtime.reset, "prompt")

    def _sentences(self, learning, reasons):
        self.asked.append((learning["id"], [row["reason"] for row in reasons]))
        if not reasons:
            return STATEMENT, None
        return STATEMENT, SAW

    def doubt(self, confidence="moderate", weeks=WEEKS, reason=REASON, text=TEXT):
        """A learning reflect doubts. At moderate (three supporting weeks) two contradicting
        weeks propose tentative; at tentative (one) a single week proposes retirement."""
        lid = test_db.add_learning(text, sports="cycling", confidence=confidence)
        test_db.apply_learning_deltas([
            {"op": "contradict", "id": lid, "evidence": list(weeks), "reason": reason},
        ])
        return lid

    def run_end(self):
        """The end of a reflect or bootstrap run."""
        coach_service._review_learning_proposals()

    def questions(self):
        return [item for item in test_db.waiting_queue_items()
                if item["kind"] == learning_doubts.KIND]

    def age(self, learning_id, days):
        old = (datetime.now(timezone.utc) - timedelta(days=days)).isoformat()
        with test_db._get_connection() as conn:
            conn.execute(
                "UPDATE coach_learnings SET last_reinforced_at=? WHERE id=?", (old, learning_id)
            )

    def later(self, **delta):
        self.now = self.now + timedelta(**delta)


class QueuingTest(_DoubtCase):
    def test_a_run_queues_one_question_per_pending_proposal_and_asks_nothing(self):
        demoted = self.doubt()
        retired = self.doubt(confidence="tentative", weeks=["2026-09-07"], text="Absorbs doubles.")
        test_db.add_learning("Sleeps well before long rides.", confidence="moderate")
        runtime.prompt = _NoPrompt()
        self.run_end()
        items = self.questions()
        self.assertEqual([item["payload"]["learning_id"] for item in items], [demoted, retired])
        first = items[0]["payload"]
        self.assertEqual((first["level"], first["step"]), ("moderate", "tentative"))
        self.assertEqual((first["statement"], first["saw"]), (STATEMENT, SAW))
        self.assertEqual(items[1]["payload"]["step"], "retire")

    @patch("trainmate.coach.engine.openrouter_client")
    def test_a_reflect_run_files_the_reason_and_queues_the_question(self, client):
        lid = test_db.add_learning(TEXT, sports="cycling", confidence="moderate")
        test_db.set_sync_state(
            through_date="2026-08-30", last_pull_utc="2026-08-30T00:00:00+00:00", key="reflect"
        )
        client.complete.return_value = {"macrocycle_summary": "s", "learning_updates": [
            {"op": "contradict", "id": lid, "evidence": list(WEEKS), "reason": REASON},
        ]}
        runtime.prompt = _NoPrompt()
        coach_service.data_reflect(until_date_str="2026-09-13", no_pull=True)
        [item] = self.questions()
        self.assertEqual(item["payload"]["reasons"], [
            {"weeks": ["2026-08-31", "2026-09-07"], "reason": REASON},
        ])
        self.assertEqual(self.asked, [(lid, [REASON])])

    def test_staleness_steps_apply_on_every_run(self):
        moderate = test_db.add_learning("Aging note", confidence="moderate")  # 60-day budget
        tentative = test_db.add_learning("Old note")                          # 21-day budget
        self.age(moderate, 90)
        self.age(tentative, 30)
        self.run_end()
        self.assertEqual(test_db.get_learning(moderate)["confidence"], "tentative")
        self.assertIsNone(test_db.get_learning(moderate)["proposed_confidence"])
        self.assertTrue(test_db.get_learning(tentative)["archived"])
        self.assertEqual(self.questions(), [])

    def test_no_second_question_while_one_waits_even_hidden(self):
        self.doubt()
        self.run_end()
        [item] = self.questions()
        athlete_queue.act(item, QUEUE_LATER_DAY, self.now)
        self.later(hours=1)
        self.assertTrue(athlete_queue.is_hidden(test_db.get_queue_item(item["id"]), self.now))
        self.run_end()
        self.assertEqual(ids(self.questions()), [item["id"]])
        self.assertEqual(len(self.asked), 1)

    def test_no_question_for_a_dormant_learning(self):
        lid = self.doubt()
        self.age(lid, 90)
        self.run_end()
        self.assertEqual(self.questions(), [])
        self.assertEqual(test_db.get_learning(lid)["proposed_confidence"], "tentative")

    def test_a_failed_sentence_call_queues_nothing_and_the_next_run_asks(self):
        self.doubt()
        with patch.object(coach_service, "learning_question",
                          side_effect=RuntimeError("model down")):
            self.run_end()
        self.assertEqual(self.questions(), [])
        self.later(days=1)
        self.run_end()
        self.assertEqual(len(self.questions()), 1)

    def test_the_reflect_command_ends_with_the_queue_hint(self):
        self.doubt()
        self.run_end()
        test_db.set_sync_state(
            through_date="2026-09-13", last_pull_utc="2026-09-14T00:00:00+00:00", key="reflect"
        )
        with patch.dict(os.environ, {}):
            os.environ.pop("TRAINMATE_FRONTEND", None)
            os.environ.pop("TRAINMATE_RENDER", None)
            code, out, _ = run_cli(["data", "reflect", "--auto", "--no-pull"])
        self.assertEqual(code, 0)
        self.assertIn("1 question is waiting for you.", out)


class CheckTest(_DoubtCase):
    """A question is checked before it is shown, when tapped, and before a new one is queued
    (§5)."""

    def test_a_question_that_no_longer_holds_is_closed_without_being_shown(self):
        settles = (
            ("kept by hand", test_db.keep_learning),
            ("archived", test_db.archive_learning),
            ("gone dormant", lambda lid: self.age(lid, 90)),
            ("questions off", lambda lid: settings.write(settings.LEARNING_QUESTIONS, "off")),
        )
        for name, settle in settles:
            with self.subTest(name):
                clear_all_tables(test_db)
                lid = self.doubt()
                self.run_end()
                [item] = self.questions()
                settle(lid)
                self.assertEqual(athlete_queue.walk(self.now), [])
                self.assertEqual(
                    test_db.get_queue_item(item["id"])["outcome"], athlete_queue.STALE
                )

    def test_a_changed_step_closes_the_question_and_asks_again_in_new_words(self):
        """A third contradicting week turns a demotion into a retirement: the waiting
        question promised to lean on it less, which Not really no longer does."""
        lid = self.doubt()
        self.run_end()
        [old] = self.questions()
        self.later(days=7)
        test_db.apply_learning_deltas([
            {"op": "contradict", "id": lid, "evidence": ["2026-09-14"], "reason": REASON},
        ])
        self.run_end()
        [new] = self.questions()
        self.assertEqual(test_db.get_queue_item(old["id"])["outcome"], athlete_queue.STALE)
        self.assertEqual(new["payload"]["step"], "retire")
        self.assertTrue(athlete_queue.wording(new, companion=True).endswith(
            "If it doesn't fit any more, or you're not sure, I'll set it aside."
        ))
        self.assertTrue(athlete_queue.wording(new).endswith("Not really archives it."))


class WordingTest(_DoubtCase):
    def test_the_companion_hears_what_the_coach_saw(self):
        self.doubt()
        self.run_end()
        [item] = self.questions()
        text, buttons = simple_queue_message(item, 1)
        self.assertEqual(text, (
            "🙋 Quick question (1 left)\n"
            "Something I've been assuming about you — tell me if it still fits: "
            f"“{STATEMENT}” {SAW} If it doesn't fit any more, or you're not sure, "
            "I'll lean on it less."
        ))
        self.assertEqual([b["label"] for b in buttons], ["Still fits", "Not really", "🕐 Not now"])

    def test_without_a_reason_the_question_says_it_is_less_sure(self):
        lid = self.doubt(reason=None)
        self.run_end()
        [item] = self.questions()
        self.assertEqual(self.asked, [(lid, [])])
        self.assertIn(f"“{STATEMENT}” Lately I'm less sure. If it",
                      athlete_queue.wording(item, companion=True))

    def test_the_expert_reads_the_learning_the_step_and_the_reasons(self):
        lid = self.doubt()
        self.run_end()
        [item] = self.questions()
        self.assertEqual(athlete_queue.wording(item).split("\n"), [
            f"Recent weeks contradict learning #{lid}: moderate → tentative.",
            f"[{lid}|cycling|moderate] {TEXT}",
            f"Weeks of 2026-08-31, 2026-09-07: {REASON}",
            "Still fits keeps it and overrules those weeks. Not really demotes it.",
        ])

    def test_the_question_offers_no_drop_and_refuses_one(self):
        self.doubt()
        self.run_end()
        [item] = self.questions()
        codes = [choice.value for choice in queue_cli.terminal_choices(item, self.now)]
        self.assertEqual(codes, [
            "a1", "a2", athlete_queue.SKIP, QUEUE_LATER_HOUR, QUEUE_LATER_DAY, QUEUE_LATER_BACK,
        ])
        athlete_queue.act(item, athlete_queue.DROP, self.now)
        self.assertIsNone(test_db.get_queue_item(item["id"])["closed_at"])


class AnswerTest(_DoubtCase):
    """A tap in the companion's chat runs one of the two answers (§4)."""

    def setUp(self):
        super().setUp()
        env = patch.dict(os.environ, {"TRAINMATE_FRONTEND": "json", "TRAINMATE_RENDER": "simple"})
        env.start()
        self.addCleanup(env.stop)

    def tap(self, item, action):
        since = queue_cli.since_token(self.now, single=True)
        code, out, _ = run_cli(["bot", "queue", str(item["id"]), action, "--since", since])
        self.assertEqual(code, 0)
        self.assertNotIn(QUEUE_SENTINEL, out)
        return out

    def test_still_fits_keeps_it_and_overrules_the_weeks(self):
        lid = self.doubt()
        self.run_end()
        [item] = self.questions()
        out = self.tap(item, "a1")
        self.assertIn("Thanks — good to know, I'll keep that in mind.", out)
        learning = test_db.get_learning(lid)
        self.assertEqual((learning["confidence"], learning["proposed_confidence"]),
                         ("moderate", None))
        self.assertFalse(any(row["polarity"] < 0 for row in test_db.get_learning_evidence(lid)))
        self.assertEqual(test_db.get_queue_item(item["id"])["outcome"], athlete_queue.ANSWERED)

    def test_not_really_leans_on_it_less_and_keeps_the_weeks(self):
        lid = self.doubt()
        self.run_end()
        [item] = self.questions()
        out = self.tap(item, "a2")
        self.assertIn("Got it — I'll lean on that less.", out)
        self.assertEqual(test_db.get_learning(lid)["confidence"], "tentative")
        contradicting = [row for row in test_db.get_learning_evidence(lid) if row["polarity"] < 0]
        self.assertEqual(len(contradicting), 2)

    def test_not_really_on_the_retirement_rung_sets_it_aside(self):
        lid = self.doubt(confidence="tentative", weeks=["2026-09-07"])
        self.run_end()
        [item] = self.questions()
        out = self.tap(item, "a2")
        self.assertIn("Got it — I've set that idea aside.", out)
        self.assertTrue(test_db.get_learning(lid)["archived"])
        self.assertNotIn(TEXT, coach_service._get_learnings_text())

    def test_a_tap_on_a_question_settled_meanwhile_says_so(self):
        lid = self.doubt()
        self.run_end()
        [item] = self.questions()
        test_db.keep_learning(lid)
        out = self.tap(item, "a2")
        self.assertIn(queue_cli.QUEUE_SETTLED_LINE, out)
        self.assertEqual(test_db.get_learning(lid)["confidence"], "moderate")


class TerminalAnswerTest(_DoubtCase):
    def setUp(self):
        super().setUp()
        env = patch.dict(os.environ, {})
        env.start()
        self.addCleanup(env.stop)
        os.environ.pop("TRAINMATE_FRONTEND", None)
        os.environ.pop("TRAINMATE_RENDER", None)

    def test_the_operator_answers_with_queue_answer(self):
        lid = self.doubt()
        self.run_end()
        runtime.prompt = _Picks(["a2"])
        code, out, _ = run_cli(["queue", "answer"])
        self.assertEqual(code, 0)
        self.assertIn(f"[{lid}|cycling|tentative]", out)
        self.assertIn("Learning demoted to 'tentative'.", out)


class SwitchTest(_DoubtCase):
    """`learning-questions off`: the coach settles its doubts by itself (§3.4)."""

    def test_off_queues_nothing_and_applies_the_proposals_on_a_run_that_read_nothing(self):
        demoted = self.doubt()
        retired = self.doubt(confidence="tentative", weeks=["2026-09-07"], text="Absorbs doubles.")
        settings.write(settings.LEARNING_QUESTIONS, "off")
        test_db.set_sync_state(
            through_date="2026-09-13", last_pull_utc="2026-09-14T00:00:00+00:00", key="reflect"
        )
        with patch("trainmate.coach.engine.openrouter_client") as client:
            result = coach_service.data_reflect(until_date_str="2026-09-13", no_pull=True)
            client.complete.assert_not_called()
        self.assertEqual(result, {})
        self.assertEqual(self.questions(), [])
        self.assertEqual(self.asked, [])
        self.assertEqual(test_db.get_learning(demoted)["confidence"], "tentative")
        self.assertTrue(test_db.get_learning(retired)["archived"])

    def test_turning_it_back_on_asks_the_next_doubt(self):
        settings.write(settings.LEARNING_QUESTIONS, "off")
        settings.write(settings.LEARNING_QUESTIONS, "on")
        self.doubt()
        self.run_end()
        self.assertEqual(len(self.questions()), 1)


class SentenceCallTest(unittest.TestCase):
    """`CoachService.learning_question`: one short call, prose only (§4)."""

    LEARNING = {"text": TEXT, "sports": "cycling"}

    @patch("trainmate.coach.engine.openrouter_client")
    def test_the_coach_writes_the_statement_and_what_it_saw(self, client):
        client.complete.return_value = {"statement": f" {STATEMENT} ", "saw": SAW}
        got = CoachService().learning_question(
            self.LEARNING, [{"weeks": ["2026-09-07"], "reason": REASON}]
        )
        self.assertEqual(got, (STATEMENT, SAW))
        system, user = client.complete.call_args[0][:2]
        self.assertIn("## TASK", system)
        self.assertIn(TEXT, user)
        self.assertIn(f"- {REASON}", user)
        self.assertEqual(client.complete.call_args[1]["label"], "learning_question")

    @patch("trainmate.coach.engine.openrouter_client")
    def test_without_a_reason_what_it_saw_is_dropped(self, client):
        client.complete.return_value = {"statement": STATEMENT, "saw": "But it invented this."}
        self.assertEqual(CoachService().learning_question(self.LEARNING, []), (STATEMENT, None))

    @patch("trainmate.coach.engine.openrouter_client")
    def test_an_answer_without_a_statement_is_a_failure(self, client):
        client.complete.return_value = {"macrocycle_summary": "not what was asked"}
        with self.assertRaises(ValueError):
            CoachService().learning_question(self.LEARNING, [])


if __name__ == "__main__":
    unittest.main()
