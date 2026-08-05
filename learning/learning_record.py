"""Data shape for Learning Phase2 analysis snapshots."""

from dataclasses import asdict, dataclass, field
from typing import Any, Dict, List, Optional


@dataclass
class LearningRecord:
    """One horse-level analysis snapshot for future learning phases."""

    race_id: str = ""
    horse_id: str = ""
    horse_name: str = ""
    decision: str = ""
    final_score: Optional[float] = None
    adjusted_score: Optional[float] = None
    confidence: Any = ""
    consensus: Dict[str, Any] = field(default_factory=dict)
    risk: List[Any] = field(default_factory=list)
    ability: Any = None
    distance: Any = None
    course: Any = None
    pace: Any = None
    running_style: Any = None
    blood: Any = None
    condition: Any = None
    track_bias: Any = None
    race_shape: Any = None
    course_shape: Any = None
    decision_reason: str = ""
    explain: str = ""
    race_summary: str = ""
    race_decision: str = ""
    analysis_date: str = ""
    result: Dict[str, Any] = field(default_factory=dict)
    finish_position: Optional[int] = None
    metadata: Dict[str, Any] = field(default_factory=dict)

    def to_dict(self):
        return asdict(self)
