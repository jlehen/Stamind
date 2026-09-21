"""What one chat message means: the router's intent table, both halves of it.

The model — through `tm bot route` — only ever picks a name out of `ROUTER_INTENTS`. The
three tables under it say what that name runs: fixed argv for a view or a picker, an argv
the athlete's words are appended to for the two coach lanes, or a `bot capture <intent>`
for the intents that need values read out of the message
(DESIGN_bot_simple_frontend.md §5.3, §12.8).

They are one table in one file because they have to agree name for name, and a test
checks that they do. Pure data and pure parsing: nothing here imports the telegram
library, and `tm bot route` reads `ROUTER_INTENTS` from here to build its prompt.
"""
import shlex
from typing import List, Optional

# The names the model may pick from, and what each one means to it (§5.3, widened by the
# writes pass — §12.8 is the authoritative table). `tm bot route` builds its prompt from
# this dict; the three tables under it say what each name runs.
ROUTER_INTENTS = {
    "show_today": "the athlete wants to see today's session or what to do today",
    "show_week": "the athlete wants to see the upcoming schedule / their week",
    "show_done": (
        "the athlete wants to look back at what they actually did — which sessions "
        "they completed or missed, how the last days went"
    ),
    "show_goals": (
        "the athlete wants to see their goals — what they are training for, or when "
        "the event is"
    ),
    "show_plan": (
        "the athlete wants the big picture of their training plan — the phases or "
        "mesocycles on the way to the goal, what comes after this week"
    ),
    "show_progress": "the athlete wants to see progress, fitness, stats or a chart",
    "coach_message": (
        "the athlete is telling the coach something about their state or availability "
        "(tired, sore, sick, busy, travelling, no equipment, ...), or that a planned "
        "ride, event or session has changed — its size, route or date"
    ),
    "tweak_session": (
        "the athlete asks for a change they have decided, to sessions they name — make "
        "one shorter, longer, easier or harder, another sport instead, other exercises, "
        "drop it, add one, move it, or swap two days ('make Thursday's ride 45 minutes', "
        "'step-ups instead of belt squats on Friday', 'add a swim on Sunday', 'swap "
        "Thursday and Friday')"
    ),
    "add_constraint": (
        "the athlete states a standing rule or restriction to remember going forward "
        "('no training on Wednesdays', 'I can't swim until June', 'keep Sundays free')"
    ),
    "add_signal": (
        "the athlete reports an outside cause that acted on their body on given days, "
        "the kind that explains a recovery reading ('three beers last night', 'the kid "
        "was up all night', 'it was 35 degrees all week')"
    ),
    "show_constraints": (
        "the athlete wants to see the rules or restrictions the coach is working around"
    ),
    "edit_constraint": (
        "the athlete changes one of those rules rather than adding or dropping it — its "
        "wording or its dates ('the knee thing runs to the end of the month', 'make it "
        "Tuesdays instead')"
    ),
    "remove_constraint": (
        "the athlete wants to drop or cancel one of those rules ('I can run again', "
        "'forget the Wednesday rule')"
    ),
    "add_goal": (
        "the athlete says what they want to train for next — a race, an event, a new "
        "target ('I signed up for a marathon in May', 'I'd like to do a triathlon next "
        "year')"
    ),
    "edit_goal": (
        "the athlete changes a goal they already have — its date, its name or what it "
        "is about ('move my marathon to October 12', 'the 10k is called off to the "
        "spring')"
    ),
    "remove_goal": (
        "the athlete is not doing one of their goals any more ('I'm not doing the 10k', "
        "'drop the marathon')"
    ),
    "change_setting": (
        "the athlete asks to change how the app behaves in this chat — when it messages "
        "in the morning, whether it does at all, or whether it asks about what it has "
        "learned about them ('can you message me at 7 instead?', 'stop the morning "
        "messages', 'stop asking me about that stuff')"
    ),
    "help": "the athlete asks what they can say or how this works",
    "unclear": "anything else, or too ambiguous to route",
}

CAPTURE_PROMPT = "I'm listening — what should I know? (or /cancel)"

ROUTER_FALLBACK = (
    "I didn't quite get that 🤔 — try one of the buttons below, or say it another way."
)


# What each of those names runs (§5.3). The model picks a name above and never argv, so
# a hostile or confused message cannot reach a flag this table does not expose. Views and
# pickers live here — fixed argv, no slots; help and unclear are answered by the bot.
ROUTER_INTENT_ARGV = {
    "show_today": ["workout", "list", "-d", "today"],
    "show_week": ["workout", "list"],
    "show_done": ["workout", "compare", "-d", "7d", "--no-mark"],
    "show_goals": ["goal", "list"],
    "show_plan": ["plan", "show"],
    "show_progress": ["progress", "--chart"],
    "show_constraints": ["bot", "constraints"],
    "remove_constraint": ["bot", "constraints"],
    "remove_goal": ["bot", "goals"],
}


# The two intents that carry the athlete's words to the coach, and the argv the text is
# appended to: how the athlete is goes to `workout adapt`, a change they decided goes to
# `workout tweak` (DESIGN_workout_tweak.md §3.4).
ROUTER_MESSAGE_ARGV = {
    "coach_message": ["workout", "adapt", "-m"],
    "tweak_session": ["workout", "tweak"],
}


# The intents that need values out of the message: each runs `bot capture <intent>` with
# the athlete's text, and that second, domain-focused call extracts, previews and asks
# (§12.2). The two note intents share one inbox — they differ only in the echo, so a
# misroute between them changes what she is told, never what is stored (§12.3).
ROUTER_CAPTURE_INTENTS = {
    "add_constraint": "note",
    "add_signal": "note",
    "add_goal": "add_goal",
    "edit_goal": "edit_goal",
    "edit_constraint": "edit_constraint",
    "change_setting": "change_setting",
}


# One short italic echo per routed intent, so the athlete learns the vocabulary and a
# misroute is visible immediately (§5.3, open question 1: always shown). They are also
# the per-message half of teaching the two lanes: "noting that rule for your coach" and
# "passing that on to your coach" say which inbox took the message (§12.3).
ROUTER_ECHO = {
    "show_today": "showing today",
    "show_week": "showing your week",
    "show_done": "showing what you've done lately",
    "show_goals": "showing your goals",
    "show_plan": "showing your plan",
    "show_progress": "showing your progress",
    "coach_message": "passing that on to your coach",
    "tweak_session": "asking your coach to change that",
    "add_constraint": "noting that rule for your coach",
    "add_signal": "logging that for your coach",
    "show_constraints": "showing what I'm working around",
    # The two edit echoes are readings, not actions: the capture call that follows may
    # find the name is a session and hand it to the coach instead (§12.4).
    "edit_constraint": "sounds like a change to a rule — checking",
    "remove_constraint": "showing your rules — tap the one to drop",
    "add_goal": "setting up a new goal",
    "edit_goal": "sounds like a change to a goal — checking",
    "remove_goal": "showing your goals — tap the one to call off",
    "change_setting": "changing that for you",
}


# What the §5.2 rescue window echoes. Text the router could not place, sent while a
# "💬 Talk to me" tap is live, rides the capture inbox rather than bouncing — she was
# just asked what the coach should know, so an unreadable answer is likelier a note the
# router failed. The inbox that asks before storing is the right landing (§12.3).
CAPTURE_RESCUE_ECHO = "noting that for your coach"


# Seconds a `bot route` classification may take before the tap falls back to
# 'unclear' — a router that hangs must not wedge the chat.
ROUTER_TIMEOUT_SECONDS = 30


# --- The /ui runtime persona switch (§5.6) ---
# Advertised in the expert menu only; the confirmation lines teach the way back, so
# the switch stays reachable from simple mode without cluttering the athlete's menu.

UI_USAGE = "Usage: /ui [simple|expert] — bare /ui flips the mode."
UI_SIMPLE_ON = (
    "Simple mode on 🙌 — buttons below, free text goes through the router.\n"
    "Send /ui to switch back; a restart returns to what config.yaml says."
)
UI_EXPERT_ON = (
    "Expert mode on — full command vocabulary, monospace output, keyboard removed.\n"
    "Send /ui to switch back; a restart returns to what config.yaml says."
)


def parse_ui_switch(text: str, simple_now: bool) -> Optional[bool]:
    """The /ui argument → target persona: True = simple, False = expert, None = show
    usage. Bare /ui flips the current mode (§5.6)."""
    parts = text.split()
    if len(parts) == 1:
        return not simple_now
    if len(parts) > 2:
        return None
    return {"simple": True, "on": True, "expert": False, "off": False}.get(
        parts[1].lower()
    )


def parse_message_to_argv(text: str, bot_username: Optional[str] = None) -> Optional[List[str]]:
    """Turns a raw chat message into a CLI argv list, or None if there's nothing to run.

    The leading ``/`` Telegram puts on commands is stripped, as is the ``@botname``
    suffix it appends in group chats. Bare ``help`` is passed through to the CLI's own
    ``help`` command (the full command/sub-command tree); ``help <cmd>`` is rewritten to
    the argparse-native ``<cmd> --help`` for that command's options. Raises
    ``ValueError`` on unbalanced quotes (so the caller can report it)."""
    text = (text or "").strip()
    if not text:
        return None
    if text.startswith("/"):
        text = text[1:]
    argv = shlex.split(text)
    if not argv:
        return None
    # Strip a '@botname' suffix Telegram adds to the command token in groups.
    head = argv[0]
    if "@" in head:
        name, _, suffix = head.partition("@")
        if bot_username is None or suffix.lower() == bot_username.lower():
            argv[0] = name
    # Bare 'help' runs the CLI's own help command (full tree); 'help <cmd>' maps
    # onto argparse's --help for that one command.
    if argv[0].lower() == "help":
        rest = argv[1:]
        return rest + ["--help"] if rest else ["help"]
    return argv
