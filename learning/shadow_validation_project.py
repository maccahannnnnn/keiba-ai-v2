"""Data model for Shadow Validation Manager v1.0."""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from datetime import datetime


@dataclass
class ShadowValidationProject:
    project_id: str
    candidate_id: str
    candidate_name: str
    candidate_category: str
    target_component: str
    priority: str
    project_status: str = "DRAFT"
    approval_status: str = "PENDING"
    approved_by: str = ""
    approved_at: str = ""
    created_at: str = field(default_factory=lambda: datetime.now().isoformat(timespec="seconds"))
    updated_at: str = field(default_factory=lambda: datetime.now().isoformat(timespec="seconds"))
    shadow_version: str = "shadow_validation_manager_v1_0"
    feature_flag_name: str = ""
    objective: str = ""
    hypothesis: str = ""
    baseline_definition: dict[str, object] = field(default_factory=dict)
    comparison_definition: str = ""
    implementation_scope: str = ""
    prohibited_changes: list[str] = field(default_factory=list)
    validation_dataset: dict[str, object] = field(default_factory=dict)
    unseen_dataset_requirement: list[str] = field(default_factory=list)
    required_metrics: list[str] = field(default_factory=list)
    acceptance_criteria: list[str] = field(default_factory=list)
    hold_criteria: list[str] = field(default_factory=list)
    revert_criteria: list[str] = field(default_factory=list)
    production_impact_expected: str = "none_before_shadow_implementation"
    implementation_started_at: str = ""
    implementation_completed_at: str = ""
    validation_started_at: str = ""
    validation_completed_at: str = ""
    validation_run_count: int = 0
    result_summary: dict[str, object] = field(default_factory=dict)
    final_decision: str = ""
    decision_reason: str = ""
    source_files: list[str] = field(default_factory=list)
    notes: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, object]:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: dict[str, object]) -> "ShadowValidationProject":
        fields = cls.__dataclass_fields__.keys()
        return cls(**{key: data.get(key) for key in fields if key in data})
