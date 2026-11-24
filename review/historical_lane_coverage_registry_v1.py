"""Phase 0 historical coverage inventory. No Result import or Result path access."""
from __future__ import annotations

import hashlib
import csv
import json
import re
from collections import Counter, defaultdict
from datetime import datetime
from functools import lru_cache
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SOURCE_MAP = ROOT / "docs/KeibaAI_HISTORICAL_LANE_SOURCE_MAP_V1.json"
LANES = ("CURRENT", "EXP024", "CURRENT_RANK1", "PL_JOCKEY", "A_NEW", "E1", "INDEPENDENT_V5", "B1")
FILE_RE = re.compile(r"^(DG|DE|DS)(\d{6})(v\d+)?\.CSV$", re.IGNORECASE)
PREDICTION_FILENAMES = frozenset(("prediction_manifest.json", "selection.json", "pre_selection.json", "selection_manifest.json", "runtime_pre_only_output.json", "pre_freeze.json", "current_pre.json", "prediction_matrix.csv"))


class CoverageStop(RuntimeError):
    pass


def sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def read_json(path: Path):
    return json.loads(path.read_text(encoding="utf-8"))


def read_prediction(path: Path) -> dict:
    if path.name != "prediction_matrix.csv":
        return read_json(path)
    allowed = {"date", "venue", "race_number", "race_id", "CURRENT", "INDEPENDENT_V5",
               "TRACKCONDITION_SEMANTIC", "DAILY_V5_SAME_VOLUME", "FORMAL_V5", "FORMAL_V6"}
    races = []
    with path.open(encoding="utf-8-sig", newline="") as stream:
        reader = csv.DictReader(stream)
        if not reader.fieldnames or not {"date", "race_id", "INDEPENDENT_V5"} <= set(reader.fieldnames) or set(reader.fieldnames) - allowed:
            raise CoverageStop("STOP_PREDICTION_MATRIX_COLUMNS")
        for row in reader:
            cell = row["INDEPENDENT_V5"].strip()
            selected = []
            if cell not in ("NO_BUY", "OUT_OF_SCOPE"):
                parts = [part.strip() for part in cell.split(",")]
                for part in parts:
                    match = re.fullmatch(r"#(\d+)\s+.+", part)
                    if not match:
                        raise CoverageStop("STOP_PREDICTION_MATRIX_SELECTION")
                    selected.append({"horse_number": int(match.group(1))})
            races.append({"date": row["date"], "race_id": row["race_id"], "selected_horses": selected})
    return {"races": races, "source_format": "SAVED_PRE_COMPARISON_MATRIX_INDEPENDENT_V5_ONLY"}


def safe_prediction_path(path: Path) -> Path:
    """Reject a misdirected source before any file open, especially POST/Result."""
    resolved = path.resolve()
    parts = {part.lower() for part in resolved.parts}
    if (resolved.name not in PREDICTION_FILENAMES or
            parts & {"result", "results", "daily_result_list", "post", "formal_post", "result_join"} or
            any("post" in part.lower() or "result" in part.lower() for part in resolved.parts[-3:-1])):
        raise CoverageStop("STOP_NON_PREDICTION_SOURCE_PATH:" + str(path))
    return resolved


def load_source_map(path: Path = SOURCE_MAP) -> dict:
    config = read_json(path)
    if config.get("schema_version") != "HISTORICAL_LANE_SOURCE_MAP_V1" or set(config.get("lanes", {})) != set(LANES) or config.get("panel_evidence_credit") != 0:
        raise CoverageStop("STOP_SOURCE_MAP_AUTHORITY")
    return config


def discover_dates(input_root: Path) -> dict[str, dict[str, Path]]:
    """Union of dated DG/DE/DS files; a missing member never hides a date."""
    versions: dict[str, dict[str, dict[str, Path]]] = defaultdict(lambda: defaultdict(dict))
    if not input_root.is_dir():
        raise CoverageStop("STOP_INPUT_ROOT_MISSING")
    for path in input_root.iterdir():
        match = FILE_RE.fullmatch(path.name) if path.is_file() else None
        if not match:
            if path.is_file() and re.match(r"^(DG|DE|DS)\d{6}", path.name, re.IGNORECASE):
                raise CoverageStop("STOP_UNKNOWN_INPUT_FILENAME:" + path.name)
            continue
        kind, short, version = match.group(1).upper(), match.group(2), match.group(3) or "base"
        date = "20" + short
        try:
            datetime.strptime(date, "%Y%m%d")
        except ValueError as error:
            raise CoverageStop("STOP_INVALID_SOURCE_DATE:" + path.name) from error
        if version in versions[date][kind]:
            raise CoverageStop("STOP_DUPLICATE_SOURCE_VERSION:" + date + ":" + kind)
        versions[date][kind][version] = path
    found = {}
    for date, kinds in versions.items():
        found[date] = {}
        for kind, candidates in kinds.items():
            if date == "20260418":
                if "v2" not in candidates:
                    raise CoverageStop("STOP_APPROVED_V2_MISSING:" + kind)
                found[date][kind] = candidates["v2"]
            elif set(candidates) == {"base"}:
                found[date][kind] = candidates["base"]
            else:
                raise CoverageStop("STOP_UNKNOWN_INPUT_VERSION:" + date + ":" + kind)
    return dict(sorted(found.items()))


def parse_day_default(date: str, files: dict[str, Path]) -> tuple[list[dict], str | None]:
    """Existing adapter first; validated DG/DE inventory fallback on input errors."""
    from review.target_bulk_prediction_input_adapter_v1 import TargetBulkPredictionInputAdapterV1

    adapter = TargetBulkPredictionInputAdapterV1()
    if set(files) == {"DG", "DE", "DS"}:
        try:
            compatibility = ("HUMAN_APPROVED_20260906_HANSHIN11R" if date == "20260906" else None)
            bundle = adapter.load(files["DG"], files["DE"], files["DS"], compatibility_exception=compatibility)
            if bundle.date != date:
                raise CoverageStop("STOP_ADAPTER_DATE_MISMATCH:" + date)
            return ([{"race_id": rid, "horse_count": len(race.today_entries)}
                     for rid, race in bundle.races.items()], None)
        except Exception as error:
            adapter_error = type(error).__name__ + ":" + str(error)
    else:
        adapter_error = "INPUT_TRIPLET_MISSING:" + ",".join(sorted(set(("DG", "DE", "DS"))-set(files)))
    inventories: dict[str, dict[str, int | None]] = {}
    for kind in ("DG", "DE"):
        if kind not in files:
            continue
        try:
            rows, _ = adapter._read_fixed(files[kind], kind)
            if kind == "DG":
                parsed = adapter._validate_dg(rows, date)
                inventories[kind] = {adapter._race_id(date, venue, number): None for venue, number in parsed}
            else:
                parsed, _, _ = adapter._validate_de(rows, date)
                inventories[kind] = {adapter._race_id(date, venue, number): len(horses)
                                     for (venue, number), horses in parsed.items()}
        except Exception:
            continue
    if not inventories:
        raise CoverageStop("STOP_RACE_INVENTORY_UNVERIFIED:" + date + ":" + adapter_error)
    ids = set().union(*(set(v) for v in inventories.values()))
    if not ids:
        raise CoverageStop("STOP_EMPTY_RACE_INVENTORY:" + date)
    races = [{"race_id": rid, "horse_count": inventories.get("DE", {}).get(rid)} for rid in sorted(ids)]
    return races, adapter_error


def period_role(date: str, config: dict) -> tuple[str, str]:
    matches = [item for item in config["period_roles"] if item["start"] <= date <= item["end"]]
    if len(matches) > 1:
        raise CoverageStop("STOP_OVERLAPPING_PERIOD_RULES:" + date)
    return (matches[0]["role"], matches[0]["result_policy"]) if matches else (config["default_period_role"], "HOLD")


def _artifact_races(lane: str, path: Path, value: dict, *, formal_lanes: dict | None, root: Path) -> set[str] | None:
    if path.name == "runtime_pre_only_output.json":
        dated = {row["race_id"] for row in value.get("race_index", [])}
        if lane == "CURRENT_RANK1":
            return {row["race_id"] for row in value.get("generated_rows", [])
                    if row.get("values", {}).get("race_state") == "PLAY_UNCONVERGED_4PLUS"} & dated
        return dated
    if path.name == "pre_freeze.json":
        branch = "A0" if lane == "PL_JOCKEY" else "A_new"
        predictions = value.get("predictions", {}).get(branch)
        return {row["race_id"] for row in predictions} if isinstance(predictions, list) else None
    if path.name == "current_pre.json" and lane == "CURRENT":
        return {row["race_id"] for row in value.get("predictions", [])}
    if lane == "CURRENT":
        index = path.with_name("race_index.json")
        return {item["race_id"] for item in read_json(index)["race_index"]} if index.is_file() else None
    if lane in ("EXP024", "PL_JOCKEY", "A_NEW", "INDEPENDENT_V5"):
        return {item["race_id"] for item in value.get("races", [])}
    if lane == "CURRENT_RANK1":
        selections = value.get("selections")
        if not isinstance(selections, list) or value.get("eligible_races") != len(selections):
            return None
        ids = [item["race_id"] for item in selections]
        return set(ids) if len(ids) == len(set(ids)) else None
    if lane == "E1":
        eligible = value.get("eligible_races")
        return set(eligible) if isinstance(eligible, list) and all(isinstance(x, str) for x in eligible) else None
    if lane == "B1" and formal_lanes and "PL_JOCKEY" in formal_lanes:
        upstream = formal_lanes["PL_JOCKEY"]
        upstream_path = Path(upstream["selection_path"])
        if not upstream_path.is_absolute():
            upstream_path = root / upstream_path
        if upstream_path.is_file() and value.get("pl_jockey_selection_sha256") == sha(upstream_path):
            upstream_value = read_json(upstream_path)
            assert_prediction_result_free(upstream_value)
            return {item["race_id"] for item in upstream_value.get("races", [])}
    return None


def normalize_model_date(value: object) -> str | None:
    if not isinstance(value, str):
        return None
    compact = value.replace("-", "")
    if not re.fullmatch(r"20\d{6}", compact):
        return None
    try:
        datetime.strptime(compact, "%Y%m%d")
    except ValueError:
        return None
    return compact


RESULT_LABEL_KEYS = frozenset(("actual_top3", "valid_result", "finish", "finish_position", "actual_finish", "odds", "popularity"))


def assert_prediction_result_free(value: object) -> None:
    """Allow PRE metadata, but reject horse-level labels and market/Result inputs."""
    if isinstance(value, dict):
        for key, nested in value.items():
            if key.lower() in RESULT_LABEL_KEYS:
                raise CoverageStop("STOP_RESULT_FIELD_IN_PREDICTION:" + key)
            assert_prediction_result_free(nested)
    elif isinstance(value, list):
        for nested in value:
            assert_prediction_result_free(nested)


@lru_cache(maxsize=4)
def run_c_date_index(root_text: str, pattern: str) -> dict[str, Path]:
    root = Path(root_text)
    indexed = {}
    for path in root.glob(pattern):
        path = safe_prediction_path(path)
        value = read_json(path)
        assert_prediction_result_free(value)
        for row in value.get("race_index", []):
            date = row.get("date")
            if date in indexed and indexed[date] != path:
                raise CoverageStop("STOP_RUN_C_DATE_AMBIGUOUS:" + str(date))
            indexed[date] = path
    return indexed


def _source_for_lane(root: Path, date: str, lane: str, config: dict, formal: dict | None) -> tuple[Path | None, str | None, str]:
    if formal and lane != "B1" and lane in formal.get("lanes", {}):
        entry = formal["lanes"][lane]
        path = Path(entry["selection_path"])
        path = path if path.is_absolute() else root / path
        return safe_prediction_path(path), entry.get("selection_sha256"), "FORMAL_PRE_SOURCE"
    candidates = [root / pattern.format(date=date) for pattern in config["lanes"][lane]["patterns"]]
    candidates = [safe_prediction_path(path) for path in candidates]
    found = [p for p in candidates if p.is_file()]
    if len(found) > 1:
        if lane == "INDEPENDENT_V5" and len(found) == 2 and {path.name for path in found} == {"selection_manifest.json", "prediction_matrix.csv"}:
            found = [next(path for path in found if path.name == "selection_manifest.json")]
        else:
            return None, None, "AMBIGUOUS_SAVED_SOURCES"
    if found:
        role = "NON_EVIDENTIAL_RECOVERY_SOURCE" if "non_evidential_recovery" in str(found[0]).lower() else "SAVED_SOURCE_ROLE_UNVERIFIED"
        return found[0], None, role
    historical = config.get("historical_sources", {})
    if lane == "CURRENT" and date.startswith("202512") and "december_one_shot_current" in historical:
        december = safe_prediction_path(root / historical["december_one_shot_current"])
        if december.is_file():
            return december, None, "DECEMBER_CONSUMED_ONE_SHOT_PRE"
    if lane in ("CURRENT", "CURRENT_RANK1") and "run_c_shards" in historical:
        path = run_c_date_index(str(root.resolve()), historical["run_c_shards"]).get(date)
        if path:
            return path, None, "SAVED_RUN_C_PRE_ONLY"
    if lane in ("PL_JOCKEY", "A_NEW") and "walk_forward_fold" in historical and "20260301" <= date <= "20260930":
        fold = safe_prediction_path(Path(historical["walk_forward_fold"].replace("{month}", date[:6])))
        if fold.is_file():
            manifest_path = fold.with_name("freeze_manifest.json")
            if not manifest_path.is_file():
                raise CoverageStop("STOP_FOLD_FREEZE_MANIFEST_MISSING:" + date[:6])
            manifest = read_json(manifest_path)
            if (manifest.get("month") != date[:6] or
                    manifest.get("status") != "PRE_FROZEN_BEFORE_SAME_MONTH_RESULT_ACCESS" or
                    manifest.get("same_month_result_access_before_freeze") != 0):
                raise CoverageStop("STOP_FOLD_FREEZE_AUTHORITY_INVALID:" + date[:6])
            return fold, manifest.get("pre_freeze_sha256"), "WALK_FORWARD_FOLD_PRE_ONLY"
    if lane == "INDEPENDENT_V5" and "daily_v5_distinct_variant" in historical:
        variant = root / historical["daily_v5_distinct_variant"].format(date=date)
        if variant.is_file():
            return None, None, "RELATED_DAILY_V5_VARIANT_NOT_INDEPENDENT_V5"
    if lane == "INDEPENDENT_V5" and date.startswith("202512") and "december_one_shot_v5" in historical:
        variant = root / historical["december_one_shot_v5"]
        if variant.is_file():
            return None, None, "RELATED_DECEMBER_V5_VARIANT_NOT_INDEPENDENT_V5"
    return None, None, "PREDICTION_NOT_SAVED"


def build_registry(input_root: Path, root: Path, config: dict, *, parse_day=parse_day_default) -> dict:
    """Pure inventory result; caller decides whether/when to write Phase 0."""
    discovered = discover_dates(input_root)
    rows, days, issues = [], [], []
    seen = set()
    for date, files in discovered.items():
        override = config.get("approved_input_version", {}).get(date)
        if override:
            authority = root / override["authority_path"]
            if not authority.is_file() or sha(authority) != override["authority_sha256"]:
                raise CoverageStop("STOP_APPROVED_INPUT_AUTHORITY_DRIFT:" + date)
            source_map = read_json(authority).get("new", {}).get("sources", {})
            for kind, path in files.items():
                if Path(source_map.get(kind, {}).get("path", "")).name != path.name or source_map[kind]["sha256"] != sha(path):
                    raise CoverageStop("STOP_APPROVED_INPUT_SHA_DRIFT:" + date + ":" + kind)
        races, input_error = parse_day(date, files)
        exception = config.get("approved_race_exceptions", {}).get(date)
        exception_applies = False
        if exception and input_error and exception.get("reason_code") and exception["reason_code"] in input_error:
            authority = root / exception["authority_path"]
            if not authority.is_file() or sha(authority) != exception["authority_sha256"]:
                raise CoverageStop("STOP_APPROVED_RACE_EXCEPTION_AUTHORITY_DRIFT:" + date)
            attested = read_json(authority)
            if attested.get("target_race", {}).get("race_id") != exception["race_id"]:
                raise CoverageStop("STOP_APPROVED_RACE_EXCEPTION_SCOPE_DRIFT:" + date)
            exception_applies = True
        ids = [item["race_id"] for item in races]
        if len(ids) != len(set(ids)) or any(not rid.startswith("race_" + date + "_") for rid in ids):
            raise CoverageStop("STOP_DUPLICATE_OR_INVALID_RACE:" + date)
        role, result_policy = period_role(date, config)
        hashes = {kind: sha(path) for kind, path in files.items()}
        summary_path = root / config["formal_summary_pattern"].format(date=date)
        formal = read_json(summary_path) if summary_path.is_file() else None
        if formal and (formal.get("date") != date or formal.get("status") != "COMPLETE"):
            raise CoverageStop("STOP_FORMAL_SUMMARY_INVALID:" + date)
        source_cache = {}
        for race in races:
            rid = race["race_id"]
            race_input_error = (exception["reason_code"] if rid == exception["race_id"] else None) if exception_applies else input_error
            if rid in seen:
                raise CoverageStop("STOP_DUPLICATE_RACE_ID:" + rid)
            seen.add(rid)
            for lane in LANES:
                spec = config["lanes"][lane]
                if lane not in source_cache:
                    path, expected_sha, source_role = _source_for_lane(root, date, lane, config, formal)
                    value = None
                    member_races = None
                    actual_sha = None
                    parse_reason = None
                    if path and path.is_file():
                        try:
                            actual_sha = sha(path)
                            if expected_sha is not None and expected_sha != actual_sha:
                                parse_reason = "PREDICTION_SHA_MISMATCH"
                            else:
                                value = read_prediction(path)
                                assert_prediction_result_free(value)
                                member_races = _artifact_races(lane, path, value, formal_lanes=formal.get("lanes") if formal else None, root=root)
                        except (OSError, ValueError, KeyError, TypeError) as error:
                            parse_reason = "PREDICTION_PARSE_ERROR:" + type(error).__name__
                    source_cache[lane] = (path, source_role, value, member_races, actual_sha, parse_reason)
                path, source_role, value, member_races, actual_sha, parse_reason = source_cache[lane]
                reason = None
                model_sha = None
                cutoff = None
                training_start = None
                if race_input_error:
                    reason = "INPUT_INVALID_OR_INCOMPLETE"
                elif lane == "B1" and date < spec["effective_from"]:
                    reason = "BEFORE_B1_EFFECTIVE_FROM"
                elif source_role == "AMBIGUOUS_SAVED_SOURCES":
                    reason = source_role
                elif path is None:
                    reason = source_role if source_role.startswith("RELATED_") else "DERIVATION_PENDING_APPROVAL" if lane in ("E1", "B1") and "20260301" <= date <= "20260913" else "MODEL_NOT_AVAILABLE" if lane == "INDEPENDENT_V5" else "PREDICTION_NOT_SAVED"
                elif not path.is_file():
                    reason = "PREDICTION_SOURCE_MISSING"
                elif parse_reason:
                    reason = parse_reason
                elif member_races is None:
                    reason = "RACE_SET_UNVERIFIED"
                elif rid not in member_races:
                    reason = "NOT_APPLICABLE_BY_LANE_DESIGN" if lane == "CURRENT_RANK1" else "RACE_NOT_IN_SAVED_PREDICTION"
                if value:
                    field = spec.get("model_sha_field")
                    model_sha = value.get(field) if field else None
                    cutoff = next((normalize_model_date(value.get(key)) for key in ("training_cutoff", "training_end_date", "training_end") if normalize_model_date(value.get(key))), None)
                    training_start = next((normalize_model_date(value.get(key)) for key in ("training_start", "training_start_date") if normalize_model_date(value.get(key))), None)
                if source_role == "WALK_FORWARD_FOLD_PRE_ONLY" and value:
                    training_range = value.get("training_range")
                    if isinstance(training_range, list) and len(training_range) == 2:
                        training_start, cutoff = map(normalize_model_date, training_range)
                overlap = ("UNKNOWN" if cutoff is None else
                           "WALK_FORWARD_FOLD_OOS" if source_role == "WALK_FORWARD_FOLD_PRE_ONLY" and date > cutoff else
                           "TIME_REVERSED" if training_start and date < training_start else
                           "IN_SAMPLE" if training_start and date <= cutoff else
                           "TRAINING_PERIOD_UNVERIFIED" if date <= cutoff else "AFTER_CUTOFF")
                evidence = "FORMAL_PRE_SOURCE_ORIGINAL_PROTOCOL_RECHECK_REQUIRED" if source_role == "FORMAL_PRE_SOURCE" else "ANALYSIS_OR_HISTORICAL_UNVERIFIED"
                if role == "CONSUMED_HOLDOUT":
                    evidence = "CONSUMED_HOLDOUT_NO_NEW_CREDIT"
                if overlap in ("TIME_REVERSED", "IN_SAMPLE", "TRAINING_PERIOD_UNVERIFIED"):
                    evidence = overlap + "_NON_EVIDENTIAL"
                technical = reason is None
                rows.append({"date": date, "race_id": rid, "venue": rid.split("_")[2], "race_number": int(rid.rsplit("_", 1)[1][:-1]),
                             "horse_count": race.get("horse_count"), "lane": lane,
                             "input_present": {kind: kind in files for kind in ("DG", "DE", "DS")},
                             "input_sha256": hashes, "input_validation": "PASS_WITH_APPROVED_RACE_EXCEPTION" if exception_applies and not race_input_error else "PASS" if not race_input_error else race_input_error,
                             "approved_race_exception_sha256": exception["authority_sha256"] if exception_applies else None,
                             "prediction_exists": bool(path and path.is_file()), "prediction_path": str(path) if path else None,
                             "prediction_sha256": actual_sha,
                             "model_version": value.get("model_version") if value else None, "model_sha256": model_sha,
                             "training_start": training_start or "UNKNOWN", "training_cutoff": cutoff or "UNKNOWN", "training_overlap": overlap,
                             "technical_predictable": technical, "technical_reason": reason,
                             "prediction_reproducibility": "SAVED_SELECTION_VERIFIABLE_ONLY" if technical else "UNVERIFIED",
                             "source_role": source_role, "period_role": role, "result_policy": result_policy,
                             "evidence_role": evidence, "new_panel_evidence_credit": 0})
        days.append({"date": date, "race_count": len(races), "horse_count": sum(item["horse_count"] or 0 for item in races),
                     "horse_count_complete": all(item["horse_count"] is not None for item in races),
                     "input_sha256": hashes, "input_issue": input_error})
        if input_error:
            issues.append({"date": date, "reason": input_error})
    if len(rows) != len(seen) * len(LANES):
        raise CoverageStop("STOP_COVERAGE_ROW_COUNT")
    by_lane = {lane: {row["race_id"] for row in rows if row["lane"] == lane and row["technical_predictable"]}
               for lane in LANES}
    comparison_pairs = (("CURRENT", "PL_JOCKEY"), ("CURRENT", "A_NEW"),
                        ("PL_JOCKEY", "EXP024"), ("E1", "B1"),
                        ("E1", "PL_JOCKEY"))
    reference = config.get("initial_reference_not_a_limit", {})
    measured = {"dates": len(days), "races": len(seen), "horses": sum(day["horse_count"] for day in days)}
    return {"schema_version": "HISTORICAL_LANE_COVERAGE_REGISTRY_V1", "dates": days, "rows": rows,
            "issues": issues, "counts": {"dates": len(days), "races": len(seen), "horses_known": sum(day["horse_count"] for day in days),
                                   "race_lane_rows": len(rows), "technical_by_lane": dict(Counter(row["lane"] for row in rows if row["technical_predictable"])),
                                   "common_technical_by_pair": {a + "__" + b: len(by_lane[a] & by_lane[b]) for a, b in comparison_pairs},
                                   "reason_counts": dict(Counter(row["technical_reason"] for row in rows if row["technical_reason"]))},
            "initial_reference_comparison_not_a_gate": {key: {"reference": reference.get(key), "measured": measured[key],
                                                          "delta": measured[key] - reference[key] if isinstance(reference.get(key), int) else None}
                                                       for key in measured},
            "source_map_config_sha256": hashlib.sha256(json.dumps(config, sort_keys=True, ensure_ascii=False).encode("utf-8")).hexdigest(),
            "registry_code_sha256": sha(Path(__file__)),
            "independent_evidence_eligible_races": "UNVERIFIED_BY_THIS_REGISTRY",
            "new_panel_evidence_credit": 0}


def require_human_phase_approval(approval: dict, phase: int) -> None:
    if (approval.get("human_approved") is not True or approval.get("phase") != phase or
            not approval.get("approval_id") or not approval.get("approved_at")):
        raise CoverageStop("STOP_HUMAN_PHASE_APPROVAL_REQUIRED")


def write_phase0(registry: dict, output: Path, approval: dict) -> Path:
    require_human_phase_approval(approval, 0)
    if output.exists():
        raise CoverageStop("STOP_OUTPUT_EXISTS")
    output.parent.mkdir(parents=True, exist_ok=True)
    with output.open("x", encoding="utf-8") as stream:
        json.dump({"approval": approval, "registry": registry}, stream, ensure_ascii=False, sort_keys=True)
        stream.write("\n")
    return output
