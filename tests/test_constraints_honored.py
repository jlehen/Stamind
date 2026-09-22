"""`constraints.honored_at` — whether the schedule actually did what the
constraint asked, which is the signal the DESIGN_constraints.md §4.1 sweep
reads.
"""
import argparse
import io
import os
import unittest
from contextlib import redirect_stdout
from unittest.mock import patch

from tests import test_db_path
from tests.helpers import clear_all_tables, rebind_test_db, save_workout

TEST_DB_PATH = test_db_path("test_constraints_honored.db")

from stamind.db import Database

test_db = Database(db_path=TEST_DB_PATH)
rebind_test_db(test_db)

from stamind.coach.service import coach_service
from stamind.coach import honoring
from stamind.cli.common import constraint_line


def tearDownModule():
    """The classes here recreate the database file without removing it, so the cleanup
    belongs to the module rather than to any one class."""
    if os.path.exists(TEST_DB_PATH):
        try:
            os.remove(TEST_DB_PATH)
        except OSError:
            pass


class TestHonoredAt(unittest.TestCase):
    """`constraints.honored_at` — the signal the §4.1 sweep reads
    (DESIGN_constraint_honoring.md §2). It means: a coach pass had this constraint in
    scope, with authority over every day of it still ahead. Not "the plan definitely
    changed"."""

    @classmethod
    def setUpClass(cls):
        global test_db
        test_db = Database(db_path=TEST_DB_PATH)
        rebind_test_db(test_db)

    def setUp(self):
        clear_all_tables(test_db)

    def _constraint(self, start="2026-06-10", end="2026-06-20", sessions=True, **kw):
        cid = test_db.add_constraint(title=kw.pop("title", "Away"),
                                     start_date=start, end_date=end, **kw)
        # A window with no sessions in it is nothing to reshuffle, so nothing offers the
        # window tier for it (§8). Every case below is about some OTHER term of that rule,
        # so give them all a session to displace; `sessions=False` isolates this one.
        if sessions:
            save_workout(test_db, end, "running", "Tempo", "40min", duration_minutes=40)
        return cid

    def test_a_constraint_with_nothing_scheduled_in_its_window_is_not_offered(self):
        # Nothing to reshuffle, so naming it would be a nudge the athlete cannot act on.
        empty = self._constraint(title="Nothing planned", sessions=False)
        self.assertIsNone(test_db.get_constraint(empty)["honored_at"])
        self.assertEqual(honoring.constraints_needing_a_pass(test_db, "2026-06-01"), [])

    def test_a_new_constraint_starts_unhonored(self):
        cid = self._constraint()
        self.assertIsNone(test_db.get_constraint(cid)["honored_at"])
        self.assertEqual(
            [c["id"] for c in honoring.constraints_needing_a_pass(test_db, "2026-06-01")], [cid]
        )

    def test_the_sweep_filter_drops_honored_and_finished_constraints(self):
        honored = self._constraint(title="Honored")
        test_db.mark_honored(honored)
        past = self._constraint("2026-05-01", "2026-05-05", title="Past")
        live = self._constraint(title="Live")
        got = [c["id"] for c in honoring.constraints_needing_a_pass(test_db, "2026-06-01")]
        self.assertEqual(got, [live])
        self.assertNotIn(past, got)

    def test_clear_honored_re_arms_the_sweep(self):
        cid = self._constraint()
        test_db.mark_honored(cid)
        test_db.clear_honored(cid)
        self.assertIsNone(test_db.get_constraint(cid)["honored_at"])

    def test_coverage_clips_the_window_to_what_the_pass_could_write(self):
        # No command has authority over days already behind it, so a constraint already
        # under way is covered by a pass that reaches its END — demanding the literal whole
        # window would leave it flagged forever.
        under_way = {"id": 1, "start_date": "2026-05-25", "end_date": "2026-06-10"}
        self.assertTrue(honoring.covers(
            under_way, "2026-06-01", "2026-06-28"))
        # ...but a constraint running past the pass's end is not covered.
        straddling = {"id": 2, "start_date": "2026-06-20", "end_date": "2026-07-05"}
        self.assertFalse(honoring.covers(
            straddling, "2026-06-01", "2026-06-28"))

    @patch("stamind.coach.engine.openrouter_client")
    def test_a_no_change_run_stamps_only_when_the_caller_records_it(self, mock_client):
        """A run proposing nothing never reaches apply, so the no-change branch records it
        explicitly — requiring a *change* would leave "no adaptation needed" flagged
        forever. Proposing must not write on its own, so the stamp lands on the call, not
        on `workout_adapt`."""
        self._plan("2026-06-01", "2026-06-30")
        cid = self._constraint("2026-06-10", "2026-06-20")
        mock_client.complete.return_value = {
            "change_needed": False, "reason": "On track.", "adapted_workouts": [],
        }
        with patch("builtins.print"):
            proposal = coach_service.workout_adapt("2026-06-01")
        self.assertEqual(proposal.covered_constraint_ids, (cid,))
        self.assertIsNone(test_db.get_constraint(cid)["honored_at"])

        coach_service.workout_revision_record_no_change(proposal)
        self.assertIsNotNone(test_db.get_constraint(cid)["honored_at"])

    @patch("stamind.coach.engine.openrouter_client")
    def test_a_declined_adapt_proposal_stamps_nothing(self, mock_client):
        """A proposal the athlete never accepted reflects nothing, so the stamp waits for
        the `y` — i.e. for `workout_revision_apply`."""
        self._plan("2026-06-01", "2026-06-30")
        cid = self._constraint("2026-06-10", "2026-06-20")
        save_workout(test_db, "2026-06-11", "running", "Tempo", "40min",
                             duration_minutes=40, rpe=6, tss=45)
        mock_client.complete.return_value = {
            "change_needed": True, "reason": "Eased.",
            "adapted_workouts": [
                {"date": "2026-06-11", "sport_type": "running", "title": "Easy run",
                 "description": "30min", "duration_minutes": 30, "rpe": 3, "tss": 20},
            ],
        }
        with patch("builtins.print"):
            proposal = coach_service.workout_adapt("2026-06-01")
        self.assertEqual(proposal.covered_constraint_ids, (cid,))
        self.assertIsNone(test_db.get_constraint(cid)["honored_at"])

        with patch("builtins.print"):
            coach_service.workout_revision_apply(proposal)
        self.assertIsNotNone(test_db.get_constraint(cid)["honored_at"])

    def test_a_rollback_clears_only_honorings_newer_than_the_undone_change(self):
        """A constraint honored INTO a plan newer than the one coming back cannot be
        reflected by the restored sessions; one honored BEFORE it already was.

        The comparison survived the move to revisions with its key changed: the batch is
        now the change that CREATED the rows, so it is that change's `created_at` a
        honoring is measured against (DESIGN_workout_revisions.md §10)."""
        older = self._constraint("2026-06-10", "2026-06-20", title="Older")
        newer = self._constraint("2026-06-10", "2026-06-20", title="Newer")
        test_db.mark_honored(older)
        save_workout(test_db, "2026-06-11", "running", "Tempo", "40min")
        # The change to undo: the one that rewrote the session after `older` was honored.
        with test_db.workout_change(kind="generate") as change:
            change.append(date="2026-06-11", sport_type="running", title="Tempo",
                          description="60min")
        rewrite = test_db.get_workout_changes()[0]["id"]
        test_db.mark_honored(newer)

        # The rollback reports what it un-honored, so the CLI can name it afterwards.
        _restored, unhonored = test_db.rollback_to_change(rewrite, "2026-06-01")
        self.assertEqual([c["id"] for c in unhonored], [newer])
        self.assertIsNotNone(test_db.get_constraint(older)["honored_at"])
        self.assertIsNone(test_db.get_constraint(newer)["honored_at"])

    def test_generate_stamps_the_constraints_its_written_range_covers(self):
        """The same warrant every other constraint a generation built around gets: its
        remaining window sits inside the range about to be WRITTEN. Generate's constraint
        fetch is open-ended, so coverage is checked against that range, not the fetch."""
        inside = self._constraint("2026-06-10", "2026-06-20", title="Inside")
        past_end = self._constraint("2026-07-10", "2026-07-20", title="Past the horizon")
        for cid, expected in ((inside, True), (past_end, False)):
            covered = honoring.covers(
                test_db.get_constraint(cid), "2026-06-01", "2026-06-28"
            )
            self.assertEqual(covered, expected, cid)

    def _edit(self, cid, **flags):
        """`constraint edit` through its real handler, so the clear is tested where it
        lives."""
        import argparse
        from stamind.cli.constraints import run_constraint_edit
        ns = argparse.Namespace(id=cid, title=None, start=None, end=None, rest=None,
                                desc=None, replan=None)
        for k, v in flags.items():
            setattr(ns, k, v)
        # The §7 replan proposal is a separate decision and asks on stdin; declining it
        # here keeps this test about the honored axis (and off the terminal).
        with patch("builtins.print"), \
                patch("stamind.cli.constraints._run_replan_flow"), \
                patch("stamind.runtime.prompt") as prompt:
            prompt.confirm.return_value = False
            run_constraint_edit(ns)

    def test_editing_the_window_or_the_directive_clears_the_honoring(self):
        # The window moved, or the directive changed — and for an advisory constraint the
        # prose IS the enforcement mechanism, so new words are a new directive a previous
        # honoring says nothing about.
        for flags in ({"start": "2026-06-11"}, {"end": "2026-06-21"}, {"rest": True},
                      {"title": "Away, but shorter"}, {"desc": "richer context"}):
            with self.subTest(flags=sorted(flags)):
                cid = self._constraint()
                test_db.mark_honored(cid)
                self._edit(cid, **flags)
                self.assertIsNone(test_db.get_constraint(cid)["honored_at"])

    def test_editing_only_the_replan_tier_leaves_the_honoring_alone(self):
        # `replan` escalates the tier; it does not restate what to work around.
        cid = self._constraint()
        test_db.mark_honored(cid)
        self._edit(cid, replan=True)
        self.assertIsNotNone(test_db.get_constraint(cid)["honored_at"])

    def test_the_add_time_message_fires_when_the_window_outruns_the_mesocycle(self):
        """§4: below the replan threshold nothing used to say WHEN a constraint takes
        effect. Fires for a window landing beyond the active mesocycle AND for one straddling
        its boundary, which daily adapt honors only in part."""
        self._plan_mesocycles([
            ("Base 2", "2026-06-01", "2026-06-30"),
            ("Build 1", "2026-07-01", "2026-08-15"),
        ])
        from stamind.cli.constraints import point_at_honor
        for start, end, should_fire in (
            ("2026-07-05", "2026-07-10", True),    # wholly beyond the active mesocycle
            ("2026-06-28", "2026-07-04", True),    # straddling its boundary
            ("2026-06-10", "2026-06-20", False),   # inside it — adapt's, and it says so
        ):
            with self.subTest(start=start):
                cid = self._constraint(start, end)
                buf = io.StringIO()
                with patch("stamind.cli.constraints._today_str", return_value="2026-06-01"), \
                        redirect_stdout(buf):
                    point_at_honor(cid)
                out = " ".join(buf.getvalue().split())
                self.assertEqual("workout generate -m" in out, should_fire)

    def test_the_add_time_message_names_the_landing_mesocycle_and_when_adapt_reaches_it(self):
        """Adapt at date D reaches to the end of D's mesocycle, so it sees the constraint once
        its window rolls onto the LANDING mesocycle — that mesocycle's first day, not the current
        mesocycle's last."""
        self._plan_mesocycles([
            ("Base 2", "2026-06-01", "2026-06-30"),
            ("Build 1", "2026-07-01", "2026-08-15"),
        ])
        from stamind.cli.constraints import point_at_honor
        cid = self._constraint("2026-07-20", "2026-07-24")
        buf = io.StringIO()
        with patch("stamind.cli.constraints._today_str", return_value="2026-06-01"), \
                redirect_stdout(buf):
            point_at_honor(cid)
        out = " ".join(buf.getvalue().split())
        self.assertIn("Lands in Build 1 (2026-07-01 Wed — 2026-08-15 Sat)", out)
        self.assertIn("adapt reaches it on 2026-07-01 Wed", out)

    def test_a_straddling_constraint_names_the_mesocycle_holding_its_UNREACHED_days(self):
        """The mesocycle is read off the constraint's END. Asked of its start, a straddling
        window names the CURRENT mesocycle — the one adapt reaches today — and offers a
        past date as the day adapt will get to it (§1, the seam case)."""
        self._plan_mesocycles([
            ("Build 1", "2026-08-15", "2026-09-14"),
            ("Build 2", "2026-09-15", "2026-10-04"),
        ])
        from stamind.cli.constraints import point_at_honor
        cid = self._constraint("2026-09-12", "2026-09-20")
        buf = io.StringIO()
        with patch("stamind.cli.constraints._today_str", return_value="2026-08-21"), \
                redirect_stdout(buf):
            point_at_honor(cid)
        out = " ".join(buf.getvalue().split())
        self.assertIn("Straddles the end of Build 1 (2026-09-14 Mon)", out)
        self.assertIn("Build 2 holds the rest", out)
        # One run covers both mesocycles, because generation starts today and runs through
        # the end of the mesocycle it is given — so it is Build 2 that must be named.
        build_2 = test_db.get_covering_mesocycle("2026-09-20")
        self.assertIn(f"workout generate -m {build_2['id']}", out)
        # The two ways it used to be wrong: the current mesocycle named as out of reach, and
        # a date already behind the athlete offered as when adapt arrives.
        self.assertNotIn("Lands in Build 1", out)
        self.assertNotIn("2026-08-15", out)

    def test_a_constraint_running_off_the_plans_end_is_offered_its_governed_days(self):
        """Its last day is ungoverned but its first is not, so there are still governed
        days to build around — named, with `plan generate` for the rest."""
        self._plan_mesocycles([("Build 1", "2026-08-15", "2026-09-14")])
        from stamind.cli.constraints import point_at_honor
        cid = self._constraint("2026-09-10", "2026-09-25")
        buf = io.StringIO()
        with patch("stamind.cli.constraints._today_str", return_value="2026-08-21"), \
                redirect_stdout(buf):
            point_at_honor(cid)
        out = " ".join(buf.getvalue().split())
        self.assertIn("past the end of your plan", out)
        self.assertIn("workout generate", out)
        self.assertIn("plan generate", out)
        # It does not start past the plan's end, so it must not be described that way.
        self.assertNotIn("Starts 2026-09-10", out)

    def test_a_constraint_past_the_plans_end_is_pointed_at_plan_generate(self):
        # `get_active_mesocycle` falls back to a neighbouring mesocycle when none covers the
        # date, so naming one here would name a mesocycle the constraint is not in.
        self._plan("2026-06-01", "2026-06-30")
        from stamind.cli.constraints import point_at_honor
        cid = self._constraint("2026-09-01", "2026-09-05")
        buf = io.StringIO()
        with patch("stamind.cli.constraints._today_str", return_value="2026-06-01"), \
                redirect_stdout(buf):
            point_at_honor(cid)
        out = " ".join(buf.getvalue().split())
        self.assertIn("past the end of the plan", out)
        self.assertIn("plan generate", out)
        self.assertNotIn("workout generate", out)

    def test_the_add_time_message_stays_quiet_on_a_plan_shaping_constraint(self):
        # It is being built into the plan, so pointing at a rebuild is the wrong tier.
        self._plan("2026-06-01", "2026-06-30")
        from stamind.cli.constraints import point_at_honor
        cid = self._constraint("2026-07-05", "2026-07-10")
        test_db.update_constraint(cid, replan=1)
        buf = io.StringIO()
        with patch("stamind.cli.constraints._today_str", return_value="2026-06-01"), \
                redirect_stdout(buf):
            point_at_honor(cid)
        self.assertEqual(buf.getvalue(), "")

    def test_a_pass_that_ended_before_the_range_never_covered_it(self):
        # `covers` is the one owner of who may stamp, so it may not lean on its callers
        # having pre-filtered to an overlapping set (§3).
        past = {"start_date": "2026-05-01", "end_date": "2026-05-10"}
        self.assertFalse(honoring.covers(past, "2026-06-01", "2026-07-31"))
        ahead = {"start_date": "2026-08-01", "end_date": "2026-08-05"}
        self.assertFalse(honoring.covers(ahead, "2026-06-01", "2026-07-31"))
        under_way = {"start_date": "2026-05-20", "end_date": "2026-06-10"}
        self.assertTrue(honoring.covers(under_way, "2026-06-01", "2026-07-31"))

    def test_every_surface_agrees_on_which_tier_owns_a_directive(self):
        """A rule that spans files gets a test that spans them (AGENTS.md).

        The `status` count, the one-line rendering, the `show` detail and the add-time
        nudge each answer "does the schedule reflect this yet?" — and each one used to answer
        it for itself, which is how `constraint show` came to flag a plan-shaping
        directive the count deliberately skips (§2).
        """
        from stamind.cli.constraints import point_at_honor, run_constraint_show
        self._plan_mesocycles([("Base 2", "2026-06-01", "2026-06-30"),
                           ("Build 1", "2026-07-01", "2026-08-15")])
        cases = {
            "offered": self._constraint("2026-07-05", "2026-07-10", title="Away"),
            "plan-shaping": self._constraint("2026-07-05", "2026-07-10", title="Surgery",
                                             replan=1),
            "nothing scheduled": self._constraint("2026-07-20", "2026-07-25",
                                                  title="Quiet", sessions=False),
        }
        for label, cid in cases.items():
            with self.subTest(case=label):
                constraint = test_db.get_constraint(cid)
                with patch("stamind.cli.constraints._today_str",
                           return_value="2026-06-01"):
                    swept = [
                        c["id"] for c in
                        honoring.constraints_needing_a_pass(test_db, "2026-06-01")
                    ]
                    buf = io.StringIO()
                    with redirect_stdout(buf):
                        run_constraint_show(argparse.Namespace(id=cid))
                        point_at_honor(cid)
                    line = constraint_line(constraint, cid in swept)
                offered = cid in swept
                # All four surfaces say the same thing, whatever that thing is.
                self.assertEqual("not yet in the schedule" in line, offered)
                self.assertEqual("Coach pass: none yet" in buf.getvalue(), offered)
                self.assertEqual("workout generate" in buf.getvalue(), offered)

    @classmethod
    def _plan(cls, start, end):
        cls._plan_mesocycles([("Base", start, end)])

    @staticmethod
    def _plan_mesocycles(mesocycles):
        obj_id = test_db.add_objective(title="Goal", target_date="2026-12-31",
                                       sport_type="running")
        test_db.save_macrocycle(
            objective_id=obj_id, strategy="Prep.", goals_hash="h", constraints_hash="h",
            mesocycles=[{"name": name, "start_date": start, "end_date": end,
                         "focus": "Aerobic base"} for name, start, end in mesocycles],
        )


if __name__ == "__main__":
    unittest.main()
