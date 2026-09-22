"""The line protocol between the CLI and a chat front-end (stamind/sentinels.py).

Both ends are here, because a frame only works if the writer and the reader agree: each
test writes with the `emit_*` the CLI calls and reads with the `parse_frame` the bot
calls. When the two lived in two files these were round-trips across a file boundary,
and the tag each reader matched was a constant it happened to import.
"""
import io
import os
import unittest
from unittest import mock

from stamind.sentinels import (
    BUTTONS_SENTINEL, FLUSH_SENTINEL, PHOTO_SENTINEL, PROMPT_PROTOCOL_VERSION,
    PROMPT_SENTINEL, QUEUE_SENTINEL, SENTINEL_PREFIX, emit_buttons, emit_flush,
    emit_photo, emit_queue_item, flush_wants_a_wait, parse_frame, prompt_answer,
)


def _emitted(emit, *args, **kwargs) -> str:
    """One frame as the bot reads it: a single line, split on \\n alone.

    Not `splitlines()`: \\x1e is itself a `str.splitlines` boundary, while the bot reads
    byte lines split on \\n.
    """
    out = io.StringIO()
    emit(*args, out=out, **kwargs)
    return out.getvalue().split("\n")[0]


class TestEachFrameRoundTrips(unittest.TestCase):
    def test_a_photo_carries_its_path_and_caption(self):
        tag, payload = parse_frame(
            _emitted(emit_photo, "/tmp/chart.png", caption="FORM today   CTL 55")
        )
        self.assertEqual(tag, PHOTO_SENTINEL)
        self.assertEqual(payload["path"], "/tmp/chart.png")
        self.assertEqual(payload["caption"], "FORM today   CTL 55")

    def test_a_photo_with_no_caption_says_so_rather_than_omitting_it(self):
        _tag, payload = parse_frame(_emitted(emit_photo, "/tmp/chart.png"))
        self.assertIsNone(payload["caption"])

    def test_a_button_row_carries_its_buttons(self):
        tag, payload = parse_frame(
            _emitted(emit_buttons, [{"label": "A", "send": "status"}])
        )
        self.assertEqual(tag, BUTTONS_SENTINEL)
        self.assertEqual(payload["buttons"], [{"label": "A", "send": "status"}])

    def test_a_queued_item_carries_its_id_text_buttons_and_walk_start(self):
        tag, payload = parse_frame(_emitted(
            emit_queue_item, 12, "🙋 Quick question (1 left)\nWhat was it?",
            [{"label": "Leg press", "action": "a2"}, {"label": "🕐 Not now", "action": "n"}],
            "1789538400",
        ))
        self.assertEqual(tag, QUEUE_SENTINEL)
        self.assertEqual(payload["id"], 12)
        self.assertEqual(payload["text"], "🙋 Quick question (1 left)\nWhat was it?")
        self.assertEqual(payload["since"], "1789538400")
        # The buttons ride in the payload: a tap has to carry everything the bot
        # needs, because it stores nothing about the item (§6.2).
        self.assertEqual(payload["buttons"], [
            {"label": "Leg press", "action": "a2"},
            {"label": "🕐 Not now", "action": "n"},
        ])

    def test_a_flush_marker_round_trips_under_a_chat_front_end(self):
        with mock.patch.dict(os.environ, {"STAMIND_FRONTEND": "json"}):
            line = _emitted(emit_flush)
        tag, payload = parse_frame(line)
        self.assertEqual(tag, FLUSH_SENTINEL)
        self.assertEqual(payload, {})

    def test_a_terminal_gets_no_flush_marker_at_all(self):
        """Emitted unconditionally, the frame would land in the athlete's own scrollback
        as protocol bytes. The gate is inside `emit_flush`, not at its call sites."""
        out = io.StringIO()
        with mock.patch.dict(os.environ, {"STAMIND_FRONTEND": ""}):
            emit_flush(out=out)
        self.assertEqual(out.getvalue(), "")


class TestWhatIsAndIsNotAFrame(unittest.TestCase):
    def test_ordinary_output_is_not_a_frame(self):
        self.assertIsNone(parse_frame("All workouts wiped.\n"))

    def test_every_tag_is_claimed_by_itself_and_no_other(self):
        """Each tag gets its own branch in the bot's read loop. A reader that matched a
        sibling would swallow a prompt and hang the command waiting for an answer."""
        for sentinel in (PROMPT_SENTINEL, PHOTO_SENTINEL, BUTTONS_SENTINEL,
                         FLUSH_SENTINEL, QUEUE_SENTINEL):
            tag, _payload = parse_frame(sentinel + '{"id": "p1"}\n')
            self.assertEqual(tag, sentinel)

    def test_a_tag_this_build_does_not_know_is_not_a_frame_but_is_framing(self):
        """A newer CLI's tag: not a frame this build can act on, so the bot drops the
        line rather than posting raw protocol bytes as chat text."""
        line = '\x1eSM-FUTURE-THING {"x": 1}\n'
        self.assertIsNone(parse_frame(line))
        self.assertTrue(line.startswith(SENTINEL_PREFIX))

    def test_a_payload_that_does_not_parse_is_not_a_frame(self):
        self.assertIsNone(parse_frame(PROMPT_SENTINEL + "{not json\n"))

    def test_a_prompt_request_comes_back_whole(self):
        line = PROMPT_SENTINEL + '{"v":1,"id":"p1","type":"confirm","message":"go?"}\n'
        tag, payload = parse_frame(line)
        self.assertEqual(tag, PROMPT_SENTINEL)
        self.assertEqual(payload["id"], "p1")
        self.assertEqual(payload["type"], "confirm")

    def test_an_empty_flush_payload_is_still_a_frame(self):
        """`{}` is falsy, which is why `parse_frame` returns a pair and not the payload
        alone: a bare dict would read as "not a frame" at every call site."""
        frame = parse_frame(FLUSH_SENTINEL + "{}\n")
        self.assertIsNotNone(frame)
        self.assertEqual(frame[1], {})


class TestTheFlushWaitFlag(unittest.TestCase):
    """Only `{"wait": false}` says no wait follows, so no Stop button is offered
    (DESIGN_change_heads_up.md §4)."""

    def test_an_ordinary_flush_announces_a_wait(self):
        with mock.patch.dict(os.environ, {"STAMIND_FRONTEND": "json"}):
            _tag, payload = parse_frame(_emitted(emit_flush))
        self.assertTrue(flush_wants_a_wait(payload))

    def test_a_message_break_does_not(self):
        with mock.patch.dict(os.environ, {"STAMIND_FRONTEND": "json"}):
            _tag, payload = parse_frame(_emitted(emit_flush, wait=False))
        self.assertFalse(flush_wants_a_wait(payload))

    def test_a_payload_that_is_not_a_dict_is_read_as_announcing_one(self):
        self.assertTrue(flush_wants_a_wait("nonsense"))


class TestTheAnswerSentBack(unittest.TestCase):
    """`prompt_answer` builds the reply the CLI's JsonPrompt reads off its stdin. The
    bot answers from six places and used to write this dict by hand at each."""

    def test_an_answer_carries_the_value_and_no_cancellation(self):
        frame = prompt_answer("p1", answer="yes please")
        self.assertEqual(frame["v"], PROMPT_PROTOCOL_VERSION)
        self.assertEqual(frame["id"], "p1")
        self.assertEqual(frame["answer"], "yes please")
        self.assertNotIn("cancelled", frame)

    def test_a_cancellation_carries_no_answer(self):
        frame = prompt_answer("p1", cancelled=True)
        self.assertTrue(frame["cancelled"])
        self.assertNotIn("answer", frame)

    def test_a_false_answer_is_an_answer(self):
        """A confirm answered No is `False`, which must not read as "no answer"."""
        self.assertIs(prompt_answer("p1", answer=False)["answer"], False)


if __name__ == "__main__":
    unittest.main()
