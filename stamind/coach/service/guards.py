"""The rules the app enforces whatever the week planner wrote.

A `rest` constraint is the one edge that never reaches the model, so its days are forced
to rest here (DESIGN_constraints.md §5, §6). Every date of a generated span must carry a
row, so an empty one is backfilled (DESIGN_runway_nudge.md §2.1). A benchmark the athlete
scheduled is not displaced by an ordinary session on its date, and a mesocycle boundary
that ended up with no benchmark is warned about rather than filled in
(DESIGN_benchmark_workouts.md §4.1). `workout generate` and `workout adapt` both pass their
sessions through these.

It is one mixin of :class:`CoachService` — see coach/service/__init__.py.
"""
from datetime import date, datetime, timedelta
from typing import Any, Dict, List, Optional, Tuple

from stamind.types import Constraint, Workout
from stamind.benchmarks import MIN_RETEST_DAYS
from stamind.sports import canonical_sport
from stamind.output import notice


class GuardsMixin:
    @staticmethod
    def _rest_workout(
        date: str, cause: str, title: str = 'Rest (forced constraint)'
    ) -> Dict[str, Any]:
        """A deterministic rest session the rest-window pre-pass places on a date the
        athlete has barred from training (DESIGN_constraints.md §6). The title/description
        are tagged "(forced constraint)" so it reads unmistakably as a code-enforced
        override rather than an ordinary planned/adapted rest day. The change_reason names
        the constraint so a later adaptation, which won't see the live constraint list in
        the same run, reads the cause back with the plan.

        `title` names which pass placed the row: the coverage backstop
        (DESIGN_runway_nudge.md §2.1) fills an ordinary "Rest Day", not a forced one."""
        return {
            'date': date,
            'sport_type': 'rest',
            'title': title,
            'description': f"[{title}]\nNo training — {cause}.",
            'duration_minutes': 0,
            'rpe': 0,
            'tss': 0,
            'change_reason': f"Rest — {cause}.",
        }

    @classmethod
    def _hard_rest_windows(
        cls, constraints: List[Constraint]
    ) -> List[Tuple[str, str, str]]:
        """The `rest` windows — the only edge that skips the LLM (§5): a full no-training
        window whose dates are forced to rest. Every other constraint is advisory prose
        the LLM honors itself, so it is deliberately excluded here. Returns
        [(start, end, title)]."""
        return [
            (c['start_date'], c['end_date'], c['title'])
            for c in constraints
            if c.get('rest')
        ]

    @classmethod
    def _enforce_rest_windows_generate(
        cls, workouts: List[Dict[str, Any]], constraints: List[Constraint], gen_start: str,
        gen_end: str, span_sessions: Optional[List[Workout]] = None
    ) -> Tuple[List[Dict[str, Any]], Dict[Tuple[str, str], str]]:
        """Forces `rest` constraints onto a freshly generated workout list (§6): every rest
        date inside the generated span becomes a single rest, deterministically, bypassing
        the LLM for that date entirely. Every other constraint is advisory only — left to
        the model via the prompt section, not enforced here (§5).

        Dates the model simply left out are filled too, not only the ones it scheduled: an
        absent row and an explicit rest day mean different things to adherence (§6). The
        span is the *requested* `gen_start`..`gen_end`, not what the model happened to
        return — a rest window at the tail of the range is exactly the case the model
        answers with silence, so bounding by its last date would reopen the gap (§6).

        The rest row continues the first session already on the date, so that day keeps
        one event and the constraint's own title is the reason on it; any further
        session there is voided under the same reason, which is what the returned
        `{slot: reason}` map carries (DESIGN_plan_change_continuity.md §5.5)."""
        full_rest = cls._hard_rest_windows(constraints)
        if not full_rest:
            return workouts, {}

        span_end = gen_end
        forced: Dict[str, str] = {}          # date -> constraint title
        for (s, e, title) in full_rest:
            day = datetime.strptime(max(s, gen_start), "%Y-%m-%d").date()
            last = datetime.strptime(min(e, span_end), "%Y-%m-%d").date()
            while day <= last:
                forced.setdefault(day.strftime("%Y-%m-%d"), title)
                day += timedelta(days=1)
        if not forced:
            return workouts, {}

        rest_sport = canonical_sport('rest')
        by_date: Dict[str, List[Workout]] = {}
        for live in span_sessions or []:
            by_date.setdefault(live['date'], []).append(live)

        out = [w for w in workouts if w.get('date', '') not in forced]
        void_reasons: Dict[Tuple[str, str], str] = {}
        for day, title in sorted(forced.items()):
            rest = cls._rest_workout(day, f"constraint '{title}'")
            rows = sorted(
                by_date.get(day, []), key=lambda w: canonical_sport(w['sport_type'])
            )
            # A rest day already on the date is the slot the rest row lands in,
            # so it is revised in place and no lineage is carried across.
            carrier = None
            sports_there = {canonical_sport(r['sport_type']) for r in rows}
            if rest_sport not in sports_there and rows:
                carrier = rows[0]
            if carrier is not None:
                rest['replaces_slot'] = (carrier['date'], carrier['sport_type'])
                rest['replaces_lineage'] = carrier['id']
            for row in rows:
                slot = (row['date'], canonical_sport(row['sport_type']))
                if row is carrier or slot[1] == rest_sport:
                    continue
                void_reasons[slot] = rest['change_reason']
            out.append(rest)
        return out, void_reasons

    @classmethod
    def _fill_coverage_gaps(
        cls, workouts: List[Dict[str, Any]], gen_start: str, gen_end: str
    ) -> List[Dict[str, Any]]:
        """Writes an explicit rest row on every date of the span the proposal left empty,
        so generation covers its whole span by construction (DESIGN_runway_nudge.md §2.1).

        That coverage is what lets the end of the schedule be read straight off the rows:
        a hole then means the schedule stopped, never a rest day the model didn't bother
        to name. A proposal with no sessions at all is left alone — an empty answer is a
        failed generation, and a span of rest is not the way to salvage it."""
        if not workouts:
            return workouts
        covered = {w.get('date', '') for w in workouts}
        day = datetime.strptime(gen_start, "%Y-%m-%d").date()
        last = datetime.strptime(gen_end, "%Y-%m-%d").date()
        filled = list(workouts)
        while day <= last:
            date_str = day.strftime("%Y-%m-%d")
            day += timedelta(days=1)
            if date_str in covered:
                continue
            filled.append(cls._rest_workout(
                date_str, "no session planned for this day", title='Rest Day'
            ))
        return filled

    @classmethod
    def _forced_rest_days(
        cls, planned_workouts: List[Workout], constraints: List[Constraint],
        completed_keys: Optional[set], from_date: str
    ) -> Dict[str, str]:
        """`date -> constraint title` for the days a `rest` constraint clears outright.

        One reading of the rule, because two callers act on it: the pass below replaces
        those days with rest, and the adaptation drops anything it was holding there."""
        full_rest = cls._hard_rest_windows(constraints)
        if not full_rest:
            return {}
        completed = completed_keys or set()
        rest_sport = canonical_sport('rest')

        forced_rest: Dict[str, str] = {}
        for w in planned_workouts:
            day = w.get('date', '')
            if day < from_date:
                continue
            sport = canonical_sport(w.get('sport_type', ''))
            if sport == rest_sport or (day, sport) in completed:
                continue
            fr = next((t for (s, e, t) in full_rest if s <= day <= e), None)
            if fr is not None:
                forced_rest[day] = fr
        return forced_rest

    @classmethod
    def _enforce_rest_windows_revision(
        cls, adapted: List[Dict[str, Any]], planned_workouts: List[Workout],
        constraints: List[Constraint], completed_keys: Optional[set], from_date: str
    ) -> List[Dict[str, Any]]:
        """Eases planned sessions to rest on `rest` constraint dates (§6). Every other
        constraint is advisory only (§5) — left to the model, not enforced here. Only
        touches sessions on or after `from_date` that aren't already rest or completed."""
        forced_rest = cls._forced_rest_days(
            planned_workouts, constraints, completed_keys, from_date
        )
        if not forced_rest:
            return adapted

        cleaned = []
        for w in adapted:
            day = w.get('date', '')
            if day in forced_rest:
                continue  # whole day replaced with rest below
            cleaned.append(w)

        for day, title in sorted(forced_rest.items()):
            cleaned.append(cls._rest_workout(day, f"constraint '{title}'"))
        return cleaned

    @staticmethod
    def _drop_benchmark_collisions(
        workouts: List[Dict[str, Any]]
    ) -> List[Dict[str, Any]]:
        """Same-day collision rule (§4.1): save_workout keys on (date, sport), so a second
        same-sport session on a benchmark's date would silently overwrite the test. On a
        date holding a benchmark of sport X, drop any OTHER proposed sport-X session and
        warn. The benchmark is identified by its flag — no guessing."""
        # date -> {canonical sport with a benchmark that day}
        bench_sports: Dict[str, set] = {}
        for w in workouts:
            if w.get('benchmark_type'):
                bench_sports.setdefault(w.get('date', ''), set()).add(
                    canonical_sport(w.get('sport_type', ''))
                )
        if not bench_sports:
            return workouts
        out: List[Dict[str, Any]] = []
        for w in workouts:
            day = w.get('date', '')
            sport = canonical_sport(w.get('sport_type', ''))
            if (not w.get('benchmark_type')
                    and sport in bench_sports.get(day, set())):
                notice(
                    f"Dropping {w.get('sport_type', '')} session on {day}: it collides "
                    f"with a scheduled benchmark of the same sport.",
                )
                continue
            out.append(w)
        return out

    def _event_date_for_macrocycle(self, macrocycle_id: int) -> Optional[date]:
        """The event date a macrocycle's boundary tests must keep clear of — None when
        unresolvable, and None for a horizon goal, whose date has no event a test could
        compete with."""
        macro = self._db.get_macrocycle(macrocycle_id)
        if not macro:
            return None
        objective = self._db.get_objective(macro.get('objective_id'))
        if (objective or {}).get('date_type') == 'horizon':
            return None
        target = (objective or {}).get('target_date')
        if not target:
            return None
        try:
            return datetime.strptime(target, "%Y-%m-%d").date()
        except ValueError:
            return None

    def _warn_missing_boundary_benchmarks(
        self, workouts: List[Dict[str, Any]], constraints: List[Constraint],
        mesocycles: List[Dict[str, Any]], gen_start: str
    ) -> None:
        """Boundary-week post-check (§4.1): warn — don't auto-insert — when a covered
        mesocycle-boundary week ended up with no benchmark. Same spirit as the rest-window
        pass, but a surfaced warning the athlete can act on (regenerate), not a silent fix.
        Stays quiet when the boundary week sits under a `rest` constraint — rest wins — and
        for a boundary week reaching into the goal's own week, where a maximal test would
        compete with the event it is meant to serve (§4.1).

        `mesocycles` govern this span, which may come from more than one
        plan when a long horizon runs from one goal into the next — so the goal week that
        silences a test is read per mesocycle, not once for the run."""
        if not workouts or not mesocycles:
            return
        dated = [w for w in workouts if w.get('date')]
        span_end = max(w['date'] for w in dated)
        rest_windows = self._hard_rest_windows(constraints)
        for m in mesocycles:
            end = m.get('end_date', '')
            # Only boundary weeks whose end falls inside the generated span.
            if not (gen_start <= end <= span_end):
                continue
            end_obj = datetime.strptime(end, "%Y-%m-%d").date()
            # Goal week wins: a boundary week ending inside it gets no test (§4.1) —
            # unless the goal is a horizon, which has no event week to protect.
            goal_obj = self._event_date_for_macrocycle(m['macrocycle_id'])
            if goal_obj and end_obj > goal_obj - timedelta(days=7):
                continue
            win_start = (end_obj - timedelta(days=6)).strftime("%Y-%m-%d")
            # Rest wins: a full-rest window overlapping the boundary week silences the check.
            if any(s <= end and e >= win_start for (s, e, _t) in rest_windows):
                continue
            # A test already run earlier in this boundary week counts (§4.1): regenerating
            # mid-boundary-week would otherwise advise regenerating again to recover a
            # benchmark the athlete has already done. Bounded below gen_start because the
            # displaced plan's future rows are still live here — only an accepted proposal
            # archives them — and would answer for sessions this run proposes to replace.
            already_run = any(
                w.get('benchmark_type') and win_start <= w['date'] < gen_start
                for w in self._db.get_workouts(start_date=win_start, end_date=end)
            )
            has_benchmark = already_run or any(
                w.get('benchmark_type') and win_start <= w['date'] <= end
                for w in dated
            )
            if has_benchmark:
                continue
            # The science/benchmarks.md §1 interval floor wins: a test inside
            # MIN_RETEST_DAYS of this boundary means none is due here, so warning would
            # nag the athlete into violating the floor the generator just honored. Any
            # anchor silences — the check cannot know which anchor a missing test would
            # have measured, and a false silence costs one un-nudged athlete where a
            # false nag contradicts the plan.
            recent_start = (
                end_obj - timedelta(days=MIN_RETEST_DAYS)
            ).strftime("%Y-%m-%d")
            recent_test = (
                any(w.get('benchmark_type') and recent_start <= w['date'] < win_start
                    for w in dated)
                or any(
                    w.get('benchmark_type') and w['date'] < gen_start
                    for w in self._db.get_workouts(
                        start_date=recent_start, end_date=end)
                )
                or any(
                    r.get('source') == 'test' and recent_start <= r['date'] <= end
                    for r in self._db.get_benchmark_results()
                )
            )
            if not recent_test:
                notice(
                    f"No benchmark scheduled in the boundary week of '{m.get('name', '')}' "
                    f"({win_start} to {end}), and none tested in the {MIN_RETEST_DAYS} "
                    f"days before it. If a test is due, consider regenerating.",
                )
