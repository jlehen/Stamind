"""The pages' files in the bucket (DESIGN_miniapp_storage.md): the recipe both languages
hold, the files built from the database, the step after every command, the two commands
and their guard, the button and the status line. Google is an in-memory bucket here.
"""
import base64
import json
import os
import unittest
from datetime import datetime
from types import SimpleNamespace
from unittest.mock import patch

from tests import test_db_path
from tests.helpers import (
    clear_all_tables, pin_clock, rebind_test_db, run_cli, save_workout, started_from,
)

from stamind import calendar_days
from stamind.cli import status
from stamind.cli.data import publish
from stamind.cli.render import calendar_page
from stamind.config import config
from stamind.db import Database
from stamind.page_files import bucket, recipe, sync

TEST_DB_PATH = test_db_path("test_page_files.db")
test_db = Database(db_path=TEST_DB_PATH)
rebind_test_db(test_db)

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
TODAY = "2026-09-30"
TOKEN = "123456789:AAFakeTokenForTheTestsOnly"
BUCKET = "stamind-pages"
FOLDER = "123456789"

# One example both languages open: `miniapp/tests/storage.test.mjs` holds the same three.
KEY = "IiDj40QCoCdJWU3MtQSdXiIUxAfdHa2tsSjfchSeSAg"
SEPTEMBER = "e1e44c0cd3c43d90cc87728e35c3f0e9"
BLOB = ("Tpon53mKKQfBlovsF9sQxlNkm8jRYsUCh1PTsdNyd5/5EeXX5sL7WTRERu+/F1xZuu8m8LVIedBKY0vLwHC+T1m"
        "QMgUBBssllEOSdH7P4ILDwB5FheWS2005KBo2NoDMfrZh3UrCDP7D+6mh4KGdOjZZMYxjlIP5HLsXZ9noL8FxZZT"
        "Z35XCaIcKu15NR/SAXfxWCKK5F2rPconycyjRcCeMb2M=")
CONTENT = {"v": 1, "days": {"2026-09-22": {
    "x": [{"i": "🏃", "g": "ok"}], "u": [], "c": 0, "s": 0,
    "sheet": [["Planned", ["🏃 Easy run — 50 min", "Easy run in zone 2."]]]}}}

# A workout text with a line longer than any terminal, so wrapping would show.
EASY_TEXT = ("Easy run in zone 2, at a pace where a whole sentence comes out without a breath "
             "in the middle of it.\n\n- 10 min warm-up\n- 30 min steady")


def _read(*parts):
    with open(os.path.join(REPO, *parts), encoding="utf-8") as handle:
        return handle.read()


class FakeBucket:
    """The bucket in memory. Every instance shares `files`, keyed by (bucket, folder,
    name), and `uploads` lists each upload's name in order."""
    files = {}
    uploads = []
    failing = False
    listable = False

    def __init__(self, name, folder):
        self.name = name
        self.folder = folder

    @classmethod
    def reset(cls):
        cls.files, cls.uploads, cls.failing, cls.listable = {}, [], False, False

    def sign_in(self):
        pass

    def upload(self, name, data, seconds=bucket.SECONDS):
        if FakeBucket.failing:
            raise bucket.BucketError(503)
        FakeBucket.files[(self.name, self.folder, name)] = data
        FakeBucket.uploads.append(name)

    def download(self, name, origin):
        data = FakeBucket.files.get((self.name, self.folder, name))
        return SimpleNamespace(status_code=200 if data else 404, content=data,
                               headers={"Access-Control-Allow-Origin": origin})

    def names(self):
        return [n for (b, f, n) in FakeBucket.files if (b, f) == (self.name, self.folder)]

    def open_to_listing(self):
        return FakeBucket.listable

    def delete(self, name):
        FakeBucket.files.pop((self.name, self.folder, name), None)


def use_storage(testcase, token=TOKEN, bucket_name=BUCKET):
    """Pins the bucket and the bot token for one test, with the in-memory bucket."""
    google = {**(config.data.get("google") or {}), "storage_bucket": bucket_name}
    telegram = {**(config.data.get("telegram") or {}), "bot_token": token}
    patchers = [
        patch.dict(config.data, {"google": google, "telegram": telegram}),
        patch.dict(os.environ),
        patch.object(bucket, "Bucket", FakeBucket),
        patch.object(publish, "WRITE_GAP_SECONDS", 0),
    ]
    for patcher in patchers:
        patcher.start()
        testcase.addCleanup(patcher.stop)
    os.environ.pop("TELEGRAM_BOT_TOKEN", None)
    # The step after a command says what it uploaded; a test that reads the line unsets this.
    os.environ["STAMIND_VERBOSE"] = "0"


def the_month():
    """A goal in October, two mesocycles and one that ended on 1 September, a run with a
    long text, and an activity in May, the first day of the history."""
    goal = test_db.add_objective(title="Autumn 10k", target_date="2026-10-18",
                                 sport_type="running")
    test_db.save_macrocycle(
        objective_id=goal, strategy="s", goals_hash="h", constraints_hash="c",
        mesocycles=[
            {"name": "Summer", "start_date": "2026-08-01", "end_date": "2026-09-01",
             "focus": "Keep moving."},
            {"name": "Build", "start_date": "2026-09-02", "end_date": "2026-09-27",
             "focus": "Build the engine.\n\nMost of it easy, one quality day a week."},
            {"name": "Taper", "start_date": "2026-09-28", "end_date": "2026-10-18",
             "focus": "Arrive fresh."},
        ],
    )
    save_workout(test_db, date="2026-09-29", sport_type="running", title="Easy run",
                 description=EASY_TEXT, duration_minutes=40, tss=30)
    save_workout(test_db, date="2026-10-02", sport_type="running", title="Tempo run",
                 duration_minutes=45, tss=50)
    _activity("a0510", "2026-05-10")


def _activity(activity_id, day):
    test_db.save_completed_activity(
        activity_id=activity_id, date=day, start_time=f"{day} 08:00:00",
        activity_name="Run", activity_type="running", duration_sec=2400.0,
        distance_km=6.0, elevation_gain_m=10.0, avg_hr=140, max_hr=160, rpe=4, tss=30.0,
    )


def _gym_log(day, log):
    """A gym log as `strength ingest` stores it, on the day's placeholder activity."""
    activity_id = test_db.upsert_logged_activity(day, f"{day} 18:02:00", 3780.0)
    now = datetime(2026, 9, 24, 19, 6).astimezone()
    test_db.store_exercise_sets(activity_id, [], now, now)
    test_db.save_gym_log(activity_id, log["r"], json.dumps(log))


class RecipeTest(unittest.TestCase):
    """The key, the names and the encryption (§5)."""

    def test_the_example_both_languages_open(self):
        key = recipe.page_key(TOKEN)
        self.assertEqual(recipe.key_param(key), KEY)
        self.assertEqual(recipe.file_name(key, "calendar/2026-09"), SEPTEMBER)
        self.assertEqual(recipe.unseal(key, base64.b64decode(BLOB)), CONTENT)
        page_test = _read("miniapp", "tests", "storage.test.mjs")
        for constant in (KEY, SEPTEMBER, BLOB[:60], BLOB[-20:]):
            self.assertIn(constant, page_test)

    def test_every_upload_draws_fresh_bytes(self):
        key = recipe.page_key(TOKEN)
        one, two = recipe.seal(key, CONTENT), recipe.seal(key, CONTENT)
        self.assertNotEqual(one[:recipe.NONCE_BYTES], two[:recipe.NONCE_BYTES])
        self.assertEqual(recipe.unseal(key, two), CONTENT)

    def test_the_folder_is_the_bots_number(self):
        self.assertEqual(recipe.folder(TOKEN), FOLDER)

    def test_the_page_names_the_files_as_python_does(self):
        page = _read("miniapp", "storage.js")
        self.assertIn(f'INDEX = "{sync.INDEX}"', page)
        self.assertIn(f'PLAN = "{sync.PLAN}"', page)
        self.assertEqual(calendar_page.month_label("2026-09"), "calendar/2026-09")
        self.assertIn("`calendar/${monthKey(month)}`", _read("miniapp", "calendar_logic.js"))


class FilesTestCase(unittest.TestCase):

    def setUp(self):
        rebind_test_db(test_db)
        clear_all_tables(test_db)
        pin_clock(self, TODAY)
        FakeBucket.reset()
        the_month()


class BuildTest(FilesTestCase):
    """What the files hold (§4)."""

    def test_after_a_command_the_months_the_window_touches(self):
        # The window runs from 2 September to 11 November.
        self.assertEqual(set(sync.build(test_db, TODAY)), {
            "calendar/2026-09", "calendar/2026-10", "calendar/2026-11", sync.INDEX, sync.PLAN})

    def test_publish_builds_every_month_from_the_first_empty_ones_included(self):
        files = sync.build(test_db, TODAY, every_month=True)
        months = sorted(label for label in files if label not in (sync.INDEX, sync.PLAN))
        self.assertEqual(months[0], "calendar/2026-05")
        self.assertEqual(months[-1], "calendar/2026-11")
        self.assertEqual(len(months), 7)
        self.assertEqual(files["calendar/2026-06"], {"v": 1, "days": {}})
        self.assertIn("2026-05-10", files["calendar/2026-05"]["days"])

    def test_a_month_file_holds_the_workout_text_as_stored(self):
        september = sync.build(test_db, TODAY)["calendar/2026-09"]
        planned = dict(september["days"]["2026-09-29"]["sheet"])["Planned"]
        self.assertIn(EASY_TEXT, planned)
        # A day with nothing on it but inside the schedule says it is a rest day.
        self.assertIn("sheet", september["days"]["2026-09-30"])

    def test_a_month_file_holds_a_days_gym_log_beside_its_session(self):
        """Thursday's gym was logged from the page, so its day carries the two things the
        gym logger opens that log from (DESIGN_gym_logger.md §8)."""
        save_workout(test_db, date="2026-09-24", sport_type="strength_training", title="Gym",
                     duration_minutes=50, prescribed_sets=[
                         {"exercise": "belt squat", "sets": 3, "reps_low": 4, "reps_high": 6,
                          "load_kg": 140.0}])
        session = test_db.get_workout("2026-09-24", "strength_training")
        log = {"v": 1, "r": session["revision_id"], "d": "2026-09-24", "st": "18:02",
               "en": "19:05", "x": [{"n": "belt squat", "p": 1, "sets": [[5, 140, 40]]}]}
        _gym_log("2026-09-24", log)
        day = sync.build(test_db, TODAY)["calendar/2026-09"]["days"]["2026-09-24"]
        self.assertEqual(day["gym"]["l"], log)
        self.assertEqual(day["gym"]["s"]["r"], session["revision_id"])
        self.assertEqual(day["gym"]["s"]["x"],
                         [{"n": "belt squat", "s": 3, "lo": 4, "hi": 6, "kg": 140.0}])
        # The button's own data does not carry it: a log would eat its budget.
        cal = calendar_days.gather(test_db, *calendar_page.window(TODAY), TODAY)
        payload, _sheets = calendar_page.snapshot(cal, datetime(2026, 9, 30, 7, 2))
        self.assertNotIn("gym", payload["days"]["2026-09-24"])
        # The page reads the day's log under the name Python writes it.
        self.assertIn("(snapshot.days[iso] || {}).gym", _read("miniapp", "calendar.js"))
        self.assertIn("encodeSession(gym.s)}&l=${encodeSession(gym.l)}",
                      _read("miniapp", "logic.js"))
        # A log written against another revision has no session to open beside it.
        _gym_log("2026-09-24", {**log, "r": session["revision_id"] + 1})
        day = sync.build(test_db, TODAY)["calendar/2026-09"]["days"]["2026-09-24"]
        self.assertNotIn("gym", day)

    def test_the_content_is_the_same_whatever_width_the_process_wraps_at(self):
        with patch.dict(os.environ, {"STAMIND_WRAP_WIDTH": "80"}):
            narrow = sync.build(test_db, TODAY)
        with patch.dict(os.environ, {"STAMIND_WRAP_WIDTH": "900"}):
            wide = sync.build(test_db, TODAY)
        self.assertEqual({k: sync.fingerprint(v) for k, v in narrow.items()},
                         {k: sync.fingerprint(v) for k, v in wide.items()})

    def test_the_index_file(self):
        index = sync.build(test_db, TODAY)[sync.INDEX]
        self.assertEqual((index["first"], index["last"]), ("2026-05", "2026-11"))
        self.assertEqual((index["from"], index["to"]), ("2026-09-02", "2026-11-11"))
        self.assertNotIn("days", index)
        self.assertNotIn("fit", index)
        self.assertEqual(index["end"], "2026-10-02")

    def test_the_button_and_the_files_carry_one_list_of_mesocycles(self):
        # Summer ended on 1 September, the day before the window: both lists hold it.
        index = sync.build(test_db, TODAY)[sync.INDEX]
        start, end = calendar_page.window(TODAY)
        cal = calendar_days.gather(test_db, start, end, TODAY)
        button = calendar_page.unpack(
            calendar_page.calendar_url(cal, datetime(2026, 9, 30, 7, 2)).split("#c=")[1])
        self.assertEqual([m["n"] for m in index["meso"]], ["Summer", "Build", "Taper"])
        self.assertEqual(button["meso"], index["meso"])

    def test_a_schedule_that_ended_before_the_window_reaches_the_button_too(self):
        # 5 November: the window starts on 8 October, the last session was on 2 October.
        # Both draws grey the window, so nothing moves when the index file arrives.
        today = "2026-11-05"
        start, end = calendar_page.window(today)
        cal = calendar_days.gather(test_db, start, end, today)
        button = calendar_page.unpack(
            calendar_page.calendar_url(cal, datetime(2026, 11, 5, 7, 2)).split("#c=")[1])
        self.assertEqual(button["end"], "2026-10-02")
        self.assertEqual(sync.build(test_db, today)[sync.INDEX]["end"], "2026-10-02")

    def test_the_plan_file_carries_each_long_text(self):
        plan = sync.build(test_db, TODAY)[sync.PLAN]
        build = [m for m in plan["meso"] if m["n"] == "Build"][0]
        self.assertEqual(build["f"],
                         "Build the engine.\n\nMost of it easy, one quality day a week.")

    def test_the_stamp_is_left_out_of_the_comparison(self):
        index = sync.build(test_db, TODAY)[sync.INDEX]
        self.assertEqual(sync.fingerprint(index), sync.fingerprint({**index, "at": "later"}))


class AfterCommandTest(FilesTestCase):
    """The step after every command (§6)."""

    def publish(self):
        code, out, _err = run_cli(["data", "publish"])
        self.assertIn("Every file is uploaded", out)
        FakeBucket.uploads.clear()

    def test_a_database_never_published_uploads_nothing(self):
        use_storage(self)
        sync.after_command()
        run_cli(["calendar", "--no-pull"])
        self.assertEqual(FakeBucket.files, {})

    def test_no_bucket_configured_uploads_nothing(self):
        use_storage(self, bucket_name=None)
        sync.after_command()
        self.assertEqual(FakeBucket.uploads, [])

    def test_an_unchanged_database_uploads_nothing(self):
        use_storage(self)
        self.publish()
        sync.after_command()
        self.assertEqual(FakeBucket.uploads, [])

    def test_a_new_activity_uploads_its_month_then_the_index(self):
        use_storage(self)
        self.publish()
        _activity("a0930", TODAY)
        run_cli(["calendar", "--no-pull"])
        key = recipe.page_key(TOKEN)
        self.assertEqual(FakeBucket.uploads, [recipe.file_name(key, "calendar/2026-09"),
                                              recipe.file_name(key, sync.INDEX)])

    def test_a_terminal_reads_one_line_about_the_upload_and_the_chat_none(self):
        line = "Pages' files updated: 2 file(s) uploaded to the bucket."
        use_storage(self)
        os.environ.pop("STAMIND_VERBOSE", None)
        self.publish()
        started_from(self, "terminal")
        _activity("a0930", TODAY)
        self.assertIn(line, run_cli(["calendar", "--no-pull"])[1])
        # Nothing changed since, so nothing went up and nothing is said.
        self.assertNotIn("Pages' files updated", run_cli(["calendar", "--no-pull"])[1])
        started_from(self, "chat")
        _activity("a0929", "2026-09-29")
        self.assertNotIn("Pages' files updated", run_cli(["calendar", "--no-pull"])[1])
        self.assertEqual(len(FakeBucket.uploads), 4)

    def test_a_line_that_only_printed_help_uploads_nothing(self):
        use_storage(self)
        self.publish()
        _activity("a0930", TODAY)
        run_cli(["goal"])
        self.assertEqual(FakeBucket.uploads, [])

    def test_past_the_time_limit_the_rest_waits_for_the_next_command(self):
        use_storage(self)
        self.publish()
        _activity("a0930", TODAY)
        with patch.object(sync, "UPLOAD_SECONDS", 0):
            sync.after_command()
        self.assertEqual(FakeBucket.uploads, [])
        sync.after_command()
        self.assertEqual(len(FakeBucket.uploads), 2)

    def test_a_failed_upload_goes_to_the_journal_and_status_and_the_command_goes_on(self):
        use_storage(self)
        self.publish()
        _activity("a0930", TODAY)
        FakeBucket.failing = True
        with patch.object(sync.journal, "note") as note:
            sync.after_command()
        labels = [c.kwargs.get("label") for c in note.call_args_list]
        self.assertIn("calendar/2026-09", labels)
        self.assertTrue(all(c.kwargs.get("error") == "HTTP 503" for c in note.call_args_list))
        line = status._page_files_line()
        self.assertIn("calendar/2026-09", line)
        self.assertIn("HTTP 503", line)
        FakeBucket.failing = False
        sync.after_command()
        self.assertIsNone(status._page_files_line())

    def test_a_failed_upload_goes_again_though_its_content_is_the_same(self):
        # The index file that failed after its month went up, and a month two commands
        # raced for: the record's fingerprint already matches (§6 step 3).
        use_storage(self)
        self.publish()
        where = sync.target()
        for label in (sync.INDEX, "calendar/2026-09"):
            test_db.record_page_error(where.address(where.name(label)), label, "HTTP 503")
            self.assertIn("The next command uploads it again", status._page_files_line())
            sync.after_command()
            self.assertIn(where.name(label), FakeBucket.uploads)
            self.assertIsNone(status._page_files_line())

    def test_a_failed_month_older_than_the_window_sends_the_operator_to_publish(self):
        # 30 September: the window starts on 2 September, so no command builds August.
        use_storage(self)
        self.publish()
        where = sync.target()
        august = "calendar/2026-08"
        test_db.record_page_error(where.address(where.name(august)), august, "HTTP 503")
        line = status._page_files_line()
        self.assertIn("sm data publish", line)
        self.assertNotIn("next command", line)


class PublishTest(FilesTestCase):
    """`sm data publish` and `sm data unpublish` (§9)."""

    def names(self, folder=FOLDER):
        return sorted(n for (b, f, n) in FakeBucket.files if f == folder)

    def expected(self, token=TOKEN):
        key = recipe.page_key(token)
        return sorted(recipe.file_name(key, label)
                      for label in sync.build(test_db, TODAY, every_month=True))

    def test_publish_checks_the_setup_then_uploads_every_file(self):
        use_storage(self)
        _code, out, _err = run_cli(["data", "publish"])
        self.assertEqual(out.count("✓"), 6, out)
        # The test file of check 3 is gone with the fill.
        self.assertEqual(self.names(), self.expected())
        self.assertEqual(len(test_db.get_page_files()), 9)
        self.assertNotIn(KEY, out)

    def test_a_failed_check_names_the_step_and_nothing_is_uploaded(self):
        use_storage(self)
        FakeBucket.listable = True
        _code, out, _err = run_cli(["data", "publish"])
        self.assertIn("Storage Legacy Object Reader", out)
        self.assertIn("step 4", out)
        self.assertEqual(test_db.get_page_files(), {})

    def test_no_bucket_is_named_in_the_config(self):
        use_storage(self, bucket_name=None)
        _code, out, _err = run_cli(["data", "publish"])
        self.assertIn("google.storage_bucket", out)

    def test_both_commands_stop_at_a_folder_another_database_published(self):
        use_storage(self)
        FakeBucket.files[(BUCKET, FOLDER, "someone-elses")] = b"x"
        for command in ("publish", "unpublish"):
            _code, out, _err = run_cli(["data", command])
            self.assertIn("another database published", out)
        self.assertEqual(self.names(), ["someone-elses"])

    def test_force_goes_on_and_the_stranger_goes(self):
        use_storage(self)
        FakeBucket.files[(BUCKET, FOLDER, "someone-elses")] = b"x"
        run_cli(["data", "publish", "--force"])
        self.assertEqual(self.names(), self.expected())

    def test_after_a_new_bot_token_publish_passes_and_the_old_names_go(self):
        use_storage(self)
        run_cli(["data", "publish"])
        new = "123456789:AAANewTokenAfterARevocation"
        use_storage(self, token=new)
        self.assertEqual(sync.button_params(test_db), "")
        _code, out, _err = run_cli(["data", "publish"])
        self.assertNotIn("another database", out)
        self.assertEqual(self.names(), self.expected(new))

    def test_unpublish_empties_the_record_and_deletes_its_own_folder_only(self):
        use_storage(self)
        run_cli(["data", "publish"])
        FakeBucket.files[(BUCKET, "987654321", "another-bots")] = b"x"
        _code, out, _err = run_cli(["data", "unpublish"])
        self.assertIn("gone from the bucket", out)
        self.assertEqual(self.names(), [])
        self.assertEqual(self.names("987654321"), ["another-bots"])
        self.assertEqual(test_db.get_page_files(), {})
        _activity("a0930", TODAY)
        sync.after_command()
        self.assertEqual(self.names(), [])


class ButtonTest(FilesTestCase):
    """What the bot's buttons carry, and the status line (§8, §10)."""

    def test_the_button_carries_the_key_only_once_published(self):
        use_storage(self)
        self.assertEqual(sync.button_params(test_db), "")
        self.assertIn("never published", status._page_files_line())
        run_cli(["data", "publish"])
        params = sync.button_params(test_db)
        self.assertEqual(params, f"&k={KEY}&b={BUCKET}&f={FOLDER}")
        self.assertIsNone(status._page_files_line())

    def test_a_first_publish_whose_index_file_failed_is_not_published(self):
        # The failed upload leaves a row with its error and no fingerprint (§6 step 1).
        use_storage(self)
        where = sync.target()
        test_db.record_page_error(where.address(where.name(sync.INDEX)), sync.INDEX,
                                  "HTTP 503")
        self.assertEqual(sync.button_params(test_db), "")
        sync.after_command()
        self.assertEqual(FakeBucket.uploads, [])

    def test_what_storage_adds_comes_out_of_the_budget(self):
        start, end = calendar_page.window(TODAY)
        cal = calendar_days.gather(test_db, start, end, TODAY)
        extra = "&k=" + "x" * 4000
        url = calendar_page.calendar_url(cal, datetime(2026, 9, 30, 7, 2), extra)
        packed, tail = url.split("#c=")[1].split("&k=")
        self.assertLessEqual(len(packed) + len(extra), calendar_page.BUDGET_BYTES)
        self.assertEqual("&k=" + tail, extra)

    def test_no_bucket_means_no_status_line(self):
        use_storage(self, bucket_name=None)
        self.assertIsNone(status._page_files_line())


if __name__ == "__main__":
    unittest.main()
