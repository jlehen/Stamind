"""SQLite persistence layer.

One ``Database`` class, assembled here from a mixin per domain so no one file holds the
whole schema's worth of methods. Nothing else is exported: the process-wide handle is
``runtime.db``, which is what every caller reads.
"""

from trainmate.db.base import BaseDB, SettingsMixin
from trainmate.db.schema import SchemaMixin
from trainmate.db.objectives import ObjectivesMixin
from trainmate.db.constraints import ConstraintsMixin
from trainmate.db.signals import DailySignalsMixin
from trainmate.db.benchmarks import BenchmarksMixin
from trainmate.db.workout_change import WorkoutChangeMixin
from trainmate.db.workouts import WorkoutsMixin
from trainmate.db.workout_history import WorkoutHistoryMixin
from trainmate.db.activities import ActivitiesMixin
from trainmate.db.learnings import LearningsMixin
from trainmate.db.analysis import AnalysisCacheMixin
from trainmate.db.periodization import PeriodizationMixin
from trainmate.db.mesocycles import MesocyclesMixin
from trainmate.db.queue import QueueMixin
from trainmate.db.strength import StrengthMixin
from trainmate.db.wipes import WipesMixin


class Database(
    ObjectivesMixin,
    ConstraintsMixin,
    DailySignalsMixin,
    BenchmarksMixin,
    WorkoutChangeMixin,
    WorkoutsMixin,
    WorkoutHistoryMixin,
    ActivitiesMixin,
    LearningsMixin,
    AnalysisCacheMixin,
    PeriodizationMixin,
    MesocyclesMixin,
    SettingsMixin,
    QueueMixin,
    StrengthMixin,
    WipesMixin,
    SchemaMixin,
    BaseDB,
):
    """Handles all database schema setups and operations using SQLite."""

