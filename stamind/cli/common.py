"""Shared helpers used across the CLI command modules.

The companion-voice line builders used to live here too; they moved to `cli/render/`
with the rest of that voice (DESIGN_render_persona.md §7).
"""
import textwrap
from datetime import datetime, timedelta
from typing import Any, Dict, List, Optional
from stamind import runtime
from stamind.config import config
from stamind.text import cmd, cyan, gray, green, magenta, visible_len, wrap_text, yellow
from stamind.output import notice
from stamind.clock import fmt_date, today_str as _today_str


def print_strength_notes(proposal) -> None:
    """What the strength planner could not do, under every preview that shows its work
    (DESIGN_strength_tracking.md §9).

    Two things: the exercises its output checks dropped, each naming the day and the name
    Stamind does not know, and the one sentence for a morning it could not recheck the
    kilograms at all. Shared by `workout generate`'s preview, `workout adapt`'s and the
    companion's, which is why it lives here rather than in whichever one printed it first.
    """
    for line in getattr(proposal, 'strength_dropped', ()):
        notice(line)
    if getattr(proposal, 'strength_notice', None):
        print(wrap_text(proposal.strength_notice))


def ensure_recent_data(
    end_date: Optional[str] = None, no_pull: bool = False, force_pull: bool = False
) -> None:
    """Ensures Garmin data covering the recent metrics window is present and fresh,
    auto-pulling small/recent gaps and surfacing large backfills as a command. Warns
    if today's metrics are still unavailable afterward. `force_pull` bypasses the
    refresh-minutes throttle."""
    if no_pull:
        return
    end_date = end_date or _today_str()
    history_days = config.metrics_lookback_days
    start_date = (
        datetime.strptime(end_date, "%Y-%m-%d").date() - timedelta(days=history_days - 1)
    ).strftime("%Y-%m-%d")
    runtime.garmin.ensure_data(start_date, end_date, force=force_pull)

    today = _today_str()
    if end_date == today:
        rows = runtime.db.get_metrics_cache(start_date=today, end_date=today)
        present = bool(rows) and not (
            rows[0].get('rhr') is None and rows[0].get('hrv') is None
            and rows[0].get('sleep_score') is None and rows[0].get('stress') is None
        )
        if not present:
            notice(
                f"Note: Garmin metrics for today ({fmt_date(today)}) are not available yet.",
            )


def constraint_line(c: Dict[str, Any], needs_a_pass: bool = False) -> str:
    """One-line rendering of a constraint, for `constraint list`/`show`/`add` and `status`.

    Here rather than in `cli/constraints.py` because `status` also draws it, and its own
    hand-rolled copy had already drifted (DESIGN_constraint_honoring.md §4).

    `needs_a_pass` is `coach/honoring.py`'s answer, passed in rather than re-derived: this
    stays a renderer, and the one place that decides which tier owns a directive stays the
    one place. Deciding it here is how the tag came to contradict the sweep (§8).
    """
    tags = ("no training" if c.get('rest') else "advisory") + (
        " · plan-shaping" if c.get('replan') else ""
    )
    if c.get('honored_at'):
        tags += " · honored"
    elif needs_a_pass:
        tags += " · not yet in the schedule"
    return (
        f"ID: {c['id']} | {yellow(c['title'])}: "
        f"{cyan(fmt_date(c['start_date']))} to {cyan(fmt_date(c['end_date']))} | {tags}"
    )


def report_unhonored(constraints: List[Dict[str, Any]]) -> None:
    """Names the constraints a rollback just un-honored (§8).

    The restored plan predates those honorings, so it cannot reflect them. Said after the
    fact, not before the `y`: the cost of the flag being cleared is one nudge and a cheap
    re-pass, which is not worth complicating a confirm over.
    """
    if not constraints:
        return
    names = ", ".join(f"[{c['id']}] {c['title']}" for c in constraints)
    notice(
        f"{len(constraints)} constraint(s) the restored plan predates are no longer "
        f"marked honored: {names}. Run " + cmd("workout generate") + " to build them "
        "back in.",
    )


def print_plan_cascade(objective_id: int) -> None:
    """The blast radius `goal rm --purge` and `plan rm` both print before asking — one
    renderer, so two copies cannot drift into disagreeing about one cascade
    (DESIGN_cli_noargs.md §b1)."""
    versions = runtime.db.get_macrocycle_versions(objective_id)
    mesocycles = sum(
        len(runtime.db.get_mesocycles_for_macrocycle(m['id'])) for m in versions
    )
    notes = sum(len(runtime.db.list_plan_feedback(m['id'])) for m in versions)
    orphaned = runtime.db.count_future_workouts_for_macrocycles(
        [m['id'] for m in versions], _today_str()
    )
    print(f"  - {len(versions)} periodization plan version(s)")
    print(f"  - {mesocycles} mesocycle(s)")
    print(f"  - {notes} plan feedback note(s)")
    if orphaned:
        notice(
            f"  and leaves {orphaned} upcoming session(s) with no plan to explain "
            "them.",
        )


# --- The plan's hanging-indent block (DESIGN_plan_feedback.md §4, §8) ---
# `plan show` draws a mesocycle as a head line with its prose and metadata aligned under
# it; `plan diff` draws a changed field the same way. Here rather than in either, because
# whichever defined it first would own the other's layout.

def print_hanging(head: str, text: str, width: int, color_fn=None) -> str:
    """Prints ``text`` after ``head``, wrapped with continuation lines aligned under it.

    Returns the indent string so the caller can align the mesocycle's follow-up lines
    (dates, progress bar, prose) to the same column. A narrow client gets a plain
    2-space indent instead, since aligning under a long head leaves no usable width."""
    pad_len = visible_len(head)
    if width - pad_len < 24:
        pad_len = 2
    pad = " " * pad_len
    lines = textwrap.wrap(text or "", width=max(20, width - pad_len)) or [""]
    for i, line in enumerate(lines):
        print((head if i == 0 else pad) + (color_fn(line) if color_fn else line))
    return pad


def print_indented(text: str, pad: str, width: int, color_fn=None) -> None:
    """Prints wrapped prose at an existing mesocycle's indent."""
    for line in textwrap.wrap(text, width=max(20, width - len(pad))):
        print(pad + (color_fn(line) if color_fn else line))


def print_segments(pad: str, segments: list, width: int) -> None:
    """Prints already-coloured metadata segments joined by ' · ', breaking onto a new
    indented line rather than letting the terminal wrap them mid-word."""
    avail = max(20, width - len(pad))
    line = ""
    for seg in segments:
        if not seg:
            continue
        candidate = f"{line} · {seg}" if line else seg
        if line and visible_len(candidate) > avail:
            print(pad + line)
            line = seg
        else:
            line = candidate
    if line:
        print(pad + line)


def print_feedback_notes(notes: List[dict], width: int, indent: str = "") -> None:
    """The log's one rendering — '[id] date · plan-level|<mesocycle> · text', oldest first —
    shared by the listing, `plan show` and `plan diff` (DESIGN_plan_feedback.md §4)."""
    for n in notes:
        filing = n.get('mesocycle_name') or 'plan-level'
        date = str(n.get('created_at') or '')[:10]
        print_hanging(
            f"{indent}{gray('[' + str(n['id']) + ']')} {cyan(fmt_date(date))} "
            f"· {magenta(filing)} · ",
            n['text'], width,
        )


def add_feedback_note(macro: dict, text: str, meso: Optional[dict] = None) -> None:
    """Appends one note to the plan's log and echoes it (DESIGN_plan_feedback.md §4).

    Here rather than in `cli/plans/feedback.py` because `plan generate --feedback` files a
    note too, and `plan feedback --replan` runs `plan generate`: each command file holding
    the other's helper is the import cycle AGENTS.md says to move the shared code out of.
    """
    note_id = runtime.db.add_plan_feedback(macro['id'], text, meso['id'] if meso else None)
    filing = f"filed: {meso['name']}" if meso else "plan-level"
    print(green(f"Noted [id {note_id}, {filing}]: ") + f"\"{text}\"")
