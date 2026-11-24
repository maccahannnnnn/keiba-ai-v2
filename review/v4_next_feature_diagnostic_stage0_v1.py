"""Consumed-data-only March/February BUY precision diagnostic Stage-0."""
from __future__ import annotations

import csv
import hashlib
import itertools
import json
import math
import statistics
import sys
from pathlib import Path
from typing import Any

import numpy as np
from sklearn.linear_model import LogisticRegression
from sklearn.metrics import roc_auc_score
from sklearn.preprocessing import StandardScaler

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from review.historical_replay_post_race import result_semantics
from review.v4_model_v4_train_ablation_v1 import BASE, MARCH, matrix


OUT = ROOT / "reports" / "v4_next_feature_diagnostic_stage0_v1"
ABLATION = ROOT / "reports" / "v4_model_v4_train_ablation_v1"
V3 = ROOT / "reports" / "ml_v4_buy_selection_dataset_v3"
V4 = ROOT / "reports" / "ml_v4_buy_selection_dataset_v4"
FEB_PRE = ROOT / "reports" / "v4_model_v4_february_historical_holdout" / "formal_pre"
FEB_POST = ROOT / "reports" / "v4_model_v4_february_historical_holdout" / "formal_post"
RAW = ROOT / "data" / "raw" / "target" / "daily_result_list"
BLOCKS = ("April", "May 2026 Independent OOS additive TRAIN reuse for V4 Model v3+", "June", "July H1", "July H2", "August Development", "August Development (Prospective)")
SMALL = "August Development (Prospective)"
DATES = ["20260201", "20260207", "20260208", "20260210", "20260214", "20260215", "20260221", "20260222", "20260228"]
SEED = 20260831
BOOTSTRAPS = 10000
ABNORMAL = {"中止", "除外", "取消", "失格"}


class Stop(RuntimeError):
    pass


def sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def load_json(path: Path) -> dict[str, Any]:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise Stop(f"JSON_OBJECT_REQUIRED:{path}")
    return value


def dump(name: str, value: Any) -> None:
    (OUT / name).write_text(json.dumps(value, ensure_ascii=False, sort_keys=True, indent=2) + "\n", encoding="utf-8")


def csv_rows(path: Path) -> list[dict[str, str]]:
    with path.open(encoding="utf-8", newline="") as handle:
        return list(csv.DictReader(handle))


def check_index(root: Path) -> int:
    indexed = load_json(root / "artifact_hashes.json").get("indexed_artifacts", load_json(root / "artifact_hashes.json").get("hashes"))
    if not isinstance(indexed, dict):
        raise Stop(f"HASH_INDEX_INVALID:{root}")
    for name, expected in indexed.items():
        if not isinstance(expected, str) or not (root / name).is_file() or sha(root / name) != expected:
            raise Stop(f"HASH_INDEX_MISMATCH:{root}:{name}")
    return len(indexed)


def auc_predictions(train: list[dict[str, str]], valid: list[dict[str, str]]) -> tuple[np.ndarray, np.ndarray]:
    x_train, y_train = matrix(train, False)
    x_valid, y_valid = matrix(valid, False)
    if len(set(y_train)) != 2 or len(set(y_valid)) != 2:
        raise Stop("FOLD_CLASS_DEGENERACY")
    scaler = StandardScaler()
    model = LogisticRegression(penalty="l2", C=1.0, solver="lbfgs", class_weight=None)
    return y_valid, model.fit(scaler.fit_transform(x_train), y_train).predict_proba(scaler.transform(x_valid))[:, 1]


def percentile(values: list[float], q: float) -> float:
    return float(np.percentile(np.asarray(values, dtype=float), q))


def rank(values: list[float]) -> list[float]:
    ordered = sorted(enumerate(values), key=lambda pair: pair[1])
    ranks = [0.0] * len(values)
    cursor = 0
    while cursor < len(ordered):
        end = cursor + 1
        while end < len(ordered) and ordered[end][1] == ordered[cursor][1]:
            end += 1
        value = (cursor + 1 + end) / 2.0
        for index, _ in ordered[cursor:end]:
            ranks[index] = value
        cursor = end
    return ranks


def pearson(left: list[float], right: list[float]) -> float:
    mean_l, mean_r = statistics.mean(left), statistics.mean(right)
    numerator = sum((x - mean_l) * (y - mean_r) for x, y in zip(left, right))
    denom = math.sqrt(sum((x - mean_l) ** 2 for x in left) * sum((y - mean_r) ** 2 for y in right))
    return numerator / denom if denom else 0.0


def fold_bootstrap() -> tuple[dict[str, Any], dict[str, Any]]:
    v3, v4 = csv_rows(V3 / "dataset.csv"), csv_rows(V4 / "dataset.csv")
    existing = [row for row in v4 if row["source_block"] != MARCH]
    march = [row for row in v4 if row["source_block"] == MARCH]
    if len(v3) != 3240 or len(v4) != 4100 or len(march) != 860 or {row["row_id"] for row in existing} != {row["row_id"] for row in v3}:
        raise Stop("FROZEN_DEVELOPMENT_DATASET_RELATION_MISMATCH")
    frozen_pairs = load_json(ABLATION / "pairwise_comparisons.json")["comparisons"]["C_minus_A"]
    frozen_delta = {row["validation_block"]: row["auc_delta"] for row in frozen_pairs}
    rng = np.random.default_rng(SEED)
    folds: list[dict[str, Any]] = []
    for block in BLOCKS:
        valid = [row for row in existing if row["source_block"] == block]
        train = [row for row in existing if row["source_block"] != block]
        target, a_probability = auc_predictions(train, valid)
        target_c, c_probability = auc_predictions([*train, *march], valid)
        if not np.array_equal(target, target_c):
            raise Stop(f"PAIRED_VALIDATION_TARGET_MISMATCH:{block}")
        observed = float(roc_auc_score(target, c_probability) - roc_auc_score(target, a_probability))
        if not math.isclose(observed, frozen_delta[block], abs_tol=1e-12):
            raise Stop(f"FROZEN_C_MINUS_A_REPRODUCTION_MISMATCH:{block}")
        draws: list[float] = []
        discarded = 0
        while len(draws) < BOOTSTRAPS:
            take = rng.integers(0, len(target), size=len(target))
            y = target[take]
            if len(np.unique(y)) != 2:
                discarded += 1
                continue
            draws.append(float(roc_auc_score(y, c_probability[take]) - roc_auc_score(y, a_probability[take])))
        folds.append({
            "validation_block": block, "n": len(target), "positive_count": int(target.sum()), "negative_count": int(len(target) - target.sum()),
            "observed_delta_auc": observed, "bootstrap_replicates": BOOTSTRAPS, "bootstrap_seed": SEED,
            "bootstrap_mean": statistics.mean(draws), "bootstrap_standard_error": statistics.stdev(draws),
            "bootstrap_percentile_95_interval": [percentile(draws, 2.5), percentile(draws, 97.5)],
            "positive_replicate_fraction": sum(value > 0 for value in draws) / len(draws), "discard_count": discarded,
        })
    sizes = [float(row["n"]) for row in folds]
    deltas = [float(row["observed_delta_auc"]) for row in folds]
    rho = pearson(rank(sizes), rank(deltas))
    permutation = [pearson(rank(sizes), list(values)) for values in itertools.permutations(rank(deltas))]
    exact_p = sum(abs(value) >= abs(rho) - 1e-12 for value in permutation) / len(permutation)
    slope = sum((x - statistics.mean(sizes)) * (y - statistics.mean(deltas)) for x, y in zip(sizes, deltas)) / sum((x - statistics.mean(sizes)) ** 2 for x in sizes)
    association = {
        "label": "LOW_POWER_EXPLORATORY_DIAGNOSTIC_ONLY", "fold_count": 7,
        "fold_size": sizes, "observed_c_minus_a_delta_auc": deltas,
        "spearman_rho": rho, "exact_permutation_two_sided_p_value": exact_p,
        "descriptive_linear_slope_delta_auc_per_row": slope,
    }
    smallest = next(row for row in folds if row["validation_block"] == SMALL)
    other_intervals = [row["bootstrap_percentile_95_interval"] for row in folds if row["validation_block"] != SMALL]
    overlap = any(smallest["bootstrap_percentile_95_interval"][0] <= interval[1] and interval[0] <= smallest["bootstrap_percentile_95_interval"][1] for interval in other_intervals)
    if exact_p > 0.10 or overlap:
        status = "FOLD_SIZE_SENSITIVITY_NOT_DISTINGUISHABLE_FROM_SAMPLING_VARIANCE"
    elif abs(rho) < 0.75:
        status = "FOLD_SIZE_ASSOCIATION_DIRECTIONAL_ONLY"
    else:
        status = "FOLD_SIZE_ASSOCIATION_STRUCTURALLY_PLAUSIBLE_REQUIRES_STAGE1"
    association.update({"smallest_fold": SMALL, "smallest_fold_n": smallest["n"], "smallest_fold_observed_delta_auc": smallest["observed_delta_auc"], "smallest_fold_interval_overlaps_another_fold": overlap, "smallest_fold_interpretation": status})
    return {"status": "PASS", "comparison": "C_MINUS_A", "frozen_development_comparison": "same seven existing validation folds; A=old six TRAIN blocks / 20 features; C=A plus March additive TRAIN reuse / same 20 features", "folds": folds}, association


def raw_outcomes() -> dict[tuple[str, str, int, int], dict[str, Any]]:
    answer: dict[tuple[str, str, int, int], dict[str, Any]] = {}
    for date in DATES:
        path = RAW / f"馬番順着順_{date}.csv"
        if not path.is_file():
            raise Stop(f"CONSUMED_RESULT_SOURCE_MISSING:{date}")
        with path.open(encoding="cp932", newline="") as handle:
            for row in csv.reader(handle):
                venue, race_number, head = row[1], int(row[2]), int(row[9])
                for horse_number in range(1, head + 1):
                    raw = row[11 + horse_number].strip()
                    if raw.isdigit() and int(raw) > 0:
                        semantics = result_semantics({"馬番": str(horse_number), "確定着順": raw, "異常コード": "0"})
                    elif raw in ABNORMAL or raw == "0":
                        semantics = result_semantics({"馬番": str(horse_number), "確定着順": "0", "異常コード": raw or "0"})
                    else:
                        raise Stop(f"CONSUMED_RESULT_SEMANTICS_UNRESOLVED:{date}:{venue}:{race_number}:{horse_number}")
                    answer[(date, venue, race_number, horse_number)] = {"raw_result_value": raw, **semantics}
    return answer


def v4_top5() -> dict[str, list[dict[str, Any]]]:
    records = load_json(FEB_PRE / "v4_prediction.json")["inference_records"]
    result = {record["race_id"]: record["top5_probabilities"] for record in records}
    if len(result) != 81 or any(len(rows) != 5 for rows in result.values()):
        raise Stop("FROZEN_V4_TOP5_UNIVERSE_INVALID")
    return result


def current_top5(item: dict[str, Any]) -> list[dict[str, Any]]:
    path = FEB_PRE / "current_ai" / item["date"] / f"{item['race_id']}_prediction.json"
    payload = load_json(path)
    rows = payload.get("top5")
    if not isinstance(rows, list) or len(rows) != 5:
        raise Stop(f"FROZEN_CURRENT_TOP5_INVALID:{item['race_id']}")
    return rows


def february_null_controls() -> tuple[dict[str, Any], dict[str, Any], dict[str, Any], dict[str, Any]]:
    eligible = load_json(FEB_PRE / "formal_eligible_population.json")["eligible_races"]
    top5 = v4_top5()
    outcomes = raw_outcomes()
    focal = [item for item in eligible if item["current_buy_count"] == 1 and item["replacement_depth"] == 1]
    if len(focal) != 30:
        raise Stop(f"FROZEN_FOCAL_CELL_MISMATCH:{len(focal)}")
    records: list[dict[str, Any]] = []
    for item in focal:
        current_out = item["current_selected_horses"]
        v4_in = item["v4_selected_horses"]
        if len(current_out) != 1 or len(v4_in) != 1 or current_out[0]["horse_number"] == v4_in[0]["horse_number"]:
            raise Stop(f"FROZEN_REPLACEMENT_PAIR_INVALID:{item['race_id']}")
        current = current_out[0]
        replacement = v4_in[0]
        frozen_current = current_top5(item)
        candidate_universe = top5.get(item["race_id"])
        if candidate_universe is None:
            raise Stop(f"FROZEN_V4_TOP5_RACE_MISSING:{item['race_id']}")
        current_number, replacement_number = int(current["horse_number"]), int(replacement["horse_number"])
        universe_numbers = [int(row["horse_number"]) for row in candidate_universe]
        if current_number not in universe_numbers or replacement_number not in universe_numbers:
            raise Stop(f"FROZEN_RESELECTION_UNIVERSE_MISMATCH:{item['race_id']}")
        alternatives = [row for row in frozen_current if int(row["horse_number"]) != current_number and int(row["horse_number"]) in universe_numbers]
        if not alternatives:
            raise Stop(f"MECHANICAL_CURRENT_NEXT_RANK_UNCONSTRUCTABLE:{item['race_id']}")
        mechanical = min(alternatives, key=lambda row: (int(row["rank"]), int(row["horse_number"])))
        def result_for(horse: dict[str, Any]) -> dict[str, Any]:
            number = int(horse["horse_number"])
            venue_map = {"sapporo":"札幌", "tokyo":"東京", "kyoto":"京都", "kokura":"小倉", "nakayama":"中山", "hanshin":"阪神"}
            result = outcomes.get((item["date"], venue_map[item["venue"]], int(item["race_number"]), number))
            if result is None:
                raise Stop(f"CONSUMED_RESULT_JOIN_UNRESOLVED:{item['race_id']}:{number}")
            return {"horse_number": number, "horse_name": horse.get("horse_name"), **result}
        current_result, v4_result, mechanical_result = result_for(current), result_for(replacement), result_for(mechanical)
        records.append({"date": item["date"], "race_id": item["race_id"], "venue": item["venue"], "race_number": item["race_number"], "current_out": {**current, "current_rank": next(row["rank"] for row in frozen_current if int(row["horse_number"]) == current_number), "outcome": current_result}, "v4_in": {**replacement, "outcome": v4_result}, "mechanical_current_next_rank_alternative": {**mechanical, "outcome": mechanical_result}, "frozen_candidate_universe": candidate_universe})
    def count(key: str) -> dict[str, Any]:
        values = [record[key]["outcome"] for record in records]
        valid = [value for value in values if value["valid_result"]]
        return {"selected_count": len(values), "valid_count": len(valid), "invalid_count": len(values) - len(valid), "top3_hits": sum(value["actual_top3"] for value in valid), "top3_rate": sum(value["actual_top3"] for value in valid) / len(valid) if valid else None}
    current_metric, v4_metric, mechanical_metric = count("current_out"), count("v4_in"), count("mechanical_current_next_rank_alternative")
    if (current_metric["top3_hits"], v4_metric["top3_hits"], current_metric["valid_count"], v4_metric["valid_count"]) != (4, 13, 30, 30):
        raise Stop("FROZEN_FOCAL_OUTCOME_REPRODUCTION_MISMATCH")
    pairs = [int(record["v4_in"]["outcome"]["actual_top3"]) - int(record["current_out"]["outcome"]["actual_top3"]) for record in records]
    v4_vs_mechanical = [int(record["v4_in"]["outcome"]["actual_top3"]) - int(record["mechanical_current_next_rank_alternative"]["outcome"]["actual_top3"]) for record in records]
    primary = {"label": "POST_HOC_REPLACEMENT_ACTIVE_SUBSET_DIAGNOSTIC_ONLY", "definition": "buy_volume=1 AND replacement_depth=1", "race_count": len(records), "current": current_metric, "v4": v4_metric, "raw_hit_difference": v4_metric["top3_hits"] - current_metric["top3_hits"], "lift_percentage_points": (v4_metric["top3_rate"] - current_metric["top3_rate"]) * 100, "records": records}
    mechanical = {"control": "MECHANICAL_CURRENT_NEXT_RANK_ALTERNATIVE", "definition": "highest frozen Current Top5 rank not equal to the single Current BUY and present in frozen V4 Top5 universe", "race_count": len(records), "mechanical": mechanical_metric, "v4": v4_metric, "raw_hit_difference_v4_minus_mechanical": v4_metric["top3_hits"] - mechanical_metric["top3_hits"], "lift_percentage_points_v4_minus_mechanical": (v4_metric["top3_rate"] - mechanical_metric["top3_rate"]) * 100, "paired_win_tie_loss_v4_vs_mechanical": {"win": sum(x > 0 for x in v4_vs_mechanical), "tie": sum(x == 0 for x in v4_vs_mechanical), "loss": sum(x < 0 for x in v4_vs_mechanical)}}
    pair = {"v4_replacement_vs_current_out": {"plus_1": sum(x == 1 for x in pairs), "zero": sum(x == 0 for x in pairs), "minus_1": sum(x == -1 for x in pairs), "net_contribution": sum(pairs)}, "v4_replacement_vs_mechanical": {"plus_1": sum(x == 1 for x in v4_vs_mechanical), "zero": sum(x == 0 for x in v4_vs_mechanical), "minus_1": sum(x == -1 for x in v4_vs_mechanical), "net_contribution": sum(v4_vs_mechanical)}}
    rng = np.random.default_rng(SEED)
    counts: list[int] = []
    universes = [[row for row in record["frozen_candidate_universe"] if int(row["horse_number"]) != int(record["current_out"]["horse_number"])] for record in records]
    for universe in universes:
        if not universe:
            raise Stop("RANDOM_NULL_UNIVERSE_EMPTY")
    for _ in range(BOOTSTRAPS):
        total = 0
        for record, universe in zip(records, universes):
            row = universe[int(rng.integers(0, len(universe)))]
            number = int(row["horse_number"])
            result = outcomes[(record["date"], {"sapporo":"札幌", "tokyo":"東京", "kyoto":"京都", "kokura":"小倉", "nakayama":"中山", "hanshin":"阪神"}[record["venue"]], int(record["race_number"]), number)]
            total += int(result["actual_top3"])
        counts.append(total)
    random_control = {"control": "RANDOM_NON_CURRENT_ALTERNATIVE", "seed": SEED, "iterations": BOOTSTRAPS, "candidate_universe": "frozen V4 Top5 reselection candidate universe excluding the Current BUY; no V4 probability used for sampling", "mean_random_hits": statistics.mean(counts), "median_random_hits": statistics.median(counts), "percentile_2_5_hits": percentile(counts, 2.5), "percentile_97_5_hits": percentile(counts, 97.5), "expected_random_top3_rate": statistics.mean(counts) / len(records), "probability_random_hits_ge_observed_v4_13": sum(value >= v4_metric["top3_hits"] for value in counts) / len(counts), "observed_v4_hits": v4_metric["top3_hits"]}
    return primary, mechanical, random_control, pair


def depth_volume_context() -> dict[str, Any]:
    rows = load_json(FEB_POST / "race_level_comparison.json")["races"]
    target = {(0, 1): 11, (0, 2): 5, (0, 3): 3, (1, 1): 30, (1, 2): 13, (1, 3): 8, (2, 2): 10, (2, 3): 1}
    table = []
    for key, expected in target.items():
        subset = [row for row in rows if row["replacement_depth"] == key[0] and row["buy_volume"] == key[1]]
        if len(subset) != expected:
            raise Stop(f"FROZEN_DEPTH_VOLUME_TABLE_MISMATCH:{key}:{len(subset)}")
        current = sum(row["current"]["top3_hits"] for row in subset)
        v4 = sum(row["v4"]["top3_hits"] for row in subset)
        table.append({"replacement_depth": key[0], "buy_volume": key[1], "race_count": len(subset), "selection_count": sum(row["current"]["selected_count"] for row in subset), "current_hits": current, "v4_hits": v4, "raw_hit_difference": v4 - current})
    active = [row for row in rows if row["replacement_depth"] >= 1]
    return {"label": "DESCRIPTIVE_CONTEXT_ONLY", "replacement_active": {"race_count": len(active), "selection_count": sum(row["current"]["selected_count"] for row in active), "current_hits": sum(row["current"]["top3_hits"] for row in active), "v4_hits": sum(row["v4"]["top3_hits"] for row in active)}, "depth_buy_volume_table": table, "depth_2_label": "INSUFFICIENT_EFFECT_MAGNITUDE_FOR_MECHANISTIC_INTERPRETATION"}


def main() -> int:
    if OUT.exists():
        raise FileExistsError(f"EXCLUSIVE_CREATE_REQUIRED:{OUT}")
    before = {"ablation_index": sha(ABLATION / "artifact_hashes.json"), "february_pre_index": sha(FEB_PRE / "artifact_hashes.json"), "february_post_index": sha(FEB_POST / "artifact_hashes.json")}
    checks = {"ablation_artifacts_verified": check_index(ABLATION), "february_pre_artifacts_verified": check_index(FEB_PRE), "february_post_artifacts_verified": check_index(FEB_POST)}
    bootstrap, association = fold_bootstrap()
    primary, mechanical, random_control, pairs = february_null_controls()
    context = depth_volume_context()
    h2 = mechanical["raw_hit_difference_v4_minus_mechanical"] > 0 and random_control["probability_random_hits_ge_observed_v4_13"] <= 0.05
    h1 = primary["current"]["top3_rate"] < random_control["expected_random_top3_rate"] and not h2
    h3 = association["smallest_fold_interpretation"] == "FOLD_SIZE_SENSITIVITY_NOT_DISTINGUISHABLE_FROM_SAMPLING_VARIANCE"
    status = "FAMILY_F_INVESTIGATION_JUSTIFIED" if h2 and not h1 else "FURTHER_DIAGNOSTIC_REQUIRED" if h1 or h3 else "NOT_JUSTIFIED"
    assessment = {"H1_current_buy_boundary_marginality": "SUPPORTED" if h1 else "NOT_ESTABLISHED", "H2_v4_additional_ranking_discrimination": "SUPPORTED" if h2 else "NOT_ESTABLISHED", "H3_population_composition": "SUPPORTED_AS_CONTEXT" if h3 else "NOT_ESTABLISHED", "mixed_evidence": sum([h1, h2, h3]) > 1, "feature_hypothesis_status": status, "feature_implementation_authorized": False, "what_is_not_proven": ["Production benefit", "new feature causal mechanism", "generalization to any untouched holdout", "threshold or gate change"]}
    after = {"ablation_index": sha(ABLATION / "artifact_hashes.json"), "february_pre_index": sha(FEB_PRE / "artifact_hashes.json"), "february_post_index": sha(FEB_POST / "artifact_hashes.json")}
    if before != after:
        raise Stop("CONSUMED_AUTHORITY_MUTATION")
    OUT.mkdir(parents=True)
    dump("scope.json", {"status": "CONSUMED_DATA_DIAGNOSTIC_ONLY", "allowed": ["consumed March development dataset v3/v4", "consumed February formal PRE/POST and Result sources"], "forbidden": ["untouched historical holdout", "new Result acquisition", "Prediction", "Production modification", "feature implementation"], "random_seed": SEED, "bootstrap_replicates": BOOTSTRAPS})
    dump("march_fold_bootstrap.json", bootstrap)
    dump("march_fold_size_association.json", association)
    dump("february_primary_cell.json", primary)
    dump("february_mechanical_null_control.json", mechanical)
    dump("february_random_null_control.json", random_control)
    dump("february_pair_outcomes.json", pairs)
    dump("february_depth_buyvolume_table.json", context)
    dump("hypothesis_branch_assessment.json", assessment)
    dump("evidence_boundary.json", {"February formal lift remains": "+10.53pt", "replacement_active_subset_label": "POST_HOC_REPLACEMENT_ACTIVE_SUBSET_DIAGNOSTIC_ONLY", "next_untouched_holdout": "SEALED", "cf_evidence_track": "SEPARATE_AND_CONTINUING", "v4_model_v3_formal_prospective": "CONTINUING_UNLESS_FORMALLY_SUSPENDED_BY_HUMAN"})
    dump("safety.json", {"status": "PASS", "production_change_count": 0, "model_change_count": 0, "feature_implementation_count": 0, "new_holdout_access_count": 0, "new_result_acquisition_count": 0, "prediction_execution_count": 0, "february_formal_evidence_mutation_count": 0, "authority_hashes_before_after": after, **checks})
    report = ["# Next BUY Precision Diagnostic Stage-0", "", "- Status: `NEXT_FEATURE_DIAGNOSTIC_STAGE0 = COMPLETE`", "- February formal evidence preserved: `Current 35/133 = 26.32%; V4 49/133 = 36.84%; lift +10.53pt`", f"- March smallest-fold conclusion: `{association['smallest_fold_interpretation']}`", f"- February focal cell: Current `{primary['current']['top3_hits']}/{primary['current']['valid_count']}`, V4 `{primary['v4']['top3_hits']}/{primary['v4']['valid_count']}`", f"- Feature hypothesis status: `{status}`", "- NEXT_UNTOUCHED_HOLDOUT = `SEALED`", "- CF_EVIDENCE_TRACK = `SEPARATE_AND_CONTINUING`", ""]
    (OUT / "report.md").write_text("\n".join(report), encoding="utf-8")
    hashes = {path.name: sha(path) for path in OUT.iterdir() if path.is_file() and path.name != "artifact_hashes.json"}
    dump("artifact_hashes.json", {"indexed_artifacts": hashes, "self_hash_excluded": True})
    if any(sha(OUT / name) != digest for name, digest in hashes.items()):
        raise Stop("STAGE0_ARTIFACT_HASH_MISMATCH")
    print(f"NEXT_FEATURE_DIAGNOSTIC_STAGE0=COMPLETE;FEATURE_HYPOTHESIS_STATUS={status}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
