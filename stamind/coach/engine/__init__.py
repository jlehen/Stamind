"""The coach engine: the prompts, the model call, and the patch seam the tests use.

The files are `prompt.py` (the shared system prompt), `planning.py` (`plan generate`),
`analysis.py` (the weekly history analysis), and the week planner's four:
`sessions.py` (the sections both week-planner prompts share), `notes.py` (the sections
about the athlete's words), `generate.py` (`workout generate`) and `adapt.py`
(`workout adapt` and `workout tweak`).

Every file here that calls the model reaches it through `_eng.openrouter_client`, looked
up when it is called, so that `patch("stamind.coach.engine.openrouter_client")` reaches
all of them. `sessions.py` and `notes.py` are prompt text only and call nothing.
"""
from stamind.openrouter import openrouter_client

from stamind.coach.engine.prompt import PromptBuildMixin
from stamind.coach.engine.planning import PlanStrategyMixin
from stamind.coach.engine.generate import WorkoutGenerateMixin
from stamind.coach.engine.adapt import WorkoutAdaptMixin
from stamind.coach.engine.analysis import AnalysisLogicMixin


class CoachEngine(
    PromptBuildMixin, PlanStrategyMixin, WorkoutGenerateMixin, WorkoutAdaptMixin,
    AnalysisLogicMixin,
):
    """Pure business logic coach that builds prompts, computes hashes, and makes LLM calls."""
