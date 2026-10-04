"""`strength`: the surgery on a strength activity's sets (DESIGN_strength_tracking.md §7).

`strength name` shows a day's sets and names the ones picked, `strength reset` reads a day's
sets again from Garmin, and `strength discard` keeps a day's activity out of the strength
history. On a day with two strength activities, reset and discard ask which one. The other
three commands of the family are in files of their own: `strength log` and `strength
exercises` in `strength_log.py`, `strength ingest` in `strength_ingest.py`.
"""
import argparse
from typing import Any, Dict, List

from stamind import clock, runtime, settings
from stamind.cli.selectors import parse_single_date
from stamind.cli.strength_ingest import add_ingest_parser
from stamind.cli.strength_log import add_log_parsers
from stamind.db.strength import ACTIVE
from stamind.prompt import Choice
from stamind.queue_kind import NotApplied
from stamind.strength import questions, sets, vocabulary
from stamind.text import bold, capitalized, cmd, red, wrap_text
from stamind.output import fail, notice
from stamind.clock import fmt_date

KEEP = "keep"
CLEAR = "clear"
OTHER = "other"
ALL = "all"
NONE = "none"
DONE = "done"


def _title(activity: Dict[str, Any]) -> str:
    return questions.activity_words(sets.activity_ref(activity))


def _which(day: str, activities: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """The day's one strength activity, or the ones picked when it has more: a second one
    or a warm-up is not reset or discarded along with the activity (§7)."""
    if len(activities) < 2:
        return activities
    choices = [Choice(activity["activity_id"], _title(activity)) for activity in activities]
    choices += [Choice(ALL, "all of them"), Choice(NONE, "none")]
    picked = runtime.prompt.choose(
        f"{fmt_date(day)} has {len(activities)} strength activities. Which one?", choices,
        default=NONE,
    )
    if picked == ALL:
        return activities
    return [activity for activity in activities if activity["activity_id"] == picked]


def _line_label(line: sets.Line) -> str:
    """'sets 10, 12, 14: olympic lift: clean and press 3×16 @ 22': one line of the layout."""
    span = sets.position_list(line.positions)
    if line.exercise is None:
        reps = [s["reps"] for s in line.sets]
        return f"{span}: {sets.reps_and_load(reps, line.sets[0]['load_kg'])}, unnamed"
    return f"{span}: {sets.named_line(line)}"


def _how_many(line: sets.Line, exercise: str) -> int:
    """"All 6 sets, or how many?": a line that was two exercises is split here (§7)."""
    count = len(line.sets)
    if count == 1:
        return 1
    choices = [Choice(ALL, f"all {count} sets")]
    choices += [Choice(str(n), f"the first {n}") for n in range(1, count)]
    picked = runtime.prompt.choose(
        f"{vocabulary.words(exercise)}: all {count} sets, or how many?", choices, default=ALL
    )
    return count if picked == ALL else int(picked)


def _answers(line: sets.Line, recent: List[str]) -> List[str]:
    """The exercises offered as what a line was: the recent ones for unnamed sets, and for a
    named line the ones like its name (§7)."""
    if line.exercise is None:
        return recent
    return vocabulary.similar(line.exercise, sets.own_exercises(), sets.MAX_ANSWERS)


def _ask_line(activity_id: str, line: sets.Line, recent: List[str]) -> None:
    """Asks what one line of the layout was and applies the answer."""
    span = sets.position_list(line.positions)
    seqs = [s["seq"] for s in line.sets]
    offered = _answers(line, recent)
    choices = [Choice(f"a{n}", vocabulary.words(key)) for n, key in enumerate(offered, 1)]
    choices.append(Choice(OTHER, "something else…"))
    clear = "leave it unnamed" + (", clearing its name" if line.exercise else "")
    choices.append(Choice(CLEAR, clear))
    choices.append(Choice(KEEP, "keep it as it is"))
    picked = runtime.prompt.choose(
        f"{capitalized(_line_label(line))}. What was it?", choices, default=KEEP
    )
    if picked == KEEP:
        # Keeping a name the watch guessed confirms it: the athlete has just looked at it,
        # which is the whole of what makes a guess count (§7).
        if any(s["named_by"] == sets.WATCH for s in line.sets):
            runtime.db.name_exercise_sets(activity_id, seqs, line.exercise)
            print(f"{capitalized(span)} confirmed: {vocabulary.words(line.exercise)}.")
        return
    if picked == CLEAR:
        runtime.db.name_exercise_sets(activity_id, seqs, None)
        print(f"{capitalized(span)} left unnamed.")
        return
    if picked == OTHER:
        text = runtime.prompt.ask_text(sets.SOMETHING_ELSE["ask"]).strip()
        try:
            exercise = questions.choose_proposed(text)
        except NotApplied as not_applied:
            print(wrap_text(str(not_applied)))
            return
    else:
        exercise = offered[int(picked[1:]) - 1]
    count = _how_many(line, exercise)
    runtime.db.name_exercise_sets(activity_id, seqs[:count], exercise)
    print(f"Named {sets.position_list(line.positions[:count])}: {vocabulary.words(exercise)}.")


def _name_activity(activity: Dict[str, Any], recent: List[str]) -> None:
    """Shows an activity's layout, one line per exercise, and names the line the athlete
    picks, until she is done. Naming by hand declares the sets final, so a waiting "are the
    sets final?" question is settled at the first pick (§7)."""
    activity_id = activity["activity_id"]
    frozen = bool(activity["sets_final_at"])
    while True:
        layout = sets.exercise_lines(runtime.db.get_exercise_sets(activity_id))
        choices = [Choice(str(n), _line_label(line)) for n, line in enumerate(layout, 1)]
        choices.append(Choice(DONE, "none, I am done"))
        print()
        picked = runtime.prompt.choose(
            f"{bold(_title(activity))}\nWhich sets do you want to name?", choices, default=DONE
        )
        if picked == DONE:
            return
        if not frozen:
            runtime.db.freeze_exercise_sets(activity_id, clock.now())
            frozen = True
        _ask_line(activity_id, layout[int(picked) - 1], recent)


def run_strength_name(args: argparse.Namespace) -> None:
    """Names the sets picked in a day's strength activities, on the spot (§7)."""
    day = args.date
    activities = runtime.db.strength_activities(day, date=day)
    with_sets = [
        activity for activity in activities
        if any(row["set_type"] == ACTIVE
               for row in runtime.db.get_exercise_sets(activity["activity_id"]))
    ]
    if not with_sets:
        unread = [activity for activity in activities if not activity["sets_read_at"]]
        if unread:
            notice(f"The sets of {fmt_date(day)} are not read yet: they are read the morning "
                   "after training, or now with " + cmd(f"strength reset {day}") + ".")
            return
        notice(f"No strength activity with sets on {fmt_date(day)}.")
        return
    recent = sets.recent_exercises()
    for activity in with_sets:
        _name_activity(activity, recent)


def run_strength_reset(args: argparse.Namespace) -> None:
    """Reads a day's sets again from Garmin, drops the answers on them, freezes them anew and
    queues the naming questions for what is still unnamed (§7)."""
    day = args.date
    since = settings.strength_sets_since()
    if not since:
        notice("Strength sets are not read. Set the first day to read them from with "
               + cmd("settings set strength-sets-since YYYY-MM-DD") + ".", red)
        return
    if day < since:
        notice(f"{fmt_date(day)} is before strength-sets-since ({since}), so its sets are "
               "not read.", red)
        return
    activities = runtime.db.strength_activities(day, date=day)
    if not activities:
        notice(f"No strength activity on {fmt_date(day)}. Fetch it first with "
               + cmd(f"data pull -d {day}") + ".")
        return
    activities = _which(day, activities)
    if not activities:
        print("Nothing changed.")
        return
    try:
        client = runtime.garmin.connect()
    except Exception as e:
        fail(f"Could not log into Garmin: {e}")
        return
    for activity in activities:
        title = _title(activity)
        try:
            found = sets.read_again(activity, client)
        except Exception as e:
            fail(f"Could not read the sets of the {title}: {e}")
            continue
        if not found:
            print(f"{title}: Garmin has no sets for it.")
            continue
        count = len([group for group in found if group.exercise is None])
        if not count:
            print(f"{title}: sets read again and frozen. Every set has a name.")
            continue
        print(wrap_text(
            f"{title}: sets read again and frozen. {count} group{'s' if count != 1 else ''} "
            "without a name: the questions are in the queue, " + cmd("queue answer")
            + " goes through them."
        ))


def run_strength_discard(args: argparse.Namespace) -> None:
    """Keeps a day's activity out of the strength history, or brings it back with --undo
    (§7)."""
    day = args.date
    activities = runtime.db.strength_activities(day, date=day)
    if not activities:
        notice(f"No strength activity on {fmt_date(day)}.")
        return
    activities = _which(day, activities)
    if not activities:
        print("Nothing changed.")
        return
    for activity in activities:
        runtime.db.set_activity_discarded(activity["activity_id"], not args.undo)
        if args.undo:
            print(f"The {_title(activity)} is back in the strength history.")
        else:
            print(f"Discarded the {_title(activity)}.")
    if args.undo:
        return
    print(wrap_text(
        "A discarded activity still counts as training: its sets stay on record but are "
        "left out of the strength history, and its waiting questions are settled. "
        + cmd(f"strength discard {day} --undo") + " brings it back."
    ))


def add_strength_parser(subparsers):
    # strength command & subparsers — the sets of strength activities
    # (DESIGN_strength_tracking.md §7).
    strength_parser = subparsers.add_parser(
        "strength",
        help="Read back what you lifted, or fix an activity's sets by hand",
        description=(
            "Stamind reads your sets from Garmin the morning after you lift. Anything it "
            "can't name, it asks you about through the queue. `log` and `exercises` read "
            "your record and the exercise table behind it back, `ingest` stores a session you "
            "logged on your phone, and the other three fix a day by hand."
        ),
    )
    strength_subparsers = strength_parser.add_subparsers(
        dest="subcommand", help="Strength sub-commands"
    )
    date_help = "The activity's day: YYYY-MM-DD, 'today', or an offset like -1d"

    s_name = strength_subparsers.add_parser(
        "name",
        help="Show the sets of a day's activity and name the ones you pick",
        description=(
            "Show the day's activity, one line per exercise, and pick the line to name; the "
            "layout comes back after every name until you are done. After a name, say "
            "whether it covers every set of the line or only its first ones."
        ),
    )
    s_name.add_argument("date", metavar="DATE", type=parse_single_date, help=date_help)
    s_name.set_defaults(func=run_strength_name)

    s_reset = strength_subparsers.add_parser(
        "reset",
        help="Read a day's sets again from Garmin, dropping the names given in Stamind",
        description=(
            "Read the day's sets again from Garmin, so a name fixed in Garmin Connect comes "
            "in. The names given in Stamind for that day are dropped, and a question is "
            "queued for every group still unnamed. On a day with two strength activities, it "
            "asks which one."
        ),
    )
    s_reset.add_argument("date", metavar="DATE", type=parse_single_date, help=date_help)
    s_reset.set_defaults(func=run_strength_reset)

    s_discard = strength_subparsers.add_parser(
        "discard",
        help="Keep a day's activity out of the strength history",
        description=(
            "Keep the day's activity out of the strength history: a hotel gym, a warm-up "
            "recorded as strength, an activity logged too badly to fix. It still counts as "
            "training and the sets stay stored. On a day with two strength activities, it "
            "asks which one."
        ),
    )
    s_discard.add_argument("date", metavar="DATE", type=parse_single_date, help=date_help)
    s_discard.add_argument("--undo", action="store_true",
                           help="Bring the activity back into the strength history")
    s_discard.set_defaults(func=run_strength_discard)
    # The family's other commands, in files of their own.
    add_log_parsers(strength_subparsers)
    add_ingest_parser(strength_subparsers)

    return strength_parser
