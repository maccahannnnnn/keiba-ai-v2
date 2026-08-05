"""Learning Phase2 storage foundation.

The package stores analysis snapshots only. It does not learn, re-score,
change knowledge, mutate decisions, or update evaluator behavior.
"""

from .learning_database import LearningDatabase
from .learning_record import LearningRecord
from .learning_writer import LEARNING_PHASE2_ENABLED, LearningWriter

__all__ = [
    "LEARNING_PHASE2_ENABLED",
    "LearningDatabase",
    "LearningRecord",
    "LearningWriter",
]
