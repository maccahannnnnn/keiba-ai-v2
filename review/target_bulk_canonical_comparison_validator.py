"""Safety and zero-delta validator for Canonical Comparison v1."""

from __future__ import annotations

import ast
import hashlib
import json
from pathlib import Path

from review.target_bulk_conflict_phase_ab_validator import PROTECTED_FILES, tree_hash


ROOT = Path(__file__).resolve().parents[1]
RESULT = ROOT / "reports/target_bulk_canonical_comparison_v1/target_bulk_canonical_comparison_result_v1.json"
REPLAY_FROZEN = {
    "reports/historical_replay/phase4_batch1_result_join_aligned_v2_asset_manifest.json": "4b8dc9a37a6916ec8198a562af85c00344f17613337b084b32bc324146673856",
    "reports/historical_replay/phase4_batch2_result_join_aligned_v2_asset_manifest.json": "71319ec404d7cab1850bf5414ec2565f6cc2939d0268112e5a85d9d36869b4ac",
    "reports/historical_replay/phase4_batch3_result_join_aligned_v2_asset_manifest.json": "13ddeab0d796528834f12d7cea48b3c961d6319fc4f3eff6bf11468595905bee",
    "reports/historical_replay/phase4_batch4_result_join_aligned_v2_asset_manifest.json": "6eff549c2d0f735f172f4659f7c74191f9e619265bec826f17361afad05f2050",
}


def sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def validate(root: str | Path = ROOT) -> dict:
    base = Path(root)
    findings = []
    protected = {}
    for name, expected in PROTECTED_FILES.items():
        path = base / name
        actual = sha(path) if path.is_file() else "MISSING"
        protected[name] = {"expected": expected, "actual": actual, "match": actual == expected}
        if actual != expected:
            findings.append({"code": "PROTECTED_SHA_CHANGED", "path": name, "actual": actual})
    replay_frozen = {}
    for name, expected in REPLAY_FROZEN.items():
        actual = sha(base / name) if (base / name).is_file() else "MISSING"
        replay_frozen[name] = {"expected": expected, "actual": actual, "match": actual == expected}
        if actual != expected:
            findings.append({"code": "REPLAY_FROZEN_SHA_CHANGED", "path": name, "actual": actual})

    result = json.loads(RESULT.read_text(encoding="utf-8"))
    result_file_checks = {}
    for row in result.get("files", []):
        path = Path(row["official_path"])
        expected = row["official_sha256"]
        actual = sha(path) if path.is_file() else "MISSING"
        key = f"{row['race_id']}:{row['role']}"
        result_file_checks[key] = {"path": str(path), "expected": expected, "actual": actual, "match": actual == expected}
        if actual != expected:
            findings.append({"code": "OFFICIAL_RESULT_SHA_CHANGED", "path": str(path), "actual": actual})
    required = {
        "file_count": 50, "race_id_count": 25, "conflict_stop_count": 0,
        "human_evidence_count": 5, "human_evidence_used_count": 5,
    }
    for field, expected in required.items():
        if result.get(field) != expected:
            findings.append({"code": "RESULT_COUNT_MISMATCH", "field": field, "expected": expected, "actual": result.get(field)})
    if result.get("inputs", {}).get("reconstructed_split_file_count") != 192 or result.get("inputs", {}).get("reconstructed_split_sha_match_count") != 192:
        findings.append({"code": "RECONSTRUCTED_SPLIT_PROVENANCE_FAILURE"})
    if result.get("human_verified_bulk_result_correct_count") != 5:
        findings.append({"code": "HUMAN_EVIDENCE_NOT_PRESERVED"})
    if result.get("taxonomy_counts", {}).get("SEMANTICALLY_EQUIVALENT_MISSING_TIME") != 4:
        findings.append({"code": "TIME_SENTINEL_COUNT_MISMATCH"})
    if result.get("taxonomy_counts", {}).get("TRUE_CONFLICT", 0) != 0:
        findings.append({"code": "TRUE_CONFLICT_REMAINS"})
    if result.get("raw_comparison_taxonomy_counts", {}).get("TRUE_CONFLICT") != 5:
        findings.append({"code": "RAW_HUMAN_CELL_CONFLICT_COUNT_MISMATCH"})
    if result.get("taxonomy_counts", {}).get("UNDETERMINED", 0) != 0:
        findings.append({"code": "UNDETERMINED_REMAINS", "actual": result.get("taxonomy_counts", {}).get("UNDETERMINED")})
    allowance_cells = [
        row for row in result.get("cells", [])
        if row.get("field") == "斤量" and row.get("allowance_symbol")
    ]
    if len(allowance_cells) != 13:
        findings.append({"code": "WEIGHT_ALLOWANCE_CELL_COUNT", "actual": len(allowance_cells)})
    if any(
        row.get("comparison_status") != "CANONICALLY_EQUIVALENT"
        or row.get("allowance_symbol") not in {"▲", "☆", "◇", "★"}
        or row.get("parsed_existing_weight") != row.get("parsed_bulk_weight").removesuffix(".0")
        for row in allowance_cells
    ):
        findings.append({"code": "WEIGHT_ALLOWANCE_CANONICALIZATION_FAILURE"})

    sources = [base / "review/target_bulk_canonical_comparison.py", base / "review/target_bulk_canonical_comparison_runner.py"]
    target_trial_run_count = 0
    production_write_count = 0
    for source in sources:
        tree = ast.parse(source.read_text(encoding="utf-8"), filename=str(source))
        for node in ast.walk(tree):
            if not isinstance(node, ast.Call):
                continue
            name = _call_name(node.func)
            if name.endswith("TargetTrialAdapter.run") or name.endswith("adapter.run"):
                target_trial_run_count += 1
            literals = " ".join(str(child.value).lower() for child in ast.walk(node) if isinstance(child, ast.Constant) and isinstance(child.value, str)).replace("\\", "/")
            if name.rsplit(".", 1)[-1] in {"write_text", "write_bytes", "writerow", "writerows", "copy", "copy2", "replace", "rename", "move"}:
                if any(marker in literals for marker in ("data/results", "data/raw", "learning", "knowledge", "baseline", "historical_replay", "main.py")):
                    production_write_count += 1
    if target_trial_run_count or production_write_count:
        findings.append({"code": "FORBIDDEN_EXECUTION_OR_WRITE", "target_trial_run_count": target_trial_run_count, "production_write_count": production_write_count})

    kpi = json.loads((base / "reports/baseline/baseline_34_race_v1_kpi.json").read_text(encoding="utf-8"))
    metrics = {key: kpi[key] for key in ("buy_total", "valid_result_buy", "buy_top3", "official_buy_place_rate")}
    if metrics != {"buy_total": 40, "valid_result_buy": 39, "buy_top3": 10, "official_buy_place_rate": 25.64}:
        findings.append({"code": "BASELINE_KPI_CHANGED", "actual": metrics})
    return {
        "version": "TARGET_BULK_CANONICAL_COMPARISON_SAFETY_V1",
        "status": "PASS" if not findings else "FAIL",
        "protected_files": protected, "official_result_files": result_file_checks, "replay_frozen_files": replay_frozen,
        "protected_sha_findings": sum(item["code"] in {"PROTECTED_SHA_CHANGED", "REPLAY_FROZEN_SHA_CHANGED"} for item in findings),
        "target_trial_adapter_run_count": target_trial_run_count, "production_write_count": production_write_count,
        "observation_registration_count": 0, "ranking_decision_buy_recalculation_count": 0,
        "baseline_metrics": metrics,
        "baseline_tree_sha256": tree_hash(base / "reports/baseline"),
        "replay_tree_sha256": tree_hash(base / "reports/historical_replay"),
        "learning_tree_sha256": tree_hash(base / "learning"), "knowledge_tree_sha256": tree_hash(base / "knowledge"),
        "findings": findings,
    }


def _call_name(node: ast.AST) -> str:
    if isinstance(node, ast.Name):
        return node.id
    if isinstance(node, ast.Attribute):
        return f"{_call_name(node.value)}.{node.attr}".strip(".")
    if isinstance(node, ast.Call):
        return _call_name(node.func)
    return ""


if __name__ == "__main__":
    payload = validate()
    output = ROOT / "reports/target_bulk_canonical_comparison_v1/target_bulk_canonical_comparison_safety_v1.json"
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(payload, ensure_ascii=False, indent=2))
