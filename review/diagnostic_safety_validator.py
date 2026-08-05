"""Evidence-based safety validation for Ranking Provenance diagnostics."""
from __future__ import annotations

import ast
import hashlib
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
PROTECTED_PATHS = (
    "learning", "knowledge", "reports/shadow_validation",
)
PROTECTED_FILES = (
    "main.py", "evaluation/final_score_integrator.py",
    "evaluation/target_trial_adapter.py",
    "learning/candidate_review_status.json", "learning/improvement_candidates.json",
    "learning/meeting_bias_candidates.json", "reports/ranking_diagnostic_readiness_v1.json",
)
ALLOWED_WRITE_ROOTS = ("reports/ranking_provenance",)
ALLOWED_CHANGED_FILES = (
    "review/diagnostic_safety_validator.py",
    "tests/test_diagnostic_safety_validator.py",
    "review/ranking_provenance_exporter.py",
)
EXPECTED_PROTECTED_HASHES = {
    "main.py": "e92905b8d2d3d9644b1eb849d798fce9a3c37e90d2b10be32aa30268bd1ad0b3",
    "evaluation/final_score_integrator.py": "dd44c47c7d5f910a5d784fc134849ade87377b27c7d081b9c52842e4e3828fff",
    "evaluation/target_trial_adapter.py": "a7a0465fd75babadbac1eed6ee9eb0580d32f7b2e95f10ccad0b67774ba8a506",
}

WRITE_METHODS = {"write_text", "write_bytes", "dump", "writer", "writerow", "writerows", "copy", "copy2", "move", "replace", "rename"}
PROTECTED_MARKERS = {
    "learning_write_count": ("learning/", "learning\\", "candidate_review_status", "improvement_candidates"),
    "human_review_write_count": ("human review", "human_review", "horse_review", "race_review"),
    "shadow_project_write_count": ("shadow_validation", "shadow_projects"),
    "knowledge_write_count": ("knowledge/", "knowledge\\", "meeting_bias"),
}


def _sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def snapshot(paths=PROTECTED_FILES, root=ROOT):
    result={}
    for value in paths:
        path=Path(root)/value
        result[value]=_sha(path) if path.is_file() else "MISSING"
    return result


def _call_name(node):
    if isinstance(node,ast.Name):return node.id
    if isinstance(node,ast.Attribute):return f"{_call_name(node.value)}.{node.attr}".strip(".")
    if isinstance(node,ast.Call):return _call_name(node.func)
    return ""


def _literal_text(node):
    values=[]
    for child in ast.walk(node):
        if isinstance(child,ast.Constant) and isinstance(child.value,str):values.append(child.value)
    return " ".join(values).lower()


def _scan_file(path, root):
    source=path.read_text(encoding="utf-8");tree=ast.parse(source,filename=str(path));findings=[]
    relative=path.relative_to(root).as_posix() if path.is_relative_to(root) else str(path)
    is_post=relative.endswith("ranking_provenance_post_race_evaluator.py")
    is_diagnostic=not relative.endswith("evaluation/trial_batch_runner.py")
    adapter_vars=set()
    for candidate in ast.walk(tree):
        if isinstance(candidate,(ast.Assign,ast.AnnAssign)):
            value=getattr(candidate,"value",None)
            if isinstance(value,ast.Call) and _call_name(value.func) in ("TargetTrialAdapter","TargetResultAdapter"):
                targets=candidate.targets if isinstance(candidate,ast.Assign) else [candidate.target]
                adapter_vars.update(target.id for target in targets if isinstance(target,ast.Name))
    for node in ast.walk(tree):
        if isinstance(node,(ast.Import,ast.ImportFrom)):
            names=[]
            if isinstance(node,ast.Import):names=[x.name for x in node.names]
            else:names=[node.module or ""]
            for name in names:
                if is_diagnostic and name in ("evaluation.target_trial_adapter","evaluation.target_result_adapter"):
                    findings.append(("dangerous_diagnostic_import_count",relative,node.lineno,name))
        if not isinstance(node,ast.Call):continue
        name=_call_name(node.func);text=_literal_text(node)
        if name.endswith(".open") or name=="open":
            modes=[x.value for x in list(node.args[1:])+[x.value for x in node.keywords if x.arg=="mode"] if isinstance(x,ast.Constant)]
            if any(any(flag in str(mode) for flag in "wax+") for mode in modes):findings.append(("write_call_count",relative,node.lineno,text or name))
        is_write=name.rsplit(".",1)[-1] in WRITE_METHODS or name.endswith(".open") or name=="open"
        if name.rsplit(".",1)[-1] in WRITE_METHODS:findings.append(("write_call_count",relative,node.lineno,text or name))
        if is_write and ("/" in text or "\\" in text) and not any(root_name in text.replace("\\","/") for root_name in ALLOWED_WRITE_ROOTS):
            findings.append(("unauthorized_write_count",relative,node.lineno,text or name))
        receiver=name.rsplit(".",1)[0] if "." in name else ""
        if is_diagnostic and (name.endswith("TargetTrialAdapter.run") or receiver in adapter_vars or ("targettrialadapter" in _call_name(getattr(node.func,"value",None)).lower() and name.endswith(".run"))):
            findings.append(("diagnostic_target_trial_adapter_run_count",relative,node.lineno,name))
        if name.endswith("TargetResultAdapter.run"):
            findings.append(("production_calculation_change_count",relative,node.lineno,name))
        if is_post and name.endswith("write_weight_source"):
            findings.append(("post_path_writer_call_count",relative,node.lineno,name))
        if relative.endswith("evaluation/trial_batch_runner.py") and name.endswith("write_weight_source"):
            findings.append(("production_orchestration_caller_count",relative,node.lineno,name))
        if name.endswith(("subprocess.run","subprocess.call","os.system")) and "main.py" in text:
            findings.append(("production_calculation_change_count",relative,node.lineno,text))
        if any(key in text for key in ("final_score", "adjusted_score", "decision", "buy")) and name.rsplit(".",1)[-1] in WRITE_METHODS:
            findings.append(("existing_production_artifact_overwrite_count",relative,node.lineno,text))
        if name.rsplit(".",1)[-1] in WRITE_METHODS or name.endswith(".open") or name=="open":
            for category,markers in PROTECTED_MARKERS.items():
                if any(marker in text for marker in markers):findings.append((category,relative,node.lineno,text))
    return findings


def validate(scan_files=None, before_hashes=None, protected_files=PROTECTED_FILES, root=ROOT, require_operational_caller=True):
    root=Path(root).resolve();files=[Path(p) if Path(p).is_absolute() else root/p for p in (scan_files or (
        "evaluation/trial_batch_runner.py", "review/ranking_provenance_exporter.py",
        "review/ranking_provenance_post_race_evaluator.py", "review/ranking_provenance_ledger.py",
    ))]
    checks=[];all_findings=[]
    existing=[]
    for path in files:
        if not path.is_file():
            checks.append({"name":f"scan:{path}","checked":False,"method":"AST_SOURCE_SCAN","target_count":0,"finding_count":0,"status":"FAIL","error":"SCAN_TARGET_NOT_FOUND"})
            continue
        existing.append(path)
        try:
            found=_scan_file(path,root);all_findings.extend(found)
            checks.append({"name":f"scan:{path.name}","checked":True,"method":"AST_SOURCE_SCAN","target_count":1,"finding_count":len(found),"status":"PASS","error":""})
        except Exception as exc:
            checks.append({"name":f"scan:{path.name}","checked":False,"method":"AST_SOURCE_SCAN","target_count":1,"finding_count":0,"status":"FAIL","error":str(exc)})
    after=snapshot(protected_files,root);baseline=before_hashes or {key:EXPECTED_PROTECTED_HASHES.get(key,"UNVERIFIED") for key in protected_files}
    hash_errors=[]
    for key in protected_files:
        if baseline.get(key) in (None,"UNVERIFIED") or after.get(key)=="MISSING":hash_errors.append(f"UNVERIFIED:{key}")
        elif baseline.get(key)!=after.get(key):hash_errors.append(f"HASH_CHANGED:{key}")
    checks.append({"name":"protected_hashes","checked":True,"method":"SHA256_BEFORE_AFTER","target_count":len(protected_files),"finding_count":len(hash_errors),"status":"PASS" if not hash_errors else "FAIL","error":";".join(hash_errors)})
    categories=("dangerous_diagnostic_import_count","diagnostic_target_trial_adapter_run_count","post_path_writer_call_count","production_calculation_change_count","learning_write_count","human_review_write_count","shadow_project_write_count","knowledge_write_count","existing_production_artifact_overwrite_count","unauthorized_write_count","production_orchestration_caller_count")
    counts={key:sum(1 for finding in all_findings if finding[0]==key) for key in categories}
    for key in categories:
        expected=1 if key=="production_orchestration_caller_count" and require_operational_caller else 0
        checks.append({"name":key,"checked":True,"method":"AST_CALL_AND_LITERAL_SCAN","target_count":len(existing),"finding_count":counts[key],"status":"PASS" if counts[key]==expected else "FAIL","error":"" if counts[key]==expected else f"EXPECTED_{expected}_FOUND_{counts[key]}"})
    if not existing:checks.append({"name":"nonzero_scan_scope","checked":False,"method":"TARGET_COUNT","target_count":0,"finding_count":0,"status":"FAIL","error":"NO_FILES_SCANNED"})
    status="PASS" if checks and all(x["checked"] and x["status"]=="PASS" for x in checks) else "FAIL"
    return {"status":status,"scanned_file_count":len(existing),"protected_file_count":len(protected_files),**counts,"hash_changed":any(x.startswith("HASH_CHANGED") for x in hash_errors),"scan_error_count":sum(bool(x["error"]) for x in checks if x["name"].startswith("scan:")),"checks":checks,"findings":[{"category":a,"file":b,"line":c,"evidence":d} for a,b,c,d in all_findings],"protected_hashes_before":baseline,"protected_hashes_after":after,"protection_manifest":{"protected_paths":list(PROTECTED_PATHS),"protected_files":list(PROTECTED_FILES),"allowed_write_roots":list(ALLOWED_WRITE_ROOTS),"allowed_changed_files":list(ALLOWED_CHANGED_FILES)}}
