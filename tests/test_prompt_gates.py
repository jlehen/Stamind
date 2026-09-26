"""An optional prompt feature must appear in every place it belongs, or in none.

`_workout_adapt_logic` has two gated features, and each controls three or four regions
that sit hundreds of lines apart in a 388-line builder: instructions telling the model
how to weigh the thing, the data section containing it, a schema member for what to say
about it, and a clause spliced into shared wording. That they move together was
guaranteed by comments. Half-applying one is the failure that matters — the model is
told to read a section that was never sent, or is sent data it was never told to use —
and it is silent, so it is asserted here.
"""
import os
import unittest
from unittest.mock import patch

from tests.helpers import as_instance, bind_test_db
from tests import test_db_path

TEST_DB_PATH = test_db_path("test_prompt_gates.db")
test_db = bind_test_db(TEST_DB_PATH)

from stamind.coach.engine import CoachEngine
from stamind.config import config
from stamind.strength import history as strength_history, planner_prompt

# Sentinels for each region a gate controls, matched against the built prompt.
NOTE_INSTRUCTIONS = "### ATHLETE'S NOTE FOR TODAY"
NOTE_SCHEMA_MEMBER = '"new_constraints"'
NOTE_CLAUSE = "constraint from the athlete's note drove the change"
NOTE_DATA = "## ATHLETE'S NOTE FOR THIS ADAPTATION"
NOTE_SIGNAL_INSTRUCTIONS = "### RECORDING A DAILY SIGNAL FROM THE NOTE"
NOTE_SIGNAL_SCHEMA_MEMBER = '"new_signals"'

from stamind.coach.engine.adapt import RULE_MESOCYCLE_NOT_YOURS, RULE_MOVE_FIRST
from stamind.coach.engine.sessions import benchmark_task, replaces_field

MOVE_SECTION = "### MOVING A SESSION TO ANOTHER DAY"
MOVE_SCHEMA_MEMBER = '"replaces"'

DRIFT_INSTRUCTIONS = "### CORRECTING EXECUTION DRIFT"
DRIFT_BRANCH = "measured intensity distribution has diverged from its stated"
DRIFT_DATA = "## MEASURED INTENSITY DISTRIBUTION OF THE ACTIVE MESOCYCLE"

STANDING_INSTRUCTIONS = "### THE SESSIONS THE ATHLETE IS ALREADY LOOKING AT"
STANDING_KEEP_MEMBER = '"keep": true'
STANDING_DROP_MEMBER = '"drop": true'
STANDING_REPLACES_MEMBER = '"replaces"'
STANDING_REASON_MEMBER = '"change_reason"'
STANDING_NOTE_MEMBER = '"athlete_note"'
STANDING_RULE = "unless it contradicts the athlete's profile, the plan, or a"
STANDING_DATA = "## SESSIONS ALREADY STANDING"
STANDING_SCOPE = "You must answer for every session listed here"

PAST_CONSTRAINTS_INSTRUCTIONS = "### WHAT ALREADY HAPPENED IN THIS MESOCYCLE"
PAST_CONSTRAINTS_DATA = "## CONSTRAINTS EARLIER IN THIS MESOCYCLE"

NEIGHBOUR_INSTRUCTIONS = "### THE DAYS JUST OUTSIDE THE SPAN"
NEIGHBOUR_DATA = "## SESSIONS JUST OUTSIDE THE SPAN"

STRENGTH_BRIEF_INSTRUCTIONS = "### WRITING A STRENGTH DAY"
STRENGTH_KEEP_THE_REQUEST = "A brief names an exercise in one case only"
STRENGTH_REQUEST_INSTRUCTIONS = "asks for something INSIDE a strength session"

TWEAK_TASK = "- FIND THE DAYS the request is about"
TWEAK_SCHEMA_MEMBER = '"tweak_dates"'
TWEAK_DATA = "## THE ATHLETE'S REQUEST"
TWEAK_CANCELLED_DATA = "## SESSIONS NO LONGER ON THE SCHEDULE"
FATIGUE_SECTIONS = (
    "### ATTRIBUTING A DEPRESSED MORNING", "### DO NOT COMPOUND A PRIOR ADAPTATION",
)

BASE = dict(
    history_days=7,
    start_date_str="2026-05-28",
    constraints=[],
    metrics=[{"date": "2026-06-03", "rhr": 50, "hrv": 70,
              "sleep_score": 80, "stress": 20}],
    baseline_str="RHR 50 +/- 2",
    planned_workouts=[{"date": "2026-06-03", "sport_type": "running",
                       "title": "Tempo", "description": "40min",
                       "duration_minutes": 40, "rpe": 6, "tss": 45}],
    completed_activities=[],
    target_date_str="2026-06-03",
    meso_end_date_str="2026-06-28",
    objectives=[{"id": 1, "title": "Race", "target_date": "2026-09-01",
                 "sport_type": "running"}],
    guidelines="Guidelines text.",
    profile={"max_hr": 185},
    strategy="Build aerobic base.",
    meso_text="  - Base (2026-06-01 to 2026-06-28): Aerobic\n",
    learnings="No learnings.",
    discrepancies=[],
)


def build_prompt(**extra):
    """The (system, user) pair the adapt call would send."""
    engine = CoachEngine()
    with patch("stamind.coach.engine.openrouter_client") as client:
        client.complete.return_value = {
            "change_needed": False, "reason": "ok", "adapted_workouts": [],
        }
        with patch("builtins.print"):
            engine._workout_adapt_logic(**BASE, **extra)
        system, user = client.complete.call_args[0][0], client.complete.call_args[0][1]
    return system, user


GENERATE_BASE = dict(
    objectives=[{"id": 1, "title": "Race", "target_date": "2026-09-01",
                 "sport_type": "running"}],
    constraints=[],
    today_str="2026-06-03",
    guidelines="Guidelines text.",
    profile={"max_hr": 185},
    strategy="Build aerobic base.",
    meso_text="  - Base (2026-06-01 to 2026-06-28): Aerobic\n",
    learnings="No learnings.",
)


def build_generate_prompt(**extra):
    """The (system, user) pair the generate call would send."""
    engine = CoachEngine()
    with patch("stamind.coach.engine.openrouter_client") as client:
        client.complete.return_value = {"reasoning": "ok", "workouts": []}
        with patch("builtins.print"):
            engine._workout_generate_logic(**GENERATE_BASE, **extra)
        return client.complete.call_args[0][0], client.complete.call_args[0][1]


NOTE_REGIONS = (
    NOTE_INSTRUCTIONS, NOTE_SCHEMA_MEMBER, NOTE_CLAUSE, NOTE_DATA,
    NOTE_SIGNAL_INSTRUCTIONS, NOTE_SIGNAL_SCHEMA_MEMBER,
)


class TestStrengthBriefRegion(unittest.TestCase):
    """A strength day's description is a brief in BOTH calls that write one
    (DESIGN_strength_tracking.md §9).

    Not a gate — nothing switches it off — but the same failure applies: if only one of the
    two calls carries it, `workout adapt` quietly writes kilograms into a description the
    strength planner then renders from its rows, and the two disagree on the athlete's
    screen.
    """

    def test_both_calls_tell_the_week_planner_to_write_a_brief(self):
        for name, prompt in (("adapt", build_prompt()[0]),
                             ("generate", build_generate_prompt()[0])):
            with self.subTest(call=name):
                self.assertIn(STRENGTH_BRIEF_INSTRUCTIONS, prompt)
                self.assertIn("no set count", prompt)
                # A request written into a brief outlives any rewrite of it
                # (DESIGN_workout_tweak.md §4).
                self.assertIn(STRENGTH_KEEP_THE_REQUEST, prompt)

    def test_the_rule_for_a_request_comes_with_the_message(self):
        """Only a run with a message has a request to write into a brief (§4)."""
        self.assertIn(STRENGTH_REQUEST_INSTRUCTIONS, build_prompt(athlete_message="x")[0])
        self.assertNotIn(STRENGTH_REQUEST_INSTRUCTIONS, build_prompt()[0])


class TestTheNoteTheAthleteDidNotWrite(unittest.TestCase):
    """A terminal run on a companion instance: the -m message is the athlete's coach's, and
    the reason goes to the athlete later (DESIGN_change_heads_up.md §3)."""

    NOTE = "rain all Friday, move the test to Saturday"
    COACH_NOTE = "the athlete did NOT write it"

    def test_the_paragraph_says_who_wrote_the_note_and_who_reads_the_reason(self):
        as_instance(self, "simple")
        system, user = build_prompt(athlete_message=self.NOTE)
        self.assertIn(self.COACH_NOTE, system)
        self.assertIn('"as you asked"', system)
        # Only the paragraph changes: every region the note governs is still there.
        for region in NOTE_REGIONS:
            self.assertIn(region, system + user, f"missing region: {region!r}")

    def test_a_run_the_athlete_watches_keeps_the_prompt_byte_for_byte(self):
        as_instance(self, "expert")
        expert = build_prompt(athlete_message=self.NOTE)
        as_instance(self, "simple", from_chat=True)
        from_chat = build_prompt(athlete_message=self.NOTE)
        self.assertEqual(expert, from_chat)
        self.assertNotIn(self.COACH_NOTE, expert[0])

    def test_a_run_without_a_message_keeps_the_prompt_byte_for_byte(self):
        as_instance(self, "expert")
        expert = build_prompt()
        as_instance(self, "simple")
        self.assertEqual(expert, build_prompt())


class TestStrengthHabitsRegion(unittest.TestCase):
    """The strength planner's habit rule reads what the strength history prints
    (DESIGN_strength_tracking.md §8, §9).

    Not a gate either, but the same silent failure: the rule names the history's sections and
    its mark, and a history that renamed one would leave the rule pointing at nothing.
    """

    def test_the_rule_names_what_the_history_prints_and_counts_to_the_configured_number(self):
        with patch.dict(config.data, {"strength": {"habit_after": 3}}):
            system = planner_prompt.system_prompt(set())
        self.assertIn("has happened 3 times", system)
        for printed in (
            strength_history.SESSIONS_HEADING.splitlines()[0].lstrip("# "),
            strength_history.NOT_DONE_HEADING,
            strength_history.NOT_PRESCRIBED.strip(),
        ):
            with self.subTest(printed=printed):
                self.assertIn(printed, system)


class TestAthleteNoteGate(unittest.TestCase):
    NOTE = "knee is sore, keep impact low"

    def test_a_note_reaches_every_region_it_governs(self):
        system, user = build_prompt(athlete_message=self.NOTE)
        whole = system + user
        for region in NOTE_REGIONS:
            with self.subTest(region=region):
                self.assertIn(region, whole)
        self.assertIn(self.NOTE, user, "the note itself must be in the data")

    def test_without_a_note_none_of_them_appear(self):
        system, user = build_prompt()
        whole = system + user
        for region in NOTE_REGIONS:
            with self.subTest(region=region):
                self.assertNotIn(region, whole)

    def test_a_blank_note_counts_as_no_note(self):
        """Whitespace is not intent; a blank note must not open the section."""
        system, user = build_prompt(athlete_message="   \n  ")
        self.assertNotIn(NOTE_INSTRUCTIONS, system + user)


class TestExecutionDriftGate(unittest.TestCase):
    CONTEXT = "Z1 2h00  Z2 3h00"

    def test_drift_context_reaches_every_region_it_governs(self):
        system, user = build_prompt(intensity_context=self.CONTEXT)
        whole = system + user
        for region in (DRIFT_INSTRUCTIONS, DRIFT_BRANCH, DRIFT_DATA):
            with self.subTest(region=region):
                self.assertIn(region, whole)
        self.assertIn(self.CONTEXT, user)

    def test_without_drift_context_none_of_them_appear(self):
        system, user = build_prompt()
        whole = system + user
        for region in (DRIFT_INSTRUCTIONS, DRIFT_BRANCH, DRIFT_DATA):
            with self.subTest(region=region):
                self.assertNotIn(region, whole)


class TestTheTweakGate(unittest.TestCase):
    """`tweak` puts the request's TASK in place of adapt's, and its data section and schema
    member come with it (DESIGN_workout_tweak.md §3.2)."""

    REQUEST = "Friday: step-ups instead of belt squats, the machine is broken"

    def test_the_request_regions_appear_together(self):
        system, user = build_prompt(tweak=True, athlete_message=self.REQUEST)
        self.assertIn(TWEAK_TASK, system)
        self.assertIn(TWEAK_SCHEMA_MEMBER, system)
        self.assertIn(TWEAK_DATA, user)
        self.assertIn(self.REQUEST, user)

    def test_the_fatigue_reading_and_the_note_are_left_out(self):
        system, user = build_prompt(tweak=True, athlete_message=self.REQUEST)
        for section in FATIGUE_SECTIONS:
            with self.subTest(section=section):
                self.assertNotIn(section, system)
        self.assertNotIn(NOTE_INSTRUCTIONS, system)
        self.assertNotIn(NOTE_DATA, user)

    def test_the_shared_sections_stay(self):
        system, _user = build_prompt(tweak=True, athlete_message=self.REQUEST)
        for section in (
            "### WHAT YOU MAY NOT TOUCH", STRENGTH_BRIEF_INSTRUCTIONS,
            STRENGTH_REQUEST_INSTRUCTIONS, MOVE_SECTION, "### PROTECTING A BENCHMARK",
            NOTE_SCHEMA_MEMBER, NOTE_SIGNAL_INSTRUCTIONS,
        ):
            with self.subTest(section=section):
                self.assertIn(section, system)

    def test_an_adapt_has_none_of_the_request_regions(self):
        system, user = build_prompt(athlete_message="knee is sore")
        whole = system + user
        for region in (TWEAK_TASK, TWEAK_SCHEMA_MEMBER, TWEAK_DATA):
            with self.subTest(region=region):
                self.assertNotIn(region, whole)
        for section in FATIGUE_SECTIONS:
            self.assertIn(section, system)

    def test_the_cancelled_sessions_come_under_the_tweaks_own_heading(self):
        """A tweak may bring any of them back, whoever cancelled it (§3.1)."""
        cancelled = [{
            "date": "2026-06-09", "sport_type": "running", "title": "Tempo run",
            "duration_minutes": 45, "rpe": 7, "tss": 50, "removed_reason": "Fatigue.",
        }]
        _system, user = build_prompt(
            tweak=True, athlete_message="put Tuesday's run back",
            removed_workouts=cancelled,
        )
        self.assertIn(TWEAK_CANCELLED_DATA, user)
        self.assertIn("Tempo run", user)
        self.assertNotIn("WORKOUTS REMOVED BY ATHLETE", user)

    def test_days_given_with_d_are_named_rather_than_asked_for(self):
        system, _user = build_prompt(
            tweak=True, athlete_message="make it shorter", tweak_dates=["2026-06-05"]
        )
        self.assertIn("The days are: 2026-06-05.", system)
        self.assertNotIn("Read them off the request", system)


class TestTheTerseSwitch(unittest.TestCase):
    """`terse` halves the summary the athlete reads once, and leaves "change_reason" alone,
    because later runs read it again (DESIGN_output_verbosity.md §9)."""

    ADAPT_FULL = "AT MOST 3 SENTENCES"
    ADAPT_TERSE = "MOST 2 SHORT SENTENCES"
    CHANGE_REASON_CAP = "a single sentence of at most 20 words"

    def test_off_asks_for_the_full_summary(self):
        system, _user = build_prompt()
        self.assertIn(self.ADAPT_FULL, system)
        self.assertNotIn(self.ADAPT_TERSE, system)
        system, _user = build_generate_prompt()
        self.assertIn("MOST 4 SENTENCES", system)

    def test_on_halves_the_summary_of_adapt_and_tweak(self):
        for extra in ({}, {"tweak": True, "athlete_message": "swap Thursday and Friday"}):
            with self.subTest(extra=list(extra)):
                system, _user = build_prompt(terse=True, **extra)
                self.assertIn(self.ADAPT_TERSE, system)
                self.assertNotIn(self.ADAPT_FULL, system)
                self.assertIn(self.CHANGE_REASON_CAP, system)

    def test_on_halves_the_summary_of_generate(self):
        system, _user = build_generate_prompt(terse=True)
        self.assertIn("MOST 2 SENTENCES", system)
        self.assertNotIn("MOST 4 SENTENCES", system)


class TestTheGatesAreIndependent(unittest.TestCase):
    def test_one_feature_does_not_switch_the_other_on(self):
        system, user = build_prompt(athlete_message="sore knee")
        self.assertNotIn(DRIFT_INSTRUCTIONS, system + user)

        system, user = build_prompt(intensity_context="Z1 2h00")
        self.assertNotIn(NOTE_INSTRUCTIONS, system + user)

    def test_both_together_produce_both(self):
        system, user = build_prompt(
            athlete_message="sore knee", intensity_context="Z1 2h00"
        )
        whole = system + user
        for region in (NOTE_INSTRUCTIONS, NOTE_DATA, DRIFT_INSTRUCTIONS, DRIFT_DATA):
            with self.subTest(region=region):
                self.assertIn(region, whole)


class TestTheSchemaStaysWellFormed(unittest.TestCase):
    """The response schema is assembled from string fragments joined with commas, so a
    gated member is exactly where punctuation desyncs."""

    def test_the_schema_object_has_no_double_or_trailing_comma(self):
        for extra in ({}, {"athlete_message": "sore knee"}):
            with self.subTest(extra=list(extra)):
                system, _ = build_prompt(**extra)
                self.assertNotIn(",,", system)
                self.assertNotIn(",\n}", system)


class TestAlwaysOnSections(unittest.TestCase):
    """Not every shared section is gated — the move rule fires on almost every pass,
    so its failure mode is being absent, not being half-applied
    (DESIGN_adapt_task_prompt.md §2)."""

    def test_the_move_rule_and_its_field_are_always_on_in_the_adapt_task(self):
        # The section tells the model to name the slot a moved session came from, and
        # the schema member is where it names it. Either one alone is the
        # half-application that loses the session's history
        # (DESIGN_workout_revisions.md §11).
        for extra in ({}, {"athlete_message": "knee is sore"},
                      {"intensity_context": "Base 2 — focus \"volume\""}):
            with self.subTest(extra=sorted(extra)):
                system, _user = build_prompt(**extra)
                self.assertIn(MOVE_SECTION, system)
                self.assertIn(MOVE_SCHEMA_MEMBER, system)

    def test_the_moved_session_names_the_list_adapt_was_actually_shown(self):
        # Generate's copy of the field points at SESSIONS ALREADY STANDING, which adapt
        # is never sent: a shared field that named the wrong section would send the model
        # looking for a list that is not there.
        system, _user = build_prompt()
        self.assertIn(replaces_field("PLANNED WORKOUTS"), system)
        self.assertNotIn("SESSIONS ALREADY STANDING", system)


class TestTheStandingRules(unittest.TestCase):
    """Which rules the adapt TASK is given, asserted against the constants it is built
    from rather than against quoted prose: rewording a rule should not break a test
    whose subject is which rules are present."""

    def test_adapt_gets_five_standing_rules_including_the_two_named_ones(self):
        system, _user = build_prompt()
        self.assertIn(RULE_MOVE_FIRST, system)
        self.assertIn(RULE_MESOCYCLE_NOT_YOURS, system)
        # Adapt's other three are written inline at its call site — counted, not quoted,
        # so rewording one does not break a test about how many rules the model is given.
        rules = system.split("### STANDING RULES")[1].split("###")[0]
        self.assertIn("\n5. ", rules)
        self.assertNotIn("\n6. ", rules)

    def test_the_benchmark_section_is_present_whole(self):
        # Its closing line — that an unchanged benchmark is not returned — is what
        # makes `workout_revision_apply`'s `clear_benchmark` inference sound, so the
        # section must reach the prompt intact rather than paraphrased.
        system, _user = build_prompt()
        self.assertIn(benchmark_task(), system)


class TestStandingSessionsGate(unittest.TestCase):
    """`workout generate` must answer for the sessions the athlete has already been told
    about, so the instruction, the schema members that express an answer and the list
    itself are one gated region (DESIGN_plan_change_continuity.md §8)."""

    EASED = [{
        "date": "2026-06-05", "sport_type": "cycling", "title": "Easy Z2 Spin",
        "description": "[Easy Z2 Spin]\n40 min ERG-locked, no surges.",
        "duration_minutes": 40, "rpe": 3, "tss": 26,
        "planned_zone_currency": "power",
        "planned_zone1_sec": 600, "planned_zone2_sec": 1800,
        "adaptation_count": 1, "adapted_at": "2026-06-01",
        "original_duration_minutes": 90, "original_rpe": 7, "original_tss": 95,
        "modification_reason": "Cut to easy Z2 to shed intensity.",
    }]

    REGIONS_IN_SYSTEM = (
        STANDING_INSTRUCTIONS, STANDING_RULE, STANDING_KEEP_MEMBER,
        STANDING_DROP_MEMBER, STANDING_REPLACES_MEMBER, STANDING_REASON_MEMBER,
        STANDING_NOTE_MEMBER,
    )

    def test_a_standing_session_reaches_every_region_it_governs(self):
        system, user = build_generate_prompt(standing_workouts=self.EASED)
        for region in self.REGIONS_IN_SYSTEM:
            with self.subTest(region=region):
                self.assertIn(region, system)
        for region in (STANDING_DATA, STANDING_SCOPE):
            with self.subTest(region=region):
                self.assertIn(region, user)
        self.assertIn("Easy Z2 Spin", user, "the session itself must be in the data")

    def test_the_list_says_what_the_session_was_first_prescribed_as(self):
        """Load alone does not say the numbers are already reduced, and "do not compound"
        could not say from what. The first form can (§4.6)."""
        _system, user = build_generate_prompt(standing_workouts=self.EASED)
        self.assertIn(
            "[first prescribed as 90m, RPE 7, TSS 95 — eased once, most recently "
            "2 days ago]", user
        )
        self.assertIn("Cut to easy Z2 to shed intensity.", user)

    def test_the_list_carries_the_intensity_target(self):
        """Duration and TSS fold intensity away — 40min steady and 12min hard inside 40min
        read the same, and whether a day still fits the week is a question about zones."""
        _system, user = build_generate_prompt(standing_workouts=self.EASED)
        self.assertIn("Target: ~10min recovery, ~30min endurance", user)

    def test_a_keep_is_told_not_to_restate_the_target(self):
        """Showing the target invites a revised one back on a KEEP. `_resolve_standing`
        discards it, so the only cost is tokens — say so rather than pay it."""
        system, _user = build_generate_prompt(standing_workouts=self.EASED)
        self.assertIn('carries no "planned_zone_sec"', system)

    def test_a_standing_session_ships_its_description(self):
        """A revision should be minimal rather than re-invented, which needs the prose the
        session already carries (§4.6)."""
        _system, user = build_generate_prompt(standing_workouts=self.EASED)
        self.assertIn("ERG-locked, no surges.", user)

    def test_without_a_standing_session_none_of_them_appear(self):
        system, user = build_generate_prompt()
        whole = system + user
        for region in self.REGIONS_IN_SYSTEM + (STANDING_DATA, STANDING_SCOPE):
            with self.subTest(region=region):
                self.assertNotIn(region, whole)

    def test_an_empty_standing_list_counts_as_none(self):
        """A bare `workout generate` extends into empty days; it must not open a section
        that would then name no sessions."""
        system, user = build_generate_prompt(standing_workouts=[])
        self.assertNotIn(STANDING_INSTRUCTIONS, system + user)
        self.assertNotIn(STANDING_KEEP_MEMBER, system)

    def test_the_generate_schema_stays_well_formed_either_way(self):
        """The answer members are spliced ahead of `benchmark_type`, so their own trailing
        comma is what a bad splice loses and the object's last member runs on. (The schema
        mixes two annotation styles — comma after the value, or after the closing paren —
        so the member ahead of the splice is not asserted against one rule.)"""
        for standing in ([], self.EASED):
            with self.subTest(standing=bool(standing)):
                system, _user = build_generate_prompt(standing_workouts=standing)
                self.assertNotIn(",,", system)
                self.assertNotIn(",\n}", system)

        system, _user = build_generate_prompt(standing_workouts=self.EASED)
        schema = system.split('"workouts": [')[1].split("\n    }")[0]
        member = schema[schema.index('"keep"'):].split('\n      "')[0]
        self.assertTrue(member.rstrip().endswith(","), msg=repr(member))
        self.assertGreater(
            schema.index('"benchmark_type"'), schema.rindex('"change_reason"'),
            "the answer members must sit ahead of the object's last member",
        )


class TestPastConstraintsGate(unittest.TestCase):
    """A constraint that ended earlier in the mesocycle is why a week went quiet, and the
    coach cannot see those days any other way (DESIGN_plan_change_continuity.md §6.1)."""

    PAST = [{
        "id": 4, "title": "Ill", "start_date": "2026-05-25", "end_date": "2026-05-29",
        "description": "Chest infection.", "rest": 1,
    }]

    def test_a_past_constraint_reaches_both_regions(self):
        system, user = build_generate_prompt(past_constraints=self.PAST)
        self.assertIn(PAST_CONSTRAINTS_INSTRUCTIONS, system)
        self.assertIn(PAST_CONSTRAINTS_DATA, user)
        self.assertIn("Ill", user)

    def test_without_one_neither_appears(self):
        system, user = build_generate_prompt()
        whole = system + user
        self.assertNotIn(PAST_CONSTRAINTS_INSTRUCTIONS, whole)
        self.assertNotIn(PAST_CONSTRAINTS_DATA, whole)


class TestNeighbourSessionsGate(unittest.TestCase):
    """The week either side of the span, shown so a weekly rule counts it
    (DESIGN_mesocycle_boundary.md §7)."""

    NEIGHBOURS = [{
        "date": "2026-06-08", "sport_type": "strength_training", "title": "Monday lift",
        "description": "[Monday lift]", "duration_minutes": 60, "rpe": 6, "tss": 30,
    }]

    def test_a_neighbour_reaches_both_regions(self):
        system, user = build_generate_prompt(neighbour_workouts=self.NEIGHBOURS)
        self.assertIn(NEIGHBOUR_INSTRUCTIONS, system)
        self.assertIn(NEIGHBOUR_DATA, user)
        self.assertIn("Monday lift", user)

    def test_without_one_neither_appears(self):
        system, user = build_generate_prompt()
        whole = system + user
        self.assertNotIn(NEIGHBOUR_INSTRUCTIONS, whole)
        self.assertNotIn(NEIGHBOUR_DATA, whole)


# The optional inputs whose regions are asserted above.
GATES_WITH_A_TEST = {
    "athlete_message", "intensity_context", "standing_workouts", "past_constraints",
    "neighbour_workouts", "tweak", "tweak_dates", "terse",
}

# The rest of the two builders' optional inputs. Being here is not a claim that an input
# is harmless — only that nobody has written a gate test for it yet. It is a ledger, so
# `TestEveryOptionalPromptInputIsAccountedFor` can tell a *new* input from a known one.
GATES_WITHOUT_A_TEST = {
    # adapt
    "informational", "removed_workouts", "daily_signals", "performed",
    "pmc_warmup_cutoff", "pmc_context", "zone_currencies", "signal_vocabulary",
    "signal_earliest_date",
    # generate
    "num_days", "start_str", "metrics", "completed_activities", "baseline",
    "mesocycle_progress", "mesocycle_has_intensity", "anchor_history",
}

BUILDERS = ("_workout_adapt_logic", "_workout_generate_logic")


def _optional_inputs():
    """Every optional parameter of the two prompt builders, read off their signatures."""
    import inspect

    names = set()
    for builder in BUILDERS:
        signature = inspect.signature(getattr(CoachEngine, builder))
        names.update(
            parameter.name for parameter in signature.parameters.values()
            if parameter.default is not inspect.Parameter.empty
        )
    return names


class TestEveryOptionalPromptInputIsAccountedFor(unittest.TestCase):
    """A twelfth gate added to a 380-line builder must not pass unnoticed.

    The sentinels above cover three inputs; the builders take twenty. Reading the
    parameter list off the signatures means a new one fails here until someone decides
    whether it governs prompt regions and needs a gate test of its own — which is the
    safe direction for a list to rot in.
    """

    def test_a_new_builder_input_must_be_classified(self):
        declared = GATES_WITH_A_TEST | GATES_WITHOUT_A_TEST
        unclassified = sorted(_optional_inputs() - declared)
        self.assertEqual(
            unclassified, [],
            "these optional prompt inputs are new since this ledger was written. If one "
            "switches whole prompt regions on and off, give it a gate test above and add "
            "it to GATES_WITH_A_TEST; otherwise record it in GATES_WITHOUT_A_TEST: "
            f"{unclassified}",
        )

    def test_the_ledger_does_not_name_inputs_that_are_gone(self):
        declared = GATES_WITH_A_TEST | GATES_WITHOUT_A_TEST
        departed = sorted(declared - _optional_inputs())
        self.assertEqual(
            departed, [],
            f"the builders no longer take these; drop them from the ledger: {departed}",
        )

    def test_the_two_halves_of_the_ledger_do_not_overlap(self):
        self.assertEqual(GATES_WITH_A_TEST & GATES_WITHOUT_A_TEST, set())


if __name__ == "__main__":
    unittest.main()
