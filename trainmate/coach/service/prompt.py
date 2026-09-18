import difflib
import json
from datetime import datetime
from typing import Any, List, Optional, Tuple, Dict
from trainmate import learning_doubts, runtime
from trainmate.config import (
    athlete_science_documents, changed_plan_profile_fields, changed_science_documents,
    config, plan_profile, plan_shaping,
)
from trainmate.types import Objective, Constraint
from trainmate.util import cmd, notice
from trainmate.coach.formatting import _load_science_guidelines
from trainmate.coach.proposals import CoachContext
import trainmate.coach.service as _svc


_PROFILE_CHANGED = "athlete profile changed"
_SCIENCE_CHANGED = "training guidelines changed"


def _profile_change_reason(snapshot_raw: Optional[str]) -> str:
    """Why the profile fingerprint no longer matches, naming the fields when the plan
    carries a snapshot to compare against (DESIGN_plan_staleness.md §5).

    Falls back to the bare reason for a plan generated before the snapshot column, and for
    the one-off mismatch every pre-existing plan sees when the plan-shaping partition
    itself changes (§7) — in both cases the fields cannot be attributed honestly."""
    old_profile = _snapshot_profile(snapshot_raw)
    if old_profile is None:
        return _PROFILE_CHANGED
    fields = changed_plan_profile_fields(old_profile)
    return f"{_PROFILE_CHANGED}: {', '.join(fields)}" if fields else _PROFILE_CHANGED


def _snapshot_profile(snapshot_raw: Optional[str]) -> Optional[Dict[str, Any]]:
    """The plan-time profile a macrocycle carries, or None when it has none it can be
    held to (pre-snapshot plan, or a snapshot that does not parse)."""
    if not snapshot_raw:
        return None
    try:
        old_profile = json.loads(snapshot_raw)
    except (ValueError, TypeError):
        return None
    return old_profile if isinstance(old_profile, dict) else None


def _snapshot_science(snapshot_raw: Optional[str]) -> Optional[Dict[str, str]]:
    """The athlete's science documents as the plan saw them, {filename: text}, or None
    when the plan carries none it can be held to (DESIGN_plan_staleness.md §11)."""
    if not snapshot_raw:
        return None
    try:
        docs = json.loads(snapshot_raw)
    except (ValueError, TypeError):
        return None
    if not isinstance(docs, dict):
        return None
    return docs if all(isinstance(v, str) for v in docs.values()) else None


def _profile_field_lines(value: Any) -> List[str]:
    """One field as lines a diff can work on: prose stays prose, structure becomes
    sorted JSON so a reordered dict does not read as a change."""
    if value is None:
        return []
    if isinstance(value, str):
        return value.splitlines()
    return json.dumps(value, indent=2, sort_keys=True, ensure_ascii=False).splitlines()


def _snapshot_records(snapshot_raw: Optional[str]) -> Optional[List[Dict[str, Any]]]:
    """The goal or constraint list a macrocycle carries, or None when it has none it can
    be held to (DESIGN_plan_change_continuity.md §6.5)."""
    if not snapshot_raw:
        return None
    try:
        records = json.loads(snapshot_raw)
    except (ValueError, TypeError):
        return None
    return records if isinstance(records, list) else None


def records_diff_text(
    old_records: List[Dict[str, Any]], new_records: List[Dict[str, Any]], label: str
) -> str:
    """A unified diff of two cleaned record lists, so a moved race date reads as the edit
    it is rather than as the word "goals" (§6.5). Empty when nothing differs."""
    if old_records == new_records:
        return ""
    lines = difflib.unified_diff(
        _profile_field_lines(old_records), _profile_field_lines(new_records),
        fromfile=f"{label} (when the plan was generated)", tofile=f"{label} (now)",
        lineterm="", n=1,
    )
    return "\n".join(lines)


def profile_diff_text(old_profile: Dict[str, Any]) -> str:
    """A unified diff per plan-shaping field that differs between `old_profile` and the
    live config, so the athlete and the coach see the same edit the flag names
    (DESIGN_plan_staleness.md §10). Empty when nothing differs."""
    current = plan_profile()
    old_profile = plan_shaping(old_profile)
    chunks = []
    for field in changed_plan_profile_fields(old_profile):
        lines = difflib.unified_diff(
            _profile_field_lines(old_profile.get(field)),
            _profile_field_lines(current.get(field)),
            fromfile=f"{field} (when the plan was generated)",
            tofile=f"{field} (now)", lineterm="", n=1,
        )
        chunks.append("\n".join(lines))
    return "\n\n".join(chunks)


def science_diff_text(old_docs: Dict[str, str]) -> str:
    """A unified diff per athlete science file that differs between `old_docs` and the
    directory now (§11). Empty when nothing differs."""
    current = athlete_science_documents()
    chunks = []
    for name in changed_science_documents(old_docs):
        lines = difflib.unified_diff(
            _profile_field_lines(old_docs.get(name)),
            _profile_field_lines(current.get(name)),
            fromfile=f"{name} (when the plan was generated)",
            tofile=f"{name} (now)", lineterm="", n=1,
        )
        chunks.append("\n".join(lines))
    return "\n\n".join(chunks)


class PromptConfigMixin:
    """Part of :class:`CoachService` — see coach/service/__init__.py."""

    def _get_config_hash(self) -> str:
        return self.engine._get_config_hash()

    def effective_thresholds(self) -> Dict[str, float]:
        """The athlete's current threshold anchors — the single set both the coaching
        prompt and the plan-staleness check read through (DESIGN_benchmark_workouts.md
        §3.3, the linchpin accessor).

        Trainable anchors (ftp, lthr, threshold_pace, css, e1rm, mas) come from the latest
        logbook row per kind (§3.2); quasi-fixed physiology (max_hr) stays in config (§3.4).
        No kind is privileged — logbook kinds and max_hr flow through identically (§3.5).
        A logbook value overrides a same-named config value should one linger.
        """
        thresholds: Dict[str, float] = {}
        max_hr = config.user_profile.get('max_hr')
        if max_hr is not None:
            thresholds['max_hr'] = float(max_hr)
        thresholds.update(self._db.latest_thresholds())
        return thresholds

    def _effective_profile(self) -> Dict[str, Any]:
        """`config.user_profile` with the effective threshold anchors overlaid, so every
        engine prompt call prescribes zones/targets from the live logbook values (§3.3).

        The profile dict is passed through as-is; the logbook thresholds simply overlay it.
        The code makes no assumption about which threshold keys the profile does or does not
        carry — a logbook value overrides a same-named profile key, and any other key rides
        through untouched."""
        return {**config.user_profile, **self.effective_thresholds()}

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
        axes: the fingerprint over plan-shaping profile fields (see engine._clean_profile),
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
        if macro.get('config_hash') != self.engine._get_config_hash():
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
        if stored_goals and stored_goals != self.engine._get_goals_hash(objectives):
            reasons.append("goals changed")
        replan_constraints = [
            c for c in self._db.get_constraints(_svc._today_str())
            if c.get('replan')
        ]
        stored_constraints = macro.get('constraints_hash')
        if (stored_constraints and stored_constraints
                != self.engine._get_constraints_hash(replan_constraints)):
            reasons.append("plan-shaping constraints changed")
        return reasons

    def profile_diff(self, macro: Dict[str, Any]) -> str:
        """What actually changed in the plan-shaping profile since `macro` was generated,
        as a unified diff — or "" when the drift is elsewhere (thresholds, whose reason
        already carries the numbers) or the plan predates the snapshot (§10)."""
        if macro.get('config_hash') == self.engine._get_config_hash():
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
                old_goals, self.engine._clean_goals(self._db.upcoming_objectives()),
                "goals",
            ))

        old_constraints = _snapshot_records(macro.get('constraints_snapshot'))
        if old_constraints is not None:
            replan = [
                c for c in self._db.get_constraints(_svc._today_str())
                if c.get('replan')
            ]
            chunks.append(records_diff_text(
                old_constraints, self.engine._clean_constraints(replan),
                "plan-shaping constraints",
            ))

        old_docs = _snapshot_science(macro.get('science_snapshot'))
        if old_docs is not None:
            chunks.append(science_diff_text(old_docs))
        return "\n\n".join(chunk for chunk in chunks if chunk)

    def _get_goals_hash(self, objectives: List[Objective]) -> str:
        return self.engine._get_goals_hash(objectives)

    def _get_constraints_hash(self, constraints: List[Constraint]) -> str:
        return self.engine._get_constraints_hash(constraints)

    def _load_science_guidelines(self) -> str:
        return _load_science_guidelines(
            runtime.config.app_science_dir, runtime.config.science_dir
        )

    def _coach_context(
        self,
        constraints: List[Dict[str, Any]],
        objectives: Optional[List[Objective]] = None,
        objective_id: Optional[int] = None,
        mesocycles: Optional[List[Dict[str, Any]]] = None,
    ) -> CoachContext:
        """Assembles the shared context every prompt builder needs.

        Planning, generation and adaptation each built this by hand from the same four
        calls. `constraints` stays a parameter because the window each command reads
        differs — adaptation asks for the adaptation range, generation for the
        generation window — and that difference is deliberate.

        `mesocycles` is the date-keyed path (DESIGN_cli_selectors.md §8): a caller that has
        already resolved which mesocycles govern its window takes its strategy text from
        those, rather than from whichever macrocycle a goal points at. Generation uses it;
        planning and adaptation still name a goal.
        """
        if objectives is None:
            objectives = self._db.upcoming_objectives()
        strategy, meso_text = (
            self.strategy_text_for_mesocycles(mesocycles) if mesocycles is not None
            else self._get_active_strategy_and_meso_text(
                objectives, objective_id=objective_id
            )
        )
        return CoachContext(
            objectives=objectives,
            constraints=constraints,
            guidelines=self._load_science_guidelines(),
            profile=self._effective_profile(),
            strategy=strategy,
            meso_text=meso_text,
            learnings=self._get_learnings_text(),
        )

    def _get_active_strategy_and_meso_text(
        self, objectives: List[Objective], objective_id: Optional[int] = None
    ) -> Tuple[str, str]:
        strategy = None
        meso_text = ""

        next_goal = self._db.get_active_objective(objective_id)
        if not next_goal and objective_id is not None:
            next_goal = self._db.get_objective(objective_id)

        if next_goal and next_goal['id'] is not None:
            macrocycle = self._db.get_macrocycle_for_objective(next_goal['id'])
            if macrocycle:
                strategy = macrocycle['strategy']
                mesocycles = self._db.get_mesocycles_for_macrocycle(macrocycle['id'])
                for m in mesocycles:
                    meso_text += (
                        f"  - {m['name']} ({m['start_date']} to "
                        f"{m['end_date']}): {m['focus']}\n"
                    )
        if not strategy:
            strategy = (
                "Not established yet. Establish an endurance-focused training strategy "
                "based on goals."
            )
            meso_text = "  - Not established yet."
        return strategy, meso_text

    def strategy_text_for_mesocycles(self, mesocycles: List[Dict[str, Any]]) -> Tuple[str, str]:
        """Renders (strategy, meso_text) for a window's governing mesocycles.

        Each governing plan's mesocycles are listed in full, not just the ones the window
        touches: how a mesocycle is written depends on what follows it, so the week planner still
        needs to see the ones past the horizon. The covered ones are marked so it no
        longer has to infer which mesocycles the span falls in from the dates alone.
        """
        macro_ids: List[int] = []
        for b in mesocycles:
            if b['macrocycle_id'] not in macro_ids:
                macro_ids.append(b['macrocycle_id'])
        if not macro_ids:
            return (
                "Not established yet. Establish an endurance-focused training strategy "
                "based on goals.",
                "  - Not established yet.",
            )

        covered = {b['id'] for b in mesocycles}
        multi = len(macro_ids) > 1
        strategy_parts: List[str] = []
        meso_parts: List[str] = []
        for macro_id in macro_ids:
            macro = self._db.get_macrocycle(macro_id)
            if not macro:
                continue
            goal = self._db.get_objective(macro.get('objective_id'))
            label = (
                f"{goal['title']} ({goal['target_date']})" if goal else f"plan {macro_id}"
            )
            strategy_parts.append(
                f"For {label}:\n{macro['strategy']}" if multi else macro['strategy']
            )
            if multi:
                meso_parts.append(f"  Toward {label}:")
            for m in self._db.get_mesocycles_for_macrocycle(macro_id):
                mark = ">" if m['id'] in covered else "-"
                meso_parts.append(
                    f"  {mark} {m['name']} ({m['start_date']} to "
                    f"{m['end_date']}): {m['focus']}"
                )
        # "this window", not "this generation window": callers that pass `mesocycles=`
        # reach this same assembler and generate nothing.
        meso_parts.append(
            "  ('>' marks the mesocycles this window falls in; '-' mesocycles are "
            "context, outside it.)"
        )
        return "\n\n".join(strategy_parts), "\n".join(meso_parts) + "\n"

    def _get_learnings_text(self) -> str:
        """Renders active athlete observations as tagged lines for prompts. Each line is
        `[id|sports|confidence] text`. Dormant (decayed) and archived observations are
        omitted, so stale notes stop influencing planning until reaffirmed or restored."""
        learnings = [
            l for l in self._db.get_learnings()
            if not l.get("dormant") and not l.get("archived")
        ]
        if not learnings:
            return (
                "No observations yet. Over time, observe the athlete's responses to "
                "training volume and intensity."
            )
        return "\n".join(
            f"  [{l['id']}|{l.get('sports') or 'general'}|"
            f"{l.get('confidence') or 'tentative'}] {l['text']}"
            for l in learnings
        )

    def _apply_learning_updates(
        self, data: Dict[str, Any], available_weeks: List[str], source: str
    ) -> Dict[str, int]:
        """Applies evidence-cited learning deltas returned by the LLM, if any.

        `available_weeks` is the set of week_commencing (Monday) dates under analysis; cited
        weeks outside it are dropped. `source` tags the evidence rows ('bootstrap'/'reflect').
        Confidence is derived by the app from the accumulated basis — re-citing counted weeks
        cannot inflate it (see db.apply_learning_deltas and
        DESIGN_evidence_based_confidence.md §6).

        Deltas the app cannot act on are skipped, but the skip is reported: silently dropping
        every delta reads to the user as "the model had nothing to say"
        (DESIGN_backward_evaluation.md §13)."""
        tally = self._db.apply_learning_deltas(
            data.get("learning_updates") or [],
            available_weeks=available_weeks,
            source=source,
        )
        if tally["skipped"]:
            noun = "update" if tally["skipped"] == 1 else "updates"
            notice(
                f"{tally['skipped']} coach-learning {noun} came back in a shape this app "
                f"cannot read and {'was' if tally['skipped'] == 1 else 'were'} discarded "
                f"({tally['applied']} applied). The full response is in the LLM exchange "
                "log; re-running with " + cmd("--force") + " asks the model again.",
            )
        return tally

    def _review_learning_proposals(self) -> None:
        """The end of every reflect and bootstrap run (DESIGN_learning_doubt_nudge.md §3.2):
        the staleness steps apply, then each pending proposal goes to the athlete queue as a
        question, or is applied when the questions are switched off. Nothing is asked on
        the spot."""
        self._db.apply_staleness_steps()
        learning_doubts.settle_doubts(self.learning_question)

    def learning_question(
        self, learning: Dict[str, Any], reasons: List[Dict[str, Any]]
    ) -> Tuple[str, Optional[str]]:
        """The coach's two sentences for a doubted learning's question: what the learning
        claims about the athlete's experience, and what the coach saw against it, None when
        reflect gave no reason (DESIGN_learning_doubt_nudge.md §4). Raises ValueError when
        the answer carries no statement."""
        result = self.engine._learning_question_logic(
            learning["text"], learning.get("sports") or "general",
            [row["reason"] for row in reasons],
        )
        statement = result.get("statement")
        if not isinstance(statement, str) or not statement.strip():
            raise ValueError("the coach wrote no statement")
        saw = result.get("saw")
        if not reasons or not isinstance(saw, str) or not saw.strip():
            return statement.strip(), None
        return statement.strip(), saw.strip()

    def _maybe_nudge_no_threshold(self) -> None:
        """Cold-start hint when no trainable threshold is on record (§3.4).

        A fresh install has no FTP/LTHR/etc — the coach still plans, prescribing by RPE/HR
        feel (the prompt formatter and drift code both degrade gracefully on absent keys),
        and the very first plan schedules a benchmark to close the gap. So this nudges,
        never refuses. `max_hr` alone (config physiology) does not count as a threshold on
        record — the athlete still has no measured anchor."""
        recorded = {k for k in self.effective_thresholds() if k != 'max_hr'}
        if recorded:
            return
        notice(
            "No fitness thresholds on record — prescriptions will use RPE/HR feel until "
            "you record one (" + cmd("benchmark record …")
            + ") or complete the scheduled benchmark.",
        )

    def _maybe_nudge_bootstrap(self) -> None:
        """Prints a cold-start hint to run `data bootstrap` when there are no active coach
        learnings yet — durable observations are authored only by the history analysis.

        A bootstrap that already ran and seeded nothing gets the other half of the message:
        pointing at a command the user just ran reads as the app not having noticed
        (DESIGN_backward_evaluation.md §13)."""
        if any(not l.get("dormant") and not l.get("archived") for l in self._db.get_learnings()):
            return
        # Only when the table is genuinely empty: learnings that exist but have all gone
        # dormant are a staleness story, not a bootstrap that came back with nothing.
        prior = self._db.get_sync_state("bootstrap")
        if prior and not self._db.get_learnings():
            ran_on = (prior.get("last_pull_utc") or "")[:10] or "?"
            notice(
                f"No coach learnings yet — bootstrap ran on {ran_on} but seeded none. "
                "Re-run " + cmd("data bootstrap --force") + " to ask the model again.",
            )
            return
        notice(
            "No coach learnings yet. Run " + cmd("data bootstrap")
            + " to reconstruct your training history and seed evidence-based observations.",
        )

    def _maybe_warn_stale_analysis(self, today_str: str) -> None:
        """Warns when the cached analyses fed to the strategy prompt have fallen behind
        today. `plan generate` reads them as-is and never recomputes, so without this the
        plan is shaped by an old picture of the athlete's training in silence
        (DESIGN_backward_evaluation.md §5).

        Judged over `_cached_reconstructions()` — the same rows the prompt reads — so the
        `data reflect` this points at is a command that can actually clear it (§10.2). The
        wording names the *history read*, not a reconstruction: past §10.3 only bootstrap's
        row carries cycles, and bootstrap being old is by design rather than news."""
        ends = [
            c["window_end"] for c in self._cached_reconstructions() if c.get("window_end")
        ]
        if not ends:
            return
        window_end = max(ends)
        lag = (datetime.strptime(today_str, "%Y-%m-%d").date()
               - datetime.strptime(window_end, "%Y-%m-%d").date()).days
        if lag <= config.analysis_staleness_days:
            return
        notice(
            f"The training history read into this plan ends {window_end} ({lag} days ago); "
            f"sessions since then did not shape it. Run " + cmd("data reflect")
            + " first to bring it up to date.",
        )

    def _get_coach_system_prompt(
        self, objectives: List[Objective], constraints: List[Constraint],
        custom_task: str = "", objective_id: Optional[int] = None
    ) -> str:
        guidelines = self._load_science_guidelines()
        strategy, meso_text = self._get_active_strategy_and_meso_text(
            objectives, objective_id=objective_id
        )
        learnings = self._get_learnings_text()
        profile = self._effective_profile()
        return self.engine._build_system_prompt(
            objectives=objectives,
            constraints=constraints,
            guidelines=guidelines,
            strategy=strategy,
            meso_text=meso_text,
            learnings=learnings,
            profile=profile,
            custom_task=custom_task
        )
