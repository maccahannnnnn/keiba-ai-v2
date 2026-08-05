"""Learning Phase3 Improvement Candidate Engine v1.0."""

from __future__ import annotations

import csv
import json
from collections import Counter, defaultdict
from datetime import datetime
from pathlib import Path

from learning.improvement_candidate import ImprovementCandidate
from learning.improvement_candidate_repository import ImprovementCandidateRepository


class ImprovementCandidateEngine:
    """Generate explainable, review-ready improvement candidates from reports."""

    def __init__(self, root_dir=None, output_dir=None):
        self.root = Path(root_dir) if root_dir else Path(__file__).resolve().parents[1]
        self.output_dir = Path(output_dir) if output_dir else self.root / "reports" / "improvement_candidates"
        self.repository = ImprovementCandidateRepository(self.output_dir)
        self.warnings: list[str] = []

    def generate(self) -> dict[str, object]:
        monitor_summary = self._read_json(self.root / "reports" / "buy_monitor" / "summary.json")
        monitor_races = self._read_csv(self.root / "reports" / "buy_monitor" / "buy_monitor_races.csv")
        monitor_horses = self._read_csv(self.root / "reports" / "buy_monitor" / "buy_monitor_horses.csv")
        rc1_rows = self._read_csv(self.root / "reports" / "buy_v1_rc1_validation" / "legacy_comparison.csv")
        rc1_detail = self._read_csv(self.root / "reports" / "buy_v1_rc1_validation" / "buy_report.csv")
        detail_by_key = {(row.get("race_id"), row.get("horse_name")): row for row in rc1_detail}

        generated = []
        generated.extend(
            self._buy_false_positive_candidates(monitor_summary, monitor_horses)
        )
        generated.extend(
            self._buy_false_negative_candidates(monitor_summary, rc1_rows, detail_by_key)
        )
        generated.extend(self._unconverged_candidate(monitor_summary, monitor_races, rc1_rows))
        consensus_candidate = self._consensus_targeted_rescue_candidate()
        if consensus_candidate:
            generated.append(consensus_candidate)
        generated.extend(self._accepted_component_candidates(monitor_summary))

        persisted = [self.repository.upsert(candidate) for candidate in generated]
        all_candidates = self.repository.list_all()
        self._write_reports(all_candidates, persisted)
        return {
            "candidate_count": len(all_candidates),
            "generated_count": len(generated),
            "persisted_count": len(persisted),
            "warnings": self.warnings,
            "output_dir": str(self.output_dir),
        }

    def _buy_false_positive_candidates(self, summary, monitor_horses):
        fp_rows = [
            row
            for row in monitor_horses
            if row.get("rc1_decision") == "BUY" and str(row.get("buy_success")).lower() != "true"
        ]
        if not fp_rows:
            return []
        risk_counts = Counter(row.get("risk", "") for row in fp_rows)
        consensus_counts = Counter(row.get("consensus", "") for row in fp_rows)
        evidence = [
            {
                "race_id": row.get("race_id"),
                "horse_name": row.get("horse_name"),
                "finish": row.get("finish"),
                "buy_reason": row.get("buy_reason"),
                "risk": row.get("risk"),
                "consensus": row.get("consensus"),
            }
            for row in fp_rows
        ]
        return [
            ImprovementCandidate(
                candidate_id="BUY_FALSE_POSITIVE_RC1",
                candidate_name="RC1 BUY false positive monitoring",
                candidate_category="BUY",
                target_component="BUY v1.0 RC1",
                target_scope="RC1 formal BUY horses finishing 4th or worse",
                source_type="BUY_MONITOR",
                source_files=[
                    "reports/buy_monitor/buy_monitor_horses.csv",
                    "reports/buy_monitor/summary.json",
                ],
                race_count=len({row.get("race_id") for row in fp_rows}),
                horse_count=len(fp_rows),
                evidence_count=len(fp_rows),
                failure_case_count=len(fp_rows),
                false_positive_count=len(fp_rows),
                expected_benefit=18,
                implementation_cost=8,
                overfitting_risk=14,
                compatibility_risk=6,
                explainability=18,
                confidence=16,
                recommended_action="MORE_DATA_REQUIRED"
                if len({row.get("race_id") for row in fp_rows}) < 8
                else "SHADOW_VALIDATE",
                status="REVIEW_REQUIRED",
                summary=(
                    f"RC1 BUY false positives detected: {len(fp_rows)} horses. "
                    "Keep as monitoring candidate before changing BUY logic."
                ),
                evidence=evidence,
                risks=[
                    "Small 40-race sample may overfit BUY suppression.",
                    f"Top risk patterns: {risk_counts.most_common(3)}",
                    f"Top consensus patterns: {consensus_counts.most_common(3)}",
                ],
                validation_requirements=[
                    "Validate on unused 20-30 races before any production change.",
                    "Confirm BUY place rate does not decline.",
                    "Confirm successful BUY horses are not removed broadly.",
                ],
                acceptance_criteria=[
                    "FP reduction repeats across multiple race days.",
                    "BUY success rate is maintained or improved.",
                    "Feature Flag OFF keeps legacy output unchanged.",
                ],
                revert_criteria=[
                    "Successful BUY removals exceed FP reduction.",
                    "Production decision differences appear outside target scope.",
                ],
            )
        ]

    def _buy_false_negative_candidates(self, summary, rc1_rows, detail_by_key):
        fn_rows = [
            row
            for row in rc1_rows
            if self._truthy(row.get("actual_top3")) and row.get("rc1_decision") != "BUY"
        ]
        groups: dict[str, list[dict[str, object]]] = defaultdict(list)
        for row in fn_rows:
            detail = detail_by_key.get((row.get("race_id"), row.get("horse_name")), {})
            group = self._fn_group(row, detail)
            groups[group].append({"row": row, "detail": detail})

        specs = {
            "CONSENSUS": ("BUY_FALSE_NEGATIVE_CONSENSUS", "CONSENSUS", "Consensus Reliability"),
            "ABSOLUTE": ("BUY_FALSE_NEGATIVE_ABSOLUTE", "BUY", "Absolute Quality"),
            "RELATIVE": ("BUY_FALSE_NEGATIVE_RELATIVE", "BUY", "Relative Advantage"),
            "RISK": ("BUY_FALSE_NEGATIVE_RISK", "RISK", "Risk Guard"),
        }
        candidates = []
        for group, rows in groups.items():
            if group not in specs or not rows:
                continue
            candidate_id, category, component = specs[group]
            evidence = [
                {
                    "race_id": item["row"].get("race_id"),
                    "horse_name": item["row"].get("horse_name"),
                    "finish": item["row"].get("actual_finish"),
                    "race_state": item["row"].get("rc1_race_state"),
                    "rc1_status": item["row"].get("rc1_status"),
                    "reason": item["row"].get("rc1_reason"),
                    "absolute": item["detail"].get("absolute_quality_pass"),
                    "relative": item["detail"].get("relative_advantage_pass"),
                    "consensus": item["detail"].get("reliability_pass"),
                    "risk": item["detail"].get("risk_guard_pass"),
                }
                for item in rows
            ]
            race_count = len({item["row"].get("race_id") for item in rows})
            action = "SHADOW_VALIDATE" if race_count >= 4 and len(rows) >= 6 else "MORE_DATA_REQUIRED"
            candidates.append(
                ImprovementCandidate(
                    candidate_id=candidate_id,
                    candidate_name=f"RC1 false negative caused by {component}",
                    candidate_category=category,
                    target_component=component,
                    target_scope="RC1 non-BUY horses finishing top3",
                    source_type="BUY_V1_RC1_VALIDATION",
                    source_files=[
                        "reports/buy_v1_rc1_validation/legacy_comparison.csv",
                        "reports/buy_v1_rc1_validation/buy_report.csv",
                    ],
                    race_count=race_count,
                    horse_count=len(rows),
                    evidence_count=len(rows),
                    success_case_count=len(rows),
                    false_negative_count=len(rows),
                    expected_benefit=20 if action == "SHADOW_VALIDATE" else 12,
                    implementation_cost=10,
                    overfitting_risk=16,
                    compatibility_risk=8,
                    explainability=18,
                    confidence=16 if action == "SHADOW_VALIDATE" else 10,
                    recommended_action=action,
                    status="REVIEW_REQUIRED",
                    summary=f"{len(rows)} top3 horses were blocked mainly by {component}.",
                    evidence=evidence,
                    risks=[
                        "FN as a whole must not become a blanket rescue rule.",
                        "Candidate must be validated by blocker subtype before implementation.",
                    ],
                    validation_requirements=[
                        "Run shadow validation with exact blocker subtype only.",
                        "Measure FP increase and successful BUY retention.",
                        "Check production diff remains target scoped.",
                    ],
                    acceptance_criteria=[
                        "FN rescue exceeds new FP on unused races.",
                        "BUY place rate remains acceptable.",
                    ],
                    revert_criteria=[
                        "FP increases faster than rescued FN.",
                        "Rule rescues horses without explainable blocker evidence.",
                    ],
                )
            )
        return candidates

    def _unconverged_candidate(self, summary, monitor_races, rc1_rows):
        races = [row for row in monitor_races if row.get("race_state") == "PLAY_UNCONVERGED_4PLUS"]
        if not races:
            return []
        evidence = []
        for race in races:
            race_id = race.get("race_id")
            race_rows = [
                row
                for row in rc1_rows
                if row.get("race_id") == race_id
                and row.get("rc1_status") == "RC1_CANDIDATE_UNCONVERGED_4PLUS"
            ]
            evidence.append(
                {
                    "race_id": race_id,
                    "candidate_count": len(race_rows),
                    "candidate_top3": sum(1 for row in race_rows if self._truthy(row.get("actual_top3"))),
                    "candidate_fp": sum(1 for row in race_rows if not self._truthy(row.get("actual_top3"))),
                    "buy_horses": race.get("buy_horses"),
                }
            )
        candidate_count = sum(int(item["candidate_count"]) for item in evidence)
        return [
            ImprovementCandidate(
                candidate_id="UNCONVERGED_4PLUS_MONITOR",
                candidate_name="PLAY_UNCONVERGED_4PLUS monitoring record",
                candidate_category="PLAY_SKIP",
                target_component="BUY v1.0 RC1 Race State",
                target_scope="PLAY_UNCONVERGED_4PLUS race handling",
                source_type="BUY_MONITOR",
                source_files=["reports/buy_monitor/buy_monitor_races.csv"],
                race_count=len(races),
                horse_count=candidate_count,
                evidence_count=candidate_count,
                success_case_count=sum(int(item["candidate_top3"]) for item in evidence),
                false_negative_count=sum(int(item["candidate_top3"]) for item in evidence),
                false_positive_count=sum(int(item["candidate_fp"]) for item in evidence),
                expected_benefit=10,
                implementation_cost=4,
                overfitting_risk=8,
                compatibility_risk=4,
                explainability=20,
                confidence=18,
                recommended_action="ACCEPTED_ALREADY",
                status="VALIDATED",
                summary="4+ candidate races are retained as monitored unconverged races, not formal BUY.",
                evidence=evidence,
                risks=["Do not convert unconverged candidates into automatic BUY without separate approval."],
                validation_requirements=["Continue monitoring candidate outcomes by race state."],
                acceptance_criteria=["Unconverged races remain explainable and separated from formal BUY."],
                revert_criteria=["Formal BUY is emitted in PLAY_UNCONVERGED_4PLUS."],
            )
        ]

    def _consensus_targeted_rescue_candidate(self):
        path = self.root / "reports" / "consensus_targeted_rescue_validation" / "summary.md"
        if not path.exists():
            self.warnings.append("consensus targeted rescue report not found")
            return None
        text = path.read_text(encoding="utf-8", errors="replace")
        return ImprovementCandidate(
            candidate_id="CONSENSUS_TARGETED_RESCUE_V1",
            candidate_name="Consensus Targeted Rescue shadow result",
            candidate_category="CONSENSUS",
            target_component="Consensus Reliability",
            target_scope="positive_count=4 rescue patterns",
            source_type="CONSENSUS_TARGETED_RESCUE_VALIDATION",
            source_files=["reports/consensus_targeted_rescue_validation/summary.md"],
            race_count=40,
            horse_count=540,
            evidence_count=1,
            expected_benefit=8,
            implementation_cost=12,
            overfitting_risk=25,
            compatibility_risk=12,
            explainability=16,
            confidence=8,
            recommended_action="HOLD",
            status="HOLD",
            summary="Consensus Targeted Rescue remains HOLD and is recorded only as a candidate history item.",
            evidence=[{"summary_excerpt": text[:1000]}],
            risks=[
                "Overfitting risk is high.",
                "HOLD functionality must not be mixed into BUY v1.0 RC1.",
            ],
            validation_requirements=["Retest only after more races are available."],
            acceptance_criteria=["Multiple unused race sets show stable FN rescue without FP growth."],
            revert_criteria=["FP increase or BUY quality decline appears in shadow validation."],
        )

    def _accepted_component_candidates(self, summary):
        race_count = int(summary.get("race_count", 0) or 0)
        horse_count = int(summary.get("horse_count", 0) or 0)
        return [
            ImprovementCandidate(
                candidate_id="PLAY_SKIP_GUARD_ACCEPTED",
                candidate_name="PLAY/SKIP Guard accepted component",
                candidate_category="PLAY_SKIP",
                target_component="BUY v1.0 RC1 Race State",
                target_scope="PLAY/SKIP and BUY0 handling",
                source_type="ACCEPTED_COMPONENT_RECORD",
                source_files=["reports/buy_v1_rc1_validation/summary.md"],
                race_count=race_count,
                horse_count=horse_count,
                evidence_count=max(1, race_count),
                expected_benefit=16,
                implementation_cost=0,
                overfitting_risk=4,
                compatibility_risk=2,
                explainability=20,
                confidence=20,
                recommended_action="ACCEPTED_ALREADY",
                status="VALIDATED",
                summary="PLAY/SKIP and BUY0 handling are accepted in RC1 and tracked as baseline components.",
                evidence=[{"race_state_counts": summary.get("race_state_counts", {})}],
                validation_requirements=["Continue race-state monitoring after each meeting."],
                acceptance_criteria=["RaceState output remains present and explainable."],
                revert_criteria=["PLAY/SKIP changes production output when feature flag is OFF."],
            ),
            ImprovementCandidate(
                candidate_id="BUY_V1_RC1_ACCEPTED",
                candidate_name="BUY v1.0 RC1 accepted baseline",
                candidate_category="BUY",
                target_component="BUY v1.0 RC1",
                target_scope="Feature-flagged RC1 formal BUY",
                source_type="ACCEPTED_COMPONENT_RECORD",
                source_files=["reports/buy_v1_rc1_validation/summary.md"],
                race_count=race_count,
                horse_count=horse_count,
                evidence_count=max(1, horse_count),
                success_case_count=int(summary.get("buy_success_count", 0) or 0),
                false_positive_count=int(summary.get("fp", 0) or 0),
                false_negative_count=int(summary.get("fn", 0) or 0),
                expected_benefit=18,
                implementation_cost=0,
                overfitting_risk=8,
                compatibility_risk=2,
                explainability=20,
                confidence=18,
                recommended_action="ACCEPTED_ALREADY",
                status="VALIDATED",
                summary="BUY v1.0 RC1 is the current monitored production-candidate baseline.",
                evidence=[summary],
                validation_requirements=["Compare each new meeting against legacy and RC1 monitoring."],
                acceptance_criteria=["Feature Flag ON works; Feature Flag OFF remains compatible."],
                revert_criteria=["RC1 output breaks report compatibility or unexpected production diffs occur."],
            ),
            ImprovementCandidate(
                candidate_id="BUY_MONITORING_V1_ACCEPTED",
                candidate_name="BUY Monitoring v1.0 accepted component",
                candidate_category="MONITORING",
                target_component="BUY Monitoring",
                target_scope="Post-race BUY monitoring reports",
                source_type="ACCEPTED_COMPONENT_RECORD",
                source_files=["reports/buy_monitor/buy_monitor_summary.md"],
                race_count=race_count,
                horse_count=horse_count,
                evidence_count=max(1, race_count),
                expected_benefit=14,
                implementation_cost=0,
                overfitting_risk=2,
                compatibility_risk=1,
                explainability=20,
                confidence=20,
                recommended_action="ACCEPTED_ALREADY",
                status="VALIDATED",
                summary="BUY Monitoring v1.0 provides review-only summaries without changing BUY logic.",
                evidence=[{"output_dir": "reports/buy_monitor"}],
                validation_requirements=["Run monitor after each result import."],
                acceptance_criteria=["Reports generate without touching scoring or decision logic."],
                revert_criteria=["Monitoring script mutates input reports or production logic."],
            ),
        ]

    def _fn_group(self, row, detail):
        if detail.get("risk_guard_pass") == "False":
            return "RISK"
        if detail.get("reliability_pass") == "False":
            return "CONSENSUS"
        if detail.get("absolute_quality_pass") == "False":
            return "ABSOLUTE"
        if detail.get("relative_advantage_pass") == "False":
            return "RELATIVE"
        if row.get("rc1_race_state") == "PLAY_UNCONVERGED_4PLUS":
            return "UNCONVERGED"
        return "OTHER"

    def _write_reports(self, all_candidates, persisted):
        self.output_dir.mkdir(parents=True, exist_ok=True)
        rows = [candidate.to_dict() for candidate in all_candidates]
        rows.sort(key=lambda item: (-int(item.get("priority_score", 0)), item.get("candidate_id", "")))
        self._write_json(self.output_dir / "improvement_candidates.json", {"candidates": rows})
        self._write_candidates_csv(self.output_dir / "improvement_candidates.csv", rows)
        self._write_evidence_csv(self.output_dir / "candidate_evidence.csv", rows)
        summary = {
            "generated_at": datetime.now().isoformat(timespec="seconds"),
            "candidate_count": len(rows),
            "new_or_updated_count": len(persisted),
            "recommended_action_counts": dict(Counter(row.get("recommended_action") for row in rows)),
            "status_counts": dict(Counter(row.get("status") for row in rows)),
            "duplicate_candidate_ids": self._duplicates([row.get("candidate_id") for row in rows]),
            "warnings": self.warnings,
        }
        self._write_json(self.output_dir / "summary.json", summary)
        self._write_markdown(self.output_dir / "improvement_candidates.md", rows, summary)

    def _write_candidates_csv(self, path, rows):
        fields = [
            "candidate_id",
            "candidate_name",
            "candidate_category",
            "target_component",
            "evidence_count",
            "race_count",
            "horse_count",
            "success_case_count",
            "failure_case_count",
            "false_positive_count",
            "false_negative_count",
            "expected_benefit",
            "implementation_cost",
            "overfitting_risk",
            "compatibility_risk",
            "explainability",
            "confidence",
            "priority_score",
            "recommended_action",
            "status",
            "summary",
        ]
        self._write_csv(path, rows, fields)

    def _write_evidence_csv(self, path, rows):
        fields = ["candidate_id", "candidate_name", "evidence_index", "evidence"]
        evidence_rows = []
        for row in rows:
            for index, evidence in enumerate(row.get("evidence", []), start=1):
                evidence_rows.append(
                    {
                        "candidate_id": row.get("candidate_id"),
                        "candidate_name": row.get("candidate_name"),
                        "evidence_index": index,
                        "evidence": json.dumps(evidence, ensure_ascii=False),
                    }
                )
        self._write_csv(path, evidence_rows, fields)

    def _write_markdown(self, path, rows, summary):
        lines = [
            "# Improvement Candidates",
            "",
            "## 概要",
            f"- 候補数: {summary['candidate_count']}",
            f"- 更新候補数: {summary['new_or_updated_count']}",
            f"- 重複候補ID: {len(summary['duplicate_candidate_ids'])}",
            "",
            "## 対象レポート",
            "- reports/buy_monitor/",
            "- reports/buy_v1_rc1_validation/",
            "- reports/consensus_targeted_rescue_validation/",
            "",
            "## 優先順位一覧",
        ]
        for row in rows:
            lines.append(
                f"- {row['candidate_id']} | score={row['priority_score']} | "
                f"action={row['recommended_action']} | status={row['status']}"
            )
        lines.extend(["", "## 新規候補"])
        for row in rows:
            if row.get("status") in {"NEW", "REVIEW_REQUIRED"}:
                lines.extend(self._candidate_md(row))
        lines.extend(["", "## HOLD候補"])
        for row in rows:
            if row.get("status") == "HOLD":
                lines.extend(self._candidate_md(row))
        lines.extend(["", "## ACCEPT済み候補"])
        for row in rows:
            if row.get("recommended_action") == "ACCEPTED_ALREADY":
                lines.extend(self._candidate_md(row))
        lines.extend(["", "## データ品質候補"])
        lines.append("- 現時点で明示的なINPUT_MISSING候補は生成されていない。")
        lines.extend(["", "## 次に推奨する開発候補"])
        actionable = [
            row
            for row in rows
            if row.get("recommended_action") in {"SHADOW_VALIDATE", "MORE_DATA_REQUIRED"}
        ]
        for row in actionable[:3]:
            lines.append(f"- {row['candidate_id']}: {row['summary']}")
        lines.extend(["", "## 人間による確認待ち項目"])
        lines.append("- recommended_action は実装判断ではなく、次の検証行動の推奨。")
        lines.append("- 自動実装、自動閾値変更、自動Knowledge更新は行わない。")
        path.write_text("\n".join(lines) + "\n", encoding="utf-8")

    def _candidate_md(self, row):
        return [
            "",
            f"### {row['candidate_id']}",
            f"- Name: {row['candidate_name']}",
            f"- Category: {row['candidate_category']}",
            f"- Target: {row['target_component']} / {row['target_scope']}",
            f"- Evidence: {row['evidence_count']} / Race: {row['race_count']} / Horse: {row['horse_count']}",
            f"- FP: {row['false_positive_count']} / FN: {row['false_negative_count']}",
            f"- Priority: {row['priority_score']}",
            f"- Recommended Action: {row['recommended_action']}",
            f"- Status: {row['status']}",
            f"- Summary: {row['summary']}",
        ]

    def _read_json(self, path):
        if not path.exists():
            self.warnings.append(f"missing json: {path}")
            return {}
        with path.open("r", encoding="utf-8-sig") as handle:
            return json.load(handle)

    def _read_csv(self, path):
        if not path.exists():
            self.warnings.append(f"missing csv: {path}")
            return []
        with path.open("r", encoding="utf-8-sig", newline="") as handle:
            return list(csv.DictReader(handle))

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

    def _duplicates(self, values):
        counts = Counter(values)
        return [value for value, count in counts.items() if count > 1]

    def _truthy(self, value):
        return str(value).strip().lower() in {"1", "true", "yes", "on"}
