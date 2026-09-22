"""SQLite persistence layer.

One ``Database`` class, assembled here from a mixin per domain so no one file holds the
whole schema's worth of methods. Nothing else is exported: the process-wide handle is
``runtime.db``, which is what every caller reads.
"""

from stamind.db.base import BaseDB, SettingsMixin
from stamind.db.schema import SchemaMixin
from stamind.db.objectives import ObjectivesMixin
from stamind.db.constraints import ConstraintsMixin
from stamind.db.signals import DailySignalsMixin
from stamind.db.benchmarks import BenchmarksMixin
from stamind.db.workout_change import WorkoutChangeMixin
from stamind.db.workouts import WorkoutsMixin
from stamind.db.workout_history import WorkoutHistoryMixin
from stamind.db.activities import ActivitiesMixin
from stamind.db.learnings import LearningsMixin
from stamind.db.analysis import AnalysisCacheMixin
from stamind.db.periodization import PeriodizationMixin
from stamind.db.mesocycles import MesocyclesMixin
from stamind.db.queue import QueueMixin
from stamind.db.strength import StrengthMixin
from stamind.db.wipes import WipesMixin


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

