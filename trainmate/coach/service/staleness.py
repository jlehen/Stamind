"""Has the plan been overtaken by its own inputs, and does that matter?

`plan_inputs.py` says what the inputs *are* and hashes them. This is the judgment on top:
which differences are worth telling the athlete about, how to show them the edit, what
the coach thinks it would have changed, and how to stop asking once they have answered.

It is one mixin of :class:`CoachService` — see coach/service/__init__.py. The wording the
athlete reads is `cli/staleness.py`; nothing here prints except the one aside for a
verdict call that could not be made.
"""
import hashlib
import json
from typing import Any, Dict, List, Optional

from trainmate import plan_inputs
from trainmate.config import config
from trainmate.output import aside
from trainmate.plan_inputs import (
    _SCIENCE_CHANGED, _profile_change_reason, _snapshot_profile,
    _snapshot_records, _snapshot_science, athlete_science_documents,
    changed_science_documents, plan_profile, profile_diff_text, records_diff_text,
    science_diff_text,
)
from trainmate.coach.proposals import PlanFingerprints
from trainmate.clock import today_str as _today_str


class StalenessMixin:
    def _get_config_snapshot(self) -> str:
        """JSON of the current effective threshold anchors, persisted on the macrocycle
        so config_changed() can judge later drift against real values."""
        return json.dumps(self.effective_thresholds(), sort_keys=True)

    def _get_profile_snapshot(self) -> str:
        """JSON of the current plan-shaping profile fields, persisted on the macrocycle so
        config_changed() can name which field moved (DESIGN_plan_staleness.md §5)."""
        return json.dumps(plan_profile(), sort_keys=True)

    def _get_science_snapshot(self) -> str:
        """JSON of the athlete's science documents, {filename: text}, persisted on the
        macrocycle so config_changed() can name the file that moved and show the edit
        (DESIGN_plan_staleness.md §11). The text itself, not a hash: the verdict call
        reads the diff, and the prompt already carries these files on every call."""
        return json.dumps(athlete_science_documents(), sort_keys=True)

    def _science_reasons(self, macro: Dict[str, Any]) -> List[str]:
        """Whether the athlete's science documents have moved since `macro` was
        generated (§11). A plan carrying no snapshot cannot be held to one."""
        old_docs = _snapshot_science(macro.get('science_snapshot'))
        if old_docs is None:
            return []
        changed = changed_science_documents(old_docs)
        if not changed:
            return []
        return [f"{_SCIENCE_CHANGED}: {', '.join(changed)}"]

    def _threshold_reasons(self, macro: Dict[str, Any]) -> List[str]:
        """Every threshold anchor that has drifted past `coach.threshold_replan_pct`
        since `macro` was generated — a small FTP/LTHR retest correction feeds the next
        workout generation without invalidating the periodization strategy (§3.3).

        Every anchor kind on record joins the snapshot uniformly (§3.5). A kind absent
        from the OLD snapshot is a *newly recorded* one, so it is skipped rather than read
        as instant drift; a kind that *disappears* is real drift. `e1rm` is the one
        exclusion: it collides across lifts, so a squat PR would invalidate a whole
        periodization (DESIGN_intensity_distribution.md §10). It still feeds the prompt,
        never a replan."""
        snapshot_raw = macro.get('config_snapshot')
        if not snapshot_raw:
            return []
        try:
            old_thresholds = json.loads(snapshot_raw)
        except (ValueError, TypeError):
            return []

        current = self.effective_thresholds()
        tolerance = config.threshold_replan_pct / 100.0
        reasons: List[str] = []
        for key in sorted(set(old_thresholds) | set(current)):
            if key == 'e1rm':
                continue
            old_val, new_val = old_thresholds.get(key), current.get(key)
            if old_val is None:
                continue  # newly recorded kind — joins drift-checking from the next plan
            if new_val is None:
                reasons.append(f"{key} was removed")
                continue
            if old_val and abs(new_val - old_val) / abs(old_val) > tolerance:
                pct = (new_val - old_val) / old_val * 100.0
                reasons.append(f"{key} changed {old_val:g} → {new_val:g} ({pct:+.1f}%)")
        return reasons

    def config_changed(self, macro: Dict[str, Any]) -> Optional[str]:
        """Whether a plan-shaping input has drifted since `macro` was generated.

        Returns a human-readable reason, or None when the plan is still current. Five
        axes: the fingerprint over plan-shaping profile fields (see `plan_inputs.plan_profile`),
        the effective threshold anchors, the goals, the `replan = 1` constraints, and the
        athlete's science documents (DESIGN_plan_staleness.md §11). A
        moved race date is the largest reshaper there is, and both it and the constraints
        were fingerprinted for `plan generate`'s strategy-reuse check alone
        (DESIGN_plan_change_continuity.md §6.5).

        EVERY reason is collected, not the first one found. Returning early let a profile
        edit swallow a concurrent threshold move: `plan show` named one of them, the
        verdict call never learned about the other, and `plan keep` stamped both away.
        """
        reasons: List[str] = []
        if macro.get('config_hash') != plan_inputs.plan_config_hash():
            reasons.append(_profile_change_reason(macro.get('profile_snapshot')))
        reasons.extend(self._threshold_reasons(macro))
        reasons.extend(self._plan_input_reasons(macro))
        reasons.extend(self._science_reasons(macro))
        return "; ".join(reasons) if reasons else None

    def _plan_input_reasons(self, macro: Dict[str, Any]) -> List[str]:
        """Whether the goals or the plan-shaping constraints have moved since `macro` was
        generated (DESIGN_plan_change_continuity.md §6.5).

        `all_constraints_snapshot` is deliberately not read here: it holds every active
        constraint, tactical ones included, and exists so `plan show` can list what the
        coach saw. Flagging on it would make the companion athlete's "not Wednesday next
        week" restage the operator's plan."""
        reasons: List[str] = []
        objectives = self._db.upcoming_objectives()
        # A hash the plan does not carry cannot be held to: there is nothing to compare
        # against, the same reading the profile snapshot gets above.
        stored_goals = macro.get('goals_hash')
        if stored_goals and stored_goals != plan_inputs.goals_hash(objectives):
            reasons.append("goals changed")
        replan_constraints = [
            c for c in self._db.get_constraints(_today_str())
            if c.get('replan')
        ]
        stored_constraints = macro.get('constraints_hash')
        if (stored_constraints and stored_constraints
                != plan_inputs.constraints_hash(replan_constraints)):
            reasons.append("plan-shaping constraints changed")
        return reasons

    def profile_diff(self, macro: Dict[str, Any]) -> str:
        """What actually changed in the plan-shaping profile since `macro` was generated,
        as a unified diff — or "" when the drift is elsewhere (thresholds, whose reason
        already carries the numbers) or the plan predates the snapshot (§10)."""
        if macro.get('config_hash') == plan_inputs.plan_config_hash():
            return ""
        old_profile = _snapshot_profile(macro.get('profile_snapshot'))
        return profile_diff_text(old_profile) if old_profile is not None else ""

    def staleness_diff(self, macro: Dict[str, Any]) -> str:
        """Every edit the staleness reason names, as diffs the athlete can judge: the
        profile fields, the goals, the plan-shaping constraints
        (DESIGN_plan_change_continuity.md §6.5) and the athlete's science documents
        (DESIGN_plan_staleness.md §11).

        A snapshot the plan does not carry contributes nothing — it cannot be attributed
        honestly — and the threshold reasons already carry their own numbers."""
        chunks = [self.profile_diff(macro)]

        old_goals = _snapshot_records(macro.get('goals_snapshot'))
        if old_goals is not None:
            chunks.append(records_diff_text(
                old_goals, plan_inputs.clean_goals(self._db.upcoming_objectives()),
                "goals",
            ))

        old_constraints = _snapshot_records(macro.get('constraints_snapshot'))
        if old_constraints is not None:
            replan = [
                c for c in self._db.get_constraints(_today_str())
                if c.get('replan')
            ]
            chunks.append(records_diff_text(
                old_constraints, plan_inputs.clean_constraints(replan),
                "plan-shaping constraints",
            ))

        old_docs = _snapshot_science(macro.get('science_snapshot'))
        if old_docs is not None:
            chunks.append(science_diff_text(old_docs))
        return "\n\n".join(chunk for chunk in chunks if chunk)

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

    def plan_reshape_verdict(
        self, macro: Dict[str, Any], change_reason: str,
    ) -> Optional[Dict[str, Any]]:
        """The verdict call's read on whether `change_reason` would have reshaped `macro`:
        {"reshaping": bool, "why": str}, or None when no verdict could be had. Fails open
        on purpose — the staleness question must never hang on the network, so any error
        or malformed reply leaves the athlete with the question and no verdict
        (DESIGN_plan_staleness.md §10)."""
        from trainmate.openrouter import openrouter_client
        if openrouter_client.show_prompt_only:
            # That flag shows the command's own prompt; this preliminary would print
            # its prompt instead and exit before the one being asked for.
            return None
        try:
            verdict = self.engine._plan_reshape_verdict(
                change_reason, self.staleness_diff(macro), macro.get('strategy') or "",
                self._db.get_mesocycles_for_macrocycle(macro['id']),
            )
        except Exception as e:
            aside(f"Could not get the coach's read on this change: {e}")
            return None
        reshaping = verdict.get('reshaping') if isinstance(verdict, dict) else None
        if not isinstance(reshaping, bool):
            return None
        return {'reshaping': reshaping, 'why': str(verdict.get('why') or "").strip()}

    def plan_fingerprints(
        self, objectives: List[Dict[str, Any]], constraints: List[Dict[str, Any]]
    ) -> PlanFingerprints:
        """The inputs a strategy is being generated against, hashed and snapshotted.

        The one builder. `plan generate` stamps these onto the proposal and `plan apply`
        persists them verbatim; re-deriving them at accept time is what let an edit
        between the two be recorded as if the strategy had seen it (coach/proposals.py).
        `plan keep` builds the same set to say "the plan has seen this now".

        `constraints` is every active constraint. Only the plan-shaping (`replan = 1`)
        ones are fingerprinted and snapshotted, so a tactical "no run Thursday" never
        trips the reuse-vs-regenerate decision (DESIGN_constraints.md §7); the full list
        is snapshotted separately, for display only.
        """
        replan = [c for c in constraints if c.get('replan')]
        return PlanFingerprints(
            goals_hash=plan_inputs.goals_hash(objectives),
            constraints_hash=plan_inputs.constraints_hash(replan),
            config_hash=plan_inputs.plan_config_hash(),
            config_snapshot=self._get_config_snapshot(),
            profile_snapshot=self._get_profile_snapshot(),
            goals_snapshot=json.dumps(plan_inputs.clean_goals(objectives)),
            constraints_snapshot=json.dumps(plan_inputs.clean_constraints(replan)),
            all_constraints_snapshot=json.dumps(
                plan_inputs.clean_constraints_all(constraints)
            ),
            science_snapshot=self._get_science_snapshot(),
        )

    def stamp(self, macro: dict) -> None:
        """Records the current inputs against `macro`, so the change stops being flagged.

        Every axis `config_changed` reads, or a plan kept today flags again tomorrow
        (DESIGN_plan_change_continuity.md §6.5). It builds the same fingerprint set
        `plan generate` does, rather than a second hand-written copy of it.

        All but one field is written. `all_constraints_snapshot` is the list of
        constraints the strategy was shown, and keeping a plan does not rewrite its
        strategy — so refreshing that list would have `plan show` claim the coach
        considered a constraint added after it wrote the words."""
        constraints = self._db.get_constraints(_today_str())
        prints = self.plan_fingerprints(self._db.upcoming_objectives(), constraints)
        self._db.update_macrocycle_config_hash(
            macro['id'],
            prints.config_hash,
            prints.config_snapshot,
            prints.profile_snapshot,
            goals_hash=prints.goals_hash,
            goals_snapshot=prints.goals_snapshot,
            constraints_hash=prints.constraints_hash,
            constraints_snapshot=prints.constraints_snapshot,
            science_snapshot=prints.science_snapshot,
        )

    def _verdict_key(self, macro: dict, change_reason: str) -> str:
        """What a cached verdict was asked about: the edit itself, not the plan. Two runs
        over one unchanged edit ask once (DESIGN_plan_change_continuity.md §7)."""
        diff = self.staleness_diff(macro)
        return hashlib.sha256(f"{change_reason}\n{diff}".encode()).hexdigest()[:16]

    def cached_verdict(self, macro: dict, change_reason: str) -> Optional[Dict[str, Any]]:
        """The verdict call's read on this edit, asked once and cached against it (§7).

        Fails open exactly as the uncached call does: a network error leaves the caller with
        the question and no verdict, and nothing is cached, so the next run asks again."""
        key = self._verdict_key(macro, change_reason)
        if macro.get('reshape_verdict_key') == key:
            try:
                cached = json.loads(macro.get('reshape_verdict') or "")
            except (ValueError, TypeError):
                cached = None
            if isinstance(cached, dict) and isinstance(cached.get('reshaping'), bool):
                return cached
        verdict = self.plan_reshape_verdict(macro, change_reason)
        # Anything but the shape the caller renders is "no verdict": nothing is cached, so
        # the next run asks again rather than serving a malformed reply forever.
        if not isinstance(verdict, dict) or not isinstance(verdict.get('reshaping'), bool):
            return None
        self._db.save_reshape_verdict(macro['id'], key, json.dumps(verdict))
        return verdict
