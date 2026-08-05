"""Improvement Priority Manager v1.0.

Ranks existing Improvement Candidate Engine outputs for human review.  This is
planning metadata only and never changes BUY, evaluator, score, or Decision
logic.
"""

from __future__ import annotations

import csv
import json
from collections import Counter
from datetime import datetime
from pathlib import Path

from learning.improvement_priority_repository import ImprovementPriorityRepository


class ImprovementPriorityManager:
    """Assign P0-P3 priorities and maintain a shadow validation queue."""

    def __init__(self, root_dir=None, output_dir=None):
        self.root = Path(root_dir) if root_dir else Path(__file__).resolve().parents[1]
        self.input_dir = self.root / "reports" / "improvement_candidates"
        self.output_dir = Path(output_dir) if output_dir else self.root / "reports" / "improvement_priority"
        self.repository = ImprovementPriorityRepository(self.output_dir)
        self.warnings: list[str] = []

    def run(self) -> dict[str, object]:
        candidates = self._load_candidates()
        priority_rows = [self._priority_row(candidate) for candidate in candidates]
        priority_rows.sort(
            key=lambda row: (
                self._priority_order(row["priority"]),
                -int(row.get("priority_score", 0)),
                row.get("candidate_id", ""),
            )
        )
        repository_state = self.repository.upsert_many(priority_rows)
        queue_rows = [
            row
            for row in priority_rows
            if row["priority"] in {"P0", "P1"}
            and row.get("recommended_action") == "SHADOW_VALIDATE"
            and row.get("status") == "REVIEW_REQUIRED"
        ]
        self._write_outputs(priority_rows, queue_rows, repository_state)
        summary = {
            "generated_at": datetime.now().isoformat(timespec="seconds"),
            "candidate_count": len(priority_rows),
            "priority_counts": dict(Counter(row["priority"] for row in priority_rows)),
            "shadow_queue_count": len(queue_rows),
            "repository_count": len(repository_state),
            "duplicate_candidate_ids": self._duplicates([row["candidate_id"] for row in priority_rows]),
            "warnings": self.warnings,
            "buy_diff": 0,
            "score_diff": 0,
            "decision_diff": 0,
        }
        self._write_json(self.output_dir / "priority_summary.json", summary)
        self._write_summary_md(priority_rows, queue_rows, summary)
        return summary

    def _priority_row(self, candidate: dict[str, object]) -> dict[str, object]:
        priority, reason = self._classify(candidate)
        return {
            "priority": priority,
            "candidate_id": candidate.get("candidate_id", ""),
            "candidate_name": candidate.get("candidate_name", ""),
            "candidate_category": candidate.get("candidate_category", ""),
            "target_component": candidate.get("target_component", ""),
            "priority_score": int(candidate.get("priority_score", 0) or 0),
            "expected_benefit": int(candidate.get("expected_benefit", 0) or 0),
            "implementation_cost": int(candidate.get("implementation_cost", 0) or 0),
            "overfitting_risk": int(candidate.get("overfitting_risk", 0) or 0),
            "compatibility_risk": int(candidate.get("compatibility_risk", 0) or 0),
            "confidence": int(candidate.get("confidence", 0) or 0),
            "recommended_action": candidate.get("recommended_action", ""),
            "status": candidate.get("status", ""),
            "priority_reason": reason,
            "summary": candidate.get("summary", ""),
        }

    def _classify(self, candidate: dict[str, object]) -> tuple[str, str]:
        action = candidate.get("recommended_action", "")
        status = candidate.get("status", "")
        score = int(candidate.get("priority_score", 0) or 0)
        overfit = int(candidate.get("overfitting_risk", 0) or 0)
        compatibility = int(candidate.get("compatibility_risk", 0) or 0)
        confidence = int(candidate.get("confidence", 0) or 0)

        if action in {"HOLD", "REJECT"} or status in {"HOLD", "REJECTED"}:
            return "P3", "保留または却下状態のためShadow Queueへ送らない"
        if action == "ACCEPTED_ALREADY" or status in {"VALIDATED", "IMPLEMENTED"}:
            return "P3", "採用済みコンポーネントとしてRoadmapに記録"
        if action == "MORE_DATA_REQUIRED":
            return "P2", "追加データ待ち"
        if (
            action == "SHADOW_VALIDATE"
            and status == "REVIEW_REQUIRED"
            and score >= 45
            and overfit <= 18
            and compatibility <= 10
            and confidence >= 14
        ):
            return "P0", "Shadowへすぐ送る価値あり"
        if action == "SHADOW_VALIDATE":
            return "P1", "次候補としてShadow検証待ち"
        return "P2", "優先判断に追加確認が必要"

    def _write_outputs(self, priority_rows, queue_rows, repository_state):
        self.output_dir.mkdir(parents=True, exist_ok=True)
        self._write_csv(
            self.output_dir / "shadow_queue.csv",
            queue_rows,
            ["priority", "candidate_id", "candidate_name", "recommended_action", "priority_reason"],
        )
        self._write_roadmap(priority_rows, queue_rows, repository_state)

    def _write_summary_md(self, priority_rows, queue_rows, summary):
        lines = [
            "# Improvement Priority Summary",
            "",
            "## 概要",
            f"- 候補数: {summary['candidate_count']}",
            f"- Shadow Queue件数: {summary['shadow_queue_count']}",
            f"- Repository件数: {summary['repository_count']}",
            f"- 重複候補ID: {len(summary['duplicate_candidate_ids'])}",
            "",
            "## Priority内訳",
        ]
        for priority in ["P0", "P1", "P2", "P3"]:
            lines.append(f"- {priority}: {summary['priority_counts'].get(priority, 0)}")
        lines.extend(["", "## Shadow Queue"])
        for row in queue_rows:
            lines.append(
                f"- {row['priority']} {row['candidate_id']}: {row['priority_reason']}"
            )
        lines.extend(["", "## 互換性"])
        lines.append("- BUY差分: 0")
        lines.append("- Score差分: 0")
        lines.append("- Decision差分: 0")
        lines.append("- Priority管理のみ。本番ロジックは変更していない。")
        (self.output_dir / "priority_summary.md").write_text(
            "\n".join(lines) + "\n",
            encoding="utf-8",
        )

    def _write_roadmap(self, priority_rows, queue_rows, repository_state):
        by_priority = {priority: [] for priority in ["P0", "P1", "P2", "P3"]}
        for row in priority_rows:
            by_priority[row["priority"]].append(row)
        accepted = [
            row
            for row in priority_rows
            if row.get("recommended_action") == "ACCEPTED_ALREADY"
            or row.get("status") in {"VALIDATED", "IMPLEMENTED"}
        ]
        hold = [
            row
            for row in priority_rows
            if row.get("recommended_action") == "HOLD" or row.get("status") == "HOLD"
        ]
        lines = [
            "# Improvement Roadmap",
            "",
            "## 現在候補",
        ]
        for row in priority_rows:
            lines.append(
                f"- {row['priority']} {row['candidate_id']} "
                f"(score={row['priority_score']}, action={row['recommended_action']})"
            )
        lines.extend(["", "## 優先順位"])
        for priority in ["P0", "P1", "P2", "P3"]:
            lines.append(f"### {priority}")
            if not by_priority[priority]:
                lines.append("- なし")
            for row in by_priority[priority]:
                lines.append(f"- {row['candidate_id']}: {row['priority_reason']}")
        lines.extend(["", "## Shadow予定"])
        if not queue_rows:
            lines.append("- なし")
        for row in queue_rows:
            lines.append(f"- {row['priority']} {row['candidate_id']}: {row['candidate_name']}")
        lines.extend(["", "## 保留"])
        if not hold:
            lines.append("- なし")
        for row in hold:
            lines.append(f"- {row['candidate_id']}: {row['summary']}")
        lines.extend(["", "## 採用済み"])
        if not accepted:
            lines.append("- なし")
        for row in accepted:
            repo = repository_state.get(row["candidate_id"], {})
            lines.append(
                f"- {row['candidate_id']}: {row['summary']} "
                f"(validation_count={repo.get('validation_count', 0)})"
            )
        lines.extend(
            [
                "",
                "## 運用メモ",
                "- このRoadmapは人間の実装判断を支援するもの。",
                "- 自動実装、自動閾値変更、自動Learning改善は行わない。",
            ]
        )
        (self.output_dir / "improvement_roadmap.md").write_text(
            "\n".join(lines) + "\n",
            encoding="utf-8",
        )

    def _load_candidates(self):
        path = self.input_dir / "improvement_candidates.json"
        if not path.exists():
            self.warnings.append(f"missing candidates json: {path}")
            return []
        with path.open("r", encoding="utf-8") as handle:
            data = json.load(handle)
        return [row for row in data.get("candidates", []) if isinstance(row, dict)]

    def _write_json(self, path, data):
        path.parent.mkdir(parents=True, exist_ok=True)
        with path.open("w", encoding="utf-8") as handle:
            json.dump(data, handle, ensure_ascii=False, indent=2)

    def _write_csv(self, path, rows, fields):
        path.parent.mkdir(parents=True, exist_ok=True)
        with path.open("w", encoding="utf-8-sig", newline="") as handle:
            writer = csv.DictWriter(handle, fieldnames=fields, extrasaction="ignore")
            writer.writeheader()
            writer.writerows(rows)

    def _priority_order(self, priority):
        return {"P0": 0, "P1": 1, "P2": 2, "P3": 3}.get(priority, 4)

    def _duplicates(self, values):
        counts = Counter(values)
        return [value for value, count in counts.items() if count > 1]
