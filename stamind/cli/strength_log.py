"""`strength log` and `strength exercises`: the athlete's record of what was lifted, and the
exercise table behind it, read back (DESIGN_strength_tracking.md §7, DESIGN_exercise_table.md
§7). The commands that change a day's sets are in `strength.py`.
"""
import argparse
from typing import Dict, List, Sequence

from stamind import settings
from stamind.strength import sets, vocabulary
from stamind.text import bold, cmd, gray, red, wrap_text
from stamind.output import notice
from stamind.clock import fmt_date

# The heading for a lift with no movement pattern: a class the table gives none, or a Garmin
# name the table lacks (DESIGN_exercise_table.md §3.4, §6).
NO_PATTERN = "no pattern"


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
    words, or the name people use for it, contain it, case ignored, sorted by their words
    (DESIGN_exercise_table.md §7)."""
    wanted = text.strip().lower()
    exact = [key for key in keys if vocabulary.words(key) == wanted]
    if exact:
        return exact
    return sorted((key for key in keys if wanted in vocabulary.searched(key)),
                  key=vocabulary.words)


def _muscles_and_gear(known: vocabulary.Exercise) -> str:
    """'quads, glutes · Barbell, Squat Rack': a class's main muscles and its gear, as the
    exercise listing shows them (DESIGN_exercise_table.md §7). A class with no muscles shows
    its gear alone, and one people call by another name says it first: 'also pallof press'."""
    parts = [f"also {name}" for name in known.also_words]
    parts.append(", ".join(muscle.lower().replace("_", " ") for muscle in known.muscles))
    parts.append(", ".join(known.gear))
    return " · ".join(part for part in parts if part)


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
        listed = [e for e in listed if wanted in vocabulary.searched(e.key)]
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


def add_log_parsers(strength_subparsers) -> None:
    """Wires `strength log` and `strength exercises` under the strength command (§7)."""
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
