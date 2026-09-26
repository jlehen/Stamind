"""How an in-place revision is computed — the pure helpers behind a `RevisionProposal`.

Kept apart from `proposals.py`, which holds only the frozen records the coach hands the
CLI: this is the logic that fills them in.
"""
from typing import Any, Dict, List, Optional, Sequence, Tuple

from stamind.coach.proposals import RevisionPair
from stamind.sports import canonical_sport


def replaces_source(entry: Dict[str, Any]) -> Optional[Tuple[str, str]]:
    """The `(date, canonical sport)` an entry's `replaces` names, or None.

    `replaces` is how the week planner says a session it wrote in one slot is the session
    that was standing in another — moved to a different day, or given a different sport
    (DESIGN_plan_change_continuity.md §4.5). Both `workout generate` and `workout adapt`
    read it, so the reading lives here rather than in whichever resolver got it first.

    None when the field is absent, or when it names the entry's own slot: that is an
    ordinary in-place revision writing itself down twice.
    """
    replaces = entry.get('replaces')
    if not isinstance(replaces, dict) or not replaces.get('date'):
        return None
    named = (replaces['date'], canonical_sport(replaces.get('sport_type', '')))
    slot = (entry.get('date'), canonical_sport(entry.get('sport_type', '')))
    return None if named == slot else named


def rest_in_place_of(
    source: Dict[str, Any], reason: str, fallback: str
) -> Dict[str, Any]:
    """The rest day that takes over a date whose session is gone.

    One builder for the two answers that empty a date: `workout generate` dropping a
    session (DESIGN_plan_change_continuity.md §5.4) and `workout adapt` carrying one to
    another day (DESIGN_workout_revisions.md §11). `reason` is the coach's own sentence
    about the change, which the athlete reads on the day; `fallback` is what the day says
    when the coach wrote no sentence.
    """
    body = reason.strip() or fallback
    return {
        'date': source['date'],
        'sport_type': 'rest',
        'title': 'Rest Day',
        'description': f"[Rest Day]\n{body}",
        'duration_minutes': 0,
        'rpe': 0,
        'tss': 0,
        'change_reason': reason.strip(),
    }


def structure_revision(
    revised: List[Dict[str, Any]], reason: str
) -> List[Dict[str, Any]]:
    """The row shape `workout_revision_apply` consumes, built from the model's response.

    One builder for every revision the week planner proposes: the rules
    about how a returned change becomes a row — the `modification_reason` fallback below
    above all — are written once rather than copied into each propose method.
    """
    return [
        {
            'date': w['date'],
            'sport_type': w['sport_type'],
            'title': w['title'],
            'short_name': w.get('short_name'),
            'description': w['description'],
            # This revision's own note; the long batch rationale travels separately as
            # `reason` and lands on the change row (DESIGN_workout_revisions.md §3). Falls
            # back to the batch reason so a revised session is never left without one.
            'modification_reason': w.get('change_reason') or reason,
            'duration_minutes': w.get('duration_minutes'),
            'rpe': w.get('rpe'),
            'tss': w.get('tss'),
            # Carry the benchmark flag through the rebuild: a moved test must stay a test.
            # The model owns its survival by re-emitting it, and a returned change that
            # drops it clears the stored flag at apply time
            # (DESIGN_benchmark_workouts.md §3.1/§4.2).
            'benchmark_type': w.get('benchmark_type'),
            # The slot this session was standing in before the change, and the lineage it
            # carries out of it — already resolved against the sessions in the window, so
            # the preview and apply read the same decision (DESIGN_workout_revisions.md
            # §11). None on a session that is not going anywhere.
            'replaces_slot': w.get('replaces_slot'),
            'replaces_lineage': w.get('replaces_lineage'),
            # The intensity target, in the shape the week planner wrote it: apply reads it
            # back through `intensity.parse_planned_zones`, and omitting it here is how an
            # eased target used to be asked for, returned, and then dropped on the way to
            # the row (DESIGN_intensity_distribution.md §9.8).
            'planned_zone_currency': w.get('planned_zone_currency'),
            'planned_zone_sec': w.get('planned_zone_sec'),
        } for w in revised
    ]


def prescription_matches(proposed: Dict[str, Any], live: Dict[str, Any]) -> bool:
    """Whether appending `proposed` over `live` would be suppressed as a no-op.

    The §9 no-op rule lives in the write path (`db.workout_change.WorkoutChange._write`), so a
    preview built from the week planner's answers would report a wording-only revision as a
    change to the day. The proposal step asks this instead, against the standing rows it
    already loaded (DESIGN_plan_change_continuity.md §4.5). It mirrors `append`'s merge:
    a field the proposal omits carries forward and is therefore not a change.

    Prose is compared on its words, not its spacing: a model that re-lists a session it is
    holding wraps the same sentence differently often enough, and a proposal that only
    re-wraps a line is not a change the athlete can see.
    """
    from stamind.analytics import intensity

    def _words(value: Any) -> str:
        return " ".join(str(value or "").split())

    if live.get('removed'):
        return False
    for field in ('date', 'sport_type'):
        if proposed.get(field) != live.get(field):
            return False
    for field in ('title', 'description'):
        if _words(proposed.get(field)) != _words(live.get(field)):
            return False
    for field in ('duration_minutes', 'rpe', 'tss'):
        value = proposed.get(field)
        if value is not None and value != live.get(field):
            return False
    benchmark = proposed.get('benchmark_type')
    # Apply blanks the flag when a test's slot is rewritten without it, so that IS a
    # change (DESIGN_benchmark_workouts.md §4.2).
    if benchmark != live.get('benchmark_type') and (benchmark or live.get('benchmark_type')):
        return False
    currency, seconds = intensity.parse_planned_zones(proposed)
    if currency is not None and currency != live.get('planned_zone_currency'):
        return False
    zones = list(seconds or [])[:7]
    zones += [None] * (7 - len(zones))
    for index, value in enumerate(zones, start=1):
        if value is not None and value != live.get(f'planned_zone{index}_sec'):
            return False
    return True


def normalize_load_fields(workouts: List[Dict[str, Any]]) -> None:
    """Rounds the model's load fields to the integers the plan columns store.

    A JSON `24.0` is the same load as a stored `24`, but it renders `TSS24 -> TSS24.0`, so
    an unchanged number reads as a change. Fixed here rather than in the prompt so
    correctness does not rest on the model's formatting.
    """
    for w in workouts:
        for field in ('duration_minutes', 'rpe', 'tss'):
            value = w.get(field)
            if isinstance(value, float):
                w[field] = round(value)


def held_slots(held: Sequence[Tuple[str, str]]) -> Dict[str, set]:
    """`date -> {canonical sport}` for the sessions a revision holds rather than rewrites.

    A held session appends nothing, but it is still spoken for: the displacement rule
    below and in `workout_revision_apply` reads an unmentioned sport as one the week planner
    wants gone, so omitting it here deletes it (§9.1).
    """
    by_date: Dict[str, set] = {}
    for date, sport in held:
        by_date.setdefault(date, set()).add(canonical_sport(sport))
    return by_date


def pair_revisions(
    proposals: List[Dict[str, Any]], existing: List[Dict[str, Any]],
    held: Sequence[Tuple[str, str]] = (),
) -> Tuple[Tuple[RevisionPair, ...], Tuple[Dict[str, Any], ...]]:
    """Decides, per date, which planned session each proposal replaces.

    An in-place change matches its original by (date, canonical sport). A sport swap
    carries a new sport_type and so has no same-sport original: on a proposed date, an
    existing session whose canonical sport is not among that date's proposals is the one
    being overridden, and is paired with that date's new-sport proposal.

    A session the week planner MOVED says so itself, in `replaces_slot`, and is paired
    with the session standing in the slot it names — which may be another date. That
    session is then not overridden by whatever else lands on its own date: it left, and
    saying otherwise would print the move as a cancellation and an arrival
    (DESIGN_workout_revisions.md §11).

    `held` names sessions the week planner kept as planned. They produce no pair — there is
    nothing to show — but they count as proposed, so a date's other change cannot
    displace them (§9.1).

    Returns `(pairs, removals)`, where removals are overridden sessions left without a
    replacement — plain deletions, which the preview must show so apply never drops a
    session silently.
    """
    proposed_by_date: Dict[str, List[Dict[str, Any]]] = {}
    for proposal in proposals:
        proposed_by_date.setdefault(proposal["date"], []).append(proposal)

    existing_by_date: Dict[str, List[Dict[str, Any]]] = {}
    for session in existing:
        existing_by_date.setdefault(session["date"], []).append(session)

    held_by_date = held_slots(held)
    swap_original: Dict[int, Dict[str, Any]] = {}
    removals: List[Dict[str, Any]] = []

    by_slot = {(w["date"], canonical_sport(w["sport_type"])): w for w in existing}
    moved_from: Dict[int, Dict[str, Any]] = {}
    departed: set = set()
    for proposal in proposals:
        named = proposal.get("replaces_slot")
        slot = (named[0], canonical_sport(named[1])) if named else None
        if slot is None or slot not in by_slot:
            continue
        moved_from[id(proposal)] = by_slot[slot]
        departed.add(slot)

    for date, date_proposals in proposed_by_date.items():
        on_date = existing_by_date.get(date, [])
        proposed_sports = {canonical_sport(p["sport_type"]) for p in date_proposals}
        proposed_sports |= held_by_date.get(date, set())
        existing_sports = {canonical_sport(e["sport_type"]) for e in on_date}

        overridden = [
            e for e in on_date
            if canonical_sport(e["sport_type"]) not in proposed_sports
            and (e["date"], canonical_sport(e["sport_type"])) not in departed
        ]
        new_sport_proposals = [
            p for p in date_proposals
            if canonical_sport(p["sport_type"]) not in existing_sports
            and id(p) not in moved_from
        ]
        # The common case is one overridden session and one new-sport proposal — a clean
        # swap — so pair positionally and treat the surplus as deletions.
        for proposal, original in zip(new_sport_proposals, overridden):
            swap_original[id(proposal)] = original
        removals.extend(overridden[len(new_sport_proposals):])

    pairs = []
    for proposal in proposals:
        same_sport = next(
            (
                e for e in existing_by_date.get(proposal["date"], [])
                if canonical_sport(e["sport_type"]) == canonical_sport(proposal["sport_type"])
            ),
            None,
        )
        displaced = moved_from.get(id(proposal)) or swap_original.get(id(proposal))
        pairs.append(
            RevisionPair(
                proposal=proposal,
                original=same_sport or displaced,
                # A move to another day keeps its sport, so the sport label must not
                # claim a swap the athlete would not recognize.
                is_swap=(
                    same_sport is None and displaced is not None
                    and canonical_sport(displaced["sport_type"])
                    != canonical_sport(proposal["sport_type"])
                ),
            )
        )
    return tuple(pairs), tuple(removals)
