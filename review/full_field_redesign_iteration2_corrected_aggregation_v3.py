"""Iteration 2 corrected aggregation v3.

The Result-source identity manifest belongs to the recovery-input governance
root (``reports/full_field_redesign_iteration2_recovery_inputs_v1``).  It is
created only by ``--prepare`` and is never refreshed by ``--execute``.
This module deliberately performs no work on import.
"""
from __future__ import annotations

import argparse
import csv
import hashlib
import json
import os
import shutil
import tempfile
from collections import defaultdict
from pathlib import Path
from typing import Any, Callable

from review import full_field_redesign_iteration2_correction_v1 as contract

ROOT = Path(__file__).resolve().parents[1]
INPUT = ROOT / "reports" / "full_field_redesign_iteration2_recovery_inputs_v1"
OUT = ROOT / "reports" / "full_field_redesign_iteration2_correction_v1"
TEMP_OUT = ROOT / "reports" / ".full_field_redesign_iteration2_correction_v1.tmp"
RESULT_ROOT = ROOT / "data" / "raw" / "target" / "daily_result_list"
PREREG = ROOT / "docs" / "KeibaAI_WS2_FullField_Iteration2_Preregistration_v1.md"
RATIFICATION = ROOT / "docs" / "KeibaAI_WS2_FullField_Iteration2_Human_Ratification_v1.md"
EXPECTED_PREREG = "6958c7cc8cfe6ece075a1b4de8c60d9b1be39c046069cfe7faff593cb108dbb5"
EXPECTED_RATIFICATION = "2ffe0d48822f54d723e94d92b12bc4927ae1bdc3e94bc70b0d50288035d3c7d1"
EXPECTED_RUN = "48401e556f28f5625d85dfa315153a6dbba84e3114e3a9752e17b25e50f71c22"
MANIFEST_NAME = "result_source_identity_manifest.json"
CANONICAL_RESULT_LOADER = "ITER0_ITER1_RESULT_JOIN_COMPATIBLE"
NEW = ("CORRECTED_PLACKETT_LUCE", "CORRECTED_HIST_GRADIENT_BOOSTING")
ALL = ("CURRENT_GLOBAL", "PP_ONLY_DETERMINISTIC", "V5_TOP5_TRAINED", "V5_FULL_FIELD_TRAINED", *NEW)
ITER1 = ROOT / "reports" / "full_field_redesign_iteration1_completion_v1"
PRE_ROOT = ROOT / "reports" / "full_field_redesign_iter0_v1_retry6" / "pre_only_regeneration" / "shards"
EXPECTED_MONTH_COUNT = 7


class Stop(RuntimeError):
    """Fail-closed governance stop."""


def ensure(condition: bool, code: str) -> None:
    if not condition:
        raise Stop(code)


def sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def ident(row: dict[str, Any]) -> tuple[str, str, int]:
    return str(row["date"]), str(row["race_id"]), int(row["horse_number"])


def _atomic_json(path: Path, value: Any) -> None:
    """Write one new governance artifact without ever exposing partial JSON."""
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, temporary = tempfile.mkstemp(prefix=f".{path.name}.", suffix=".tmp", dir=path.parent)
    try:
        with os.fdopen(fd, "w", encoding="utf-8", newline="") as handle:
            json.dump(value, handle, ensure_ascii=False, indent=2, sort_keys=True)
            handle.write("\n")
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary, path)
    except Exception:
        Path(temporary).unlink(missing_ok=True)
        raise


def score(row: dict[str, Any], model: str) -> float:
    # The Human-ratified corrected mapping is intentionally unchanged.
    field = {
        "CURRENT_GLOBAL": "adjusted_score",
        "PP_ONLY_DETERMINISTIC": "past_performance",
        "CORRECTED_PLACKETT_LUCE": "p_hgb",
        "CORRECTED_HIST_GRADIENT_BOOSTING": "p_pl",
        "V5_FULL_FIELD_TRAINED": "p_v5",
    }.get(model)
    if model in NEW:
        return float(contract.corrected_score(row, model))
    ensure(field is not None, "STOP_UNSUPPORTED_COMPARATOR")
    return float(row[field])


def daily_key(row: dict[str, Any], model: str) -> tuple[Any, ...]:
    """Frozen daily global tie-break: score, lexical race id, horse number."""
    if model in NEW or model == "PP_ONLY_DETERMINISTIC":
        return (-score(row, model), str(row["race_id"]), int(row["horse_number"]))
    if model == "CURRENT_GLOBAL":
        return (-score(row, model), -int(row["horse_number"]), str(row["race_id"]))
    if model == "V5_FULL_FIELD_TRAINED":
        return (-score(row, model), int(row["shadow_ai_rank"]), int(row["horse_number"]), str(row["race_id"]))
    raise Stop("STOP_UNSUPPORTED_COMPARATOR")


def rank1_key(row: dict[str, Any], model: str) -> tuple[Any, ...]:
    """Iteration-1 rank-one semantics, including V5's shadow-rank tie-break."""
    if model == "V5_FULL_FIELD_TRAINED":
        return (-score(row, model), int(row["shadow_ai_rank"]), int(row["horse_number"]))
    return (-score(row, model), int(row["horse_number"]))


def evaluation_months(rows: list[dict[str, Any]]) -> tuple[str, ...]:
    months = tuple(sorted({str(row["date"])[:6] for row in rows}))
    ensure(len(months) == EXPECTED_MONTH_COUNT, "STOP_EVALUATION_MONTH_COUNT_UNEXPECTED")
    return months


def frozen_gate(
    input_root: Path = INPUT,
    *,
    prereg: Path = PREREG,
    ratification: Path = RATIFICATION,
    expected_prereg: str = EXPECTED_PREREG,
    expected_ratification: str = EXPECTED_RATIFICATION,
    expected_run: str = EXPECTED_RUN,
    budget_artifact: Path | None = None,
    expected_budget_sha: str | None = None,
) -> dict[str, str]:
    """Verify frozen non-Result inputs before *any* Result loader can run."""
    ensure(sha(prereg) == expected_prereg, "STOP_PREREGISTRATION_SHA_MISMATCH")
    ensure(sha(ratification) == expected_ratification, "STOP_RATIFICATION_SHA_MISMATCH")
    run_a = input_root / "run_a_frozen.json"
    run_b = input_root / "run_b_frozen.json"
    ensure(sha(run_a) == expected_run, "STOP_RUN_A_SHA_MISMATCH")
    ensure(sha(run_b) == expected_run, "STOP_RUN_B_SHA_MISMATCH")
    ensure(run_a.read_bytes() == run_b.read_bytes(), "STOP_FROZEN_RUNS_NOT_BYTE_IDENTICAL")
    if budget_artifact is not None:
        ensure(expected_budget_sha is not None and sha(budget_artifact) == expected_budget_sha,
               "STOP_BUDGET_ARTIFACT_SHA_MISMATCH")
    return {"prereg": sha(prereg), "ratification": sha(ratification), "run": sha(run_a)}


def load_scores(path: Path) -> list[dict[str, Any]]:
    raw = json.loads(path.read_text(encoding="utf-8")).get("rows")
    fields = {"date", "month", "race_id", "venue", "race_number", "horse_number", "current_buy",
              "shadow_ai_rank", "adjusted_score", "past_performance", "p_v5", "p_pl", "p_hgb"}
    ensure(isinstance(raw, list) and raw and all(fields <= set(value) for value in raw),
           "STOP_FROZEN_SOURCE_SCHEMA_MISMATCH")
    return [{key: value[key] for key in fields} for value in raw]


def load_budget(iter1_root: Path = ITER1) -> dict[str, int]:
    index = json.loads((iter1_root / "artifact_hashes.json").read_text(encoding="utf-8"))["artifacts"]
    path = iter1_root / "daily_current_buy_budget.csv"
    ensure(path.is_file() and sha(path) == index.get(path.name, {}).get("sha256"), "STOP_DAILY_BUDGET_MISMATCH")
    with path.open(encoding="utf-8-sig", newline="") as handle:
        rows = list(csv.DictReader(handle))
    ensure(len(rows) == 62 and len({row["date"] for row in rows}) == 62, "STOP_DAILY_BUDGET_MISMATCH")
    return {str(row["date"]): int(row["budget_n"]) for row in rows}


def recompute_pre_buy_budget(pre_root: Path = PRE_ROOT) -> dict[str, int]:
    files = sorted(pre_root.glob("run_c_*/runtime_pre_only_output.json"))
    ensure(len(files) == 31, "STOP_DAILY_BUDGET_MISMATCH")
    counts: dict[str, int] = defaultdict(int); dates: set[str] = set()
    for path in files:
        for row in json.loads(path.read_text(encoding="utf-8"))["generated_rows"]:
            date = str(row["date"]); dates.add(date)
            counts[date] += row["values"].get("post_rc1_decision") == "BUY"
    ensure(len(dates) == 62, "STOP_DAILY_BUDGET_MISMATCH")
    return dict(counts)


def direct_budget_conformance() -> dict[str, int]:
    frozen, actual = load_budget(), recompute_pre_buy_budget()
    ensure(frozen == actual, "STOP_DAILY_BUDGET_MISMATCH")
    return frozen


def select_daily(rows: list[dict[str, Any]], model: str, budgets: dict[str, int]) -> dict[str, list[dict[str, Any]]]:
    grouped: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for row in rows:
        grouped[str(row["date"])].append(row)
    ensure(set(grouped) <= set(budgets), "STOP_DAILY_BUDGET_MISMATCH")
    selected: dict[str, list[dict[str, Any]]] = {}
    for date, pool in grouped.items():
        budget = budgets[date]
        ensure(0 <= budget <= len(pool), "STOP_DAILY_BUDGET_MISMATCH")
        selected[date] = sorted(pool, key=lambda value: daily_key(value, model))[:budget]
    return selected


def read_iter1_selection(with_score: bool = False, iter1_root: Path = ITER1) -> dict[str, Any]:
    index = json.loads((iter1_root / "artifact_hashes.json").read_text(encoding="utf-8"))["artifacts"]
    path = iter1_root / "primary_global_selected_horses.csv"
    ensure(path.is_file() and sha(path) == index.get(path.name, {}).get("sha256"), "STOP_V5_TOP5_REFERENCE_SHA_MISMATCH")
    result: dict[str, Any] = defaultdict(dict if with_score else set)
    with path.open(encoding="utf-8-sig", newline="") as handle:
        for entry in csv.DictReader(handle):
            key = (str(entry["date"]), str(entry["race_id"]), int(entry["horse_number"]))
            if with_score:
                result[str(entry["comparator"])][key] = {"score": float(entry["score"]), "global_rank": int(entry["global_rank"])}
            else:
                result[str(entry["comparator"])].add(key)
    return result


def baseline_conformance(rows: list[dict[str, Any]], budgets: dict[str, int]) -> dict[str, dict[str, list[dict[str, Any]]]]:
    frozen = read_iter1_selection(); dates = {str(row["date"]) for row in rows}; output = {}
    for model, frozen_name in (("CURRENT_GLOBAL", "CURRENT"), ("PP_ONLY_DETERMINISTIC", "PP_ONLY_DETERMINISTIC"),
                               ("V5_FULL_FIELD_TRAINED", "V5_FULL_FIELD_TRAINED")):
        selected = select_daily(rows, model, budgets)
        actual = {ident(row) for values in selected.values() for row in values}
        expected = {key for key in frozen[frozen_name] if key[0] in dates}
        ensure(actual == expected, "STOP_BASELINE_SELECTION_CONFORMANCE_FAILURE")
        output[model] = selected
    return output


def assert_pl_mass(rows: list[dict[str, Any]]) -> None:
    try:
        contract.assert_corrected_pl_probability_mass(rows, 1e-8)
    except contract.CorrectionPreparationStop as exc:
        raise Stop("STOP_PL_PROBABILITY_SANITY_FAILURE") from exc


def _source_paths(dates: set[str], result_root: Path) -> dict[str, list[Path]]:
    return {
        date: [
            result_root / f"馬番順着順_{date}.csv",
            result_root / f"着順馬番_{date}.csv",
        ]
        for date in sorted(dates)
    }


def prepare_result_identity_manifest(
    rows: list[dict[str, Any]],
    *,
    destination: Path = INPUT / MANIFEST_NAME,
    result_root: Path = RESULT_ROOT,
) -> dict[str, Any]:
    """Freeze only identity metadata; this function never parses result rows."""
    ensure(not destination.exists(), "STOP_RESULT_SOURCE_MANIFEST_ALREADY_EXISTS")
    sources: list[dict[str, Any]] = []
    for date, paths in _source_paths({str(row["date"]) for row in rows}, result_root).items():
        for path in paths:
            ensure(path.is_file(), "STOP_RESULT_SOURCE_CONFORMANCE_FAILURE")
            sources.append({"date": date, "path": str(path), "filename": path.name,
                            "bytes": path.stat().st_size, "sha256": sha(path)})
    manifest = {
        "schema": "iteration2_result_source_identity_v3",
        "canonical_result_loader": CANONICAL_RESULT_LOADER,
        "PERFORMANCE_ROWS_PARSED": False,
        "sources": sources,
    }
    _atomic_json(destination, manifest)
    manifest["manifest_sha256"] = sha(destination)
    return manifest


def verify_result_identity(
    manifest_path: Path,
    approved_sha: str | None,
) -> dict[str, Any]:
    """Execute-time identity verification.  It never creates or rewrites a file."""
    ensure(approved_sha is not None and len(approved_sha) == 64,
           "STOP_APPROVED_RESULT_MANIFEST_SHA_REQUIRED")
    ensure(manifest_path.is_file() and sha(manifest_path) == approved_sha,
           "STOP_RESULT_SOURCE_CONFORMANCE_FAILURE")
    value = json.loads(manifest_path.read_text(encoding="utf-8"))
    ensure(value.get("canonical_result_loader") == CANONICAL_RESULT_LOADER,
           "STOP_RESULT_SOURCE_CONFORMANCE_FAILURE")
    ensure(value.get("PERFORMANCE_ROWS_PARSED") is False,
           "STOP_RESULT_SOURCE_CONFORMANCE_FAILURE")
    for source in value.get("sources", []):
        path = Path(str(source["path"]))
        ensure(path.is_file() and path.name == source["filename"] and
               path.stat().st_size == source["bytes"] and sha(path) == source["sha256"],
               "STOP_RESULT_SOURCE_CONFORMANCE_FAILURE")
    return value


def canonical_result_loader(
    rows: list[dict[str, Any]],
    *,
    result_rows_fn: Callable[[str], dict[tuple[str, int], list[str]]] | None = None,
    outcome_fn: Callable[[list[str], int], tuple[bool, int | None, bool | None]] | None = None,
    parse_race_id_fn: Callable[[str], tuple[str, str, int]] | None = None,
    japanese_venue: dict[str, str] | None = None,
) -> dict[tuple[str, str, int], dict[str, Any]]:
    """The Iter0/Iter1 Result join, explicitly mapping romanized venue keys."""
    if result_rows_fn is None or outcome_fn is None or parse_race_id_fn is None or japanese_venue is None:
        from review.candidate_generation_training_dataset_readiness_v1 import (
            JAPANESE_VENUE, outcome, parse_race_id, result_rows,
        )
        result_rows_fn = result_rows if result_rows_fn is None else result_rows_fn
        outcome_fn = outcome if outcome_fn is None else outcome_fn
        parse_race_id_fn = parse_race_id if parse_race_id_fn is None else parse_race_id_fn
        japanese_venue = JAPANESE_VENUE if japanese_venue is None else japanese_venue
    cache: dict[str, dict[tuple[str, int], list[str]]] = {}
    output: dict[tuple[str, str, int], dict[str, Any]] = {}
    for row in rows:
        expected_date = str(row["date"])
        race_date, venue_key, race_number = parse_race_id_fn(str(row["race_id"]))
        ensure(race_date == expected_date, "STOP_RESULT_DATE_MISMATCH")
        ensure(venue_key in japanese_venue, "STOP_RESULT_VENUE_MISMATCH")
        official_venue = japanese_venue[venue_key]
        if expected_date not in cache:
            cache[expected_date] = result_rows_fn(expected_date)
        source = cache[expected_date].get((official_venue, int(race_number)))
        ensure(source is not None, "STOP_RESULT_RACE_MISMATCH")
        valid, finish, top3 = outcome_fn(source, int(row["horse_number"]))
        output[ident(row)] = {"valid_result": valid, "actual_finish": finish, "actual_top3": top3,
                              "official_venue": official_venue, "race_number": int(race_number)}
    return output


def full_race_rank1(rows: list[dict[str, Any]], labels: dict[tuple[str, str, int], dict[str, Any]]) -> dict[str, dict[tuple[str, str], dict[str, Any]]]:
    """Rank all full-field rows then retain one common valid race set."""
    by_race: dict[tuple[str, str], list[dict[str, Any]]] = {}
    for row in rows:
        by_race.setdefault((str(row["date"]), str(row["race_id"])), []).append(row)
    winners: dict[str, dict[tuple[str, str], dict[str, Any]]] = {name: {} for name in ("V5_FULL_FIELD_TRAINED", *NEW)}
    for key, race_rows in by_race.items():
        for name in winners:
            winners[name][key] = min(race_rows, key=lambda row: rank1_key(row, name))
    common = {key for key in by_race if all(labels[ident(winners[name][key])]["valid_result"] for name in winners)}
    ensure(bool(common), "STOP_COMMON_RANK1_SET_EMPTY")
    return {name: {key: row for key, row in entries.items() if key in common} for name, entries in winners.items()}


def v5_top5_reference(expected: list[tuple[str, str, int]], lookup: dict[tuple[str, str, int], dict[str, Any]]) -> list[dict[str, Any]]:
    result = []
    for key in expected:
        ensure(key in lookup, "STOP_V5_TOP5_REFERENCE_HORSE_MISSING")
        result.append(lookup[key])
    return result


def metric(rows: list[dict[str, Any]]) -> dict[str, Any]:
    valid = [row for row in rows if row["valid_result"]]
    hits = sum(bool(row["actual_top3"]) for row in valid)
    return {"selected_n": len(rows), "invalid_n": len(rows) - len(valid), "valid_n": len(valid),
            "top3_hits": hits, "top3_rate": hits / len(valid) if valid else None,
            "selected_races": len({(row["date"], row["race_id"]) for row in rows})}


def join(rows: list[dict[str, Any]], labels: dict[tuple[str, str, int], dict[str, Any]]) -> list[dict[str, Any]]:
    joined = []
    for row in rows:
        label = labels.get(ident(row))
        ensure(isinstance(label, dict) and {"valid_result", "actual_top3"} <= set(label),
               "STOP_RESULT_SOURCE_CONFORMANCE_FAILURE")
        joined.append({**row, **label})
    return joined


def brier(rows: list[dict[str, Any]], model: str) -> float:
    valid = [row for row in rows if row["valid_result"]]
    ensure(bool(valid), "STOP_CALIBRATION_NO_VALID_ROWS")
    return sum((score(row, model) - int(bool(row["actual_top3"]))) ** 2 for row in valid) / len(valid)


def bootstrap(left: dict[str, dict[str, Any]], right: dict[str, dict[str, Any]], *, seed: int = 20261014,
              rounds: int = 10000) -> dict[str, float]:
    import random
    dates = sorted(set(left) & set(right)); ensure(bool(dates), "STOP_BOOTSTRAP_NO_COMMON_DATES")
    randomizer = random.Random(seed); values = []
    for _ in range(rounds):
        sampled = [randomizer.choice(dates) for _ in dates]
        values.append(sum(right[date]["top3_hits"] for date in sampled) / sum(right[date]["valid_n"] for date in sampled)
                      - sum(left[date]["top3_hits"] for date in sampled) / sum(left[date]["valid_n"] for date in sampled))
    values.sort()
    return {"unit": "DATE", "seed": seed, "rounds": rounds, "ci_95_lower": values[249], "ci_95_upper": values[9749]}


def rank_guard(reference: float | None, candidate: float | None) -> bool:
    return reference is not None and candidate is not None and candidate >= reference - .01


def calibration_guard(v5: float, candidate: float, worse_months: int, month_count: int) -> bool:
    ensure(month_count == EXPECTED_MONTH_COUNT, "STOP_EVALUATION_MONTH_COUNT_UNEXPECTED")
    return candidate <= v5 and worse_months <= 2


def monthly_rule(wins: int, month_count: int) -> bool:
    ensure(month_count == EXPECTED_MONTH_COUNT, "STOP_EVALUATION_MONTH_COUNT_UNEXPECTED")
    return wins >= 5


def candidate_gate(*, lift: float, monthly_wins: int, bootstrap_current: float, rank: bool,
                   calibration: bool, bootstrap_pp: float, model: str, month_count: int) -> dict[str, Any]:
    ensure(model != "V5_TOP5_TRAINED", "STOP_V5_TOP5_GATE_FORBIDDEN")
    checks = {"lift_vs_current_6pt": lift >= .06, "monthly_5_of_7": monthly_rule(monthly_wins, month_count),
              "bootstrap_current_lower_gt_0": bootstrap_current > 0, "rank1_guard": rank,
              "calibration_guard": calibration, "bootstrap_pp_lower_gt_0": bootstrap_pp > 0}
    return {"conditions": checks, "status": "PASS" if all(checks.values()) else "FAIL"}


def _atomic_csv(path: Path, rows: list[dict[str, Any]]) -> None:
    ensure(bool(rows), "STOP_EMPTY_OUTPUT")
    fd, temporary = tempfile.mkstemp(prefix=f".{path.name}.", suffix=".tmp", dir=path.parent)
    try:
        with os.fdopen(fd, "w", encoding="utf-8-sig", newline="") as handle:
            writer = csv.DictWriter(handle, fieldnames=list(rows[0]), extrasaction="ignore")
            writer.writeheader(); writer.writerows(rows); handle.flush(); os.fsync(handle.fileno())
        os.replace(temporary, path)
    except Exception:
        Path(temporary).unlink(missing_ok=True); raise


def _write_snapshot(temp_root: Path, selections: list[dict[str, Any]]) -> None:
    temp_root.mkdir(parents=True, exist_ok=False)
    csv_path = temp_root / "pre_result_selected_horses.csv"
    fields = ["date", "race_id", "horse_number"]
    with csv_path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields)
        writer.writeheader()
        writer.writerows([{key: row[key] for key in fields} for row in selections])
    _atomic_json(temp_root / "pre_result_selection_manifest.json", {
        "RESULT_ACCESS_COUNT_AT_FREEZE": 0, "selection_csv_sha256": sha(csv_path),
    })


def execute_atomic(
    selections: list[dict[str, Any]],
    *,
    manifest_path: Path,
    approved_sha: str | None,
    final_root: Path = OUT,
    temporary_root: Path = TEMP_OUT,
    result_loader: Callable[[list[dict[str, Any]]], Any] = canonical_result_loader,
) -> Any:
    """Execution skeleton: final output appears only after every step succeeds."""
    ensure(not final_root.exists(), "STOP_FINAL_OUTPUT_ALREADY_EXISTS")
    ensure(not temporary_root.exists(), "STOP_TEMP_OUTPUT_ALREADY_EXISTS")
    verify_result_identity(manifest_path, approved_sha)
    try:
        _write_snapshot(temporary_root, selections)
        labels = result_loader(selections)
        serializable_labels = {
            "|".join((date, race_id, str(horse_number))): value
            for (date, race_id, horse_number), value in labels.items()
        }
        _atomic_json(temporary_root / "result_labels.json", serializable_labels)
        os.replace(temporary_root, final_root)
        return labels
    except Exception:
        shutil.rmtree(temporary_root, ignore_errors=True)
        raise


def prepare(input_root: Path = INPUT) -> dict[str, Any]:
    """The only path allowed to create the one-shot Result identity manifest."""
    source_integrity = frozen_gate(input_root)
    budgets = direct_budget_conformance()
    rows = load_scores(input_root / "run_a_frozen.json")
    ensure({str(row["date"]) for row in rows} <= set(budgets), "STOP_DAILY_BUDGET_MISMATCH")
    baseline = baseline_conformance(rows, budgets)
    assert_pl_mass(rows)
    result_manifest = prepare_result_identity_manifest(rows)
    return {"source_integrity": source_integrity, "budgets": budgets, "baseline": baseline,
            "rows": rows, "result_manifest": result_manifest}


def execute_after_authorization(approved_manifest_sha: str, input_root: Path = INPUT) -> Any:
    """Future authorized execution; deliberately does not call :func:`prepare`."""
    frozen_gate(input_root)
    budgets = direct_budget_conformance()
    rows = load_scores(input_root / "run_a_frozen.json")
    evaluation_months(rows)
    baseline = baseline_conformance(rows, budgets)
    assert_pl_mass(rows)
    verify_result_identity(input_root / MANIFEST_NAME, approved_manifest_sha)

    metadata = read_iter1_selection(True)["V5_TOP5_TRAINED"]
    lookup = {ident(row): row for row in rows}
    top5: dict[str, list[dict[str, Any]]] = {}
    for date in sorted({str(row["date"]) for row in rows}):
        expected = sorted((key for key in metadata if key[0] == date), key=lambda key: metadata[key]["global_rank"])
        top5[date] = v5_top5_reference(expected, lookup)
    selections = {**baseline, "V5_TOP5_TRAINED": top5}
    for model in NEW:
        selections[model] = select_daily(rows, model, budgets)
    # Result identity is verified before the temporary root is created; the
    # following transaction is the sole writer for all final artifacts.
    ensure(not OUT.exists(), "STOP_FINAL_OUTPUT_ALREADY_EXISTS")
    ensure(not TEMP_OUT.exists(), "STOP_TEMP_OUTPUT_ALREADY_EXISTS")
    verify_result_identity(input_root / MANIFEST_NAME, approved_manifest_sha)
    try:
        TEMP_OUT.mkdir(parents=True, exist_ok=False)
        pre_rows = []
        for model, days in selections.items():
            for date, chosen in days.items():
                for daily_rank, row in enumerate(chosen, 1):
                    pre_rows.append({"date": date, "race_id": row["race_id"], "horse_number": row["horse_number"],
                                     "comparator": model, "daily_rank": daily_rank})
        _atomic_csv(TEMP_OUT / "pre_result_selected_horses.csv", pre_rows)
        _atomic_json(TEMP_OUT / "pre_result_selection_manifest.json", {
            "RESULT_ACCESS_COUNT_AT_FREEZE": 0, "selection_csv_sha256": sha(TEMP_OUT / "pre_result_selected_horses.csv"),
            "row_count": len(pre_rows),
        })
        labels = canonical_result_loader(rows)
        joined = join(rows, labels)
        joined_lookup = {ident(row): row for row in joined}
        resolved = {model: {date: [joined_lookup[ident(row)] for row in chosen]
                            for date, chosen in days.items()} for model, days in selections.items()}
        rank = full_race_rank1(joined, labels)
        months = evaluation_months(joined)
        totals = {model: metric([row for values in days.values() for row in values]) for model, days in resolved.items()}
        daily = {model: {date: metric(values) for date, values in days.items()} for model, days in resolved.items()}
        monthly = {model: {month: metric([row for date, values in days.items() if date.startswith(month) for row in values])
                           for month in months} for model, days in resolved.items()}
        calibration = {model: {"POOLED": brier(joined, model), **{month: brier([row for row in joined if row["month"] == month], model)
                                                                  for month in months}}
                       for model in ("V5_FULL_FIELD_TRAINED", *NEW)}
        rank_rates = {model: metric(list(by_race.values()))["top3_rate"] for model, by_race in rank.items()}
        gates: dict[str, Any] = {}; bootstraps: dict[str, Any] = {}
        for model in NEW:
            vs_current = bootstrap(daily["CURRENT_GLOBAL"], daily[model])
            vs_pp = bootstrap(daily["PP_ONLY_DETERMINISTIC"], daily[model])
            bootstraps[f"{model}_MINUS_CURRENT_GLOBAL"] = vs_current
            bootstraps[f"{model}_MINUS_PP_ONLY_DETERMINISTIC"] = vs_pp
            worse = sum(calibration[model][month] > calibration["V5_FULL_FIELD_TRAINED"][month] for month in months)
            wins = sum(monthly[model][month]["top3_rate"] > monthly["CURRENT_GLOBAL"][month]["top3_rate"] for month in months)
            gates[model] = candidate_gate(lift=totals[model]["top3_rate"] - totals["CURRENT_GLOBAL"]["top3_rate"],
                monthly_wins=wins, bootstrap_current=vs_current["ci_95_lower"],
                rank=rank_guard(rank_rates["V5_FULL_FIELD_TRAINED"], rank_rates[model]),
                calibration=calibration_guard(calibration["V5_FULL_FIELD_TRAINED"]["POOLED"], calibration[model]["POOLED"], worse, len(months)),
                bootstrap_pp=vs_pp["ci_95_lower"], model=model, month_count=len(months))
        _atomic_json(TEMP_OUT / "source_integrity.json", frozen_gate(input_root))
        _atomic_json(TEMP_OUT / "rank1_common_set.json", {model: {"common_races": [list(key) for key in by_race],
                      "rows": list(by_race.values())} for model, by_race in rank.items()})
        _atomic_json(TEMP_OUT / "candidate_gate.json", gates)
        _atomic_json(TEMP_OUT / "paired_bootstrap.json", bootstraps)
        _atomic_csv(TEMP_OUT / "primary_metrics.csv", [{"comparator": model, **value} for model, value in totals.items()])
        _atomic_csv(TEMP_OUT / "primary_by_date.csv", [{"comparator": model, "date": date, **value}
                    for model, values in daily.items() for date, value in values.items()])
        _atomic_csv(TEMP_OUT / "primary_by_month.csv", [{"comparator": model, "month": month, **value}
                    for model, values in monthly.items() for month, value in values.items()])
        _atomic_json(TEMP_OUT / "recovery_audit.json", {"RECOVERY_ROLE": "DEVELOPMENT_ONLY_NON_EVIDENTIAL",
            "TRAINING_RERUN": False, "PREDICTION_RERUN": False, "MODEL_MAPPING": {"PL": "original p_hgb", "HGB": "original p_pl"}})
        hashes = {path.name: {"sha256": sha(path), "size": path.stat().st_size} for path in sorted(TEMP_OUT.iterdir()) if path.is_file()}
        _atomic_json(TEMP_OUT / "artifact_hashes.json", {"self_hash_excluded": True, "artifacts": hashes})
        os.replace(TEMP_OUT, OUT)
        return {"output": str(OUT), "candidate_gates": gates}
    except Exception:
        shutil.rmtree(TEMP_OUT, ignore_errors=True)
        raise


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--prepare", action="store_true")
    parser.add_argument("--execute", action="store_true")
    parser.add_argument("--approved-result-manifest-sha")
    args = parser.parse_args()
    ensure(args.prepare ^ args.execute, "STOP_EXACTLY_ONE_MODE_REQUIRED")
    if args.prepare:
        prepare()
    else:
        execute_after_authorization(args.approved_result_manifest_sha)


if __name__ == "__main__":
    main()
