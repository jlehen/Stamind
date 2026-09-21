"""How a revision lands, and how it is taken back.

The write path for a `RevisionProposal` — what `workout adapt`, `workout tweak` and the
strength pass produce. `workout generate` has its own, in `generate.py`, because a
proposal for a whole span is a different shape.

A move arrives as two halves — the session at its new date, and the slot it left — and
both are resolved before anything is written, so the write sees one uniform list.
Nothing is deleted: a session a pass ends becomes a void revision, and a moved one
becomes a void at the source plus a revision at the destination carrying the same lineage
(DESIGN_workout_revisions.md §4, §11). A date the proposal mentions is read as holding
only the sessions named for it, so a pass that rewrites one session of a day has to say
which of its neighbours to keep; `_hold_around` works that out for the two passes that
need it, `workout_adapt` in `adapt.py` and `workout_generate_strength` in `generate.py`.
`workout_rollback` is the other direction — the sessions as they stood the moment before
a change ran.

It is one mixin of :class:`CoachService` — see coach/service/__init__.py.
"""
from contextlib import nullcontext
from typing import Any, Dict, List, Optional, Tuple

from stamind.types import Workout
from stamind.analytics import intensity
from stamind.sports import canonical_sport
from stamind.output import notice
from stamind.gcal.reconcile import verbose_events
from stamind.coach import honoring
from stamind.coach.proposals import RevisionProposal
from stamind.clock import today_str as _today_str
from stamind.coach.revisions import held_slots, replaces_source, rest_in_place_of
from stamind.strength import planner as strength_planner


class RevisionApplyMixin:
    @staticmethod
    def _vacated_rest(source: Workout, mover: Dict[str, Any]) -> Dict[str, Any]:
        """The rest day left on the date a move carried a session out of.

        Written here rather than asked of the week planner: the day it left is decided by
        the move itself, and a planner that forgot to name it used to leave a hole
        (DESIGN_workout_revisions.md §11)."""
        return rest_in_place_of(
            source, str(mover.get('change_reason') or ''),
            f"{source['title']} moved to {mover['date']}.",
        )

    @staticmethod
    def _move_source(
        entry: Dict[str, Any], by_slot: Dict[Tuple[str, str], Workout],
        completed_keys: set, claimed: set, leaving: set,
    ) -> Optional[Workout]:
        """The session an entry's `replaces` takes out of another slot, or None.

        Four answers are refused, each with a notice, because honouring half of one loses
        a session: a source no session stands in, a source the athlete has already
        trained, a destination that already holds a same-sport session, and a second
        entry claiming a source the first one took. A refused entry is still written
        where it stands — only its claim on the other day is dropped.

        A destination whose session is itself `leaving`, moved out by another entry, is
        free: that is a swap of two sessions of the same sport (DESIGN_workout_tweak.md
        §3.1).
        """
        source = replaces_source(entry)
        if source is None:
            return None
        if source not in by_slot:
            notice(
                f"The coach says this {entry.get('date')} session came from "
                f"{source[0]}, where no session of yours stands — writing it where it "
                f"is and leaving {source[0]} alone.",
            )
            return None
        if source in completed_keys:
            notice(
                f"The coach moved the {source[0]} session to {entry.get('date')}, but "
                f"you have already trained it — writing the new session and leaving "
                f"{source[0]} alone.",
            )
            return None
        slot = (entry.get('date'), canonical_sport(entry.get('sport_type', '')))
        if slot in by_slot and slot not in leaving:
            notice(
                f"The coach moved the {source[0]} session onto {entry.get('date')}, "
                f"where a session of yours already stands — revising that one and "
                f"leaving {source[0]} alone.",
            )
            return None
        if source in claimed:
            notice(f"Two sessions came back for the {source[0]} session — keeping the "
                   f"first.")
            return None
        return by_slot[source]

    def _resolve_moves(
        self, adapted: List[Dict[str, Any]], window_workouts: List[Workout],
        completed_keys: set,
    ) -> List[Dict[str, Any]]:
        """Turns each accepted `replaces` into the slot the session leaves and the
        lineage it carries there, and fills the day it left
        (DESIGN_workout_revisions.md §11).

        A date a move empties gets a rest day, unless another entry already covers it or
        another session still stands there.
        """
        by_slot = {
            (w['date'], canonical_sport(w['sport_type'])): w for w in window_workouts
        }
        # The sessions some entry carries out of their slot, and could: the other half of
        # a swap lands where one of them stood.
        leaving = {
            source for source in map(replaces_source, adapted)
            if source in by_slot and source not in completed_keys
        }
        out: List[Dict[str, Any]] = []
        movers: Dict[Tuple[str, str], Dict[str, Any]] = {}   # source slot -> its mover
        for entry in adapted:
            occupant = self._move_source(
                entry, by_slot, completed_keys, set(movers), leaving
            )
            if occupant is None:
                out.append(entry)
                continue
            entry = {
                **entry,
                'replaces_slot': (occupant['date'], occupant['sport_type']),
                'replaces_lineage': occupant['id'],
            }
            movers[(occupant['date'], canonical_sport(occupant['sport_type']))] = entry
            out.append(entry)

        covered = {w.get('date') for w in out}
        for source, mover in movers.items():
            day = source[0]
            if day in covered:
                continue
            # Another session still stands on the day it left, so the day is not empty
            # and a rest row there would contradict it.
            if any(
                w['date'] == day
                and (w['date'], canonical_sport(w['sport_type'])) not in movers
                for w in window_workouts
            ):
                continue
            out.append(self._vacated_rest(by_slot[source], mover))
            covered.add(day)
        return out

    @staticmethod
    def _hold_around(
        days: List[str], window_workouts: List[Dict[str, Any]]
    ) -> List[Tuple[str, str]]:
        """The other sessions of a date the strength planner named on its own.

        Apply reads a date the proposal mentions as holding only the sessions named for it
        and voids the rest (DESIGN_workout_revisions.md §9.1). The week planner knows that
        and names what it keeps; a kilogram change arrives after it has spoken, on a day it
        may never have mentioned, so Thursday's intervals would be removed because the belt
        squat went up 5 kg (DESIGN_strength_tracking.md §9).
        """
        strength = canonical_sport('strength_training')
        return [
            (w['date'], canonical_sport(w['sport_type']))
            for w in window_workouts
            if w['date'] in days and canonical_sport(w['sport_type']) != strength
        ]

    def workout_revision_apply(
        self, proposal: RevisionProposal
    ) -> None:
        """Appends a revision's sessions under one change, and lets Calendar follow.

        Takes the whole proposal so the range and the displacement decisions are the ones
        the week planner actually made, not a reconstruction.

        A session the pass drops becomes a void revision rather than a `DELETE`, and one it
        moves to another day or substitutes cross-sport becomes a void at the source plus a
        revision at the destination carrying the same lineage — the swap shape, which is
        what keeps the adaptation tally following the session
        (DESIGN_workout_revisions.md §4/§11). The voids go first, so a moved session's
        newest revision is always the copy (§8).
        """
        proposed_workouts = proposal.workouts
        start_date, end_date = proposal.range_start, proposal.range_end
        # Read before the change opens, so every decision below is made against the plan
        # as it stood, not against rows this pass has already appended.
        existing_workouts = self._db.get_workouts(
            start_date=start_date, end_date=end_date
        )
        by_slot = {
            (w['date'], canonical_sport(w['sport_type'])): w for w in existing_workouts
        }

        proposed_by_date: Dict[str, List[Dict[str, Any]]] = {}
        for pw in proposed_workouts:
            proposed_by_date.setdefault(pw['date'], []).append(pw)
        # Sessions the week planner kept as planned. They append nothing, but they are spoken for,
        # so the displacement rule below must not read them as sessions it wants gone
        # (§9.1) — the same union the preview made in `pair_revisions`.
        held_by_date = held_slots(proposal.held)

        # The slots a move takes a session OUT of, each named by the entry that takes it
        # there. Kept out of the displacement rule below: the session left, so whatever
        # else lands on its date is not what replaced it and must not take its lineage.
        moved_out: Dict[Tuple[str, str], Dict[str, Any]] = {}
        for pw in proposed_workouts:
            named = pw.get('replaces_slot')
            if named:
                moved_out[(named[0], canonical_sport(named[1]))] = pw

        # The session displaced on each date, so a cross-sport substitution can carry its
        # lineage to the sport it becomes.
        displaced_by_date: Dict[str, Dict[str, Any]] = {}
        for ew in existing_workouts:
            if (ew['date'], canonical_sport(ew['sport_type'])) in moved_out:
                continue
            if ew['date'] not in proposed_by_date:
                continue
            # Compare canonically so a proposal for 'strength_training' is recognized as
            # adapting an existing 'strength' session, not overriding it.
            proposed_sports = {
                canonical_sport(p['sport_type']) for p in proposed_by_date[ew['date']]
            }
            proposed_sports |= held_by_date.get(ew['date'], set())
            if canonical_sport(ew['sport_type']) not in proposed_sports:
                displaced_by_date.setdefault(ew['date'], ew)

        # The reason is also the athlete's line about this change, in the one column both
        # revision commands use (DESIGN_change_heads_up.md §6).
        with self._db.workout_change(
            kind=proposal.kind, summary=proposal.reason, note=proposal.reason
        ) as change:
            for (day, sport), mover in moved_out.items():
                source = by_slot.get((day, sport))
                if source is None:
                    continue
                notice(
                    f"Moving {source['title']} ({source['sport_type']}) from {day} to "
                    f"{mover['date']}",
                )
                change.void(
                    date=source['date'], sport_type=source['sport_type'],
                    reason=mover.get('modification_reason') or proposal.reason,
                )

            for ew in displaced_by_date.values():
                notice(
                    f"Removing overridden workout: {ew['title']} ({ew['sport_type']}) "
                    f"on {ew['date']}",
                )
                change.void(
                    date=ew['date'], sport_type=ew['sport_type'],
                    reason=proposal.reason,
                )

            for w in proposed_workouts:
                slot = (w['date'], canonical_sport(w['sport_type']))
                existing = by_slot.get(slot)
                # No same-sport session to revise: this proposal swapped in a new sport.
                # It IS the displaced session, in a different sport, so it carries that
                # session's lineage — which is what keeps its originals and its tally (§4).
                # Popped, not read: a date's displaced session can only become ONE of the
                # sessions replacing it, and handing its lineage to two would leave one
                # session live in two slots (§10). A second new-sport proposal that day is
                # a session in its own right and starts its own lineage.
                #
                # A move already named the session it carries, so it skips that rule
                # entirely: its lineage is the one the source slot held (§11).
                if w.get('replaces_slot'):
                    lineage_id = w.get('replaces_lineage')
                else:
                    displaced = None if existing else displaced_by_date.pop(w['date'], None)
                    lineage_id = displaced['id'] if displaced else None
                zone_currency, zone_sec = intensity.parse_planned_zones(w)
                # The flag belongs to the TEST, not to the slot: a returned change on a
                # benchmark's date that does not re-emit benchmark_type is the model saying
                # this session is no longer that test, so blank it rather than let the
                # carry-forward resurrect it onto a replacement
                # (DESIGN_benchmark_workouts.md §4.2).
                clear_benchmark = bool(
                    existing and existing['benchmark_type'] and not w.get('benchmark_type')
                )
                change.append(
                    date=w['date'],
                    sport_type=w['sport_type'],
                    title=w['title'],
                    description=w['description'],
                    duration_minutes=w.get('duration_minutes'),
                    rpe=w.get('rpe'),
                    tss=w.get('tss'),
                    reason=w.get('modification_reason'),
                    benchmark_type=w.get('benchmark_type'),
                    clear_benchmark=clear_benchmark,
                    lineage_id=lineage_id,
                    # The strength planner's exercises, written with the revision they
                    # belong to (DESIGN_strength_tracking.md §9).
                    prescribed_sets=w.get('prescribed_sets'),
                    # A drift correction rewrites HOW a session is prescribed, so its zone
                    # target moves with it; omitted, the carry-forward preserves what the
                    # plan already held (DESIGN_intensity_distribution.md §9.8).
                    planned_zone_currency=zone_currency,
                    planned_zone_sec=zone_sec,
                )

        # Stamped on the athlete's `y`, never on a proposal they declined (§8).
        honoring.stamp(self._db, proposal.covered_constraint_ids)
        strength_planner.record_checks(self._db, proposal)

    def workout_revision_record_no_change(self, proposal: RevisionProposal) -> None:
        """Records a pass that proposed nothing. Every revision command's no-change branch
        calls this, and it is the only write on that path.

        Two writes, neither of them a workout. The change row is written even though it
        appends nothing: an adapt that looked at the metrics and held is a real event, and
        `workout batches` reads it back as `(held)` — a run of them then says what it is
        rather than saying nothing (DESIGN_workout_revisions.md §3).

        And the pass still had the constraints in scope with authority over them, which is
        all `honored_at` claims — requiring a *change* would leave "no adaptation needed"
        flagged forever (§8). Separate from `workout_revision_apply` because there is
        nothing to apply, and outside the propose call because a propose writes nothing.
        """
        with self._db.workout_change(kind=proposal.kind, summary=proposal.reason):
            pass
        honoring.stamp(self._db, proposal.covered_constraint_ids)
        # A pass that weighed a session's kilograms and kept them has still weighed them,
        # which is what stops tomorrow asking again (DESIGN_strength_tracking.md §9).
        strength_planner.record_checks(self._db, proposal)

    def workout_rollback(
        self, change_id: Optional[int] = None, verbose: bool = False
    ) -> Dict[str, Any]:
        """Undoes a workout change — and every change made after it (§10).

        The sibling of `plan_rollback` on the workout axis: it puts the sessions back the
        way they were the moment before `change_id` ran, without touching the active plan
        version, so it also undoes a regeneration that never changed the strategy. With no
        target it undoes the newest change, which is what makes an adapt undoable on its
        own — point-in-time reverts what came AFTER the target, never what came before
        (DESIGN_plan_rollback.md §9, DESIGN_workout_revisions.md §10).

        Returns {change, restored_workouts, first_date, last_date, unhonored}.
        Raises ValueError when there is nothing to undo.
        """
        today_str = _today_str()
        changes = self._db.get_workout_changes(from_date=today_str)
        if not changes:
            raise ValueError(
                "No workout changes to roll back — nothing has been written yet."
            )
        if change_id is None:
            change_id = changes[0]["id"]
        target = next((c for c in changes if c["id"] == change_id), None)
        if target is None:
            raise ValueError(f"No workout change #{change_id}.")

        with verbose_events() if verbose else nullcontext():
            restored, unhonored = self._db.rollback_to_change(
                change_id, today_str,
                summary=f"Undo of change #{change_id} ({target['kind']}).",
            )
        return {
            'change': target,
            'restored_workouts': len(restored),
            'first_date': min((w['date'] for w in restored), default=None),
            'last_date': max((w['date'] for w in restored), default=None),
            # The restored plan predates these honorings, so they are unhonored again and
            # the caller says so (§8).
            'unhonored': unhonored,
        }
