"""One selector grammar for every filtering command (DESIGN_cli_selectors.md).

`-d/--date`, `-m/--mesocycle`, `-M/--macrocycle` and `-g/--goal` all take the same
`A..B` range spelling, and this file is the spelling: what an atom may be, what a range
parses to, and how a command registers the flags. Turning whichever flags were given
into one (start_date, end_date) pair needs the database, so it is `cli/windows.py`.
"""
import argparse
import re
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Optional

from trainmate.clock import fmt_span, today_date as _today_date, today_str as _today_str


SEP = ".."

_ISO_RE = re.compile(r"\d{4}-\d{2}-\d{2}$")
OFFSET_RE = re.compile(r"([+-]?)(\d+(?:\.\d+)?)([dw])$")

# Every command that filters by range, in the athlete's words. Kept next to the grammar
# so the error messages and the help strings say the same thing.
RANGE_SYNTAX = (
    "DATE, DATE.., ..DATE, DATE..DATE, or a span like 7d / 2w "
    "(dates are YYYY-MM-DD, 'today', or a signed offset like -7d / +2w)"
)


class SelectorError(argparse.ArgumentTypeError):
    """A selector that does not parse. Raised at argparse time, reported like any bad value."""


@dataclass(frozen=True)
class DateRange:
    """A parsed `-d` selector, still unresolved: `today` and offsets resolve at use time."""
    start: Optional[str] = None
    end: Optional[str] = None
    span: Optional[str] = None  # bare span ('7d'): which side of today it covers is the
                                # command's call, not the selector's


@dataclass(frozen=True)
class IdRange:
    """A parsed `-m`/`-M`/`-g` selector. `current` is the bare flag: the one in progress."""
    start: Optional[int] = None
    end: Optional[int] = None
    current: bool = False


CURRENT = IdRange(current=True)


def offset_days(sign: str, amount: str, unit: str) -> int:
    days = float(amount) * (7 if unit == "w" else 1)
    return int(round(days)) * (-1 if sign == "-" else 1)


def _parse_date_atom(raw: str) -> str:
    """Resolves one endpoint — an ISO date, `today`, or a signed offset — to an ISO date."""
    atom = raw.strip().lower()
    if atom == "today":
        return _today_str()
    if _ISO_RE.match(atom):
        try:
            datetime.strptime(atom, "%Y-%m-%d")
        except ValueError:
            raise SelectorError(f"'{raw}' is not a real date (YYYY-MM-DD).")
        return atom
    match = OFFSET_RE.match(atom)
    if match and match.group(1):
        return (
            _today_date() + timedelta(days=offset_days(*match.groups()))
        ).strftime("%Y-%m-%d")
    if match:
        raise SelectorError(
            f"'{raw}' needs a sign to be an endpoint: '-{atom}' for {atom} ago, "
            f"'+{atom}' for {atom} ahead. Without one it is a span, which only stands alone."
        )
    raise SelectorError(f"'{raw}' is not a date. Use {RANGE_SYNTAX}.")


def parse_date_range(raw: str) -> DateRange:
    """argparse type for `-d/--date`. The grammar is `A..B` with either side optional."""
    text = raw.strip()
    if not text:
        raise SelectorError(f"Empty date selector. Use {RANGE_SYNTAX}.")
    if SEP not in text:
        if OFFSET_RE.match(text.lower()) and not text.startswith(("+", "-")):
            return DateRange(span=text.lower())
        day = _parse_date_atom(text)
        return DateRange(start=day, end=day)
    if text.count(SEP) > 1:
        raise SelectorError(f"'{raw}' has more than one '..'. Use {RANGE_SYNTAX}.")
    left, right = text.split(SEP)
    if not left and not right:
        raise SelectorError(f"'{raw}' bounds nothing. Use {RANGE_SYNTAX}.")
    start = _parse_date_atom(left) if left else None
    end = _parse_date_atom(right) if right else None
    if start and end and start > end:
        raise SelectorError(f"'{raw}' ends before it starts.")
    return DateRange(start=start, end=end)


def _parse_id_atom(raw: str, label: str) -> int:
    try:
        return int(raw)
    except ValueError:
        raise SelectorError(f"'{raw}' is not a {label} ID. Use ID, ID.., ..ID or ID..ID.")


def parse_id_range(raw: str, label: str = "mesocycle") -> IdRange:
    """argparse type for `-m`/`-M`/`-g` in their filtering role — same grammar over IDs."""
    text = raw.strip()
    if not text:
        return CURRENT
    if SEP not in text:
        one = _parse_id_atom(text, label)
        return IdRange(start=one, end=one)
    if text.count(SEP) > 1:
        raise SelectorError(f"'{raw}' has more than one '..'.")
    left, right = text.split(SEP)
    if not left and not right:
        raise SelectorError(f"'{raw}' bounds nothing. Use ID, ID.., ..ID or ID..ID.")
    return IdRange(
        start=_parse_id_atom(left, label) if left else None,
        end=_parse_id_atom(right, label) if right else None,
    )


def _maybe_date_atom(raw: str) -> Optional[str]:
    """`_parse_date_atom` for an atom that may not be a date at all: returns the ISO day
    when the spelling *is* a date one, None when it is something else entirely (a mesocycle
    name). A malformed date still raises — `2026-13-40` is a typo, not a name."""
    atom = raw.strip().lower()
    if atom == "today" or _ISO_RE.match(atom):
        return _parse_date_atom(raw)
    match = OFFSET_RE.match(atom)
    if match and match.group(1):
        return _parse_date_atom(raw)
    if match:
        raise SelectorError(
            f"'{raw}' is a span, not a day: a note files to the mesocycle covering ONE day. "
            f"Use '-{atom}' for {atom} ago or '+{atom}' for {atom} ahead."
        )
    return None


def _mesocycle_listing(mesocycles: list) -> str:
    """The mesocycles searched, name and dates, to retry an unmatched atom against — an
    error listing rather than an interactive picker, so the bot behaves identically (§5).
    Mesocycles from several plans are grouped under their `goal_title`."""
    def row(m):
        return f"[{m['id']}] {m['name']} ({fmt_span(m['start_date'], m['end_date'], sep=' -> ')})"

    goals = list(dict.fromkeys(m.get('goal_title') for m in mesocycles))
    if len(goals) < 2:
        return "This plan's mesocycles:\n" + "\n".join(f"  {row(m)}" for m in mesocycles)
    groups = "\n".join(
        f"  {goal}:\n" + "\n".join(f"    {row(m)}" for m in mesocycles
                                   if m.get('goal_title') == goal)
        for goal in goals
    )
    return f"The active plans' mesocycles:\n{groups}"


def resolve_meso_atom(atom, mesocycles: list) -> dict:
    """The ONE mesocycle an atom names, resolved against the mesocycles given — one plan's,
    or several plans' in date order (DESIGN_plan_feedback.md §5).

    A bare integer is a mesocycle ID, a date atom is the mesocycle covering that day, and
    anything else is a case-insensitive infix of a mesocycle name that must match exactly
    one. `CURRENT` (a bare `-m`) is the mesocycle covering today. Where two plans cover the
    same day, the first one given wins. Raises `SelectorError` listing the mesocycles when
    nothing — or more than one thing — matches.

    Single-target on purpose: range spellings are refused, because a note files to one
    mesocycle. The range grammar can lift this the day a command wants `-m climb` as a
    filter (DESIGN_cli_selectors.md §1)."""
    if not mesocycles:
        raise SelectorError("This plan has no mesocycles to file a note against.")
    listing = _mesocycle_listing(mesocycles)
    where = ("this plan" if len({m['macrocycle_id'] for m in mesocycles}) == 1
             else "the active plans")

    if atom is None or atom == CURRENT or (isinstance(atom, str) and not atom.strip()):
        today = _today_str()
        mesocycle = next(
            (m for m in mesocycles if m['start_date'] <= today <= m['end_date']), None
        )
        if not mesocycle:
            raise SelectorError(f"No mesocycle of {where} covers today ({today}).\n{listing}")
        return mesocycle

    text = str(atom).strip()
    if SEP in text:
        raise SelectorError(
            f"'{text}' is a range; a note files to one mesocycle, so -m takes a single atom."
        )
    if text.isdigit():
        mesocycle = next((m for m in mesocycles if m['id'] == int(text)), None)
        if not mesocycle:
            raise SelectorError(
                f"Mesocycle {text} is not part of {where}.\n{listing}"
            )
        return mesocycle

    day = _maybe_date_atom(text)
    if day:
        mesocycle = next(
            (m for m in mesocycles if m['start_date'] <= day <= m['end_date']), None
        )
        if not mesocycle:
            raise SelectorError(f"No mesocycle of {where} covers {day}.\n{listing}")
        return mesocycle

    matches = [m for m in mesocycles if text.lower() in m['name'].lower()]
    if len(matches) == 1:
        return matches[0]
    if not matches:
        raise SelectorError(f"No mesocycle name contains '{text}'.\n{listing}")
    names = ", ".join(f"'{m['name']}'" for m in matches)
    raise SelectorError(f"'{text}' matches several mesocycles ({names}).\n{listing}")


def parse_single_date(raw: str) -> str:
    """argparse type for the commands that act on ONE day (`workout adapt`, `benchmark
    record`): the same atoms as a range endpoint, but no `..`."""
    if SEP in raw:
        raise SelectorError(f"'{raw}' is a range; this command takes a single date.")
    return _parse_date_atom(raw)


def parse_target(raw: str):
    """argparse type for a positional target: a row ID, or a date selector.

    Returns ``('id', int)`` or ``('date', DateRange)``. A bare integer is always an ID —
    which is why a span has to carry its unit (`7d`, not `7`)."""
    text = raw.strip()
    if text.isdigit():
        return ("id", int(text))
    return ("date", parse_date_range(text))


def add_selector_args(
    parser, *, date=True, meso=False, macro=False, goal=False, sport=False,
    direction="backward", default=None, span_days=7, group=None, generates=False,
):
    """Registers this command's selector flags and records how it fills the gaps.

    ``direction`` and ``default`` are the command's own policy, read back by
    ``resolve_window``: ``forward`` plans (an open end stays open), ``backward`` reviews
    history (an open end is today), ``none`` sweeps everything it is not told to spare.
    ``default`` is a selector string used only when no dimension is given at all.
    ``group`` puts the flags in a mutually exclusive group while the policy still rides on
    the parser (`workout generate`, where the span is one choice among several).
    ``generates`` says the same flags name the span the command WRITES rather than a
    filter it reads (§8), so the help says so."""
    target = group if group is not None else parser
    lead = "Generate" if generates else "Restrict to"
    if date:
        target.add_argument(
            "-d", "--date", dest="date_range", type=parse_date_range, metavar="RANGE",
            help=f"{lead} a date range: {RANGE_SYNTAX}"
                 + (f" (default: {default})" if default else "")
        )
    if meso:
        target.add_argument(
            "-m", "--mesocycle", dest="meso_range", type=parse_id_range, nargs="?",
            const=CURRENT, metavar="RANGE",
            help=f"{lead} a mesocycle range: ID, ID.., ..ID or ID..ID "
                 "(bare -m is the current mesocycle)"
        )
    if macro:
        target.add_argument(
            "-M", "--macrocycle", dest="macro_range", nargs="?", const=CURRENT,
            type=lambda raw: parse_id_range(raw, "macrocycle"), metavar="RANGE",
            help=f"{lead} a macrocycle range: ID, ID.., ..ID or ID..ID "
                 "(bare -M is the active plan). List IDs with 'plan versions'."
                 + (" Naming one plan also settles which to follow where two cover the "
                    "same days." if generates else "")
        )
    if goal:
        target.add_argument(
            "-g", "--goal", dest="goal_range", nargs="?", const=CURRENT,
            type=lambda raw: parse_id_range(raw, "goal"), metavar="RANGE",
            help=(
                "Generate a goal's whole plan span, its plan start through its target "
                "date: ID, ID.., ..ID or ID..ID (bare -g is the active goal)"
                if generates else
                "Restrict to the plan span of a goal range: ID, ID.., ..ID or ID..ID "
                "(bare -g is the active goal)"
            )
        )
    if sport:
        target.add_argument(
            "-t", "--type", "--sport-type", "--sport", dest="sport_type",
            help="Filter by sport type"
        )
    parser.set_defaults(_selector_policy=(direction, default, span_days))


def add_single_date_arg(parser, help_text: str, repeat: bool = False):
    """Registers `-d/--date` for a command that acts on days rather than a range.

    `repeat` lets it be given more than once, and `args.date` is then the list of days
    (`workout tweak`, DESIGN_workout_tweak.md §3.1)."""
    action = "store"
    if repeat:
        action = "append"
    parser.add_argument(
        "-d", "--date", dest="date", type=parse_single_date, metavar="DATE",
        action=action, help=help_text
    )
