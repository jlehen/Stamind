"""The line protocol between the CLI and a chat front-end.

When the bot runs a command it reads that command's stdout. Most of what comes back is
prose to post in the chat, but some lines are control traffic: a question the command
wants answered, a chart it has rendered, a row of buttons to offer, a marker saying
"send what you have so far", an item from the athlete queue. Those lines begin with the
byte ``\\x1e`` (ASCII record-separator), which never appears in normal output, so a
front-end can tell the two apart whatever a command prints. Each carries a tag and one
JSON object:

    \\x1eTM-PROMPT  {"v": 1, "id": …, "type": "confirm", "message": …}   answer expected
    \\x1eTM-PHOTO   {"path": …, "caption": …}                            one-way
    \\x1eTM-BUTTONS {"buttons": [{"label": …, "send"|"ack"|"menu": …}]}   one-way
    \\x1eTM-FLUSH   {} or {"wait": false}                                one-way
    \\x1eTM-QUEUE   {"id": …, "text": …, "buttons": […], "since": …}      one-way

Both ends of every frame live here: the CLI writes with the `emit_*` functions, the bot
reads with `parse_frame`, and the answer it sends back is built by `prompt_answer`. They
were in two files, and each frame's fields were documented twice — which is how a field
added on one side goes unread on the other.

Standard library only. `prompt.py` holds the question broker that sits on top of this.
"""
import json
import os
import sys
from typing import Any, Dict, Optional, Sequence, Tuple

# Any \x1e-prefixed line is framing, whether or not this build knows the tag. A bot that
# meets a tag from a newer CLI drops the line rather than posting raw protocol bytes as
# chat text, so a stale front-end degrades to a missing feature (DESIGN_progress_timeline.md
# §7.2).
SENTINEL_PREFIX = "\x1e"

PROMPT_PROTOCOL_VERSION = 1

# A question, and the only frame that expects an answer back on the process's stdin.
PROMPT_SENTINEL = "\x1eTM-PROMPT "
# Where a rendered chart landed. The caption travels in the payload because the
# front-end must not re-parse forwarded chat text (DESIGN_progress_timeline.md §7.2).
PHOTO_SENTINEL = "\x1eTM-PHOTO "
# A non-blocking inline-button row attached to the output just flushed. Prompts ask and
# wait; buttons offer and exit — the CLI keeps deciding WHAT to offer, the front-end only
# renders (DESIGN_bot_simple_frontend.md §4.4).
BUTTONS_SENTINEL = "\x1eTM-BUTTONS "
# A payload-free "send what you have buffered" marker. The others flush the chat as a
# side effect of doing something else; this one exists only to flush, so a command about
# to go quiet for an LLM call can deliver its setup first instead of letting it arrive
# glued to the answer (DESIGN_output_verbosity.md §7).
FLUSH_SENTINEL = "\x1eTM-FLUSH "
# One item of the athlete queue, sent as a message of its own whose buttons carry the
# item id. It replaces no button row and no row replaces it, so the bot remembers nothing
# about it (DESIGN_athlete_queue.md §6.2).
QUEUE_SENTINEL = "\x1eTM-QUEUE "

_SENTINELS = (
    PROMPT_SENTINEL, PHOTO_SENTINEL, BUTTONS_SENTINEL, FLUSH_SENTINEL, QUEUE_SENTINEL,
)


def is_json_frontend(frontend: Optional[str] = None) -> bool:
    """Whether this run is driven by a front-end that speaks this protocol.

    `TRAINMATE_FRONTEND=json` is set by the bot on the commands it spawns. Off a terminal
    but without it — a cron run, a piped command — the answer is False: nothing is there
    to read a frame."""
    if frontend is None:
        frontend = os.environ.get("TRAINMATE_FRONTEND", "")
    return frontend.lower() == "json"


def _write(sentinel: str, payload: Dict[str, Any], out) -> None:
    """One frame, on a line of its own, flushed — the front-end reads line by line."""
    if out is None:
        out = sys.stdout
    out.write(sentinel + json.dumps(payload) + "\n")
    out.flush()


def emit_photo(path: str, caption: Optional[str] = None, out=None) -> None:
    """Tells the front-end a chart is ready at `path`, with the caption to post above it."""
    _write(PHOTO_SENTINEL, {"path": path, "caption": caption}, out)


def emit_buttons(buttons: Sequence[dict], out=None) -> None:
    """Offers a row of buttons. Each is ``{"label": …}`` plus exactly one of: ``send``
    (a canned utterance the front-end feeds back through its normal command pipeline when
    tapped), ``ack`` (a short reply text; nothing runs), or ``menu`` (a nested list of
    send/ack buttons) — DESIGN_bot_simple_frontend.md §4.4."""
    _write(BUTTONS_SENTINEL, {"buttons": list(buttons)}, out)


def emit_flush(out=None, wait: bool = True) -> None:
    """Ends the message being buffered, so what follows arrives as a new one.

    Does nothing on a terminal, where output already reaches the screen line by line. The
    front-end test lives here rather than at each call site because a flush has no meaning
    outside a buffering front-end (DESIGN_output_verbosity.md §7).

    `wait=False` says no wait follows this marker — it merely ends a message — so the bot
    hangs no Stop button on it (DESIGN_change_heads_up.md §4)."""
    if not is_json_frontend():
        return
    _write(FLUSH_SENTINEL, {} if wait else {"wait": False}, out)


def emit_queue_item(
    item_id: int, text: str, buttons: Sequence[dict], since: str, out=None
) -> None:
    """Sends one queued item. Its buttons are ``{"label", "action"}`` and `since` is the
    walk's start in epoch seconds, ``r``-prefixed for a walk of one
    (DESIGN_athlete_queue.md §6.2)."""
    _write(
        QUEUE_SENTINEL,
        {"id": item_id, "text": text, "buttons": list(buttons), "since": since},
        out,
    )


def parse_frame(line: str) -> Optional[Tuple[str, Any]]:
    """One line of CLI output as `(tag, payload)`, or None when it is ordinary prose.

    The tag is the sentinel constant itself, so a caller compares against the same name
    the writer used. It comes back as a pair rather than as the payload alone because a
    TM-FLUSH payload is legitimately ``{}``, and a bare falsy dict reads as "not a frame"
    at every call site.

    A frame whose JSON does not parse is not a frame. The caller still sees the
    `SENTINEL_PREFIX` on the raw line and drops it, which is also what happens to a tag
    this build does not know.
    """
    for sentinel in _SENTINELS:
        if not line.startswith(sentinel):
            continue
        try:
            return sentinel, json.loads(line[len(sentinel):])
        except json.JSONDecodeError:
            return None
    return None


def flush_wants_a_wait(payload: Any) -> bool:
    """Whether a flush marker announces a wait, and so earns a Stop button. Only
    ``{"wait": false}`` says no (DESIGN_change_heads_up.md §4)."""
    return not isinstance(payload, dict) or payload.get("wait", True) is not False


def prompt_answer(
    prompt_id: Any, *, answer: Any = None, cancelled: bool = False
) -> Dict[str, Any]:
    """The reply to a TM-PROMPT, as the CLI's `JsonPrompt` expects to read it back.

    Exactly one of the two outcomes rides on it: an `answer` the athlete gave, or
    `cancelled` when they walked away, the bot restarted, or the question timed out. The
    six places the bot answers from used to build this dict by hand.
    """
    frame: Dict[str, Any] = {"v": PROMPT_PROTOCOL_VERSION, "id": prompt_id}
    if cancelled:
        frame["cancelled"] = True
    else:
        frame["answer"] = answer
    return frame
