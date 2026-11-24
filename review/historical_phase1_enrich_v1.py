"""Bind pre-only H1 V5 and B1 derivations into the existing Phase 1 format."""
from __future__ import annotations

import json
from copy import deepcopy
from pathlib import Path

from review.historical_lane_combination_validation_v1 import verify_phase1
from review.historical_lane_coverage_registry_v1 import CoverageStop, sha


def enrich_phase1(base_path: Path, v5_path: Path, b1_h1_path: Path,
                  b1_p_path: Path, output: Path) -> dict:
    if output.exists():
        raise CoverageStop("STOP_OUTPUT_EXISTS")
    base = verify_phase1(base_path, sha(base_path))
    v5 = json.loads(v5_path.read_text(encoding="utf-8"))
    b1_h1 = json.loads(b1_h1_path.read_text(encoding="utf-8"))
    b1_p = json.loads(b1_p_path.read_text(encoding="utf-8"))
    if (v5.get("schema_version") != "HISTORICAL_V5_CHRONOLOGICAL_PHASE1_V1" or
            v5.get("evaluation_result_label_access") != 0 or v5.get("evidence_credit") != 0 or
            v5.get("phase1_sha256") != sha(base_path)):
        raise CoverageStop("STOP_V5_ENRICH_SOURCE")
    for source, path, block, count in ((b1_h1, b1_h1_path, "H1", 716),
                                       (b1_p, b1_p_path, "P", 38)):
        if (source.get("schema_version") != "HISTORICAL_B1_PHASE1_DERIVATION_V1" or
                source.get("phase1_sha256") != sha(base_path) or
                source.get("result_access_count") != 0 or source.get("evidence_credit") != 0 or
                source.get("selected_count") != count or
                {row["block"] for row in source["selected_horses"]} != {block}):
            raise CoverageStop("STOP_B1_ENRICH_SOURCE:" + block)
    result = deepcopy(base)
    existing = {(row["date"], row["lane"], row["race_id"], row["horse_number"])
                for row in result["selected_horses"]}
    if len(existing) != len(result["selected_horses"]):
        raise CoverageStop("STOP_BASE_SELECTION_DUPLICATE")
    allowed = {(row["date"], row["race_id"]) for row in
               json.loads(Path(base["registry_path"]).read_text(encoding="utf-8"))["registry"]["rows"]}
    fold_by_month = {fold["evaluation_month"]: fold for fold in v5["folds"]}
    for row in v5["selected_horses"]:
        fold = fold_by_month[row["date"][:6]]
        target = {"date": row["date"], "block": "H1", "lane": "INDEPENDENT_V5",
                  "race_id": row["race_id"], "horse_number": row["horse_number"],
                  "parent_score": row["p_top3"], "selection_eligibility": "TECHNICAL_SOURCE_PASS",
                  "source_role": "RESEARCH_WALK_FORWARD_NON_EVIDENTIAL",
                  "model_version": row["model_version"], "model_sha256": fold["model_sha256"]}
        key = tuple(target[k] for k in ("date", "lane", "race_id", "horse_number"))
        if key in existing or (target["date"], target["race_id"]) not in allowed:
            raise CoverageStop("STOP_V5_ENRICH_IDENTITY")
        existing.add(key)
        result["selected_horses"].append(target)
    for source, path, block in ((b1_h1, b1_h1_path, "H1"), (b1_p, b1_p_path, "P")):
        for row in source["selected_horses"]:
            plj = next((item for item in base["sources"]
                        if item["date"] == row["date"] and item["lane"] == "PL_JOCKEY"), None)
            if plj is None:
                raise CoverageStop("STOP_B1_PLJ_PARENT")
            target = {"date": row["date"], "block": block, "lane": "B1",
                      "race_id": row["race_id"], "horse_number": row["horse_number"],
                      "parent_score": row["pl_jockey_p_top3"],
                      "selection_eligibility": "TECHNICAL_SOURCE_PASS",
                      "source_role": source["source_role"],
                      "model_version": "B1_FROM_" + plj["model_version"],
                      "model_sha256": plj["model_sha256"]}
            key = tuple(target[k] for k in ("date", "lane", "race_id", "horse_number"))
            if key in existing or (target["date"], target["race_id"]) not in allowed:
                raise CoverageStop("STOP_B1_ENRICH_IDENTITY")
            existing.add(key)
            result["selected_horses"].append(target)
        for date in sorted({row["date"] for row in source["selected_horses"]}):
            result["sources"].append({"date": date, "block": block, "lane": "B1",
                                      "path": str(path.resolve()), "sha256": sha(path),
                                      "source_role": source["source_role"],
                                      "model_version": "B1_DIAGNOSTIC_" + block,
                                      "model_sha256": next(item["model_sha256"] for item in base["sources"]
                                                               if item["date"] == date and item["lane"] == "PL_JOCKEY")})
            result["source_status_by_date"][date]["B1"] = "AVAILABLE"
        result["source_status"][block]["B1"] = "AVAILABLE"
    for fold in v5["folds"]:
        for source in fold["pre_sources"]:
            date = source["date"]
            result["sources"].append({"date": date, "block": "H1", "lane": "INDEPENDENT_V5",
                                      "path": str(v5_path.resolve()), "sha256": sha(v5_path),
                                      "source_role": "RESEARCH_WALK_FORWARD_NON_EVIDENTIAL",
                                      "model_version": "RESEARCH_CHRONOLOGICAL_" + fold["evaluation_month"],
                                      "model_sha256": fold["model_sha256"]})
            result["source_status_by_date"][date]["INDEPENDENT_V5"] = "AVAILABLE"
    result["source_status"]["H1"]["INDEPENDENT_V5"] = "AVAILABLE"
    result["selected_horses"].sort(key=lambda row: (row["date"], row["lane"], row["race_id"], row["horse_number"]))
    result["sources"].sort(key=lambda row: (row["date"], row["lane"]))
    result["enrichment"] = {"code_sha256": sha(Path(__file__)),
                            "base_sha256": sha(base_path),
                            "v5_selection_sha256": sha(v5_path),
                            "b1_h1_sha256": sha(b1_h1_path),
                            "b1_p_sha256": sha(b1_p_path),
                            "H2_full_eight_lane_status": "PENDING"}
    result["issues"] = [issue for issue in result["issues"]
                        if not (issue["block"] == "H1" and issue["lane"] in ("INDEPENDENT_V5", "B1"))
                        and not (issue["block"] == "P" and issue["lane"] == "B1")]
    output.parent.mkdir(parents=True, exist_ok=True)
    with output.open("x", encoding="utf-8") as stream:
        json.dump(result, stream, ensure_ascii=False, sort_keys=True)
        stream.write("\n")
    return result
