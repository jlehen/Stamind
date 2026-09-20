"""`workout adapt` and `workout tweak`: what today changes about the days ahead.

It is Wednesday morning. HRV is down and yesterday's ride never happened. `workout adapt`
reads the metrics and the activities over a rolling window, shows the week planner the
sessions it may rewrite, and comes back with a proposal that has written nothing.
`workout tweak` is the same call driven by a sentence the athlete typed, narrowed to the
days that sentence names.

Writing the proposal is `revision_apply.py`, and the rules its sessions pass on the way
out are `guards.py`. It is one mixin of :class:`CoachService` — see
coach/service/__init__.py.
"""
from datetime import datetime, timedelta
from typing import Any, Dict, List, Optional, Sequence, Set, Tuple

from trainmate.config import config
from trainmate.analytics.adherence import (
    analyze_adherence, format_discrepancies, performed_sessions,
)
from trainmate.sports import canonical_sport
from trainmate import signals
from trainmate.text import cmd
from trainmate.clock import fmt_date, today_str as _today_str
from trainmate.coach.formatting import format_baseline
from trainmate.coach import honoring
from trainmate.coach.proposals import RevisionProposal
from trainmate.coach.revisions import (
    normalize_load_fields, pair_revisions, prescription_matches, replaces_source,
    structure_revision,
)
from trainmate.db.workout_change import ATHLETE_VOID_KINDS
from trainmate.strength import planner as strength_planner


def _outside_tweak_reach(days: Sequence[str], meso_end: str) -> str:
    """The refusal for days a tweak cannot reach: it goes as far as `workout adapt`, from
    today to the end of the current mesocycle (DESIGN_workout_tweak.md §3.2)."""
    return (
        f"A tweak reaches from today to the end of the current mesocycle "
        f"({fmt_date(meso_end)}). Outside that: {', '.join(fmt_date(d) for d in days)}. "
        f"To plan around a day further out, add a constraint with {cmd('constraint add')}."
    )

class AdaptMixin:
    @staticmethod
    def _is_keep_marker(proposal: Dict[str, Any]) -> bool:
        """True for `{"date", "sport_type", "keep": true}` — hold this session, don't
        rewrite it. Carries no prescription, so it cannot drift into a spurious
        adaptation the way a verbatim re-list does (DESIGN_workout_revisions.md §9.1)."""
        return bool(proposal.get('keep'))

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
            target_date_str = _today_str()

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
                signals.signal_metrics(), self._db.list_signal_metrics()
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
            **strength_planner.proposal_fields(strength),
        )
