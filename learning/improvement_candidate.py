"""Data model for Learning Phase3 improvement candidates."""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from datetime import datetime


VALID_CATEGORIES = {
    "BUY",
    "PLAY_SKIP",
    "CONSENSUS",
    "RISK",
    "EVALUATOR",
    "KNOWLEDGE",
    "TRACK_BIAS",
    "MEETING_BIAS",
    "RACE_SHAPE",
    "EXPLAIN",
    "DATA_QUALITY",
    "INPUT_MISSING",
    "MONITORING",
    "OTHER",
}

VALID_ACTIONS = {
    "IMPLEMENT_CANDIDATE",
    "SHADOW_VALIDATE",
    "MORE_DATA_REQUIRED",
    "HOLD",
    "REJECT",
    "ACCEPTED_ALREADY",
}

VALID_STATUSES = {
    "NEW",
    "REVIEW_REQUIRED",
    "APPROVED_FOR_SHADOW",
    "SHADOW_RUNNING",
    "HOLD",
    "REJECTED",
    "IMPLEMENTED",
    "VALIDATED",
    "REVERTED",
}


@dataclass
class ImprovementCandidate:
    candidate_id: str
    candidate_name: str
    candidate_category: str
    target_component: str
    target_scope: str
    source_type: str
    source_files: list[str] = field(default_factory=list)
    detected_at: str = field(default_factory=lambda: datetime.now().isoformat(timespec="seconds"))
    race_count: int = 0
    horse_count: int = 0
    evidence_count: int = 0
    success_case_count: int = 0
    failure_case_count: int = 0
    false_positive_count: int = 0
    false_negative_count: int = 0
    expected_benefit: int = 0
    implementation_cost: int = 0
    overfitting_risk: int = 0
    compatibility_risk: int = 0
    explainability: int = 0
    confidence: int = 0
    priority_score: int = 0
    recommended_action: str = "MORE_DATA_REQUIRED"
    status: str = "NEW"
    summary: str = ""
    evidence: list[dict[str, object]] = field(default_factory=list)
    risks: list[str] = field(default_factory=list)
    validation_requirements: list[str] = field(default_factory=list)
    acceptance_criteria: list[str] = field(default_factory=list)
    revert_criteria: list[str] = field(default_factory=list)
    notes: list[str] = field(default_factory=list)

    def __post_init__(self):
        if self.candidate_category not in VALID_CATEGORIES:
            self.candidate_category = "OTHER"
        if self.recommended_action not in VALID_ACTIONS:
            self.recommended_action = "MORE_DATA_REQUIRED"
        if self.status not in VALID_STATUSES:
            self.status = "NEW"
        self.priority_score = self.calculate_priority_score()

    def calculate_priority_score(self) -> int:
        evidence_strength = min(30, self.evidence_count * 2 + self.race_count)
        value = (
            evidence_strength
            + self.expected_benefit
            + self.explainability
            + self.confidence
            - self.implementation_cost
            - self.overfitting_risk
            - self.compatibility_risk
        )
        return max(0, min(100, int(round(value))))

    def to_dict(self) -> dict[str, object]:
        data = asdict(self)
        data["priority_score"] = self.calculate_priority_score()
        return data

    @classmethod
    def from_dict(cls, data: dict[str, object]) -> "ImprovementCandidate":
        fields = cls.__dataclass_fields__.keys()
        filtered = {key: data.get(key) for key in fields if key in data}
        return cls(**filtered)
