import hashlib
import json
from datetime import datetime, timedelta, timezone
from typing import Any, List, Optional, Dict
from stamind.config import config
from stamind.types import CompletedActivity, Constraint
from stamind import garmin
from stamind.analytics import weekly_evidence
from stamind.analytics.load import activity_load
from stamind.analytics.pmc import load_ratio
from stamind.text import cmd, cyan
from stamind.output import notice, step
from stamind.clock import today_date as _today_date

# Fallback look-back for `reflect` when no watermark exists yet (bootstrap not run).
DEFAULT_REFLECT_WEEKS = 4


def _nonblank(value: Any) -> bool:
    """True when a scalar the LLM was asked to fill actually carries text/number."""
    if value is None or isinstance(value, bool):
        return False
    if isinstance(value, (int, float)):
        return True
    return bool(str(value).strip())


def _reconstruction_content(decision: Dict[str, Any], cycles: bool) -> Dict[str, bool]:
    """Which parts of an analysis response came back readable.

    A response can parse as JSON and still be empty of everything the app reads: a model
    that mangles nested keys (prefixing each one, say) yields well-formed objects whose
    every `.get()` misses. Judged per part so the caller can tell "the model said little"
    from "nothing survived" (DESIGN_backward_evaluation.md §13).
    """
    macro = decision.get("inferred_macrocycle")
    mesos = decision.get("inferred_mesocycles")
    insights = decision.get("physiological_insights")
    content = {
        "summary": _nonblank(decision.get("macrocycle_summary")),
        "insights": isinstance(insights, (list, tuple)) and any(
            _nonblank(i) for i in insights
        ),
    }
    if cycles:
        content["macrocycle"] = isinstance(macro, dict) and _nonblank(
            macro.get("overall_focus")
        )
        content["mesocycles"] = isinstance(mesos, (list, tuple)) and any(
            isinstance(m, dict) and _nonblank(m.get("name")) for m in mesos
        )
    return content


def _unreadable_parts(decision: Dict[str, Any], cycles: bool) -> List[str]:
    """Parts the model DID answer but the app could not read, as display names.

    Presence is the discriminator: an omitted key is the model declining to answer, while
    a populated one whose fields all miss is a shape mismatch worth reporting (§13). Only
    the structured parts can mismatch — a summary is a plain string, so it is either
    answered or not.
    """
    content = _reconstruction_content(decision, cycles)
    parts = []
    if decision.get("physiological_insights") and not content["insights"]:
        parts.append("physiological insights")
    if cycles:
        if decision.get("inferred_macrocycle") and not content["macrocycle"]:
            parts.append("macrocycle")
        if decision.get("inferred_mesocycles") and not content["mesocycles"]:
            parts.append("mesocycles")
    return parts


class DataAnalysisMixin:
    """Part of :class:`CoachService` — see coach/service/__init__.py."""

    def _resolve_until(self, until_date_str: Optional[str]):
        until_date = _today_date()
        if until_date_str:
            until_date = datetime.strptime(until_date_str, "%Y-%m-%d").date()
        return until_date

    def _set_reflect_watermark(self, through_date: str) -> None:
        """Records how far `reflect` has consumed evidence. Reuses the generic
        `sync_state` table under the 'reflect' key (through_date = reflected-through
        day, last_pull_utc = run timestamp)."""
        self._db.set_sync_state(
            through_date=through_date,
            last_pull_utc=datetime.now(timezone.utc).isoformat(),
            key="reflect",
        )

    def _advance_reflect_watermark(self, through_date: str) -> None:
        """Advances the reflect watermark forward only, so a back-dated --from/--until
        run cannot rewind it and cause future reflects to re-ingest old evidence."""
        existing = self._db.get_sync_state("reflect")
        if existing and existing.get("through_date") and existing["through_date"] >= through_date:
            return
        self._set_reflect_watermark(through_date)

    def _record_bootstrap_run(self, through_date: str) -> None:
        """Marks that a cold-start reconstruction has completed, under the 'bootstrap'
        `sync_state` key. Distinct from the 'reflect' watermark (which `reflect` also
        advances): this records specifically that `bootstrap` itself has run, so a repeat
        invocation can detect it and avoid re-paying for the full reconstruction (and
        rewinding the reflect baseline) by accident."""
        self._db.set_sync_state(
            through_date=through_date,
            last_pull_utc=datetime.now(timezone.utc).isoformat(),
            key="bootstrap",
        )

    def data_bootstrap(
        self, from_date_str: Optional[str] = None, until_date_str: Optional[str] = None,
        context: Optional[str] = None, force: bool = False, inspect_only: bool = False,
        no_pull: bool = False, force_pull: bool = False, auto: bool = False
    ) -> Dict[str, Any]:
        """Cold-start backward reconstruction over the full training backlog.

        Reverse-engineers the macro/mesocycle structure and seeds initial coach
        learnings from history. Run once when onboarding (or after a long gap); `reflect`
        then handles the incremental stream. With no date filter, the window is
        auto-detected from the active goal (since the previous goal, else 12 weeks back).

        Establishes the reflect watermark at the window end, so subsequent `reflect` runs
        only ingest evidence newer than this — preventing the same backlog from being
        re-counted (and confidence ratcheted to 'established') on every run.

        Because this is a once-per-onboarding operation, a repeat invocation is detected
        (via the 'bootstrap' `sync_state` key) and confirmed before re-running: `--force`
        proceeds, `--auto` skips, and `--inspect-only` is read-only so it's never gated.
        """
        until_date = self._resolve_until(until_date_str)

        from_date = None
        if from_date_str:
            from_date = datetime.strptime(from_date_str, "%Y-%m-%d").date()
        else:
            # Auto-timeline detection based on active goals
            earliest_goal = self._db.get_active_objective()
            if earliest_goal:
                target_date_str = earliest_goal['target_date']
                preceding = self._db.get_preceding_objectives(target_date_str)
                if preceding:
                    last_goal_date = datetime.strptime(
                        preceding[0]['target_date'], "%Y-%m-%d"
                    ).date()
                    from_date = last_goal_date + timedelta(days=1)
                else:
                    # No preceding goal. Assume the athlete was training for it.
                    # Default to 12 weeks lookback from today/until_date, capped at today
                    from_date = until_date - timedelta(weeks=12)
            else:
                # No active goals found. Default to 12 weeks lookback.
                from_date = until_date - timedelta(weeks=12)

        if from_date > until_date:
            raise ValueError(f"Start date {from_date} is after end date {until_date}.")

        # Bootstrap is a once-per-onboarding reconstruction. If it has already run, a
        # repeat is almost always unintended: it re-pays for the full LLM pass and resets
        # the reflect baseline (potentially rewinding it). Confirm before re-running —
        # `--force` is the explicit "yes, redo it" signal; `--inspect-only` is read-only
        # and harmless so it's never gated.
        prior = self._db.get_sync_state("bootstrap")
        if prior and not force and not inspect_only:
            ran_on = (prior.get("last_pull_utc") or "")[:10] or "?"
            notice(
                f"Bootstrap already ran on {ran_on} (through {prior.get('through_date')}). "
                "For incremental updates use " + cmd("data reflect") + " instead.",
            )
            if auto:
                print(cyan("Skipping bootstrap (pass --force to re-run)."))
                return {}
            if not self._prompt.confirm("Re-run the full bootstrap anyway?"):
                print(cyan("Bootstrap skipped."))
                return {}

        decision = self._run_workout_analysis(
            from_date, until_date, context=context, force=force,
            inspect_only=inspect_only, no_pull=no_pull, force_pull=force_pull,
            horizon="long", label="data_bootstrap",
        )
        # Establish the reflect baseline and record the bootstrap run (read-only inspect
        # mode writes nothing).
        if not inspect_only:
            self._set_reflect_watermark(until_date.strftime("%Y-%m-%d"))
            self._record_bootstrap_run(until_date.strftime("%Y-%m-%d"))
            self._review_learning_proposals()
            # Bootstrap is the command that seeds observations, so ending with none on
            # record is news — otherwise the next command's cold-start nudge points the
            # user right back here with no hint that the run already happened (§13).
            active = [
                l for l in self._db.get_learnings()
                if not l.get("dormant") and not l.get("archived")
            ]
            if not active:
                notice(
                    "Bootstrap finished with no active coach observations on record. The "
                    "reconstruction above is saved; re-run with "
                    + cmd("data bootstrap --force") + " to ask the model again.",
                )
        return decision

    def data_reflect(
        self, from_date_str: Optional[str] = None, until_date_str: Optional[str] = None,
        days: Optional[int] = None, weeks: Optional[int] = None,
        context: Optional[str] = None, force: bool = False, inspect_only: bool = False,
        no_pull: bool = False, force_pull: bool = False
    ) -> Dict[str, Any]:
        """Incremental reflection over evidence accrued since the last reflect.

        Unlike `bootstrap`, the window starts at the reflect watermark (the day after the
        last reflected-through date) unless an explicit date filter is given, so
        overlapping history is never re-counted — the root cause of confidence converging
        to 'established' when the command was run day after day over a sliding window.
        Advances the watermark on success.

        The window also ENDS on a completed week unless an explicit end date is given: the
        evidence basis counts whole weeks, so a window ending mid-week lets a part-week be
        cited as one (DESIGN_evidence_based_confidence.md §4, §10.4 here). A run with no
        completed week since the watermark therefore reports nothing new and makes no LLM
        call, which is what makes a daily invocation harmless.

        Reuse / integrity invariants are inherited from `_run_workout_analysis`.
        """
        until_date = self._resolve_until(until_date_str)
        if not until_date_str:
            until_date -= timedelta(days=until_date.weekday() + 1)  # last completed Sunday

        watermark = self._db.get_sync_state("reflect")
        if from_date_str:
            from_date = datetime.strptime(from_date_str, "%Y-%m-%d").date()
        elif watermark and watermark.get("through_date"):
            from_date = (
                datetime.strptime(watermark["through_date"], "%Y-%m-%d").date()
                + timedelta(days=1)
            )
        else:
            # No watermark yet (bootstrap not run). Reflect over a recent default window
            # rather than dead-ending, but nudge the user toward bootstrap.
            from_date = (
                until_date - timedelta(weeks=DEFAULT_REFLECT_WEEKS) + timedelta(days=1)
            )
            notice(
                f"No reflect baseline found; reflecting over the last {DEFAULT_REFLECT_WEEKS} "
                f"weeks. Run {cmd('data bootstrap')} to reconstruct your full training "
                "history first.",
            )

        if from_date > until_date:
            # Only a range the caller gave BOTH ends of can be self-contradictory; a start
            # that outruns a snapped end just means no week has completed yet.
            if from_date_str and until_date_str:
                raise ValueError(f"Start date {from_date} is after end date {until_date}.")
            since = watermark["through_date"] if watermark else (from_date_str or "?")
            tail = "" if until_date_str else " (no completed week since)"
            print(cyan(f"Nothing new to reflect on since {since}{tail}."))
            # Even with no new evidence, the staleness steps and the pending doubts are
            # settled (DESIGN_learning_doubt_nudge.md §3.2).
            if not inspect_only:
                self._review_learning_proposals()
            return {}

        decision = self._run_workout_analysis(
            from_date, until_date, context=context, force=force,
            inspect_only=inspect_only, no_pull=no_pull, force_pull=force_pull,
            horizon="short", label="data_reflect",
        )
        if not inspect_only:
            self._advance_reflect_watermark(until_date.strftime("%Y-%m-%d"))
            self._review_learning_proposals()
        return decision

    def _run_workout_analysis(
        self, from_date, until_date,
        context: Optional[str] = None, force: bool = False, inspect_only: bool = False,
        no_pull: bool = False, force_pull: bool = False,
        horizon: str = "long", label: str = "workout_analysis"
    ) -> Dict[str, Any]:
        """Shared core for bootstrap/reflect: builds weekly summaries over
        [from_date, until_date], runs the LLM reconstruction, applies learning deltas,
        and caches the reconstruction under `horizon`.

        Backward-evaluation reuse (DESIGN_backward_evaluation.md §5, §8, §9):
        - The reconstruction is cached per `horizon`, keyed by an evidence fingerprint. If
          the evidence is unchanged since the last run and `force` is False, the cached
          reconstruction is returned without an LLM call.
        - `force` bypasses *reuse* only (recompute even if unchanged); integrity is owned by
          the per-learning evidence basis, which dedupes re-cited weeks
          (DESIGN_evidence_based_confidence.md §8).
        - `inspect_only` is read-only: it renders the reconstruction but writes neither coach
          learnings nor the cache.
        """
        from_str = from_date.strftime("%Y-%m-%d")
        until_str = until_date.strftime("%Y-%m-%d")

        step(f"Analyzing activities from {from_str} to {until_str}...", cyan)

        # Ensure Garmin data covers the analysis window (auto-pull recent/small gaps,
        # surface a command for large backfills) before reading it unless no_pull is True.
        if not no_pull:
            garmin.ensure_data(from_str, until_str, force=force_pull)

        metrics = self._db.get_metrics_cache(start_date=from_str, end_date=until_str)
        completed_activities = self._db.get_completed_activities(
            start_date=from_str, end_date=until_str
        )
        # Constraints overlapping the window contextualize anomalies (illness/travel/work)
        # so the model doesn't misattribute them to training. get_constraints(start, end)
        # already returns only overlapping rows (DESIGN_constraints.md §6).
        constraints = self._db.get_constraints(from_str, until_str)
        # External daily signals (alcohol, sleep, stress, …) ingested from the
        # calendar; they explain recovery anomalies the same way constraints explain load
        # ones (DESIGN_calendar_signal_ingest.md §7).
        daily_signals = self._db.get_daily_signals(start_date=from_str, end_date=until_str)

        # Quantitative signal-impact rows cover the athlete's FULL history of signal-days,
        # not just [from,until]: an incremental reflect window holds almost no drinking
        # history to find a pattern in (DESIGN_quantitative_signal_impact.md §6). Computed
        # before the fingerprint because they are hashed into it (§8).
        signal_days = weekly_evidence.signal_days(
            daily_signals=self._db.get_daily_signals(),
            metrics=self._db.get_metrics_cache(),
            activities=self._db.get_completed_activities(),
            baseline_for=self._db.get_baseline,
            k=config.signal_days_lookahead,
            min_signal_days=config.signal_days_min_days,
        )

        # Reuse path: if the evidence is unchanged since the last analysis, return the
        # cached reconstruction instead of paying for another LLM pass (unless --force).
        fingerprint = self._get_evidence_fingerprint(
            completed_activities, metrics, from_str, until_str, constraints, daily_signals,
            signal_days
        )
        cached = self._db.get_analysis_cache(horizon)
        evidence_unchanged = bool(cached and cached.get("fingerprint") == fingerprint)
        if evidence_unchanged and not force and cached.get("reconstruction"):
            step("Evidence unchanged since last analysis; reusing cached reconstruction "
                  "(use --force to recompute).", cyan)
            return cached["reconstruction"]

        # Group by ISO week (Monday date string)
        weeks_data: Dict[str, Dict[str, Any]] = {}
        current_day = from_date
        while current_day <= until_date:
            monday = current_day - timedelta(days=current_day.weekday())
            monday_str = monday.strftime("%Y-%m-%d")

            if monday_str not in weeks_data:
                weeks_data[monday_str] = {
                    "days": [],
                    "metrics": [],
                    "activities": [],
                    "daily_signals": []
                }
            weeks_data[monday_str]["days"].append(current_day)
            current_day += timedelta(days=1)

        # Distribute metrics and activities into the weeks
        for m in metrics:
            m_date = datetime.strptime(m['date'], "%Y-%m-%d").date()
            monday = m_date - timedelta(days=m_date.weekday())
            monday_str = monday.strftime("%Y-%m-%d")
            if monday_str in weeks_data:
                weeks_data[monday_str]["metrics"].append(m)

        for sig in daily_signals:
            c_date = datetime.strptime(sig["date"], "%Y-%m-%d").date()
            monday = c_date - timedelta(days=c_date.weekday())
            monday_str = monday.strftime("%Y-%m-%d")
            if monday_str in weeks_data:
                weeks_data[monday_str]["daily_signals"].append(sig)

        for act in completed_activities:
            act_date = datetime.strptime(act['date'], "%Y-%m-%d").date()
            monday = act_date - timedelta(days=act_date.weekday())
            monday_str = monday.strftime("%Y-%m-%d")
            if monday_str in weeks_data:
                weeks_data[monday_str]["activities"].append(act)

        # PMC weekly trajectory (DESIGN_pmc_fitness_fatigue.md §5.4): the warm-up cutoff
        # and a full in-window date->CTL map, both read once, for end_ctl/week_ramp/min_tsb.
        pmc_cutoff = garmin.warmup_cutoff(self._db)
        ctl_by_date = {m['date']: m.get('ctl') for m in metrics}

        # Build summaries per week
        weekly_summaries = []
        for monday_str in sorted(weeks_data.keys()):
            w_info = weeks_data[monday_str]
            days_in_week = w_info["days"]
            w_metrics = w_info["metrics"]
            w_activities = w_info["activities"]

            total_duration_hours = sum(
                (act.get('duration_sec') or 0.0) / 3600.0 for act in w_activities
            )
            total_tss = sum(activity_load(act) for act in w_activities)

            sports: Dict[str, int] = {}
            for act in w_activities:
                st = act['activity_type'].lower()
                sports[st] = sports.get(st, 0) + 1

            z1_z2_sec = sum(
                (act.get('zone1_sec') or 0) + (act.get('zone2_sec') or 0)
                for act in w_activities
            )
            z3_sec = sum(act.get('zone3_sec') or 0 for act in w_activities)
            z4_z5_sec = sum(
                (act.get('zone4_sec') or 0) + (act.get('zone5_sec') or 0)
                for act in w_activities
            )

            # Power zones (Garmin 7-zone model), grouped polarized like HR.
            pz1_pz2_sec = sum(
                (act.get('power_zone1_sec') or 0) + (act.get('power_zone2_sec') or 0)
                for act in w_activities
            )
            pz3_pz4_sec = sum(
                (act.get('power_zone3_sec') or 0) + (act.get('power_zone4_sec') or 0)
                for act in w_activities
            )
            pz5_pz7_sec = sum(
                (act.get('power_zone5_sec') or 0) + (act.get('power_zone6_sec') or 0)
                + (act.get('power_zone7_sec') or 0) for act in w_activities
            )

            avg_rpe = 0.0
            rpes = [act['rpe'] for act in w_activities if act.get('rpe') is not None]
            if rpes:
                avg_rpe = sum(rpes) / len(rpes)

            avg_rhr = None
            rhrs = [m['rhr'] for m in w_metrics if m.get('rhr') is not None]
            if rhrs:
                avg_rhr = sum(rhrs) / len(rhrs)

            avg_hrv = None
            hrvs = [m['hrv'] for m in w_metrics if m.get('hrv') is not None]
            if hrvs:
                avg_hrv = sum(hrvs) / len(hrvs)

            max_load_ratio = None
            ratios = [
                r for r in (load_ratio(m.get('atl'), m.get('ctl')) for m in w_metrics)
                if r is not None
            ]
            if ratios:
                max_load_ratio = max(ratios)

            end_ctl, week_ramp, min_tsb = weekly_evidence.pmc_week_summary(
                w_metrics, ctl_by_date, pmc_cutoff
            )

            active_dates = {act['date'] for act in w_activities}
            rest_days = len(days_in_week) - len(active_dates)

            # Deterministic body-response features + overlapping life events for this week
            # (DESIGN_richer_analysis_evidence.md §2–§3). The baseline moves slowly, so one
            # lookup per week (at the week's last in-window day) is enough.
            week_start, week_end = days_in_week[0], days_in_week[-1]
            baseline = self._db.get_baseline(week_end.strftime("%Y-%m-%d"))
            response = weekly_evidence.week_response_features(w_metrics, baseline)
            week_events = weekly_evidence.week_constraints(constraints, week_start, week_end)
            # All signals for the week, handed to the LLM verbatim (no collapsing
            # of multiple metrics/day — DESIGN_calendar_signal_ingest.md §7).
            week_signals = sorted(
                (
                    {"date": c["date"], "metric": c["metric"],
                     "value": c["value"], "text": c.get("text")}
                    for c in w_info["daily_signals"]
                ),
                key=lambda r: (r["date"], r["metric"]),
            )

            highlights = []
            for act in w_activities:
                is_hi = (
                    (act.get('tss') and act['tss'] >= config.high_intensity_tss_threshold) or
                    (act.get('rpe') and act['rpe'] >= config.high_intensity_rpe_threshold) or
                    any(
                        kw in (act.get('activity_name') or "").lower()
                        for kw in ["race", "test", "ftp", "marathon"]
                    )
                )
                if is_hi:
                    highlights.append({
                        "date": act['date'],
                        "type": act['activity_type'],
                        "name": act.get('activity_name') or "Workout",
                        "duration_min": int((act.get('duration_sec') or 0.0) / 60.0),
                        "tss": act.get('tss'),
                        "rpe": act.get('rpe')
                    })

            summary = {
                "week_commencing": monday_str,
                "total_duration_hours": round(total_duration_hours, 1),
                "total_tss": round(total_tss, 1),
                "average_rpe": round(avg_rpe, 1) if avg_rpe > 0 else 0.0,
                "sports": sports,
                "zone_distribution_sec": {
                    "Z1_Z2": z1_z2_sec,
                    "Z3": z3_sec,
                    "Z4_Z5": z4_z5_sec
                },
                # Only emitted when some activity recorded power-zone data, so its
                # absence means "no power meter" rather than "no hard riding".
                "power_zone_distribution_sec": {
                    "Z1_Z2": pz1_pz2_sec,
                    "Z3_Z4": pz3_pz4_sec,
                    "Z5_Z7": pz5_pz7_sec
                } if (pz1_pz2_sec + pz3_pz4_sec + pz5_pz7_sec) > 0 else None,
                "avg_rhr": round(avg_rhr, 1) if avg_rhr is not None else None,
                "avg_hrv": round(avg_hrv, 1) if avg_hrv is not None else None,
                "avg_sleep_score": response["avg_sleep_score"],
                "avg_stress": response["avg_stress"],
                "max_load_ratio": (
                    round(max_load_ratio, 2) if max_load_ratio is not None else None
                ),
                "end_ctl": round(end_ctl, 1) if end_ctl is not None else None,
                "week_ramp": week_ramp,
                "min_tsb": round(min_tsb, 1) if min_tsb is not None else None,
                "rest_days": rest_days,
                "highlights": highlights,
                "constraints": week_events,
            }
            # Baseline-relative deviations, omitted whole when no metric/baseline supports
            # any component (so its absence reads as "no data", not "on baseline").
            if "vs_baseline_z" in response:
                summary["vs_baseline_z"] = response["vs_baseline_z"]
            # Emitted only when present so its absence reads as "no signals logged".
            if week_signals:
                summary["daily_signals"] = week_signals
            weekly_summaries.append(summary)

        # Fetch relevant objectives (occurring on or after from_date)
        all_objectives = self._db.get_objectives()
        objectives = [
            obj for obj in all_objectives
            if datetime.strptime(obj['target_date'], "%Y-%m-%d").date() >= from_date
        ]

        guidelines = self._load_science_guidelines()
        profile = self._effective_profile()

        decision = self.engine._data_analyze_logic(
            objectives=objectives,
            guidelines=guidelines,
            profile=profile,
            weekly_summaries=weekly_summaries,
            signal_days=signal_days,
            learnings=self._get_learnings_text(),
            context=context,
            label=label,
            horizon=horizon
        )

        # A response that parses but carries nothing the app can read is a failed exchange,
        # not a result: caching it pins the emptiness behind the fingerprint (only --force
        # gets past it) and, for bootstrap, the watermark would move as if the history had
        # been read (DESIGN_backward_evaluation.md §13).
        cycles = horizon == "long"
        if not any(_reconstruction_content(decision, cycles).values()):
            raise ValueError(
                f"The model's {label} response parsed but contained none of the requested "
                "content — no summary, no insights"
                + (", no macrocycle or mesocycles" if cycles else "")
                + ". Nothing was saved. The raw response is in the LLM exchange log; re-run "
                "to ask again, or switch models with " + cmd("settings set coach-model") + "."
            )
        unreadable = _unreadable_parts(decision, cycles)
        if unreadable:
            notice(
                "The model answered but these parts came back in an unreadable shape and "
                f"render empty below: {', '.join(unreadable)}. The raw response is in the "
                "LLM exchange log.",
            )

        if not inspect_only:
            # Apply evidence-cited learning deltas. The LLM attributes observations to the
            # week_commencing weeks it was shown; the app derives confidence from the
            # accumulated distinct weeks, so re-citing counted weeks (forced re-runs,
            # overlapping windows) is a structural no-op — no reinforcement-suppression flag
            # needed (DESIGN_evidence_based_confidence.md §6, §8).
            available_weeks = sorted(weeks_data.keys())
            source = "bootstrap" if horizon == "long" else "reflect"
            self._apply_learning_updates(decision, available_weeks, source)
            # Cache the reconstruction (everything but the point-in-time deltas) so future
            # runs — and `plan generate` — can reuse it without another LLM call.
            reconstruction = {
                k: v for k, v in decision.items() if k != "learning_updates"
            }
            self._db.save_analysis_cache(
                horizon, fingerprint, from_str, until_str, reconstruction
            )

        return decision

    def _get_evidence_fingerprint(
        self, completed_activities: List[CompletedActivity],
        metrics: List[Dict[str, Any]], window_start: str, window_end: str,
        constraints: Optional[List[Constraint]] = None,
        daily_signals: Optional[List[Dict[str, Any]]] = None,
        signal_days: Optional[Dict[str, Any]] = None
    ) -> str:
        """Fingerprints the *evidence* a backward evaluation reconstructs from — the
        completed activities + daily metrics (+ overlapping constraints) within a window —
        so a re-run over unchanged data can be detected (see DESIGN_backward_evaluation.md
        §5, §8). `signal_days` is the *full-history* episode mesocycle, hashed as computed
        because it is built outside the window (DESIGN_quantitative_signal_impact.md §8).

        We hash the load-bearing fields (not just activity ids) so that a re-pull which
        *corrects* a value also shifts the fingerprint. Hashing the concrete activity-id
        set rather than only the date range narrows the overlapping/shrinking-window edge
        (§7). Constraints and `stress` are hashed because they now feed the analysis input
        as discounting context (DESIGN_richer_analysis_evidence.md §5, DESIGN_constraints.md §6).

        DELIBERATE OMISSIONS (§11 / richer-evidence §5): the prompt text, the science/*.md
        files and bare baseline recomputation are NOT hashed, so editing one reuses a stale
        reconstruction until the underlying data changes. `--force` is the escape hatch.
        """
        act_digest = sorted(
            {
                (
                    a.get('activity_id'), a.get('date'), a.get('activity_type'),
                    a.get('duration_sec'), a.get('tss'), a.get('rpe'),
                    a.get('zone1_sec'), a.get('zone2_sec'), a.get('zone3_sec'),
                    a.get('zone4_sec'), a.get('zone5_sec'),
                )
                for a in completed_activities
            }
        )
        met_digest = sorted(
            (m.get('date'), m.get('rhr'), m.get('hrv'), m.get('sleep_score'),
             m.get('stress'), m.get('ctl'), m.get('atl'), m.get('tsb'))
            for m in metrics
        )
        evt_digest = sorted(
            (c.get('id'), c.get('start_date'), c.get('end_date'),
             int(c.get('rest') or 0),
             c.get('title'), c.get('description'))
            for c in (constraints or [])
        )
        # Daily signals feed the analysis input, so an added/edited/deleted signal must
        # shift the fingerprint (DESIGN_calendar_signal_ingest.md §7).
        sig_digest = sorted(
            (c.get('date'), c.get('metric'), c.get('value'), c.get('text'))
            for c in (daily_signals or [])
        )
        serialized = json.dumps(
            {'window': [window_start, window_end],
             'activities': act_digest, 'metrics': met_digest, 'constraints': evt_digest,
             'daily_signals': sig_digest, 'signal_days': signal_days or {}},
            sort_keys=True
        )
        return hashlib.sha256(serialized.encode('utf-8')).hexdigest()
