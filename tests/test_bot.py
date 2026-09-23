"""The Telegram front-end's pure modules: what a message means, what the bot draws,
and when the scheduler fires. None of it needs the telegram library.

`tests/test_chat_process.py` covers the process that uses them — `ChatBot`, its
handlers, and the state they share."""
import os
import sys
import unittest
from unittest import mock

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from stamind.chat import keyboards, replies, routing, scheduler


class ParseMessageTest(unittest.TestCase):
    def test_strips_leading_slash(self):
        self.assertEqual(routing.parse_message_to_argv("/status"), ["status"])

    def test_plain_text_is_a_command_too(self):
        self.assertEqual(routing.parse_message_to_argv("status"), ["status"])

    def test_subcommand_and_flags(self):
        self.assertEqual(
            routing.parse_message_to_argv("/workout list -d 1w"),
            ["workout", "list", "-d", "1w"],
        )

    def test_quoted_argument_kept_whole(self):
        self.assertEqual(
            routing.parse_message_to_argv('/workout adapt -m "tired today"'),
            ["workout", "adapt", "-m", "tired today"],
        )

    def test_strips_matching_bot_username_suffix(self):
        self.assertEqual(
            routing.parse_message_to_argv("/status@StamindBot", bot_username="StamindBot"),
            ["status"],
        )

    def test_strips_bot_suffix_when_username_unknown(self):
        self.assertEqual(routing.parse_message_to_argv("/status@SomeBot"), ["status"])

    def test_help_alone_maps_to_help_command(self):
        self.assertEqual(routing.parse_message_to_argv("/help"), ["help"])

    def test_help_with_command_maps_to_command_help(self):
        self.assertEqual(routing.parse_message_to_argv("help workout"), ["workout", "--help"])

    def test_blank_returns_none(self):
        self.assertIsNone(routing.parse_message_to_argv("   "))
        self.assertIsNone(routing.parse_message_to_argv("/"))

    def test_unbalanced_quotes_raise(self):
        with self.assertRaises(ValueError):
            routing.parse_message_to_argv('/workout adapt -m "oops')


class PromptProtocolTest(unittest.TestCase):
    """How a SM-PROMPT request becomes Telegram buttons, and a tap becomes an answer.

    The frame it arrives in is tested in test_sentinels.py, with the writer beside it.
    """

    def test_confirm_buttons_yes_no(self):
        rows = keyboards.prompt_buttons({"id": "p1", "type": "confirm"}, "ab12")
        labels = [label for row in rows for label, _ in row]
        datas = [data for row in rows for _, data in row]
        self.assertIn("✅ Yes", labels)
        self.assertEqual(datas, ["ab12:p1:y", "ab12:p1:n"])

    def test_danger_confirm_uses_warning_label(self):
        rows = keyboards.prompt_buttons({"id": "p1", "type": "confirm", "danger": True}, "ab12")
        self.assertEqual(rows[0][0][0], "⚠️ Confirm")

    def test_choose_buttons_one_per_choice(self):
        req = {"id": "p2", "type": "choose",
               "choices": [{"value": "demote", "label": "Demote"},
                           {"value": "keep", "label": "Keep"}]}
        rows = keyboards.prompt_buttons(req, "n0nce")
        self.assertEqual(len(rows), 2)
        self.assertEqual(rows[0][0], ("Demote", "n0nce:p2:demote"))

    def test_text_prompt_has_no_buttons(self):
        self.assertEqual(keyboards.prompt_buttons({"id": "p3", "type": "text"}, "n"), [])

    def test_callback_roundtrips_through_buttons(self):
        rows = keyboards.prompt_buttons({"id": "p1", "type": "confirm"}, "ab12")
        _, data = rows[0][0]
        self.assertEqual(keyboards.decode_callback(data), ("ab12", "p1", "y"))

    def test_decode_callback_rejects_malformed(self):
        self.assertIsNone(keyboards.decode_callback("only:two"))

    def test_format_prompt_message_strips_ansi(self):
        msg = replies.format_prompt_message({"message": "\033[33mProceed?\033[0m"})
        self.assertEqual(msg, "Proceed?")


class MenuCommandsTest(unittest.TestCase):
    def test_restart_is_advertised_in_the_command_menu(self):
        # Not treated as special: the teardown ends any live session cleanly, so a
        # mis-tap costs a reconnect, not work (DESIGN_bot_restart.md §7).
        names = [name for name, _ in keyboards.MENU_COMMANDS]
        self.assertIn("restart", names)
        self.assertIn("cancel", names)

    def test_simple_menu_keeps_cancel_reachable(self):
        names = [name for name, _ in keyboards.SIMPLE_MENU_COMMANDS]
        self.assertIn("cancel", names)


class UiSwitchTest(unittest.TestCase):
    """The /ui runtime persona switch (§5.6): bare form flips, explicit form sets,
    anything else reads as usage (None)."""

    def test_bare_ui_flips_the_current_mode(self):
        self.assertIs(routing.parse_ui_switch("ui", simple_now=False), True)
        self.assertIs(routing.parse_ui_switch("ui", simple_now=True), False)

    def test_explicit_arguments_set_the_mode_regardless_of_current(self):
        self.assertIs(routing.parse_ui_switch("ui simple", simple_now=True), True)
        self.assertIs(routing.parse_ui_switch("ui expert", simple_now=False), False)
        self.assertIs(routing.parse_ui_switch("ui on", simple_now=True), True)
        self.assertIs(routing.parse_ui_switch("ui off", simple_now=False), False)

    def test_unknown_or_extra_arguments_read_as_usage(self):
        self.assertIsNone(routing.parse_ui_switch("ui blorp", simple_now=False))
        self.assertIsNone(routing.parse_ui_switch("ui simple please", simple_now=False))

    def test_only_the_expert_menu_advertises_the_switch(self):
        # The simple menu stays the athlete's two entries; the §5.6 confirmation
        # lines teach the way back instead.
        self.assertIn("ui", [n for n, _ in keyboards.MENU_COMMANDS])
        self.assertNotIn("ui", [n for n, _ in keyboards.SIMPLE_MENU_COMMANDS])


class SimpleKeyboardTest(unittest.TestCase):
    """The §5.1 reply keyboard: labels map onto a fixed argv table, nothing else."""

    def test_labels_map_to_fixed_argv(self):
        self.assertEqual(
            keyboards.keyboard_action("📅 Today"),
            ("run", ["workout", "list", "-d", "today"]),
        )
        self.assertEqual(keyboards.keyboard_action("🗓 My week"), ("run", ["workout", "list"]))
        self.assertEqual(keyboards.keyboard_action("🎯 Goals"), ("run", ["goal", "list"]))
        self.assertEqual(keyboards.keyboard_action("🧭 My plan"), ("run", ["plan", "show"]))
        self.assertEqual(
            keyboards.keyboard_action("📈 Progress"), ("run", ["progress", "--chart"])
        )

    def test_capture_button_arms_instead_of_running(self):
        self.assertEqual(keyboards.keyboard_action("💬 Talk to me"), ("capture", None))

    def test_welcome_names_every_keyboard_label(self):
        """The welcome teaches the keyboard, so a relabelled button cannot drift
        out of it (§5.1)."""
        for label, _ in keyboards.SIMPLE_KEYBOARD:
            self.assertIn(label, keyboards.SIMPLE_WELCOME, label)

    def test_non_label_text_is_not_a_button(self):
        self.assertIsNone(keyboards.keyboard_action("show me my week"))
        self.assertIsNone(keyboards.keyboard_action(""))

    def test_surrounding_whitespace_is_tolerated(self):
        self.assertEqual(
            keyboards.keyboard_action("  📅 Today  "),
            ("run", ["workout", "list", "-d", "today"]),
        )

    def test_returned_argv_is_a_copy(self):
        kind, argv = keyboards.keyboard_action("📅 Today")
        argv.append("--verbose")
        self.assertEqual(
            keyboards.keyboard_action("📅 Today"),
            ("run", ["workout", "list", "-d", "today"]),
        )


class GymButtonTest(unittest.TestCase):
    """Which session the gym button carries, and what it says (DESIGN_gym_logger.md §6).

    The week here is the design's: Tuesday 2026-09-22 is "today", and the gym day two
    days out is Thursday 2026-09-24."""

    TUESDAY = "2026-09-22"
    THURSDAY = "2026-09-24"

    def session(self, day, prescribed=True, sport="strength_training"):
        sets = [{"exercise": "belt squat", "sets": 3, "reps_low": 4, "reps_high": 6}]
        return {"date": day, "sport_type": sport, "title": "Gym: lower body strength",
                "prescribed_sets": sets if prescribed else []}

    def test_today_is_offered_over_a_later_gym_day(self):
        today = self.session(self.TUESDAY)
        found = keyboards.gym_button([self.session(self.THURSDAY), today], self.TUESDAY)
        self.assertEqual(found, ("🏋️ Log today's gym", today))

    def test_the_next_gym_day_is_named_by_its_weekday(self):
        thursday = self.session(self.THURSDAY)
        found = keyboards.gym_button([thursday], self.TUESDAY)
        self.assertEqual(found, ("🏋️ Log Thursday's gym", thursday))

    def test_a_session_past_the_window_is_not_offered(self):
        """Today plus six days: the seventh waits for tomorrow's keyboard."""
        self.assertIsNotNone(keyboards.gym_button([self.session("2026-09-28")], self.TUESDAY))
        self.assertIsNone(keyboards.gym_button([self.session("2026-09-29")], self.TUESDAY))

    def test_yesterdays_gym_day_is_gone(self):
        self.assertIsNone(keyboards.gym_button([self.session("2026-09-21")], self.TUESDAY))

    def test_a_session_with_no_prescribed_sets_has_nothing_to_log(self):
        session = self.session(self.THURSDAY, prescribed=False)
        self.assertIsNone(keyboards.gym_button([session], self.TUESDAY))

    def test_another_sport_is_not_a_gym_day(self):
        session = self.session(self.THURSDAY, sport="cycling")
        self.assertIsNone(keyboards.gym_button([session], self.TUESDAY))

    def test_an_alias_spelling_still_reads_as_strength(self):
        """Older rows spell the sport `strength`; `canonical_sport` is what reconciles
        the two spellings everywhere else."""
        session = self.session(self.THURSDAY, sport="strength")
        self.assertIsNotNone(keyboards.gym_button([session], self.TUESDAY))

    def test_the_gym_row_sits_above_the_companion_labels(self):
        plain = keyboards.simple_keyboard_rows()
        withgym = keyboards.simple_keyboard_rows(("🏋️ Log today's gym", "https://x/#s=e30"))
        self.assertEqual(withgym[0], [("🏋️ Log today's gym", "https://x/#s=e30")])
        self.assertEqual(withgym[1:], plain)
        self.assertEqual(plain[0], ["📅 Today", "🗓 My week"])

    def test_the_gym_label_is_neither_a_command_nor_a_stale_tap(self):
        """Tapping it opens the page and sends no text, so nothing here should ever see
        it; if Telegram ever did deliver it as text, it must not run anything."""
        for label in ("🏋️ Log today's gym", "🏋️ Log Thursday's gym"):
            self.assertIsNone(keyboards.keyboard_action(label), label)
            self.assertFalse(keyboards.stale_keyboard_tap(label, simple_now=False), label)


class TwoLanesTest(unittest.TestCase):
    """The two lanes are taught, not discovered (§12.3). The surface has exactly two
    teachers — the help card and the per-message router echoes — and neither may promise
    a verbatim delivery that no tap performs."""

    def test_the_help_card_names_both_lanes(self):
        card = keyboards.SIMPLE_HELP
        self.assertIn("ask you first", card)             # the recording lane
        self.assertIn("in your own words", card)         # the coach lane
        self.assertIn("your coach", card)                # named as the app, per §5

    def test_the_echoes_say_which_inbox_took_the_message(self):
        self.assertNotEqual(
            routing.ROUTER_ECHO["add_constraint"], routing.ROUTER_ECHO["coach_message"]
        )
        self.assertIn("noting", routing.ROUTER_ECHO["add_constraint"])
        self.assertIn("passing that on", routing.ROUTER_ECHO["coach_message"])

    def test_the_rescue_echo_belongs_to_the_recording_lane(self):
        """The §5.2 window sends unroutable text to `bot capture note`, so its echo must
        not claim the coach heard the words as written."""
        self.assertIn("noting", routing.CAPTURE_RESCUE_ECHO)
        self.assertNotIn("as written", routing.CAPTURE_RESCUE_ECHO)

    def test_a_retired_row_says_so_rather_than_vanishing(self):
        """One live row per chat: the message behind a retired offer was already
        consumed by the capture, so silence there loses it twice (§12.3)."""
        self.assertIn("expired", keyboards.UI_STALE_TAP)
        self.assertIn("send it again", keyboards.UI_STALE_TAP)


class StaleKeyboardTest(unittest.TestCase):
    """A restart returns to config's persona while the phone keeps the §5.1 keyboard;
    a tap on it must reach the companion, not shlex (§5.6)."""

    def test_label_tapped_in_expert_is_a_stale_tap(self):
        for label, _ in keyboards.SIMPLE_KEYBOARD:
            self.assertTrue(keyboards.stale_keyboard_tap(label, simple_now=False), label)

    def test_nothing_is_stale_while_simple(self):
        for label, _ in keyboards.SIMPLE_KEYBOARD:
            self.assertFalse(keyboards.stale_keyboard_tap(label, simple_now=True), label)

    def test_expert_typing_is_untouched(self):
        self.assertFalse(keyboards.stale_keyboard_tap("workout list", simple_now=False))
        self.assertFalse(keyboards.stale_keyboard_tap("/ui", simple_now=False))
        self.assertFalse(keyboards.stale_keyboard_tap("", simple_now=False))


class GuardrailTest(unittest.TestCase):
    """§7/§12.9: buttons and router intents reach read-only views, `adapt -m`, the two
    companion pickers (whose leaves offer single-ID `constraint rm` / `goal rm` — pinned
    in tests/test_cli_bot.py) and the capture command, which asks before it writes.
    Nothing plan-shaping, expensive or irreversible is reachable without typing."""

    ALLOWED_PREFIXES = {
        ("workout", "list"), ("workout", "compare"), ("goal", "list"), ("plan", "show"),
        ("progress", "--chart"), ("bot", "constraints"), ("bot", "goals"),
        ("bot", "capture"),
    }

    def test_capture_intents_reach_only_the_capture_command(self):
        for intent, captured_as in routing.ROUTER_CAPTURE_INTENTS.items():
            argv = ["bot", "capture", captured_as, "some message"]
            self.assertIn(tuple(argv[:2]), self.ALLOWED_PREFIXES, intent)

    def test_the_captures_own_offers_stay_inside_the_guardrail(self):
        """The two buttons a capture emits, and the picker leaf that re-enters it: none
        may reach a command the router itself could not (§12.9)."""
        from stamind.cli.bot.extraction import (
            adjust_week_button, send_to_coach_button,
        )
        adjust = routing.parse_message_to_argv(adjust_week_button()["send"])
        self.assertEqual(adjust, ["workout", "adapt"])
        # The coach lane carries her words verbatim through one -m, quoting and all.
        message = "knee's sore; \"no running\" for 2 weeks"
        to_coach = routing.parse_message_to_argv(send_to_coach_button(message)["send"])
        self.assertEqual(to_coach, ["workout", "adapt", "-m", message])

    def test_keyboard_argv_stays_read_only(self):
        for label, argv in keyboards.SIMPLE_KEYBOARD:
            if argv is None:
                continue
            self.assertIn(tuple(argv[:2]), self.ALLOWED_PREFIXES, label)

    def test_a_look_back_never_stamps_the_calendar(self):
        """`workout compare` writes adherence tags to Calendar events unless told not
        to; from a tap or a routed message it is a read (§5.1)."""
        argvs = [argv for _, argv in keyboards.SIMPLE_KEYBOARD if argv]
        argvs += list(routing.ROUTER_INTENT_ARGV.values())
        compares = [argv for argv in argvs if argv[:2] == ["workout", "compare"]]
        self.assertTrue(compares)
        for argv in compares:
            self.assertIn("--no-mark", argv)

    def test_router_argv_stays_read_only(self):
        for intent, argv in routing.ROUTER_INTENT_ARGV.items():
            self.assertIn(tuple(argv[:2]), self.ALLOWED_PREFIXES, intent)

    def test_morning_button_utterances_reach_only_adapt_m(self):
        from stamind.cli.bot.views import MORNING_BUTTONS

        def leaves(buttons):
            for b in buttons:
                if b.get("menu"):
                    yield from leaves(b["menu"])
                else:
                    yield b

        sends = [b["send"] for b in leaves(MORNING_BUTTONS) if b.get("send")]
        self.assertTrue(sends)
        for utterance in sends:
            argv = routing.parse_message_to_argv(utterance)
            self.assertEqual(argv[:2], ["workout", "adapt"], utterance)
            self.assertIn("-m", argv)
            self.assertNotIn("-y", argv)


class RouterTablesTest(unittest.TestCase):
    """`stamind/chat/routing.py` holds both halves: the names the model may pick, and
    what each name runs. They have to agree name for name, so this pins the one file
    against itself (§5.3, reshaped by the writes pass §12.10)."""

    # The two note intents share one inbox. They run the same argv and differ only in
    # the echo, so a misroute between them changes what the athlete is told the coach
    # heard, never what is stored (§12.3).
    NOTE_INTENTS = {"add_constraint", "add_signal"}
    # Intents the bot answers itself.
    SPECIAL = {"help", "unclear"}

    def test_every_cli_intent_lands_somewhere_in_the_bot(self):
        for intent in routing.ROUTER_INTENTS:
            self.assertTrue(
                intent in routing.ROUTER_INTENT_ARGV
                or intent in routing.ROUTER_CAPTURE_INTENTS
                or intent in routing.ROUTER_MESSAGE_ARGV
                or intent in self.SPECIAL, intent
            )

    def test_bot_tables_name_no_unknown_intent(self):
        for intent in (list(routing.ROUTER_INTENT_ARGV) + list(routing.ROUTER_ECHO)
                       + list(routing.ROUTER_CAPTURE_INTENTS) + list(routing.ROUTER_MESSAGE_ARGV)):
            self.assertIn(intent, routing.ROUTER_INTENTS)

    def test_every_capture_intent_reaches_the_capture_command(self):
        from stamind.cli.bot.capture import CAPTURE_INTENTS
        for intent, captured_as in routing.ROUTER_CAPTURE_INTENTS.items():
            self.assertIn(intent, routing.ROUTER_INTENTS, intent)
            self.assertIn(captured_as, CAPTURE_INTENTS, intent)
            # A capture carries the message, so it can own no fixed argv (§12.2).
            self.assertNotIn(intent, routing.ROUTER_INTENT_ARGV, intent)
            self.assertIn(intent, routing.ROUTER_ECHO, intent)

    def test_note_intents_share_one_inbox_and_differ_only_in_the_echo(self):
        landings = {routing.ROUTER_CAPTURE_INTENTS[i] for i in self.NOTE_INTENTS}
        self.assertEqual(landings, {"note"})
        echoes = [routing.ROUTER_ECHO[i] for i in self.NOTE_INTENTS]
        self.assertEqual(len(set(echoes)), len(echoes))

    def test_the_two_coach_lanes_carry_the_words_to_different_commands(self):
        """State goes to the coach verbatim, records go to capture, which transcribes
        (§12.3). How the athlete is goes to `workout adapt`; a change they decided goes to
        `workout tweak` (DESIGN_workout_tweak.md §3.4). Both carry the text, so neither
        owns a fixed argv."""
        self.assertEqual(
            routing.ROUTER_MESSAGE_ARGV["coach_message"], ["workout", "adapt", "-m"]
        )
        self.assertEqual(routing.ROUTER_MESSAGE_ARGV["tweak_session"], ["workout", "tweak"])
        for intent in routing.ROUTER_MESSAGE_ARGV:
            self.assertNotIn(intent, routing.ROUTER_INTENT_ARGV, intent)
            self.assertNotIn(intent, routing.ROUTER_CAPTURE_INTENTS, intent)
            self.assertIn(intent, routing.ROUTER_ECHO, intent)


class UiCallbackTest(unittest.TestCase):
    def test_roundtrips(self):
        data = keyboards.ui_callback_data("abc123", "2.1")
        self.assertEqual(keyboards.decode_ui_callback(data), ("abc123", "2.1"))

    def test_rejects_malformed_and_foreign_namespaces(self):
        self.assertIsNone(keyboards.decode_ui_callback("nonce:p1:y"))
        self.assertIsNone(keyboards.decode_ui_callback("ui:onlytoken"))
        self.assertIsNone(keyboards.decode_ui_callback(""))
        self.assertIsNone(keyboards.decode_ui_callback("ui::2"))

    def test_resolves_top_level_and_menu_paths(self):
        buttons = [
            {"label": "A", "ack": "ok"},
            {"label": "B", "menu": [{"label": "B1", "send": "status"}]},
        ]
        self.assertEqual(keyboards.resolve_ui_action(buttons, "0")["label"], "A")
        self.assertEqual(keyboards.resolve_ui_action(buttons, "1.0")["label"], "B1")

    def test_unresolvable_paths_return_none(self):
        buttons = [{"label": "A"}]
        self.assertIsNone(keyboards.resolve_ui_action(buttons, "5"))
        self.assertIsNone(keyboards.resolve_ui_action(buttons, "0.0"))
        self.assertIsNone(keyboards.resolve_ui_action(buttons, "0.0.0"))
        self.assertIsNone(keyboards.resolve_ui_action(buttons, "x"))

    def test_morning_buttons_fit_telegrams_64_byte_callback_cap(self):
        from stamind.cli.bot.views import MORNING_BUTTONS
        token = "aabbcc"  # secrets.token_hex(3) width
        rows = keyboards.ui_button_rows(MORNING_BUTTONS, token)
        for i, button in enumerate(MORNING_BUTTONS):
            for menu_row in keyboards.ui_menu_rows(button.get("menu") or [], token, str(i)):
                rows.append(menu_row)
        for row in rows:
            for _label, data in row:
                self.assertLessEqual(len(data.encode()), 64, data)

    def test_top_level_renders_one_row_menu_one_per_line(self):
        buttons = [{"label": "A"}, {"label": "B"}, {"label": "C"}]
        self.assertEqual(len(keyboards.ui_button_rows(buttons, "t")), 1)
        self.assertEqual(len(keyboards.ui_menu_rows(buttons, "t", "2")), 3)

    def test_a_fourth_button_wraps_and_keeps_its_flat_position(self):
        """The morning push gains one when the schedule is running out
        (DESIGN_runway_nudge.md §6); four across would shrink all four past reading."""
        buttons = [{"label": c} for c in "ABCD"]
        rows = keyboards.ui_button_rows(buttons, "t")
        self.assertEqual([len(r) for r in rows], [3, 1])
        self.assertEqual(rows[1][0][1], keyboards.ui_callback_data("t", "3"))


class StopButtonTest(unittest.TestCase):
    """The ✋ Stop button raised over a coach call (DESIGN_bot_stop_button.md)."""

    def test_callback_roundtrips(self):
        self.assertEqual(
            keyboards.decode_stop_callback(keyboards.stop_callback_data("a1b2")), "a1b2"
        )

    def test_rejects_malformed_and_foreign_namespaces(self):
        for data in ("", "stop", "stop:", "ui:tok:2", "nonce:p1:y", "stop:a:b"):
            self.assertIsNone(keyboards.decode_stop_callback(data), data)

    def test_a_stop_tap_is_never_read_as_a_prompt_answer(self):
        """§7: the two namespaces share one callback channel, so neither may decode the
        other's data into something actionable."""
        data = keyboards.stop_callback_data("a1b2")
        self.assertIsNone(keyboards.decode_callback(data))
        self.assertIsNone(keyboards.decode_ui_callback(data))

    def test_a_prompt_answer_is_never_read_as_a_stop_tap(self):
        rows = keyboards.prompt_buttons({"id": "p1", "type": "confirm"}, "nonce")
        for _label, data in rows[0]:
            self.assertIsNone(keyboards.decode_stop_callback(data), data)

    def test_fits_telegrams_64_byte_callback_cap(self):
        data = keyboards.stop_callback_data("aabbccdd")  # secrets.token_hex(4) width
        self.assertLessEqual(len(data.encode()), 64, data)


class PushScheduleTest(unittest.TestCase):
    """`next_push_delay` — the §4.3 send/catch-up window arithmetic."""

    def _at(self, hour, minute=0):
        import datetime as dt
        return dt.datetime(2026, 8, 25, hour, minute)

    def test_before_the_window_waits_for_morning(self):
        self.assertEqual(scheduler.next_push_delay(self._at(6), "08:00", "15:00"), 7200.0)

    def test_inside_the_window_fires_now(self):
        self.assertEqual(scheduler.next_push_delay(self._at(8), "08:00", "15:00"), 0.0)
        self.assertEqual(scheduler.next_push_delay(self._at(14, 59), "08:00", "15:00"), 0.0)

    def test_past_the_deadline_skips_to_tomorrow(self):
        delay = scheduler.next_push_delay(self._at(16), "08:00", "15:00")
        self.assertEqual(delay, 16 * 3600.0)  # 16:00 → 08:00 next day

    def test_unparseable_times_fall_back_to_defaults(self):
        self.assertEqual(scheduler.next_push_delay(self._at(9), "morning!", "nope"), 0.0)
        self.assertEqual(scheduler.next_push_delay(self._at(6), "25:99", ""), 7200.0)

    def test_deadline_before_morning_means_no_catchup(self):
        delay = scheduler.next_push_delay(self._at(9), "08:00", "07:00")
        self.assertGreater(delay, 0)  # window already closed for the day


class SchedulerWakeTest(unittest.IsolatedAsyncioTestCase):
    """One wake of the scheduler: due reminders, the nightly reflect, then the push
    (DESIGN_athlete_queue.md §6.5, DESIGN_learning_doubt_nudge.md §3.1)."""

    def setUp(self):
        import datetime as dt
        self.now = dt.datetime(2026, 9, 16, 8, 0).astimezone()  # a Wednesday
        patches = [
            mock.patch.object(scheduler, "athlete_now", side_effect=lambda: self.now),
            mock.patch.object(scheduler, "forget_timezone"),
            mock.patch.object(scheduler.settings, "morning_time", return_value="08:00"),
            mock.patch.object(scheduler.settings, "morning_deadline", return_value="15:00"),
            mock.patch.object(scheduler.settings, "push_enabled", return_value=True),
            mock.patch.object(scheduler.athlete_queue, "reminders_due", return_value=True),
            mock.patch.object(scheduler.heads_up, "changes_due", return_value=False),
        ]
        for patcher in patches:
            patcher.start()
            self.addCleanup(patcher.stop)
        self.ran = []
        self.reflects = []
        self.last_run = {}

    async def run_command(self, argv, wait):
        self.ran.append((argv, wait))

    def reflect(self):
        self.reflects.append(self.now.strftime("%a %H:%M"))

    async def wake(self, simple=True, busy=False):
        return await scheduler.scheduler_wake(
            self.last_run, simple, lambda: busy, self.run_command, self.reflect
        )

    async def test_a_due_reminder_goes_out_before_the_push_on_the_same_wake(self):
        await self.wake()
        self.assertEqual(self.ran, [
            (["bot", "queue", "--remind"], True), (["bot", "morning"], False),
        ])
        self.assertEqual(self.last_run["push"], "2026-09-16")

    async def test_reminders_go_out_whatever_the_persona_and_the_push_switch(self):
        with mock.patch.object(scheduler.settings, "push_enabled", return_value=False):
            await self.wake()
        await self.wake(simple=False)
        self.assertEqual(self.ran, [(["bot", "queue", "--remind"], True)] * 2)

    async def test_a_busy_chat_leaves_the_reminder_to_the_next_wake(self):
        pause = await self.wake(busy=True)
        self.assertEqual(self.ran, [])
        self.assertEqual((self.last_run.get("push"), pause), (None, 180))

    async def test_reflect_starts_once_a_night_from_wednesday_to_sunday(self):
        import datetime as dt
        for day in range(14, 21):  # Monday 14 to Sunday 20 September
            for hour, minute in ((2, 55), (3, 0), (3, 5), (8, 0)):
                self.now = dt.datetime(2026, 9, day, hour, minute).astimezone()
                await self.wake()
        self.assertEqual(self.reflects, [
            "Wed 03:00", "Thu 03:00", "Fri 03:00", "Sat 03:00", "Sun 03:00",
        ])
        self.assertNotIn("data", [argv[0] for argv, _ in self.ran])

    async def test_reflect_leaves_the_chat_to_the_push(self):
        """Started outside the chat, reflect neither waits for a busy chat nor holds up a
        push due on the same wake, as after the bot was down overnight."""
        await self.wake(busy=True)
        self.assertEqual(self.reflects, ["Wed 08:00"])
        await self.wake()
        self.assertEqual(self.reflects, ["Wed 08:00"])
        self.assertIn((["bot", "morning"], False), self.ran)

    async def test_the_expert_persona_has_no_nightly_reflect(self):
        import datetime as dt
        self.now = dt.datetime(2026, 9, 16, 3, 0).astimezone()
        await self.wake(simple=False)
        self.assertEqual(self.reflects, [])

    async def test_changes_go_out_after_reminders_and_before_the_push(self):
        """DESIGN_change_heads_up.md §4: waited for, so the push finds the chat free."""
        with mock.patch.object(scheduler.heads_up, "changes_due", return_value=True):
            await self.wake()
        self.assertEqual(self.ran, [
            (["bot", "queue", "--remind"], True), (["bot", "changes"], True),
            (["bot", "morning"], False),
        ])

    async def test_changes_go_out_with_the_push_switched_off(self):
        with mock.patch.object(scheduler.heads_up, "changes_due", return_value=True), \
                mock.patch.object(scheduler.settings, "push_enabled", return_value=False):
            await self.wake()
        self.assertIn((["bot", "changes"], True), self.ran)
        self.assertNotIn((["bot", "morning"], False), self.ran)

    async def test_a_busy_chat_leaves_the_changes_to_the_next_wake(self):
        with mock.patch.object(scheduler.heads_up, "changes_due", return_value=True):
            await self.wake(busy=True)
        self.assertEqual(self.ran, [])


class QueueProtocolTest(unittest.TestCase):
    """The `q:` buttons of a queued item (DESIGN_athlete_queue.md §6.2).

    They are their own namespace: no button token and no Stop nonce reads them, so a
    tap on an item neither retires nor answers the morning row.
    """

    def test_an_items_buttons_become_rows_carrying_its_id_and_the_walk_start(self):
        """Each button of a queued item becomes a `q:<id>:<action>:<since>` tap.

        The item's id and the walk's start travel in the callback data rather than in
        anything the bot remembers, which is what lets it forget the item entirely
        (DESIGN_athlete_queue.md §6.2)."""
        req = {
            "id": 12,
            "text": "🙋 Quick question (1 left)\nWhat was it?",
            "buttons": [{"label": "Leg press", "action": "a2"},
                        {"label": "🕐 Not now", "action": "n"}],
            "since": "1789538400",
        }
        self.assertEqual(keyboards.queue_button_rows(req), [[
            ("Leg press", "q:12:a2:1789538400"),
            ("🕐 Not now", "q:12:n:1789538400"),
        ]])

    def test_more_buttons_than_fit_are_chunked_into_rows(self):
        """The same width the morning row uses, so an item does not read as a wall."""
        req = {
            "id": 3, "since": "1789538400",
            "buttons": [{"label": f"a{i}", "action": f"a{i}"}
                        for i in range(keyboards.UI_BUTTONS_PER_ROW + 1)],
        }
        rows = keyboards.queue_button_rows(req)
        self.assertEqual(len(rows), 2)
        self.assertEqual(len(rows[0]), keyboards.UI_BUTTONS_PER_ROW)
        self.assertEqual(len(rows[1]), 1)

    def test_callback_roundtrips_inside_telegrams_64_bytes(self):
        data = keyboards.queue_callback_data(123456, "a12", "r1789538400")
        self.assertEqual(keyboards.decode_queue_callback(data), ("123456", "a12", "r1789538400"))
        self.assertLessEqual(len(data.encode()), 64)

    def test_decode_rejects_anything_but_a_queue_tap(self):
        for data in ("ui:ab12:0", "stop:ab12", "q:12:a2", "q:x:a2:1", "q:12:a-2:1",
                     "q:12:a2:1789 --remind", "q:12:a2:x1", "q:12::1"):
            self.assertIsNone(keyboards.decode_queue_callback(data), data)

    def test_a_queue_tap_leaves_the_live_button_row_alone(self):
        """The item's buttons are their own namespace: no SM-BUTTONS token or Stop nonce
        reads them, so a tap neither retires nor answers the morning row (§6.2)."""
        data = keyboards.queue_callback_data(12, "a1", "1789538400")
        self.assertIsNone(keyboards.decode_ui_callback(data))
        self.assertIsNone(keyboards.decode_stop_callback(data))

    def test_not_now_swaps_in_the_three_later_choices_from_the_tap(self):
        self.assertEqual(keyboards.queue_later_rows("12", "1789538400"), [[
            ("⏰ In 1 hour", "q:12:h:1789538400"),
            ("⏰ In 1 day", "q:12:t:1789538400"),
            ("↩️ After the others", "q:12:b:1789538400"),
        ]])

    def test_the_echo_names_the_button_that_was_tapped(self):
        rows = [[("Belt squat", "q:1:a1:5"), ("Leg press", "q:1:a2:5")]]
        self.assertEqual(keyboards.tapped_label(rows, "q:1:a2:5"), "Leg press")
        self.assertIsNone(keyboards.tapped_label(rows, "q:1:a3:5"))


if __name__ == "__main__":
    unittest.main()
