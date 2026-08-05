"""Persistent repository for Learning Phase3 improvement candidates."""

from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path

from learning.improvement_candidate import ImprovementCandidate


class ImprovementCandidateRepository:
    """Store candidates with stable IDs and append-only update history."""

    def __init__(self, output_dir=None):
        root = Path(__file__).resolve().parents[1]
        self.output_dir = Path(output_dir) if output_dir else root / "reports" / "improvement_candidates"
        self.json_path = self.output_dir / "improvement_candidates.json"
        self.history_path = self.output_dir / "candidate_history.jsonl"

    def load(self) -> dict[str, ImprovementCandidate]:
        if not self.json_path.exists():
            return {}
        with self.json_path.open("r", encoding="utf-8") as handle:
            data = json.load(handle)
        items = data.get("candidates", data if isinstance(data, list) else [])
        return {
            item.get("candidate_id"): ImprovementCandidate.from_dict(item)
            for item in items
            if isinstance(item, dict) and item.get("candidate_id")
        }

    def save(self, candidates) -> None:
        self.output_dir.mkdir(parents=True, exist_ok=True)
        rows = [candidate.to_dict() for candidate in candidates.values()]
        rows.sort(key=lambda item: (-int(item.get("priority_score", 0)), item.get("candidate_id", "")))
        with self.json_path.open("w", encoding="utf-8") as handle:
            json.dump({"candidates": rows}, handle, ensure_ascii=False, indent=2)

    def upsert(self, candidate: ImprovementCandidate) -> ImprovementCandidate:
        candidates = self.load()
        existing = candidates.get(candidate.candidate_id)
        if existing:
            original_detected_at = existing.detected_at
            existing_data = candidate.to_dict()
            existing_data["detected_at"] = original_detected_at
            existing_data["notes"] = list(existing.notes or []) + list(candidate.notes or [])
            candidate = ImprovementCandidate.from_dict(existing_data)
        candidates[candidate.candidate_id] = candidate
        self.save(candidates)
        self.append_history(candidate, "upsert")
        return candidate

    def get_by_id(self, candidate_id: str):
        return self.load().get(candidate_id)

    def list_all(self) -> list[ImprovementCandidate]:
        return list(self.load().values())

    def list_by_status(self, status: str) -> list[ImprovementCandidate]:
        return [candidate for candidate in self.list_all() if candidate.status == status]

    def update_status(self, candidate_id: str, status: str, review_notes: str = ""):
        candidates = self.load()
        candidate = candidates.get(candidate_id)
        if not candidate:
            return None
        candidate.status = status
        if review_notes:
            candidate.notes.append(review_notes)
        candidates[candidate_id] = candidate
        self.save(candidates)
        self.append_history(candidate, "status_update", {"status": status, "review_notes": review_notes})
        return candidate

    def append_history(self, candidate: ImprovementCandidate, event: str, extra=None) -> None:
        self.output_dir.mkdir(parents=True, exist_ok=True)
        record = {
            "event": event,
            "candidate_id": candidate.candidate_id,
            "candidate_name": candidate.candidate_name,
            "status": candidate.status,
            "recommended_action": candidate.recommended_action,
            "priority_score": candidate.calculate_priority_score(),
            "recorded_at": datetime.now().isoformat(timespec="seconds"),
        }
        if extra:
            record.update(extra)
        with self.history_path.open("a", encoding="utf-8") as handle:
            handle.write(json.dumps(record, ensure_ascii=False) + "\n")
