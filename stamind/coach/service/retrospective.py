"""The write step: a due retrospective record gets its numbers, its lines and its sentence
(DESIGN_cycle_retrospective.md §5).

Which records exist and when one is due is `stamind/cycle_records.py`; the writer's prompt
is `coach/engine/retrospective.py`.

It is one mixin of :class:`CoachService` — see coach/service/__init__.py.
"""
from typing import Any, Dict, List, Optional

from stamind import cycle_records, runtime
from stamind.analytics.adherence import PARTIAL
from stamind.analytics.compare import adherence_verdicts
from stamind.analytics.load import activity_load, planned_load
from stamind.clock import today_str as _today_str
from stamind.output import step
from stamind.sports import canonical_sport
from stamind.text import cyan


class RetrospectiveMixin:
    def retrospectives_step(self) -> None:
        """The date check, then the write step, as a command runs them at its start
        (§3, §5). A failure never stops the command: the next run tries again."""
        today = _today_str()
        try:
            cycle_records.date_check(self._db, today)
            self._write_due_retrospective(today)
        except Exception as e:
            step(f"Could not bring the retrospectives up to date: {e}")

    def _write_due_retrospective(self, today: str) -> None:
        """Writes one due record, the oldest first."""
        from stamind.openrouter import openrouter_client
        if openrouter_client.show_prompt_only:
            # That flag shows the command's own prompt; the writer would print its prompt
            # instead and exit before the one being asked for.
            return
        due = [r for r in self._db.get_retrospectives() if cycle_records.is_due(r, today)]
        if due:
            self.write_retrospective(due[0])

    def write_retrospective(
        self, record: Dict[str, Any], wait_notice: Optional[str] = None
    ) -> str:
        """Writes one record and returns its sentence for the athlete: refreshes Garmin for
        the record's days, computes the numbers, calls the writer and stores the result.

        Raises when the writer fails, and the record then keeps what it held (§9)."""
        today = _today_str()
        start, end = record['start_date'], record['end_date']
        step(f"Writing the retrospective of '{record['name']}' ({start} to {end})...", cyan)
        runtime.garmin.ensure_data(start, end)
        numbers = self._retrospective_numbers(start, end, today)
        mesocycle = {
            'name': record['name'], 'start_date': start, 'end_date': end,
            'focus': record['intent'],
        }
        result = self.engine._retrospective_writer(
            record, today,
            measured=self._mesocycle_review(
                mesocycle, today, benchmarks=self._db.get_benchmark_results()
            ) or "",
            constraints=self._db.get_constraints(start, end),
            signals=self._db.get_daily_signals(start, end),
            spoken_workouts=[
                w for w in self._db.get_workouts(start_date=start, end_date=end)
                if w['athlete_notes']
            ],
            wait_notice=wait_notice,
        )
        body = str(result.get('record') or "").strip()
        if not body:
            raise ValueError("the retrospective writer returned no record")
        athlete_line = str(result.get('athlete_line') or "").strip()
        self._db.write_retrospective(record['id'], numbers, body, athlete_line)
        return athlete_line

    def _retrospective_numbers(self, start: str, end: str, today: str) -> Dict[str, Any]:
        """The values a mesocycle record's first line shows, exact, as totals over its own
        days (§5)."""
        rest = canonical_sport('rest')
        planned = [
            w for w in self._db.get_workouts(start_date=start, end_date=end)
            if canonical_sport(w['sport_type']) != rest
        ]
        verdicts = adherence_verdicts(self._db, start, end, today)
        done = [
            w for w in planned
            if (verdicts.get(w['id']) or {}).get('status') in ("done", PARTIAL)
        ]
        activities = self._db.get_completed_activities(start_date=start, end_date=end)
        fitness = {m['date']: m.get('ctl') for m in self._db.get_metrics_cache(start, end)}
        return {
            'sessions_done': len(done),
            'sessions_planned': len(planned),
            'duration_sec': sum(float(a.get('duration_sec') or 0.0) for a in activities),
            'load_planned': sum(planned_load(w) for w in planned),
            'load_done': sum(activity_load(a) for a in activities),
            'fitness_start': fitness.get(start),
            'fitness_end': fitness.get(end),
            'benchmarks': self._benchmark_changes(start, end),
        }

    def _benchmark_changes(self, start: str, end: str) -> List[Dict[str, Any]]:
        """Each benchmark with a result in the window: its latest value there, and the
        latest one before the window, None when it is the first on record."""
        by_kind: Dict[str, List[Dict[str, Any]]] = {}
        # The logbook comes newest first.
        for row in reversed(self._db.get_benchmark_results()):
            by_kind.setdefault(row['anchor_kind'], []).append(row)
        changes = []
        for kind in sorted(by_kind):
            inside = [r for r in by_kind[kind] if start <= r['date'] <= end]
            if not inside:
                continue
            before = [float(r['value']) for r in by_kind[kind] if r['date'] < start]
            changes.append({
                'kind': kind,
                'before': before[-1] if before else None,
                'after': float(inside[-1]['value']),
            })
        return changes
