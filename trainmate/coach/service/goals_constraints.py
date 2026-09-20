"""Goals and constraints: standing a goal down, and sizing what gets in its way.

The two things that shape a plan without being one. A goal can be archived — its sessions
stood down and its plan left intact — and reinstated, which recovers only what is still
ahead. A constraint is sized before it is written: how much planned load its window
displaces, and whether that is enough for the plan itself to want rebuilding. This file
also holds the two captures, where a constraint or a signal the athlete typed into a
message becomes a row.

It is one mixin of :class:`CoachService` — see coach/service/__init__.py.
"""
from datetime import datetime, timedelta
from typing import Any, Dict, List, Optional, Tuple

from trainmate.config import config
from trainmate.analytics.load import planned_load
from trainmate.sports import canonical_sport
from trainmate import signals
from trainmate.clock import today_str as _today_str


class GoalsConstraintsMixin:
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
        today_str = _today_str()
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
        today_str = _today_str()
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
        # As in `plan rollback` (DESIGN_plan_rollback.md §8): the restored sessions
        # predate any honoring made while the goal was stood down, so they cannot
        # reflect it.
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
        window_start = max(start, _today_str())
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
