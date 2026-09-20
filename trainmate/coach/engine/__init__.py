from trainmate.openrouter import openrouter_client

from trainmate.coach.engine.prompt import PromptBuildMixin
from trainmate.coach.engine.planning import PlanStrategyMixin
from trainmate.coach.engine.workouts import WorkoutLogicMixin
from trainmate.coach.engine.analysis import AnalysisLogicMixin


class CoachEngine(PromptBuildMixin, PlanStrategyMixin, WorkoutLogicMixin, AnalysisLogicMixin):
    """Pure business logic coach that builds prompts, computes hashes, and makes LLM calls."""
