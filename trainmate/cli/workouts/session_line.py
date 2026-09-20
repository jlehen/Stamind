"""One session, rendered as one line — and the short form drawn under it.

`workout list`, `workout show` and the `workout generate` preview all draw a session this
way, so the plan the athlete is asked to accept reads exactly like the plan they will live
with.
"""
from typing import List, Optional
from trainmate.analytics import intensity
from trainmate.workout_state import calendar_status, modification_markers
from trainmate.sports import is_strength_sport
from trainmate.strength.prescription import exercise_lines
from trainmate.text import blue, bold, cyan, gray, green, magenta, red, yellow
from trainmate.clock import fmt_date


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

    `adherence` is `analytics.compare.adherence_verdicts`' entry for this session when the day is
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
