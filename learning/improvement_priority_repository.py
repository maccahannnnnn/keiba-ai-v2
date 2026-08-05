"""Repository for Improvement Priority Manager v1.0."""

from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path


class ImprovementPriorityRepository:
    """Persist priority metadata separately from improvement candidates."""

    def __init__(self, output_dir=None):
        root = Path(__file__).resolve().parents[1]
        self.output_dir = Path(output_dir) if output_dir else root / "reports" / "improvement_priority"
        self.json_path = self.output_dir / "priority_repository.json"

    def load(self) -> dict[str, dict[str, object]]:
        if not self.json_path.exists():
            return {}
        with self.json_path.open("r", encoding="utf-8") as handle:
            data = json.load(handle)
        rows = data.get("priorities", [])
        return {
            row.get("candidate_id"): row
            for row in rows
            if isinstance(row, dict) and row.get("candidate_id")
        }

    def save(self, records: dict[str, dict[str, object]]) -> None:
        self.output_dir.mkdir(parents=True, exist_ok=True)
        rows = list(records.values())
        rows.sort(key=lambda row: (row.get("priority", "P3"), row.get("candidate_id", "")))
        with self.json_path.open("w", encoding="utf-8") as handle:
            json.dump({"priorities": rows}, handle, ensure_ascii=False, indent=2)

    def upsert_many(self, priority_rows: list[dict[str, object]]) -> dict[str, dict[str, object]]:
        existing = self.load()
        now = datetime.now().isoformat(timespec="seconds")
        for row in priority_rows:
            candidate_id = row.get("candidate_id")
            if not candidate_id:
                continue
            prior = existing.get(candidate_id, {})
            existing[candidate_id] = {
                "candidate_id": candidate_id,
                "candidate_name": row.get("candidate_name", prior.get("candidate_name", "")),
                "priority": row.get("priority", prior.get("priority", "P3")),
                "assigned_date": prior.get("assigned_date") or now,
                "last_review": now,
                "shadow_count": int(prior.get("shadow_count", 0))
                + (1 if row.get("recommended_action") == "SHADOW_VALIDATE" else 0),
                "validation_count": int(prior.get("validation_count", 0))
                + (1 if row.get("status") in {"VALIDATED", "IMPLEMENTED"} else 0),
                "recommended_action": row.get("recommended_action", ""),
                "status": row.get("status", ""),
                "priority_score": row.get("priority_score", 0),
                "reason": row.get("priority_reason", ""),
            }
        self.save(existing)
        return existing
