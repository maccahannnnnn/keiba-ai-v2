"""Hash and output-root safety checks for Historical Replay."""
from __future__ import annotations
import ast,hashlib
from pathlib import Path

ROOT=Path(__file__).resolve().parents[1]
PROTECTED=("evaluation/target_trial_adapter.py","reports/ranking_provenance","reports/review_20260725","reports/review_20260726","reports/review_20260801","reports/review_20260802","learning","knowledge","reports/ranking_diagnostic_readiness_v1.json","reports/improvement_candidates.md","reports/improvement_candidates")
def tree_hash(path):
    path=Path(path);digest=hashlib.sha256()
    if path.is_file():return hashlib.sha256(path.read_bytes()).hexdigest()
    if not path.exists():return "MISSING"
    for item in sorted(x for x in path.rglob("*") if x.is_file()):digest.update(str(item.relative_to(path)).encode());digest.update(hashlib.sha256(item.read_bytes()).digest())
    return digest.hexdigest()
def snapshot():return {name:tree_hash(ROOT/name) for name in PROTECTED}
def _call_name(node):
    if isinstance(node,ast.Name):return node.id
    if isinstance(node,ast.Attribute):return f"{_call_name(node.value)}.{node.attr}".strip(".")
    if isinstance(node,ast.Call):return _call_name(node.func)
    if isinstance(node,ast.Subscript):return _call_name(node.value)
    return ""
def _text(node):return " ".join(str(x.value) for x in ast.walk(node) if isinstance(x,ast.Constant) and isinstance(x.value,str)).lower()
def ast_scan(scan_files=None,root=ROOT):
    root=Path(root);targets=[root/x for x in (scan_files or ("review/historical_replay_runner.py","review/historical_replay_asset_locator.py","review/historical_replay_post_race.py","review/historical_replay_ledger.py"))];findings=[];adapter_calls=[];weight_calls=[];post_calls=[];write_calls=0
    for path in targets:
        if not path.is_file():findings.append({"category":"missing_scan_target","file":str(path),"line":0,"evidence":"MISSING"});continue
        tree=ast.parse(path.read_text(encoding="utf-8"),filename=str(path));relative=path.relative_to(root).as_posix()
        for node in ast.walk(tree):
            if isinstance(node,(ast.Import,ast.ImportFrom)):
                names=[x.name for x in node.names] if isinstance(node,ast.Import) else [node.module or ""]
                if any(x in ("main","evaluation.trial_batch_runner","review.ranking_provenance_ledger") for x in names):findings.append({"category":"dangerous_import","file":relative,"line":node.lineno,"evidence":str(names)})
            if not isinstance(node,ast.Call):continue
            name=_call_name(node.func);text=_text(node);method=name.rsplit(".",1)[-1]
            if name.endswith("learning_candidate_engine.generate") or name.endswith("LearningCandidateEngine.generate"):findings.append({"category":"learning_generate_call","file":relative,"line":node.lineno,"evidence":name})
            if name.endswith("adapter.run"):
                adapter_calls.append((relative,node))
                args=[ast.unparse(x) for x in node.args]
                if relative!="review/historical_replay_runner.py" or args!="str(paths['entry']) str(paths['horses'])".split():findings.append({"category":"unauthorized_adapter_run","file":relative,"line":node.lineno,"evidence":str(args)})
            if relative=="review/historical_replay_runner.py" and name.endswith("write_weight_source"):weight_calls.append(node.lineno)
            if relative=="review/historical_replay_runner.py" and name.endswith("_post_with_sidecar"):post_calls.append(node.lineno)
            if method in {"write_text","write_bytes","writerow","writerows","dump","copy","copy2","move","replace","rename"}:write_calls+=1
            protected=("learning/","knowledge/","reports/ranking_provenance/","ranking_provenance_ledger","human_review","shadow_validation","reports/review_","reports/baseline")
            if method in {"write_text","write_bytes","writerow","writerows","dump","copy","copy2","move","replace","rename"} and any(x in text.replace("\\","/") for x in protected):findings.append({"category":"protected_write","file":relative,"line":node.lineno,"evidence":text})
            if name.endswith(("subprocess.run","subprocess.call","os.system")) and "main.py" in text:findings.append({"category":"main_execution","file":relative,"line":node.lineno,"evidence":text})
    if len(adapter_calls)!=1:findings.append({"category":"adapter_run_callsite_count","file":"SCAN_SET","line":0,"evidence":str(len(adapter_calls))})
    if len(weight_calls)!=1 or len(post_calls)!=1 or weight_calls[0]>=post_calls[0]:findings.append({"category":"post_weight_source_generation","file":"review/historical_replay_runner.py","line":0,"evidence":f"weight={weight_calls},post={post_calls}"})
    return {"status":"PASS" if targets and not findings else "FAIL","scan_target_count":len(targets),"adapter_run_callsite_count":len(adapter_calls),"write_call_count":write_calls,"finding_count":len(findings),"findings":findings}
def validate(before,run_root,scan_files=None):
    after=snapshot();changed=[key for key in before if before[key]!=after[key]];root=Path(run_root).resolve();allowed=(ROOT/"reports/historical_replay_current_code").resolve()
    scan=ast_scan(scan_files)
    return {"status":"PASS" if not changed and root.is_relative_to(allowed) and scan["status"]=="PASS" else "FAIL","protected_hash_changed":bool(changed),"changed":changed,"before":before,"after":after,"run_root_isolated":root.is_relative_to(allowed),"ast_safety":scan}
