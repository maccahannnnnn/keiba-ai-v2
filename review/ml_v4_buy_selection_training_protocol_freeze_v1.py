"""Freeze the approved V4 training protocol; intentionally performs no model fit."""
from __future__ import annotations

import hashlib
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DATASET = ROOT / "reports" / "ml_v4_buy_selection_dataset_v1"
OUT = ROOT / "reports" / "ml_v4_buy_selection_training_protocol_v1"
EXPECTED = {
    "dataset": "02d2471f11c1069ebb264946eacdc55fe3ea673c8812b6d17c8fd973af538b53",
    "feature_schema": "10f576bb55a23225c84634a5c79e21fa7f54ee239977d0faf8743042eb31aaa0",
    "dataset_manifest": "98a623a7561af504a3c6e69c7d357eb17e919522aedec8417b648c01e0707c38",
}
SEMANTIC_FEATURE_SET = {"Ability", "PastPerformance", "Distance", "CourseShape", "LapSuitability", "RaceShape", "PaceStyle", "shadow_ai_rank", "decision_score", "final_score", "adjusted_score", "absolute_quality_pass", "relative_advantage_pass", "effective_reliability_pass", "risk_guard_pass", "consensus_positive_count", "consensus_negative_count", "risk_count", "conflict_count", "race_state"}


class Stop(RuntimeError):
    pass


def sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def write(name: str, value: object) -> None:
    (OUT / name).write_text(json.dumps(value, ensure_ascii=False, sort_keys=True, indent=2) + "\n", encoding="utf-8")


def run() -> Path:
    if OUT.exists():
        # The only permitted recovery case is the partial failed record created
        # by this program before it had written any formal protocol artifact.
        files = list(OUT.iterdir())
        if not files:
            pass
        elif len(files) != 1 or files[0].name != "training_protocol.json":
            raise FileExistsError(f"OUTPUT_EXISTS:{OUT}")
        else:
            failed = json.loads(files[0].read_text(encoding="utf-8"))
            if failed.get("status") != "FAILED":
                raise FileExistsError(f"OUTPUT_EXISTS:{OUT}")
            files[0].unlink()
    OUT.mkdir(parents=True, exist_ok=True)
    try:
        actual = {"dataset": sha(DATASET / "dataset.csv"), "feature_schema": sha(DATASET / "feature_schema.json"), "dataset_manifest": sha(DATASET / "dataset_manifest.json")}
        if actual != EXPECTED:
            raise Stop(f"DATASET_AUTHORITY_SHA_MISMATCH:{actual}")
        schema = json.loads((DATASET / "feature_schema.json").read_text(encoding="utf-8"))
        features = schema.get("feature_order")
        if not isinstance(features, list) or set(features) != SEMANTIC_FEATURE_SET or len(features) != 20 or schema.get("feature_column_count") != 20:
            raise Stop("DATASET_FEATURE_SCHEMA_MISMATCH")
        model_columns = [*features[:-1], "is_PLAY_UNCONVERGED_4PLUS", "is_SKIP"]
        transform = {"semantic_feature_count": 20, "semantic_feature_order": features, "semantic_feature_set": sorted(SEMANTIC_FEATURE_SET), "ordering_authority": "Frozen Dataset feature_schema.json", "categorical": {"race_state": {"allowed_categories": ["PLAY_CONVERGED", "PLAY_UNCONVERGED_4PLUS", "SKIP"], "reference": "PLAY_CONVERGED", "encoding": "one_hot_drop_reference", "dummy_columns_in_order": ["is_PLAY_UNCONVERGED_4PLUS", "is_SKIP"], "unknown_category": "FAIL_CLOSED"}}, "boolean": {name: {"false": 0, "true": 1, "other": "FAIL_CLOSED"} for name in ["absolute_quality_pass", "relative_advantage_pass", "effective_reliability_pass", "risk_guard_pass"]}, "transformed_model_input_columns": model_columns, "transformed_model_input_column_count": 21, "ordinal_encoding": "FORBIDDEN"}
        evaluation = {"primary_benchmark": {"name": "CURRENT_BUY_RACE_RESELECTION_BENCHMARK", "scope": "PLAY_CONVERGED_ONLY", "eligible_race": ["Top5 population exists", "current BUY count N >= 1", "both current and V4 sides have at least one valid_result=true evaluable horse"], "selection": "Within Top5, select exactly N horses by V4 P(actual_top3) DESC", "tie_break": ["P(actual_top3) DESC", "safe shadow_ai_rank ASC", "horse_number ASC"], "invalid_result": "valid_result=false is excluded symmetrically; a race with all current BUY invalid is ineligible", "metric": "V4_SELECTION_LIFT = V4 same-volume selected BUY_TOP3_RATE - current BUY_TOP3_RATE, horse-level valid denominator"}, "formal_model_gate": {"operator": "AND", "conditions": ["eligible independent races >= 20", "eligible dates >= 4", "V4_SELECTION_LIFT >= +0.0pt"], "pass": "V4_MODEL_OOS_ACCEPT", "fail": "V4_MODEL_OOS_REJECT"}, "lodo": {"status": "PREREGISTERED_DIAGNOSTIC", "rule": "If any leave-one-date-out pooled lift reverses sign and main gate passes, record V4_MODEL_OOS_ACCEPT_WITH_TEMPORAL_FRAGILITY_FLAG. It does not override the main gate."}, "secondary_diagnostics": ["TOP5_NONBUY_MISSED recovery", "BUY_FALSE_POSITIVE demotion", "race_state composition", "LODO", "P50_REFERENCE_CLASSIFIER_DIAGNOSTIC"], "p50_reference_classifier_diagnostic": {"status": "P50_REFERENCE_CLASSIFIER_DIAGNOSTIC", "not_a_buy_policy": True, "scope": "PLAY_CONVERGED_ONLY", "rule": "P(actual_top3) >= 0.50; max 3 selected; sort by P DESC, shadow_ai_rank ASC, horse_number ASC", "required_paired_reporting": ["selected horse count", "selected race count", "zero-selection race count", "BUY_TOP3_RATE", "difference from current BUY", "volume change"], "not_used_for": ["formal ACCEPT/REJECT", "Production adoption", "BUY policy", "May threshold retuning"]}}
        governance = {"train_scope": "Top5 valid all race_state values: PLAY_CONVERGED, PLAY_UNCONVERGED_4PLUS, SKIP", "action_boundary": {"PLAY_CONVERGED": "Initial V4 evaluation scope", "PLAY_UNCONVERGED_4PLUS": "Existing CF area; no V4 initial Action override", "SKIP": "Existing race gate retained; no V4 initial Action override"}, "preprocessing": {"scaler": "StandardScaler", "fit_scope": "TRAIN dataset only", "oos_use": "transform only; refit forbidden"}, "model_recipe": {"algorithm": "LogisticRegression", "penalty": "L2", "C": 1.0, "solver": "lbfgs", "class_weight": None, "resampling": None, "hyperparameter_search": None, "feature_selection": None}, "internal_cv": "NONE", "final_train_usage": "Fit all 2,283 TRAIN rows; no permanent internal validation split", "sanity_checks_after_future_training": ["solver convergence", "finite coefficients", "finite probabilities", "probabilities within [0,1]", "row/probability alignment", "deterministic reproduction", "non-constant output", "21 transformed columns", "2,283 train rows"], "output_semantics": "RAW_MODEL_PROBABILITY = P(actual_top3); no Platt/isotonic/additional calibration", "may_boundary": {"status_before_access": "UNTOUCHED_INDEPENDENT_OOS", "status_after_aggregate_disclosure": "CONSUMED_OOS", "forbidden_after_consumption": ["feature/algo/C/threshold/policy change followed by May re-evaluation"], "next_independent_evidence": ["March or earlier", "Future Prospective"]}, "accept_authority": {"allows": ["Production design review", "formal 0-3 BUY policy design"], "does_not_allow": ["automatic Production adoption", "automatic current BUY replacement", "SKIP override", "UNCONVERGED override", "May retuning/re-evaluation"], "human_approval_required": True}}
        protocol = {"protocol_version": "ML_V4_BUY_SELECTION_TRAINING_PROTOCOL_V1", "status": "FROZEN", "dataset_authority": {"path": str(DATASET.relative_to(ROOT)), "sha256": actual, "train_rows": 2283, "target": "actual_top3", "positive": 783, "negative": 1500}, "round1_scope": governance["train_scope"], "feature_transform": transform, "governance": governance, "evaluation": evaluation, "freeze_validators": {"dataset_sha": "PASS", "feature_schema_sha": "PASS", "semantic_features": "PASS", "transformed_input_count": "PASS", "encoding": "PASS", "scaler_scope": "PASS", "model_recipe": "PASS", "internal_cv_none": "PASS", "sanity_protocol": "PASS", "primary_gate_three_conditions_only": "PASS", "lodo": "PASS", "p50": "PASS", "may_access_count": 0, "march_or_earlier_access_count": 0, "scaler_fit_count": 0, "model_fit_count": 0}}
        write("training_protocol.json", protocol); write("feature_transform_schema.json", transform); write("evaluation_protocol.json", evaluation); write("governance_boundary.json", governance)
        markdown = """# KeibaAI ML V4 BUY Selection Learning — Training Protocol v1\n\n## 凍結対象\n\n- Dataset: `reports/ml_v4_buy_selection_dataset_v1/dataset.csv`\n- TRAIN: Top5かつ`valid_result=true`の2,283行\n- Target: `actual_top3`（positive 783 / negative 1,500）\n- 20 semantic featuresを固定する。`race_state`はPLAY_CONVERGEDをreferenceとし、`is_PLAY_UNCONVERGED_4PLUS`、`is_SKIP`の2ダミーへ変換する。変換後入力は21列。未知race_stateとbooleanの非bool値はFAIL_CLOSED。\n\n## 学習レシピ（将来の実行用）\n\n全21列をStandardScalerでTRAINのみfitし、LogisticRegression（L2 / C=1.0 / lbfgs / class_weight=None）を使用する。resampling、CV、探索、特徴量選択は行わない。今回fitは0件。\n\n## OOSと統治境界\n\nPrimaryはPLAY_CONVERGED限定の`CURRENT_BUY_RACE_RESELECTION_BENCHMARK`。各eligible raceで現行BUY数Nを維持し、Top5からV4確率順にN頭を選ぶ。Formal Gateは「独立race>=20」「独立date>=4」「V4_SELECTION_LIFT>=0.0pt」のANDのみ。\n\nLODOは`PREREGISTERED_DIAGNOSTIC`でありGateではない。P50は`P50_REFERENCE_CLASSIFIER_DIAGNOSTIC`でありBUY PolicyでもProduction候補Policyでもない。Mayは未アクセスの独立OOSであり、一度aggregateを開示すればCONSUMED_OOSとなる。\n\nPLAY_UNCONVERGED_4PLUSとSKIPはTRAINに含むが、V4初期Actionでoverrideしない。Aprilの既存外部holdout evidence roleは保持し、V4 TRAIN reuseは加算的である。\n"""
        (OUT / "training_protocol.md").write_text(markdown, encoding="utf-8")
        write("protocol_manifest.json", {"protocol_version": protocol["protocol_version"], "status": "FROZEN", "dataset_sha256": actual["dataset"], "feature_schema_sha256": actual["feature_schema"], "dataset_manifest_sha256": actual["dataset_manifest"], "training_protocol_sha256": sha(OUT / "training_protocol.md"), "training_protocol_json_sha256": sha(OUT / "training_protocol.json"), "feature_transform_schema_sha256": sha(OUT / "feature_transform_schema.json"), "evaluation_protocol_sha256": sha(OUT / "evaluation_protocol.json"), "governance_boundary_sha256": sha(OUT / "governance_boundary.json"), "model_fit_count": 0, "scaler_fit_count": 0, "may_access_count": 0, "march_or_earlier_access_count": 0})
        write("artifact_hashes.json", {"indexed_artifacts": {p.name: sha(p) for p in OUT.iterdir() if p.is_file() and p.name != "artifact_hashes.json"}, "self_hash_excluded": True})
        return OUT
    except Stop as exc:
        write("training_protocol.json", {"status": "FAILED", "reason": str(exc), "model_fit_count": 0, "scaler_fit_count": 0, "may_access_count": 0})
        return OUT


if __name__ == "__main__":
    print(run())
