from datetime import datetime, timedelta
from typing import Any, List, Optional, Tuple, Dict
from trainmate.config import config
from trainmate.types import Workout
from trainmate.coach.proposals import PlanFingerprints, PlanProposal
from trainmate.analytics.load import planned_load
from trainmate.sports import canonical_sport
from trainmate import signals
from trainmate.db.periodization import repair_mesocycle_contiguity
from trainmate.text import cyan, default_wrap_width, wrap_text
from trainmate.output import notice, step
import trainmate.coach.service as _svc


class PlanningMixin:
    """Part of :class:`CoachService` — see coach/service/__init__.py."""

    def plan_rm(self, objective_id: int) -> None:
        """Deletes the periodization plan for a specific objective."""
        self._db.delete_macrocycle_for_objective(objective_id)

    def _objective_macrocycle_ids(self, objective_id: int) -> List[int]:
        """Every plan version the goal owns, active and superseded alike.

        Archival works off all of them because a superseded version can still own live
        sessions (DESIGN_backward_evaluation.md §14)."""
        return [m['id'] for m in self._db.get_macrocycle_versions(objective_id)]

    def goal_archive(self, objective_id: int) -> Dict[str, Any]:
        """Stands the goal's future sessions down and clears them from Calendar.

        One void per live session the goal's plan versions own, from today on, under one
        `stand-down` change — the same row-level `macrocycle_id` scoping that spares a
        neighbouring goal (DESIGN_workout_revisions.md §10). The plan, its versions and its
        feedback are untouched: calling a goal off hides it from planning but must not
        destroy its history (DESIGN_backward_evaluation.md §14). Past sessions stay put —
        a called-off race does not un-train the work already done.

        Returns {archived_workouts, untagged, first_date, last_date}."""
        today_str = _svc._today_str()
        sessions = self._db.live_workouts_for_macrocycles(
            self._objective_macrocycle_ids(objective_id), today_str
        )
        if sessions:
            with self._db.workout_change(
                kind="stand-down", summary="Goal called off."
            ) as change:
                for w in sessions:
                    change.void(
                        date=w['date'], sport_type=w['sport_type'],
                        reason="Goal called off",
                    )
        return {
            'archived_workouts': len(sessions),
            'untagged': self._db.count_untagged_future_workouts(today_str),
            'first_date': min((w['date'] for w in sessions), default=None),
            'last_date': max((w['date'] for w in sessions), default=None),
        }

    def goal_reinstate(self, objective_id: int) -> Dict[str, Any]:
        """Brings back the sessions `goal_archive` stood down, and re-pushes them.

        The mirror of `goal_archive` (DESIGN_backward_evaluation.md §14), read off the live
        view: every lineage still showing a `stand-down` void gets a copy of the revision
        that void ended, floored at today, so a goal reinstated months later recovers only
        the sessions still ahead. A slot regenerated or edited since no longer has that
        void live and is left alone — something else owns it now
        (DESIGN_workout_revisions.md §10).

        Returns {restored_workouts, unhonored, first_date, last_date}."""
        today_str = _svc._today_str()
        stood_down = self._db.stood_down_sessions(
            self._objective_macrocycle_ids(objective_id), today_str
        )
        if not stood_down:
            return {
                'restored_workouts': 0, 'unhonored': [],
                'first_date': None, 'last_date': None,
            }
        with self._db.workout_change(
            kind="reinstate", summary="Goal reinstated."
        ) as change:
            for revision in stood_down:
                change.restore(revision)
            appended = list(change.appended)
        restored = self._db.hydrate_revisions(appended)
        # As in `plan rollback` (§8): the restored sessions predate any honoring made
        # while the goal was stood down, so they cannot reflect it.
        unhonored = self._db.clear_honored_after(
            max(r['stood_down_at'] for r in stood_down), today_str
        )
        return {
            'restored_workouts': len(restored),
            'unhonored': unhonored,
            'first_date': min((w['date'] for w in restored), default=None),
            'last_date': max((w['date'] for w in restored), default=None),
        }

    def constraint_plan_impact(self, constraint: Dict[str, Any]) -> Dict[str, Any]:
        """Magnitude of a directive against the active plan (DESIGN_constraints.md §7,
        concrete formula): the planned load it displaces, expressed as a percentage of the
        plan's trailing weekly planned load (a self-scaling ratio — no absolute TSS number
        rots as the athlete's fitness changes), plus its span in days. The trailing week is
        the 7 days immediately before the constraint's start, so the reference point isn't
        itself affected by the constraint being evaluated. Feeds the human-confirmed replan
        proposal only — never an automatic regen."""
        start, end = constraint['start_date'], constraint['end_date']
        window_start = max(start, _svc._today_str())
        rest = canonical_sport('rest')

        def _load(w_start: str, w_end: str) -> float:
            sessions = [
                w for w in self._db.get_workouts(start_date=w_start, end_date=w_end)
                if canonical_sport(w.get('sport_type', '')) != rest
            ]
            return sum(planned_load(w) for w in sessions)

        displaced_load = _load(window_start, end)
        days = (datetime.strptime(end, "%Y-%m-%d").date()
                - datetime.strptime(start, "%Y-%m-%d").date()).days + 1

        trailing_end_date = datetime.strptime(start, "%Y-%m-%d").date() - timedelta(days=1)
        trailing_start_date = trailing_end_date - timedelta(days=6)
        trailing_weekly_load = _load(
            trailing_start_date.strftime("%Y-%m-%d"), trailing_end_date.strftime("%Y-%m-%d")
        )
        displaced_pct = (
            (displaced_load / trailing_weekly_load * 100) if trailing_weekly_load > 0 else 0.0
        )
        return {
            'days': days,
            'displaced_load': displaced_load,
            'trailing_weekly_load': trailing_weekly_load,
            'displaced_pct': displaced_pct,
        }

    def capture_message_constraint(
        self, candidate: Dict[str, Any], default_date_str: str
    ) -> Tuple[Optional[int], Optional[Dict[str, Any]]]:
        """Creates one durable constraint from a `new_constraints` candidate the CLI has
        already confirmed with the athlete (DESIGN_constraints.md §8 two-confirmation
        flow, step 1). Always `source='message'`, always advisory (`rest=0`) — the LLM can
        never mark an extracted constraint as a deterministic rest window (trust boundary
        §8); a genuine rest escalation is a deliberate human action (`constraint edit <id>
        --rest`). Never sets `replan=1` either — a large capture only *surfaces a
        suggestion* to escalate, which the human acts on separately.

        Returns the new constraint's id, and its impact when that impact makes it
        plan-shaping. The caller renders the escalation: the words differ by persona,
        and choosing them is not the service's job (DESIGN_bot_simple_frontend.md
        §12.10)."""
        title = (candidate.get('title') or '').strip()
        if not title:
            return None, None
        start = candidate.get('start_date') or default_date_str
        end = candidate.get('end_date') or start
        if end < start:
            end = start
        cid = self._db.add_constraint(
            title=title, start_date=start, end_date=end, rest=0,
            description=candidate.get('description'), replan=0, source='message',
        )
        constraint = self._db.get_constraint(cid)
        impact = self.constraint_plan_impact(constraint)
        if not self.constraint_is_plan_shaping(constraint, impact):
            return cid, None
        return cid, impact

    def known_signal_metrics(self) -> List[str]:
        """`signals.known_metrics` for this instance's config and history (§5)."""
        return signals.known_metrics(signals.signal_metrics(), self._db.list_signal_metrics())

    def capture_message_signal(
        self, candidate: Dict[str, Any], default_date_str: str,
        metric_override: Optional[str] = None
    ) -> List[dict]:
        """Creates the daily-signal rows for one `new_signals` candidate the CLI has
        already confirmed with the athlete (DESIGN_signal_extraction.md §2).

        `metric_override` is the category the athlete settled on, which may differ from the
        one the model proposed (§6). A `value` that is not a number is dropped rather than
        coerced: the model may only pass through a number the note stated, and a fabricated
        one would enter the quantitative path as a measurement (§3).
        """
        metric = signals.normalize_metric(metric_override or candidate.get("metric"))
        if not metric:
            return []
        start = candidate.get("date") or default_date_str
        end = candidate.get("end_date") or start
        if end < start:
            end = start
        value = candidate.get("value")
        if isinstance(value, bool) or not isinstance(value, (int, float)):
            value = None
        text = signals.signal_summary(metric, value, str(candidate.get("text") or "").strip())
        return signals.write_signal_days(start, end, metric, value, text)

    @staticmethod
    def constraint_is_plan_shaping(
        constraint: Dict[str, Any], impact: Dict[str, Any]
    ) -> bool:
        """Concrete §7 magnitude heuristic for whether to *propose* a replan. Two
        independent triggers, either firing proposes a replan; deliberately no
        per-session "importance" term (TrainMate has no priority field at all):

        1. Displaced-load trigger (relative): the constraint's overlapping planned load
           is >= config.replan_displaced_load_pct of the plan's trailing weekly planned
           load (default 50 — wipes out at least half a typical week).
        2. Rest-window floor: the constraint is a `rest` window spanning >= config.
           replan_rest_span_days days (default 3), regardless of load overlap (it may
           land in a light taper week yet still reshape everything after it).
        """
        if impact['displaced_pct'] >= config.replan_displaced_load_pct:
            return True
        if (
            constraint.get('rest')
            and impact['days'] >= config.replan_rest_span_days
        ):
            return True
        return False

    def _changed_inputs_text(
        self, macro: Optional[Dict[str, Any]]
    ) -> Optional[str]:
        """The staleness reason and its diff for the plan being replaced, or None when
        there is no plan, or it was current (DESIGN_plan_change_continuity.md §6.2)."""
        if not macro:
            return None
        change_reason = self.config_changed(macro)
        if not change_reason:
            return None
        diff = self.staleness_diff(macro)
        return f"{change_reason}\n\n{diff}" if diff else change_reason

    def plan_generate(
        self, force: bool = False, objective_id: Optional[int] = None,
        auto_apply: bool = True, fresh: bool = False, start_date: Optional[str] = None,
        show_context: bool = False
    ) -> PlanProposal:
        """Determines the macrocycle strategy and mesocycles.

        With `auto_apply` the proposal is saved before returning; otherwise the caller
        hands it back to :meth:`plan_apply` once the athlete accepts it.

        `start_date` is the caller's own bound on where the plan window opens, which is
        how `plan generate -g N` plans N's OWN span rather than everything from today
        (DESIGN_cli_selectors.md §9). Never earlier than today.

        `fresh` withholds the plan in place from the prompt, so the new strategy is not
        asked to continue it — a clean slate, not a revision. It implies `force`: there is
        nothing to reuse when the point is to depart. What the athlete *did* still feeds in
        (the planned-vs-actual review, the history summary, the learnings, their feedback);
        only the old plan's stated intent is withheld.

        `show_context` echoes the prompt's planned-vs-actual review to the screen. Off by
        default: it is the longest thing this command prints and it pushes the strategy
        the athlete asked for below the fold (DESIGN_output_verbosity.md §7)."""
        force = force or fresh
        # Identify the target goal
        if objective_id is not None:
            next_goal = self._db.get_active_objective(objective_id)
            if not next_goal:
                next_goal = self._db.get_objective(objective_id)
                if not next_goal:
                    raise ValueError(f"Goal with ID {objective_id} not found.")
        else:
            next_goal = self._db.get_active_objective()
            if not next_goal:
                # `goal: None` is the caller's signal that there was nothing to plan
                # for, and `strategy` carries the reason rather than a strategy.
                return {
                    'strategy': (
                        "No active goals found. TrainMate needs at least one objective."
                    ),
                    'mesocycles': [], 'reused': False, 'goal': None,
                    'prior_training_review': None, 'has_prior_training': False,
                }

        # Compute plan-window dates (constraints are fetched below with the hashes).
        today_str = _svc._today_str()
        today_date = datetime.strptime(today_str, "%Y-%m-%d").date()

        # Determine plan start date based on preceding goals with plans
        plan_start_date = today_date
        preceding_objs = self._db.get_preceding_objectives(next_goal['target_date'])

        latest_preceding_target = None
        # Kept in its own name: `prev_macro` below is whichever plan the new one *replaces*,
        # which on a re-plan is this goal's own — not the preceding goal's season, which the
        # review still needs (DESIGN_backward_evaluation.md §6.1).
        preceding_macro = None

        for po in preceding_objs:
            if po['id'] is not None:
                po_macro = self._db.get_macrocycle_for_objective(po['id'])
                if po_macro:
                    po_target = datetime.strptime(po['target_date'], "%Y-%m-%d").date()
                    latest_preceding_target = po_target
                    preceding_macro = po_macro
                    break

        if latest_preceding_target is not None:
            plan_start_date = latest_preceding_target + timedelta(days=1)
            if plan_start_date < today_date:
                plan_start_date = today_date

        # A named goal bounds its own span, so the caller's start wins over the
        # derivation above (DESIGN_cli_selectors.md §9). Transitional: the two readings
        # differ only when the days before this goal were about to be swallowed into its
        # plan, so that is the only time it is worth a word.
        if start_date is not None:
            requested = max(
                datetime.strptime(start_date, "%Y-%m-%d").date(), today_date
            )
            if requested != plan_start_date:
                notice(
                    "Note: -g now plans this goal's own span. This plan starts on "
                    f"{requested.strftime('%Y-%m-%d')} — the day after the goal before "
                    f"it. It used to start on {plan_start_date.strftime('%Y-%m-%d')}, "
                    "swallowing that earlier goal's days into this plan. Plan that goal "
                    "separately to cover them.",
                )
                print()
            plan_start_date = requested

        # The plan window. There is no lower or upper bound on how long it may be: how a
        # three-week run-in or a two-year horizon should be periodized is a question the
        # science guidelines answer, not one the app pre-empts with a threshold. The only
        # requirement is that the window exists.
        plan_start_str = plan_start_date.strftime("%Y-%m-%d")
        target_date = datetime.strptime(next_goal['target_date'], "%Y-%m-%d").date()
        if target_date <= plan_start_date:
            raise ValueError(
                f"Goal '{next_goal['title']}' is dated {next_goal['target_date']}, on or "
                f"before the plan start {plan_start_str} — there is no window to plan in."
            )

        # Compute current hashes
        # We need to fetch active objectives for hash computation so the hash covers the whole landscape
        objectives = self._db.upcoming_objectives()
        constraints = self._db.get_constraints(today_str)
        # Fingerprint the inputs the strategy is about to be generated against, and carry
        # them to `plan_apply` verbatim. Re-deriving at accept time meant an edit made
        # between generating and accepting was recorded as if the strategy had seen it,
        # which silently defeats the staleness detector (see coach/proposals.py).
        fingerprints = self.plan_fingerprints(objectives, constraints)

        # Try to retrieve existing macrocycle
        strategy = ""
        mesocycles: List[Dict[str, Any]] = []
        existing_macro = None
        if next_goal['id'] is not None:
            existing_macro = self._db.get_macrocycle_for_objective(next_goal['id'])

        # Notes the athlete left against the plan in place. They are plan inputs, so
        # their presence is one more disjunct in the staleness test below — feedback
        # applies without --force (DESIGN_plan_feedback.md §7).
        pending_feedback = (
            self._db.list_plan_feedback(existing_macro['id']) if existing_macro else []
        )

        reused = False
        prior_training_review = None
        has_prior_training = False
        if existing_macro and not force and not pending_feedback:
            if (
                existing_macro['goals_hash'] == fingerprints.goals_hash
                and existing_macro['constraints_hash'] == fingerprints.constraints_hash
                and self.config_changed(existing_macro) is None
            ):
                reused = True
                strategy = existing_macro['strategy']
                mesocycles = self._db.get_mesocycles_for_macrocycle(existing_macro['id'])
                step(wrap_text(
                    "Reusing existing periodization strategy (macrocycle and mesocycles) "
                    "from database."
                ), cyan)

        if not reused:
            # The plan being replaced, for the "PREVIOUS PERIODIZATION STRATEGY" section —
            # deliberately singular, since that section is about the intent this one departs
            # from. The *review* below sees both (§6.1).
            prev_macro = existing_macro or preceding_macro

            # `fresh` withholds only this mesocycle: `prev_macro` still reaches the
            # planned-vs-actual review below, which is what the athlete trained, not the
            # intent they are departing from.
            previous_plan = None
            if prev_macro and not fresh:
                previous_plan = (
                    prev_macro['strategy'],
                    self._db.get_mesocycles_for_macrocycle(prev_macro['id']),
                )

            # The mesocycle the athlete is mid-way through, offered so the new plan may let it
            # finish rather than cutting it at today (DESIGN_mesocycle_progress.md §7). Gated on
            # the plan starting today: a start pinned after a preceding goal's target must
            # not be reached back past, or the kept mesocycle would overlap that goal's season.
            current_mesocycle = None
            if existing_macro and not fresh and plan_start_date == today_date:
                covering = self._db.get_covering_mesocycle(today_str)
                if (
                    covering
                    and covering['macrocycle_id'] == existing_macro['id']
                    and covering['start_date'] < today_str
                ):
                    current_mesocycle = covering

            # The pending log, verbatim and oldest first, so a later note reads as an
            # amendment of an earlier one. Filed notes carry the phase NAME: names
            # survive version churn, IDs do not (DESIGN_plan_feedback.md §7).
            feedback_text = "\n".join(
                f"- [{str(n['created_at'])[:10]}]"
                + (f" (phase: {n['mesocycle_name']})" if n.get('mesocycle_name') else "")
                + f" \"{n['text']}\""
                for n in pending_feedback
            ) or None

            # Generate new macrocycle strategy and mesocycles
            width = default_wrap_width()
            if fresh:
                step(wrap_text(
                    "Clean slate: the plan in place is withheld from the prompt, so the "
                    "new strategy is not asked to continue it. Your training history, the "
                    "planned-vs-actual review and your plan feedback still feed in."
                ), cyan)
            else:
                step(wrap_text(
                    "Goals or plan-shaping constraints have changed, or force generation "
                    "requested. Determining new overall periodization strategy..."
                ), cyan)
            guidelines = self._load_science_guidelines()
            profile = self._effective_profile()
            history_summary = self._get_recent_history_summary(today_str)
            # Read-only here, as everywhere outside the analysis flow
            # (DESIGN_backward_evaluation.md §10.1).
            learnings = self._get_learnings_text()
            # Planned-vs-actual review of every plan the athlete has trained through (+ the
            # cached reconstructions) fed as read-only context (Option A).
            prior_training_text = self._build_prior_training_context(
                [preceding_macro, prev_macro], today_str
            )
            has_prior_training = bool(prior_training_text)
            if prior_training_text and show_context:
                # Rebuilt at the caller's own width rather than re-wrapping the prompt
                # copy: the zone tables are column-aligned, so re-wrapping them (as
                # opposed to re-laying them out at the target width) shreds the columns
                # instead of fitting them (DESIGN_intensity_distribution.md §6). Built
                # only when it will be shown — off the flag it is a second full pass
                # over the same plans for nothing (DESIGN_output_verbosity.md §7).
                prior_training_review = self._build_prior_training_context(
                    [preceding_macro, prev_macro], today_str, width=width,
                )
            self._maybe_warn_stale_analysis(today_str)
            macro_data = self.engine._plan_generate_strategy(
                next_goal=next_goal,
                objectives=objectives,
                constraints=constraints,
                today_str=today_str,
                guidelines=guidelines,
                profile=profile,
                previous_plan=previous_plan,
                plan_start_str=plan_start_str,
                athlete_feedback=feedback_text,
                history_summary=history_summary,
                prior_training_text=prior_training_text,
                learnings=learnings,
                current_mesocycle=current_mesocycle,
                changed_inputs=self._changed_inputs_text(prev_macro),
                anchor_history=self._anchor_history_text(plan_start_str),
            )
            strategy = macro_data.get("strategy", "Endurance preparation strategy.")
            mesocycles = macro_data.get("mesocycles", [])

            if auto_apply:
                self.plan_apply(
                    next_goal['id'], strategy, mesocycles, fingerprints=fingerprints
                )

        self._maybe_nudge_bootstrap()
        return {
            'strategy': strategy, 'mesocycles': mesocycles, 'reused': reused,
            'goal': next_goal, 'fingerprints': fingerprints,
            # What the caller may show: the planned-vs-actual review laid out at its
            # width when it asked for it, and whether one fed the prompt at all — the
            # flag that would reveal it is the CLI's, so the offer to pass it is too.
            'prior_training_review': prior_training_review,
            'has_prior_training': has_prior_training,
        }

    def plan_apply(
        self, objective_id: Optional[int], strategy: str, mesocycles: List[Dict[str, Any]],
        fingerprints: Optional[PlanFingerprints] = None
    ) -> Optional[int]:
        """Saves a generated periodization plan to the database, and returns the id of the
        goal it was saved under.

        `fingerprints` are the ones computed when the strategy was generated. Pass them:
        recomputing here reads whatever the database holds at accept time, so a goal
        edited between generating and accepting is fingerprinted as though the strategy
        had been built from it. They are optional only for callers that apply a plan
        they did not just generate.
        """
        if objective_id is None:
            return None

        # Repair within-plan gaps/overlaps here, where the note can reach the user; the
        # write boundary re-applies the same repair as a no-op (DOMAIN_MODEL.md §4).
        mesocycles, repair_notes = repair_mesocycle_contiguity(mesocycles)
        for note in repair_notes:
            notice(f"Note: mesocycle dates repaired — {note}.")

        if fingerprints is None:
            fingerprints = self.plan_fingerprints(
                self._db.upcoming_objectives(),
                self._db.get_constraints(_svc._today_str()),
            )

        self._db.save_macrocycle(
            objective_id=objective_id,
            strategy=strategy,
            goals_hash=fingerprints.goals_hash,
            constraints_hash=fingerprints.constraints_hash,
            config_hash=fingerprints.config_hash,
            config_snapshot=fingerprints.config_snapshot,
            profile_snapshot=fingerprints.profile_snapshot,
            goals_snapshot=fingerprints.goals_snapshot,
            constraints_snapshot=fingerprints.constraints_snapshot,
            all_constraints_snapshot=fingerprints.all_constraints_snapshot,
            science_snapshot=fingerprints.science_snapshot,
            mesocycles=mesocycles
        )
        return objective_id

    def plan_rollback(
        self, objective_id: Optional[int] = None, target_macrocycle_id: Optional[int] = None
    ) -> Dict[str, Any]:
        """Restores an earlier periodization plan version and its workouts.

        Swaps the active macrocycle for `objective_id` (defaults to the next active goal)
        back to a superseded version — the chronologically previous one by default, or
        `target_macrocycle_id` when given — then puts the workouts back the way they were
        the moment just after that version last wrote, Calendar included (see
        DESIGN_plan_rollback.md, DESIGN_workout_revisions.md §10).

        Returns a summary dict: {objective, from, to, restored_workouts, unhonored}.
        Raises ValueError when there is nothing to roll back to.
        """
        if objective_id is not None:
            objective = self._db.get_objective(objective_id)
        else:
            objective = self._db.get_active_objective()
        if not objective:
            raise ValueError("No goal found to roll back.")

        current = self._db.get_macrocycle_for_objective(objective['id'])
        if not current:
            raise ValueError(
                f"Goal '{objective['title']}' has no active plan to roll back."
            )

        if target_macrocycle_id is not None:
            target = self._db.get_macrocycle(target_macrocycle_id)
            if not target or target.get('objective_id') != objective['id']:
                raise ValueError(
                    f"Plan version {target_macrocycle_id} does not belong to goal "
                    f"'{objective['title']}'."
                )
            if target_macrocycle_id == current['id']:
                raise ValueError("That plan version is already active.")
        else:
            target = self._db.get_previous_macrocycle_version(objective['id'])
            if not target:
                raise ValueError(
                    f"Goal '{objective['title']}' has no earlier plan version to roll "
                    "back to."
                )

        today_str = _svc._today_str()

        # 1. Flip the active version so date->plan lookups resolve to the restored plan.
        self._db.set_active_macrocycle(target['id'])

        # 2. Undo every workout change made after the restored version's newest one. The
        # restore is point-in-time and UNSCOPED, exactly the `workout rollback` primitive:
        # restoring the whole moment is what keeps one session from being live twice
        # (DESIGN_workout_revisions.md §10).
        restored: List[Workout] = []
        unhonored: List[Dict[str, Any]] = []
        newest = self._db.newest_change_for_macrocycles([target['id']])
        undo_from = self._db.next_change_after(newest) if newest is not None else None
        if undo_from is not None:
            restored, unhonored = self._db.rollback_to_change(
                undo_from, today_str,
                summary=f"Rolled the plan back to version {target['id']}.",
            )

        return {
            'objective': objective,
            'from': current,
            'to': target,
            'restored_workouts': len(restored),
            # As in `workout rollback` (§8).
            'unhonored': unhonored,
        }

    def replan(
        self, force: bool = False, objective_id: Optional[int] = None
    ) -> Tuple[str, List[Workout]]:
        """Runs `plan generate`, then `workout generate`, from today onwards.

        Unattended by design — it applies the generated workouts without a preview, unlike
        the CLI's `workout generate`, which shows them and asks."""
        objectives = self._db.upcoming_objectives()
        if not objectives:
            return (
                "No active goals found. TrainMate needs at least one objective to "
                "start planning.",
                []
            )

        # Workouts follow the mesocycles covering the days they land on, so the plan just
        # saved needs no naming here — it is the newest, and therefore wins any overlap
        # with an older goal's plan. Named explicitly all the same, so an explicit replan
        # of one goal still settles that contest its way (DESIGN_cli_selectors.md §8).
        proposal = self.plan_generate(force=force, objective_id=objective_id)
        planned_goal = proposal['goal']
        macro = (
            self._db.get_macrocycle_for_objective(planned_goal['id'])
            if planned_goal else None
        )
        generated = self.workout_generate(
            prefer_macro_id=macro['id'] if macro else None
        )
        if not generated.workouts:
            return generated.reasoning, []
        return generated.reasoning, self.workout_generate_apply(generated)
