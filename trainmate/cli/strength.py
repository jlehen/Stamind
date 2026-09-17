"""`strength`: the surgery on a strength session's sets (DESIGN_strength_tracking.md §7).

`strength name` names a day's blocks on the spot, `strength reset` reads a day's sets again
from Garmin, and `strength discard` marks a day's session as one that does not count.
`strength log` reads the record back, and `strength exercises` the vocabulary behind it.
"""
import argparse
from typing import Any, Dict, List, Optional, Sequence

from trainmate import clock, runtime, settings
from trainmate.cli.selectors import parse_single_date
from trainmate.db.strength import ACTIVE
from trainmate.prompt import Choice
from trainmate.queue_kind import NotApplied
from trainmate.strength import questions, sets, vocabulary
from trainmate.util import bold, cmd, fail, fmt_date, gray, notice, red, wrap_text

# The heading for a lift whose Garmin name the vocabulary lacks: stored verbatim, with
# no pattern (§4).
NO_PATTERN = "no pattern"

KEEP = "keep"
CLEAR = "clear"
OTHER = "other"
ALL = "all"


def _title(activity: Dict[str, Any]) -> str:
    return questions.session_words(sets.session(activity))


def _block_at(rows: List[Dict[str, Any]], position: int) -> Optional[sets.Block]:
    """The block holding the active set at `position`, from that set on."""
    for block in sets.blocks(rows):
        if block.last < position:
            continue
        start = max(position, block.first)
        return sets.Block(block.exercise, block.sets[start - block.first:], start)
    return None


def _block_prompt(block: sets.Block) -> str:
    span = sets.set_span(block.first, block.last)
    if block.exercise is None:
        return f"{span}: {sets.reps_and_load(block.reps, block.load_kg)}, unnamed. What was it?"
    return f"{span}: {sets.named_line(block)}. What was it?"


def _how_many(block: sets.Block, exercise: str) -> int:
    """"All 6 sets, or how many?": a block that was two exercises is split here (§7)."""
    count = len(block.sets)
    if count == 1:
        return 1
    choices = [Choice(ALL, f"all {count} sets")]
    choices += [Choice(str(n), f"the first {n}") for n in range(1, count)]
    picked = runtime.prompt.choose(f"{exercise}: all {count} sets, or how many?", choices,
                                   default=ALL)
    return count if picked == ALL else int(picked)


def _ask_block(activity_id: str, block: sets.Block, recent: List[str]) -> int:
    """Asks what one block was and applies the answer; returns the next position to ask."""
    choices = [Choice(f"a{n}", name) for n, name in enumerate(recent, 1)]
    choices.append(Choice(OTHER, "something else…"))
    clear = "leave it unnamed" + (", clearing its name" if block.exercise else "")
    choices.append(Choice(CLEAR, clear))
    choices.append(Choice(KEEP, "keep it as it is"))
    picked = runtime.prompt.choose(wrap_text(_block_prompt(block)), choices, default=KEEP)
    if picked == KEEP:
        return block.last + 1
    if picked == CLEAR:
        runtime.db.name_exercise_sets(activity_id, block.seqs, None)
        print(f"{_capitalize(sets.set_span(block.first, block.last))} left unnamed.")
        return block.last + 1
    if picked == OTHER:
        text = runtime.prompt.ask_text(sets.SOMETHING_ELSE["ask"]).strip()
        try:
            exercise = questions.choose_proposed(text)
        except NotApplied as not_applied:
            print(wrap_text(str(not_applied)))
            return block.first
    else:
        exercise = recent[int(picked[1:]) - 1]
    count = _how_many(block, exercise)
    runtime.db.name_exercise_sets(activity_id, block.seqs[:count], exercise)
    print(f"Named {sets.set_span(block.first, block.first + count - 1)}: {exercise}.")
    return block.first + count


def _capitalize(text: str) -> str:
    return text[:1].upper() + text[1:]


def _name_session(activity: Dict[str, Any], recent: List[str]) -> None:
    """Goes through a session's blocks, named or not, in order. Naming by hand declares the
    sets final, so a waiting "are the sets final?" question is settled first (§7)."""
    activity_id = activity["activity_id"]
    if not activity["sets_final_at"]:
        runtime.db.freeze_exercise_sets(activity_id, clock.now())
    print()
    print(bold(_title(activity)))
    position = 1
    while True:
        block = _block_at(runtime.db.get_exercise_sets(activity_id), position)
        if block is None:
            return
        position = _ask_block(activity_id, block, recent)


def run_strength_name(args: argparse.Namespace) -> None:
    """Names the blocks of a day's strength session on the spot (§7)."""
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
                   "after the session, or now with " + cmd(f"strength reset {day}") + ".")
            return
        notice(f"No strength session with sets on {fmt_date(day)}.")
        return
    recent = sets.recent_exercises()
    for activity in with_sets:
        _name_session(activity, recent)


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
        count = len([block for block in found if block.exercise is None])
        if not count:
            print(f"{title}: sets read again and frozen. Every set has a name.")
            continue
        print(wrap_text(
            f"{title}: sets read again and frozen. {count} block{'s' if count != 1 else ''} "
            "without a name: the questions are in the queue, " + cmd("queue answer")
            + " goes through them."
        ))


def run_strength_discard(args: argparse.Namespace) -> None:
    """Marks a day's session as one that does not count, or counts it again with --undo."""
    day = args.date
    activities = runtime.db.strength_activities(day, date=day)
    if not activities:
        notice(f"No strength activity on {fmt_date(day)}.")
        return
    for activity in activities:
        runtime.db.set_activity_discarded(activity["activity_id"], not args.undo)
    if args.undo:
        print(f"The {fmt_date(day)} strength session counts again.")
        return
    print(wrap_text(
        f"Discarded the {fmt_date(day)} strength session: its sets stay on record but no "
        "longer count, and its waiting questions are settled. "
        + cmd(f"strength discard {day} --undo") + " counts it again."
    ))


def _plural(count: int, word: str) -> str:
    return f"{count} {word}{'' if count == 1 else 's'}"


def _pattern_of(name: str) -> str:
    """A lift's movement pattern, or the heading for one the vocabulary lacks (§4)."""
    known = vocabulary.get(name)
    return known.pattern if known else NO_PATTERN


def _matches(text: str, names: Sequence[str]) -> List[str]:
    """The lifts `text` names: the exact name if there is one, else everything it is part
    of, case ignored."""
    wanted = text.strip().lower()
    exact = [name for name in names if name.lower() == wanted]
    return exact or sorted(name for name in names if wanted in name.lower())


def _sessions_block(name: str, days: List[sets.Logged]) -> None:
    """One lift's record: its name, where it sits in the vocabulary, and a line per day."""
    known = vocabulary.get(name)
    where = f" — {known.pattern}, {known.equipment}" if known else ""
    print()
    print(bold(f"{name.upper()}{where}"))
    for day, lifted in days:
        print(f"  {fmt_date(day)}   {lifted}")


def _log_index(logbook: Dict[str, List[sets.Logged]]) -> None:
    """Every lift on record under its movement pattern."""
    days = {day for entries in logbook.values() for day, _ in entries}
    print(bold(f"YOUR LIFTS — {_plural(len(logbook), 'exercise')} over "
               f"{_plural(len(days), 'session')}"))
    width = max(len(name) for name in logbook)
    for pattern in vocabulary.PATTERNS + (NO_PATTERN,):
        named = sorted(name for name in logbook if _pattern_of(name) == pattern)
        if not named:
            continue
        print()
        print(pattern)
        for name in named:
            entries = logbook[name]
            known = vocabulary.get(name)
            equipment = known.equipment if known else ""
            print(f"  {name:<{width}}  {equipment:<10} "
                  + gray(f"{_plural(len(entries), 'session')}, last "
                         f"{fmt_date(entries[-1].date)}"))
    print()
    notice("A lift's own sets: " + cmd("strength log EXERCISE") + ", a whole pattern: "
           + cmd("strength log --pattern squat") + ".")


def run_strength_log(args: argparse.Namespace) -> None:
    """The athlete's own logbook: what was lifted, and when (§7). With no exercise and no
    pattern it is the index of the lifts on record."""
    logbook = sets.logbook()
    if not logbook:
        since = settings.strength_sets_since()
        if not since:
            notice("Strength sets are not read. Set the first day to read them from with "
                   + cmd("settings set strength-sets-since YYYY-MM-DD") + ".", red)
            return
        notice(f"No named sets on record since {since}. They are read the morning after a "
               "session, and " + cmd("strength name DATE") + " names what the watch could "
               "not.")
        return
    wanted = list(logbook)
    if args.pattern:
        wanted = [name for name in wanted if _pattern_of(name) == args.pattern]
        if not wanted:
            notice(f"No {args.pattern} lift on record yet.")
            return
    if args.exercise:
        wanted = _matches(args.exercise, wanted)
        if not wanted:
            where = f" {args.pattern}" if args.pattern else ""
            notice(f"No{where} lift on record is called '{args.exercise}'. "
                   + cmd("strength log") + " lists yours, " + cmd("strength exercises")
                   + " every name TrainMate knows.")
            return
    elif not args.pattern:
        _log_index(logbook)
        return
    for name in sorted(wanted, key=lambda n: (_pattern_of(n), n)):
        _sessions_block(name, logbook[name])


def _pattern_index(mine: Dict[str, int]) -> None:
    """The nine movement patterns, what the vocabulary holds for each, and what the athlete
    has done in it (§4)."""
    catalog = vocabulary.all_exercises()
    print(bold(f"MOVEMENT PATTERNS — {_plural(len(catalog), 'exercise')} TrainMate can name"))
    print()
    for pattern in vocabulary.PATTERNS:
        known = [e for e in catalog if e.pattern == pattern]
        yours = mine.get(pattern, 0)
        mine_here = gray(f"{yours} on your record") if yours else ""
        print(f"  {pattern:<16} {_plural(len(known), 'exercise'):<16} {mine_here}".rstrip())
    print()
    notice("One pattern's exercises: " + cmd("strength exercises --pattern squat")
           + ", by name: " + cmd("strength exercises row") + ".")


def run_strength_exercises(args: argparse.Namespace) -> None:
    """The shipped vocabulary: which movement patterns exist and which exercises are in them
    (§4). It ships with the code and nobody configures it."""
    mine = set(sets.logbook())
    if not args.pattern and not args.search:
        done: Dict[str, int] = {}
        for name in mine:
            done[_pattern_of(name)] = done.get(_pattern_of(name), 0) + 1
        _pattern_index(done)
        return
    listed = vocabulary.all_exercises()
    if args.pattern:
        listed = [e for e in listed if e.pattern == args.pattern]
    if args.search:
        wanted = args.search.strip().lower()
        listed = [e for e in listed if wanted in e.name.lower()]
    if not listed:
        notice(f"No {args.pattern or ''} exercise TrainMate knows is called "
               f"'{args.search}'.".replace("  ", " "))
        return
    title = args.pattern.upper() if args.pattern else f"'{args.search}'"
    print(bold(f"{title} — {_plural(len(listed), 'exercise')}"))
    width = max(len(e.name) for e in listed)
    for exercise in sorted(listed, key=lambda e: e.name):
        mark = "•" if exercise.name in mine else " "
        pattern = "" if args.pattern else f"  {exercise.pattern}"
        print(f"  {mark} {exercise.name:<{width}}  {exercise.equipment:<10}{pattern}".rstrip())
    if mine & {e.name for e in listed}:
        print()
        print(gray("• on your record."))


def add_strength_parser(subparsers):
    # strength command & subparsers — the sets of strength sessions
    # (DESIGN_strength_tracking.md §7).
    strength_parser = subparsers.add_parser(
        "strength",
        help="Read back what you lifted, or fix a session's sets by hand",
        description=(
            "TrainMate reads your sets from Garmin the morning after a session. Anything it "
            "can't name, it asks you about through the queue. `log` and `exercises` read "
            "your record and the vocabulary behind it back; the other three fix a day by "
            "hand."
        ),
    )
    strength_subparsers = strength_parser.add_subparsers(
        dest="subcommand", help="Strength sub-commands"
    )
    date_help = "The session's day: YYYY-MM-DD, 'today', or an offset like -1d"

    s_name = strength_subparsers.add_parser(
        "name",
        help="Name the sets of a day's session, block by block",
        description=(
            "Go through every block of the day's session, named or not, and name it. After "
            "a name, say whether it covers the whole block or only its first sets, and the "
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
            "queued for every block still unnamed."
        ),
    )
    s_reset.add_argument("date", metavar="DATE", type=parse_single_date, help=date_help)
    s_reset.set_defaults(func=run_strength_reset)

    s_discard = strength_subparsers.add_parser(
        "discard",
        help="Mark a day's session as one that does not count",
        description=(
            "Mark the day's session as one that should not count: a hotel gym, a warm-up "
            "recorded as strength, a session logged too badly to fix. The sets stay stored."
        ),
    )
    s_discard.add_argument("date", metavar="DATE", type=parse_single_date, help=date_help)
    s_discard.add_argument("--undo", action="store_true", help="Count the session again")
    s_discard.set_defaults(func=run_strength_discard)
    s_log = strength_subparsers.add_parser(
        "log",
        help="What you have lifted: one exercise's sessions, or the index of them all",
        description=(
            "Your own logbook, read back from the sets Garmin recorded. With no exercise, "
            "the lifts you have on record grouped by movement pattern. With one, every "
            "session it was done in, oldest first. Discarded sessions are left out, and a "
            "day with two lifting activities is one session."
        ),
    )
    s_log.add_argument(
        "exercise", metavar="EXERCISE", nargs="?",
        help="An exercise on your record: its full name, or a part of one",
    )
    s_log.add_argument(
        "-p", "--pattern", choices=vocabulary.PATTERNS,
        help="Every lift of one movement pattern, each with its own sessions",
    )
    s_log.set_defaults(func=run_strength_log)

    s_exercises = strength_subparsers.add_parser(
        "exercises",
        help="The exercises TrainMate can name, and the movement patterns they sit in",
        description=(
            "The shipped vocabulary: every exercise TrainMate can name, each in one "
            "movement pattern and one equipment class. It ships with the code and nobody "
            "configures it. With no argument, the patterns and how many exercises each "
            "holds."
        ),
    )
    s_exercises.add_argument(
        "search", metavar="TEXT", nargs="?",
        help="Only exercises whose name contains this",
    )
    s_exercises.add_argument(
        "-p", "--pattern", choices=vocabulary.PATTERNS,
        help="Only exercises of this movement pattern",
    )
    s_exercises.set_defaults(func=run_strength_exercises)

    return strength_parser
