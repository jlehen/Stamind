"""Strength tracking, phase 1 (DESIGN_strength_tracking.md): the vocabulary, reading and
freezing a session's sets, the two naming questions, the three `strength` commands, and the
sets under the activity line."""
import json
import os
import unittest
from datetime import datetime
from unittest.mock import patch

from tests import test_db_path
from tests.helpers import clear_all_tables, rebind_test_db, run_cli, save_workout

TEST_DB_PATH = test_db_path("test_strength.db")

from stamind.db import Database
import stamind_cli  # noqa: F401 — the CLI binds its handles at import, before the rebind

from stamind import athlete_queue, runtime, settings
from stamind.cli.render.session_lines import simple_compare_lines
from stamind.garmin import sync
from stamind.sentinels import QUEUE_SENTINEL
from stamind.strength import questions, sets, vocabulary

if os.path.exists(TEST_DB_PATH):
    os.remove(TEST_DB_PATH)
test_db = Database(db_path=TEST_DB_PATH)
rebind_test_db(test_db)


def tearDownModule():
    try:
        os.remove(TEST_DB_PATH)
    except OSError:
        pass


# Wednesday 16 September, 08:00: the morning after Tuesday's gym session.
WEDNESDAY_8AM = datetime(2026, 9, 16, 8, 0).astimezone()
TUESDAY = "2026-09-15"


def lift(category, name=None, reps=10, kg=60.0):
    """One set as Garmin returns a person's pick: one candidate at 100%, the weight in grams."""
    return {
        "setType": "ACTIVE", "repetitionCount": reps, "duration": 30.0,
        "weight": None if kg is None else kg * 1000.0,
        "exercises": [{"category": category, "name": name, "probability": 100.0}],
    }


def guess(category, name=None, reps=10, kg=60.0, probability=64.0):
    """One set as the watch guessed it: ranked candidates below 100%."""
    entry = lift(category, name, reps, kg)
    entry["exercises"] = [
        {"category": category, "name": name, "probability": probability},
        {"category": "UNKNOWN", "name": None, "probability": 100.0 - probability},
    ]
    return entry


def unnamed(reps=10, kg=60.0):
    return guess("UNKNOWN", None, reps, kg, probability=99.6)


def garmin_sets(*entries):
    """A session's payload, with a rest entry after every set."""
    listed = []
    for entry in entries:
        listed.append(entry)
        listed.append({"setType": "REST", "duration": 90.0, "exercises": [],
                       "repetitionCount": None, "weight": None})
    return {"exerciseSets": listed}


def queue_lines(out):
    return [json.loads(line[len(QUEUE_SENTINEL):]) for line in out.split("\n")
            if line.startswith(QUEUE_SENTINEL)]


class FakeGarmin:
    """The sets endpoint, answering per activity; `down` makes every call fail."""

    def __init__(self):
        self.payloads = {}
        self.calls = []
        self.down = False

    def get_activity_exercise_sets(self, activity_id):
        self.calls.append(activity_id)
        if self.down:
            raise RuntimeError("garmin down")
        return self.payloads.get(activity_id, {"exerciseSets": []})


class _Prompt:
    """Picks what the script says, in order, and types `typed`."""

    def __init__(self, picks=(), typed=""):
        self.picks = list(picks)
        self.typed = typed
        self.shown = []

    def choose(self, message, choices, *, default=None):
        self.shown.append((message, [c.label for c in choices]))
        return self.picks.pop(0) if self.picks else default

    def ask_text(self, message, *, secret=False, default=None):
        return self.typed

    def confirm(self, message, *, default=False, danger=False):
        return default


class _StrengthCase(unittest.TestCase):
    def setUp(self):
        rebind_test_db(test_db)
        clear_all_tables(test_db)
        self.now = WEDNESDAY_8AM
        moving_clock = patch("stamind.clock.now", side_effect=lambda: self.now)
        moving_clock.start()
        self.addCleanup(moving_clock.stop)
        settings.write(settings.STRENGTH_SETS_SINCE, "2026-09-01")
        self.garmin = FakeGarmin()
        connect = patch("stamind.garmin.connect", return_value=self.garmin)
        connect.start()
        self.addCleanup(connect.stop)
        self.addCleanup(runtime.reset, "prompt")

    def activity(self, activity_id, day=TUESDAY, start="18:10:00",
                 type_key="strength_training", payload=None):
        test_db.save_completed_activity(
            activity_id=activity_id, date=day, start_time=f"{day} {start}",
            activity_name="Strength", activity_type=type_key, duration_sec=3600.0,
            distance_km=0.0, elevation_gain_m=0.0, avg_hr=None, max_hr=None,
            rpe=6, tss=None,
        )
        if payload is not None:
            self.garmin.payloads[activity_id] = payload
        return test_db.get_completed_activity(activity_id)

    def row(self, activity_id):
        return test_db.get_completed_activity(activity_id)

    def read(self):
        return sets.read_new_activities(self.garmin)

    def answer_final(self, activity_id="tue"):
        """Reads the sessions and answers "yes, final" to the question about one of them."""
        self.read()
        [item] = [i for i in test_db.waiting_queue_items() if i["subject"] == activity_id]
        return athlete_queue.act(item, "a1", self.now)

    def names_asked(self):
        return [i for i in test_db.waiting_queue_items() if i["kind"] == sets.SET_NAMES]


class VocabularyTest(unittest.TestCase):
    def test_every_exercise_has_a_known_pattern_and_equipment(self):
        for name in vocabulary.names():
            exercise = vocabulary.get(name)
            self.assertIn(exercise.pattern, vocabulary.PATTERNS, name)
            self.assertIn(exercise.equipment, vocabulary.EQUIPMENT, name)

    def test_every_garmin_name_means_one_exercise(self):
        seen = {}
        with open(vocabulary.TABLE_PATH, encoding="utf-8") as table:
            for line in table:
                if line.startswith("#") or not line.strip():
                    continue
                name, _pattern, _equipment, aliases = line.rstrip("\n").split("\t")
                for alias in aliases.split():
                    self.assertNotIn(alias, seen, f"{alias} means {seen.get(alias)} and {name}")
                    seen[alias] = name

    def test_the_names_a_watch_sent_are_in_it(self):
        """From the athlete's account on 2026-09-14: a name Connect has and the FIT SDK does
        not, a category with no exercise, and a weighted variant of a bodyweight exercise."""
        self.assertEqual(vocabulary.from_garmin("SQUAT/BELT_SQUAT"), "belt squat")
        self.assertEqual(vocabulary.from_garmin("ROW"), "row")
        self.assertEqual(vocabulary.from_garmin("PULL_UP/WEIGHTED_PULL_UP"), "pull up")
        self.assertEqual(vocabulary.get("sit up").equipment, vocabulary.BODYWEIGHT)


class ParseSetsTest(unittest.TestCase):
    def test_a_set_is_stored_in_kilograms_beside_its_rest(self):
        rows, unknown = sets.parse_sets(garmin_sets(lift("SQUAT", "BELT_SQUAT", reps=5, kg=140)))
        self.assertEqual([(row["seq"], row["set_type"]) for row in rows],
                         [(1, "active"), (2, "rest")])
        self.assertEqual((rows[0]["exercise"], rows[0]["reps"], rows[0]["load_kg"]),
                         ("belt squat", 5, 140.0))
        self.assertEqual(rows[0]["garmin_name"], "SQUAT/BELT_SQUAT")
        self.assertEqual(unknown, [])

    def test_no_weight_entered_is_no_load(self):
        """A dead bug comes back at -1 g, an ab twist with no weight at all."""
        minus_one = lift("HIP_STABILITY", "DEAD_BUG")
        minus_one["weight"] = -1.0
        rows, _ = sets.parse_sets(garmin_sets(minus_one, lift("BANDED_EXERCISES", "AB_TWIST",
                                                               kg=None)))
        self.assertEqual([row["load_kg"] for row in rows if row["set_type"] == "active"],
                         [None, None])

    def test_a_persons_pick_and_the_watchs_guess_are_told_apart(self):
        rows, _ = sets.parse_sets(garmin_sets(
            lift("PULL_UP", "LAT_PULLDOWN", kg=110), guess("DEADLIFT", "BARBELL_DEADLIFT", kg=80),
        ))
        self.assertEqual([row["named_by"] for row in rows if row["set_type"] == "active"],
                         [sets.GARMIN, sets.WATCH])

    def test_the_watch_guessing_a_bodyweight_exercise_at_a_heavy_load_names_nothing(self):
        rows, _ = sets.parse_sets(garmin_sets(guess("SIT_UP", kg=100)))
        self.assertEqual((rows[0]["exercise"], rows[0]["named_by"]), (None, None))
        self.assertEqual(rows[0]["garmin_name"], "SIT_UP")

    def test_a_person_picking_a_bodyweight_name_keeps_it_at_any_load(self):
        """The athlete files the pec deck under the suspension trainer's chest fly."""
        rows, _ = sets.parse_sets(garmin_sets(lift("SUSPENSION", "CHEST_FLY", kg=60)))
        self.assertEqual((rows[0]["exercise"], rows[0]["named_by"]), ("chest fly", sets.GARMIN))

    def test_a_category_without_an_exercise_is_the_category(self):
        rows, _ = sets.parse_sets(garmin_sets(lift("ROW", None, kg=120)))
        self.assertEqual(rows[0]["exercise"], "row")

    def test_a_name_the_vocabulary_lacks_is_stored_in_words_and_reported(self):
        rows, unknown = sets.parse_sets(garmin_sets(lift("SQUAT", "MOON_SQUAT")))
        self.assertEqual(rows[0]["exercise"], "moon squat")
        self.assertEqual(unknown, ["SQUAT/MOON_SQUAT"])

    def test_unnamed_sets_at_one_load_are_one_block_whatever_the_reps(self):
        rows, _ = sets.parse_sets(garmin_sets(
            lift("SQUAT", "LEG_PRESS", kg=140), unnamed(10, 60), unnamed(10, 60), unnamed(8, 60),
            unnamed(12, 30), lift("SQUAT", "LEG_PRESS", kg=140), unnamed(12, 30),
        ))
        found = sets.unnamed_groups(rows)
        self.assertEqual([(b.first, b.last, b.load_kg) for b in found],
                         [(2, 4, 60.0), (5, 5, 30.0), (7, 7, 30.0)])
        self.assertEqual(found[0].reps, [10, 10, 8])


class ReadingTest(_StrengthCase):
    def test_nothing_is_read_before_a_first_day_is_set(self):
        settings.clear(settings.STRENGTH_SETS_SINCE)
        self.activity("tue")
        self.assertEqual(self.read(), sets.SetsRead(None, []))
        self.assertEqual(self.garmin.calls, [])

    def test_only_strength_sessions_from_the_first_day_and_before_today_are_read(self):
        self.activity("tue")
        self.activity("today", day="2026-09-16")
        self.activity("august", day="2026-08-31")
        self.activity("warm-up", type_key="indoor_cardio")
        self.read()
        self.assertEqual(self.garmin.calls, ["tue"])

    def test_a_session_whose_sets_all_have_names_is_final_at_once(self):
        self.activity("tue", payload=garmin_sets(lift("SQUAT", "BELT_SQUAT"),
                                                 lift("PULL_UP", "LAT_PULLDOWN")))
        self.read()
        self.assertTrue(self.row("tue")["sets_read_at"])
        self.assertTrue(self.row("tue")["sets_final_at"])
        self.assertEqual(len(test_db.get_exercise_sets("tue")), 4)
        self.assertEqual(test_db.waiting_queue_items(), [])

    def test_a_recent_session_with_unnamed_sets_asks_whether_they_are_final(self):
        self.activity("tue", payload=garmin_sets(
            lift("SQUAT", "BELT_SQUAT"), unnamed(10, 60), unnamed(10, 60), unnamed(12, 30),
        ))
        self.read()
        self.assertTrue(self.row("tue")["sets_read_at"])
        self.assertIsNone(self.row("tue")["sets_final_at"])
        [item] = test_db.waiting_queue_items()
        self.assertEqual((item["kind"], item["subject"]), (sets.SETS_FINAL, "tue"))
        self.assertEqual(
            athlete_queue.wording(item),
            "Tue Sep 15 18:10 gym session: the watch couldn't name 2 groups "
            "(sets 2–3, 4). Are the sets in Garmin final?",
        )
        self.assertEqual(
            athlete_queue.wording(item, companion=True),
            "Tuesday's 18:10 gym session has 2 groups of sets the watch couldn't name. "
            "Are the sets in Garmin final?",
        )

    def test_a_recent_activity_the_watch_guessed_is_not_final_on_its_own(self):
        """September 3, 20:45: two guesses stand in an evening where nothing weighed more
        than 16 kg, so the activity waits for the athlete rather than freezing (§6)."""
        self.activity("tue", payload=garmin_sets(
            lift("SQUAT", "BELT_SQUAT"),
            guess("DEADLIFT", "BARBELL_DEADLIFT", 12, 16),
            guess("LATERAL_RAISE", "LATERAL_RAISE", 12, 16),
        ))
        self.read()
        self.assertIsNone(self.row("tue")["sets_final_at"])
        [item] = test_db.waiting_queue_items()
        self.assertEqual(
            athlete_queue.wording(item),
            "Tue Sep 15 18:10 gym session: the watch guessed 2 exercises "
            "(barbell deadlift, lateral raise). Are the sets in Garmin final?",
        )
        self.assertEqual(
            athlete_queue.wording(item, companion=True),
            "Tuesday's 18:10 gym session has 2 exercises the watch only guessed. "
            "Are the sets in Garmin final?",
        )
        self.assertEqual(athlete_queue.drop_label(item),
                         "no, leave it — the watch's names won't count")

    def test_both_halves_of_the_question_when_the_watch_guessed_and_gave_up(self):
        self.activity("tue", payload=garmin_sets(
            guess("DEADLIFT", "BARBELL_DEADLIFT", 12, 16), unnamed(10, 60),
        ))
        self.read()
        [item] = test_db.waiting_queue_items()
        self.assertEqual(
            athlete_queue.wording(item),
            "Tue Sep 15 18:10 gym session: the watch guessed 1 exercise "
            "(barbell deadlift) and couldn't name 1 group (set 2). "
            "Are the sets in Garmin final?",
        )
        self.assertEqual(
            athlete_queue.wording(item, companion=True),
            "Tuesday's 18:10 gym session has 1 exercise the watch only guessed and "
            "1 group of sets it couldn't name. Are the sets in Garmin final?",
        )

    def test_a_guess_counts_for_nothing_until_the_athlete_looks_at_it(self):
        self.activity("tue", payload=garmin_sets(guess("SQUAT", "BELT_SQUAT", 5, 140)))
        self.read()
        self.assertEqual(sets.recent_exercises(), [])

    def test_yes_final_makes_the_guesses_still_standing_the_athletes(self):
        self.activity("tue", payload=garmin_sets(
            guess("DEADLIFT", "BARBELL_DEADLIFT", 12, 16), unnamed(10, 60),
        ))
        self.answer_final()
        named = [(row["exercise"], row["named_by"])
                 for row in test_db.get_exercise_sets("tue") if row["set_type"] == "active"]
        self.assertEqual(named, [("barbell deadlift", "athlete"), (None, None)])
        self.assertEqual(sets.recent_exercises(), ["barbell deadlift"])

    def test_the_drop_leaves_the_guesses_guesses(self):
        self.activity("tue", payload=garmin_sets(guess("SQUAT", "BELT_SQUAT", 5, 140)))
        self.read()
        [item] = test_db.waiting_queue_items()
        athlete_queue.act(item, athlete_queue.DROP, self.now)
        self.assertEqual([row["named_by"] for row in test_db.get_exercise_sets("tue")
                          if row["set_type"] == "active"], ["watch"])
        self.assertEqual(sets.recent_exercises(), [])
        self.assertTrue(self.row("tue")["sets_final_at"])

    def test_an_old_session_is_frozen_as_read_and_asks_nothing(self):
        self.activity("old", day="2026-09-02", payload=garmin_sets(unnamed()))
        self.read()
        self.assertTrue(self.row("old")["sets_final_at"])
        self.assertEqual(test_db.waiting_queue_items(), [])

    def test_an_activity_that_returns_no_sets_is_not_a_session(self):
        self.activity("tue")
        self.read()
        self.assertEqual(test_db.get_exercise_sets("tue"), [])
        self.assertTrue(self.row("tue")["sets_final_at"])
        self.assertEqual(sets.activity_lines(self.row("tue")), [])

    def test_sets_are_read_once(self):
        self.activity("tue", payload=garmin_sets(unnamed()))
        self.read()
        self.read()
        self.assertEqual(self.garmin.calls, ["tue"])

    def test_a_later_pull_of_the_summary_leaves_the_read_alone(self):
        self.activity("tue", payload=garmin_sets(lift("SQUAT", "BELT_SQUAT")))
        self.read()
        read_at = self.row("tue")["sets_read_at"]
        self.activity("tue")
        self.assertEqual(self.row("tue")["sets_read_at"], read_at)
        self.assertEqual(len(test_db.get_exercise_sets("tue")), 2)

    def test_garmin_failing_stops_the_pass_and_leaves_the_session_unread(self):
        self.activity("tue")
        self.garmin.down = True
        result = self.read()
        self.assertIn("garmin down", result.failure)
        self.assertIsNone(self.row("tue")["sets_read_at"])

    def test_the_sets_go_with_their_activity(self):
        self.activity("tue", payload=garmin_sets(lift("SQUAT", "BELT_SQUAT")))
        self.read()
        test_db.prune_completed_activities(TUESDAY, TUESDAY, [])
        with test_db._get_connection() as conn:
            self.assertEqual(conn.execute("SELECT COUNT(*) FROM exercise_sets").fetchone()[0], 0)

    def test_a_pull_reads_the_sets_of_the_sessions_it_brought_in(self):
        class PullClient(FakeGarmin):
            def get_activities(self, start, end):
                return [{"activityId": "tue", "startTimeLocal": f"{TUESDAY} 18:10:00",
                         "activityType": {"typeKey": "strength_training"}, "duration": 3600.0,
                         "averageHR": None}]

            def get_activity_rpe(self, activity_id):
                return 6.0

        client = PullClient()
        client.payloads["tue"] = garmin_sets(lift("SQUAT", "BELT_SQUAT"))
        with patch.object(sync, "connect", return_value=client), patch("builtins.print"):
            sync.pull(TUESDAY, TUESDAY, metrics=False, advance_watermark=False)
        self.assertEqual(client.calls, ["tue"])
        self.assertTrue(self.row("tue")["sets_final_at"])


class SetsFinalTest(_StrengthCase):
    def setUp(self):
        super().setUp()
        self.activity("tue", payload=garmin_sets(
            lift("SQUAT", "BELT_SQUAT"), unnamed(10, 60), unnamed(10, 60), unnamed(12, 30),
        ))
        self.read()
        [self.item] = test_db.waiting_queue_items()

    def test_yes_final_reads_again_freezes_and_asks_the_names_still_missing(self):
        """She named the 30 kg group in Connect after the first read: the answer brings it in."""
        self.garmin.payloads["tue"] = garmin_sets(
            lift("SQUAT", "BELT_SQUAT"), unnamed(10, 60), unnamed(10, 60),
            lift("ROW", "SEATED_CABLE_ROW", 12, 30),
        )
        line = athlete_queue.act(self.item, "a1", self.now)
        self.assertEqual(line, "Sets read again and frozen. 1 group still without a name: "
                               "I'll ask about it next time.")
        self.assertEqual(test_db.get_queue_item(self.item["id"])["outcome"],
                         athlete_queue.ANSWERED)
        final_at = self.row("tue")["sets_final_at"]
        self.assertTrue(final_at)
        [names] = self.names_asked()
        self.assertEqual(names["subject"], f"tue:{final_at}:2-3")
        self.assertEqual(athlete_queue.wording(names),
                         "Tue Sep 15 18:10 gym session, sets 2–3: 10, 10 reps @ 60 kg. "
                         "What was it?")

    def test_garmin_out_of_reach_leaves_the_question_waiting(self):
        self.garmin.down = True
        line = athlete_queue.act(self.item, "a1", self.now)
        self.assertIn("nothing changed", line)
        self.assertIsNone(test_db.get_queue_item(self.item["id"])["closed_at"])
        self.assertIsNone(self.row("tue")["sets_final_at"])

    def test_leave_it_unnamed_asks_no_names(self):
        athlete_queue.act(self.item, athlete_queue.DROP, self.now)
        self.assertEqual(test_db.waiting_queue_items(), [])
        self.assertEqual(self.garmin.calls, ["tue"])

    def test_a_discard_settles_it(self):
        run_cli(["strength", "discard", TUESDAY])
        self.assertEqual(athlete_queue.walk(self.now), [])
        self.assertEqual(test_db.get_queue_item(self.item["id"])["outcome"], athlete_queue.STALE)

    def test_the_activity_going_settles_it(self):
        test_db.prune_completed_activities(TUESDAY, TUESDAY, [])
        self.assertEqual(athlete_queue.walk(self.now), [])


class SetNamesTest(_StrengthCase):
    def setUp(self):
        super().setUp()
        self.activity("sat", day="2026-09-12", payload=garmin_sets(
            lift("ROW", "SEATED_CABLE_ROW")))
        self.activity("sun", day="2026-09-13", payload=garmin_sets(
            lift("ROW", "SEATED_CABLE_ROW")))
        self.activity("mon", day="2026-09-14", payload=garmin_sets(
            lift("SQUAT", "LEG_PRESS"), lift("ROW", "SEATED_CABLE_ROW")))
        self.activity("tue", payload=garmin_sets(
            unnamed(10, 60), unnamed(8, 60), lift("SQUAT", "LEG_PRESS", kg=140), unnamed(12, 0),
            unnamed(15, None),
        ))
        self.answer_final()
        self.group, self.warm_up, self.no_weight = self.names_asked()

    def test_the_question_shows_the_whole_block(self):
        self.assertEqual(athlete_queue.wording(self.group),
                         "Tue Sep 15 18:10 gym session, sets 1–2: 10, 8 reps @ 60 kg. "
                         "What was it?")
        self.assertEqual(athlete_queue.wording(self.group, companion=True),
                         "Tuesday's 18:10 gym session, sets 1–2: 10, 8 reps at 60 kg. "
                         "What was it?")
        self.assertIn("set 4: 12 reps @ 0 kg", athlete_queue.wording(self.warm_up))
        self.assertIn("set 5: 15 reps, no weight entered", athlete_queue.wording(self.no_weight))

    def test_the_answers_are_the_recent_exercises_done_most_often_first(self):
        self.assertEqual([a["label"] for a in athlete_queue.answers(self.group)],
                         ["seated cable row", "leg press", "something else…"])

    def test_an_answer_names_every_set_of_the_block(self):
        line = athlete_queue.act(self.group, "a2", self.now)
        self.assertEqual(line, "Named sets 1–2: leg press.")
        named = [(row["exercise"], row["named_by"]) for row in test_db.get_exercise_sets("tue")
                 if row["seq"] in self.group["payload"]["seqs"]]
        self.assertEqual(named, [("leg press", "athlete")] * 2)

    def test_something_else_names_the_block_with_the_proposal_she_picks(self):
        runtime.prompt = _Prompt(picks=["pec deck"])
        with patch.object(questions, "propose", return_value=["pec deck", "chest fly"]):
            line = athlete_queue.act(self.group, "a3", self.now, text="butterfly machine")
        self.assertEqual(line, "Named sets 1–2: pec deck.")
        self.assertEqual(runtime.prompt.shown[0][1], ["pec deck", "chest fly", "none of these"])

    def test_none_of_the_proposals_leaves_the_question_waiting(self):
        runtime.prompt = _Prompt(picks=[questions.NONE_OF_THESE])
        with patch.object(questions, "propose", return_value=["pec deck"]):
            athlete_queue.act(self.group, "a3", self.now, text="butterfly machine")
        with patch.object(questions, "propose", return_value=[]):
            line = athlete_queue.act(self.group, "a3", self.now, text="zzz")
        self.assertIn("Nothing named", line)
        self.assertIsNone(test_db.get_queue_item(self.group["id"])["closed_at"])
        self.assertIsNone(test_db.get_exercise_sets("tue")[0]["exercise"])

    def test_a_proposal_is_only_ever_a_name_the_vocabulary_has(self):
        with patch("stamind.openrouter.openrouter_client.complete",
                   return_value={"names": ["Pec Deck", "nordic curl", 7, "pec deck",
                                           "chest fly", "leg press"]}):
            self.assertEqual(questions.propose("butterfly machine"),
                             ["pec deck", "chest fly", "leg press"])

    def test_a_name_given_another_way_settles_the_question(self):
        test_db.name_exercise_sets("tue", self.group["payload"]["seqs"][:1], "leg press")
        self.assertNotIn(self.group["id"], [i["id"] for i in athlete_queue.walk(self.now)])


class CommandsTest(_StrengthCase):
    def setUp(self):
        super().setUp()
        os.environ.pop("STAMIND_FRONTEND", None)
        self.activity("mon", day="2026-09-14", payload=garmin_sets(lift("SQUAT", "LEG_PRESS")))

    def test_name_splits_a_block_and_asks_the_rest_again(self):
        self.activity("tue", payload=garmin_sets(*[unnamed(10, 60)] * 4))
        self.read()
        runtime.prompt = _Prompt(picks=["a1", "2", "keep"])
        code, out, _ = run_cli(["strength", "name", TUESDAY])
        self.assertEqual(code, 0)
        self.assertIn("Named sets 1–2: leg press.", out)
        self.assertEqual([row["exercise"] for row in test_db.get_exercise_sets("tue")
                          if row["set_type"] == "active"],
                         ["leg press", "leg press", None, None])
        self.assertIn("sets 3–4: 10, 10 reps @ 60 kg, unnamed", runtime.prompt.shown[-1][0])
        # Naming by hand declares the sets final, so "are they final?" is settled.
        self.assertTrue(self.row("tue")["sets_final_at"])
        self.assertEqual(athlete_queue.walk(self.now), [])

    def test_keeping_a_guess_in_name_confirms_it(self):
        self.activity("tue", payload=garmin_sets(guess("SQUAT", "BELT_SQUAT", 5, 140)))
        self.read()
        runtime.prompt = _Prompt(picks=["keep"])
        _, out, _ = run_cli(["strength", "name", TUESDAY])
        self.assertIn("Set 1 confirmed: belt squat.", out)
        self.assertEqual([row["named_by"] for row in test_db.get_exercise_sets("tue")
                          if row["set_type"] == "active"], ["athlete"])

    def test_reset_makes_the_guesses_still_standing_the_athletes(self):
        self.activity("tue", payload=garmin_sets(guess("SQUAT", "BELT_SQUAT", 5, 140)))
        self.read()
        code, _, _ = run_cli(["strength", "reset", TUESDAY])
        self.assertEqual(code, 0)
        self.assertEqual([row["named_by"] for row in test_db.get_exercise_sets("tue")
                          if row["set_type"] == "active"], ["athlete"])

    def test_reset_reads_again_and_asks_anew(self):
        self.activity("tue", payload=garmin_sets(unnamed(10, 60), unnamed(12, 30)))
        self.answer_final()
        first, _ = self.names_asked()
        athlete_queue.act(first, "a1", self.now)
        self.now = WEDNESDAY_8AM.replace(hour=9)
        code, out, _ = run_cli(["strength", "reset", TUESDAY])
        self.assertEqual(code, 0)
        self.assertIn("2 groups without a name", " ".join(out.split()))
        self.assertEqual([row["exercise"] for row in test_db.get_exercise_sets("tue")
                          if row["set_type"] == "active"], [None, None])
        subjects = [item["subject"] for item in athlete_queue.walk(self.now)]
        final_at = self.row("tue")["sets_final_at"]
        self.assertEqual(subjects, [f"tue:{final_at}:1-1", f"tue:{final_at}:2-2"])

    def test_reset_refuses_a_day_before_the_first_day(self):
        self.activity("aug", day="2026-08-20")
        code, out, _ = run_cli(["strength", "reset", "2026-08-20"])
        self.assertIn("before strength-sets-since", out)
        self.assertEqual(self.garmin.calls, [])

    def test_discard_and_undo(self):
        self.read()
        run_cli(["strength", "discard", "2026-09-14"])
        self.assertEqual(self.row("mon")["discarded"], 1)
        self.assertEqual(sets.recent_exercises(), [])
        code, out, _ = run_cli(["strength", "discard", "2026-09-14", "--undo"])
        self.assertIn("back in the strength history", out)
        self.assertEqual(sets.recent_exercises(), ["leg press"])

    def test_reset_on_a_day_with_two_sessions_reads_the_one_picked(self):
        self.activity("am", start="09:00:00", payload=garmin_sets(lift("SQUAT", "LEG_PRESS")))
        self.activity("pm", start="20:10:00", payload=garmin_sets(lift("ROW", "SEATED_CABLE_ROW")))
        self.read()
        self.garmin.calls = []
        runtime.prompt = _Prompt(picks=["pm"])
        code, _, _ = run_cli(["strength", "reset", TUESDAY])
        self.assertEqual(code, 0)
        self.assertEqual(runtime.prompt.shown, [(
            "2026-09-15 Tue has 2 strength activities. Which one?",
            ["Tue Sep 15 09:00 gym session", "Tue Sep 15 20:10 gym session", "all of them",
             "none"],
        )])
        self.assertEqual(self.garmin.calls, ["pm"])

    def test_discard_on_a_day_with_two_sessions_leaves_the_other_alone(self):
        self.activity("am", start="09:00:00", payload=garmin_sets(lift("SQUAT", "LEG_PRESS")))
        self.activity("pm", start="20:10:00", payload=garmin_sets(lift("ROW", "SEATED_CABLE_ROW")))
        self.read()
        runtime.prompt = _Prompt(picks=["pm"])
        _, out, _ = run_cli(["strength", "discard", TUESDAY])
        self.assertIn("Discarded the Tue Sep 15 20:10 gym session.", out)
        self.assertIn("still counts as training", out)
        self.assertEqual((self.row("am")["discarded"], self.row("pm")["discarded"]), (0, 1))
        # Enter picks "none": nothing is brought back.
        runtime.prompt = _Prompt()
        _, out, _ = run_cli(["strength", "discard", TUESDAY, "--undo"])
        self.assertIn("Nothing changed.", out)
        self.assertEqual(self.row("pm")["discarded"], 1)


class ShownTest(_StrengthCase):
    def test_each_exercise_is_one_line_even_when_two_alternate(self):
        self.activity("sun", day="2026-09-13", payload=garmin_sets(
            lift("SQUAT", "BELT_SQUAT", 5, 120),
            lift("SHOULDER_PRESS", "BARBELL_PUSH_PRESS", 5, 60),
            lift("SQUAT", "BELT_SQUAT", 5, 140),
            lift("SHOULDER_PRESS", "BARBELL_PUSH_PRESS", 4, 70),
            unnamed(10, 20), guess("DEADLIFT", "BARBELL_DEADLIFT", 4, 80),
            guess("DEADLIFT", "BARBELL_DEADLIFT", 4, 80),
        ))
        self.read()
        self.assertEqual(sets.activity_lines(self.row("sun")), [
            "belt squat 1×5 @ 120, 1×5 @ 140",
            "barbell push press 1×5 @ 60, 1×4 @ 70",
            "barbell deadlift 2×4 @ 80 (watch)",
            "set 5 unnamed",
        ])

    def test_a_session_not_read_yet_says_so_and_one_before_the_first_day_says_nothing(self):
        self.assertEqual(sets.activity_lines(self.activity("tue")), [sets.SETS_NOT_READ])
        self.assertEqual(sets.activity_lines(self.activity("aug", day="2026-08-20")), [])

    def test_a_discarded_session_says_so(self):
        self.activity("sun", day="2026-09-13", payload=garmin_sets(lift("SQUAT", "LEG_PRESS")))
        self.read()
        test_db.set_activity_discarded("sun", True)
        self.assertEqual(sets.activity_lines(self.row("sun"))[-1],
                         "discarded: counts as training, not for planning weights")

    def test_workout_compare_and_done_lately_show_the_sets(self):
        activity = self.activity("tue", payload=garmin_sets(lift("SQUAT", "LEG_PRESS", 10, 140)))
        self.read()
        os.environ.pop("STAMIND_RENDER", None)
        _, out, _ = run_cli(["workout", "compare", "-d", TUESDAY, "--no-pull", "--no-mark"])
        self.assertIn("leg press 1×10 @ 140", out)
        lines = simple_compare_lines([(TUESDAY, [], [self.row("tue")])], TUESDAY, TUESDAY,
                                     "2026-09-16")
        self.assertIn("      leg press 1×10 @ 140", lines)
        self.assertTrue(activity)


class LogTest(_StrengthCase):
    """`strength log` reads the record back, `strength exercises` the vocabulary behind
    it (§7)."""

    def setUp(self):
        super().setUp()
        os.environ.pop("STAMIND_FRONTEND", None)
        self.activity("sun", day="2026-09-13", payload=garmin_sets(
            lift("SQUAT", "BELT_SQUAT", 5, 120),
            lift("SQUAT", "BELT_SQUAT", 5, 140),
            lift("SQUAT", "GOBLET_SQUAT", 12, 16),
            unnamed(10, 55),
        ))
        # Monday at the gym twice: a split session is one session (§3).
        self.activity("mon-am", day="2026-09-14", start="08:00:00", payload=garmin_sets(
            lift("SQUAT", "BELT_SQUAT", 5, 145),
        ))
        self.activity("mon-pm", day="2026-09-14", start="18:00:00", payload=garmin_sets(
            guess("DEADLIFT", "BARBELL_DEADLIFT", 4, 80),
        ))
        self.read()

    def test_a_lifts_sessions_read_oldest_first(self):
        _, out, _ = run_cli(["strength", "log", "belt squat"])
        self.assertIn("BELT SQUAT — squat, machine", out)
        self.assertIn("2026-09-13 Sun   1×5 @ 120, 1×5 @ 140", out)
        self.assertIn("2026-09-14 Mon   1×5 @ 145", out)
        self.assertLess(out.index("2026-09-13"), out.index("2026-09-14"))

    def test_a_name_only_the_watch_guessed_is_marked(self):
        _, out, _ = run_cli(["strength", "log", "barbell deadlift"])
        self.assertIn("2026-09-14 Mon   1×4 @ 80 (watch)", out)

    def test_the_index_counts_sessions_by_day_and_skips_unnamed_sets(self):
        _, out, _ = run_cli(["strength", "log"])
        self.assertIn("YOUR LIFTS — 3 exercises over 2 sessions", out)
        self.assertIn("belt squat", out)
        self.assertNotIn("unnamed", out)
        # Grouped by movement pattern, the two squats under one heading and the pull under
        # its own.
        self.assertLess(out.index("squat\n"), out.index("hinge\n"))
        self.assertIn("2 sessions, last 2026-09-14 Mon", out)

    def test_a_pattern_groups_the_lifts_and_never_merges_them(self):
        _, out, _ = run_cli(["strength", "log", "--pattern", "squat"])
        self.assertIn("BELT SQUAT — squat, machine", out)
        self.assertIn("GOBLET SQUAT — squat, dumbbell", out)
        self.assertNotIn("DEADLIFT", out)
        # One 140 kg belt squat and one 16 kg goblet squat, never one squat series.
        self.assertIn("1×12 @ 16", out)
        self.assertNotIn("1×5 @ 140, 1×12 @ 16", out)

    def test_part_of_a_name_finds_the_lifts_it_is_part_of(self):
        _, out, _ = run_cli(["strength", "log", "SQUAT"])
        self.assertIn("BELT SQUAT", out)
        self.assertIn("GOBLET SQUAT", out)
        self.assertNotIn("DEADLIFT", out)

    def test_a_name_off_the_record_says_where_to_look(self):
        _, out, _ = run_cli(["strength", "log", "bicep curl"])
        self.assertIn("No lift on record is called 'bicep curl'", out)
        self.assertIn("strength exercises", out)

    def test_a_discarded_session_is_off_the_record(self):
        # Monday is two activities, so discard asks which; "all of them" takes the day.
        runtime.prompt = _Prompt(picks=["all"])
        run_cli(["strength", "discard", "2026-09-14"])
        _, out, _ = run_cli(["strength", "log", "belt squat"])
        self.assertIn("2026-09-13 Sun", out)
        self.assertNotIn("2026-09-14", out)
        _, out, _ = run_cli(["strength", "log"])
        self.assertIn("YOUR LIFTS — 2 exercises over 1 session", out)

    def test_an_empty_record_says_how_it_fills(self):
        clear_all_tables(test_db)
        settings.write(settings.STRENGTH_SETS_SINCE, "2026-09-01")
        _, out, _ = run_cli(["strength", "log"])
        self.assertIn("No named sets on record since 2026-09-01", out)

    def test_the_patterns_list_the_vocabulary_and_what_is_on_the_record(self):
        _, out, _ = run_cli(["strength", "exercises"])
        for pattern in vocabulary.PATTERNS:
            self.assertIn(pattern, out)
        self.assertIn(f"{len(vocabulary.all_exercises())} exercises Stamind can name", out)
        self.assertIn("2 on your record", out)  # belt squat and goblet squat

    def test_one_pattern_lists_its_exercises_and_marks_the_athletes_own(self):
        _, out, _ = run_cli(["strength", "exercises", "--pattern", "squat"])
        lines = [line for line in out.split("\n") if "goblet squat" in line]
        self.assertTrue(any(line.strip().startswith("•") for line in lines))
        self.assertIn("barbell back squat", out)
        self.assertNotIn("barbell deadlift", out)

    def test_a_search_crosses_the_patterns(self):
        _, out, _ = run_cli(["strength", "exercises", "deadlift"])
        self.assertIn("barbell deadlift", out)
        self.assertIn("hinge", out)
        self.assertNotIn("belt squat", out)

class MorningPushTest(_StrengthCase):
    """The push reads new sets before its walk, so the question comes with it (§11)."""

    def setUp(self):
        super().setUp()
        ensure = patch("stamind.garmin.ensure_data")
        ensure.start()
        self.addCleanup(ensure.stop)
        env = patch.dict(os.environ, {"STAMIND_FRONTEND": "json",
                                      "STAMIND_RENDER": "simple"})
        env.start()
        self.addCleanup(env.stop)
        test_db.set_setting("push_adapt_first", "off")

    def test_the_question_about_yesterdays_sets_follows_the_briefing(self):
        save_workout(test_db, "2026-09-16", "running", "Easy run", description="40 min.",
                     duration_minutes=40)
        self.activity("tue", payload=garmin_sets(lift("SQUAT", "BELT_SQUAT"), unnamed()))
        code, out, _ = run_cli(["bot", "morning"])
        self.assertEqual(code, 0)
        [item] = queue_lines(out)
        self.assertIn("Tuesday's 18:10 gym session has 1 group of sets the watch couldn't "
                      "name.", item["text"])
        self.assertEqual([b["label"] for b in item["buttons"]],
                         ["Yes, final", "No, leave it unnamed", "🕐 Not now"])


if __name__ == "__main__":
    unittest.main()
