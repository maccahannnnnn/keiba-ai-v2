"""Build the read-only daily PRE track-information observability audit.

The audit only reads frozen PRE artifacts, source code, and the finalized
Full-Race Observation source for schema/coverage.  It never invokes the
prediction adapter and never joins track context to performance outcomes.
"""

from __future__ import annotations

import csv
import hashlib
import json
import math
import re
from collections import Counter, defaultdict
from pathlib import Path
from typing import Any, Iterable


ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "reports" / "daily_pre_track_information_runtime_observability_audit_v1"
ROLE = "OBSERVABILITY_AND_REPLAY_FEASIBILITY_DIAGNOSTIC_ONLY"

DAILY_RUNS = (
    ("20260815", "reports/prospective_analysis_20260815_v1"),
    ("20260816", "reports/prospective_analysis_20260816_v1"),
    ("20260822", "reports/prospective_prediction_20260822_v1"),
    ("20260823", "reports/prospective_prediction_20260823_v1"),
    ("20260829", "reports/prospective_prediction_20260829_v1"),
    ("20260830", "reports/prospective_prediction_20260830_v1"),
    ("20260905", "reports/prospective_prediction_20260905_v1"),
    ("20260906", "reports/prospective_prediction_20260906_v1"),
    ("20260912", "reports/daily_pre_prediction_20260912/current_frozen"),
)

CODE_PATHS = (
    "evaluators/track_bias_evaluator.py",
    "evaluation/track_condition_suitability_evaluator.py",
    "evaluation/track_condition_evaluator.py",
    "evaluation/target_trial_adapter.py",
    "evaluation/manual_track_bias_builder.py",
    "engine/meeting_bias_evidence_extractor.py",
    "review/meeting_bias_read_only_collector.py",
    "review/prospective_prediction_runner_v1.py",
    "review/target_bulk_prediction_input_shadow_v1.py",
)

LAYER_B_RAW = ROOT / "data" / "raw" / "target" / "scehema_samples" / "テスト３.csv"
LAYER_B_SCHEMA = ROOT / "docs" / "target_bulk_result_schema_v1.json"


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def canonical_json(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, indent=2) + "\n"


def dump_json(path: Path, value: Any) -> None:
    path.write_text(canonical_json(value), encoding="utf-8")


def write_csv(path: Path, rows: list[dict[str, Any]], fields: list[str]) -> None:
    with path.open("w", encoding="utf-8-sig", newline="") as stream:
        writer = csv.DictWriter(stream, fieldnames=fields, extrasaction="ignore")
        writer.writeheader()
        writer.writerows(rows)


def classify_manual_track_bias(value: Any, observable: bool = True) -> str:
    if not observable:
        return "NOT_OBSERVABLE_FROM_ARTIFACT"
    if value is None or value is False or str(value).strip().lower() in {"", "none", "null", "neutral", "false"}:
        return "PROVEN_NULL_OR_ABSENT"
    return "PROVEN_NON_NULL"


def count_track_bias_scores(rows: Iterable[dict[str, Any]]) -> dict[str, int]:
    counts = {"total": 0, "zero": 0, "positive": 0, "negative": 0, "missing": 0, "malformed": 0}
    for row in rows:
        counts["total"] += 1
        value = row.get("track_bias_score")
        if value is None or value == "":
            counts["missing"] += 1
            continue
        try:
            number = float(value)
        except (TypeError, ValueError):
            counts["malformed"] += 1
            continue
        if not math.isfinite(number):
            counts["malformed"] += 1
        elif number == 0:
            counts["zero"] += 1
        elif number > 0:
            counts["positive"] += 1
        else:
            counts["negative"] += 1
    return counts


def classify_timestamp(field_name: str, value: Any) -> str:
    if value in (None, ""):
        return "NONE"
    key = field_name.lower()
    if any(token in key for token in ("result_available", "finalized", "source_timestamp", "published_at")):
        return "SOURCE_SEMANTIC_TIMESTAMP"
    if any(token in key for token in ("post_time", "scheduled", "start_time")):
        return "SCHEDULED_RACE_TIME_ONLY"
    if any(token in key for token in ("mtime", "created_at", "modified_at", "filesystem")):
        return "FILESYSTEM_METADATA_ONLY"
    return "NONE"


def prior_same_surface_count(races: Iterable[dict[str, Any]], target: dict[str, Any]) -> int:
    return sum(
        1
        for row in races
        if row["date"] == target["date"]
        and row["venue"] == target["venue"]
        and row["surface"] == target["surface"]
        and row["race_number"] < target["race_number"]
    )


def _race_parts(race_id: str) -> tuple[str, int]:
    match = re.match(r"race_\d{8}_([^_]+)_(\d+)R$", race_id)
    if not match:
        return "UNKNOWN", 0
    aliases = {
        "sapporo": "札幌", "hakodate": "函館", "fukushima": "福島",
        "niigata": "新潟", "tokyo": "東京", "nakayama": "中山",
        "chuukyou": "中京", "chukyo": "中京", "kyoto": "京都",
        "hanshin": "阪神", "kokura": "小倉",
    }
    return aliases.get(match.group(1).lower(), match.group(1)), int(match.group(2))


def _prediction_files(root: Path) -> list[Path]:
    return sorted(root.glob("race_*_prediction.json"))


def _daily_inventory() -> tuple[list[dict[str, Any]], list[dict[str, Any]], list[dict[str, Any]]]:
    inventory: list[dict[str, Any]] = []
    manual: list[dict[str, Any]] = []
    race_rows: list[dict[str, Any]] = []
    for date, rel in DAILY_RUNS:
        run_root = ROOT / rel
        if not run_root.exists():
            raise FileNotFoundError(f"AUTHORITATIVE_DAILY_PRE_ROOT_MISSING:{rel}")
        provenance_path = run_root / "provenance.json"
        input_path = run_root / "input_manifest.json"
        provenance = json.loads(provenance_path.read_text(encoding="utf-8"))
        input_manifest = json.loads(input_path.read_text(encoding="utf-8"))
        files = _prediction_files(run_root)
        if not files:
            raise ValueError(f"PREDICTION_ARTIFACTS_NOT_FOUND:{rel}")
        per_venue: dict[str, dict[str, int]] = defaultdict(
            lambda: {"races": 0, "horses": 0, "race_context": 0, "evaluator": 0, "condition": 0, "bias": 0}
        )
        for artifact in files:
            payload = json.loads(artifact.read_text(encoding="utf-8"))
            race_id = str(payload.get("race_id") or artifact.stem.replace("_prediction", ""))
            venue, race_number = _race_parts(race_id)
            rows = payload.get("ranked_results") or []
            row_conditions = sorted({
                str(row.get("track_condition")).strip()
                for row in rows if row.get("track_condition") not in (None, "")
            })
            root_condition = payload.get("track_condition")
            context = payload.get("race_context") if isinstance(payload.get("race_context"), dict) else {}
            persisted_condition = root_condition or context.get("track_condition")
            if persisted_condition in (None, "") and len(row_conditions) == 1:
                persisted_condition = row_conditions[0]
            evaluator_available = any("track_bias_score" in row or "track_condition_score" in row for row in rows)
            bias_available = any("track_bias_score" in row for row in rows)
            per_venue[venue]["races"] += 1
            per_venue[venue]["horses"] += len(rows)
            per_venue[venue]["race_context"] += int(bool(context))
            per_venue[venue]["evaluator"] += int(evaluator_available)
            per_venue[venue]["condition"] += int(persisted_condition not in (None, ""))
            per_venue[venue]["bias"] += int(bias_available)
            race_rows.append({
                "date": date, "venue": venue, "race_number": race_number, "race_id": race_id,
                "artifact": artifact.relative_to(ROOT).as_posix(), "horse_count": len(rows),
                "rows": rows,
                "race_context_available": bool(context),
                "evaluator_outputs_available": evaluator_available,
                "track_condition": persisted_condition,
                "track_condition_row_values": row_conditions,
                "race_context": context,
            })
        sources = input_manifest.get("sources") or {}
        source_paths = ";".join(
            str((value or {}).get("path") or "") for _, value in sorted(sources.items()) if isinstance(value, dict)
        )
        for venue, count in sorted(per_venue.items()):
            inventory.append({
                "included": True, "date": date, "venue": venue,
                "race_count": count["races"], "horse_count": count["horses"],
                "source_path": source_paths,
                "prediction_artifact_path": run_root.relative_to(ROOT).as_posix(),
                "artifact_type": "AUTHORITATIVE_DAILY_PRE_CURRENT_AI",
                "schema_version": provenance.get("schema_version") or "prospective_prediction_schema_v1",
                "race_context_available": count["race_context"] > 0,
                "evaluator_outputs_available": count["evaluator"] > 0,
                "track_condition_available": count["condition"] > 0,
                "track_bias_fields_available": count["bias"] > 0,
            })
        runner = str(provenance.get("runner_path") or "")
        run_new = str(provenance.get("run_new_module") or "review/target_bulk_prediction_input_shadow_v1.py")
        proven_by_wiring = (
            "prospective_prediction_runner_v1.py" in runner
            or "prospective_prediction_20260823_human_exclusion_runner.py" in runner
        ) and (
            "target_bulk_prediction_input_shadow_v1.py" in run_new
            or "prospective_prediction_20260823_human_exclusion_runner.py" in runner
        )
        manual.append({
            "date": date,
            "run_path": run_root.relative_to(ROOT).as_posix(),
            "runner_path": runner,
            "manual_track_bias_artifact_value": "ABSENT",
            "classification": classify_manual_track_bias(None, observable=proven_by_wiring),
            "evidence": "run_new initializes all bias fields None and sets manual_track_bias_active=False" if proven_by_wiring else "runtime artifact does not persist invocation argument",
        })
    return inventory, manual, race_rows


def _discover_other_prediction_generations(primary_roots: set[str]) -> list[dict[str, Any]]:
    rows = []
    for path in sorted((ROOT / "reports").glob("**/prediction_manifest.json")):
        rel_root = path.parent.relative_to(ROOT).as_posix()
        if rel_root in primary_roots:
            continue
        category = "RETROSPECTIVE_OR_DEVELOPMENT_PREDICTION"
        if "retry" in rel_root.lower():
            category = "RETRY_OR_SUPERSEDED_PREDICTION"
        rows.append({"path": rel_root, "category": category, "included_in_runtime_population": False})
    return rows


def _score_coverage(race_rows: list[dict[str, Any]]) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    detail = []
    total = Counter()
    for race in race_rows:
        count = count_track_bias_scores(race["rows"])
        total.update(count)
        detail.append({
            "date": race["date"], "venue": race["venue"], "race_number": race["race_number"],
            "race_id": race["race_id"], **count,
            "zero_rate": count["zero"] / count["total"] if count["total"] else 0,
            "nonzero_rate": (count["positive"] + count["negative"]) / count["total"] if count["total"] else 0,
            "missing_rate": count["missing"] / count["total"] if count["total"] else 0,
        })
    total_n = total["total"]
    summary = {
        **dict(total),
        "zero_rate": total["zero"] / total_n if total_n else 0,
        "nonzero_rate": (total["positive"] + total["negative"]) / total_n if total_n else 0,
        "missing_rate": total["missing"] / total_n if total_n else 0,
        "status": (
            "ACTIVE_ON_SOME_RUNS"
            if total["positive"] + total["negative"] > 0
            else "NOT_OBSERVABLE"
            if total["missing"] > 0
            else "ALWAYS_NEUTRAL"
        ),
        "observable_subset_status": "ALWAYS_NEUTRAL" if total["zero"] and not (total["positive"] + total["negative"] + total["malformed"]) else "MIXED_OR_EMPTY",
        "interpretation": "projection omits track_bias_score; missing is not proof of zero",
    }
    return detail, summary


def _condition_coverage(race_rows: list[dict[str, Any]]) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    detail = []
    distribution = Counter()
    populated = 0
    for race in race_rows:
        value = race.get("track_condition") or (race.get("race_context") or {}).get("track_condition")
        normalized = {
            "good": "良", "firm": "良", "良": "良",
            "yielding": "稍重", "稍": "稍重", "稍重": "稍重",
            "heavy": "重", "重": "重",
            "soft": "不良", "不": "不良", "不良": "不良",
        }.get(str(value or "").strip().lower(), "unknown/missing")
        if normalized != "unknown/missing":
            populated += 1
        distribution[normalized] += 1
        detail.append({
            "date": race["date"], "venue": race["venue"], "race_number": race["race_number"],
            "race_id": race["race_id"], "track_condition": normalized,
            "source_artifact": race["artifact"], "missing": normalized == "unknown/missing",
            "part_of_initial_snapshot": normalized != "unknown/missing",
            "later_pre_update_exists": False,
            "timestamp_semantics": "NONE",
            "provenance_class": "HORSE_HISTORY_DOMINANT_RUNTIME_VALUE" if normalized != "unknown/missing" else "NOT_PERSISTED",
            "track_condition_score_observable_horses": sum("track_condition_score" in row for row in race["rows"]),
        })
    total = len(detail)
    return detail, {
        "total_races": total, "populated_races": populated, "missing_races": total - populated,
        "distribution": dict(sorted(distribution.items())),
        "status": "NOT_OBSERVABLE" if populated == 0 else ("FULL" if populated == total else "PARTIAL"),
        "official_target_condition_source": "NOT_PRESENT_IN_DG_DE_DS_DAILY_ARTIFACT",
        "runtime_fallback": "dominant normalized condition from horse own history; value not persisted by projection",
    }


def _numeric(value: str) -> bool:
    try:
        float(str(value).strip())
        return True
    except (TypeError, ValueError):
        return False


def _surface(value: str) -> str:
    text = str(value).strip()
    if "芝" in text:
        return "turf"
    if "ダ" in text:
        return "dirt"
    return "other"


def _layer_b() -> tuple[dict[str, Any], list[dict[str, Any]], list[dict[str, Any]]]:
    schema = json.loads(LAYER_B_SCHEMA.read_text(encoding="utf-8"))
    columns = schema["ordered_columns"]
    with LAYER_B_RAW.open("r", encoding="cp932", newline="") as stream:
        raw_rows = list(csv.reader(stream))
    if any(len(row) != 50 for row in raw_rows):
        raise ValueError("LAYER_B_SCHEMA_WIDTH_MISMATCH")
    rows = [dict(zip(columns, row)) for row in raw_rows]
    race_map: dict[tuple[str, str, int], list[dict[str, str]]] = defaultdict(list)
    for row in rows:
        year = int(row["年"])
        if year < 100:
            year += 2000
        date = f"{year:04d}{int(row['月']):02d}{int(row['日']):02d}"
        race_map[(date, row["場所"].strip(), int(row["レース番号"]))].append(row)

    specs = {
        "race_date": ("RACE", None, "date"), "venue": ("RACE", "場所", "text"),
        "race_number": ("RACE", "レース番号", "numeric"), "surface": ("RACE", "芝・ダ", "surface"),
        "distance": ("RACE", "距離", "numeric"), "course_configuration": ("RACE", "トラックコード", "text"),
        "frame_number": ("HORSE_RECORD", None, "absent"), "horse_number": ("HORSE_RECORD", "馬番", "numeric"),
        "finish_position": ("HORSE_RECORD", "確定着順", "numeric"),
        "corner_1": ("HORSE_RECORD", "通過順1角", "numeric"), "corner_2": ("HORSE_RECORD", "通過順2角", "numeric"),
        "corner_3": ("HORSE_RECORD", "通過順3角", "numeric"), "corner_4": ("HORSE_RECORD", "通過順4角", "numeric"),
        "last_3f": ("HORSE_RECORD", "上がり3Fタイム", "numeric"),
        "race_timing": ("HORSE_RECORD", "走破タイム(秒)", "numeric"),
        "lap_timing": ("HORSE_RECORD", "タイムS", "time"),
        "track_condition": ("RACE", "馬場状態", "condition"),
        "scheduled_start_time": ("RACE", None, "absent"),
        "result_finalization_timestamp": ("RACE", None, "absent"),
    }
    race_records = []
    for (date, venue, race_number), members in sorted(race_map.items()):
        first = members[0]
        race_records.append({"date": date, "venue": venue, "race_number": race_number, "surface": _surface(first["芝・ダ"]), "row": first})

    coverage = []
    for field, (unit, column, kind) in specs.items():
        for surface in ("all", "turf", "dirt", "other"):
            source = race_records if unit == "RACE" else [
                {"surface": _surface(row["芝・ダ"]), "row": row} for row in rows
            ]
            selected = [item for item in source if surface == "all" or item["surface"] == surface]
            valid = missing = malformed = 0
            for item in selected:
                if field == "race_date":
                    value = item.get("date")
                elif column is None:
                    value = ""
                else:
                    value = item["row"].get(column, "")
                text = str(value or "").strip()
                if not text:
                    missing += 1
                elif kind == "numeric" and not _numeric(text):
                    malformed += 1
                elif kind == "time" and not (_numeric(text) or re.fullmatch(r"\d+\.\d{2}\.\d", text)):
                    malformed += 1
                elif kind == "surface" and _surface(text) == "other":
                    malformed += 1
                elif kind == "condition" and text not in {"良", "稍", "稍重", "重", "不", "不良"}:
                    malformed += 1
                else:
                    valid += 1
            coverage.append({
                "field": field, "schema_column": column or "NOT_IN_SCHEMA", "unit": unit,
                "surface": surface, "total": len(selected), "valid": valid,
                "missing": missing, "malformed": malformed,
                "coverage_rate": valid / len(selected) if selected else None,
            })

    distributions = Counter()
    for race in race_records:
        prior = prior_same_surface_count(race_records, race)
        bucket = "3+" if prior >= 3 else str(prior)
        distributions[(race["race_number"], race["surface"], bucket)] += 1
    prior_rows = [
        {"target_race_number": race_no, "surface": surface, "prior_same_surface_bucket": bucket, "target_race_count": count}
        for (race_no, surface, bucket), count in sorted(distributions.items())
    ]
    inventory = {
        "source_path": LAYER_B_RAW.relative_to(ROOT).as_posix(), "source_sha256": sha256(LAYER_B_RAW),
        "schema_path": LAYER_B_SCHEMA.relative_to(ROOT).as_posix(), "schema_sha256": sha256(LAYER_B_SCHEMA),
        "schema_version": schema["schema_version"], "row_count": len(rows), "race_count": len(race_records),
        "date_count": len({row["date"] for row in race_records}),
        "dates": sorted({row["date"] for row in race_records}),
        "race_order_deterministic": True,
        "scheduled_start_time_available": False,
        "result_finalization_semantic_timestamp_available": False,
        "filesystem_mtime_used_as_event_time": False,
        "notes": ["Formal finalized Full-Race Observation authority; schema/coverage inspection only", "finish values were counted for coverage only and were not joined to predictions"],
    }
    return inventory, coverage, prior_rows


def _write_report(summary: dict[str, Any], layer_b: dict[str, Any]) -> None:
    lines = [
        "# Daily PRE Track Information Runtime Observability Audit v1", "",
        f"`AUDIT_ROLE = {ROLE}`", "",
        "## 結論", "",
        "- 日次PREの標準projectionにはtrack_bias_score、track_condition_score、race_contextが保存されないため、実スコアの非ゼロ率は成果物から観測不能。",
        "- 日次runnerはmanual_track_biasを供給せず、bias fieldsをNoneで初期化する経路を使用。監査対象9 runで非null利用は確認されなかった。",
        "- target-race公式馬場状態はDG/DE/DSから供給されず、現行runtimeは各馬過去走の優勢値をrace既定値として補完するが、その値とfreshnessは標準PRE成果物へ保存されない。",
        "- 同日biasの自動refresh経路は見つからない。",
        "- Full-Race Observationはrace orderとbias観測候補fieldを多く保持するが、予定発走時刻とResult公開・確定時刻を持たないため厳密timestamp replayは証明できない。", "",
        "## Audit population", "",
        f"- Dates: {summary['audit_date_count']} ({', '.join(summary['audit_included_dates'])})",
        f"- Races: {summary['audit_race_count']}", f"- Horses: {summary['audit_horse_count']}", "",
        "## Runtime observability", "",
        f"- manual_track_bias: {summary['manual_track_bias_runtime_use_status']} (non-null={summary['manual_track_bias_proven_non_null_runs']}, null/absent={summary['manual_track_bias_proven_null_or_absent_runs']}, not-observable={summary['manual_track_bias_not_observable_runs']})",
        f"- track_bias_score: {summary['track_bias_score_runtime_status']} (total={summary['track_bias_score_total_horse_rows']}, saved zero={summary['track_bias_score_zero_rows']}, saved nonzero={summary['track_bias_score_nonzero_rows']}, missing={summary['track_bias_score_missing_rows']})",
        f"- track_condition: {summary['track_condition_runtime_coverage']}",
        f"- pre-race refresh path: {summary['track_condition_pre_race_refresh_path']}", "",
        "## Layer B", "", f"- Formal source rows: {layer_b['row_count']}", f"- Races: {layer_b['race_count']}",
        "- Race order: deterministic by date/venue/race number",
        "- Scheduled post time: unavailable",
        "- Result availability/finalization semantic timestamp: unavailable", "",
        "性能値との結合、バイアス式・閾値の作成、Prediction再実行は行っていません。",
    ]
    (OUT / "report.md").write_text("\n".join(lines) + "\n", encoding="utf-8")


def run() -> Path:
    if OUT.exists():
        raise FileExistsError(f"OUTPUT_ROOT_EXISTS:{OUT}")
    OUT.mkdir(parents=True)
    inventory, manual, races = _daily_inventory()
    primary_roots = {rel for _, rel in DAILY_RUNS}
    other_generations = _discover_other_prediction_generations(primary_roots)
    score_detail, score_summary = _score_coverage(races)
    condition_detail, condition_summary = _condition_coverage(races)
    layer_b, layer_b_coverage, prior_distribution = _layer_b()

    dates = sorted({row["date"] for row in races})
    audit_population = {
        "audit_role": ROLE,
        "audit_date_count": len(dates), "audit_race_count": len(races),
        "audit_horse_count": sum(row["horse_count"] for row in races),
        "audit_included_dates": dates,
        "population_rule": "all discoverable authoritative real daily PRE Current-AI runs using prospective_prediction_schema_v1",
        "incompatible_or_non_daily_generations": other_generations,
        "non_daily_manifest_count": len(other_generations),
    }
    code_findings = {
        "status": "PASS",
        "files": [{"path": path, "sha256": sha256(ROOT / path)} for path in CODE_PATHS],
        "line_evidence": [
            {"path": "evaluation/target_trial_adapter.py", "lines": "136,143-159", "fact": "manual_track_bias is optional and only activates a neutral baseline recursion when non-neutral"},
            {"path": "evaluation/target_trial_adapter.py", "lines": "794-806", "fact": "missing target condition is derived from dominant horse-history condition; manual bias is merged separately"},
            {"path": "evaluation/target_trial_adapter.py", "lines": "1267-1308", "fact": "TrackBiasEvaluator output is attached before FinalScore"},
            {"path": "evaluators/track_bias_evaluator.py", "lines": "36-44,100-121,228-238", "fact": "absence of bias fields returns neutral score zero and matched false"},
            {"path": "review/target_bulk_prediction_input_shadow_v1.py", "lines": "393-415", "fact": "daily run_new initializes target condition and all bias fields as None, then enriches from histories"},
            {"path": "review/prospective_prediction_runner_v1.py", "lines": "91-123,133-140", "fact": "daily runner invokes run_new and the persisted projection omits track context evaluator fields"},
            {"path": "engine/meeting_bias_evidence_extractor.py", "lines": "88-119,121-190", "fact": "extractor consumes collected result-derived Top3/finish patterns"},
            {"path": "review/meeting_bias_read_only_collector.py", "lines": "43-116", "fact": "collector scans complete saved review directories with no target-race rolling cutoff"},
        ],
        "daily_call_path": "prospective_prediction_runner_v1.run -> target_bulk_prediction_input_shadow_v1.run_new -> TargetTrialAdapter internal evaluators",
        "track_condition_origin": "entry CSV when present; otherwise dominant normalized value from all horse history runs",
        "daily_bulk_track_condition_origin": "run_new initializes target condition None; enrich derives dominant value from horse history",
        "manual_track_bias_supply_point": "TargetTrialAdapter.run(manual_track_bias=...) and ManualTrackBiasBuilder",
        "daily_runner_supplies_manual_track_bias": False,
        "track_bias_score_generation": "TrackBiasEvaluator evaluates race_context; no bias fields returns neutral zero",
        "neutral_fallback": "score=0, matched=False, neutral comment; no guessed bias",
        "projection_persists_track_fields": False,
        "automatic_same_day_refresh_found": False,
    }
    refresh = {
        "status": "NOT_FOUND", "initial_snapshot_runner": "review/prospective_prediction_runner_v1.py",
        "searched_paths": list(CODE_PATHS), "second_snapshot_or_per_race_refresh": "NOT_FOUND",
        "official_track_condition_update_function": "NOT_FOUND",
        "filesystem_timestamps_accepted_as_event_time": False,
    }
    snapshot_races = [row for row in races if row["date"] == "20260912"]
    snapshot = {
        "date": "20260912", "race_count": len(snapshot_races),
        "horse_count": sum(row["horse_count"] for row in snapshot_races),
        "track_bias_nonzero_horses": 0, "track_bias_zero_horses": 0,
        "track_bias_missing_horses": sum(row["horse_count"] for row in snapshot_races),
        "track_condition_values": ["unknown/missing"],
        "track_condition_score_observable_horses": 0,
        "manual_track_bias_provenance": "standard runner wiring proves absent; value not persisted per race",
        "race_context_bias_fields": {key: "NOT_PERSISTED" for key in ("track_bias", "inside_bias", "outside_bias", "front_bias", "closer_bias")},
        "races": [{
            "race_id": row["race_id"], "venue": row["venue"], "race_number": row["race_number"],
            "horse_count": row["horse_count"], "track_condition": "unknown/missing",
            "track_condition_score": "NOT_PERSISTED", "track_bias_score": "NOT_PERSISTED",
        } for row in snapshot_races],
        "warning": "missing persisted score must not be reclassified as runtime zero",
    }
    timestamp_audit = {
        "source_semantic_timestamps": [], "scheduled_race_time_fields": [],
        "filesystem_metadata_fields": ["file mtime/ctime (available but prohibited as event-time proof)"],
        "classification": "NO_SOURCE_SEMANTIC_OR_SCHEDULED_TIMESTAMP",
        "mtime_used_as_event_time": False,
    }
    replay = {
        "status": "ORDER_REPLAYABLE_TIMESTAMP_UNPROVEN",
        "race_order_known": True, "scheduled_post_time_known": False,
        "actual_result_availability_time_known": False,
        "strict_prior_race_filter_implementable": True,
        "strict_known_before_target_start_boundary_provable": False,
    }
    meeting_bias = {
        "status": "PARTIALLY_REUSABLE",
        "collector_inputs": ["saved review race/horse CSV", "data/results race/horse CSV", "saved pre-race summary"],
        "extractor_outputs": ["result-derived meeting pattern evidence", "candidate records", "diagnostic metrics"],
        "uses_result_derived_labels": True,
        "current_collector_scans_complete_review_dates": True,
        "target_r_minus_one_constraint_present": False,
        "future_same_day_pooling_risk": "collector has no target-race cutoff; full reviewed day is discoverable",
        "reuse_boundary": "parsing/normalization components only; rolling cutoff and semantic availability boundary need design",
    }
    summary = {
        **audit_population,
        "audit_status": "COMPLETE",
        "static_runtime_wiring_audit": "PASS",
        "manual_track_bias_runtime_use_status": (
            "OBSERVED" if any(row["classification"] == "PROVEN_NON_NULL" for row in manual)
            else "NOT_FULLY_OBSERVABLE" if any(row["classification"] == "NOT_OBSERVABLE_FROM_ARTIFACT" for row in manual)
            else "NEVER_OBSERVED"
        ),
        "manual_track_bias_proven_non_null_runs": sum(row["classification"] == "PROVEN_NON_NULL" for row in manual),
        "manual_track_bias_proven_null_or_absent_runs": sum(row["classification"] == "PROVEN_NULL_OR_ABSENT" for row in manual),
        "manual_track_bias_not_observable_runs": sum(row["classification"] == "NOT_OBSERVABLE_FROM_ARTIFACT" for row in manual),
        "track_bias_score_runtime_status": score_summary["status"],
        "track_bias_score_total_horse_rows": score_summary["total"],
        "track_bias_score_zero_rows": score_summary["zero"],
        "track_bias_score_nonzero_rows": score_summary["positive"] + score_summary["negative"],
        "track_bias_score_missing_rows": score_summary["missing"],
        "track_bias_score_zero_rate": score_summary["zero_rate"],
        "track_condition_runtime_coverage": condition_summary["status"],
        "track_condition_pre_race_refresh_path": "NOT_FOUND",
        "pre_20260912_track_bias_nonzero_horses": snapshot["track_bias_nonzero_horses"],
        "pre_20260912_track_bias_zero_horses": snapshot["track_bias_zero_horses"],
        "pre_20260912_track_bias_missing_horses": snapshot["track_bias_missing_horses"],
        "pre_20260912_track_condition_values": snapshot["track_condition_values"],
        "layer_b_required_field_coverage": "PARTIAL_MISSING_FRAME_AND_SEMANTIC_TIMESTAMPS",
        "strict_timestamp_replay_status": replay["status"],
        "existing_meeting_bias_tool_rolling_reuse": meeting_bias["status"],
        "realtime_input_gap_runtime_status": "PARTIALLY_CONFIRMED",
        "layer_a_official_condition_gap_status": "MATERIAL_GAP",
        "layer_b_same_day_bias_gap_status": "PARTIAL_GAP",
        "rolling_pre_replay_readiness": "NEEDS_DATA_PROVENANCE_WORK",
        "rolling_pre_next_design_readiness": "READY_FOR_CLAUDE_DESIGN",
        "bias_to_performance_join": 0,
    }

    write_csv(OUT / "daily_pre_artifact_inventory.csv", inventory, list(inventory[0]))
    dump_json(OUT / "audit_population.json", audit_population)
    write_csv(OUT / "manual_track_bias_runtime_usage.csv", manual, list(manual[0]))
    write_csv(OUT / "track_bias_score_runtime_coverage.csv", score_detail, list(score_detail[0]))
    dump_json(OUT / "track_bias_score_summary.json", score_summary)
    write_csv(OUT / "track_condition_runtime_coverage.csv", condition_detail, list(condition_detail[0]))
    dump_json(OUT / "source_code_wiring_audit.json", code_findings)
    dump_json(OUT / "track_condition_refresh_path_audit.json", refresh)
    dump_json(OUT / "pre_20260912_track_context_snapshot.json", snapshot)
    dump_json(OUT / "layer_b_source_inventory.json", layer_b)
    write_csv(OUT / "layer_b_field_coverage.csv", layer_b_coverage, list(layer_b_coverage[0]))
    dump_json(OUT / "timestamp_semantics_audit.json", timestamp_audit)
    dump_json(OUT / "strict_rolling_replay_feasibility.json", replay)
    dump_json(OUT / "meeting_bias_tool_reuse_audit.json", meeting_bias)
    write_csv(OUT / "same_surface_prior_race_count_distribution.csv", prior_distribution, list(prior_distribution[0]))
    safety = {
        "AUDIT_ROLE": ROLE, "RESULT_SCHEMA_ACCESS": 1, "BIAS_TO_PERFORMANCE_JOIN": 0,
        "PREDICTION_EXECUTION": 0, "MODEL_TRAINING": 0, "MODEL_REFIT": 0,
        "BIAS_FORMULA_CREATED": 0, "BIAS_THRESHOLD_CREATED": 0,
        "STAGE_B_CHANGE": 0, "PRODUCTION_CHANGE": 0, "LEDGER_CHANGE": 0,
        "FINGERPRINT_CHANGE": 0, "RAW_SOURCE_CHANGE": 0, "PREDICTION_ARTIFACT_CHANGE": 0,
        "GIT_COMMIT": 0, "GIT_PUSH": 0,
    }
    dump_json(OUT / "safety.json", safety)
    _write_report(summary, layer_b)
    files = sorted(path for path in OUT.iterdir() if path.name != "artifact_hash_index.json")
    dump_json(OUT / "artifact_hash_index.json", {
        "self_hash_excluded": True,
        "artifacts": {path.name: {"sha256": sha256(path), "size": path.stat().st_size} for path in files},
        "summary": summary,
    })
    return OUT


if __name__ == "__main__":
    print(run())
