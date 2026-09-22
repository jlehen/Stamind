"""A strength session's description, built from its prescribed sets
(DESIGN_strength_tracking.md §9).

The kilograms the athlete reads and the kilograms stored as data cannot disagree, because
both are rendered from the same rows. The blank line after the brief is the seam: above it
the week planner's words, below them the session, and the week planner is shown only what
is above, so it never meets a kilogram and never copies one into a revision.
"""
from typing import Any, Dict, List, Optional, Sequence

from stamind.strength import sets
from stamind.text import capitalized


def collapse_brief(description: Optional[str]) -> str:
    """The week planner's description as a brief, its blank lines taken out, so the first
    blank line of the stored description is the seam whatever paragraphing it wrote."""
    lines = [line.rstrip() for line in (description or "").strip().splitlines()]
    return "\n".join(line for line in lines if line.strip())


def title_line(description: Optional[str]) -> str:
    """The "[Title]" line a description opens with, or "" when it has none. A session
    written before phase 2 keeps only this line: the prose under it names sets and reps
    that the exercise lines below the seam replace (§9)."""
    first = (description or "").strip().splitlines()[:1]
    head = first[0].strip() if first else ""
    return head if head.startswith("[") and head.endswith("]") else ""


def brief_of(description: Optional[str]) -> str:
    """Everything above the seam: what the week planner wrote, and all it is shown back."""
    return (description or "").strip().split("\n\n", 1)[0].strip()


def body_of(description: Optional[str]) -> str:
    """Everything below the seam: the exercise lines and the session's notes."""
    parts = (description or "").strip().split("\n\n", 1)
    return parts[1].strip() if len(parts) == 2 else ""


def exercise_lines(rows: Sequence[Dict[str, Any]]) -> List[str]:
    """One line per exercise: "Belt squat 1×5 @ 120, 3×4–6 @ 140 kg". A warm-up ramp and
    the working sets are one exercise at several loads, so they share a line (§9, §10)."""
    lines: List[str] = []
    run: List[Dict[str, Any]] = []
    for row in list(rows) + [None]:
        if run and (row is None or row["exercise"] != run[0]["exercise"]):
            unit = " kg" if any(r.get("load_kg") is not None for r in run) else ""
            lines.append(f"{capitalized(run[0]['exercise'])} {spec(run)}{unit}")
            run = []
        if row is not None:
            run.append(row)
    return lines


def render_description(brief: str, rows: Sequence[Dict[str, Any]], notes: str) -> str:
    """The whole description: the brief, the seam, the exercise lines, then the notes."""
    body = exercise_lines(rows)
    if notes.strip():
        body.append(notes.strip())
    return f"{brief.strip()}\n\n" + "\n".join(body)


def rebrief(description: Optional[str], brief: str) -> str:
    """The same session under a new brief. The rows did not change, so everything below the
    seam still stands and only the words above it are replaced — which is what a session the
    week planner revised while its kilograms held gets (§9)."""
    body = body_of(description)
    return f"{brief.strip()}\n\n{body}" if body else brief.strip()


def spec(rows: Sequence[Dict[str, Any]]) -> str:
    """'1×5 @ 120, 3×4–6 @ 140': one exercise's entries, in the order they are done. An
    exercise written at several loads prints every entry, warm-up and working sets alike."""
    parts = []
    for row in rows:
        low, high = row["reps_low"], row["reps_high"]
        reps = f"{low}–{high}" if low != high else str(low)
        load = f" @ {sets.fmt_kg(row['load_kg'])}" if row.get("load_kg") is not None else ""
        parts.append(f"{row['sets']}×{reps}{load}")
    return ", ".join(parts)


