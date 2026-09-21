"""What a prompt is told about the training already behind the athlete.

Four read-only things, all assembled at prompt time. The past fifteen days as a block of
totals. The fitness/fatigue picture — where CTL, ATL and TSB stand, which way the ramp is
going, and the caveat for a series too young to read (DESIGN_pmc_fitness_fatigue.md
§5.2). The per-mesocycle "planned versus actual" review the strategy prompt opens with
(DESIGN_backward_evaluation.md §6). And the cached reconstructions of what the athlete
trained before Stamind was watching.

The mesocycle currently under way is `mesocycle_context.py`. It is one mixin of
:class:`CoachService` — see coach/service/__init__.py.
"""
from datetime import datetime, timedelta
from typing import Any, Dict, List, Optional, Tuple

from stamind.config import config
from stamind import garmin
from stamind.analytics import zone_tables
from stamind.analytics.mesocycle_report import mesocycle_report
from stamind.analytics.pmc import PMC_TSB_LAG_NOTE, load_ratio, pmc_data_caveat, pmc_ramp
from stamind.plan_versions import plan_lineage
from stamind.sports import canonical_sport
from stamind.text import wrap_text


class HistoryContextMixin:
    def _get_recent_history_summary(self, today_str: str) -> str:
        """Retrieves and constructs a summary of the past 15 days of workouts/metrics."""
        today_date = datetime.strptime(today_str, "%Y-%m-%d").date()
        start_date_obj = today_date - timedelta(days=14)
        start_date_str = start_date_obj.strftime("%Y-%m-%d")

        metrics = self._db.get_metrics_cache(
            start_date=start_date_str, end_date=today_str
        )
        completed_activities = self._db.get_completed_activities(
            start_date=start_date_str, end_date=today_str
        )

        lines = []

        # 1. Activities summary
        if completed_activities:
            sport_durations: Dict[str, float] = {}
            sport_counts: Dict[str, int] = {}
            for act in completed_activities:
                # The canonical sport, as every other surface counts it: road and indoor
                # cycling are one sport, so the prompt cannot read them as two
                # (stamind/sports.py).
                sport = canonical_sport(act.get('activity_type') or 'unknown')
                dur_min = act.get('duration_sec', 0.0) / 60.0
                sport_durations[sport] = sport_durations.get(sport, 0.0) + dur_min
                sport_counts[sport] = sport_counts.get(sport, 0) + 1

            lines.append("Completed Activities (Past 15 days):")
            total_duration_hours = 0.0
            for sport, count in sport_counts.items():
                dur_hours = sport_durations[sport] / 60.0
                total_duration_hours += dur_hours
                lines.append(
                    f"  - {sport}: {count} activit{'ies' if count != 1 else 'y'}, "
                    f"total duration {dur_hours:.1f} hours"
                )

            weekly_avg_hours = (total_duration_hours / 15.0) * 7.0
            lines.append(
                f"  - Total training volume: {total_duration_hours:.1f} hours "
                f"(~{weekly_avg_hours:.1f} hours/week)"
            )
        else:
            lines.append("Completed Activities (Past 15 days):\n  - No completed activities found.")

        # 2. Metrics summary
        if metrics:
            rhrs = [m['rhr'] for m in metrics if m.get('rhr') is not None]
            hrvs = [m['hrv'] for m in metrics if m.get('hrv') is not None]
            sleeps = [m['sleep_score'] for m in metrics if m.get('sleep_score') is not None]

            lines.append("Physiological Metrics (15-day average):")
            if rhrs:
                lines.append(f"  - Resting Heart Rate: {sum(rhrs)/len(rhrs):.1f} bpm")
            if hrvs:
                lines.append(f"  - Heart Rate Variability (HRV): {sum(hrvs)/len(hrvs):.1f} ms")
            if sleeps:
                lines.append(f"  - Sleep Score: {sum(sleeps)/len(sleeps):.1f}/100")
            # PMC (CTL/ATL/TSB) + the single ramp line, so the strategy/plan prompt can
            # reason about current freshness and a sustainable build rate against the
            # science directives (DESIGN_pmc_fitness_fatigue.md §5.2).
            for pmc_line in self._pmc_summary_lines(metrics, today_str):
                lines.append("  " + pmc_line)
        else:
            lines.append("Physiological Metrics (Past 15 days):\n  - No metrics found.")

        return "\n".join(lines)

    # ------------------------------------------------------------------ PMC helpers
    def _pmc_summary_lines(
        self, metrics: List[Dict[str, Any]], as_of: str
    ) -> List[str]:
        """The PMC lines for the data summary (strategy/plan prompt): the latest
        Fitness/Fatigue line, the single CTL ramp line, the §3.3(b) still-warming-up flag,
        and the TSB-lag footnote — each omitted when it has nothing to say. Order: values,
        then trust/caveat."""
        out: List[str] = []
        # History start (and the cutoff/caveat derived from it) is read ONCE here and
        # passed down — no helper below re-derives it.
        start = garmin.pmc_history_start(dbh=self._db)
        cutoff = garmin.warmup_cutoff(self._db, start)
        latest = self._pmc_latest_line(metrics, cutoff)
        if latest:
            out.append(latest)
        ramp = self._pmc_ramp_line(cutoff)
        if ramp:
            out.append(ramp)
        caveat = self._pmc_caveat_line(pmc_data_caveat(start, as_of))
        if caveat:
            out.append(caveat)
        # The footnote explains the TSB lag, so only a line actually showing TSB needs it.
        if latest and "TSB" in latest:
            out.append(PMC_TSB_LAG_NOTE)
        return out

    def _pmc_latest_line(
        self, metrics: List[Dict[str, Any]], warmup_cutoff: Optional[str]
    ) -> Optional[str]:
        """'- Fitness/Fatigue (PMC): CTL .. ATL .. TSB .. ATL:CTL ..' from the latest
        past-warm-up row carrying PMC values, or None."""
        for m in reversed(metrics):
            if warmup_cutoff and m['date'] < warmup_cutoff:
                continue
            ctl, atl, tsb = m.get('ctl'), m.get('atl'), m.get('tsb')
            if ctl is None and atl is None and tsb is None:
                continue
            parts = []
            if ctl is not None:
                parts.append(f"CTL {ctl:.1f} (fitness)")
            if atl is not None:
                parts.append(f"ATL {atl:.1f} (fatigue)")
            if tsb is not None:
                parts.append(f"TSB {tsb:.1f} (form)")
            ratio = load_ratio(atl, ctl)
            if ratio is not None:
                parts.append(f"ATL:CTL {ratio:.2f} (relative overload)")
            return "- Fitness/Fatigue (PMC): " + ", ".join(parts)
        return None

    def _pmc_ramp_line(self, cutoff: Optional[str]) -> Optional[str]:
        """The single '- CTL ramp rate: +4.2/week (last 7 days)' line, computed from the
        FULL stored CTL series (never a short prompt window, so a small window can't drop
        it — §3.1/§5.2). None inside the warm-up window, at a <7-day span edge, or when
        the -7d baseline itself lands in the warm-up zone (pmc_ramp's straddle guard)."""
        all_metrics = self._db.get_metrics_cache()
        ctl_by_date = {m['date']: m.get('ctl') for m in all_metrics}
        latest = None
        for m in all_metrics:
            if m.get('ctl') is None:
                continue
            if cutoff and m['date'] < cutoff:
                continue
            latest = m['date']
        if latest is None:
            return None
        ramp = pmc_ramp(ctl_by_date, latest, warmup_cutoff=cutoff)
        if ramp is None:
            return None
        return f"- CTL ramp rate: {ramp:+.1f}/week (last 7 days)"

    def _pmc_caveat_line(self, cav: Optional[Dict[str, Any]]) -> Optional[str]:
        """Renders the §3.3(b) static "still warming up" flag (a pmc_data_caveat
        dict, or None) as a summary line, stated as a *condition* (not an assertion that
        fitness is understated — a genuine beginner's low CTL is correct).

        While N < τ_ctl the ENTIRE history is still inside the §3.3(a) warm-up window, so
        every surface suppresses the values themselves; then this line explains the
        absence instead of caveating numbers the prompt doesn't contain."""
        if not cav:
            return None
        ctl_days = config.pmc_ctl_days
        if cav["n_days"] < ctl_days:
            return (
                f"- PMC (CTL/ATL/TSB): suppressed — only {cav['n_days']} days of "
                f"history; values are leading-edge warm-up artifacts for the first "
                f"{ctl_days} days."
            )
        return (
            f"- PMC data caveat: CTL is based on {cav['n_days']} days of history "
            f"(a {ctl_days}-day average needs months to settle). If the athlete "
            f"trained regularly before {cav['history_start']}, true fitness is higher "
            f"than shown and low TSB / high ramp are partly warm-up artifacts; if "
            f"they did not, the low values are real."
        )

    def _pmc_prompt_context(
        self, as_of: Optional[str] = None
    ) -> Tuple[Optional[str], Optional[str]]:
        """(warmup_cutoff, extra_lines) for the generate/adapt metrics section: the single
        ramp line and the still-warming-up flag — a single line each beside the per-day
        mesocycle, never repeated per day (§5.2). History start is read ONCE and passed down."""
        start = garmin.pmc_history_start(dbh=self._db)
        cutoff = garmin.warmup_cutoff(self._db, start)
        lines: List[str] = []
        ramp = self._pmc_ramp_line(cutoff)
        if ramp:
            lines.append(ramp)
        caveat = self._pmc_caveat_line(pmc_data_caveat(start, as_of))
        if caveat:
            lines.append(caveat)
        return cutoff, ("\n".join(lines) if lines else None)

    def _intensity_history_context(
        self, macros: List[Dict[str, Any]], today_str: str,
        width: int = zone_tables.PROMPT_WIDTH,
    ) -> List[str]:
        """One intensity report per elapsed mesocycle across `macros`, each carrying the
        delta against the mesocycle before it (DESIGN_intensity_distribution.md §4.1) —
        the strategy prompt's view.

        Each mesocycle's delta baseline is the mesocycle before it in the flattened lineage —
        across plan boundaries too, unlike `sm progress --mesocycles`: reviewing one season
        against the last is what this prompt is for (DESIGN_plan_rollback.md §6.1).
        """
        mesocycles = plan_lineage(self._db, macros)
        benchmarks = self._db.get_benchmark_results()
        reports = []
        for i, meso in enumerate(mesocycles):
            text = mesocycle_report(
                meso, today_str, self._db.get_completed_activities,
                previous=mesocycles[i - 1] if i else None, benchmarks=benchmarks,
                fetch_workouts=self._db.get_workouts, width=width,
            )
            if not text:
                continue
            # Elapsed part only: a finished mesocycle ends where it ended, the current one at
            # today. Both sides of every week line are cut to the same span.
            elapsed_end = min(today_str, meso['end_date'])
            weeks = self._mesocycle_week_lines(
                meso, today_str, elapsed_end,
                self._db.get_workouts(start_date=meso['start_date'], end_date=elapsed_end),
                indent="      ",
            )
            if weeks:
                text += "\n    Weekly load (what the plan asked -> what was produced)\n"
                text += "\n".join(weeks)
            reports.append(text)
        return reports

    def _build_prior_training_context(
        self, prior_macros: List[Optional[Dict[str, Any]]], today_str: str,
        width: int = zone_tables.PROMPT_WIDTH,
    ) -> Optional[str]:
        """Builds a read-only "planned vs actual" review for the strategy prompt
        (DESIGN_backward_evaluation.md §6, Option A).

        Anchored on the *elapsed* mesocycle windows of every plan given AND of the plan the
        athlete is currently in (§6, §6.1): each planned mesocycle's focus is shown beside what the
        athlete actually did in that window — volume, load, the per-sport per-zone
        intensity distribution against both its mesocycle-over-mesocycle delta and what the plan
        prescribed (DESIGN_intensity_distribution.md §4.1/§9/§9.2a), and each week's
        planned load beside the load produced — so the model can judge whether the mesocycle's
        intent materialized and whether it was actually carried out. Every cached
        backward-evaluation reconstruction then follows, reused without another LLM call
        (§10, §10.2). Returns None if there is nothing to report.

        This writes nothing — not a row in the plan's feedback log either: under Option A
        the assessment is prompt context only, sidestepping the lifecycle collision (§11).
        """
        sections: List[str] = []

        # The whole review is pre-wrapped here, not at print time: the zone tables are
        # column-aligned and re-wrapping shreds them (DESIGN_intensity_distribution.md §6).
        # `width` defaults to the model's prompt width; callers rendering this for a
        # narrower surface (e.g. Telegram) pass their own to keep the tables intact there.

        # The current plan's elapsed mesocycles join the prior plans': drift diagnosed only
        # one macrocycle late is history (gap 2 of DESIGN_intensity_distribution.md §3).
        reports = self._intensity_history_context(
            [*prior_macros, self._db.get_governing_macrocycle()], today_str, width=width,
        )
        if reports:
            sections.append(
                wrap_text(
                    "PLANNED vs ACTUAL (elapsed mesocycles — judge whether each mesocycle's intent "
                    "materialized). Each mesocycle shows its planned focus beside what the "
                    "athlete's activities ACTUALLY measured, per sport and per zone, as a "
                    "per-week rate over the mesocycle's completed weeks, plus the change "
                    "against the mesocycle before it. Read the delta as the intensity-creep "
                    "check: weekly TSS can hold flat while easy volume quietly gives way "
                    "to tempo.\n"
                    "Two more comparisons decide WHOSE problem a divergence is. Against "
                    "'What the plan PRESCRIBED', a mesocycle that measures off its focus but "
                    "tracks its prescription was MIS-DESIGNED — reshape the mesocycles still "
                    "ahead; one that diverges from the prescription was mis-executed, "
                    "which the daily adaptation owns, so do not reward it by planning "
                    "the easier mesocycle it drifted toward. Against the weekly load lines, "
                    "a mesocycle whose weeks came in far under what was asked was not the "
                    "mesocycle that was planned: build the next one from the load the athlete "
                    "actually produced, not from the load they were prescribed.", width
                )
                + "\n" + "\n".join(reports)
            )

        for cached in self._cached_reconstructions():
            recon_lines = self._reconstruction_lines(cached["reconstruction"])
            if not recon_lines:
                continue
            window = ""
            if cached.get("window_start") and cached.get("window_end"):
                window = f" ({cached['window_start']}..{cached['window_end']})"
            sections.append(wrap_text(
                f"INFERRED FROM PAST TRAINING{window} — {cached['label']}:\n"
                + "\n".join(recon_lines), width
            ))

        return "\n\n".join(sections) if sections else None

    def _cached_reconstructions(self) -> List[Dict[str, Any]]:
        """The cached history analyses the strategy prompt replays, oldest window first:
        `data bootstrap`'s reconstruction, then `data reflect`'s latest one when it begins
        past bootstrap's window (DESIGN_backward_evaluation.md §10.2).

        Each row is its cache row plus a `label` naming the command behind it, and this is
        the single accessor for both what the prompt gets and how far behind it is — so the
        staleness warning can never name a window the prompt did not actually read.
        """
        out: List[Dict[str, Any]] = []
        long_row = self._db.get_analysis_cache("long")
        long_end = (long_row or {}).get("window_end") or ""
        if long_row and long_row.get("reconstruction"):
            out.append({**long_row, "label": "full history reconstruction"})
        short_row = self._db.get_analysis_cache("short")
        short_start = (short_row or {}).get("window_start") or ""
        # Replay reflect only where it covers ground bootstrap never saw. Gating on its
        # START (not its end) rejects a window that merely reaches further while re-reading
        # weeks bootstrap already read — two accounts of one body of evidence (§10.2).
        if short_row and short_row.get("reconstruction") and short_start > long_end:
            out.append({**short_row, "label": "most recent reflection"})
        return out

    @staticmethod
    def _reconstruction_lines(recon: Dict[str, Any]) -> List[str]:
        """One cached reconstruction rendered for the prompt: its summary, the
        reverse-engineered periodization structure, and the physiological insights.

        The structure is fed so the new plan can build on the real prior arc — where
        base/build/recovery fell, how consistent each mesocycle was — rather than re-deriving
        it (DESIGN_backward_evaluation.md §10).
        """
        lines: List[str] = []
        if recon.get("macrocycle_summary"):
            lines.append(f"Summary: {recon['macrocycle_summary']}")
        im = recon.get("inferred_macrocycle") or {}
        if im.get("overall_focus"):
            span = ""
            if im.get("start_date") and im.get("end_date"):
                span = f" ({im['start_date']}..{im['end_date']})"
            lines.append(f"Reconstructed macrocycle focus{span}: {im['overall_focus']}")
        for meso in (recon.get("inferred_mesocycles") or []):
            name = meso.get("name", "Phase")
            m_span = ""
            if meso.get("start_date") and meso.get("end_date"):
                m_span = f" ({meso['start_date']}..{meso['end_date']})"
            detail = []
            if meso.get("focus_detected"):
                detail.append(f"focus \"{meso['focus_detected']}\"")
            if meso.get("average_weekly_tss") is not None:
                detail.append(f"~{float(meso['average_weekly_tss']):.0f} TSS/wk")
            if meso.get("estimated_consistency"):
                detail.append(f"{meso['estimated_consistency']} consistency")
            detail_txt = f": {', '.join(detail)}" if detail else ""
            lines.append(f"- {name}{m_span}{detail_txt}")
        for ins in (recon.get("physiological_insights") or []):
            lines.append(f"- {ins}")
        return lines
