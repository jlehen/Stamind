"""Every button the bot draws, and every tap it decodes.

The reply keyboard the companion persona attaches to the chat and what each of its labels
runs (DESIGN_bot_simple_frontend.md §5.1), and the inline rows raised over a command: a
SM-BUTTONS offer, a prompt's choices, a queued item's answers, and the ✋ Stop button over
an LLM wait (DESIGN_athlete_queue.md §6.2, DESIGN_bot_stop_button.md §3).

The cards `/start` and `/help` answer with, and Telegram's own command menu, are here too:
the companion card teaches the reply keyboard label by label, so a relabelled button and
the sentence describing it have to be edited together.

Each kind of tap carries its own callback-data namespace — `ui:`, `stop:`, `q:`, and the
bare prompt answer — and every decoder here rejects the other three. They share one
Telegram channel, so a decoder that read another namespace as its own would turn a stale
tap into an action (DESIGN_bot_stop_button.md §7). Telegram caps callback data at 64
bytes, which is why a queued item's id travels inside the data rather than in anything
the bot remembers.
"""
import datetime
import re
from typing import Any, List, Optional, Tuple

from stamind.athlete_queue import QUEUE_LATER_CHOICES, queue_later_label
from stamind.clock import day_str, parse_date
from stamind.sports import canonical_sport
from stamind.types import Workout

# Reply-keyboard label → fixed argv; None arms free-text capture (§5.1/§5.2).
# Buttons never reach beyond this table; the keyboard renders it two per row, in order.
SIMPLE_KEYBOARD = [
    ("📅 Today", ["workout", "list", "-d", "today"]),
    ("🗓 My week", ["workout", "list"]),
    # A look back is a read: --no-mark keeps the Calendar stamping out of a tap (§5.1).
    ("✅ Done lately", ["workout", "compare", "-d", "7d", "--no-mark"]),
    ("🎯 Goals", ["goal", "list"]),
    ("🧭 My plan", ["plan", "show"]),
    ("📈 Progress", ["progress", "--chart"]),
    ("💬 Talk to me", None),
]

# The keyboard renders the table two labels per row, in order.
KEYBOARD_LABELS_PER_ROW = 2


def simple_keyboard_rows(gym: Any = None) -> List[List[Any]]:
    """The §5.1 reply keyboard's labels, laid out the way the bot attaches them.

    `gym` is the gym button `gym_button` found — a label, or the (label, url) pair that
    opens the Mini App. It takes the first row on its own (DESIGN_gym_logger.md §6)."""
    labels = [label for label, _ in SIMPLE_KEYBOARD]
    rows: List[List[Any]] = [labels[i:i + KEYBOARD_LABELS_PER_ROW]
                             for i in range(0, len(labels), KEYBOARD_LABELS_PER_ROW)]
    if gym is None:
        return rows
    return [[gym]] + rows


# --- The gym button (DESIGN_gym_logger.md §6) ---

# The sport a gym session is filed under, and how far ahead the button looks: today and
# the six days after it.
GYM_SPORT = "strength_training"
GYM_WINDOW_DAYS = 7

GYM_TODAY_LABEL = "🏋️ Log today's gym"


def gym_window_end(today: str) -> str:
    """The last day the gym button looks at, given today (both YYYY-MM-DD)."""
    return day_str(parse_date(today) + datetime.timedelta(days=GYM_WINDOW_DAYS - 1))


def gym_label(day: str, today: str) -> str:
    """What the button says for a session on `day`: "today's" on the day itself, and the
    weekday's name otherwise (§6)."""
    if day == today:
        return GYM_TODAY_LABEL
    return f"🏋️ Log {parse_date(day).strftime('%A')}'s gym"


def gym_button(workouts: List[Workout], today: str) -> Optional[Tuple[str, Workout]]:
    """The gym button's label and the session it carries, or None when there is nothing to
    log (§6).

    The earliest strength session with prescribed sets, dated from today to six days out.
    `workouts` are live sessions; a cancelled one never reaches here."""
    end = gym_window_end(today)
    for workout in sorted(workouts, key=lambda w: str(w.get("date") or "")):
        day = str(workout.get("date") or "")
        if day < today or day > end:
            continue
        if canonical_sport(str(workout.get("sport_type") or "")) != GYM_SPORT:
            continue
        if not workout.get("prescribed_sets"):
            continue
        return gym_label(day, today), workout
    return None


# --- What /start and /help say, and Telegram's own command menu ---

WELCOME = (
    "Stamind is connected. Send any CLI command — the leading slash is "
    "optional.\n\n"
    "Examples:\n"
    "  /status\n"
    "  /workout list --weeks 1\n"
    "  /workout adapt -m \"tired today\"\n"
    "  /plan show\n\n"
    "Send /help for the full command list, or /help <command> (e.g. "
    "/help workout) for a command's options.\n\n"
    "When a command needs a decision (apply a plan, confirm a wipe) I'll show "
    "buttons — tap one, or send /cancel to abort."
)

# Top-level command families surfaced in Telegram's command menu (set_my_commands).
# Kept in sync by hand with the CLI's subparsers; purely cosmetic (any command
# still works whether or not it's listed here).
MENU_COMMANDS = [
    ("status", "Athlete status, goals, recent metrics"),
    ("progress", "Training progress timeline (add --chart for a PNG)"),
    ("workout", "List/generate/adapt/tweak workouts"),
    ("plan", "Show/generate periodization plans"),
    ("goal", "Manage training goals"),
    ("data", "Pull/show Garmin metrics & activities"),
    ("signal", "Author daily signals"),
    ("learnings", "Inspect coach learnings"),
    ("constraint", "Manage directives the coach works around"),
    ("settings", "Show/change preferences (model, timezone, morning push)"),
    ("queue", "Questions and messages waiting for the athlete"),
    ("ui", "Switch simple/expert chat UI (until restart)"),
    ("cancel", "Abort the command awaiting your answer"),
    ("restart", "Restart the bot process (picks up new code)"),
    ("help", "Show command help"),
]

# --- Simple mode ("companion") cards — DESIGN_bot_simple_frontend.md §5 ---
# What /start and /help say, beside MENU_COMMANDS. They name the buttons SIMPLE_KEYBOARD
# draws, which is why they sit in this file rather than beside the handler that sends them.

SIMPLE_WELCOME = (
    "Hi! I'm your training coach 🏃\n\n"
    "Use the buttons below:\n"
    "📅 Today — today's session\n"
    "🗓 My week — the days ahead\n"
    "✅ Done lately — how the last days went\n"
    "🎯 Goals — what you're training for\n"
    "🧭 My plan — the road to your goal\n"
    "📈 Progress — how your fitness is building\n"
    "💬 Talk to me — anything I should know (tired, busy, sore…)\n\n"
    "Or just type what you want, in your own words — it's the same thing."
)

# The two lanes, taught rather than discovered (§12.3). The surface has exactly two
# teachers — this card and the per-message router echoes — and both say the same thing:
# what you want remembered is recorded here, after a question; what is about how you are
# doing goes to the coach in your own words. No line promises verbatim delivery on a tap,
# because no tap delivers it.
SIMPLE_HELP = SIMPLE_WELCOME + (
    "\n\nWhen you write to me, one of two things happens:\n"
    "• Something to remember — a rule, a rough night, a new goal, a change of date, "
    "a test result — I write it down and ask you first.\n"
    "• Something about how you're doing, what's in the way, or a session you'd like "
    "changed — that goes to your coach in your own words, and your week comes back "
    "adjusted."
)

# Simple mode trims the Telegram command menu to what the athlete needs; every CLI
# command still works when typed with a leading slash.
SIMPLE_MENU_COMMANDS = [
    ("cancel", "Stop what's running"),
    ("help", "What can I ask?"),
]


# What a tap on a row a newer one replaced gets back (§12.3).
UI_STALE_TAP = "That offer expired — just send it again."

# What a tap gets while another command runs in the chat; its buttons stay alive for a retry.
BUSY_TAP = "One moment — still finishing the last thing. Tap again shortly."

# --- The Stop button raised over an LLM wait (DESIGN_bot_stop_button.md §3) ---
# One button, one meaning, the same in both personas: end the command the athlete is
# watching wait. "Stopped." is all the reply claims, because a command that already
# wrote something before this call keeps what it wrote (§6).
STOP_LABEL = "✋ Stop"
STOP_DONE = "Stopped."
STOP_ALREADY_DONE = "That's already finished — nothing to stop."


def keyboard_action(text: str) -> Optional[Tuple[str, Optional[List[str]]]]:
    """What a simple-keyboard tap maps to: ("run", argv), ("capture", None), or None
    when the text isn't a keyboard label."""
    stripped = (text or "").strip()
    for label, argv in SIMPLE_KEYBOARD:
        if stripped == label:
            return ("run", list(argv)) if argv else ("capture", None)
    return None


def stale_keyboard_tap(text: str, simple_now: bool) -> bool:
    """A companion label arriving while the persona is expert: the §5.1 keyboard lives
    on the phone and outlives the process that attached it (§5.6)."""
    return (
        not simple_now
        and not (text or "").startswith("/")
        and keyboard_action(text) is not None
    )


def ui_callback_data(token: str, path: str) -> str:
    """callback_data for a SM-BUTTONS button: ``"ui:{token}:{path}"``. The ``ui:``
    namespace keeps these taps apart from prompt answers; the token invalidates rows
    replaced by a newer push; the path indexes into the stored payload ("2", "2.1")."""
    return f"ui:{token}:{path}"


def decode_ui_callback(data: str) -> Optional[Tuple[str, str]]:
    """Splits ``"ui:{token}:{path}"`` back into (token, path), or None if it isn't a
    ui-namespace callback or is malformed."""
    parts = (data or "").split(":", 2)
    if len(parts) != 3 or parts[0] != "ui" or not parts[1] or not parts[2]:
        return None
    return parts[1], parts[2]


def stop_callback_data(nonce: str) -> str:
    """callback_data for the §3 Stop button: ``"stop:{nonce}"``. The nonce is the
    running command's own token, so a tap that arrives after it ended cannot stop
    whatever started since (DESIGN_bot_stop_button.md §7)."""
    return f"stop:{nonce}"


def decode_stop_callback(data: str) -> Optional[str]:
    """The nonce inside ``"stop:{nonce}"``, or None if it isn't a stop-namespace
    callback or is malformed."""
    parts = (data or "").split(":")
    if len(parts) != 2 or parts[0] != "stop" or not parts[1]:
        return None
    return parts[1]


def queue_callback_data(item_id: Any, action: str, since: str) -> str:
    """callback_data for a queued item's button: ``"q:{item id}:{action}:{walk start}"``.
    The action names a position among the answers stored with the item, never the answer
    itself, so it stays inside Telegram's 64 bytes (DESIGN_athlete_queue.md §6.2)."""
    return f"q:{item_id}:{action}:{since}"


def decode_queue_callback(data: str) -> Optional[Tuple[str, str, str]]:
    """Splits ``"q:{item id}:{action}:{walk start}"`` back into its parts, or None when it
    is not one. Each part becomes a word of `bot queue`'s argv, so each is held to its
    shape."""
    parts = (data or "").split(":")
    if len(parts) != 4 or parts[0] != "q":
        return None
    _, item_id, action, since = parts
    if not (item_id.isdigit() and action.isalnum() and re.fullmatch(r"r?\d+", since)):
        return None
    return item_id, action, since


def resolve_ui_action(buttons: List[Any], path: str) -> Optional[dict]:
    """The button dict a callback path names: "2" is buttons[2], "2.1" entry 1 of its
    menu. None when the path doesn't resolve (malformed, stale, or hostile data)."""
    steps = path.split(".")
    if len(steps) > 2:
        return None
    try:
        node = buttons[int(steps[0])]
        if len(steps) == 2:
            node = (node.get("menu") or [])[int(steps[1])]
    except (ValueError, IndexError, AttributeError, TypeError):
        return None
    return node if isinstance(node, dict) else None


# Telegram divides a row's width between its buttons, so a fourth one shrinks all four
# past reading. The morning push is exactly that case once the runway button joins its
# three session buttons (DESIGN_runway_nudge.md §6), and the wrap puts it on its own line.
UI_BUTTONS_PER_ROW = 3


def ui_button_rows(buttons: List[dict], token: str) -> List[List[Tuple[str, str]]]:
    """Top-level SM-BUTTONS layout: across, like the §4.1 mock, wrapping every
    `UI_BUTTONS_PER_ROW`. Positions stay flat — a callback path indexes the payload, not
    the row it landed on."""
    cells = [(b.get("label", ""), ui_callback_data(token, str(i)))
             for i, b in enumerate(buttons)]
    return [cells[i:i + UI_BUTTONS_PER_ROW]
            for i in range(0, len(cells), UI_BUTTONS_PER_ROW)] or [[]]


def ui_menu_rows(menu: List[dict], token: str, parent: str) -> List[List[Tuple[str, str]]]:
    """A tapped `menu` button's sub-choices: one per row, like a choose prompt."""
    return [[(b.get("label", ""), ui_callback_data(token, f"{parent}.{i}"))]
            for i, b in enumerate(menu)]


def queue_button_rows(req: dict) -> List[List[Tuple[str, str]]]:
    """A queued item's buttons, laid out like the morning row they arrive under (§6.1)."""
    cells = [
        (b.get("label", ""),
         queue_callback_data(req.get("id"), b.get("action", ""), req.get("since", "")))
        for b in req.get("buttons") or [] if isinstance(b, dict)
    ]
    return [cells[i:i + UI_BUTTONS_PER_ROW] for i in range(0, len(cells), UI_BUTTONS_PER_ROW)]


def queue_later_rows(item_id: str, since: str) -> List[List[Tuple[str, str]]]:
    """What "Not now" swaps in: the three later choices, built from the tap itself, so the
    bot still remembers nothing (DESIGN_athlete_queue.md §6.4)."""
    return [[(queue_later_label(words, emoji), queue_callback_data(item_id, code, since))
             for code, words, emoji in QUEUE_LATER_CHOICES]]


def tapped_label(rows: List[List[Tuple[str, str]]], data: str) -> Optional[str]:
    """The label of the button a tap came from, for the "→ …" line left under the item."""
    for row in rows:
        for label, callback in row:
            if callback == data:
                return label
    return None


def prompt_buttons(req: dict, nonce: str) -> List[List[Tuple[str, str]]]:
    """Inline-keyboard layout for a prompt request: rows of ``(label, callback_data)``.

    callback_data is ``"{nonce}:{prompt_id}:{value}"`` — well under Telegram's 64-byte
    cap, with the nonce letting the bot reject taps from a stale/replaced session. A
    ``text`` prompt has no buttons (the athlete just replies), so this returns []."""
    pid = req.get("id", "")
    ptype = req.get("type")
    if ptype == "confirm":
        yes = "⚠️ Confirm" if req.get("danger") else "✅ Yes"
        return [[(yes, f"{nonce}:{pid}:y"), ("✖️ No", f"{nonce}:{pid}:n")]]
    if ptype == "choose":
        return [[(c["label"], f"{nonce}:{pid}:{c['value']}")]
                for c in req.get("choices", [])]
    return []


def decode_callback(data: str) -> Optional[Tuple[str, str, str]]:
    """Splits ``"{nonce}:{prompt_id}:{value}"`` back into its parts, or None if malformed."""
    parts = (data or "").split(":", 2)
    if len(parts) != 3:
        return None
    return parts[0], parts[1], parts[2]
