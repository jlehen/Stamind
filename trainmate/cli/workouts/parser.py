"""Argparse wiring for the `workout` command group.

Each sub-parser binds its handler with set_defaults(func=...), so the flags and the
function that reads them are defined together.
"""
from trainmate.config import config
from trainmate.util import green
from trainmate.cli.selectors import add_selector_args, add_single_date_arg, parse_target
from trainmate.cli.workouts.calendar_sync import (
    run_workout_prune_calendar, run_workout_push, run_workout_wipe,
)
from trainmate.cli.workouts.generate import (
    run_workout_adapt, run_workout_batches, run_workout_compare,
    run_workout_generate, run_workout_list, run_workout_rollback, run_workout_show,
    run_workout_tweak,
)
from trainmate.cli.workouts.heads_up import run_workout_notify


def _add_listing_args(parser):
    """The targets, selectors and filters `workout list` and `workout show` share: one
    listing, and only the per-workout detail lines differ (`show` always prints it)."""
    parser.add_argument(
        "targets", nargs="*", metavar="TARGET", type=parse_target,
        help="Workout IDs and/or date selectors to show (e.g. '12 15', '2026-06-01..')"
    )
    add_selector_args(
        parser, meso=True, macro=True, goal=True, sport=True,
        direction="forward", default="7d",
    )
    parser.add_argument(
        "--link", "-l", action="store_true",
        help="Show each synced workout's Google Calendar event link"
    )


def add_workout_parser(subparsers, pull_bypass_parser, llm_debug_parser):
    # workout command & subparsers
    workout_parser = subparsers.add_parser(
        "workout",
        help="Manage workouts (microcycles)"
    )
    workout_subparsers = workout_parser.add_subparsers(
        dest="subcommand", help="Workout sub-commands"
    )

    # workout list
    w_list = workout_subparsers.add_parser(
        "list",
        parents=[pull_bypass_parser],
        help="Show all planned workouts",
        description=(
            "List planned workouts chronologically. With no filter at all, shows a 7-day "
            "window from today; with only --type, shows today onward. Name workout IDs or "
            "dates as arguments to show just those (handy with -vv). Every listed session "
            "dated today or earlier also carries what became of it — "
            "[DONE]/[PARTIAL]/[MISSED]/[REST OK]/[REST BROKEN], or [NOT YET] for one still "
            "ahead of you today — and -vv names the effort it matched and what a [PARTIAL] "
            "differed by. Garmin data is freshened over that past span first unless "
            "--no-pull is given; a listing entirely in the future never pulls."
        )
    )
    w_list.set_defaults(func=run_workout_list)
    _add_listing_args(w_list)
    w_list.add_argument(
        "--verbose", "-v", action="count", default=0,
        help="-v adds a short form in gray under each session: the exercises and kilograms "
             "of a strength session, the time planned in each intensity zone of any other. "
             "-vv shows the full detail instead (description, lifecycle, adapt notes)"
    )

    # workout show
    w_show = workout_subparsers.add_parser(
        "show",
        parents=[pull_bypass_parser],
        help="Show named workouts in full detail",
        description=(
            "Show workouts with their full details: the description, when the session "
            "was planned and last adapted, the effort a past session was graded against, "
            f"and any adapt notes. Same output as '{green('workout list')} -vv', under a "
            "name that says what it does. Name workout IDs or dates as arguments "
            f"('{green('workout show')} 12'), and every filter '{green('workout list')}' "
            "takes works here too. With no argument at all, it details the same 7-day "
            "window that command lists."
        )
    )
    w_show.set_defaults(func=run_workout_show)
    _add_listing_args(w_show)

    # workout compare
    w_cmp = workout_subparsers.add_parser(
        "compare",
        parents=[pull_bypass_parser],
        help="Compare planned workouts against completed activities",
        description=(
            "Compare planned workouts against completed Garmin activities, flagging "
            "missed sessions, rest-day violations, and unplanned high-load efforts. "
            "With no date filter, looks back 14 days; here a bare span like -d 7d looks "
            "backward (not forward) and the end date is always capped at today. "
            "Freshens Garmin data for the range first unless --no-pull is given. "
            "Each past event's Calendar entry is stamped with the adherence verdict "
            "(a [Done]/[Missed]/[Partial]/... title tag and an 'Adherence' description "
            "header) unless --no-mark is given."
        )
    )
    w_cmp.set_defaults(func=run_workout_compare)
    add_selector_args(
        w_cmp, meso=True, macro=True, goal=True, sport=True,
        direction="backward", default="14d", span_days=14,
    )
    w_cmp.add_argument(
        "--no-mark", action="store_true", dest="no_mark",
        help=(
            "Skip writing the adherence verdict back to each past workout's Google "
            "Calendar event (title tag + description header)."
        )
    )

    # workout generate
    p_w_gen = workout_subparsers.add_parser(
        "generate",
        parents=[pull_bypass_parser, llm_debug_parser],
        help="Generate workouts (microcycles) based on the active strategy",
        description=(
            "Generate workouts (microcycles), driven by the periodization mesocycles covering "
            "the days being generated — which plan applies is read off the dates, so no "
            "goal has to be named. -d/-m/-M/-g pick the whole span to write, both ends of "
            "it: '-m 5' is mesocycle 5 from its first day to its last, '-g' is a goal's whole "
            "plan, '-d 4w' is the next four weeks. A span never opens before today. With "
            "no selector, generates config.workout_generation_span_days days from today "
            f"(28 by default). The proposed sessions are listed as '{green('workout list')}' "
            "shows them and nothing is written until you accept; on a yes the new sessions "
            "are appended, days inside the span the plan no longer holds are cancelled, "
            "sessions outside the span are left exactly as they are, and Google Calendar "
            f"is brought into line — undoable with '{green('workout rollback')}', or "
            f"'{green('plan rollback')}' to step the strategy back with it. This is a full "
            "rebuild of the span, not a fill-in: when it already holds sessions it also "
            "asks before spending the LLM call (-f skips both prompts)."
        )
    )
    p_w_gen.set_defaults(func=run_workout_generate)
    p_w_gen.add_argument(
        "-f", "--force", "-y", "--yes", action="store_true", dest="force",
        help="Skip the confirmation prompts (spending the LLM call, applying the "
             "proposed workouts, and the out-of-date-plan warning)"
    )
    p_w_gen.add_argument(
        "-v", "--verbose", action="store_true",
        help="Name each Calendar event as it is deleted and created, instead of the "
             "progress bar"
    )
    # `--fresh` writes every session again and `--strength-only` the strength ones only.
    p_w_gen_scope = p_w_gen.add_mutually_exclusive_group()
    p_w_gen_scope.add_argument(
        "--fresh", action="store_true",
        help=(
            "Clean slate: don't show the coach the sessions already in the span, so it "
            "rewrites every day of it. Without this flag it keeps the sessions of the next "
            "commitment-days days (a setting, 7 by default), unless they contradict your "
            "profile, the plan or a constraint. A session it removes has its Calendar event "
            "deleted, not marked [Cancelled]. Strength sessions are written again in full, as "
            "with --strength-only."
        )
    )
    p_w_gen_scope.add_argument(
        "--strength-only", action="store_true", dest="strength_only",
        help=(
            "Write only the strength sessions of the span again: their exercises, sets and "
            "kilograms, under the brief each has now, those of the next commitment-days days "
            "included. No other session changes. With no end selected, the span runs to the "
            "last scheduled day."
        )
    )
    # The selectors name the span to write, both ends of it, and are grouped because a
    # span is one choice, not several (DESIGN_cli_selectors.md §8). `-M` doubles as the
    # tiebreaker when two plans cover the same days.
    p_w_gen_span = p_w_gen.add_mutually_exclusive_group()
    add_selector_args(
        p_w_gen, meso=True, macro=True, goal=True, direction="forward", default=None,
        group=p_w_gen_span, generates=True,
    )


    # workout rollback
    w_rollback = workout_subparsers.add_parser(
        "rollback", aliases=["rb"],
        help="Undo a workout change, and every change made after it",
        description=(
            "Put the sessions back the way they were the moment before a change ran. "
            "Any command that wrote workouts qualifies — a generation, an adapt, a "
            "tweak — and undoing one also undoes everything after it, which is "
            "what stops a session ending up live on two days. Defaults to the newest "
            f"change; list them with '{green('workout batches')}' and pick one with "
            "--batch. Sessions dated before today are left alone. The active "
            f"periodization plan is left untouched — use '{green('plan rollback')}' to "
            "step the strategy back as well."
        )
    )
    w_rollback.set_defaults(func=run_workout_rollback)
    w_rollback.add_argument(
        "--batch", type=int, metavar="N",
        help="Which change to undo, as numbered by 'workout batches' "
             "(1 = the newest, the default)"
    )
    w_rollback.add_argument(
        "-y", "--yes", action="store_true", help="Skip confirmation prompt"
    )
    w_rollback.add_argument(
        "-v", "--verbose", action="store_true",
        help="Name each Calendar event as it is deleted and created, instead of the "
             "progress bar"
    )

    # workout batches
    _batches_parser = workout_subparsers.add_parser(
        "batches",
        help="List the workout changes that 'workout rollback' can undo",
        description=(
            "List every command that wrote workouts, newest first: when it ran, what "
            "kind of change it was, how many revisions it appended and over what dates. "
            f"'{green('workout rollback --batch N')}' undoes one, and everything after "
            "it. A pass that looked at the plan and changed nothing — an adapt that held "
            "— is listed too, marked '(held)'. Every entry is undoable, #1 included: it "
            "is the change that wrote the plan you are on now."
        )
    )
    _batches_parser.set_defaults(func=run_workout_batches)

    # workout notify
    w_notify = workout_subparsers.add_parser(
        "notify",
        help="Send the athlete the changes to their week not yet told, at once",
        description=(
            "Companion mode only. A change made in the terminal reaches the athlete's "
            "Telegram just before their next morning message, even one that changes "
            "today's sessions. This lists the changes still waiting, each with the line the "
            "athlete will get, and asks the bot to send them on its next wake, within five "
            "minutes, whatever the hour. "
            f"'{green('workout batches')}' marks them 'not sent yet'."
        ),
    )
    w_notify.set_defaults(func=run_workout_notify)
    w_notify.add_argument(
        "-y", "--yes", action="store_true", help="Skip confirmation prompt"
    )

    # workout adapt
    w_adapt = workout_subparsers.add_parser(
        "adapt",
        parents=[pull_bypass_parser, llm_debug_parser],
        help="Run the daily Garmin check for today (syncs adapted workouts to Calendar)",
        description=(
            "Run the daily adaptation check: read recent recovery metrics and let the "
            "coach adjust upcoming workouts. Defaults to today (UTC); use --date for "
            "another day. Proposed changes are confirmed interactively unless -y/--auto "
            "is given, then synced to Google Calendar."
        )
    )
    w_adapt.set_defaults(func=run_workout_adapt)
    add_single_date_arg(
        w_adapt,
        "Day to adapt: YYYY-MM-DD, 'today' (the default) or an offset like -1d"
    )
    w_adapt.add_argument(
        "--lookback", type=int, metavar="DAYS",
        help="Days of recovery-metrics trajectory to summarize (default: config metrics_lookback_days)"
    )
    w_adapt.add_argument(
        "-m", "--message", dest="message",
        help=(
            "Ad-hoc, one-off signal to the coach for THIS adaptation run only (e.g. "
            "'knee is sore, keep impact low', 'no bike access Thursday'). Advisory: it "
            "won't override clear fatigue signals. The note itself isn't stored, but if "
            "it drives a session change its cause is recorded in that session's reason so "
            "a later run understands the tactical change; it stays a one-off and never "
            "becomes durable mesocycle evidence. For persistent signals (alcohol, sleep, "
            "stress) use 'signal add' instead."
        )
    )
    w_adapt.add_argument(
        "-y", "--yes", "--auto", action="store_true", dest="auto",
        help="Apply proposed adaptations automatically without prompting"
    )
    
    # workout tweak
    w_tweak = workout_subparsers.add_parser(
        "tweak",
        parents=[pull_bypass_parser, llm_debug_parser],
        help="Ask the coach for a change you decided: shorter, moved, swapped, dropped, added",
        description=(
            "Ask the coach for a change to your schedule, in your own words: a session "
            "made shorter or harder, another sport in its place, other exercises in a "
            "strength session, a session added, dropped or brought back, a session moved "
            "to another day, or two days swapped. The coach writes the sessions so that "
            "they fit the week, and only the days the request is about change. Say the "
            "days in the message ('Friday: ...'), or name them with --date, which may be "
            "given more than once. Every day must lie between today and the end of the "
            "current mesocycle. The change is shown first and applied on a yes, then "
            "synced to Google Calendar. When a whole change was a mistake, "
            f"'{green('workout rollback')}' is the better tool: it puts back exactly what "
            "was there. To tell the coach how you are and let it decide what to change, "
            f"use '{green('workout adapt')} -m' instead."
        )
    )
    w_tweak.set_defaults(func=run_workout_tweak)
    w_tweak.add_argument(
        "message",
        help="What you want changed, e.g. 'Saturday: a 4 hour hike instead of the ride'"
    )
    add_single_date_arg(
        w_tweak,
        "A day to change: YYYY-MM-DD, 'today' or an offset like +2d. Give it once per "
        "day. Without it, the coach reads the days off the message",
        repeat=True,
    )
    w_tweak.add_argument(
        "-y", "--yes", "--auto", action="store_true", dest="auto",
        help="Apply the proposed change without prompting"
    )

    # workout push
    w_push = workout_subparsers.add_parser(
        "push", aliases=["p"], advanced=True,
        help="Commit local planned workouts to Google Calendar",
        description=(
            "Push planned workouts to Google Calendar. With no date filter, pushes "
            "from today onward. By default only new or modified (unsynced) workouts "
            "are sent; use -f/--force to re-push already-synced workouts, overwriting "
            "their calendar entries."
        )
    )
    w_push.set_defaults(func=run_workout_push)
    add_selector_args(
        w_push, meso=True, macro=True, goal=True, sport=True, direction="forward",
        default="today..",
    )
    w_push.add_argument(
        "-f", "--force", action="store_true",
        help="Re-push already-synced workouts, overwriting existing calendar entries"
    )

    # workout wipe
    w_wipe = workout_subparsers.add_parser(
        "wipe", advanced=True,
        help="Wipe all workouts from the database and Google Calendar"
    )
    w_wipe.set_defaults(func=run_workout_wipe)
    w_wipe.add_argument("-y", "--yes", action="store_true", help="Skip confirmation prompt")

    # workout prune-calendar
    w_prune = workout_subparsers.add_parser(
        "prune-calendar", advanced=True,
        help="Delete Google Calendar workout events no local workout references",
        description=(
            "Sweep the Google Calendar for TrainMate workout events that no workout in "
            "the database points at, and delete them. These orphans are what a fresh "
            "database, a restored backup, or a wipe that never reached Calendar leaves "
            "behind. Events belonging to cancelled workouts are kept (the session still "
            "claims them). With no date filter the whole calendar is swept; -d restricts "
            "it to a window, as on 'data wipe'. Use --dry-run to preview."
        )
    )
    w_prune.set_defaults(func=run_workout_prune_calendar)
    add_selector_args(w_prune, direction="none")
    w_prune.add_argument(
        "-n", "--dry-run", action="store_true", dest="dry_run",
        help="List the orphaned events without deleting anything"
    )
    w_prune.add_argument("-y", "--yes", action="store_true", help="Skip confirmation prompt")

    return workout_parser
