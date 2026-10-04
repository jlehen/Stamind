"""`strength`: the surgery on a strength activity's sets (DESIGN_strength_tracking.md §7).

`strength name` shows a day's sets and names the ones picked, `strength reset` reads a day's
sets again from Garmin, and `strength discard` keeps a day's activity out of the strength
history. On a day with two strength activities, reset and discard ask which one. `strength
log` reads the record back, and `strength exercises` the exercise table behind it. `strength
ingest` is the sixth command of the family and lives in `strength_ingest.py`
(DESIGN_gym_logger.md §5).
"""
import argparse
from typing import Any, Dict, List, Sequence

from stamind import clock, runtime, settings
from stamind.cli.selectors import parse_single_date
from stamind.cli.strength_ingest import add_ingest_parser
from stamind.db.strength import ACTIVE
from stamind.prompt import Choice
from stamind.queue_kind import NotApplied
from stamind.strength import questions, sets, vocabulary
from stamind.text import bold, capitalized, cmd, gray, red, wrap_text
from stamind.output import fail, notice
from stamind.clock import fmt_date

# The heading for a lift with no movement pattern: a class the table gives none, or a Garmin
# name the table lacks (DESIGN_exercise_table.md §3.4, §6).
NO_PATTERN = "no pattern"

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


def _ask_line(activity_id: str, line: sets.Line, recent: List[str]) -> None:
    """Asks what one line of the layout was and applies the answer."""
    span = sets.position_list(line.positions)
    seqs = [s["seq"] for s in line.sets]
    choices = [Choice(f"a{n}", vocabulary.words(key)) for n, key in enumerate(recent, 1)]
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
        exercise = recent[int(picked[1:]) - 1]
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


def _plural(count: int, word: str) -> str:
    return f"{count} {word}{'' if count == 1 else 's'}"


def _pattern_of(key: str) -> str:
    """A lift's movement pattern, or the heading for one that has none."""
    known = vocabulary.get(key)
    if known is None or not known.pattern:
        return NO_PATTERN
    return known.pattern


def _matches(text: str, keys: Sequence[str]) -> List[str]:
    """The lifts `text` names: the one whose words are exactly it, else every one whose
    words contain it, case ignored, sorted by their words (DESIGN_exercise_table.md §7)."""
    wanted = text.strip().lower()
    exact = [key for key in keys if vocabulary.words(key) == wanted]
    if exact:
        return exact
    return sorted((key for key in keys if wanted in vocabulary.words(key)), key=vocabulary.words)


def _muscles_and_gear(known: vocabulary.Exercise) -> str:
    """'quads, glutes · Barbell, Squat Rack': a class's main muscles and its gear, as the
    exercise listing shows them (DESIGN_exercise_table.md §7). A class with no muscles shows
    its gear alone."""
    muscles = ", ".join(muscle.lower().replace("_", " ") for muscle in known.muscles)
    gear = ", ".join(known.gear)
    if not muscles:
        return gear
    return f"{muscles} · {gear}"


def _pattern_and_gear(key: str) -> str:
    """' — squat · Machine': what follows a lift's words in the heading of its record. A lift
    with no pattern shows its gear alone, and a key the table lacks shows nothing."""
    known = vocabulary.get(key)
    if known is None:
        return ""
    gear = ", ".join(known.gear)
    if not known.pattern:
        return f" — {gear}"
    return f" — {known.pattern} · {gear}"


def _sessions_block(key: str, days: List[sets.Logged]) -> None:
    """One lift's record: its words, its movement pattern and its gear, and a line per day."""
    print()
    print(bold(wrap_text(f"{vocabulary.words(key).upper()}{_pattern_and_gear(key)}")))
    for day, lifted in days:
        print(f"  {fmt_date(day)}   {lifted}")


def _log_index(logbook: Dict[str, List[sets.Logged]]) -> None:
    """Every lift on record under its movement pattern."""
    days = {day for entries in logbook.values() for day, _ in entries}
    print(bold(f"YOUR LIFTS — {_plural(len(logbook), 'exercise')} over "
               f"{_plural(len(days), 'session')}"))
    width = max(len(vocabulary.words(key)) for key in logbook)
    for pattern in vocabulary.PATTERNS + (NO_PATTERN,):
        named = sorted((key for key in logbook if _pattern_of(key) == pattern),
                       key=vocabulary.words)
        if not named:
            continue
        print()
        print(pattern)
        for key in named:
            entries = logbook[key]
            print(f"  {vocabulary.words(key):<{width}}  "
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
                   + " every name Stamind knows.")
            return
    elif not args.pattern:
        _log_index(logbook)
        return
    for key in sorted(wanted, key=lambda k: (_pattern_of(k), vocabulary.words(k))):
        _sessions_block(key, logbook[key])


def _pattern_index(mine: Dict[str, int]) -> None:
    """The nine movement patterns and the group with none, what the table holds for each,
    and what the athlete has done in it (§4, DESIGN_exercise_table.md §7)."""
    catalog = vocabulary.all_exercises()
    print(bold(f"MOVEMENT PATTERNS — {_plural(len(catalog), 'exercise')} Stamind can name"))
    print()
    for pattern in vocabulary.PATTERNS + (NO_PATTERN,):
        known = [e for e in catalog if (e.pattern or NO_PATTERN) == pattern]
        yours = mine.get(pattern, 0)
        mine_here = gray(f"{yours} on your record") if yours else ""
        print(f"  {pattern:<16} {_plural(len(known), 'exercise'):<16} {mine_here}".rstrip())
    print()
    notice("One pattern's exercises: " + cmd("strength exercises --pattern squat")
           + ", by name: " + cmd("strength exercises row") + ".")


def run_strength_exercises(args: argparse.Namespace) -> None:
    """The shipped table: which movement patterns exist and which exercises are in them
    (§4). It ships with the code and nobody configures it. An exercise is listed and searched
    by its words, with its main muscles and its gear on a line under them
    (DESIGN_exercise_table.md §7)."""
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
        listed = [e for e in listed if wanted in e.words]
    if not listed:
        notice(f"No {args.pattern or ''} exercise Stamind knows is called "
               f"'{args.search}'.".replace("  ", " "))
        return
    title = args.pattern.upper() if args.pattern else f"'{args.search}'"
    print(bold(f"{title} — {_plural(len(listed), 'exercise')}"))
    width = max(len(e.words) for e in listed)
    for exercise in sorted(listed, key=lambda e: e.words):
        mark = "•" if exercise.key in mine else " "
        pattern = "" if args.pattern else f"  {exercise.pattern}"
        print(f"  {mark} {exercise.words:<{width}}{pattern}".rstrip())
        print(gray(wrap_text(f"      {_muscles_and_gear(exercise)}")))
    if mine & {e.key for e in listed}:
        print()
        print(gray("• on your record."))


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
        help="The exercises Stamind can name, and the movement patterns they sit in",
        description=(
            "The shipped table: every exercise Stamind can name, each with its movement "
            "pattern when it has one, its main muscles and the gear it needs. It ships with "
            "the code and nobody configures it. With no argument, the patterns and how many "
            "exercises each holds."
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

    # The gym logger's own command, in a file of its own: the family is already at the
    # ~400 lines AGENTS.md splits at (DESIGN_gym_logger.md §5).
    add_ingest_parser(strength_subparsers)

    return strength_parser
