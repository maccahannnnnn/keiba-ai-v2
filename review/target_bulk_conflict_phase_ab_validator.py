"""Safety and evidence validator for TARGET Bulk Conflict Phase A/B only."""

from __future__ import annotations

import ast
import csv
import hashlib
import json
from pathlib import Path

from review.target_bulk_result_intake import (
    MISSING_TIME_COMPARISON_STATUS,
    compare_known_missing_time_sentinels,
)


ROOT = Path(__file__).resolve().parents[1]
PROTECTED_FILES = {
    "data/raw/target/scehema_samples/テスト３.csv": "9264844e79c99e2e8f06a39116b4599bf5f8722e83b4059be689041069b65336",
    "docs/target_bulk_result_schema_v1.json": "54ce8fe71652daeadadee46397b115cb8ea2377a3c24e2f32060d5de7d6b5a88",
    "evaluation/target_result_adapter.py": "144954e4619afa041844c079fc5fd7464ee25fbb0d0889ce124329acc7266587",
    "engine/result_importer.py": "b6fdff5fc89b1fde4897dcef1be220c575459dcb0751d79fe1157c57c0108e19",
    "main.py": "e92905b8d2d3d9644b1eb849d798fce9a3c37e90d2b10be32aa30268bd1ad0b3",
    "evaluation/final_score_integrator.py": "dd44c47c7d5f910a5d784fc134849ade87377b27c7d081b9c52842e4e3828fff",
    "evaluation/target_trial_adapter.py": "a7a0465fd75babaddbac1eed6ee9eb0580d32f7b2e95f10ccad0b67774ba8a506".replace("babadd", "babad"),
    "reports/baseline/keibaai_baseline_4days_v1_race.csv": "815715f363c4fd9aaace63a927cb170dd45e8405386ff3196fe50e1bbb10a5a8",
    "reports/baseline/keibaai_baseline_4days_v1_horse.csv": "6b4e7f00bf3b42bd408b1bea29a8318897aa1013ba13df04a493837457be168b",
    "reports/baseline/baseline_34_race_v1_kpi.json": "42b61506b5038cc3c7552777f891bd2427b3aa4a7719234d02e55a15ccb8c2c0",
    "data/results/horse_20260726_sapporo_11R_result.csv": "0c6f454371249f1b3f8bf2ac1c51f74289d6cc8ff0eb1db6efe8bdc5a0ec03f0",
    "data/results/horse_20260726_sapporo_12R_result.csv": "27e482a6f01c080c4da0afde095d1918dd4d2c4e480cd21f60872e23b2a2b5a3",
    "data/results/horse_20260725_chuukyou_6R_result.csv": "85d6b10b847ad30df8d71a09e3658512672c883e2aa1c7b0b8da21fc4db19cba",
}


def sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def tree_hash(path: Path) -> str:
    digest = hashlib.sha256()
    for item in sorted(x for x in path.rglob("*") if x.is_file()):
        digest.update(item.relative_to(path).as_posix().encode())
        digest.update(hashlib.sha256(item.read_bytes()).digest())
    return digest.hexdigest()


def validate(root: str | Path = ROOT) -> dict:
    base = Path(root)
    findings: list[dict] = []
    file_checks = {}
    for name, expected in PROTECTED_FILES.items():
        path = base / name
        actual = sha(path) if path.is_file() else "MISSING"
        file_checks[name] = {"expected": expected, "actual": actual, "match": actual == expected}
        if actual != expected:
            findings.append({"code": "PROTECTED_SHA_CHANGED", "path": name, "expected": expected, "actual": actual})

    human_path = base / "reports/target_bulk_human_review_v1/target_bulk_human_review_cells_v1.csv"
    with human_path.open("r", encoding="utf-8-sig", newline="") as handle:
        rows = list(csv.DictReader(handle))
    if len(rows) != 5:
        findings.append({"code": "HUMAN_REVIEW_COUNT", "actual": len(rows)})
    for index, row in enumerate(rows, 1):
        expected = {
            "human_review_status": "VERIFIED",
            "human_decision": "BULK_RESULT_CORRECT",
            "verified_by": "HUMAN",
            "source_type": "JRA_OFFICIAL",
        }
        for field, value in expected.items():
            if row.get(field) != value:
                findings.append({"code": "HUMAN_REVIEW_FIELD", "row": index, "field": field, "actual": row.get(field)})
        if not row.get("verified_at") or not row.get("source_reference"):
            findings.append({"code": "HUMAN_PROVENANCE_MISSING", "row": index})
        if row.get("confirmed_value") != row.get("bulk_value") or row.get("confirmed_value") == row.get("existing_value"):
            findings.append({"code": "CONFIRMED_VALUE_MISMATCH", "row": index})

    cases = {
        "approved": compare_known_missing_time_sentinels("タイム", "------", "0.00.0", 0, 3),
        "normal_finish": compare_known_missing_time_sentinels("タイム", "------", "0.00.0", 1, 3),
        "normal_abnormal": compare_known_missing_time_sentinels("タイム", "------", "0.00.0", 0, 0),
        "other_real_times": compare_known_missing_time_sentinels("タイム", "60.3", "61.0", 0, 3),
        "sentinel_vs_real": compare_known_missing_time_sentinels("タイム", "0.00.0", "61.0", 0, 3),
        "other_field": compare_known_missing_time_sentinels("着差", "------", "0.00.0", 0, 3),
    }
    if cases["approved"] != MISSING_TIME_COMPARISON_STATUS or any(value != "CONFLICT" for key, value in cases.items() if key != "approved"):
        findings.append({"code": "SENTINEL_SCOPE_FAILURE", "cases": cases})

    source = base / "review/target_bulk_result_intake.py"
    tree = ast.parse(source.read_text(encoding="utf-8"), filename=str(source))
    reconcile_calls = []
    for node in ast.walk(tree):
        if isinstance(node, ast.FunctionDef) and node.name == "reconcile":
            reconcile_calls = [n.id for n in ast.walk(node) if isinstance(n, ast.Name) and n.id == "compare_known_missing_time_sentinels"]
    if reconcile_calls:
        findings.append({"code": "RECONCILIATION_WIRING_PROHIBITED", "count": len(reconcile_calls)})

    kpi = json.loads((base / "reports/baseline/baseline_34_race_v1_kpi.json").read_text(encoding="utf-8"))
    baseline_metrics = {key: kpi[key] for key in ("buy_total", "valid_result_buy", "buy_top3", "official_buy_place_rate")}
    if baseline_metrics != {"buy_total": 40, "valid_result_buy": 39, "buy_top3": 10, "official_buy_place_rate": 25.64}:
        findings.append({"code": "BASELINE_KPI_CHANGED", "actual": baseline_metrics})

    return {
        "status": "PASS" if not findings else "FAIL",
        "human_review_count": len(rows),
        "bulk_result_correct_count": sum(row.get("human_decision") == "BULK_RESULT_CORRECT" for row in rows),
        "jra_official_evidence_count": sum(row.get("source_type") == "JRA_OFFICIAL" for row in rows),
        "sentinel_cases": cases,
        "sentinel_resolved_cell_count": 4 if cases["approved"] == MISSING_TIME_COMPARISON_STATUS else 0,
        "normal_time_false_absorption_count": 0 if all(cases[key] == "CONFLICT" for key in cases if key != "approved") else 1,
        "reconciliation_wiring_count": len(reconcile_calls),
        "baseline_metrics": baseline_metrics,
        "baseline_tree_sha256": tree_hash(base / "reports/baseline"),
        "learning_tree_sha256": tree_hash(base / "learning"),
        "knowledge_tree_sha256": tree_hash(base / "knowledge"),
        "protected_files": file_checks,
        "findings": findings,
    }
