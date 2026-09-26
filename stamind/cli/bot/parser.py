"""Argparse wiring for the `bot` command group.

Each sub-parser binds its handler with set_defaults(func=...), so the flags and the
function that reads them are defined together. `stamind_cli` imports `add_bot_parser`
from here and names nothing else in this package.
"""
from stamind.cli.bot.capture import CAPTURE_INTENTS, run_bot_capture
from stamind.cli.bot.route import run_bot_route
from stamind.cli.bot.views import (
    run_bot_changes, run_bot_constraints, run_bot_goals, run_bot_mesocycle,
    run_bot_morning,
)
from stamind.cli.queue import run_bot_queue


def add_bot_parser(subparsers):
    # bot command & subparsers — hidden: the Telegram bot spawns these
    # (DESIGN_bot_simple_frontend.md §8).
    bot_parser = subparsers.add_parser(
        "bot", advanced=True,
        help="Telegram-bot support commands (spawned by the bot, not typed)",
    )
    bot_subparsers = bot_parser.add_subparsers(dest="subcommand", help="Bot sub-commands")

    # bot morning
    b_morning = bot_subparsers.add_parser(
        "morning",
        help="Render the morning push message (idempotent per day)",
        description=(
            "Render the simple-mode morning message for today — the session(s) or the "
            "rest-day line — and emit the follow-up button row. Records "
            "push_morning_last in the settings table and exits silently when already "
            "sent today, so the bot's scheduler can fire it repeatedly without "
            "double-sending. With telegram.push.adapt_first, runs the daily adaptation "
            "non-interactively first, unless one already ran today with last night's "
            "sleep score in hand and nothing has been trained since."
        ),
    )
    b_morning.set_defaults(func=run_bot_morning)
    b_morning.add_argument(
        "-f", "--force", action="store_true",
        help="Send even when already recorded as sent today",
    )

    # bot changes
    b_changes = bot_subparsers.add_parser(
        "changes",
        help="Send the changes to the athlete's week not yet told, one message each",
        description=(
            "Print one message per change to the athlete's week that they have not been "
            "told about yet, oldest first, and record each as told. The bot's scheduler "
            "runs it when the changes are due, and the bot runs it before acting on the "
            "athlete's own tap or message (DESIGN_change_heads_up.md §4)."
        ),
    )
    b_changes.set_defaults(func=run_bot_changes)

    # bot route
    b_route = bot_subparsers.add_parser(
        "route",
        help="Classify one free-text chat message into a fixed intent (JSON on stdout)",
        description=(
            "Ask the router model (llm.router_model, falling back to the active "
            "coaching model) which intent one chat message carries, and print "
            "{\"intent\": ...} as one JSON line. Never fails: errors degrade to "
            "'unclear'."
        ),
    )
    b_route.set_defaults(func=run_bot_route)
    b_route.add_argument("text", help="The chat message to classify")

    # bot capture
    b_capture = bot_subparsers.add_parser(
        "capture",
        help="Read one chat message into a typed proposal, preview it, and ask",
        description=(
            "The write path behind the free-text router: a second, domain-focused LLM "
            "call (on the router model) extracts the values one intent can fill, the "
            "proposal is previewed in companion prose rendered from real rows, and a "
            "confirm makes it real. The model never authors a command — it fills typed "
            "fields and may nominate an object from rows this command gave it."
        ),
    )
    b_capture.set_defaults(func=run_bot_capture)
    b_capture.add_argument("intent", choices=CAPTURE_INTENTS, help="What to capture")
    b_capture.add_argument("text", help="The chat message to read")
    b_capture.add_argument(
        "--id", type=int, dest="pinned_id", default=None,
        help="Pin the object to edit (the picker's leaves re-enter with this set)",
    )

    # bot constraints
    b_constraints = bot_subparsers.add_parser(
        "constraints",
        help="Render the simple constraints view with its remove picker",
        description=(
            "Render the athlete's current and upcoming constraints in companion "
            "prose and emit a button picker whose leaves each run `constraint rm "
            "<id>`. The free-text router maps show_constraints and "
            "remove_constraint here."
        ),
    )
    b_constraints.set_defaults(func=run_bot_constraints)

    # bot goals
    b_goals = bot_subparsers.add_parser(
        "goals",
        help="Render the simple goals view with its call-off picker",
        description=(
            "Render the goals still ahead in companion prose and emit a button picker "
            "whose leaves each run `goal rm <id>` — which archives, keeping the plan "
            "history. The free-text router maps remove_goal here."
        ),
    )
    b_goals.set_defaults(func=run_bot_goals)

    # bot mesocycle
    b_mesocycle = bot_subparsers.add_parser(
        "mesocycle",
        help="Render one training mesocycle in full, in companion prose",
        description=(
            "Render one mesocycle the way the simple plan view draws it, followed by "
            "its whole focus. Read-only; the plan view's \"Tell me more\" leaves run it."
        ),
    )
    b_mesocycle.add_argument("mesocycle_id", type=int, help="The mesocycle to show")
    b_mesocycle.set_defaults(func=run_bot_mesocycle)

    # bot queue — the handler lives with the rest of the queue (DESIGN_athlete_queue.md §6.2)
    b_queue = bot_subparsers.add_parser(
        "queue",
        help="Act on one tapped queue item, or send the reminders that are due",
        description=(
            "Run by a tap on a queued item's button: check the item is still waiting and "
            "still worth asking, apply the action, then send the next item of the walk "
            "that started at --since. With --remind, send each item whose reminder time "
            "has passed."
        ),
    )
    b_queue.add_argument("item_id", metavar="ID", type=int, nargs="?", help="The tapped item")
    b_queue.add_argument(
        "action", metavar="ACTION", nargs="?",
        help="The tapped button: a<n> for an answer, d, s, h, t or b",
    )
    b_queue.add_argument(
        "--since", help="When the walk started, in epoch seconds; r-prefixed for a walk of one",
    )
    b_queue.add_argument(
        "--remind", action="store_true", help="Send the reminders that are due",
    )
    b_queue.set_defaults(func=run_bot_queue)
    return bot_parser
