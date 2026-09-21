"""The mesocycle under way, as `workout generate` and `workout adapt` are shown it.

It is the third week of a four-week base mesocycle, and the week planner is about to
write the days that are left. First it is shown what the two weeks behind it actually
held: the measured intensity distribution beside what the plan prescribed and beside the
mesocycle before it (DESIGN_intensity_distribution.md §9.2a), each trained week's planned
load beside the load produced, the fitness tests the mesocycle has already run, and where
each anchor stands (DESIGN_mesocycle_progress.md §3).

The training further back than this mesocycle is `history_context.py`. It is one mixin of
:class:`CoachService` — see coach/service/__init__.py.
"""
from datetime import datetime, timedelta
from typing import Any, Dict, List, Optional, Tuple

from stamind.types import Workout
from stamind.analytics import intensity, progression, timeline
from stamind.analytics.mesocycle_report import format_header, measured_window, mesocycle_report
from stamind.benchmarks import format_value, label_for_kind
from stamind.text import wrap_text
from stamind.clock import days_between


class MesocycleContextMixin:
    def _intensity_mesocycle_context(self, as_of: str) -> Optional[str]:
        """The active mesocycle's measured intensity distribution for `adapt`
        (DESIGN_intensity_distribution.md §9.3): the mesocycle to date as a per-week rate
        beside its stated focus, plus the current week's raw minutes.

        No preceding mesocycle and no delta — mesocycle-over-mesocycle creep is a periodization
        question, and §9.2 gives those to `generate`. Returns None when today falls
        outside every mesocycle — the next FUTURE mesocycle would render an empty table for
        training that has not happened (§8).
        """
        meso = self._db.get_covering_mesocycle(as_of)
        if not meso:
            return None
        return mesocycle_report(
            meso, as_of, self._db.get_completed_activities,
            current_week=True, benchmarks=self._db.get_benchmark_results(),
        )

    # ----------------------------------------------------------- mesocycle progress
    def _mesocycle_progress_context(
        self, as_of: str, gen_start: str
    ) -> Tuple[Optional[str], bool]:
        """The elapsed part of the mesocycle `generate` is about to re-plan the remainder of
        (DESIGN_mesocycle_progress.md §3): its measured intensity distribution beside what the
        plan prescribed and beside the preceding mesocycle, each already-trained week's
        planned-vs-actual load, and the fitness tests the mesocycle has already run.

        Returns `(text, has_intensity)`, a pair like `_pmc_prompt_context`'s: the
        composition TASK section quotes the zone tables, so it must be gated on those
        tables actually having rows rather than on the section merely existing (§5.1).

        `text` is None when there is no fulfilled part to report — `as_of` outside every
        mesocycle (a future or first mesocycle would describe training that has not happened),
        or `gen_start` on/before the mesocycle's first day, where generate IS writing the
        whole mesocycle and has nothing to continue.
        """
        meso = self._db.get_covering_mesocycle(as_of)
        if not meso:
            return None, False
        elapsed_end = (
            datetime.strptime(gen_start, "%Y-%m-%d").date() - timedelta(days=1)
        ).strftime("%Y-%m-%d")
        if elapsed_end < meso['start_date']:
            return None, False

        # Fetched once and handed to both renderers: they read the same rows, and the week
        # lines and the test lines must never disagree about what the mesocycle contains.
        workouts = self._db.get_workouts(start_date=meso['start_date'], end_date=elapsed_end)
        weeks = self._mesocycle_week_lines(meso, as_of, elapsed_end, workouts)
        benchmarks = self._mesocycle_benchmark_lines(meso, elapsed_end, workouts)
        # Everything is anchored on gen_start, not as_of: history ends the day before the
        # first day being written, so the header's "N completed weeks", the week lines and
        # the zone windows all count the same days. The two differ by one on the run that
        # preserves an already-completed session and starts tomorrow.
        report = mesocycle_report(
            meso, gen_start, self._db.get_completed_activities,
            current_week=True, previous=self._preceding_mesocycle(meso),
            benchmarks=self._db.get_benchmark_results(),
            fetch_workouts=self._db.get_workouts, indent="",
        )
        # Gated on banked evidence, NOT on `report`: a started mesocycle with nothing recorded
        # still yields a report ("no completed activities in ..."), and pairing that with a
        # task section about carrying a ramp on from the last completed week describes a
        # week that does not exist. Generate already sees the empty activity list.
        if not weeks and not benchmarks:
            return None, False

        # `mesocycle_report` opens with the same `format_header` line, so it stands in for the
        # header when present rather than being stacked under a second copy of it.
        lines = [report] if report else [format_header(meso, gen_start)]
        if weeks:
            lines.append("  Weeks already trained (load the plan asked -> load produced):")
            lines.extend(weeks)
        if benchmarks:
            lines.append("  Fitness tests this mesocycle has already run:")
            lines.extend(benchmarks)
        return "\n".join(lines), bool(report) and self._mesocycle_has_zone_rows(meso, gen_start)

    def _mesocycle_has_zone_rows(self, meso: Dict[str, Any], as_of: str) -> bool:
        """Whether the mesocycle's zone table will have rows — asked of the same window
        `mesocycle_report` builds that table from, via `mesocycle_report.measured_window`, so the
        prompt's gate and the table can never disagree (§5.1)."""
        win_start, win_end, _ = measured_window(
            meso['start_date'], meso['end_date'], as_of
        )
        return bool(intensity.zone_rows(
            self._db.get_completed_activities(start_date=win_start, end_date=win_end)
        ))

    def _preceding_mesocycle(
        self, meso: Dict[str, Any]
    ) -> Optional[Dict[str, Any]]:
        """The mesocycle immediately before `meso` in its own macrocycle, for the
        mesocycle-over-mesocycle delta — the periodization signal proper (§5).

        Navigated by macrocycle id rather than by a date-ordered mesocycle query
        (DESIGN_plan_rollback.md §6.1).
        """
        mesocycles = self._db.get_mesocycles_for_macrocycle(meso['macrocycle_id'])
        earlier = [b for b in mesocycles if b['start_date'] < meso['start_date']]
        return max(earlier, key=lambda b: b['start_date']) if earlier else None

    def _mesocycle_week_lines(
        self, meso: Dict[str, Any], as_of: str, elapsed_end: str,
        workouts: List[Workout], indent: str = "    ",
    ) -> List[str]:
        """One planned-vs-actual line per Monday-week of the mesocycle's elapsed part.

        Reuses `progression.weekly_aggregates`, the same planned-vs-actual weekly maths
        `sm progress` renders, so the week planner and the athlete never read different numbers
        for the same week (§3.1). The in-progress week states raw load beside the elapsed
        day count and is never extrapolated, following
        DESIGN_intensity_distribution.md §9.3.

        `indent` only differs because the two prompts nest their reports differently: the
        strategy prompt sits each report one level in, since it sends several.
        """
        activities = self._db.get_completed_activities(
            start_date=meso['start_date'], end_date=elapsed_end
        )
        weeks = progression.weekly_aggregates(
            activities, workouts, as_of, timeline.meso_bands([meso], []),
            window_end=elapsed_end,
        )
        out: List[str] = []
        for w in weeks:
            when, actual = w['week_commencing'], w['actual_load']
            denom = progression.week_plan_denom(w)
            if w['in_progress']:
                elapsed = min(7, days_between(when, elapsed_end) + 1)
                head = f"{indent}- week of {when} (in progress, {elapsed} of 7 days)"
            else:
                head = f"{indent}- week of {when}"
            if denom is None:
                out.append(f"{head}: actual {actual:.0f}, no plan covered this week")
                continue
            pct = f" ({actual / denom * 100:.0f}%)" if denom else ""
            asked = f"planned {denom:.0f}" + (" so far" if w['in_progress'] else "")
            # Partiality is judged against the MESOCYCLE, not against `partial_plan`: that flag
            # compares the week to the workout rows handed in, so a Monday the athlete had
            # no session on would read as "the plan starts mid-week" when it does not. Only
            # a week the mesocycle itself straddles is genuinely incomparable. The in-progress
            # week is always cut short by design, and its day count already says so.
            note = (
                " [mesocycle covers only part of this week]"
                if when < meso['start_date'] and not w['in_progress'] else ""
            )
            out.append(f"{head}: {asked}, actual {actual:.0f}{pct}{note}")
            sport_note = self._week_sport_gap_note(w, denom, actual)
            if sport_note:
                # A week with several sports can run past the 100-char prompt-wide wrap
                # convention (AGENTS.md) that the single blended line above never risks.
                out.append(wrap_text(f"{indent}    {sport_note}"))
        return out

    def _week_sport_gap_note(
        self, week: Dict[str, Any], denom: Optional[float], actual: float,
    ) -> Optional[str]:
        """Per-sport breakdown for a week whose planned-vs-actual TOTAL hides which
        sport actually drove it — a shortfall concentrated in one sport (e.g. missed
        strength) reads as generalized under-training when only the blended total is
        shown, even though the sport the athlete's goal depends on may be fully on
        plan (DESIGN_mesocycle_progress.md §3.3: CTL/ATL/TSB is one blended stream across
        all sports by design, DESIGN_pmc_fitness_fatigue.md's out-of-scope list; this
        note is the cheap per-sport cross-check the blended total can't give alone).

        The trigger is deliberately NOT "the blended total is far from 100%": a week
        can blend a fully-on-plan sport with a fully-missed one and still land near
        90% overall (100/205 cycling offsetting 0/32 strength) — exactly the case
        this note exists for. Instead it fires when some sport's OWN adherence rate
        is >=20 points off the blended rate, i.e. that sport is not telling the same
        story as the total. 20 points matches no other threshold in this file —
        chosen as clearly outside normal week-to-week noise between sports."""
        if not denom or actual <= 0:
            return None
        planned_by_sport = progression.week_plan_denom_by_sport(week) or {}
        actual_by_sport = week.get("actual_load_by_sport", {})
        sports = sorted(set(planned_by_sport) | set(actual_by_sport))
        if len(sports) < 2:
            return None
        overall_pct = actual / denom * 100
        sport_pcts = [
            actual_by_sport.get(sport, 0.0) / planned_by_sport[sport] * 100
            for sport in sports if planned_by_sport.get(sport)
        ]
        if not sport_pcts or max(abs(p - overall_pct) for p in sport_pcts) < 20:
            return None
        parts = []
        for sport in sports:
            sport_planned = planned_by_sport.get(sport, 0.0)
            sport_actual = actual_by_sport.get(sport, 0.0)
            if not sport_planned and not sport_actual:
                continue
            sport_pct = f" ({sport_actual / sport_planned * 100:.0f}%)" if sport_planned else ""
            parts.append(f"{sport}: {sport_actual:.0f}/{sport_planned:.0f}{sport_pct}")
        return "of which " + ", ".join(parts) if parts else None

    def _mesocycle_benchmark_lines(
        self, meso: Dict[str, Any], elapsed_end: str, workouts: List[Workout],
    ) -> List[str]:
        """The fitness tests the mesocycle's elapsed part already ran — what makes the
        generate prompt's BENCHMARK PLACEMENT conditional rather than unconditional
        (DESIGN_benchmark_workouts.md §4).

        Keyed on the planned benchmark sessions, not the logbook: a test the athlete
        performed but never recorded still must not be scheduled twice. A logbook row is
        matched to its session by `workout_id`, falling back to a same-date reading for a
        result recorded without the link; unmatched in-mesocycle rows are reported as ad-hoc
        tests.
        """
        start = meso['start_date']
        planned = [w for w in workouts if w.get('benchmark_type')]
        results = self._db.get_benchmark_results()
        by_workout = {r['workout_id']: r for r in results if r.get('workout_id')}
        in_mesocycle = [r for r in results if start <= r['date'] <= elapsed_end]

        def measured(r: Dict[str, Any]) -> str:
            label = label_for_kind(r['anchor_kind'])
            return f"{label} {format_value(r['anchor_kind'], float(r['value']))}"

        out: List[str] = []
        claimed = set()
        for w in sorted(planned, key=lambda w: w['date']):
            r = by_workout.get(w['id']) or next(
                (x for x in in_mesocycle if x['date'] == w['date']), None
            )
            if r:
                claimed.add(r['id'])
            out.append(
                f"    - {w['date']}: {w['benchmark_type']} ({w['sport_type']}) — "
                + (measured(r) if r else "no result recorded")
            )
        for r in sorted(
            (x for x in in_mesocycle if x['id'] not in claimed), key=lambda r: r['date']
        ):
            out.append(f"    - {r['date']}: {measured(r)} recorded (no planned test)")
        return out

    def _anchor_history_text(self, gen_start: str) -> str:
        """ANCHORS ON RECORD: each anchor's latest value with its date, source and the
        athlete's note (which names the protocol) — the dates BENCHMARK PLACEMENT's
        interval floor is judged against (DESIGN_benchmark_workouts.md §4.1). Planned test
        sessions count too, like §4.1's de-dup: a test performed but never recorded must
        still hold the interval. Bounded below `gen_start` — the displaced plan's future
        rows are live here and must not answer for days this run is rewriting."""
        lines: List[str] = []
        latest: Dict[str, Dict[str, Any]] = {}
        tested: Dict[str, str] = {}
        for r in self._db.get_benchmark_results():  # newest first
            latest.setdefault(r['anchor_kind'], r)
            if r.get('source') == 'test':
                tested.setdefault(r['anchor_kind'], r['date'])
        for kind, r in latest.items():
            label = label_for_kind(kind)
            when = (f"last tested {tested[kind]}" if kind in tested
                    else "never measured by a test")
            line = (
                f"  - {label}: {format_value(kind, float(r['value']))} — recorded "
                f"{r['date']} ({r.get('source', 'test')}); {when}"
            )
            if r.get('note'):
                line += f"; athlete's note: \"{r['note']}\""
            lines.append(line)
        # Tests on the calendar in the typical-cadence horizon (benchmarks.md §1).
        lookback = (
            datetime.strptime(gen_start, "%Y-%m-%d").date() - timedelta(days=90)
        ).strftime("%Y-%m-%d")
        for w in self._db.get_workouts(start_date=lookback, end_date=gen_start):
            if w.get('benchmark_type') and w['date'] < gen_start:
                lines.append(
                    f"  - Planned test on the calendar: {w['date']} "
                    f"{w['benchmark_type']} ({w['sport_type']})"
                )
        return "\n".join(lines)

    def _planning_zone_currencies(self, as_of: str) -> Dict[str, str]:
        """`{sport: 'power'|'hr'}` for the sports the week planner may prescribe zone targets in
        (DESIGN_intensity_distribution.md §9.8).

        §9.6's currency rule needs a window and authoring has none — at generation time
        there is only forward plan — so it borrows the display default of 8 trailing
        weeks, and the ordinary case agrees by construction. The transient worth naming
        is the athlete who has just bought a power meter: trailing coverage still says HR
        while the display flips to power as the meter's weeks accumulate, so the future
        half of the table goes dark until the next `workout generate` re-picks the
        currency from fresh coverage. Self-healing, on the same rolling horizon that
        regenerates everything else.
        """
        start = (
            datetime.strptime(as_of, "%Y-%m-%d").date()
            - timedelta(days=7 * intensity.PLANNING_COVERAGE_WEEKS)
        ).strftime("%Y-%m-%d")
        return intensity.currency_by_sport(
            self._db.get_completed_activities(start_date=start, end_date=as_of)
        )
