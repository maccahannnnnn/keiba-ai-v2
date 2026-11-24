"""Existing-source eight-lane combination orchestration; no new predictor.

Phase 1 reads only saved PRE selections. Phase 2 is a separately approved
Result join and is deliberately never called by the Phase 1 entrypoint.
"""
from __future__ import annotations

import itertools
import json
from collections import defaultdict
from pathlib import Path

from review.historical_lane_coverage_registry_v1 import (
    CoverageStop, LANES, assert_prediction_result_free, read_json, read_prediction,
    require_human_phase_approval, safe_prediction_path, sha,
)
from review.historical_seven_lane_development_panel_v1 import _selection_keys, official_labels

ROOT = Path(__file__).resolve().parents[1]
SPEC = ROOT / "docs/KeibaAI_HISTORICAL_LANE_COMBINATION_VALIDATION_V1.json"
PAIRS = tuple(itertools.combinations(LANES, 2))


def block_for_date(date: str, spec: dict) -> str | None:
    for block, rule in spec["blocks"].items():
        if date in rule.get("dates", []) or (rule.get("start", "99999999") <= date <= rule.get("end", "00000000")):
            return block
    return None


def _diagnostic_sources(root: Path, spec: dict) -> dict[str, tuple[dict, Path, str]]:
    folder = root / spec["diagnostic_pre_root"]
    freeze = read_json(folder / spec["diagnostic_pre_freeze"])
    if freeze.get("result_access_before_freeze") != 0 or freeze.get("new_inference") is not False:
        raise CoverageStop("STOP_DIAGNOSTIC_PRE_FREEZE_AUTHORITY")
    sources = {}
    for block, filename, hash_key in (("H1", spec["diagnostic_a"], "a_pre_selection_sha256"),
                                      ("H2", spec["diagnostic_b"], "b_pre_selection_sha256")):
        path = folder / filename
        if sha(path) != freeze.get(hash_key):
            raise CoverageStop("STOP_DIAGNOSTIC_PRE_SHA:" + block)
        value = read_json(path)
        assert_prediction_result_free(value)
        if value.get("result_access_during_selection") != 0:
            raise CoverageStop("STOP_DIAGNOSTIC_RESULT_ACCESS:" + block)
        sources[block] = (value, path, sha(path))
    return sources


def _score_map(lane: str, path: Path, value: dict, date: str) -> dict[tuple[str, int], float]:
    rows = []
    if path.name == "pre_freeze.json" and lane in ("PL_JOCKEY", "A_NEW"):
        branch = "A0" if lane == "PL_JOCKEY" else "A_new"
        rows = value.get("selections", {}).get(branch, [])
    elif lane == "PL_JOCKEY" and isinstance(value.get("races"), list):
        rows = [{"race_id": race["race_id"], "horse_number": horse["horse_number"],
                 "p_top3": horse.get("candidate_p_top3")}
                for race in value["races"] for horse in race.get("horses", [])]
    elif lane in ("E1", "B1"):
        rows = value.get("selected_horses", [])
    result = {}
    for row in rows:
        rid = row.get("race_id")
        if not isinstance(rid, str) or not rid.startswith("race_" + date + "_"):
            continue
        score = next((row[key] for key in ("p_top3", "candidate_p_top3", "p", "predicted_top3_probability")
                      if isinstance(row.get(key), (float, int)) and not isinstance(row.get(key), bool)), None)
        if score is not None:
            result[rid, int(row["horse_number"])] = float(score)
    return result


def _source_version(path: Path, row: dict) -> tuple[str, str | None]:
    if path.name == "pre_freeze.json":
        return "fold_" + path.parent.name.removeprefix("fold_"), row.get("model_sha256")
    return row.get("model_version") or "UNKNOWN", row.get("model_sha256")


def _load_registry(path: Path) -> dict:
    value = read_json(path)
    require_human_phase_approval(value.get("approval", {}), 0)
    registry = value["registry"]
    if registry.get("schema_version") != "HISTORICAL_LANE_COVERAGE_REGISTRY_V1" or registry.get("new_panel_evidence_credit") != 0:
        raise CoverageStop("STOP_REGISTRY_ROLE")
    return registry


def prepare_phase1(registry_path: Path, approval: dict, output: Path, *, root: Path = ROOT,
                   spec_path: Path = SPEC) -> dict:
    """Freeze only saved, verified PRE identities; never train or read Result."""
    require_human_phase_approval(approval, 1)
    if output.exists():
        raise CoverageStop("STOP_OUTPUT_EXISTS")
    spec = read_json(spec_path)
    if spec.get("schema_version") != "HISTORICAL_LANE_COMBINATION_VALIDATION_V1" or spec.get("evidence_credit") != 0:
        raise CoverageStop("STOP_SPEC_ROLE")
    registry = _load_registry(registry_path)
    source_by_day_lane = defaultdict(list)
    population = defaultdict(set)
    for row in registry["rows"]:
        block = block_for_date(row["date"], spec)
        if not block:
            continue
        if row["date"] in spec["hypothesis_discovery_dates_excluded"]:
            raise CoverageStop("STOP_DISCOVERY_DATE_IN_VALIDATION")
        population[block].add(row["race_id"])
        source_by_day_lane[row["date"], row["lane"]].append(row)
    diagnostic = _diagnostic_sources(root, spec)
    selected, issues, sources = [], [], []
    for (date, lane), rows in sorted(source_by_day_lane.items()):
        block = block_for_date(date, spec)
        override = lane in ("EXP024", "E1") and block in ("H1", "H2")
        if override:
            value, path, digest = diagnostic[block]
            eligible_dates = value.get("dates" if block == "H1" else "usable_dates", [])
            if date not in eligible_dates:
                issues.append({"date": date, "block": block, "lane": lane,
                               "reason": "DIAGNOSTIC_DATE_NOT_IN_FROZEN_SCOPE"})
                continue
            branch = spec["diagnostic_a_lanes" if block == "H1" else "diagnostic_b_lanes"][lane]
            raw = value[branch]
            choices = [(item["race_id"], int(item["horse_number"]), item.get("p"))
                       for item in raw if item.get("date") == date]
            source_role, version, model_sha = "FROZEN_DIAGNOSTIC_" + block, "DIAGNOSTIC_" + block, value.get("model_sha256")
        else:
            usable = [row for row in rows if row["technical_predictable"]]
            if not usable:
                issues.append({"date": date, "block": block, "lane": lane,
                               "reason": "DERIVATION_PENDING_APPROVAL" if lane == "B1" else rows[0].get("technical_reason") or "SOURCE_UNAVAILABLE"})
                continue
            first = usable[0]
            if any(row["prediction_path"] != first["prediction_path"] or row["prediction_sha256"] != first["prediction_sha256"] for row in usable):
                raise CoverageStop("STOP_SOURCE_MIX_WITHIN_DAY_LANE")
            path = safe_prediction_path(Path(first["prediction_path"]))
            digest = first["prediction_sha256"]
            if not path.is_file() or sha(path) != digest:
                raise CoverageStop("STOP_SOURCE_SHA_DRIFT:" + date + ":" + lane)
            value = read_prediction(path)
            assert_prediction_result_free(value)
            keys = _selection_keys(lane, path, value, date)
            scores = _score_map(lane, path, value, date)
            choices = [(rid, number, scores.get((rid, number))) for rid, number in sorted(keys)]
            source_role = first["source_role"]
            version, model_sha = _source_version(path, first)
        allowed = {row["race_id"] for row in rows}
        if len(choices) != len({(rid, number) for rid, number, _ in choices}) or any(rid not in allowed or number <= 0 for rid, number, _ in choices):
            raise CoverageStop("STOP_SELECTION_IDENTITY:" + date + ":" + lane)
        row_by_race = {row["race_id"]: row for row in rows}
        sources.append({"date": date, "block": block, "lane": lane, "path": str(path),
                        "sha256": digest, "source_role": source_role,
                        "model_version": version, "model_sha256": model_sha or "UNKNOWN"})
        for rid, number, score in choices:
            source_row = row_by_race[rid]
            input_ok = source_row.get("input_validation", "PASS") in ("PASS", "PASS_WITH_APPROVED_RACE_EXCEPTION")
            eligibility = "TECHNICAL_SOURCE_PASS" if input_ok and (override or source_row["technical_predictable"]) else "INPUT_OR_SOURCE_UNVERIFIED"
            if eligibility != "TECHNICAL_SOURCE_PASS":
                issues.append({"date": date, "block": block, "lane": lane, "race_id": rid,
                               "reason": eligibility})
            selected.append({"date": date, "block": block, "lane": lane, "race_id": rid,
                             "horse_number": number, "parent_score": score,
                             "selection_eligibility": eligibility,
                             "source_role": source_role, "model_version": version,
                             "model_sha256": model_sha or "UNKNOWN"})
    status = {block: {lane: "AVAILABLE" if any(row["block"] == block and row["lane"] == lane for row in sources)
                      else "PENDING_OR_UNAVAILABLE" for lane in LANES} for block in spec["blocks"]}
    source_status_by_date = {date: {lane: "AVAILABLE" if any(source["date"] == date and source["lane"] == lane for source in sources)
                                    else "PENDING_OR_UNAVAILABLE" for lane in LANES}
                             for date, _ in source_by_day_lane}
    result = {"schema_version": "HISTORICAL_LANE_COMBINATION_PHASE1_V1",
              "runner_code_sha256": sha(Path(__file__)),
              "registry_path": str(registry_path), "registry_sha256": sha(registry_path),
              "spec_path": str(spec_path), "spec_sha256": sha(spec_path), "approval": approval,
              "population_races_by_block": {block: len(races) for block, races in population.items()},
              "source_status": status, "source_status_by_date": source_status_by_date,
              "sources": sources, "selected_horses": selected,
              "issues": issues, "pair_count": len(PAIRS), "result_access_count": 0,
              "evidence_credit": 0, "phase2_status": "NOT_AUTHORIZED_BY_PHASE1"}
    output.parent.mkdir(parents=True, exist_ok=True)
    with output.open("x", encoding="utf-8") as stream:
        json.dump(result, stream, ensure_ascii=False, sort_keys=True)
        stream.write("\n")
    return result


def verify_phase1(path: Path, expected_sha256: str) -> dict:
    if not path.is_file() or sha(path) != expected_sha256:
        raise CoverageStop("STOP_PHASE1_SHA_MISMATCH")
    value = read_json(path)
    if (value.get("schema_version") != "HISTORICAL_LANE_COMBINATION_PHASE1_V1" or
            value.get("result_access_count") != 0 or value.get("evidence_credit") != 0 or
            value.get("pair_count") != 28):
        raise CoverageStop("STOP_PHASE1_ROLE_OR_POPULATION")
    if value.get("runner_code_sha256") != sha(Path(__file__)):
        raise CoverageStop("STOP_PHASE1_CODE_SHA_DRIFT")
    if sha(Path(value["registry_path"])) != value["registry_sha256"] or sha(Path(value["spec_path"])) != value["spec_sha256"]:
        raise CoverageStop("STOP_PHASE1_DEPENDENCY_SHA_DRIFT")
    for source in value["sources"]:
        if not Path(source["path"]).is_file() or sha(Path(source["path"])) != source["sha256"]:
            raise CoverageStop("STOP_PHASE1_SOURCE_SHA_DRIFT")
    return value


def _metric(keys: set[tuple[str, int]], labels: dict) -> dict:
    valid = [labels[key] for key in keys if labels[key][0]]
    hits = sum(item[2] is True for item in valid)
    return {"selected": len(keys), "valid": len(valid), "hits": hits,
            "top3_rate": hits / len(valid) if valid else None}


def evaluate_phase2(phase1_path: Path, approval: dict, output: Path, *,
                    label_provider=official_labels) -> dict:
    """All 28 pairs; no caller may enter without a separately approved hash."""
    require_human_phase_approval(approval, 2)
    if output.exists():
        raise CoverageStop("STOP_OUTPUT_EXISTS")
    phase1 = verify_phase1(phase1_path, approval.get("phase1_sha256", ""))
    spec = read_json(Path(phase1["spec_path"]))
    requested = approval.get("authorized_dates")
    if not isinstance(requested, list) or not requested or len(requested) != len(set(requested)):
        raise CoverageStop("STOP_PHASE2_DATE_APPROVAL")
    known = set(phase1["source_status_by_date"])
    if any(date not in known or block_for_date(date, spec) is None or date in spec["hypothesis_discovery_dates_excluded"] for date in requested):
        raise CoverageStop("STOP_PHASE2_DATE_SCOPE")
    # The existing-role H2 and consumed Holdout restrictions are not relaxed.
    if any("20260919" <= date <= "20261025" for date in requested) and approval.get("h2_existing_role_review_accepted") is not True:
        raise CoverageStop("STOP_H2_ROLE_APPROVAL")
    all_rows = [row for row in phase1["selected_horses"] if row["date"] in requested]
    rows = [row for row in all_rows if row["selection_eligibility"] == "TECHNICAL_SOURCE_PASS"]
    by_date = defaultdict(set)
    for row in rows:
        by_date[row["date"]].add((row["race_id"], row["horse_number"]))
    labels = {}
    for date in requested:
        labels.update(label_provider(date, by_date[date]))
    if set(labels) != set().union(*by_date.values()):
        raise CoverageStop("STOP_RESULT_JOIN_COVERAGE")
    by_group = defaultdict(set)
    scores = defaultdict(dict)
    for row in rows:
        key = row["race_id"], row["horse_number"]
        by_group[row["block"], row["date"], row["lane"]].add(key)
        if row["parent_score"] is not None:
            scores[row["block"], row["date"], row["lane"]][key] = row["parent_score"]
    daily = []
    for date in requested:
        block = block_for_date(date, spec)
        for a, b in PAIRS:
            aa, bb = by_group[block, date, a], by_group[block, date, b]
            available = (phase1["source_status_by_date"][date][a] == "AVAILABLE" and
                         phase1["source_status_by_date"][date][b] == "AVAILABLE" and
                         not any(row["date"] == date and row["lane"] in (a, b) and
                                 row["selection_eligibility"] != "TECHNICAL_SOURCE_PASS"
                                 for row in all_rows))
            source_a = next((item for item in phase1["sources"] if item["date"] == date and item["lane"] == a), None)
            source_b = next((item for item in phase1["sources"] if item["date"] == date and item["lane"] == b), None)
            for mode, keys in (("AND", aa & bb), ("OR", aa | bb), ("A_ONLY", aa - bb), ("B_ONLY", bb - aa)):
                metric = _metric(keys, labels) if available else {"selected": None, "valid": None, "hits": None, "top3_rate": None}
                parent = {}
                if mode == "AND" and available:
                    for lane, parent_keys in ((a, aa), (b, bb)):
                        ranked = scores[block, date, lane]
                        if len(ranked) != len(parent_keys) or len(set(ranked.values())) != len(ranked):
                            parent[lane] = {"status": "UNFAIR_COMPARISON_UNAVAILABLE", "reason": "SAVED_PARENT_SCORE_MISSING_OR_TIED"}
                        else:
                            top = set(sorted(parent_keys, key=lambda key: (-ranked[key], key))[:len(keys)])
                            parent[lane] = {"status": "COMPARABLE_PARENT_SELECTED_POOL", **_metric(top, labels)}
                daily.append({"block": block, "date": date, "month": date[:6], "lane_a": a, "lane_b": b,
                              "mode": mode, "status": "COMPLETE" if available else "SOURCE_PENDING",
                              "model_version_a": source_a["model_version"] if source_a else None,
                              "model_version_b": source_b["model_version"] if source_b else None,
                              "source_role_a": source_a["source_role"] if source_a else None,
                              "source_role_b": source_b["source_role"] if source_b else None,
                              **metric, "same_volume_parent": parent,
                              "selection_universe_note": "SAVED_SELECTION_UNION; GLOBAL_E1_B1_NOT_RACE_RESTRICTED"})
    monthly = []
    group_keys = {tuple(r[key] for key in ("block", "month", "lane_a", "lane_b", "mode", "model_version_a", "model_version_b", "source_role_a", "source_role_b")) for r in daily}
    for block, month, a, b, mode, version_a, version_b, role_a, role_b in sorted(group_keys, key=str):
        subset = [row for row in daily if tuple(row[key] for key in ("block", "month", "lane_a", "lane_b", "mode", "model_version_a", "model_version_b", "source_role_a", "source_role_b")) == (block, month, a, b, mode, version_a, version_b, role_a, role_b)]
        complete = [row for row in subset if row["status"] == "COMPLETE"]
        valid = sum(row["valid"] for row in complete)
        hits = sum(row["hits"] for row in complete)
        monthly.append({"block": block, "month": month, "lane_a": a, "lane_b": b,
                        "model_version_a": version_a, "model_version_b": version_b,
                        "source_role_a": role_a, "source_role_b": role_b,
                        "mode": mode, "complete_dates": len(complete), "pending_dates": len(subset)-len(complete),
                        "selected": sum(row["selected"] for row in complete), "valid": valid,
                        "hits": hits, "top3_rate": hits / valid if valid else None})
    block_totals = []
    block_keys = {tuple(r[key] for key in ("block", "lane_a", "lane_b", "mode", "model_version_a", "model_version_b", "source_role_a", "source_role_b")) for r in daily}
    for block, a, b, mode, version_a, version_b, role_a, role_b in sorted(block_keys, key=str):
        subset = [row for row in daily if tuple(row[key] for key in ("block", "lane_a", "lane_b", "mode", "model_version_a", "model_version_b", "source_role_a", "source_role_b")) == (block, a, b, mode, version_a, version_b, role_a, role_b)]
        complete = [row for row in subset if row["status"] == "COMPLETE"]
        valid = sum(row["valid"] for row in complete)
        hits = sum(row["hits"] for row in complete)
        block_totals.append({"block": block, "lane_a": a, "lane_b": b, "mode": mode,
                             "model_version_a": version_a, "model_version_b": version_b,
                             "source_role_a": role_a, "source_role_b": role_b,
                             "complete_dates": len(complete), "pending_dates": len(subset)-len(complete),
                             "selected": sum(row["selected"] for row in complete),
                             "valid": valid, "hits": hits,
                             "top3_rate": hits / valid if valid else None})
    result = {"schema_version": "HISTORICAL_LANE_COMBINATION_PHASE2_V1",
              "phase1_sha256": sha(phase1_path), "approval": approval,
              "excluded_phase1_selection_count": len(all_rows) - len(rows),
              "daily_28_pair_modes": daily, "monthly_28_pair_modes": monthly,
              "block_28_pair_modes": block_totals,
              "pair_count": 28, "mode_count": 4, "evidence_credit": 0,
              "role": "HISTORICAL_DEVELOPMENT_DIAGNOSTIC_NOT_PROSPECTIVE"}
    output.parent.mkdir(parents=True, exist_ok=True)
    with output.open("x", encoding="utf-8") as stream:
        json.dump(result, stream, ensure_ascii=False, sort_keys=True)
        stream.write("\n")
    return result
