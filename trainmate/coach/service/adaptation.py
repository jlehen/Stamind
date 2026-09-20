from datetime import datetime, timedelta
from typing import Any, List, Optional, Dict, Sequence, Set, Tuple
from trainmate.config import config
from trainmate.adherence import (
    analyze_adherence, format_discrepancies, performed_sessions,
)
from trainmate.sports import canonical_sport
from trainmate import intensity, signals
from trainmate.util import cmd, fmt_date, notice
from trainmate.coach.formatting import format_baseline
from trainmate.coach import honoring
from trainmate.coach.proposals import RevisionProposal
from trainmate.coach.revisions import (
    held_slots, normalize_load_fields, pair_revisions, prescription_matches,
    replaces_source, rest_in_place_of, structure_revision,
)
from trainmate.db.workouts import ATHLETE_VOID_KINDS
from trainmate.strength import planner as strength_planner
from trainmate.types import Workout
import trainmate.coach.service as _svc


def _outside_tweak_reach(days: Sequence[str], meso_end: str) -> str:
    """The refusal for days a tweak cannot reach: it goes as far as `workout adapt`, from
    today to the end of the current mesocycle (DESIGN_workout_tweak.md §3.2)."""
    return (
        f"A tweak reaches from today to the end of the current mesocycle "
        f"({fmt_date(meso_end)}). Outside that: {', '.join(fmt_date(d) for d in days)}. "
        f"To plan around a day further out, add a constraint with {cmd('constraint add')}."
    )


class AdaptationMixin:
    """Part of :class:`CoachService` — see coach/service/__init__.py."""

    @staticmethod
    def _is_keep_marker(proposal: Dict[str, Any]) -> bool:
        """True for `{"date", "sport_type", "keep": true}` — hold this session, don't
        rewrite it. Carries no prescription, so it cannot drift into a spurious
        adaptation the way a verbatim re-list does (DESIGN_workout_revisions.md §9.1)."""
        return bool(proposal.get('keep'))

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

    def _revision_is_change(self, proposal: Dict[str, Any]) -> bool:
        """True unless `proposal` prescribes exactly what the live session already does.

        Backstops the adaptation prompt's "return only changed sessions" rule: a verbatim
        (or cosmetic-only) re-list of an unchanged session is treated as a no-op so it is
        not re-stamped as adapted or re-synced. A proposal on a date with no current
        session is always a real change.

        Asks `prescription_matches`, the §9 no-op rule the preview already uses. Its own
        copy compared five fields and so could not see a change to the intensity target or
        the benchmark flag, which the write path and the preview both count.
        """
        live = self._db.get_workout(proposal['date'], proposal['sport_type'])
        if not live:
            return True
        return not prescription_matches(proposal, live)

    def _rejected_matches(self) -> set:
        """The `(activity_id, sport)` pairings the athlete has said are NOT that session."""
        return {
            key for key, accepted in self._db.get_match_decisions().items()
            if not accepted
        }

    def pending_match_questions(
        self, target_date_str: Optional[str] = None
    ) -> List[Dict[str, Any]]:
        """Pairings in the adapt window that are a guess and that the athlete has not yet
        ruled on — `adherence.is_ambiguous_match` (ARCHITECTURE.md §15).

        Asked BEFORE the LLM call, because a wrong pairing does not merely mislabel a row:
        it tells the week planner a session was performed. Each entry carries the planned session
        and the activity so the caller can render the question without re-deriving it.
        """
        if not target_date_str:
            target_date_str = _svc._today_str()
        target_date_obj = datetime.strptime(target_date_str, "%Y-%m-%d").date()
        history_days = config.metrics_lookback_days
        start_date_obj = target_date_obj - timedelta(days=history_days - 1)
        start_date_str = start_date_obj.strftime("%Y-%m-%d")

        active_meso = self._db.get_active_mesocycle(target_date_str)
        end_date_str = active_meso['end_date'] if active_meso else target_date_str
        planned = [
            w for w in self._db.get_workouts(
                start_date=start_date_str, end_date=end_date_str, include_removed=True
            ) if not w.get('removed')
        ]
        activities = self._db.get_completed_activities(
            start_date=start_date_str, end_date=target_date_str
        )

        # Pair with NO rejections applied: a pairing already answered "no" would other-
        # wise vanish before we could tell it apart from one never asked about.
        _d, matching_results, _i = analyze_adherence(
            planned_workouts=planned,
            completed_activities=activities,
            start_date_obj=start_date_obj,
            history_days=history_days,
            minor_activity_load_threshold=config.minor_activity_load_threshold,
            covered_ranges=self._db.get_mesocycle_ranges(start_date_str, target_date_str),
            pending_from=target_date_str,
        )

        decided = self._db.get_match_decisions()
        questions = []
        for m in matching_results:
            if not m.get("ambiguous"):
                continue
            act = m["completed"]
            sport = canonical_sport(m["planned"]["sport_type"])
            if (act["activity_id"], sport) in decided:
                continue
            questions.append({
                "activity_id": act["activity_id"],
                "sport": sport,
                "date": m["date"],
                "planned": m["planned"],
                "completed": act,
            })
        return questions

    def record_match_decision(
        self, activity_id: str, sport: str, accepted: bool
    ) -> None:
        """Persists one answer, so the question is asked once rather than every run and
        every adherence surface reads the same pairing."""
        self._db.save_match_decision(activity_id, canonical_sport(sport), accepted)

    def workout_tweak(
        self, message: str, tweak_dates: Sequence[str] = (),
        today_str: Optional[str] = None,
    ) -> RevisionProposal:
        """Changes the days a request is about: `workout adapt`'s path with a narrower job
        (DESIGN_workout_tweak.md §3.2). Empty `tweak_dates` lets the week planner read the
        days off the message."""
        return self.workout_adapt(
            today_str, message=message, tweak=True, tweak_dates=tweak_dates
        )

    @staticmethod
    def _tweak_days(
        decision: Dict[str, Any], tweak_dates: Sequence[str], first: str, last: str
    ) -> Set[str]:
        """The days a tweak may write: the caller's, else the ones the week planner named.
        Raises when the reply changes sessions and names no usable day, or a day past
        what a tweak reaches (§3.2)."""
        if tweak_dates:
            return set(tweak_dates)
        named = {str(day) for day in decision.get("tweak_dates") or []}
        if not named:
            raise ValueError(
                "The coach could not tell which day you mean. Name it: "
                + cmd('workout tweak -d DATE "..."')
            )
        outside = sorted(day for day in named if not first <= day <= last)
        if outside:
            raise ValueError(_outside_tweak_reach(outside, last))
        return named

    @staticmethod
    def _only_on(days: Set[str], adapted: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        """A tweak's rows cut down to its days: nothing on another date, and no session
        moved in from one (§3.2)."""
        kept = []
        for w in adapted:
            if w.get("date") not in days:
                continue
            came_from = replaces_source(w)
            if came_from and came_from[0] not in days:
                continue
            kept.append(w)
        return kept

    def workout_adapt(
        self, target_date_str: Optional[str] = None, message: Optional[str] = None,
        tweak: bool = False, tweak_dates: Sequence[str] = (),
    ) -> RevisionProposal:
        """Evaluates metrics/activities over a rolling window and adapts mesocycle if needed.

        `message` is an optional free-text note from the athlete, passed to the SAME LLM
        call as advisory intent for today (DESIGN_constraints.md §8 — no separate
        classification pass). That one call may also extract constraint-shaped directives
        from the note; they come back as the third element, raw and UNCONFIRMED — the
        caller must confirm each with the athlete (echo + y/N) before persisting it via
        `capture_message_constraint`, per the two-confirmation flow. Nothing here creates
        a constraint row or triggers a plan regen on its own.

        `tweak` narrows the job to the days a request is about; see `workout_tweak`.
        """
        if not target_date_str:
            target_date_str = _svc._today_str()

        target_date_obj = datetime.strptime(target_date_str, "%Y-%m-%d").date()

        # Fetch metrics history window
        history_days = config.metrics_lookback_days
        start_date_obj = target_date_obj - timedelta(days=history_days - 1)
        start_date_str = start_date_obj.strftime("%Y-%m-%d")

        metrics = self._db.get_metrics_cache(
            start_date=start_date_str, end_date=target_date_str
        )
        completed_activities = self._db.get_completed_activities(
            start_date=start_date_str, end_date=target_date_str
        )

        # External daily signals over the window, so the adaptation can tell a
        # lifestyle-suppressed morning (alcohol/poor sleep the day before) from genuine
        # training fatigue and avoid cutting load on a non-training artifact. Recovery
        # lags the signal by a day, so reach one day before the metrics window to cover
        # the first morning's preceding-day signal.
        signal_start_str = (start_date_obj - timedelta(days=1)).strftime("%Y-%m-%d")
        daily_signals = self._db.get_daily_signals(
            start_date=signal_start_str, end_date=target_date_str
        )

        # Workouts are fetched across the whole span (lookback start -> mesocycle end), not
        # just the backward window: otherwise the LLM never sees already-scheduled future
        # sessions and reinvents them, overwriting the athlete's plan. And no plan means no
        # adaptation — there is nothing to adapt *towards* (DESIGN_mesocycle_boundary.md §6).
        active_meso = self._db.get_active_mesocycle(target_date_str)
        if not active_meso:
            raise ValueError(
                "No active periodization strategy found. Run "
                + cmd("plan generate") + " first."
            )
        meso_end_date_str = active_meso['end_date']
        outside = sorted(
            day for day in tweak_dates
            if not target_date_str <= day <= meso_end_date_str
        )
        if outside:
            raise ValueError(_outside_tweak_reach(outside, meso_end_date_str))

        # The BACKWARD window — from the adherence lookback start, removed rows included —
        # not the forward one the proposal carries. Two different ranges, so two names.
        lookback_workouts = self._db.get_workouts(
            start_date=start_date_str, end_date=meso_end_date_str, include_removed=True
        )
        planned_workouts = [w for w in lookback_workouts if not w.get('removed')]
        # Only the cancellations the ATHLETE made. A day the plan simply stopped
        # scheduling is a void too, and telling the week planner it was cancelled would put words
        # in the athlete's mouth (DESIGN_workout_revisions.md §3).
        removed_workouts = [
            w for w in lookback_workouts
            if w.get('removed') and w.get('change_kind') in ATHLETE_VOID_KINDS
        ]
        if tweak:
            # A tweak may bring any of them back, so it is shown every one ahead, whoever
            # cancelled it (DESIGN_workout_tweak.md §3.1).
            removed_workouts = self._db.get_cancelled_workouts(
                target_date_str, meso_end_date_str
            )

        baseline = self._db.get_baseline(target_date_str)
        baseline_str = format_baseline(baseline)

        # Planned mesocycles overlapping the window. Activities on dates outside every mesocycle
        # are history the plan never governed (e.g. before tool adoption), so they are
        # reported as informational rather than as "unplanned" deviations.
        covered_ranges = self._db.get_mesocycle_ranges(start_date_str, target_date_str)

        # Match planned workouts vs completed activities and compute discrepancies.
        # analyze_adherence only inspects the `history_days` backward window, so the
        # future-dated workouts now in `planned_workouts` are ignored here (no false misses).
        # The window ENDS on the evaluation date, though, so today's not-yet-trained
        # sessions are pending, not missed — adapt runs in the morning.
        discrepancies, matching_results, informational = analyze_adherence(
            planned_workouts=planned_workouts,
            completed_activities=completed_activities,
            start_date_obj=start_date_obj,
            history_days=history_days,
            minor_activity_load_threshold=config.minor_activity_load_threshold,
            covered_ranges=covered_ranges,
            pending_from=target_date_str,
            rejected_matches=self._rejected_matches(),
        )

        # What each planned session actually got, and which of them are history the LLM
        # may not rewrite: the evaluation date is the first day of the adaptation range,
        # but the athlete may have already trained today. Without the lock the LLM
        # "adapts" a finished session (typically restating it to match the actual ride),
        # which is meaningless and, on apply, rewrites a past calendar event — and a
        # session abandoned after its warm-up is not finished (ARCHITECTURE.md §15).
        performed = performed_sessions(
            matching_results, target_date_str, config.minor_activity_load_threshold
        )
        completed_keys = {key for key, p in performed.items() if p.locked}

        objectives = self._db.upcoming_objectives()

        # Determine the fallback next_goal for passing to the prompt generator
        next_goal = None
        for obj in objectives:
            if obj['id'] is not None:
                macro = self._db.get_macrocycle_for_objective(obj['id'])
                if macro:
                    next_goal = obj
                    break
        if not next_goal and objectives:
            objectives.sort(key=lambda x: str(x['target_date']))
            next_goal = objectives[0]

        # Active constraints overlapping the adaptation window (target date → mesocycle
        # end), the single directive read path shared with generate (§6).
        constraints = self._db.get_constraints(target_date_str, meso_end_date_str)
        ctx = self._coach_context(
            constraints, objectives=objectives,
            objective_id=next_goal['id'] if next_goal else None,
        )
        guidelines, profile = ctx.guidelines, ctx.profile
        strategy, meso_text, learnings = ctx.strategy, ctx.meso_text, ctx.learnings

        # §8: the athlete's note is passed straight through as advisory intent — no
        # separate classification pass. The same LLM call also extracts any
        # constraint-shaped directives from it (see `new_constraints` below).
        pmc_cutoff, pmc_context = self._pmc_prompt_context(target_date_str)
        # The mesocycle's measured intensity distribution — adapt's primary view, since drift
        # caught in week 2 is correctable and drift diagnosed at plan-generation time is
        # history (DESIGN_intensity_distribution.md §9). Threaded as its own argument, NOT
        # folded into meso_text: that string is shared with plan generation, which §9.2
        # says must not grow this section.
        intensity_context = self._intensity_mesocycle_context(target_date_str)
        if tweak:
            # Drift is the morning adaptation's question, not a request's (§3.2).
            intensity_context = None
        decision = self.engine._workout_adapt_logic(
            target_date_str=target_date_str,
            history_days=history_days,
            start_date_str=start_date_str,
            metrics=metrics,
            completed_activities=completed_activities,
            planned_workouts=planned_workouts,
            baseline_str=baseline_str,
            meso_end_date_str=meso_end_date_str,
            objectives=objectives,
            guidelines=guidelines,
            profile=profile,
            strategy=strategy,
            meso_text=meso_text,
            learnings=learnings,
            discrepancies=format_discrepancies(discrepancies),
            informational=informational,
            removed_workouts=removed_workouts,
            daily_signals=daily_signals,
            performed=performed,
            athlete_message=message,
            constraints=constraints,
            pmc_warmup_cutoff=pmc_cutoff,
            pmc_context=pmc_context,
            intensity_context=intensity_context,
            zone_currencies=self._planning_zone_currencies(target_date_str),
            # Config-merged categories annotated with what is actually logged, so the model
            # reuses a category rather than coining one (DESIGN_signal_extraction.md §5).
            signal_vocabulary=signals.format_vocabulary(
                config.signal_metrics, self._db.list_signal_metrics()
            ),
            signal_earliest_date=start_date_str,
            tweak=tweak,
            tweak_dates=tweak_dates,
        )

        # NOTE: daily adaptation is read-only w.r.t. coach learnings
        # (DESIGN_evidence_based_confidence.md §2/§11). It consumes the rendered learnings as
        # context but authors none — durable, evidence-backed observations are written only by
        # the weekly history analysis (`data bootstrap` / `data reflect`), which can attribute
        # them to specific training weeks.

        reason = decision.get("reason", "No adaptation needed.")
        adapted = []
        if decision.get("change_needed"):
            adapted = decision.get("adapted_workouts", [])
        # The days a tweak may write, read before the passes below add rows of their own
        # (DESIGN_workout_tweak.md §3.2). A reply that changes nothing needs none.
        tweak_days: Set[str] = set(tweak_dates)
        if tweak and adapted:
            tweak_days = self._tweak_days(
                decision, tweak_dates, target_date_str, meso_end_date_str
            )

        # Integers, before the no-op backstop and the preview both read these numbers.
        normalize_load_fields(adapted)

        # Drop any proposal dated past the adaptation range: the next mesocycle is out of reach
        # and was never shown to the model, so a post-boundary date is a hallucination
        # (DESIGN_mesocycle_boundary.md §1).
        adapted = [w for w in adapted if str(w.get("date", "")) <= meso_end_date_str]

        # Drop any proposal that targets an already-completed session — those are locked
        # history (see completed_keys above). This is the load-bearing guard: it holds even
        # if the model ignores the prompt instruction not to adapt finished sessions.
        if completed_keys:
            adapted = [
                w for w in adapted
                if (w.get("date"), canonical_sport(w.get("sport_type", "")))
                not in completed_keys
            ]

        # Held, not dropped (DESIGN_workout_revisions.md §9.1). A session named only to keep
        # it — a keep marker, or the verbatim re-list the no-op backstop catches — appends
        # no revision but stays SPOKEN FOR, because the same list decides what its date
        # keeps. Filtered out instead, it was deleted by the change it was protecting.
        held: List[Tuple[str, str]] = []
        changed: List[Dict[str, Any]] = []
        for w in adapted:
            if self._is_keep_marker(w) or not self._revision_is_change(w):
                held.append((w.get("date", ""), canonical_sport(w.get("sport_type", ""))))
            else:
                changed.append(w)
        adapted = changed

        # A completed session is held by history, not by the week planner naming it: the drop
        # guard above only catches a proposal aimed AT its slot, while a rest day (or any
        # other sport) proposed for the same date displaces it without ever naming it
        # (DESIGN_workout_revisions.md §9.2).
        held.extend(key for key in completed_keys if key[0] >= target_date_str)

        # Deterministic rest-window pre-pass (§6): force rest onto any future,
        # not-yet-completed planned session that falls under a `rest` constraint, so the
        # guarantee holds regardless of what the model proposed.
        adapted = self._enforce_rest_windows_revision(
            adapted, planned_workouts, constraints, completed_keys, target_date_str
        )
        # A forced-rest day is cleared outright, so nothing on it is held: the constraint
        # outranks the week planner's wish to keep the session (§6 over §9.1). A session already
        # trained is the exception — no constraint reaches backwards into work that is
        # already done (§9.2).
        forced_rest = self._forced_rest_days(
            planned_workouts, constraints, completed_keys, target_date_str
        )
        held = [
            (date, sport) for date, sport in held
            if date not in forced_rest or (date, sport) in completed_keys
        ]

        # §8: constraint-shaped directives the same LLM call extracted from the athlete's
        # note, if any — raw and UNCONFIRMED. The caller must confirm each with the
        # athlete before persisting it (via capture_message_constraint); nothing here
        # writes a row.
        new_constraints = (decision.get("new_constraints") or []) if message else []
        # Same gate, same rule: candidates only, confirmed and written by the caller via
        # `capture_message_signal` (DESIGN_signal_extraction.md §2).
        new_signals = (decision.get("new_signals") or []) if message else []

        # Read once, against the same range apply will act on — the CLI used to
        # re-derive the pairing for its preview and rebuild a narrower range from the
        # proposal dates, so the two could disagree about which sessions disappear.
        window_workouts = self._db.get_workouts(
            start_date=target_date_str, end_date=meso_end_date_str
        )
        # A tweak writes its days only, whatever came back and whatever the passes above
        # added. Cut before the moves are resolved, so a move left half out writes no rest
        # day with a reason about it (DESIGN_workout_tweak.md §3.2).
        if tweak:
            adapted = self._only_on(tweak_days, adapted)
        # A session the week planner carried to another day says where it came from, and
        # the lineage travels with it rather than ending where it left (§11). Last of the
        # passes, so a move whose destination a rest constraint cleared is already gone.
        adapted = self._resolve_moves(adapted, window_workouts, completed_keys)

        # The row shape both revision commands write, built in one place (§7).
        structured = structure_revision(adapted, reason)

        # The kilograms, written by a call of its own from the sets the athlete actually
        # lifted — after the moves are resolved, so a session that changed day is already
        # known to be the same session, and before the revisions are paired, so the preview
        # shows what apply will write (DESIGN_strength_tracking.md §9).
        week_planner_changed = bool(structured)
        # A tweak shows the strength planner its own days only, and nothing when the week
        # planner changed nothing (DESIGN_workout_tweak.md §3.2).
        strength_sessions = window_workouts
        strength_span = (target_date_str, meso_end_date_str)
        if tweak:
            strength_sessions = [w for w in window_workouts if w['date'] in tweak_days]
            strength_span = ("", "")
            if structured:
                strength_span = (min(tweak_days), max(tweak_days))
        strength = strength_planner.run(
            structured, strength_sessions, strength_span[0], strength_span[1],
            target_date_str, profile, constraints,
            reason_key='modification_reason', held=held,
        )
        if strength is not None:
            structured.extend(strength.added)
            held.extend(self._hold_around(strength.held_dates, window_workouts))
            # When only the strength planner changed something, its sentences are what the
            # morning briefing prints, in place of "No adaptation needed." (§9).
            if strength.reasons and not week_planner_changed:
                reason = " ".join(strength.reasons)
                for row in structured:
                    if not row.get('modification_reason'):
                        row['modification_reason'] = reason

        pairs, removals = pair_revisions(structured, window_workouts, held)
        # Decided at proposal time so apply stamps this list rather than re-deriving
        # it from a set that may have been edited since (§8). A tweak had authority over
        # a few days, so it may stamp nothing (DESIGN_workout_tweak.md §3.2).
        covered = honoring.covered_ids(constraints, target_date_str, meso_end_date_str)
        if tweak:
            covered = ()
        return RevisionProposal(
            reason=reason,
            workouts=structured,
            new_constraints=tuple(new_constraints),
            new_signals=tuple(new_signals),
            range_start=target_date_str,
            range_end=meso_end_date_str,
            kind="tweak" if tweak else "adapt",
            pairs=pairs,
            removals=removals,
            held=tuple(held),
            covered_constraint_ids=covered,
            strength_checks=tuple(strength.checked) if strength else (),
            strength_stamp=strength.stamp if strength else "",
            strength_notice=strength.notice if strength else None,
            strength_dropped=tuple(strength.dropped) if strength else (),
        )

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
