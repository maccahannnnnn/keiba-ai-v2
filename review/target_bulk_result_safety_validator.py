"""Safety checks tailored to TARGET Bulk Result Intake v1."""

from __future__ import annotations

import ast
import hashlib
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
PROTECTED = (
    "engine/result_importer.py",
    "evaluation/target_result_adapter.py",
    "evaluation/target_trial_adapter.py",
    "main.py",
    "learning",
    "knowledge",
    "reports/baseline/baseline_34_race_v1_manifest.json",
    "reports/baseline/baseline_34_race_v1_kpi.json",
    "reports/historical_replay/phase4_batch1_result_join_aligned_v2_asset_manifest.json",
    "reports/historical_replay/phase4_batch2_result_join_aligned_v2_asset_manifest.json",
    "reports/historical_replay/phase4_batch3_result_join_aligned_v2_asset_manifest.json",
    "reports/historical_replay/phase4_batch4_result_join_aligned_v2_asset_manifest.json",
)


def tree_hash(path: Path) -> str:
    if path.is_file():
        return hashlib.sha256(path.read_bytes()).hexdigest()
    if not path.exists():
        return "MISSING"
    digest = hashlib.sha256()
    for item in sorted(child for child in path.rglob("*") if child.is_file()):
        digest.update(item.relative_to(path).as_posix().encode())
        digest.update(hashlib.sha256(item.read_bytes()).digest())
    return digest.hexdigest()


def snapshot(root: str | Path = ROOT) -> dict[str, str]:
    base = Path(root)
    return {item: tree_hash(base / item) for item in PROTECTED}


def validate(before: dict[str, str], *, root: str | Path = ROOT) -> dict:
    base = Path(root)
    source = base / "review" / "target_bulk_result_intake.py"
    tree = ast.parse(source.read_text(encoding="utf-8"), filename=str(source))
    findings = []
    target_result_import_count = 0
    target_trial_run_count = 0
    result_importer_reference_count = 0
    official_result_literal_count = 0
    production_write_count = 0

    for node in ast.walk(tree):
        if isinstance(node, ast.ImportFrom):
            module = node.module or ""
            if module == "evaluation.target_result_adapter":
                target_result_import_count += 1
            if module in {"engine.result_importer", "evaluation.target_trial_adapter", "main"}:
                findings.append({"code": "FORBIDDEN_IMPORT", "line": node.lineno, "detail": module})
        if not isinstance(node, ast.Call):
            continue
        name = _call_name(node.func)
        literals = " ".join(
            str(child.value).lower()
            for child in ast.walk(node)
            if isinstance(child, ast.Constant) and isinstance(child.value, str)
        ).replace("\\", "/")
        if name.endswith("TargetTrialAdapter.run") or name.endswith("adapter.run"):
            target_trial_run_count += 1
            findings.append({"code": "TARGET_TRIAL_RUN", "line": node.lineno, "detail": name})
        if "resultimporter" in name.lower() or "engine/result_importer" in literals:
            result_importer_reference_count += 1
            findings.append({"code": "RESULT_IMPORTER_REFERENCE", "line": node.lineno, "detail": name})
        if "data/results" in literals:
            official_result_literal_count += 1
            findings.append({"code": "OFFICIAL_RESULT_LITERAL", "line": node.lineno, "detail": literals})
        if name.rsplit(".", 1)[-1] in {"write_text", "write_bytes", "writerow", "writerows", "copy", "copy2", "replace", "rename", "move"}:
            if any(marker in literals for marker in ("learning", "knowledge", "baseline", "historical_replay", "main.py")):
                production_write_count += 1
                findings.append({"code": "PROTECTED_WRITE", "line": node.lineno, "detail": literals})

    if target_result_import_count != 1:
        findings.append({"code": "TARGET_RESULT_ADAPTER_IMPORT_COUNT", "line": 0, "detail": target_result_import_count})
    after = snapshot(base)
    changed = [key for key in before if before[key] != after.get(key)]
    if changed:
        findings.append({"code": "PROTECTED_SHA_CHANGED", "line": 0, "detail": changed})
    return {
        "status": "PASS" if not findings else "FAIL",
        "target_result_adapter_import_count": target_result_import_count,
        "target_trial_adapter_run_count": target_trial_run_count,
        "result_importer_reference_count": result_importer_reference_count,
        "official_result_literal_count": official_result_literal_count,
        "production_write_count": production_write_count,
        "protected_hash_changed": bool(changed),
        "changed": changed,
        "before": before,
        "after": after,
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
