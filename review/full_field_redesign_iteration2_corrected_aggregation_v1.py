"""Iteration 2 Recovery Option A corrected aggregation.

This module has no dependency on the quarantined Iteration 2 runner.  It is
safe to import and unit-test with synthetic data.  Real execution is explicit
(`--execute`) and is intentionally fail-closed before any Result access.
"""
from __future__ import annotations

import csv
import hashlib
import json
import math
import random
import sys
from collections import defaultdict
from pathlib import Path
from typing import Any, Callable

from review import full_field_redesign_iteration2_correction_v1 as contract


ROOT = Path(__file__).resolve().parents[1]
RECOVERY_INPUTS = ROOT / "reports" / "full_field_redesign_iteration2_recovery_inputs_v1"
OUTPUT = ROOT / "reports" / "full_field_redesign_iteration2_correction_v1"
ITER1 = ROOT / "reports" / "full_field_redesign_iteration1_completion_v1"
ITER1_INDEX = ITER1 / "artifact_hashes.json"
ITER1_SELECTION = ITER1 / "primary_global_selected_horses.csv"
ITER1_BUDGET = ITER1 / "daily_current_buy_budget.csv"
ITER1_RESULT_MANIFEST = ITER1 / "result_source_identity_manifest.json"
PREREG = ROOT / "docs" / "KeibaAI_WS2_FullField_Iteration2_Preregistration_v1.md"
RATIFICATION = ROOT / "docs" / "KeibaAI_WS2_FullField_Iteration2_Human_Ratification_v1.md"

EXPECTED_PREREG_SHA = "6958c7cc8cfe6ece075a1b4de8c60d9b1be39c046069cfe7faff593cb108dbb5"
EXPECTED_RATIFICATION_SHA = "2ffe0d48822f54d723e94d92b12bc4927ae1bdc3e94bc70b0d50288035d3c7d1"
EXPECTED_RUN_SHA = "48401e556f28f5625d85dfa315153a6dbba84e3114e3a9752e17b25e50f71c22"
EVALUATION_MONTHS = ("202603", "202604", "202605", "202606", "202607", "202608", "202609")
NEW_MODELS = ("CORRECTED_PLACKETT_LUCE", "CORRECTED_HIST_GRADIENT_BOOSTING")
PRIMARY_COMPARATORS = (
    "CURRENT_GLOBAL", "PP_ONLY_DETERMINISTIC", "V5_TOP5_TRAINED",
    "V5_FULL_FIELD_TRAINED", *NEW_MODELS,
)


class Stop(RuntimeError):
    pass


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def stop_unless(condition: bool, code: str) -> None:
    if not condition:
        raise Stop(code)


def copy_recovery_inputs(source_a: Path, source_b: Path, destination: Path = RECOVERY_INPUTS) -> dict[str, Any]:
    """Create only byte-for-byte isolated recovery inputs; no metric is read."""
    if destination.exists():
        raise Stop("STOP_RECOVERY_INPUT_ROOT_ALREADY_EXISTS")
    a, b = source_a.read_bytes(), source_b.read_bytes()
    stop_unless(hashlib.sha256(a).hexdigest() == EXPECTED_RUN_SHA, "STOP_FROZEN_SOURCE_SHA_MISMATCH")
    stop_unless(hashlib.sha256(b).hexdigest() == EXPECTED_RUN_SHA and a == b, "STOP_FROZEN_SOURCE_SHA_MISMATCH")
    destination.mkdir(parents=True)
    (destination / "run_a_frozen.json").write_bytes(a)
    (destination / "run_b_frozen.json").write_bytes(b)
    manifest = {
        "role": "RECOVERY_INPUT_ONLY", "performance_aggregation": False,
        "run_a": {"file": "run_a_frozen.json", "bytes": len(a), "sha256": EXPECTED_RUN_SHA},
        "run_b": {"file": "run_b_frozen.json", "bytes": len(b), "sha256": EXPECTED_RUN_SHA},
        "byte_identical": True,
    }
    (destination / "recovery_input_manifest.json").write_text(json.dumps(manifest, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return manifest


def verify_recovery_sources(input_root: Path = RECOVERY_INPUTS) -> dict[str, Any]:
    """Hard gate that must finish before score loading or Result access."""
    stop_unless(sha256(PREREG) == EXPECTED_PREREG_SHA, "STOP_FROZEN_SOURCE_SHA_MISMATCH")
    stop_unless(sha256(RATIFICATION) == EXPECTED_RATIFICATION_SHA, "STOP_FROZEN_SOURCE_SHA_MISMATCH")
    a, b = input_root / "run_a_frozen.json", input_root / "run_b_frozen.json"
    stop_unless(a.is_file() and b.is_file(), "STOP_FROZEN_SOURCE_SHA_MISMATCH")
    a_bytes, b_bytes = a.read_bytes(), b.read_bytes()
    stop_unless(hashlib.sha256(a_bytes).hexdigest() == EXPECTED_RUN_SHA, "STOP_FROZEN_SOURCE_SHA_MISMATCH")
    stop_unless(hashlib.sha256(b_bytes).hexdigest() == EXPECTED_RUN_SHA and a_bytes == b_bytes, "STOP_FROZEN_SOURCE_SHA_MISMATCH")
    return {"preregistration_sha256": EXPECTED_PREREG_SHA, "ratification_sha256": EXPECTED_RATIFICATION_SHA, "run_sha256": EXPECTED_RUN_SHA, "run_a_run_b_byte_identical": True}


def verify_v5_top5_reference() -> Path:
    """Validate the immutable Iteration 1 selection artifact before use."""
    index = json.loads(ITER1_INDEX.read_text(encoding="utf-8"))
    entry = index.get("artifacts", {}).get("primary_global_selected_horses.csv")
    stop_unless(isinstance(entry, dict) and ITER1_SELECTION.is_file(), "STOP_V5_TOP5_REFERENCE_SHA_MISMATCH")
    stop_unless(sha256(ITER1_SELECTION) == entry.get("sha256"), "STOP_V5_TOP5_REFERENCE_SHA_MISMATCH")
    return ITER1_SELECTION


def identity(row: dict[str, Any]) -> tuple[str, str, int]:
    return str(row["date"]), str(row["race_id"]), int(row["horse_number"])


def load_score_rows(path: Path) -> list[dict[str, Any]]:
    """Read score fields only. Result labels are intentionally discarded."""
    raw = json.loads(path.read_text(encoding="utf-8")).get("rows")
    fields = {"date", "month", "race_id", "venue", "race_number", "horse_number", "current_buy", "shadow_ai_rank", "adjusted_score", "past_performance", "p_v5", "p_pl", "p_hgb"}
    stop_unless(isinstance(raw, list) and raw and all(fields.issubset(row) for row in raw), "STOP_FROZEN_SOURCE_SCHEMA_MISMATCH")
    return [{field: row[field] for field in fields} for row in raw]


def score(row: dict[str, Any], comparator: str) -> float:
    if comparator == "CURRENT_GLOBAL":
        return float(row["adjusted_score"])
    if comparator == "PP_ONLY_DETERMINISTIC":
        return float(row["past_performance"])
    if comparator == "V5_FULL_FIELD_TRAINED":
        return float(row["p_v5"])
    if comparator in NEW_MODELS:
        return contract.corrected_score(row, comparator)
    raise Stop("STOP_UNSUPPORTED_SCORE_COMPARATOR")


def ranking_key(row: dict[str, Any], comparator: str) -> tuple[Any, ...]:
    """Daily ranking; corrected model ties never use Current/shadow ranks."""
    if comparator in NEW_MODELS:
        return (-score(row, comparator), str(row["race_id"]), int(row["horse_number"]))
    if comparator == "CURRENT_GLOBAL":
        return (-score(row, comparator), -int(row["horse_number"]), str(row["race_id"]))
    if comparator == "PP_ONLY_DETERMINISTIC":
        return (-score(row, comparator), str(row["race_id"]), int(row["horse_number"]))
    if comparator == "V5_FULL_FIELD_TRAINED":
        return (-score(row, comparator), float(row["shadow_ai_rank"]), int(row["horse_number"]), str(row["race_id"]))
    raise Stop("STOP_UNSUPPORTED_RANKING_COMPARATOR")


def select_daily_global(rows: list[dict[str, Any]], comparator: str, budgets: dict[str, int]) -> dict[str, list[dict[str, Any]]]:
    by_date: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for row in rows:
        by_date[str(row["date"])].append(row)
    stop_unless(set(by_date) == set(budgets), "STOP_DAILY_BUDGET_MISMATCH")
    selected: dict[str, list[dict[str, Any]]] = {}
    for day, pool in by_date.items():
        n = budgets[day]
        stop_unless(0 <= n <= len(pool), "STOP_DAILY_BUDGET_MISMATCH")
        selected[day] = sorted(pool, key=lambda row: ranking_key(row, comparator))[:n]
    return selected


def read_iteration1_budget() -> dict[str, int]:
    with ITER1_BUDGET.open(encoding="utf-8-sig", newline="") as handle:
        rows = list(csv.DictReader(handle))
    stop_unless(len(rows) == 62 and len({row["date"] for row in rows}) == 62, "STOP_DAILY_BUDGET_MISMATCH")
    return {str(row["date"]): int(row["budget_n"]) for row in rows}


def read_iteration1_selected() -> dict[str, set[tuple[str, str, int]]]:
    selected: dict[str, set[tuple[str, str, int]]] = defaultdict(set)
    with ITER1_SELECTION.open(encoding="utf-8-sig", newline="") as handle:
        for row in csv.DictReader(handle):
            selected[str(row["comparator"])].add((str(row["date"]), str(row["race_id"]), int(row["horse_number"])))
    return selected


def verify_baseline_conformance(rows: list[dict[str, Any]]) -> dict[str, dict[str, list[dict[str, Any]]]]:
    """Pre-result proof that frozen baseline selections reproduce exactly."""
    budget_all = read_iteration1_budget()
    dates = {str(row["date"]) for row in rows}
    budgets = {day: budget_all[day] for day in dates if day in budget_all}
    stop_unless(len(budgets) == len(dates), "STOP_DAILY_BUDGET_MISMATCH")
    expected = read_iteration1_selected()
    aliases = {"CURRENT_GLOBAL": "CURRENT", "PP_ONLY_DETERMINISTIC": "PP_ONLY_DETERMINISTIC", "V5_FULL_FIELD_TRAINED": "V5_FULL_FIELD_TRAINED"}
    selections: dict[str, dict[str, list[dict[str, Any]]]] = {}
    for comparator, frozen_name in aliases.items():
        chosen = select_daily_global(rows, comparator, budgets)
        actual_ids = {identity(row) for day in chosen.values() for row in day}
        expected_ids = {key for key in expected[frozen_name] if key[0] in dates}
        stop_unless(actual_ids == expected_ids, "STOP_BASELINE_SELECTION_CONFORMANCE_FAILURE")
        selections[comparator] = chosen
    return selections


def assert_pl_probability_sanity(rows: list[dict[str, Any]], tolerance: float = 1e-8) -> None:
    try:
        contract.assert_corrected_pl_probability_mass(rows, tolerance)
    except contract.CorrectionPreparationStop as error:
        raise Stop("STOP_PL_PROBABILITY_SANITY_FAILURE") from error


def common_rank1_set(selections: dict[str, dict[str, list[dict[str, Any]]]], result_by_id: dict[tuple[str, str, int], dict[str, Any]]) -> dict[str, dict[str, Any]]:
    """One shared valid-race universe for V5 Full, corrected PL, and HGB."""
    per_model: dict[str, dict[tuple[str, str], dict[str, Any]]] = {}
    for model in ("V5_FULL_FIELD_TRAINED", *NEW_MODELS):
        by_race: dict[tuple[str, str], list[dict[str, Any]]] = defaultdict(list)
        for day_rows in selections[model].values():
            for row in day_rows:
                by_race[(str(row["date"]), str(row["race_id"]))].append(row)
        per_model[model] = {race: sorted(rows, key=lambda row: ranking_key(row, model))[0] for race, rows in by_race.items()}
    common = set.intersection(*(set(value) for value in per_model.values()))
    valid = {race for race in common if all(result_by_id.get(identity(per_model[model][race]), {}).get("valid_result") is True for model in per_model)}
    return {model: {"common_races": sorted(valid), "rank1_rows": [per_model[model][race] for race in sorted(valid)]} for model in per_model}


def rank1_guard(reference_rate: float, new_rate: float) -> bool:
    return new_rate >= reference_rate - 0.01


def calibration_guard(v5_pooled: float, new_pooled: float, worse_months: int, month_count: int) -> bool:
    stop_unless(month_count == 7, "STOP_EVALUATION_MONTH_COUNT_UNEXPECTED")
    return new_pooled <= v5_pooled and worse_months <= 2


def monthly_current_condition(current_beaten_months: int, month_count: int) -> bool:
    stop_unless(month_count == 7, "STOP_EVALUATION_MONTH_COUNT_UNEXPECTED")
    return current_beaten_months >= 5


def paired_date_bootstrap(left: dict[str, dict[str, float]], right: dict[str, dict[str, float]], *, seed: int = 20261014, rounds: int = 10000) -> dict[str, Any]:
    dates = sorted(set(left) & set(right))
    stop_unless(dates, "STOP_BOOTSTRAP_NO_COMMON_DATES")
    rng = random.Random(seed)
    samples: list[float] = []
    for _ in range(rounds):
        draw = [rng.choice(dates) for _ in dates]
        l_hit, l_n = sum(left[d]["hits"] for d in draw), sum(left[d]["valid_n"] for d in draw)
        r_hit, r_n = sum(right[d]["hits"] for d in draw), sum(right[d]["valid_n"] for d in draw)
        samples.append(r_hit / r_n - l_hit / l_n)
    samples.sort()
    observed = sum(right[d]["hits"] for d in dates) / sum(right[d]["valid_n"] for d in dates) - sum(left[d]["hits"] for d in dates) / sum(left[d]["valid_n"] for d in dates)
    return {"unit": "DATE", "seed": seed, "rounds": rounds, "observed_difference": observed, "ci_95_lower": samples[249], "ci_95_upper": samples[9749]}


def candidate_gate(*, lift_vs_current: float, current_beaten_months: int, bootstrap_vs_current_lower: float, rank_guard_pass: bool, calibration_guard_pass: bool, bootstrap_vs_pp_lower: float, comparator: str) -> dict[str, Any]:
    stop_unless(comparator != "V5_TOP5_TRAINED", "STOP_V5_TOP5_GATE_FORBIDDEN")
    conditions = {
        "lift_vs_current_6pt": lift_vs_current >= 0.06,
        "current_beaten_months_5_of_7": monthly_current_condition(current_beaten_months, 7),
        "bootstrap_current_lower_gt_0": bootstrap_vs_current_lower > 0,
        "rank1_guard": rank_guard_pass,
        "calibration_guard": calibration_guard_pass,
        "bootstrap_pp_lower_gt_0": bootstrap_vs_pp_lower > 0,
    }
    return {"conditions": conditions, "status": "PASS" if all(conditions.values()) else "FAIL"}


def select_model(pl_gate: dict[str, Any], hgb_gate: dict[str, Any], hgb_minus_pl_ci_lower: float, hgb_calibration_pass: bool) -> str:
    pl, hgb = pl_gate["status"] == "PASS", hgb_gate["status"] == "PASS"
    if not pl and not hgb:
        return "NONE"
    if pl and not hgb:
        return "PLACKETT_LUCE"
    if hgb and not pl:
        return "HIST_GRADIENT_BOOSTING"
    return "HIST_GRADIENT_BOOSTING" if hgb_minus_pl_ci_lower > 0 and hgb_calibration_pass else "PLACKETT_LUCE"


def assert_fresh_output_root(output_root: Path = OUTPUT) -> None:
    if output_root.exists():
        raise Stop("STOP_OUTPUT_ROOT_ALREADY_EXISTS")


def verify_result_source_conformance() -> dict[str, Any]:
    """Result identity is mandatory at future execution; absence is fail-closed."""
    if not ITER1_RESULT_MANIFEST.is_file():
        raise Stop("STOP_RESULT_SOURCE_CONFORMANCE_FAILURE")
    manifest = json.loads(ITER1_RESULT_MANIFEST.read_text(encoding="utf-8"))
    stop_unless(manifest.get("canonical_semantics") == "ITERATION1_CANONICAL_RESULT_JOIN", "STOP_RESULT_SOURCE_CONFORMANCE_FAILURE")
    return manifest


def attach_canonical_results(rows: list[dict[str, Any]], result_by_id: dict[tuple[str, str, int], dict[str, Any]]) -> list[dict[str, Any]]:
    """Join only the separately verified canonical Result provider at execution."""
    joined: list[dict[str, Any]] = []
    for row in rows:
        result = result_by_id.get(identity(row))
        stop_unless(isinstance(result, dict) and {"valid_result", "actual_top3"}.issubset(result), "STOP_RESULT_SOURCE_CONFORMANCE_FAILURE")
        joined.append({**row, "valid_result": bool(result["valid_result"]), "actual_top3": result["actual_top3"]})
    return joined


def metric(rows: list[dict[str, Any]]) -> dict[str, Any]:
    valid = [row for row in rows if row["valid_result"]]
    hits = sum(int(bool(row["actual_top3"])) for row in valid)
    return {
        "selected_n": len(rows), "invalid_n": len(rows) - len(valid), "valid_n": len(valid),
        "top3_hits": hits, "top3_rate": hits / len(valid) if valid else None,
        "selected_races": len({(row["date"], row["race_id"]) for row in rows}),
    }


def rows_for_ids(rows: list[dict[str, Any]], ids: set[tuple[str, str, int]]) -> list[dict[str, Any]]:
    found = {identity(row): row for row in rows}
    stop_unless(ids.issubset(found), "STOP_BASELINE_SELECTION_REFERENCE_UNRESOLVED")
    return [found[key] for key in sorted(ids)]


def v5_top5_reference_selection(rows: list[dict[str, Any]]) -> dict[str, list[dict[str, Any]]]:
    frozen = read_iteration1_selected().get("V5_TOP5_TRAINED")
    stop_unless(bool(frozen), "STOP_BASELINE_SELECTION_REFERENCE_UNRESOLVED")
    dates = {str(row["date"]) for row in rows}
    selected = rows_for_ids(rows, {item for item in frozen if item[0] in dates})
    by_date: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for row in selected:
        by_date[str(row["date"])].append(row)
    return dict(by_date)


def by_date_metrics(selections: dict[str, list[dict[str, Any]]]) -> dict[str, dict[str, Any]]:
    return {day: metric(chosen) for day, chosen in selections.items()}


def brier(rows: list[dict[str, Any]], comparator: str) -> float:
    valid = [row for row in rows if row["valid_result"]]
    stop_unless(bool(valid), "STOP_CALIBRATION_NO_VALID_ROWS")
    errors = [(score(row, comparator) - int(bool(row["actual_top3"]))) ** 2 for row in valid]
    return sum(errors) / len(errors)


def execution_result_payload(rows: list[dict[str, Any]], baseline: dict[str, dict[str, list[dict[str, Any]]]]) -> dict[str, Any]:
    """Build all corrected metrics exclusively after canonical Result joining."""
    months = tuple(sorted({str(row["month"]) for row in rows}))
    stop_unless(months == EVALUATION_MONTHS, "STOP_EVALUATION_MONTH_COUNT_UNEXPECTED")
    budgets = {day: len(chosen) for day, chosen in baseline["CURRENT_GLOBAL"].items()}
    selections: dict[str, dict[str, list[dict[str, Any]]]] = {**baseline}
    selections["V5_TOP5_TRAINED"] = v5_top5_reference_selection(rows)
    for comparator in NEW_MODELS:
        selections[comparator] = select_daily_global(rows, comparator, budgets)
    total = {name: metric([row for day in selections[name].values() for row in day]) for name in PRIMARY_COMPARATORS}
    daily = {name: by_date_metrics(selections[name]) for name in PRIMARY_COMPARATORS}
    monthly: dict[str, dict[str, dict[str, Any]]] = {}
    for name in PRIMARY_COMPARATORS:
        monthly[name] = {}
        for month in months:
            monthly[name][month] = metric([row for day, chosen in selections[name].items() if day.startswith(month) for row in chosen])

    result_by_id = {identity(row): row for row in rows}
    rank_input = {name: selections[name] for name in ("V5_FULL_FIELD_TRAINED", *NEW_MODELS)}
    rank_set = common_rank1_set(rank_input, result_by_id)
    rank_metrics: dict[str, dict[str, Any]] = {}
    for name, value in rank_set.items():
        rank_metrics[name] = {"common_valid_races": len(value["common_races"]), **metric(value["rank1_rows"])}

    calibration: dict[str, dict[str, float]] = {}
    for name in ("V5_FULL_FIELD_TRAINED", *NEW_MODELS):
        calibration[name] = {"POOLED": brier(rows, name)}
        for month in months:
            calibration[name][month] = brier([row for row in rows if row["month"] == month], name)

    boots: dict[str, dict[str, Any]] = {}
    gates: dict[str, dict[str, Any]] = {}
    reference_rate = rank_metrics["V5_FULL_FIELD_TRAINED"]["top3_rate"]
    for name in NEW_MODELS:
        versus_current = paired_date_bootstrap(daily["CURRENT_GLOBAL"], daily[name])
        versus_pp = paired_date_bootstrap(daily["PP_ONLY_DETERMINISTIC"], daily[name])
        boots[f"{name}_MINUS_CURRENT_GLOBAL"] = versus_current
        boots[f"{name}_MINUS_PP_ONLY_DETERMINISTIC"] = versus_pp
        worse = sum(calibration[name][month] > calibration["V5_FULL_FIELD_TRAINED"][month] for month in months)
        cal_pass = calibration_guard(calibration["V5_FULL_FIELD_TRAINED"]["POOLED"], calibration[name]["POOLED"], worse, len(months))
        beaten = sum(monthly[name][month]["top3_rate"] > monthly["CURRENT_GLOBAL"][month]["top3_rate"] for month in months)
        gates[name] = candidate_gate(
            lift_vs_current=total[name]["top3_rate"] - total["CURRENT_GLOBAL"]["top3_rate"],
            current_beaten_months=beaten,
            bootstrap_vs_current_lower=versus_current["ci_95_lower"],
            rank_guard_pass=rank1_guard(reference_rate, rank_metrics[name]["top3_rate"]),
            calibration_guard_pass=cal_pass,
            bootstrap_vs_pp_lower=versus_pp["ci_95_lower"],
            comparator=name,
        )
        gates[name]["calibration_worse_months"] = worse
        gates[name]["rank1_guard_reference"] = "V5_FULL_FIELD_TRAINED"
    hgb_minus_pl = paired_date_bootstrap(daily["CORRECTED_PLACKETT_LUCE"], daily["CORRECTED_HIST_GRADIENT_BOOSTING"])
    boots["CORRECTED_HIST_GRADIENT_BOOSTING_MINUS_CORRECTED_PLACKETT_LUCE"] = hgb_minus_pl
    choice = select_model(
        gates["CORRECTED_PLACKETT_LUCE"], gates["CORRECTED_HIST_GRADIENT_BOOSTING"],
        hgb_minus_pl["ci_95_lower"], gates["CORRECTED_HIST_GRADIENT_BOOSTING"]["conditions"]["calibration_guard"],
    )
    return {
        "selections": selections, "primary_total": total, "primary_daily": daily, "primary_monthly": monthly,
        "rank1": rank_metrics, "calibration": calibration, "bootstrap": boots, "candidate_gate": gates,
        "model_selection": {"iteration2_candidate": choice, "v5_top5_role": "REFERENCE_ONLY"},
    }


def write_json(path: Path, value: Any) -> None:
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2, sort_keys=True, allow_nan=False) + "\n", encoding="utf-8")


def write_csv(path: Path, rows: list[dict[str, Any]]) -> None:
    stop_unless(bool(rows), "STOP_EMPTY_OUTPUT")
    with path.open("w", encoding="utf-8-sig", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(rows[0]), extrasaction="ignore")
        writer.writeheader(); writer.writerows(rows)


def write_execution_outputs(output_root: Path, source_integrity: dict[str, Any], baseline: dict[str, Any], payload: dict[str, Any]) -> None:
    output_root.mkdir(parents=True)
    write_json(output_root / "source_integrity.json", source_integrity)
    write_json(output_root / "baseline_conformance.json", {"status": "PASS", "comparators": list(baseline)})
    write_json(output_root / "rank1_common_set.json", payload["rank1"])
    write_json(output_root / "paired_bootstrap.json", payload["bootstrap"])
    write_json(output_root / "candidate_gate.json", payload["candidate_gate"])
    write_json(output_root / "model_selection_decision.json", payload["model_selection"])
    write_json(output_root / "recovery_audit.json", {
        "RECOVERY_ROLE": "DEVELOPMENT_ONLY_NON_EVIDENTIAL", "ORIGINAL_OUTPUTS": "QUARANTINED",
        "TRAINING_RERUN": False, "PREDICTION_RERUN": False, "CORRECTION": "MAPPING_AND_AGGREGATION_ONLY",
        "MODEL_MAPPING": {"PL": "original p_hgb", "HGB": "original p_pl"},
        "formal_evidence": "NO", "production_evidence": "NO", "prospective_evidence": "NO",
    })
    primary_rows = [{"comparator": name, **metric} for name, metric in payload["primary_total"].items()]
    by_date_rows = [{"comparator": name, "date": day, **metric} for name, data in payload["primary_daily"].items() for day, metric in data.items()]
    by_month_rows = [{"comparator": name, "month": month, **metric} for name, data in payload["primary_monthly"].items() for month, metric in data.items()]
    rank_rows = [{"comparator": name, **metric} for name, metric in payload["rank1"].items()]
    calibration_rows = [{"comparator": name, "scope": scope, "brier": value} for name, data in payload["calibration"].items() for scope, value in data.items()]
    write_csv(output_root / "primary_metrics.csv", primary_rows); write_csv(output_root / "primary_by_date.csv", by_date_rows)
    write_csv(output_root / "primary_by_month.csv", by_month_rows); write_csv(output_root / "rank1_metrics.csv", rank_rows)
    write_csv(output_root / "calibration_metrics.csv", calibration_rows)
    (output_root / "summary.md").write_text("# Iteration 2 corrected aggregation\n\n`DEVELOPMENT_ONLY_NON_EVIDENTIAL`\n", encoding="utf-8")
    hashes = {path.relative_to(output_root).as_posix(): {"sha256": sha256(path), "size": path.stat().st_size} for path in sorted(output_root.iterdir()) if path.is_file() and path.name != "artifact_hashes.json"}
    write_json(output_root / "artifact_hashes.json", {"self_hash_excluded": True, "artifacts": hashes})


def execute_after_explicit_authorization(result_loader: Callable[[list[dict[str, Any]]], dict[tuple[str, str, int], dict[str, Any]]]) -> None:
    """Reserved real path. It is never called in implementation-only work."""
    assert_fresh_output_root()
    source_integrity = verify_recovery_sources()
    verify_v5_top5_reference()
    rows = load_score_rows(RECOVERY_INPUTS / "run_a_frozen.json")
    assert_pl_probability_sanity(rows)
    baseline = verify_baseline_conformance(rows)
    # Only after all preceding pre-result gates is any Result loader callable.
    verify_result_source_conformance()
    joined = attach_canonical_results(rows, result_loader(rows))
    payload = execution_result_payload(joined, baseline)
    write_execution_outputs(OUTPUT, source_integrity, baseline, payload)


def main() -> None:
    raise SystemExit("Real corrected aggregation is not authorized in implementation-only mode.")


if __name__ == "__main__":
    main()
