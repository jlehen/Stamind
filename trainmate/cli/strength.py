"""`strength`: the surgery on a strength activity's sets (DESIGN_strength_tracking.md §7).

`strength name` names a day's groups on the spot, `strength reset` reads a day's sets again
from Garmin, and `strength discard` keeps a day's activity out of the strength history. On a
day with two strength activities, reset and discard ask which one.
"""
import argparse
from typing import Any, Dict, List, Optional

from trainmate import clock, runtime, settings
from trainmate.cli.selectors import parse_single_date
from trainmate.db.strength import ACTIVE
from trainmate.prompt import Choice
from trainmate.queue_kind import NotApplied
from trainmate.strength import questions, sets
from trainmate.util import bold, cmd, fail, fmt_date, notice, red, wrap_text

KEEP = "keep"
CLEAR = "clear"
OTHER = "other"
ALL = "all"
NONE = "none"


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


def _group_at(rows: List[Dict[str, Any]], position: int) -> Optional[sets.Group]:
    """The group holding the active set at `position`, from that set on."""
    for group in sets.groups(rows):
        if group.last < position:
            continue
        start = max(position, group.first)
        return sets.Group(group.exercise, group.sets[start - group.first:], start)
    return None


def _group_prompt(group: sets.Group) -> str:
    span = sets.set_span(group.first, group.last)
    if group.exercise is None:
        return f"{span}: {sets.reps_and_load(group.reps, group.load_kg)}, unnamed. What was it?"
    return f"{span}: {sets.named_line(group)}. What was it?"


def _how_many(group: sets.Group, exercise: str) -> int:
    """"All 6 sets, or how many?": a group that was two exercises is split here (§7)."""
    count = len(group.sets)
    if count == 1:
        return 1
    choices = [Choice(ALL, f"all {count} sets")]
    choices += [Choice(str(n), f"the first {n}") for n in range(1, count)]
    picked = runtime.prompt.choose(f"{exercise}: all {count} sets, or how many?", choices,
                                   default=ALL)
    return count if picked == ALL else int(picked)


def _ask_group(activity_id: str, group: sets.Group, recent: List[str]) -> int:
    """Asks what one group was and applies the answer; returns the next position to ask."""
    choices = [Choice(f"a{n}", name) for n, name in enumerate(recent, 1)]
    choices.append(Choice(OTHER, "something else…"))
    clear = "leave it unnamed" + (", clearing its name" if group.exercise else "")
    choices.append(Choice(CLEAR, clear))
    choices.append(Choice(KEEP, "keep it as it is"))
    picked = runtime.prompt.choose(wrap_text(_group_prompt(group)), choices, default=KEEP)
    if picked == KEEP:
        return group.last + 1
    if picked == CLEAR:
        runtime.db.name_exercise_sets(activity_id, group.seqs, None)
        print(f"{_capitalize(sets.set_span(group.first, group.last))} left unnamed.")
        return group.last + 1
    if picked == OTHER:
        text = runtime.prompt.ask_text(sets.SOMETHING_ELSE["ask"]).strip()
        try:
            exercise = questions.choose_proposed(text)
        except NotApplied as not_applied:
            print(wrap_text(str(not_applied)))
            return group.first
    else:
        exercise = recent[int(picked[1:]) - 1]
    count = _how_many(group, exercise)
    runtime.db.name_exercise_sets(activity_id, group.seqs[:count], exercise)
    print(f"Named {sets.set_span(group.first, group.first + count - 1)}: {exercise}.")
    return group.first + count


def _capitalize(text: str) -> str:
    return text[:1].upper() + text[1:]


def _name_activity(activity: Dict[str, Any], recent: List[str]) -> None:
    """Goes through an activity's groups, named or not, in order. Naming by hand declares the
    sets final, so a waiting "are the sets final?" question is settled first (§7)."""
    activity_id = activity["activity_id"]
    if not activity["sets_final_at"]:
        runtime.db.freeze_exercise_sets(activity_id, clock.now())
    print()
    print(bold(_title(activity)))
    position = 1
    while True:
        group = _group_at(runtime.db.get_exercise_sets(activity_id), position)
        if group is None:
            return
        position = _ask_group(activity_id, group, recent)


def run_strength_name(args: argparse.Namespace) -> None:
    """Names the groups of a day's strength activities on the spot (§7)."""
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
        help="Name, read again or discard the sets of a strength activity",
        description=(
            "TrainMate reads your sets from Garmin the morning after you lift. Anything it "
            "can't name, it asks you about through the queue. These commands fix a day by "
            "hand."
        ),
    )
    strength_subparsers = strength_parser.add_subparsers(
        dest="subcommand", help="Strength sub-commands"
    )
    date_help = "The activity's day: YYYY-MM-DD, 'today', or an offset like -1d"

    s_name = strength_subparsers.add_parser(
        "name",
        help="Name the sets of a day's activity, group by group",
        description=(
            "Go through every group of the day's activities, named or not, and name it. After "
            "a name, say whether it covers the whole group or only its first sets, and the "
            "rest are asked again."
        ),
    )
    s_name.add_argument("date", metavar="DATE", type=parse_single_date, help=date_help)
    s_name.set_defaults(func=run_strength_name)

    s_reset = strength_subparsers.add_parser(
        "reset",
        help="Read a day's sets again from Garmin, dropping the names given in TrainMate",
        description=(
            "Read the day's sets again from Garmin, so a name fixed in Garmin Connect comes "
            "in. The names given in TrainMate for that day are dropped, and a question is "
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
    return strength_parser
