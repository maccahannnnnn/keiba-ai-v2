"""Diagnostic Shadow for MeetingBias versus TrackBias.

This module is review-layer only. It reads saved MeetingBias evidence,
compares repository-relative MeetingBias tendencies against saved TrackBias
observations, and writes diagnostic reports. It never calls Production
adapters and never changes scores, BUY, Decision, Knowledge, Learning, or
Shadow Project state.
"""

from __future__ import annotations

import csv
import hashlib
import json
from collections import Counter, defaultdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


class MeetingBiasDiagnosticShadow:
    """Compare MeetingBias diagnostic predictions with TrackBias control."""

    VERSION = "meeting_bias_diagnostic_shadow_v1"
    STAGE_DERIVATION_NOTE = (
        "meeting_stage is not the official JRA meeting number. It is derived "
        "from repository-relative observed race dates, may change when future "
        "repository data is added, and is limited to diagnostic use."
    )

    def __init__(
        self,
        evidence_path: Path | str = "reports/meeting_bias/meeting_bias_read_only_evidence_v2.json",
        output_dir: Path | str = "reports/meeting_bias",
    ) -> None:
        self.evidence_path = Path(evidence_path)
        self.output_dir = Path(output_dir)

    def run(self) -> dict[str, Any]:
        payload = self._load_json(self.evidence_path, {})
        evidence = [row for row in payload.get("evidence", []) if isinstance(row, dict)]
        source_manifest = [row for row in payload.get("source_manifest", []) if isinstance(row, dict)]
        observed_window_hash = self._observed_window_hash(evidence, source_manifest)
        race_rows = self._race_rows(evidence, observed_window_hash)
        comparison_rows = self._comparison_rows(race_rows)
        summary = self._summary(payload, race_rows, comparison_rows, observed_window_hash)

        self.output_dir.mkdir(parents=True, exist_ok=True)
        self._write_csv(self.output_dir / "meeting_bias_diagnostic_shadow_v1.csv", race_rows)
        self._write_csv(self.output_dir / "meeting_bias_trackbias_comparison_v1.csv", comparison_rows)
        self._write_json(self.output_dir / "meeting_bias_shadow_summary_v1.json", summary)
        self._write_report(self.output_dir / "meeting_bias_diagnostic_shadow_v1.md", summary, race_rows, comparison_rows)
        self._annotate_stage_resolution_outputs(observed_window_hash)
        return summary

    def _race_rows(self, evidence: list[dict[str, Any]], observed_window_hash: str) -> list[dict[str, Any]]:
        by_race: dict[str, list[dict[str, Any]]] = defaultdict(list)
        for row in evidence:
            by_race[row.get("race_id") or ""].append(row)

        rows: list[dict[str, Any]] = []
        for race_id in sorted(race_id for race_id in by_race if race_id):
            race_evidence = by_race[race_id]
            base = race_evidence[0]
            actual_lane = self._actual_tendency(race_evidence, "lane")
            actual_style = self._actual_tendency(race_evidence, "style")
            meeting_lane = self._meeting_bias_prediction(evidence, base, race_id, "lane")
            meeting_style = self._meeting_bias_prediction(evidence, base, race_id, "style")
            track_lane = self._track_bias_prediction(base.get("manual_track_bias"), "lane")
            track_style = self._track_bias_prediction(base.get("manual_track_bias"), "style")
            row = {
                "race_id": race_id,
                "race_date": base.get("race_date"),
                "racecourse": base.get("racecourse"),
                "surface": base.get("surface"),
                "distance_category": base.get("distance_category"),
                "track_condition": base.get("track_condition"),
                "meeting_stage": base.get("meeting_stage"),
                "meeting_stage_source": base.get("meeting_stage_source"),
                "meeting_stage_derivation_note": self.STAGE_DERIVATION_NOTE,
                "observed_window_hash": observed_window_hash,
                "inside_outside_actual": actual_lane.get("actual"),
                "inside_outside_actual_source": actual_lane.get("source"),
                "inside_outside_meeting_bias_prediction": meeting_lane.get("prediction"),
                "inside_outside_meeting_bias_source_count": meeting_lane.get("source_count"),
                "inside_outside_track_bias_prediction": track_lane.get("prediction"),
                "inside_outside_track_bias_source": track_lane.get("source"),
                "inside_outside_meeting_bias_result": self._result(meeting_lane.get("prediction"), actual_lane.get("actual")),
                "inside_outside_track_bias_result": self._result(track_lane.get("prediction"), actual_lane.get("actual")),
                "inside_outside_difference": self._difference(meeting_lane.get("prediction"), track_lane.get("prediction"), actual_lane.get("actual")),
                "front_closer_actual": actual_style.get("actual"),
                "front_closer_actual_source": actual_style.get("source"),
                "front_closer_meeting_bias_prediction": meeting_style.get("prediction"),
                "front_closer_meeting_bias_source_count": meeting_style.get("source_count"),
                "front_closer_track_bias_prediction": track_style.get("prediction"),
                "front_closer_track_bias_source": track_style.get("source"),
                "front_closer_meeting_bias_result": self._result(meeting_style.get("prediction"), actual_style.get("actual")),
                "front_closer_track_bias_result": self._result(track_style.get("prediction"), actual_style.get("actual")),
                "front_closer_difference": self._difference(meeting_style.get("prediction"), track_style.get("prediction"), actual_style.get("actual")),
                "score_changed": False,
                "decision_changed": False,
                "buy_changed": False,
                "production_connected": False,
                "diagnostic_only": True,
            }
            rows.append(row)
        return rows

    def _comparison_rows(self, race_rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
        rows = []
        for row in race_rows:
            for dimension, label in (
                ("inside_outside", "inside_outside_tendency"),
                ("front_closer", "front_closer_tendency"),
            ):
                rows.append(
                    {
                        "race_id": row.get("race_id"),
                        "dimension": label,
                        "meeting_bias_prediction": row.get(f"{dimension}_meeting_bias_prediction"),
                        "track_bias_prediction": row.get(f"{dimension}_track_bias_prediction"),
                        "actual": row.get(f"{dimension}_actual"),
                        "meeting_bias_result": row.get(f"{dimension}_meeting_bias_result"),
                        "track_bias_result": row.get(f"{dimension}_track_bias_result"),
                        "difference": row.get(f"{dimension}_difference"),
                        "observed_window_hash": row.get("observed_window_hash"),
                    }
                )
        return rows

    def _meeting_bias_prediction(
        self,
        evidence: list[dict[str, Any]],
        target: dict[str, Any],
        race_id: str,
        dimension: str,
    ) -> dict[str, Any]:
        key_sets = [
            ("exact", ("racecourse", "surface", "distance_category", "track_condition", "meeting_stage")),
            ("stage_surface", ("racecourse", "surface", "meeting_stage")),
            ("stage_course", ("racecourse", "meeting_stage")),
        ]
        for method, keys in key_sets:
            peers = [
                row for row in evidence
                if row.get("race_id") != race_id
                and all(row.get(key) == target.get(key) for key in keys)
            ]
            prediction = self._majority_prediction(peers, dimension)
            if prediction.get("prediction") != "NO_OBSERVATION":
                prediction["method"] = method
                return prediction
        return {"prediction": "NO_OBSERVATION", "source_count": 0, "method": "NO_PEER_EVIDENCE"}

    def _majority_prediction(self, rows: list[dict[str, Any]], dimension: str) -> dict[str, Any]:
        values = [self._pattern_tendency(row.get("observed_pattern"), dimension) for row in rows]
        values = [value for value in values if value != "NO_OBSERVATION"]
        counts = Counter(values)
        if not counts:
            return {"prediction": "NO_OBSERVATION", "source_count": 0}
        most_common = counts.most_common()
        if len(most_common) > 1 and most_common[0][1] == most_common[1][1]:
            return {"prediction": "NO_OBSERVATION", "source_count": sum(counts.values())}
        if most_common[0][1] < 2:
            return {"prediction": "NO_OBSERVATION", "source_count": most_common[0][1]}
        return {"prediction": most_common[0][0], "source_count": most_common[0][1]}

    def _actual_tendency(self, rows: list[dict[str, Any]], dimension: str) -> dict[str, Any]:
        counts = Counter(
            value for value in (self._pattern_tendency(row.get("observed_pattern"), dimension) for row in rows)
            if value != "NO_OBSERVATION"
        )
        if not counts:
            return {"actual": "NO_OBSERVATION", "source": "NO_PATTERN"}
        most_common = counts.most_common()
        if len(most_common) > 1 and most_common[0][1] == most_common[1][1]:
            return {"actual": "MIXED", "source": json.dumps(dict(counts), ensure_ascii=False, sort_keys=True)}
        return {"actual": most_common[0][0], "source": json.dumps(dict(counts), ensure_ascii=False, sort_keys=True)}

    def _pattern_tendency(self, pattern: Any, dimension: str) -> str:
        text = str(pattern or "")
        if dimension == "lane":
            if "inside_lane" in text:
                return "INSIDE"
            if "outside_lane" in text:
                return "OUTSIDE"
        if dimension == "style":
            if "front_position" in text:
                return "FRONT"
            if "closer_position" in text or "strong_late_3f" in text:
                return "CLOSER"
        return "NO_OBSERVATION"

    def _track_bias_prediction(self, manual_track_bias: Any, dimension: str) -> dict[str, str]:
        text = str(manual_track_bias or "").lower()
        if not text:
            return {"prediction": "NO_OBSERVATION", "source": "MANUAL_TRACK_BIAS_EMPTY"}
        if dimension == "lane":
            if "inside" in text or "内" in text:
                return {"prediction": "INSIDE", "source": "MANUAL_TRACK_BIAS"}
            if "outside" in text or "外" in text:
                return {"prediction": "OUTSIDE", "source": "MANUAL_TRACK_BIAS"}
        if dimension == "style":
            if "front" in text or "前" in text or "先行" in text:
                return {"prediction": "FRONT", "source": "MANUAL_TRACK_BIAS"}
            if "closer" in text or "差し" in text or "追込" in text:
                return {"prediction": "CLOSER", "source": "MANUAL_TRACK_BIAS"}
        return {"prediction": "NO_OBSERVATION", "source": "MANUAL_TRACK_BIAS_UNPARSED"}

    def _result(self, prediction: Any, actual: Any) -> str:
        if prediction in {None, "", "NO_OBSERVATION"} or actual in {None, "", "NO_OBSERVATION"}:
            return "NO_OBSERVATION"
        if actual == "MIXED":
            return "NO_OBSERVATION"
        return "AGREEMENT" if prediction == actual else "CONFLICT"

    def _difference(self, meeting_prediction: Any, track_prediction: Any, actual: Any) -> str:
        mb = self._result(meeting_prediction, actual)
        tb = self._result(track_prediction, actual)
        if mb == "AGREEMENT" and tb != "AGREEMENT":
            return "MEETING_BIAS_ADDITIVE_AGREEMENT"
        if mb == "CONFLICT" and tb == "AGREEMENT":
            return "TRACK_BIAS_BETTER"
        if mb == "AGREEMENT" and tb == "AGREEMENT":
            return "BOTH_AGREE"
        if mb == "CONFLICT" and tb == "CONFLICT":
            return "BOTH_CONFLICT"
        if mb == "NO_OBSERVATION" and tb == "NO_OBSERVATION":
            return "NO_OBSERVATION"
        return "MIXED_DIAGNOSTIC"

    def _summary(
        self,
        payload: dict[str, Any],
        race_rows: list[dict[str, Any]],
        comparison_rows: list[dict[str, Any]],
        observed_window_hash: str,
    ) -> dict[str, Any]:
        mb_agree = sum(1 for row in comparison_rows if row.get("meeting_bias_result") == "AGREEMENT")
        mb_conflict = sum(1 for row in comparison_rows if row.get("meeting_bias_result") == "CONFLICT")
        mb_observed = mb_agree + mb_conflict
        tb_agree = sum(1 for row in comparison_rows if row.get("track_bias_result") == "AGREEMENT")
        tb_conflict = sum(1 for row in comparison_rows if row.get("track_bias_result") == "CONFLICT")
        tb_observed = tb_agree + tb_conflict
        additive = sum(1 for row in comparison_rows if row.get("difference") == "MEETING_BIAS_ADDITIVE_AGREEMENT")
        return {
            "status": "REVIEW_COMPLETE",
            "version": self.VERSION,
            "generated_at": datetime.now(timezone.utc).isoformat(),
            "stage_derivation_note": self.STAGE_DERIVATION_NOTE,
            "observed_window_hash": observed_window_hash,
            "reviewed_races": payload.get("reviewed_races"),
            "reviewed_horses": payload.get("reviewed_horses"),
            "race_count": len(race_rows),
            "comparison_count": len(comparison_rows),
            "meeting_bias_observed_count": mb_observed,
            "meeting_bias_agreement_count": mb_agree,
            "meeting_bias_conflict_count": mb_conflict,
            "meeting_bias_agreement_rate": round(mb_agree / mb_observed, 4) if mb_observed else None,
            "track_bias_observed_count": tb_observed,
            "track_bias_agreement_count": tb_agree,
            "track_bias_conflict_count": tb_conflict,
            "track_bias_agreement_rate": round(tb_agree / tb_observed, 4) if tb_observed else None,
            "meeting_bias_additive_agreement_count": additive,
            "difference_counts": dict(Counter(row.get("difference") for row in comparison_rows)),
            "score_changed": False,
            "decision_changed": False,
            "buy_changed": False,
            "production_changed": False,
            "learning_changed": False,
            "knowledge_changed": False,
            "shadow_project_changed": False,
            "target_trial_adapter_run_executed": False,
            "main_py_executed": False,
            "productionization_judgment": "PROHIBITED",
        }

    def _observed_window_hash(self, evidence: list[dict[str, Any]], source_manifest: list[dict[str, Any]]) -> str:
        dates = sorted({str(row.get("race_date") or "") for row in evidence if row.get("race_date")})
        courses = sorted({str(row.get("racecourse") or "") for row in evidence if row.get("racecourse")})
        sequences = sorted(
            {
                str((row.get("meeting_stage_resolution") or {}).get("meeting_sequence_id") or "")
                for row in source_manifest
                if (row.get("meeting_stage_resolution") or {}).get("meeting_sequence_id")
            }
        )
        digest = hashlib.sha256()
        digest.update(json.dumps({"dates": dates, "racecourses": courses, "sequences": sequences}, sort_keys=True).encode("utf-8"))
        return digest.hexdigest()

    def _annotate_stage_resolution_outputs(self, observed_window_hash: str) -> None:
        summary_path = self.output_dir / "meeting_stage_resolution_summary_v2.json"
        if summary_path.exists():
            summary = self._load_json(summary_path, {})
            summary.update(
                {
                    "stage_derivation_note": self.STAGE_DERIVATION_NOTE,
                    "official_jra_meeting_number": False,
                    "repository_relative_derivation": True,
                    "future_data_may_change_resolution": True,
                    "diagnostic_use_only": True,
                    "observed_window_hash": observed_window_hash,
                }
            )
            self._write_json(summary_path, summary)

        report_path = self.output_dir / "meeting_stage_resolution_report_v2.md"
        if report_path.exists():
            text = report_path.read_text(encoding="utf-8")
            marker = "## Repository-Relative Stage Notice"
            notice = (
                f"{marker}\n\n"
                "- meeting_stage is not the official JRA meeting number.\n"
                "- meeting_stage is derived from repository-relative observed race dates.\n"
                "- The resolution may change when future repository data is added.\n"
                "- The value is limited to diagnostic use.\n"
                f"- observed_window_hash: `{observed_window_hash}`\n\n"
            )
            if marker not in text:
                text = text.replace("## Final Judgment", notice + "## Final Judgment")
                report_path.write_text(text, encoding="utf-8")

        csv_path = self.output_dir / "meeting_stage_resolution_v2.csv"
        if csv_path.exists():
            rows = self._read_csv(csv_path)
            for row in rows:
                row["stage_derivation_note"] = self.STAGE_DERIVATION_NOTE
                row["official_jra_meeting_number"] = "False"
                row["repository_relative_derivation"] = "True"
                row["future_data_may_change_resolution"] = "True"
                row["diagnostic_use_only"] = "True"
                row["observed_window_hash"] = observed_window_hash
            self._write_csv(csv_path, rows)

    def _write_report(
        self,
        path: Path,
        summary: dict[str, Any],
        race_rows: list[dict[str, Any]],
        comparison_rows: list[dict[str, Any]],
    ) -> None:
        difference_counts = Counter(row.get("difference") for row in comparison_rows)
        lines = [
            "# MeetingBias Diagnostic Shadow v1",
            "",
            "## Scope",
            "",
            "- Review Layer only.",
            "- MeetingBias is evaluated as Explain-only diagnostic information.",
            "- Score / BUY / Decision / Production are unchanged.",
            "- TrackBias is used as the control group.",
            "",
            "## Stage Derivation Notice",
            "",
            f"- {self.STAGE_DERIVATION_NOTE}",
            f"- observed_window_hash: `{summary.get('observed_window_hash')}`",
            "",
            "## Summary",
            "",
            f"- Race count: {summary.get('race_count')}",
            f"- Comparison count: {summary.get('comparison_count')}",
            f"- MeetingBias observed: {summary.get('meeting_bias_observed_count')}",
            f"- MeetingBias agreement: {summary.get('meeting_bias_agreement_count')}",
            f"- MeetingBias conflict: {summary.get('meeting_bias_conflict_count')}",
            f"- MeetingBias agreement rate: {summary.get('meeting_bias_agreement_rate')}",
            f"- TrackBias observed: {summary.get('track_bias_observed_count')}",
            f"- TrackBias agreement: {summary.get('track_bias_agreement_count')}",
            f"- TrackBias conflict: {summary.get('track_bias_conflict_count')}",
            f"- TrackBias agreement rate: {summary.get('track_bias_agreement_rate')}",
            f"- MeetingBias additive agreement: {summary.get('meeting_bias_additive_agreement_count')}",
            "",
            "## Difference Counts",
            "",
        ]
        lines.extend([f"- {key}: {value}" for key, value in sorted(difference_counts.items())])
        lines.extend(
            [
                "",
                "## Safety",
                "",
                "- TargetTrialAdapter.run executed: false",
                "- main.py executed: false",
                "- Production changed: false",
                "- Learning changed: false",
                "- Shadow Project changed: false",
                "- Knowledge changed: false",
                "",
                "## Productionization",
                "",
                "- Productionization judgment is prohibited in this phase.",
                "- This report only measures MeetingBias独自寄与, TrackBiasとの差, and Explain価値.",
                "",
                "## Final Judgment",
                "",
                "**REVIEW_COMPLETE**",
            ]
        )
        path.write_text("\n".join(lines) + "\n", encoding="utf-8")

    def _load_json(self, path: Path, default: Any) -> Any:
        if not path.exists():
            return default
        return json.loads(path.read_text(encoding="utf-8"))

    def _write_json(self, path: Path, payload: Any) -> None:
        path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")

    def _read_csv(self, path: Path) -> list[dict[str, Any]]:
        with path.open("r", encoding="utf-8-sig", newline="") as handle:
            return [dict(row) for row in csv.DictReader(handle)]

    def _write_csv(self, path: Path, rows: list[dict[str, Any]]) -> None:
        if not rows:
            path.write_text("", encoding="utf-8-sig")
            return
        fieldnames = list(rows[0].keys())
        with path.open("w", encoding="utf-8-sig", newline="") as handle:
            writer = csv.DictWriter(handle, fieldnames=fieldnames)
            writer.writeheader()
            writer.writerows(rows)


if __name__ == "__main__":
    result = MeetingBiasDiagnosticShadow().run()
    print(
        json.dumps(
            {
                "status": result.get("status"),
                "race_count": result.get("race_count"),
                "meeting_bias_additive_agreement_count": result.get("meeting_bias_additive_agreement_count"),
                "observed_window_hash": result.get("observed_window_hash"),
            },
            ensure_ascii=False,
            indent=2,
        )
    )
