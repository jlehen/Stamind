"""Previewing an in-place revision before it is applied.

The expert table lives here; the companion prose form of the same proposal is
`render.simple_revision_lines`, which reuses the wording-diff helpers below
(DESIGN_render_persona.md §7).
"""
import difflib
from typing import Dict, List, Set, Tuple

from stamind import settings
from stamind.text import (
    bold, cyan, format_labeled_text, gray, green, magenta, red, render_table, yellow,
)
from stamind.cli.common import print_strength_notes
from stamind.coach.proposals import RevisionProposal
from stamind.coach.revisions import RevisionPair

# A group of the wording diff: one line and the line that took its place, or a run of lines
# that were dropped or added with nothing standing for them. No group holds a blank line.
WordingGroup = Tuple[List[str], List[str]]

# How alike two lines must be for one to count as the other rewritten: a third of their
# words, in the same order (DESIGN_workout_revisions.md §9.1).
SAME_LINE = 1 / 3


def _stats(w: dict) -> str:
    """One session's load, as the revision preview shows it."""
    return (
        f"{w.get('duration_minutes') or 0}m/"
        f"RPE{w.get('rpe') or 0}/"
        f"TSS{w.get('tss') or 0}"
    )


def rewritten_text_only(proposal: dict, original: dict) -> bool:
    """True when the prescription the table can SHOW is identical and only the text moved.

    Its columns are title and load, so a session the week planner revised in words alone renders
    as `X | X | 85m/RPE7/TSS84 -> 85m/RPE7/TSS84` and reads as a change made for no
    reason. Those are the rows the diff below exists for
    (DESIGN_workout_revisions.md §9.1)."""
    if not original:
        return False
    if proposal.get('title') != original.get('title') or _stats(proposal) != _stats(original):
        return False
    norm = lambda v: " ".join(str(v or "").split())  # noqa: E731
    return norm(proposal.get('description')) != norm(original.get('description'))


def quotes_wording(proposal: dict, original: dict) -> bool:
    """True when the preview quotes a session's old and new wording: only its text moved,
    and the athlete has not asked for short answers (DESIGN_output_verbosity.md §9)."""
    return rewritten_text_only(proposal, original) and not settings.terse()


def _lines(text) -> Tuple[List[str], Set[int]]:
    """A description's lines, and which of them stand under a blank line. A blank line is
    layout, so the diff does not compare it."""
    out: List[str] = []
    spaced: Set[int] = set()
    for line in str(text or "").splitlines():
        if not line.strip():
            spaced.add(len(out))
            continue
        out.append(" ".join(line.split()))
    return out, spaced


def _alike(old: str, new: str) -> float:
    """How much of two lines is the same words in the same order, from 0 to 1."""
    return difflib.SequenceMatcher(None, old.lower().split(), new.lower().split()).ratio()


def _rewrites(old: List[str], new: List[str]) -> Dict[int, int]:
    """Which old line each new line is a rewrite of, by position in the two lists. The pairs
    most alike are taken first, and a line is paired once. When one line is then left on
    each side, the one took the place of the other, however little they share."""
    scored = sorted(
        (-_alike(o, n), j, i) for i, o in enumerate(old) for j, n in enumerate(new)
    )
    pairs: Dict[int, int] = {}
    taken: Set[int] = set()
    for score, j, i in scored:
        if -score < SAME_LINE:
            break
        if j in pairs or i in taken:
            continue
        pairs[j] = i
        taken.add(i)
    left_old = [i for i in range(len(old)) if i not in taken]
    left_new = [j for j in range(len(new)) if j not in pairs]
    if len(left_old) == 1 and len(left_new) == 1:
        pairs[left_new[0]] = left_old[0]
    return pairs


def _runs(lines: List[str], spaced: Set[int], start: int, alone: List[int]) -> List[List[str]]:
    """The lines at the positions `alone`, as runs of lines that followed one another with
    no blank line between them. `start` is where position 0 stands in the description."""
    runs: List[List[str]] = []
    last = None
    for index in alone:
        if last is None or index != last + 1 or start + index in spaced:
            runs.append([])
        runs[-1].append(lines[start + index])
        last = index
    return runs


def _line_by_line(
    a: List[str], a_spaced: Set[int], i1: int, i2: int,
    b: List[str], b_spaced: Set[int], j1: int, j2: int,
) -> List[WordingGroup]:
    """One changed stretch as groups, in the order of the new text: a rewritten line beside
    the line it replaced, the added lines where they stand, and last the lines dropped."""
    pairs = _rewrites(a[i1:i2], b[j1:j2])
    groups: List[WordingGroup] = []
    added: List[int] = []
    for j in range(j2 - j1):
        if j not in pairs:
            added.append(j)
            continue
        groups += [([], run) for run in _runs(b, b_spaced, j1, added)]
        added = []
        groups.append(([a[i1 + pairs[j]]], [b[j1 + j]]))
    groups += [([], run) for run in _runs(b, b_spaced, j1, added)]
    dropped = [i for i in range(i2 - i1) if i not in pairs.values()]
    return groups + [(run, []) for run in _runs(a, a_spaced, i1, dropped)]


def wording_groups(proposal: dict, original: dict) -> List[WordingGroup]:
    """What moved between two descriptions, as groups of whole lines.

    Whole lines, and never a sentence cut out of one. A line that was rewritten stands
    beside the line it replaced, so each `Was:` is followed by its own `Now:`
    (DESIGN_workout_revisions.md §9.1)."""
    a, a_spaced = _lines(original.get('description'))
    b, b_spaced = _lines(proposal.get('description'))
    groups: List[WordingGroup] = []
    for tag, i1, i2, j1, j2 in difflib.SequenceMatcher(None, a, b).get_opcodes():
        if tag != 'equal':
            groups += _line_by_line(a, a_spaced, i1, i2, b, b_spaced, j1, j2)
    return groups


def wording_group_lines(
    group: WordingGroup, indent: str = "", gone: str = "", new: str = "",
) -> List[str]:
    """One group as a labelled 'Was:' / 'Now:' pair (or 'Dropped:' / 'Added:' when one
    side is empty), wrapped at the client's width with the text hanging under its label.
    `gone` and `new` are marks put before the two labels, for a client that shows no
    colour."""
    dropped, added = group
    lines: List[str] = []
    if dropped:
        label = "Was: " if added else "Dropped: "
        lines.append(
            format_labeled_text(indent + gone + label, "\n".join(dropped), color_fn=red)
        )
    if added:
        label = "Now: " if dropped else "Added: "
        lines.append(
            format_labeled_text(indent + new + label, "\n".join(added), color_fn=green)
        )
    return lines


def _original_label(pair: RevisionPair) -> str:
    """The Original column: the session this proposal stands in for, and the day it stood
    on when that is not the day it lands on.

    The Date column shows only where a moved session ends up, so without the source date
    the row reads as a session appearing from nowhere (DESIGN_workout_revisions.md §11).
    """
    existing = pair.original
    if not existing:
        return "[None]"
    if existing['date'] == pair.proposal['date']:
        return existing['title']
    return f"{existing['title']} (from {existing['date']})"


def _print_wording_changes(proposal: RevisionProposal) -> None:
    """Shows what a revision changed when the table's columns cannot.

    The athlete reads the description, so revising it is a real adaptation — the week planner
    makes them deliberately, e.g. rewriting a pacing cue to reference the session just
    executed. Printed rather than merely flagged: a preview that says a session changed
    but not how is what makes an honest text revision look like a bug (§9.1)."""
    reworded = [
        (pair.proposal, pair.original) for pair in proposal.pairs
        if quotes_wording(pair.proposal, pair.original)
    ]
    if not reworded:
        return
    print(bold(yellow("\nTEXT REVISED (same load, so the columns above cannot show it):")))
    for pw, existing in reworded:
        print(f"\n  {cyan(pw['date'])} {magenta(pw['sport_type'].upper())} — {pw['title']}")
        for group in wording_groups(pw, existing):
            for line in wording_group_lines(group, indent="    "):
                print(line)


def print_revision_preview(proposal: RevisionProposal, heading: str) -> None:
    """Renders a revision as the expert table, plus the wording diff its columns cannot
    show.

    Everything drawn comes off the proposal — the range it evaluated and the sessions it
    saw — so the preview cannot disagree with what apply will do. Drawing only: the
    caller asks the question, through `runtime.prompt` (DESIGN_render_persona.md §4).
    """
    print(bold(yellow(f"\n{heading}")))
    headers = ["Date", "Sport", "Original Workout", "Proposed Workout", "Duration/RPE/TSS"]
    rows = []

    for pair in proposal.pairs:
        pw, existing = pair.proposal, pair.original
        orig_title = _original_label(pair)
        stats_diff = (
            f"{_stats(existing)} -> {_stats(pw)}" if existing else _stats(pw)
        )
        sport_label = (
            f"{existing['sport_type'].upper()}->{pw['sport_type'].upper()}"
            if pair.is_swap else pw['sport_type'].upper()
        )
        proposed_label = green(pw['title'])
        if rewritten_text_only(pw, existing):
            proposed_label += gray(" [text revised]")
        rows.append([
            cyan(pw['date']), magenta(sport_label), gray(orig_title),
            proposed_label, yellow(stats_diff),
        ])

    # Sessions being deleted outright (overridden with no replacement proposal).
    for ew in sorted(proposal.removals, key=lambda w: w['date']):
        rows.append([
            cyan(ew['date']), magenta(ew['sport_type'].upper()),
            gray(ew['title']), red("[Removed]"),
            yellow(f"{_stats(ew)} -> removed"),
        ])

    rows.sort(key=lambda r: r[0])
    print(render_table(headers, rows))
    _print_wording_changes(proposal)
    # The strength planner's own report: what its checks dropped, and the morning it could
    # not recheck the kilograms at all (DESIGN_strength_tracking.md §9).
    print_strength_notes(proposal)
