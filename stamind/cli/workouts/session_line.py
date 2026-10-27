"""Sessions as a table, one row each, or one session as one line — and the short form
drawn under either.

`workout list` and the `workout generate` preview draw the table, so the sessions the
athlete is asked to accept read exactly like the ones they will live with. `workout list
-vv` (so `workout show`) keeps the one line, since paragraphs follow each session.
"""
import re
import textwrap
from typing import Callable, List, Optional, Set, Tuple
from stamind.analytics import intensity
from stamind.workout_state import calendar_status, modification_markers
from stamind.sports import is_strength_sport
from stamind.strength.prescription import exercise_lines
from stamind.text import (
    blue, bold, cyan, display_width, flex_width, gray, green, magenta, red, render_table,
    yellow,
)
from stamind.clock import fmt_date


# How each `adherence.classify_adherence` status is coloured. The word itself rides on
# the verdict, stamped from the shared STATUS_LABELS (ARCHITECTURE.md §5).
_ADHERENCE_COLORS = {
    'done': green,
    'partial': yellow,
    'missed': red,
    'pending': gray,
    'rest_ok': green,
    'rest_violation': red,
}


def _verdict(adherence: Optional[dict]) -> List[Tuple[str, Callable]]:
    """The verdict as a marker, a word and its colour; none for anything with no verdict —
    a future session, a proposal, a removed row."""
    label = (adherence or {}).get('label')
    if not label:
        return []
    return [(label.upper(), _ADHERENCE_COLORS.get(adherence.get('status'), yellow))]


def _flags(w: dict) -> List[Tuple[str, Callable]]:
    """The markers after the verdict, each a word and its colour, in the order they print."""
    flags = []
    # Benchmark identity is a stored column, orthogonal to the modification/sync/removed
    # axes (a benchmark can also be adapted), so it gets its own marker straight off the
    # column (DESIGN_benchmark_workouts.md §3.1/§6).
    if w.get('benchmark_type'):
        flags.append(("BENCHMARK", blue))
    markers = modification_markers(w)
    if markers:
        flags.append((", ".join(markers), yellow))
    status = calendar_status(w)
    if status == 'synced':
        flags.append(("SYNCED", green))
    elif status == 'stale':
        flags.append(("STALE", yellow))
    if w.get('removed'):
        flags.append(("REMOVED", red))
    # Only a `workout generate` proposal carries this: the day is being left alone rather
    # than rewritten, which the rest of the line cannot show
    # (DESIGN_workout_revisions.md §7.1).
    if w.get('keep'):
        flags.append(("KEPT", green))
    return flags


def _bracketed(markers: list) -> str:
    return "".join(bold(color(f" [{word}]")) for word, color in markers)


def _listed(markers: list) -> str:
    return ", ".join(bold(color(word)) for word, color in markers)


def adherence_marker(adherence: Optional[dict]) -> str:
    """The `[DONE]`/`[MISSED]`/`[PARTIAL]`/… marker for a session already behind us, empty
    for one with no verdict."""
    return _bracketed(_verdict(adherence))


def workout_line(w: dict, adherence: Optional[dict] = None) -> str:
    """One-line rendering of a workout, for `workout list -vv` and `workout cut-short`.

    `adherence` is `analytics.compare.adherence_verdicts`' entry for this session when the
    day is behind us; None leaves the line without a verdict."""
    duration = w.get('duration_minutes')
    tss = w.get('tss')
    rpe = w.get('rpe')
    duration_str = f" | {duration}min" if duration else ""
    tss_str = f" | TSS {tss}" if tss is not None else ""
    rpe_str = f" | RPE {rpe}" if rpe is not None else ""
    ident = f"ID: {w['id']} | " if w.get('id') is not None else ""
    # First of the markers: for a day already behind us, what became of the session is
    # the salient state, the way [SYNCED] is for a day ahead.
    markers = adherence_marker(adherence) + _bracketed(_flags(w))
    return (
        f"{ident}{cyan(fmt_date(w['date']))} | {magenta(w['sport_type'].upper())} | "
        f"{bold(w['title'])}{markers}{duration_str}{tss_str}{rpe_str}"
    )


_TABLE_HEADERS = ["ID", "Date", "Sport", "Session", "Result", "Min", "TSS", "RPE", "Flags"]
_MIN_TITLE_WIDTH = 24


def _cell(value) -> str:
    return "" if value is None else str(value)


def session_table(
    workouts: list, verdicts: Optional[dict] = None, under: Optional[list] = None,
) -> Tuple[str, Set[str]]:
    """The sessions as a table, one row each, and the markers it printed for the legend.

    `verdicts` is `adherence_verdicts`, keyed by workout ID. `under` holds each session's
    own lines to print beneath its row (`prescription_lines`, the `-L` link). A column no
    session fills is left out: a `workout generate` preview has no ID and no verdict."""
    rows, markers = [], set()
    for w in workouts:
        result = _listed(_verdict((verdicts or {}).get(w.get('id'))))
        flags = _listed(_flags(w))
        markers |= line_markers(f"{result} {flags}")
        rows.append([
            _cell(w.get('id')), cyan(fmt_date(w['date'])), magenta(w['sport_type'].upper()),
            bold(w['title']), result, _cell(w.get('duration_minutes')), _cell(w.get('tss')),
            _cell(w.get('rpe')), flags,
        ])
    kept = [i for i in range(len(_TABLE_HEADERS)) if any(row[i] for row in rows)]
    headers = [_TABLE_HEADERS[i] for i in kept]
    rows = [[row[i] for i in kept] for row in rows]
    # Titles are clipped to fit the screen, but not below what still names the session;
    # narrower than that, the table runs wide and the terminal wraps it, as `data sa` does.
    flex = headers.index("Session")
    if flex_width(headers, rows, flex) < _MIN_TITLE_WIDTH:
        flex = None
    return render_table(headers, rows, flex=flex, under=under), markers


def prescription_lines(w: dict) -> List[str]:
    """The short form of what a session asks, indented and in gray to go under its row: a
    strength session's exercises, none until the strength planner wrote them
    (DESIGN_strength_tracking.md §9); any other session's time in each intensity zone
    (DESIGN_intensity_distribution.md §9.8)."""
    if is_strength_sport(w['sport_type']):
        lines = exercise_lines(w.get('prescribed_sets') or [])
    else:
        lines = [intensity.format_planned_zones(w)]
    return [f"      {gray(line)}" for line in lines if line]


# Every marker a session can carry, in the order the line and the table print them, and
# the one phrase that says what it means. `STALE` in particular names no subject on its
# own: the word is about the session's Google Calendar event, not the session.
_MARKER_GLOSS = (
    ("DONE", "the session happened as asked"),
    ("PARTIAL", "you trained, but not what was asked — -vv says what differed"),
    ("MISSED", "no activity recorded against it"),
    ("REST OK", "a rest day, and you rested"),
    ("REST BROKEN", "a rest day you trained on"),
    ("NOT YET", "today, and still ahead of you"),
    ("BENCHMARK", "a repeatable test, comparable across the plan"),
    ("ADAPTED", "'workout adapt' rewrote it; ×N is how many times"),
    ("TWEAKED", "you rewrote it yourself"),
    ("SYNCED", "its Google Calendar event matches this"),
    ("STALE", "its Google Calendar event is out of date — 'workout push' updates it"),
    ("REMOVED", "dropped from the schedule"),
    ("KEPT", "left as it stands, not rewritten"),
)

# The vocabulary above, matched against a rendered line. Fixed words rather than a general
# `[A-Z]+` pattern, so an all-caps sport type or title can never enter the legend.
_MARKER_RE = re.compile("|".join(word for word, _gloss in _MARKER_GLOSS))


def line_markers(line: str) -> Set[str]:
    """The markers one rendered line or table cell carries, for the legend to gloss.

    Read back off the text rather than re-derived from the row, so the legend can never
    name a marker the listing did not print."""
    return set(_MARKER_RE.findall(line))


def print_marker_legend(markers: Set[str]) -> None:
    """Draws the gray footer saying what the markers on screen mean, after a blank line.

    Glosses only the markers the listing actually printed, the way `journal` glosses only
    the outcomes on screen (DESIGN_logging.md §7.2); a legend is answer-level output, not
    an aside (DESIGN_output_verbosity.md §3.3)."""
    text = " · ".join(
        f"{word} = {gloss}" for word, gloss in _MARKER_GLOSS if word in markers
    )
    if not text:
        return
    print()
    for line in textwrap.wrap(
        text, width=display_width(), subsequent_indent="  ", break_on_hyphens=False
    ):
        print(gray(line))
