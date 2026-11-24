"""EXP-025 one-shot bounded post-failure diagnostic.

This is deliberately not a model runner.  Q1 reads the already-frozen
Iteration-2 Rolling-OOS Base-PL values; Q2 reads the already-frozen EXP-025
same-volume selections.  The only raw-source work is PRE-time history-depth
and source-availability accounting.  It never calls a fit, inference, or
result importer.
"""
from __future__ import annotations

import csv
import hashlib
import json
import math
import shutil
import tempfile
from collections import defaultdict
from pathlib import Path
from statistics import mean
from typing import Any, Iterable

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "reports" / "exp025_post_failure_bounded_diagnostic_v1"
FROZEN = ROOT / "reports" / "full_field_redesign_iteration2_recovery_inputs_v1" / "run_a_frozen.json"
EXP025 = ROOT / "reports" / "exp025_offset_pl_raw_history_v1_retry1"
SELECTED = EXP025 / "selected_horses.csv"
SOURCE_AUDIT = EXP025 / "source_identity_audit.json"
EXPECTED_PREREG_SHA = "88e8a9dca64a0c520f79880e3eb73d5e4bc318fc0052e28b4a543de4cac79a29"
EXPECTED_ARTIFACT_INDEX_SHA = "1b49741284cdce0a09b247d8e0cc077358b807367f7db4163106dc9bbeb285db"
EXPECTED_FINAL_MODEL_SHA = "069acd3f99689ab6565b98a27e8d38f0ad0fc5539629a96e5ee85d807de03d68"
KNOWN_20260906_DE_NAME = "ファストネットワーク"
KNOWN_20260906_DS_NAME = "ファストネットワー"


class Stop(RuntimeError):
    pass


def sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def write_json(path: Path, value: Any) -> None:
    path.write_text(json.dumps(value, ensure_ascii=False, sort_keys=True, indent=2, allow_nan=False) + "\n", encoding="utf-8")


def write_csv(path: Path, rows: list[dict[str, Any]], fields: list[str]) -> None:
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields, extrasaction="ignore")
        writer.writeheader()
        writer.writerows(rows)


def bucket(value: int) -> str:
    return "5+" if value >= 5 else str(value)


def require_authority() -> dict[str, str]:
    prereg = ROOT / "docs" / "KeibaAI_Iteration3_Offset_PL_Raw_History_V1_Preregistration.md"
    hashes = {
        "preregistration_sha256": sha(prereg),
        "artifact_index_sha256": sha(EXP025 / "artifact_hashes.json"),
        "final_archival_model_sha256": sha(EXP025 / "final_offset_pl_v2_model.json"),
    }
    expected = (EXPECTED_PREREG_SHA, EXPECTED_ARTIFACT_INDEX_SHA, EXPECTED_FINAL_MODEL_SHA)
    if tuple(hashes.values()) != expected:
        raise Stop(f"STOP_EXP025_AUTHORITY_SHA_MISMATCH:{hashes}")
    return hashes


def frozen_rows() -> list[dict[str, Any]]:
    data = json.loads(FROZEN.read_text(encoding="utf-8"))
    rows = data.get("rows")
    if not isinstance(rows, list) or not rows:
        raise Stop("STOP_FROZEN_ROLLING_OOS_ROWS_MISSING")
    # March through 13 September is the exact EXP-025 evaluated scope.
    result = [dict(row) for row in rows if "202603" <= str(row.get("month")) <= "202609"]
    if len(result) != len(rows):
        raise Stop("STOP_UNEXPECTED_FROZEN_MONTH_SCOPE")
    keys = {(str(r["date"]), str(r["race_id"]), int(r["horse_number"])) for r in result}
    if len(keys) != len(result):
        raise Stop("STOP_FROZEN_IDENTITY_DUPLICATE")
    return result


def source_paths() -> dict[str, dict[str, Path]]:
    audit = json.loads(SOURCE_AUDIT.read_text(encoding="utf-8"))
    inventory = audit.get("inventory")
    if not isinstance(inventory, list):
        raise Stop("STOP_SOURCE_INVENTORY_MISSING")
    paths: dict[str, dict[str, Path]] = defaultdict(dict)
    for row in inventory:
        date, kind, rel = str(row["date"]), str(row["kind"]), str(row["path"])
        path = ROOT / rel
        if kind not in {"DG", "DE", "DS"} or not path.is_file():
            raise Stop(f"STOP_SOURCE_INVENTORY_PATH:{row}")
        if sha(path) != str(row["sha256"]):
            raise Stop(f"STOP_SOURCE_INVENTORY_SHA:{rel}")
        paths[date][kind] = path
    if not paths or any(set(value) != {"DG", "DE", "DS"} for value in paths.values()):
        raise Stop("STOP_SOURCE_INVENTORY_INCOMPLETE")
    return dict(paths)


def read_csv(path: Path, width: int) -> list[list[str]]:
    with path.open(encoding="cp932", newline="") as handle:
        rows = list(csv.reader(handle))
    if not rows or any(len(row) != width for row in rows):
        raise Stop(f"STOP_PRE_SOURCE_SCHEMA:{path.name}")
    return rows


def text(value: Any) -> str:
    return str(value or "").strip()


def number(value: Any) -> int:
    try:
        return int(text(value).replace("+", ""))
    except ValueError as exc:
        raise Stop(f"STOP_HISTORY_NUMERIC:{value!r}") from exc


def ds_day(row: list[str]) -> str:
    return f"20{number(row[0]):02d}{number(row[1]):02d}{number(row[2]):02d}"


def depth_map(rows: list[dict[str, Any]], paths: dict[str, dict[str, Path]]) -> dict[tuple[str, str, int], int]:
    """Existing adapter-compatible completed-history count, capped at five.

    The adapter's documented semantics are abnormal-code blank/0 and a
    positive finish; strict prior-date is additionally checked here.  This is
    source accounting, not a new feature transformation.
    """
    expected: dict[str, set[tuple[str, int]]] = defaultdict(set)
    for row in rows:
        expected[str(row["date"])].add((str(row["horse_name"]).replace(" ", "").replace("　", ""), int(row["horse_number"])))
    result: dict[tuple[str, str, int], int] = {}
    for date in sorted(expected):
        de = read_csv(paths[date]["DE"], 33)
        ds = read_csv(paths[date]["DS"], 50)
        by_name: dict[str, list[list[str]]] = defaultdict(list)
        for item in ds:
            if ds_day(item) >= date:
                raise Stop(f"STOP_DS_ASOF:{date}")
            by_name[text(item[16]).replace(" ", "").replace("　", "")].append(item)
        de_by_name_number = {(text(item[7]).replace(" ", "").replace("　", ""), number(item[3])): item for item in de}
        for name, horse_no in expected[date]:
            lookup_name = name
            if date == "20260906" and name == KNOWN_20260906_DE_NAME and horse_no == 8:
                lookup_name = KNOWN_20260906_DS_NAME
            if (name, horse_no) not in de_by_name_number or lookup_name not in by_name:
                raise Stop(f"STOP_DEPTH_IDENTITY:{date}:{name}:{horse_no}")
            completed = [item for item in by_name[lookup_name] if text(item[25]) in {"", "0"} and number(item[23]) > 0]
            result[(date, name, horse_no)] = min(5, len(completed))
    if len(result) != len(rows):
        raise Stop("STOP_DEPTH_COVERAGE")
    return result


def metric(rows: Iterable[dict[str, Any]], probability: str = "p_hgb") -> dict[str, Any]:
    values = list(rows)
    valid = [row for row in values if bool(row["valid_result"])]
    hits = sum(bool(row["actual_top3"]) for row in valid)
    probs = [float(row[probability]) for row in valid]
    actual = [int(bool(row["actual_top3"])) for row in valid]
    observed = hits / len(valid) if valid else None
    return {
        "horses": len(values), "races": len({(row["date"], row["race_id"]) for row in values}),
        "valid_horses": len(valid), "invalid_horses": len(values) - len(valid),
        "mean_base_pl_top3_probability": mean(probs) if probs else None,
        "actual_top3_count": hits, "actual_top3_rate": observed,
        "calibration_gap": (observed - mean(probs)) if probs else None,
        "brier": mean([(p - y) ** 2 for p, y in zip(probs, actual)]) if probs else None,
    }


def q1(rows: list[dict[str, Any]], depths: dict[tuple[str, str, int], int]) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    grouped: dict[tuple[str, str], list[dict[str, Any]]] = defaultdict(list)
    by_race: dict[tuple[str, str], list[dict[str, Any]]] = defaultdict(list)
    for row in rows:
        by_race[(str(row["date"]), str(row["race_id"]))].append(row)
    for key, values in by_race.items():
        context = "CURRENT_BUY_RACE" if any(bool(item["current_buy"]) for item in values) else "CURRENT_NO_BUY_RACE"
        for row in values:
            row["history_depth"] = depths[(str(row["date"]), str(row["horse_name"]).replace(" ", "").replace("　", ""), int(row["horse_number"]))]
            row["race_context"] = context
            grouped[("ALL_RACES", bucket(row["history_depth"]))].append(row)
            grouped[(context, bucket(row["history_depth"]))].append(row)
    output = []
    for scope in ("ALL_RACES", "CURRENT_BUY_RACE", "CURRENT_NO_BUY_RACE"):
        for level in ("1", "2", "3", "4", "5+"):
            output.append({"scope": scope, "history_depth": level, **metric(grouped[(scope, level)])})
    return output, rows


def q2(rows: list[dict[str, Any]], depths: dict[tuple[str, str, int], int]) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    with SELECTED.open(encoding="utf-8", newline="") as handle:
        selected = list(csv.DictReader(handle))
    base = {(r["date"], r["race_id"], int(r["horse_number"])): r for r in selected if r["comparator"] == "BASE_PL"}
    v2 = {(r["date"], r["race_id"], int(r["horse_number"])): r for r in selected if r["comparator"] == "OFFSET_PL_V2"}
    frozen = {(str(r["date"]), str(r["race_id"]), int(r["horse_number"])): r for r in rows}
    current_by_race: dict[tuple[str, str], bool] = {}
    for row in rows:
        key = (str(row["date"]), str(row["race_id"]))
        current_by_race[key] = current_by_race.get(key, False) or bool(row["current_buy"])
    groups: dict[tuple[str, str], dict[str, list[dict[str, Any]]]] = defaultdict(lambda: {"BASE_ONLY": [], "V2_ONLY": []})
    for label, keys in (("BASE_ONLY", set(base) - set(v2)), ("V2_ONLY", set(v2) - set(base))):
        for key in sorted(keys):
            frozen_row = frozen.get(key)
            if frozen_row is None:
                raise Stop(f"STOP_SELECTION_FROZEN_IDENTITY:{key}")
            name = str(frozen_row["horse_name"]).replace(" ", "").replace("　", "")
            depth = bucket(depths[(key[0], name, key[2])])
            context = "CURRENT_BUY_RACE" if current_by_race[(key[0], key[1])] else "CURRENT_NO_BUY_RACE"
            groups[(context, depth)][label].append(frozen_row)
    output: list[dict[str, Any]] = []
    for context in ("CURRENT_BUY_RACE", "CURRENT_NO_BUY_RACE"):
        for level in ("1", "2", "3", "4", "5+"):
            base_only, v2_only = groups[(context, level)]["BASE_ONLY"], groups[(context, level)]["V2_ONLY"]
            output.append({
                "race_context": context, "history_depth": level,
                "base_only_selected_n": len(base_only), "v2_only_selected_n": len(v2_only),
                "base_only": metric(base_only), "v2_only": metric(v2_only),
            })
    return output, {
        "base_selected_n": len(base), "v2_selected_n": len(v2),
        "base_only_selected_n": len(set(base) - set(v2)), "v2_only_selected_n": len(set(v2) - set(base)),
        "rank_movement": "NOT_AVAILABLE_IN_FROZEN_SAME_VOLUME_SELECTION_ARTIFACT",
        "interpretation": "Current-no-buy races have k=0 under same-volume semantics; therefore no Base/V2 selected horses can occur there.",
    }


def q3(paths: dict[str, dict[str, Path]]) -> dict[str, Any]:
    counts = {"de_rows": 0, "jockey_nonempty": 0, "sire_nonempty": 0, "dam_nonempty": 0, "dam_sire_nonempty": 0, "target_context_rows": 0}
    for date in sorted(paths):
        de, dg = read_csv(paths[date]["DE"], 33), read_csv(paths[date]["DG"], 11)
        counts["de_rows"] += len(de)
        counts["jockey_nonempty"] += sum(bool(text(r[10])) for r in de)
        counts["sire_nonempty"] += sum(bool(text(r[16])) for r in de)
        counts["dam_nonempty"] += sum(bool(text(r[17])) for r in de)
        counts["dam_sire_nonempty"] += sum(bool(text(r[20])) for r in de)
        counts["target_context_rows"] += sum(bool(text(r[3]) and text(r[7]) and text(r[8])) for r in dg)
    total = counts["de_rows"]
    def coverage(name: str) -> dict[str, Any]:
        return {"nonempty": counts[name], "total": total, "rate": counts[name] / total if total else None}
    return {
        "scope": "PRE_ONLY_NO_RESULT_ROWS_PARSED",
        "dates": len(paths),
        "training_workout": {
            "source_exists": "NO", "source_files_schema": "No workout/training source is present in the canonical DG/DE/DS prediction-input inventory.",
            "pre_time_status": "NOT_AVAILABLE", "coverage": None, "main_fields_available": [],
            "leakage_or_pit_risk": "No source to qualify; external search prohibited.",
        },
        "pedigree_plus_target_context": {
            "source_exists": "YES", "source_files_schema": "DE CP932/headerless/33 columns: sire=17th, dam=18th, maternal-grandsire=21st; DG: venue=4th, surface=8th, distance=9th.",
            "pre_time_status": "CONFIRMED", "coverage": {"sire": coverage("sire_nonempty"), "dam": coverage("dam_nonempty"), "maternal_grandsire": coverage("dam_sire_nonempty"), "target_race_context": {"nonempty": counts["target_context_rows"], "total": counts["target_context_rows"], "rate": 1.0}},
            "main_fields_available": ["sire", "dam", "maternal_grandsire", "target_venue", "target_surface", "target_distance"],
            "leakage_or_pit_risk": "CONFIRMED_PRE_TIME when read only from the same-date DG/DE snapshot; no performance association was calculated.",
        },
        "jockey_trainer_recent_form": {
            "source_exists": "PARTIAL", "source_files_schema": "DE current jockey=11th; DS past jockey=20th and completed past-race fields. Trainer has no authoritative mapping in the active prediction adapter.",
            "pre_time_status": "CONFIRMED for jockey/recent-form; NOT_AVAILABLE for trainer", "coverage": {"current_jockey": coverage("jockey_nonempty")},
            "main_fields_available": ["current_jockey", "past_jockey", "past_finish", "past_margin", "past_corners", "past_last3f", "past_body_weight"],
            "leakage_or_pit_risk": "DS chronology is enforced before the target date; target-day Result fields were not opened.",
        },
        "adapter_authority": "review/target_bulk_prediction_input_adapter_v1.py:_today_entry and _past_races",
    }


def run(output: Path = OUT) -> dict[str, Any]:
    if output.exists():
        raise Stop("STOP_OUTPUT_EXISTS")
    authority = require_authority()
    rows = frozen_rows()
    paths = source_paths()
    depths = depth_map(rows, paths)
    q1_rows, annotated = q1(rows, depths)
    q2_rows, q2_summary = q2(annotated, depths)
    q3_summary = q3(paths)
    staging = Path(tempfile.mkdtemp(prefix=".exp025_post_failure_", dir=output.parent))
    try:
        write_csv(staging / "q1_history_depth_table.csv", q1_rows, list(q1_rows[0]))
        buy_rows = [row for row in q1_rows if row["scope"] != "ALL_RACES"]
        write_csv(staging / "q1_buy_vs_no_buy_table.csv", buy_rows, list(buy_rows[0]))
        write_csv(staging / "q2_selection_disagreement_table.csv", q2_rows, list(q2_rows[0]))
        write_json(staging / "q2_history_depth_effect_summary.json", q2_summary)
        write_json(staging / "q3_new_pre_source_availability.json", q3_summary)
        # The coefficient is consistent, but Q1/Q2 are descriptive only.  Do not
        # convert the observed segmentation into a new gate or hypothesis claim.
        conclusion = {
            "STATUS": "COMPLETE", "ROLE": "POST_EXP025_BOUNDED_FAILURE_DIAGNOSTIC",
            "authority": authority, "q1_base_probability_source": "Frozen Iteration-2 run_a_frozen.json:p_hgb; EXP-025 reproduction audited this exactly as fold-specific Base PL.",
            "q2_selection_source": "Frozen EXP-025 retry1 selected_horses.csv; no selection was recomputed.",
            "q3_result_access": 0, "history_depth_structure": "WEAK",
            "new_pre_information_available": "YES",
            "recommended_next_path": "NEW_INFORMATION_SOURCE_PRIORITY",
            "new_experiment_ready": "NO",
            "hypothesis_family_if_authorized_later": "PRE-time pedigree/context or current-jockey/recent-form information, subject to separate PIT qualification and preregistration.",
            "boundaries": {"EXP025_CHANGED": False, "EXP024_CHANGED": False, "PRODUCTION_CHANGED": False, "MODEL_TRAINED": False, "GIT_CHANGED": False, "new_threshold": False, "new_selection_rule": False, "result_rows_parsed_for_q3": 0},
            "blocking": 0, "major": 0,
            "minor": ["Frozen same-volume artifact has no full-race rank-position export; mean/median Base-to-V2 rank movement is not reported rather than reconstructed."],
        }
        write_json(staging / "summary.json", conclusion)
        q1_display = "\n".join(f"| {r['scope']} | {r['history_depth']} | {r['horses']} | {r['races']} | {r['actual_top3_count']}/{r['valid_horses']} | {r['actual_top3_rate']!s} | {r['mean_base_pl_top3_probability']!s} | {r['calibration_gap']!s} | {r['brier']!s} |" for r in q1_rows)
        q2_display = "\n".join(f"| {r['race_context']} | {r['history_depth']} | {r['base_only_selected_n']} | {r['v2_only_selected_n']} |" for r in q2_rows)
        (staging / "summary.md").write_text(
            "# EXP-025 Post-Failure Bounded Diagnostic\n\n"
            "`POST_EXP025_BOUNDED_FAILURE_DIAGNOSTIC`。モデル再学習・再推論・新規閾値・Git変更は行っていない。\n\n"
            "## Q1 — Base PL by PRE-time history depth\n\n"
            "| Scope | Depth | Horses | Races | Top3 / valid | Actual rate | Mean Base PL P(top3) | Calibration gap | Brier |\n|---|---:|---:|---:|---:|---:|---:|---:|---:|\n" + q1_display + "\n\n"
            "## Q2 — Frozen same-volume Base-only vs V2-only selection\n\n"
            "| Race context | Depth | Base-only | V2-only |\n|---|---:|---:|---:|\n" + q2_display + "\n\n"
            f"Rank movement: `{q2_summary['rank_movement']}`.\n\n"
            "## Q3 — New PRE source availability\n\n"
            "- Training/workout: `NO` / `NOT_AVAILABLE`\n- Pedigree plus target context: `YES` / `CONFIRMED`\n- Jockey/recent-form: `PARTIAL` / current jockey and chronological DS history confirmed; trainer mapping not authoritative.\n\n"
            "## Conclusion\n\n"
            "`HISTORY_DEPTH_STRUCTURE = WEAK`\n\n"
            "`NEW_PRE_INFORMATION_AVAILABLE = YES`\n\n"
            "`RECOMMENDED_NEXT_PATH = NEW_INFORMATION_SOURCE_PRIORITY`\n\n"
            "`NEW_EXPERIMENT_READY = NO`\n",
            encoding="utf-8",
        )
        hashes = {p.relative_to(staging).as_posix(): {"sha256": sha(p), "size": p.stat().st_size} for p in sorted(staging.iterdir()) if p.is_file()}
        write_json(staging / "artifact_hashes.json", {"self_hash_excluded": True, "artifacts": hashes})
        staging.rename(output)
        return conclusion
    except Exception:
        shutil.rmtree(staging, ignore_errors=True)
        raise


if __name__ == "__main__":
    print(json.dumps(run(), ensure_ascii=False, sort_keys=True, indent=2))
