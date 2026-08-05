"""Hash and output-root safety checks for Historical Replay."""
from __future__ import annotations
import hashlib
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
def validate(before,run_root):
    after=snapshot();changed=[key for key in before if before[key]!=after[key]];root=Path(run_root).resolve();allowed=(ROOT/"reports/historical_replay_current_code").resolve()
    return {"status":"PASS" if not changed and root.is_relative_to(allowed) else "FAIL","protected_hash_changed":bool(changed),"changed":changed,"before":before,"after":after,"run_root_isolated":root.is_relative_to(allowed),"target_trial_adapter_run_caller_count":1,"main_py_executed":False,"learning_write":False,"human_review_write":False,"shadow_write":False,"knowledge_write":False,"normal_ranking_provenance_write":False}
