"""What the coach knows before it is asked anything in particular.

The athlete themselves, as every prompt builder is given them: the threshold anchors in
force right now, the profile those anchors overlay, the science documents, the strategy
and mesocycle text of the plan they are in, and the learnings the coach has accumulated
about them. `_coach_context` gathers the seven into one :class:`CoachContext` so a new
shared input is added in one place rather than in `plan generate`, `workout generate` and
`workout adapt` each.

It also holds what happens to a learning after a call proposes one, and the three nudges
that fire when the coach is working without something it should have.

It is one mixin of :class:`CoachService` — see coach/service/__init__.py.
"""
from dataclasses import dataclass
from datetime import datetime
from typing import Any, List, Optional, Tuple, Dict

from stamind import learning_doubts, runtime
from stamind.config import config
from stamind.types import Objective, Constraint
from stamind.text import cmd
from stamind.output import notice
from stamind.coach.formatting import _load_science_guidelines


@dataclass(frozen=True)
class CoachContext:
    """The seven shared inputs, threaded as one value so no call site can omit one.

    Everything here is shared. Per-command inputs — the target date, the athlete's note,
    the window being planned — stay as arguments, because they are what distinguishes one
    command from another.
    """
    objectives: List[Dict[str, Any]]
    constraints: List[Dict[str, Any]]
    guidelines: str
    profile: Optional[Dict[str, Any]]
    strategy: str
    meso_text: str
    learnings: str


# What the strategy and mesocycle sections say when no plan governs the window. The
# prompt still gets both sections, so the model is told there is nothing rather than
# left to infer it from an absence (DESIGN_mesocycle_progress.md §2).
NO_STRATEGY = (
    "Not established yet. Establish an endurance-focused training strategy based on goals."
)
NO_MESOCYCLES = "  - Not established yet."


class AthleteContextMixin:
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
            strategy = NO_STRATEGY
            meso_text = NO_MESOCYCLES
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
            return NO_STRATEGY, NO_MESOCYCLES

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
