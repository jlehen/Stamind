"""Which activity was which session, and what the athlete ruled about it.

Garmin recorded a 52-minute ride on Thursday and the plan had a 60-minute ride that day,
so the two are paired. Sometimes the pairing is a guess thin enough that the coach should
not act on it — and a wrong pairing does not merely mislabel a row, it tells the week
planner a session was performed. So the athlete is asked first, their answer is stored,
and the same guess is never offered twice. The asking is the adapt CLI's, before the
model call; `workout adapt` only reads what was already answered. `workout generate` and
`--strength-only` put the same pairing to a narrower question — was today's session
performed, so that a regeneration leaves it standing rather than overwriting history.

The pairing itself is `analytics/adherence.py`. It is one mixin of
:class:`CoachService` — see coach/service/__init__.py.
"""
from datetime import datetime, timedelta
from typing import Any, Dict, List, Optional

from stamind.config import config
from stamind.analytics.adherence import analyze_adherence
from stamind.sports import canonical_sport
from stamind.clock import today_str as _today_str


class MatchingMixin:
    def _today_workout_completed(
        self, today_str: str, completed_activities: List[Dict[str, Any]]
    ) -> bool:
        """Returns True when today's planned session has a matching completed activity.

        Used by `workout_generate` to decide whether to protect today's workout from a
        regeneration: a session already in the books should be kept as history rather
        than overwritten. Completion is decided by `analyze_adherence` over a one-day
        window so it uses the exact same planned-vs-completed sport matching as the rest
        of the app. A day counts as completed only when a non-rest planned workout for
        today is paired with an activity; rest days and empty days have nothing to protect.
        """
        planned = [
            w for w in self._db.get_workouts(start_date=today_str, end_date=today_str)
            if w['sport_type'] != 'rest'
        ]
        if not planned:
            return False
        today_date_obj = datetime.strptime(today_str, "%Y-%m-%d").date()
        _, matching, _ = analyze_adherence(
            planned_workouts=planned,
            completed_activities=completed_activities or [],
            start_date_obj=today_date_obj,
            history_days=1,
            minor_activity_load_threshold=config.minor_activity_load_threshold,
        )
        return any(r['completed'] for r in matching)

    def _rejected_matches(self) -> set:
        """The `(activity_id, sport)` pairings the athlete has said are NOT that session."""
        return {
            key for key, accepted in self._db.get_match_decisions().items()
            if not accepted
        }

    def pending_match_questions(
        self, target_date_str: Optional[str] = None
    ) -> List[Dict[str, Any]]:
        """Pairings in the adapt window that are a guess and that the athlete has not yet
        ruled on — `adherence.is_ambiguous_match` (ARCHITECTURE.md §15).

        Asked BEFORE the LLM call, because a wrong pairing does not merely mislabel a row:
        it tells the week planner a session was performed. Each entry carries the planned session
        and the activity so the caller can render the question without re-deriving it.
        """
        if not target_date_str:
            target_date_str = _today_str()
        target_date_obj = datetime.strptime(target_date_str, "%Y-%m-%d").date()
        history_days = config.metrics_lookback_days
        start_date_obj = target_date_obj - timedelta(days=history_days - 1)
        start_date_str = start_date_obj.strftime("%Y-%m-%d")

        active_meso = self._db.get_active_mesocycle(target_date_str)
        end_date_str = active_meso['end_date'] if active_meso else target_date_str
        planned = [
            w for w in self._db.get_workouts(
                start_date=start_date_str, end_date=end_date_str, include_removed=True
            ) if not w.get('removed')
        ]
        activities = self._db.get_completed_activities(
            start_date=start_date_str, end_date=target_date_str
        )

        # Pair with NO rejections applied: a pairing already answered "no" would other-
        # wise vanish before we could tell it apart from one never asked about.
        _d, matching_results, _i = analyze_adherence(
            planned_workouts=planned,
            completed_activities=activities,
            start_date_obj=start_date_obj,
            history_days=history_days,
            minor_activity_load_threshold=config.minor_activity_load_threshold,
            covered_ranges=self._db.get_mesocycle_ranges(start_date_str, target_date_str),
            pending_from=target_date_str,
        )

        decided = self._db.get_match_decisions()
        questions = []
        for m in matching_results:
            if not m.get("ambiguous"):
                continue
            act = m["completed"]
            sport = canonical_sport(m["planned"]["sport_type"])
            if (act["activity_id"], sport) in decided:
                continue
            questions.append({
                "activity_id": act["activity_id"],
                "sport": sport,
                "date": m["date"],
                "planned": m["planned"],
                "completed": act,
            })
        return questions

    def record_match_decision(
        self, activity_id: str, sport: str, accepted: bool
    ) -> None:
        """Persists one answer, so the question is asked once rather than every run and
        every adherence surface reads the same pairing."""
        self._db.save_match_decision(activity_id, canonical_sport(sport), accepted)
