"""`workout generate`: the sessions for a span, proposed and then written.

Three entry points, in the order a run meets them. `workout_generate` reads the plan
governing the span, asks the week planner, runs the answer through the guards and hands
back a proposal that has written nothing. `workout_generate_apply` writes that proposal
once the athlete has said yes. `workout_generate_strength` is `--strength-only`: the
strength pass over sessions that already stand.

The rules a proposal passes on the way out are `guards.py`, and the sessions the athlete
was already shown are `standing.py`. It is one mixin of :class:`CoachService` — see
coach/service/__init__.py.
"""
from contextlib import nullcontext
from datetime import date, datetime, timedelta
from typing import List, Optional

from trainmate.config import config
from trainmate.types import Workout
from trainmate.coach import honoring
from trainmate.coach.proposals import GenerateProposal, RevisionProposal
from trainmate.coach.revisions import normalize_load_fields, pair_revisions
from trainmate import settings
from trainmate.sports import canonical_sport
from trainmate.gcal.reconcile import verbose_events
from trainmate.analytics import intensity
from trainmate.strength import planner as strength_planner
from trainmate.text import cmd, green, keep_whole
from trainmate.output import notice
from trainmate.clock import fmt_date, today_str as _today_str


class WorkoutGenMixin:
    def workout_generate(
        self, start_date: Optional[str] = None, end_date: Optional[str] = None,
        prefer_macro_id: Optional[int] = None, fresh: bool = False
    ) -> GenerateProposal:
        """Proposes workouts (microcycles) from the plan mesocycles governing the span.

        Writes nothing: the caller previews the sessions and passes the proposal back to
        `workout_generate_apply` on a `y`, so a regeneration cannot archive the live plan
        for a proposal the athlete never saw.

        `start_date` opens the span and never reaches into the past — the caller's
        selectors pick which days are rebuilt, and the rest of the plan is left alone
        (DESIGN_cli_selectors.md §8).

        `fresh` (CLI `--fresh`) empties the commitment window for this run, so the week
        planner writes every day of the span the way it writes a day past the window
        (DESIGN_plan_change_continuity.md §4.4). It also has the strength planner write
        every strength session of the span again (DESIGN_strength_tracking.md §9).

        Which plan applies is read off the dates being generated, not off a goal the
        caller names: the goal was only ever an indirection to the macrocycle, and the
        mesocycles a span falls in are what actually shape the sessions
        (DESIGN_cli_selectors.md §8)."""
        if not self._db.get_active_objective():
            return GenerateProposal(
                reasoning="No active goals found. TrainMate needs at least one objective."
            )

        today_str = _today_str()
        today_date_obj = datetime.strptime(today_str, "%Y-%m-%d").date()

        # Retrieve recent history context
        history_days = config.metrics_lookback_days
        start_date_obj = today_date_obj - timedelta(days=history_days - 1)
        start_date_str = start_date_obj.strftime("%Y-%m-%d")

        metrics = self._db.get_metrics_cache(
            start_date=start_date_str, end_date=today_str
        )
        completed_activities = self._db.get_completed_activities(
            start_date=start_date_str, end_date=today_str
        )
        baseline = self._db.get_baseline(today_str)

        # The span opens where the selectors put it, never in the past: yesterday is
        # history, not a day to re-plan (§8).
        gen_start_str = max(start_date or today_str, today_str)

        # A regeneration replaces every workout in the span, but a session the athlete has
        # already completed should be preserved as history rather than overwritten. When
        # today's planned workout is already in the books, start the regenerated sessions
        # tomorrow and leave today's row (and its Calendar event) intact.
        if gen_start_str == today_str and self._today_workout_completed(
            today_str, completed_activities
        ):
            gen_start_str = (today_date_obj + timedelta(days=1)).strftime("%Y-%m-%d")
            print(green(
                f"Today's workout is already completed — preserving it and regenerating "
                f"from {gen_start_str}."
            ))
        gen_start_obj = datetime.strptime(gen_start_str, "%Y-%m-%d").date()

        if end_date is not None:
            end_date_obj = datetime.strptime(end_date, "%Y-%m-%d").date()
            # Inclusive of end_date itself — a `-g` span reads as "through this goal's
            # target date", so the race day belongs in it (§8).
            num_days = max(1, (end_date_obj - gen_start_obj).days + 1)
            gen_end_str = max(end_date, gen_start_str)
        else:
            num_days = config.workout_generation_span_days
            gen_end_str = (gen_start_obj + timedelta(days=num_days - 1)).strftime("%Y-%m-%d")

        # Back to the start of the mesocycle the athlete is in, not to the span: a constraint
        # that ended last week is why three sessions are missing from the mesocycle's record,
        # and the week planner cannot see the days themselves (§6.1). Only the ones still live
        # are worked around; the rest are context, and are kept out of the honoring and
        # rest-window passes below.
        mesocycle_now = self._db.get_covering_mesocycle(today_str)
        constraint_floor = min(
            (mesocycle_now or {}).get('start_date') or gen_start_str, gen_start_str
        )
        all_constraints = self._db.get_constraints(constraint_floor)
        constraints = [c for c in all_constraints if c['end_date'] >= gen_start_str]
        past_constraints = [c for c in all_constraints if c['end_date'] < gen_start_str]
        self._maybe_nudge_no_threshold()

        # The mesocycles governing the days about to be written — the whole periodization
        # input to this run, resolved from the window itself (§8).
        mesocycles, dropped_macros = self._db.get_governing_mesocycles(
            gen_start_str, gen_end_str, prefer_macro_id=prefer_macro_id
        )
        if not mesocycles:
            raise ValueError(
                "No active periodization strategy found. Run "
                + cmd("plan generate") + " first."
            )
        for macro_id in dropped_macros:
            notice(
                f"Plan ID {macro_id} also covers part of this span; following the more "
                f"recently generated plan instead. Pass "
                + cmd(keep_whole(f"-M {macro_id}"), quote=False) + " to follow that one.",
            )
        plan_end = max(b['end_date'] for b in mesocycles)
        if plan_end < gen_end_str:
            notice(
                f"The plan runs out on {plan_end}, before this horizon ({gen_end_str}) — "
                f"sessions after it have no mesocycle to follow. Run "
                + cmd("plan generate") + " to extend the periodization first.",
            )

        # All upcoming goals still reach the prompt as context; only the mesocycles above
        # decide what the sessions are shaped like.
        ctx = self._coach_context(constraints, mesocycles=mesocycles)
        objectives = ctx.objectives
        guidelines, profile = ctx.guidelines, ctx.profile
        strategy, meso_text, learnings = ctx.strategy, ctx.meso_text, ctx.learnings

        pmc_cutoff, pmc_context = self._pmc_prompt_context(today_str)
        # What the mesocycle has already banked, when this run re-plans only its remainder
        # (DESIGN_mesocycle_progress.md §3). Anchored on gen_start, so the day preserved for a
        # completed session counts as history rather than as a day still to write.
        mesocycle_progress, mesocycle_has_intensity = self._mesocycle_progress_context(
            today_str, gen_start_str
        )
        # The sessions this run would rewrite, and the part of them the athlete has already
        # been told about (DESIGN_plan_change_continuity.md §4.2). Read once and used by
        # the prompt, the resolver, the void set and the report.
        span_sessions = self._db.get_workouts(
            start_date=gen_start_str, end_date=gen_end_str
        )
        window_end: Optional[str] = None
        if not fresh:
            window_end = settings.commitment_end(today_str)
        standing_sessions = self._standing_sessions(span_sessions, window_end)
        planner_reply = self.engine._workout_generate_logic(
            objectives=objectives,
            constraints=constraints,
            today_str=today_str,
            start_str=gen_start_str,
            guidelines=guidelines,
            profile=profile,
            strategy=strategy,
            meso_text=meso_text,
            learnings=learnings,
            num_days=num_days,
            metrics=metrics,
            completed_activities=completed_activities,
            baseline=baseline,
            pmc_warmup_cutoff=pmc_cutoff,
            pmc_context=pmc_context,
            mesocycle_progress=mesocycle_progress,
            mesocycle_has_intensity=mesocycle_has_intensity,
            zone_currencies=self._planning_zone_currencies(today_str),
            anchor_history=self._anchor_history_text(gen_start_str),
            standing_workouts=standing_sessions,
            past_constraints=past_constraints,
            terse=settings.terse(),
        )

        # NOTE: workout generation is read-only w.r.t. coach learnings (see
        # DESIGN_backward_evaluation.md §11) — it does not apply learning_updates. Durable
        # memory is authored only by `analyze` and `plan generate`.

        # Save workouts to database
        workouts = planner_reply.get("workouts", [])

        # Every answer becomes a full session, so each pass below sees one kind of entry
        # and the void loop has nothing to void among the standing sessions
        # (DESIGN_plan_change_continuity.md §7).
        workouts, void_reasons = self._resolve_standing(
            workouts, standing_sessions, gen_start_str, gen_end_str
        )
        athlete_note = str(planner_reply.get("athlete_note") or "").strip() or None

        # Integers, before the preview and the save both read these numbers.
        normalize_load_fields(workouts)

        # Guard the preserved day: when today's completed session is being kept, drop any
        # workout the model mistakenly dated before the generation start. save_workout
        # matches on date+sport, so a stray today-dated row would silently overwrite the
        # completed session we deliberately kept.
        if gen_start_str != today_str:
            workouts = [w for w in workouts if w.get('date', '') >= gen_start_str]

        # Same-day collision guard (§4.1): drop any non-benchmark session that shares a
        # date+sport with a scheduled benchmark, before the (date, sport)-keyed save can
        # let it overwrite the test.
        workouts = self._drop_benchmark_collisions(workouts)

        # Deterministic rest-window pre-pass (DESIGN_constraints.md §6): a `rest`
        # constraint forces its dates to rest regardless of what the LLM produced. Every
        # other constraint is advisory and left to the model. Applied after generation so
        # the guarantee holds even if the model ignores the constraint section it was shown.
        workouts, forced_reasons = self._enforce_rest_windows_generate(
            workouts, constraints, gen_start_str, gen_end_str, span_sessions
        )
        # The constraint wins on its own dates, so its title is the reason there.
        void_reasons.update(forced_reasons)

        # Boundary-week benchmark post-check (§4.1): warn (don't auto-insert) if a covered
        # mesocycle boundary lacks a fitness test. Runs after the rest pass so a rest-covered
        # boundary week is already silenced.
        self._warn_missing_boundary_benchmarks(
            workouts, constraints, mesocycles, gen_start_str
        )

        # Coverage backstop (DESIGN_runway_nudge.md §2.1): every date of the span carries a
        # row, so a hole is the schedule ending rather than a rest day the model skipped.
        # After the benchmark post-check, which reads the span the model actually reached.
        workouts = self._fill_coverage_gaps(workouts, gen_start_str, gen_end_str)

        # The kilograms, written by a call of its own from the sets the athlete actually
        # lifted (DESIGN_strength_tracking.md §9). Before the proposal is built, so the
        # preview shows the exercise lines the athlete is accepting.
        strength = strength_planner.run(
            workouts, span_sessions, gen_start_str, gen_end_str, today_str,
            profile, constraints, reason_key='change_reason',
            write_again=fresh,
        )
        if strength is not None:
            workouts.extend(strength.added)

        # Which plan version each session belongs to, per date: a span long enough to run
        # from one goal's last mesocycle into the next goal's first produces workouts from two
        # macrocycles, and `plan rollback` accounting keys off this tag. Days past the last
        # mesocycle fall back to the plan that governed the start.
        def _macro_for(date_str: str) -> int:
            for b in mesocycles:
                if b['start_date'] <= date_str <= b['end_date']:
                    return b['macrocycle_id']
            return mesocycles[0]['macrocycle_id']

        for w in workouts:
            w['macrocycle_id'] = _macro_for(w['date'])

        # Chronological, because the preview is read as a plan and the model returns the
        # sessions in whatever order it wrote them.
        workouts.sort(key=lambda w: (w['date'], w.get('sport_type', '')))

        # The live plan this would displace, read here so the preview's warning and the
        # apply's teardown are the same set. Bounded at both ends: days past the span keep
        # the sessions they already have (§8).
        displaced = self._db.get_workouts(
            start_date=gen_start_str, end_date=gen_end_str, include_removed=True
        )
        voids = self._generate_voids(workouts, span_sessions, void_reasons)

        return GenerateProposal(
            reasoning=planner_reply.get("reasoning", "Plan generated."),
            workouts=tuple(workouts),
            displaced=tuple(displaced),
            gen_start=gen_start_str,
            gen_end=gen_end_str,
            # Checked against the range about to be WRITTEN, not the fetched set, which is
            # open-ended (DESIGN_constraint_honoring.md §2).
            covered_constraint_ids=honoring.covered_ids(
                constraints, gen_start_str, gen_end_str
            ),
            voids=voids,
            standing=self._standing_lines(workouts, standing_sessions, voids),
            athlete_note=athlete_note,
            commitment_end=window_end,
            **strength_planner.proposal_fields(strength),
        )

    def workout_generate_apply(
        self, proposal: GenerateProposal, verbose: bool = False
    ) -> List[Workout]:
        """Commits an accepted `workout generate` proposal: one change, then one reconcile.

        Every day the new sessions do not fill, *inside the generated span*, gets a void
        revision; every day it does fill gets a revision — unless the prescription is
        identical to what is already live, in which case §9 suppresses it and the day is
        left alone. A day the plan KEEPS is claimed but not written: it is spared the void
        and appends nothing, so the session and its Calendar event carry on untouched
        (§7.1). The voids go first, so a session the plan drops is ended before
        anything else can take its slot (§8). Calendar follows from the change handle's
        reconcile pass, so nothing here pushes.

        Which slots are voided and why was decided at proposal time, so the report the
        operator accepted and the write are the same set
        (DESIGN_plan_change_continuity.md §5.5). A session that takes another's place —
        a move, a sport change, a drop — carries that session's lineage, so the day keeps
        one Calendar event rather than losing one and gaining another (§4.5).

        The span is `gen_start`..`gen_end`, so sessions outside it survive a bounded
        regeneration untouched (DESIGN_cli_selectors.md §8).

        Returns the sessions the plan now holds in the slots it proposed.
        """
        summary = proposal.reasoning
        # The plan version governing the span's start — context for `workout batches`,
        # while each row keeps the per-date tag every scoping read uses (§3).
        span_macro = next(
            (w.get('macrocycle_id') for w in proposal.workouts
             if w.get('macrocycle_id') is not None), None
        )
        with (
            verbose_events() if verbose else nullcontext(),
            self._db.workout_change(
                kind="generate", summary=summary, macrocycle_id=span_macro,
                note=proposal.athlete_note,
                commitment_end=proposal.commitment_end,
            ) as change,
        ):
            span_sessions = self._db.get_workouts(
                start_date=proposal.gen_start, end_date=proposal.gen_end or None
            )
            for (day, sport_type, reason) in proposal.voids:
                change.void(date=day, sport_type=sport_type, reason=reason)
            # The flag belongs to the TEST, not to the slot: a rewrite of a benchmark's
            # slot that does not re-emit benchmark_type is an ordinary session, and the
            # carry-forward must not make it a test (DESIGN_benchmark_workouts.md §4.2,
            # as adapt already does).
            tested_slots = {
                (live['date'], canonical_sport(live['sport_type']))
                for live in span_sessions if live.get('benchmark_type')
            }
            for w in proposal.workouts:
                # Claimed above, so it escaped the void; writing it again would churn a
                # day that did not change (§7.1).
                if w.get('keep'):
                    continue
                # The intensity target the week planner stated while it still knew the intent
                # (DESIGN_intensity_distribution.md §9.8) — validated, never rescaled.
                zone_currency, zone_sec = intensity.parse_planned_zones(w)
                slot = (w['date'], canonical_sport(w['sport_type']))
                change.append(
                    date=w['date'],
                    sport_type=w['sport_type'],
                    title=w['title'],
                    description=w['description'],
                    duration_minutes=w.get('duration_minutes'),
                    rpe=w.get('rpe'),
                    tss=w.get('tss'),
                    # The coach's sentence to the athlete about this day, which is what
                    # puts it on the Calendar's `Reason:` line (§4.5).
                    reason=str(w.get('change_reason') or '').strip() or None,
                    benchmark_type=w.get('benchmark_type'),
                    clear_benchmark=bool(
                        slot in tested_slots and not w.get('benchmark_type')
                    ),
                    macrocycle_id=w.get('macrocycle_id'),
                    lineage_id=w.get('replaces_lineage'),
                    # The strength planner's exercises, written with the revision they
                    # belong to (DESIGN_strength_tracking.md §9).
                    prescribed_sets=w.get('prescribed_sets'),
                    planned_zone_currency=zone_currency,
                    planned_zone_sec=zone_sec,
                )

        # The same warrant every other constraint this run built around gets (§8).
        honoring.stamp(self._db, proposal.covered_constraint_ids)
        strength_planner.record_checks(self._db, proposal)

        # The sessions the plan now holds in the slots it proposed — which is not the same
        # as the revisions it appended, because §9 leaves an unchanged day alone.
        dates = [w['date'] for w in proposal.workouts]
        if not dates:
            return []
        live = self._db.get_workouts(start_date=min(dates), end_date=max(dates))
        by_slot = {(w['date'], canonical_sport(w['sport_type'])): w for w in live}
        return [by_slot[slot] for slot in
                ((w['date'], canonical_sport(w['sport_type'])) for w in proposal.workouts)
                if slot in by_slot]

    def workout_generate_strength(self, start_date: str, end_date: str) -> RevisionProposal:
        """`workout generate --strength-only`: the strength planner writes every strength
        session of the span again, and no other session changes. The week planner is not
        called (DESIGN_strength_tracking.md §9).

        Writes nothing: the proposal holds only the sessions whose sets changed, and
        `workout_revision_apply` writes them under a `generate` change, holding the other
        sessions of their dates."""
        today_str = _today_str()
        start = max(start_date, today_str)
        # Today's session already done is history, as in `workout_generate`.
        done_today = self._db.get_completed_activities(start_date=today_str, end_date=today_str)
        if start == today_str and self._today_workout_completed(today_str, done_today):
            start = (date.fromisoformat(today_str) + timedelta(days=1)).isoformat()
        span = self._db.get_workouts(start_date=start, end_date=end_date)
        strength = strength_planner.run(
            [], span, start, end_date, today_str, self._effective_profile(),
            self._db.get_constraints(start, end_date), reason_key='modification_reason',
            write_again=True,
        )
        written = list(strength.added) if strength else []
        held = self._hold_around(strength.held_dates, span) if strength else []
        reason = (
            f"I wrote {len(written)} of your strength sessions again, between "
            f"{fmt_date(start)} and {fmt_date(end_date)}."
        )
        if not written:
            reason = (
                f"Your strength sessions between {fmt_date(start)} and "
                f"{fmt_date(end_date)} stand as written."
            )
        # A session written with no sets before it has no sentence of its own.
        for row in written:
            if not row.get('modification_reason'):
                row['modification_reason'] = reason
        pairs, removals = pair_revisions(written, span, held)
        return RevisionProposal(
            reason=reason, workouts=written, range_start=start, range_end=end_date,
            kind="generate", pairs=pairs, removals=removals, held=tuple(held),
            **strength_planner.proposal_fields(strength),
        )
