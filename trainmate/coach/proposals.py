"""What the coach proposes, before the athlete has accepted it.

These records exist to stop the same rule being written twice on both sides of a
boundary. When the CLI preview re-derived a proposal's displaced session and date range,
preview and apply could disagree about what disappears; when ``plan_generate``
fingerprinted at prompt time and ``plan_apply`` re-read at accept time, an edit in
between silently defeated the staleness detector.

So a proposal carries the facts it was computed from, and the consumer renders rather
than recomputes. Records only: the logic that fills them in lives in `revisions.py`.
"""
from dataclasses import dataclass
from typing import Any, Dict, List, Optional, Tuple, TypedDict

from trainmate.types import Objective


@dataclass(frozen=True)
class RevisionPair:
    """One proposed session and the planned session it stands in for.

    `original` is the session being replaced — the same-sport session for an in-place
    change, or the displaced one for a sport swap. None when nothing was planned that day.
    """
    proposal: Dict[str, Any]
    original: Optional[Dict[str, Any]]
    is_swap: bool


@dataclass(frozen=True)
class RevisionProposal:
    """An in-place rewrite of the sessions in a window, before it has been accepted.

    `workout adapt`'s shape: rows revised where they stand rather than rebuilt from a
    date onward, which is what separates it from `GenerateProposal` below. Applied by
    `workout_revision_apply`.

    `range_start`/`range_end` are the window the week planner actually evaluated, not the span of
    the proposals it happened to return. Apply deletes overridden sessions across this
    range, so the two must be the same window or apply removes sessions the preview never
    showed — which is also why every caller renders these rather than its own request.
    """
    reason: str
    workouts: List[Dict[str, Any]]
    range_start: str
    range_end: str
    # The change kind apply records: "adapt", or "tweak" for one day changed on request
    # (DESIGN_workout_tweak.md §3.3).
    kind: str = "adapt"
    pairs: Tuple[RevisionPair, ...] = ()
    removals: Tuple[Dict[str, Any], ...] = ()
    # Candidate directives extracted from the athlete's note, raw and unconfirmed
    # (DESIGN_constraints.md §8).
    new_constraints: Tuple[Dict[str, Any], ...] = ()
    # Candidate daily signals extracted from the same note, raw and unconfirmed
    # (DESIGN_signal_extraction.md §2).
    new_signals: Tuple[Dict[str, Any], ...] = ()
    # Constraints this pass had authority over every remaining day of, so apply stamps
    # exactly the set decided at proposal time (DESIGN_constraint_honoring.md §3). See
    # `coach/honoring.py`.
    covered_constraint_ids: Tuple[int, ...] = ()
    # `(date, canonical sport)` the week planner named only to hold — no revision, but the
    # displacement rule must still count them as spoken for
    # (DESIGN_workout_revisions.md §9.1).
    held: Tuple[Tuple[str, str], ...] = ()
    # What the strength planner weighed, and the stamp the history it read was built from.
    # The rows are written when this proposal is applied or recorded as no change, never
    # when it is proposed (DESIGN_strength_tracking.md §9).
    strength_checks: Tuple[Tuple[str, str], ...] = ()
    strength_stamp: str = ""
    # The one sentence the athlete is told when the kilograms were not rechecked, and the
    # entries the output checks dropped — both shown in the preview (§9).
    strength_notice: Optional[str] = None
    strength_dropped: Tuple[str, ...] = ()


@dataclass(frozen=True)
class StandingLine:
    """One row of the report `workout generate` prints for a session the athlete has
    already been told about (DESIGN_plan_change_continuity.md §4.5).

    `outcome` is what apply will actually do to the session, not what the week planner answered:
    a wording-only revision is suppressed by the no-op rule and a rest constraint removes
    days no answer mentions, so reporting the answers would tell the operator the wrong
    thing in both directions.

    `outcome` is one of `kept`, `revised`, `moved` or `cancelled`. `becomes` is the new
    form for a revision and the ISO date for a move, and is empty otherwise.
    """
    date: str
    sport_type: str
    title: str
    duration_minutes: Optional[int]
    outcome: str
    becomes: str = ""
    reason: str = ""
    # False when no answer named this session at all, so the preview can say that the
    # week planner's silence is what kept it.
    mentioned: bool = True


@dataclass(frozen=True)
class GenerateProposal:
    """A `workout generate` result, before anything has been written.

    Generation is archive-and-rebuild, so the athlete sees the sessions first and the
    write happens only on a `y` (ARCHITECTURE.md §"Workout Generation"). `workouts` are
    already tagged with the `macrocycle_id` governing their date, and `displaced` is the
    live plan this would archive — both decided here, so the preview and the apply cannot
    disagree about what appears and what disappears.

    `gen_start`/`gen_end` bound the rebuild at BOTH ends: the selectors pick a span, and
    days outside it keep the sessions they already have (DESIGN_cli_selectors.md §8).
    """
    reasoning: str
    workouts: Tuple[Dict[str, Any], ...] = ()
    displaced: Tuple[Dict[str, Any], ...] = ()
    gen_start: str = ""
    gen_end: str = ""
    # As on `RevisionProposal` (DESIGN_constraint_honoring.md §3). Decided where
    # `gen_start`/`gen_end` are both in scope, so the proposal carries the resulting ids
    # rather than a range to re-check.
    covered_constraint_ids: Tuple[int, ...] = ()
    # `(date, sport_type, reason)` per slot this run ends. Decided here so the preview
    # reports the removals apply will actually make, including the ones no answer
    # explains (DESIGN_plan_change_continuity.md §5.5).
    voids: Tuple[Tuple[str, str, str], ...] = ()
    # The §4.5 report: one line per session the athlete was already told about.
    standing: Tuple[StandingLine, ...] = ()
    # The coach's one line to the athlete about the change as a whole, for the morning
    # push (§6.3). None when nothing they would notice changed.
    athlete_note: Optional[str] = None
    # The last day of the commitment window this run answered under, stamped on the
    # change so a void is judged by the window it was written under (§5.2).
    commitment_end: Optional[str] = None
    # As on `RevisionProposal` above (DESIGN_strength_tracking.md §9).
    strength_checks: Tuple[Tuple[str, str], ...] = ()
    strength_stamp: str = ""
    strength_notice: Optional[str] = None
    strength_dropped: Tuple[str, ...] = ()


@dataclass(frozen=True)
class PlanFingerprints:
    """The inputs a strategy was generated against, hashed once at prompt time.

    Persisted verbatim by `plan_apply`. Re-deriving them at accept time is what let an
    edit between generate and accept be recorded as if the strategy had seen it.
    """
    goals_hash: str
    constraints_hash: str
    config_hash: Optional[str] = None
    config_snapshot: Optional[str] = None
    profile_snapshot: Optional[str] = None
    goals_snapshot: Optional[str] = None
    constraints_snapshot: Optional[str] = None
    all_constraints_snapshot: Optional[str] = None
    science_snapshot: Optional[str] = None


class PlanProposal(TypedDict):
    """What `plan generate` produced, before the athlete has accepted it.

    `goal` is the objective the plan belongs to — the requested one, or the next active
    goal when none was named. It is `None` only when there are no active goals at all.
    """
    strategy: str
    mesocycles: List[Dict[str, Any]]
    reused: bool
    goal: Optional[Objective]
    # The planned-vs-actual review the strategy was written against, laid out at the
    # caller's width — only when the caller asked to see it (`--show-llm-context`).
    prior_training_review: Optional[str]
    # Whether one fed the prompt at all, so a caller that is not showing it can still
    # name the flag that would.
    has_prior_training: bool
