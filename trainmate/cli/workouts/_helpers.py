"""Shared resolvers/formatters for the workout CLI handlers."""
import re
import textwrap
from datetime import datetime, timedelta
from typing import List, Optional, Set
from trainmate import intensity, runtime
from trainmate.calendar_state import calendar_status
from trainmate.sports import is_strength_sport
from trainmate.strength.prescription import exercise_lines
from trainmate.util import (
    bold, gray, green, red, yellow, cyan, blue, magenta, cmd, display_width, fmt_date,
    notice,
)


# The change kind of a session's live revision, as the athlete reads it
# (DESIGN_workout_revisions.md §7). A `generate` is the plan saying what it says, so it
# gets no marker, and a void carries [REMOVED] instead.
_KIND_MARKERS = {
    'adapt': 'ADAPTED',
    'tweak': 'TWEAKED',
}


def modification_markers(w: dict) -> list:
    """What has happened to a session: the kind of its latest change, plus the easings
    that still stand.

    Two facts rather than one, which is why there is no precedence rule any more: a
    session eased twice and then copied forward by a rollback still reads `[ADAPTED ×2]`
    (§12)."""
    kind = w.get('change_kind')
    count = w.get('adaptation_count') or 0
    eased = f"ADAPTED ×{count}" if count > 1 else ("ADAPTED" if count else "")
    if kind == 'adapt':
        # The tally is the whole story here; an adapt that eased nothing still reads
        # [ADAPTED], because the prescription did change.
        return [eased or "ADAPTED"]
    return [m for m in (_KIND_MARKERS.get(kind), eased) if m]


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


def adherence_marker(adherence: Optional[dict]) -> str:
    """The `[DONE]`/`[MISSED]`/`[PARTIAL]`/… marker for a session already behind us.

    Empty for anything with no verdict — a future session, a proposal, a removed row —
    which is why the listing can carry it unconditionally."""
    label = (adherence or {}).get('label')
    if not label:
        return ""
    color = _ADHERENCE_COLORS.get(adherence.get('status'), yellow)
    return bold(color(f" [{label.upper()}]"))


def workout_line(w: dict, adherence: Optional[dict] = None) -> str:
    """One-line rendering of a workout for `list`.

    Also renders a *proposed* session — a `workout generate` preview, which has no row and
    so no ID — so the plan being accepted reads exactly like the plan `list` will show.

    `adherence` is `cli.common.adherence_verdicts`' entry for this session when the day is
    behind us; None leaves the line exactly as it was."""
    markers = modification_markers(w)
    mod_marker = bold(yellow(f" [{', '.join(markers)}]")) if markers else ""
    sync_marker = ""
    status = calendar_status(w)
    if status == 'synced':
        sync_marker = bold(green(" [SYNCED]"))
    elif status == 'stale':
        sync_marker = bold(yellow(" [STALE]"))
    rem_marker = ""
    if w.get('removed'):
        rem_marker = bold(red(" [REMOVED]"))
    # Only a `workout generate` proposal carries this: the day is being left alone rather
    # than rewritten, which the rest of the line cannot show
    # (DESIGN_workout_revisions.md §7.1).
    keep_marker = bold(green(" [KEPT]")) if w.get('keep') else ""
    # Benchmark identity is a stored column, orthogonal to the modification/sync/removed
    # axes (a benchmark can also be adapted), so it gets its own marker straight off the
    # column (DESIGN_benchmark_workouts.md §3.1/§6).
    bench_marker = bold(blue(" [BENCHMARK]")) if w.get('benchmark_type') else ""
    duration = w.get('duration_minutes')
    tss = w.get('tss')
    rpe = w.get('rpe')
    duration_str = f" | {duration}min" if duration else ""
    tss_str = f" | TSS {tss}" if tss is not None else ""
    rpe_str = f" | RPE {rpe}" if rpe is not None else ""
    ident = f"ID: {w['id']} | " if w.get('id') is not None else ""
    # First of the markers: for a day already behind us, what became of the session is
    # the salient state, the way [SYNCED] is for a day ahead.
    adh_marker = adherence_marker(adherence)
    return (
        f"{ident}{cyan(fmt_date(w['date']))} | {magenta(w['sport_type'].upper())} | "
        f"{bold(w['title'])}{adh_marker}{bench_marker}{mod_marker}{sync_marker}"
        f"{rem_marker}{keep_marker}{duration_str}{tss_str}{rpe_str}"
    )


def prescription_lines(w: dict) -> List[str]:
    """The short form of what a session asks, drawn in gray under its `workout_line`: a
    strength session's exercises, none until the strength planner wrote them
    (DESIGN_strength_tracking.md §9); any other session's time in each intensity zone
    (DESIGN_intensity_distribution.md §9.8)."""
    if is_strength_sport(w['sport_type']):
        return exercise_lines(w.get('prescribed_sets') or [])
    target = intensity.format_planned_zones(w)
    if not target:
        return []
    return [target]


def warn_stale_before(start_date: str) -> None:
    """Flags workouts left `stale` on days earlier than the window just pushed.

    `workout push` defaults to today onward, so a row that went stale in the past —
    realistically a push that failed while offline — has nothing that would ever
    re-push it. Freshness is derived, not stored (see trainmate.calendar_state), so
    the marker is durable; this just makes it visible outside the pushed range."""
    try:
        cutoff = (
            datetime.strptime(start_date, "%Y-%m-%d") - timedelta(days=1)
        ).strftime("%Y-%m-%d")
    except ValueError:
        return
    earlier = runtime.db.get_workouts(end_date=cutoff, include_removed=True)
    stale = [w for w in earlier if calendar_status(w) == 'stale']
    if not stale:
        return
    label = "workout" if len(stale) == 1 else "workouts"
    earliest = min(w['date'] for w in stale)
    notice(
        f"Note: {len(stale)} {label} before {fmt_date(start_date)} still read [STALE] "
        f"— their calendar events are out of date and this push did not cover them. "
        f"Run {cmd(f'workout push -d {earliest}..')} to update them.",
    )


# Every bracket marker a `workout_line` can carry, in the order the line prints them, and
# the one phrase that says what it means. `[STALE]` in particular names no subject on its
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
    """The markers one rendered `workout_line` carries, for the legend to gloss.

    Read back off the line rather than re-derived from the row, so the legend can never
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
