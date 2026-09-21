"""The coach service: the layer that reads the database, drives a call, and writes back.

Thirteen mixins compose one :class:`CoachService`, one file per job. The plan:
`planning.py` (`plan generate`/`apply`/`rollback`), `goals_constraints.py` (standing a
goal down, sizing a constraint, the message captures) and `staleness.py` (has the plan
been overtaken by its own inputs). The sessions: `generate.py` (`workout generate`),
`standing.py` (the sessions the athlete was already told about), `adapt.py`
(`workout adapt` and `workout tweak`), `guards.py` (the rules enforced whatever the week
planner wrote), `revision_apply.py` (how a revision lands, and the undo) and
`matching.py` (which activity was which session). What a prompt is told:
`athlete_context.py`, `history_context.py` and `mesocycle_context.py`. And
`analysis.py`, for `data bootstrap` and `data reflect`.

Callers reach every one of them through `coach_service`, so a method moving between
these files is invisible outside the package.
"""
from typing import Optional
from trainmate import runtime
from trainmate.coach.engine import CoachEngine

from trainmate.coach.service.history_context import HistoryContextMixin
from trainmate.coach.service.mesocycle_context import MesocycleContextMixin
from trainmate.coach.service.athlete_context import AthleteContextMixin
from trainmate.coach.service.staleness import StalenessMixin
from trainmate.coach.service.planning import PlanningMixin
from trainmate.coach.service.goals_constraints import GoalsConstraintsMixin
from trainmate.coach.service.generate import WorkoutGenMixin
from trainmate.coach.service.standing import StandingMixin
from trainmate.coach.service.guards import GuardsMixin
from trainmate.coach.service.adapt import AdaptMixin
from trainmate.coach.service.revision_apply import RevisionApplyMixin
from trainmate.coach.service.matching import MatchingMixin
from trainmate.coach.service.analysis import DataAnalysisMixin


class CoachService(HistoryContextMixin, MesocycleContextMixin, AthleteContextMixin,
                   StalenessMixin, PlanningMixin, GoalsConstraintsMixin,
                   WorkoutGenMixin, StandingMixin, GuardsMixin, AdaptMixin,
                   RevisionApplyMixin, MatchingMixin, DataAnalysisMixin):
    """Orchestrates sports science coaching by coordinating data I/O and business logic."""

    def __init__(
        self, db_instance=None, engine: Optional[CoachEngine] = None,
        prompt_instance=None
    ):
        self._db_instance = db_instance
        self._prompt_instance = prompt_instance
        self.engine = engine or CoachEngine()

    @property
    def _db(self):
        return self._db_instance or runtime.db

    # No calendar handle here. Writing workouts reconciles Calendar on its own, from the
    # change handle, so no command reaches the syncer any more
    # (DESIGN_workout_revisions.md §8).

    @property
    def _prompt(self):
        """The question channel, injected so the service never imports the CLI.

        It used to reach up with `import trainmate_cli as cli` mid-method, which meant
        any non-terminal frontend calling these methods got a terminal conversation.
        Whoever constructs the service now supplies the transport.
        """
        return self._prompt_instance or runtime.prompt


coach_service = CoachService()
