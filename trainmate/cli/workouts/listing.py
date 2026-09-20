"""`workout list` and `workout show`: the sessions on file, and how each one went.

Not named `list.py`, which would shadow the builtin. `show` is `list -vv` over the same
rows, so both handlers are here and the expert body they share is `print_workout_table`
(DESIGN_render_persona.md §5).
"""
import argparse
from typing import Optional
from trainmate import runtime
from trainmate.analytics import intensity
from trainmate.analytics.compare import adherence_verdicts, format_actual
from trainmate.config import config
from trainmate.gcal.event import event_url
from trainmate.text import bold, cyan, format_labeled_paragraph, gray, yellow
from trainmate.output import notice, warn
from trainmate.clock import fmt_date, fmt_timestamp, today_str as _today_str
from trainmate.cli.runway import list_end_marker
from trainmate.cli.selectors import has_selector as _has_selector, resolve_window, split_targets
from trainmate.cli.workouts.session_line import prescription_lines, workout_line


def _workouts_by_id(ids: list, sport_type: Optional[str]) -> list:
    """Looks up the workout IDs named as positional targets, reporting the ones it can't."""
    found = []
    for workout_id in ids:
        w = runtime.db.get_workout_by_id(workout_id)
        if not w:
            notice(f"No workout with ID {workout_id}.")
            continue
        if w.get('removed'):
            notice(f"Workout {workout_id} was cancelled.")
            continue
        if sport_type and w['sport_type'].lower() != sport_type.lower():
            continue
        found.append(w)
    return found


def _list_verdicts(workouts: list, args: argparse.Namespace) -> dict:
    """What became of each listed session that is today or earlier, keyed by workout ID.

    Freshens the Garmin cache over that same span first (`--no-pull` skips it), since the
    listing now reports on completed activities. A listing with nothing behind us costs
    neither the pull nor the query (ARCHITECTURE.md §5)."""
    today = _today_str()
    past = sorted(w['date'] for w in workouts if w['date'] <= today)
    if not past:
        return {}
    if not getattr(args, 'no_pull', False):
        try:
            runtime.garmin.ensure_data(
                past[0], past[-1], force=getattr(args, 'force_pull', False)
            )
        except Exception as e:
            warn(f"could not ensure recent data: {e}")
    return adherence_verdicts(runtime.db, past[0], past[-1], _today_str())


def run_workout_list(args: argparse.Namespace) -> None:
    """Lists stored workouts chronologically, by ID, date range, mesocycle, plan or sport."""
    ids, date_targets = split_targets(getattr(args, "targets", None))
    # Named dates narrow like any other selector; named IDs are looked up directly, since
    # an ID the athlete typed is not a window (DESIGN_cli_selectors.md §4).
    args._extra_windows = [(r.start, r.end) for r in date_targets]
    windowed = bool(date_targets) or _has_selector(args)

    workouts = []
    if windowed or not ids:
        start_date, end_date = resolve_window(args)
        workouts = runtime.db.get_workouts(
            start_date=start_date,
            end_date=end_date,
            sport_type=args.sport_type,
        )
    else:
        start_date = end_date = None
    if ids:
        workouts += _workouts_by_id(ids, args.sport_type)
        seen = set()
        workouts = [
            w for w in sorted(workouts, key=lambda w: (w['date'], w['id']))
            if not (w['id'] in seen or seen.add(w['id']))
        ]

    verdicts = _list_verdicts(workouts, args)

    # A pure ID lookup names no range, so there is no crossing of the end of the schedule
    # to report on (DESIGN_runway_nudge.md §4).
    names_a_range = windowed or not ids

    runtime.render.workout_list(
        workouts, verdicts, args, start_date=start_date, end_date=end_date, ids=ids,
        names_a_range=names_a_range,
    )


def run_workout_show(args: argparse.Namespace) -> None:
    """`workout show ID` is `workout list -vv ID`: the same listing with the per-workout
    detail lines always on."""
    args.verbose = 2
    run_workout_list(args)


def print_workout_table(
    workouts: list, verdicts: dict, args: argparse.Namespace, *,
    start_date: Optional[str], end_date: Optional[str], ids: list, names_a_range: bool,
) -> None:
    """The expert `workout list` body: the filter echo, one line per session (`-v` adds
    its short form in gray, `-vv` the detail lines), and the end-of-schedule marker.

    The companion form of this is CompanionRenderer.workout_list
    (DESIGN_render_persona.md §5)."""
    print(bold(cyan("=== WORKOUT SCHEDULE ===")))
    if ids:
        print(gray(f"Filters: IDs {', '.join(str(i) for i in ids)}"))
    if start_date or end_date or args.sport_type:
        filter_parts = []
        if start_date:
            filter_parts.append(f"From: {fmt_date(start_date)}")
        if end_date:
            filter_parts.append(f"Until: {fmt_date(end_date)}")
        if args.sport_type:
            filter_parts.append(f"Type: {args.sport_type}")
        print(gray(f"Filters: {', '.join(filter_parts)}"))

    # The long batch rationale is stamped on every workout of an adapt run; show each
    # distinct summary only once across the listing so it doesn't dominate the output.
    seen_summaries: set = set()
    for w in workouts:
        verdict = verdicts.get(w.get('id'))
        print(workout_line(w, verdict))
        # -l surfaces the Calendar event link (rebuilt from the stored event id) so it can
        # be opened without the sync commands having to print the URL every push.
        if getattr(args, "link", False):
            url = event_url(w.get('google_event_id'), config.google_calendar_id)
            print(gray(f"  Calendar: {url}") if url else gray("  Calendar: (not synced)"))
        # Default listing is one line per workout; -v adds the short form under it, the
        # same lines the `workout generate` preview draws; -vv the full detail.
        verbosity = getattr(args, "verbose", 0) or 0
        if verbosity == 1:
            for line in prescription_lines(w):
                print(f"      {gray(line)}")
        if verbosity < 2:
            continue
        # Lifecycle timestamps: when the session first entered the plan and, if ever
        # eased, when the most recent `workout adapt` run touched it. Both NULL on
        # rows predating these columns, so the line is omitted when neither is known.
        lifecycle_parts = []
        if w.get('created_at'):
            lifecycle_parts.append(f"Planned: {fmt_timestamp(w['created_at'])}")
        if w.get('adapted_at'):
            lifecycle_parts.append(f"Last adapted: {fmt_timestamp(w['adapted_at'])}")
        if lifecycle_parts:
            print(gray("  " + "  ·  ".join(lifecycle_parts)))
        # The effort the verdict graded against, and what a [PARTIAL] differed by — the
        # marker alone only says that it did.
        actual = (verdict or {}).get('completed')
        if actual:
            print(gray(f"  Actual: {format_actual(actual)}"))
        for reason in (verdict or {}).get('reasons') or []:
            notice(f"  Discrepancy: {reason}")
        print(format_labeled_paragraph("  Description:", w['description']))
        # The zone target, which the description never carries (§9.8 of
        # DESIGN_intensity_distribution.md).
        target = intensity.format_planned_zones(w)
        if target:
            print(gray(f"  {target}"))
        summary = w.get('adaptation_summary')
        # Show the per-workout note inline, unless it's just the batch reason echoed
        # (the fallback when the model gave no per-workout change_reason) — that would
        # duplicate the Adapt summary printed below.
        if w.get('modification_reason') and w['modification_reason'] != summary:
            print(format_labeled_paragraph("  Reason:", w['modification_reason'], color_fn=yellow))
        if summary and summary not in seen_summaries:
            seen_summaries.add(summary)
            print(format_labeled_paragraph("  Adapt summary:", summary, color_fn=gray))
        print(gray("-" * 40))
    # Where the schedule stops, when the listed range runs past it (§4). A listing with
    # nothing to show renders it alone: an empty range past the cliff is exactly where the
    # gap needs naming rather than reading as a broken render.
    end_marker = list_end_marker(end_date) if names_a_range else None
    if end_marker:
        print(end_marker)

