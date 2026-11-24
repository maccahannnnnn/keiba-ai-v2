"""Result-free, reference-only view over frozen 2026-09-27 PRE artifacts."""
from __future__ import annotations

import hashlib
import json
from pathlib import Path

import numpy as np

from review.daily_v5_same_volume_prospective_pre import load_assets
from review.v4_model_v3_formal_prospective_day1_pre_v1 import safe_rank, vector

ROOT = Path(__file__).resolve().parents[1]
RACE_ID = "race_20260927_nakayama_11R"


def sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def read(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def build(output: Path) -> Path:
    current_root = ROOT / "reports/daily_pre_analysis_20260927/current_frozen"
    independent_root = ROOT / "reports/independent_race_selection_prospective/20260927_pre"
    tc_root = ROOT / "reports/track_condition_semantic_shadow_prospective/20260927_pre"
    daily_root = ROOT / "reports/daily_v5_same_volume_prospective/20260927_pre"
    formal_root = ROOT / "reports/selection_authority_protocol_v1_v6_forward_shadow/pre/20260927"
    payload = read(current_root / f"{RACE_ID}_prediction.json")
    trace = {int(row["horse_number"]): row for row in payload["buy_gate_trace"]["horses"]}
    state = payload["buy_gate_trace"]["race"]["shadow_race_state"]
    current_top = [{"rank": row["rank"], "horse_number": row["horse_number"], "horse_name": row["horse_name"],
                    "shadow_ai_rank": trace[int(row["horse_number"])]["shadow_ai_rank"], "adjusted_score": row.get("adjusted_score"),
                    "final_score": row.get("final_score"), "decision_score": row.get("decision_score")} for row in payload["top5"]]
    model, scaler, _ = load_assets()
    daily_rows = []
    for horse in payload["top5"]:
        number = int(horse["horse_number"]); row = trace[number]
        probability = float(model.predict_proba(scaler.transform(np.asarray([vector(horse, row, state, f"{RACE_ID}:{number}")], dtype=float)))[0, 1])
        daily_rows.append({"horse_number": number, "horse_name": horse["horse_name"], "v5_p_top3": probability,
                           "shadow_ai_rank": safe_rank(row["shadow_ai_rank"], RACE_ID), "risk_guard_pass": row["risk_guard_pass"]})
    daily_rows.sort(key=lambda row: (-row["v5_p_top3"], row["shadow_ai_rank"], row["horse_number"]))
    for rank, row in enumerate(daily_rows, start=1): row["rank"] = rank
    independent = next(row for row in read(independent_root / "selection_manifest.json")["races"] if row["race_id"] == RACE_ID)
    independent_reference = sorted((row for row in independent["candidate_horses"] if row["risk_guard_pass"]), key=lambda row: (-row["p_top3"], row["shadow_ai_rank"], row["horse_number"]))
    for rank, row in enumerate(independent_reference, start=1): row["rank"] = rank
    tc_rows = [row for row in read(tc_root / "horse_level_trace.json")["rows"] if row["race_id"] == RACE_ID]
    tc_reference = sorted(({"horse_number": row["horse_number"], "horse_name": row["horse_name"], "rank": row["shadow_rank"], "score": row["shadow_score"]} for row in tc_rows), key=lambda row: (row["rank"], row["horse_number"]))[:5]
    daily = next(row for row in read(daily_root / "selection.json")["races"] if row["race_id"] == RACE_ID)
    formal = next(row for row in read(formal_root / "dual_pre_semantic.json")["races"] if row["v5"]["race_id"] == RACE_ID)
    formal_ref = {}
    for name in ("v5", "v6"):
        rows = [row for row in formal[name]["horses"] if row["exact5_membership"]]
        formal_ref[name] = sorted(({"rank": row["probability_rank"], "horse_number": row["horse_number"], "horse_name": row["horse_name"], "probability": row["probability"]} for row in rows), key=lambda row: row["rank"])
    official = {"current_race_state": state, "CURRENT": payload["buys"], "INDEPENDENT_V5": independent["selected_horses"],
                "TRACKCONDITION_SEMANTIC": [{"horse_number": row["horse_number"], "horse_name": row["horse_name"]} for row in tc_rows if row["shadow_selected"]],
                "DAILY_V5_SAME_VOLUME": {"scope_status": daily["scope_status"], "selected_horses": daily["selected_horses"]},
                "FORMAL_V5": {"eligible": formal["eligible_evidence_race"], "selected_horses": [row for row in formal["v5"]["horses"] if row["selected_by_protocol"]]},
                "FORMAL_V6": {"eligible": formal["eligible_evidence_race"], "selected_horses": [row for row in formal["v6"]["horses"] if row["selected_by_protocol"]]}}
    reference = {"CURRENT": current_top, "INDEPENDENT_V5": independent_reference, "TRACKCONDITION_SEMANTIC": tc_reference,
                 "DAILY_V5_REFERENCE_ONLY": daily_rows, "FORMAL_V5_EXACT5": formal_ref["v5"], "FORMAL_V6_EXACT5": formal_ref["v6"]}
    memberships: dict[int, dict] = {}
    reference_systems = {"CURRENT": current_top, "INDEPENDENT_V5": independent_reference, "TRACKCONDITION_SEMANTIC": tc_reference,
                         "DAILY_V5": daily_rows, "FORMAL_V5": formal_ref["v5"], "FORMAL_V6": formal_ref["v6"]}
    families = {"CURRENT": "CURRENT", "INDEPENDENT_V5": "V5", "TRACKCONDITION_SEMANTIC": "TC", "DAILY_V5": "V5", "FORMAL_V5": "V5", "FORMAL_V6": "V6"}
    for system, rows in reference_systems.items():
        for row in rows:
            number = int(row["horse_number"]); item = memberships.setdefault(number, {"horse_number": number, "horse_name": row["horse_name"], **{name: False for name in reference_systems}})
            item[system] = True
    consensus = []
    for row in memberships.values():
        selected_systems = [system for system in reference_systems if row[system]]
        consensus.append({**row, "system_count": len(selected_systems), "unique_model_family_count": len({families[system] for system in selected_systems})})
    consensus.sort(key=lambda row: (-row["system_count"], -row["unique_model_family_count"], row["horse_number"]))
    formal_availability = {"V5": "AVAILABLE" if formal_ref["v5"] else "NOT_AVAILABLE_FROM_FROZEN_ARTIFACT", "V6": "AVAILABLE" if formal_ref["v6"] else "NOT_AVAILABLE_FROM_FROZEN_ARTIFACT"}
    result = {"role": "REFERENCE_ONLY", "not_buy_override": True, "not_prospective_buy_evidence": True, "race_id": RACE_ID,
              "official_buy_status": official, "reference_rankings": reference, "consensus": consensus,
              "formal_reference_availability": formal_availability,
              "source_sha256": {"current": sha(current_root / f"{RACE_ID}_prediction.json"), "independent": sha(independent_root / "selection_manifest.json"), "trackcondition": sha(tc_root / "horse_level_trace.json"), "daily_v5": sha(daily_root / "selection.json"), "formal": sha(formal_root / "dual_pre_semantic.json")}, "result_data_access_count": 0}
    (output / "nakayama_11r_g1_reference_analysis.json").write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    def rowtext(rows, probability=""):
        return "; ".join(f"{x['rank']}. #{x['horse_number']} {x['horse_name']}{(' (' + str(x[probability]) + ')') if probability else ''}" for x in rows)
    lines = ["# 中山11R G1 Reference Ranking", "", "- `REFERENCE_ONLY` / `NOT_BUY_OVERRIDE` / `NOT_PROSPECTIVE_BUY_EVIDENCE`", f"- Current official race state: `{state}`", "", "## Official PRE BUY status"]
    lines += [f"- {name}: {value}" for name, value in official.items()]
    lines += ["", "## Reference rankings", f"- Current: {rowtext(current_top)}", f"- Independent V5: {rowtext(independent_reference, 'p_top3')}", f"- TrackCondition: {rowtext(tc_reference)}", f"- Daily V5: {rowtext(daily_rows, 'v5_p_top3')}", f"- Formal V5 Exact5: {rowtext(formal_ref['v5'], 'probability') or formal_availability['V5']}", f"- Formal V6 Exact5: {rowtext(formal_ref['v6'], 'probability') or formal_availability['V6']}", "", "## Consensus"]
    lines += [f"- #{row['horse_number']} {row['horse_name']}: systems={row['system_count']}, families={row['unique_model_family_count']}" for row in consensus]
    (output / "nakayama_11r_g1_reference_analysis.md").write_text("\n".join(lines) + "\n", encoding="utf-8")
    share_path = output / "claude_share_summary.md"
    share = share_path.read_text(encoding="utf-8")
    marker = "## Nakayama 11R G1 Reference"
    if marker not in share:
        share += "\n" + marker + "\n\n- REFERENCE_ONLY; not a BUY override or prospective BUY evidence.\n"
        share += f"- Official Current state: `{state}`\n"
        share += f"- Current top: {rowtext(current_top)}\n"
        share += f"- Independent V5 top: {rowtext(independent_reference, 'p_top3')}\n"
        share += f"- TrackCondition top: {rowtext(tc_reference)}\n"
        share += f"- Daily V5 top: {rowtext(daily_rows, 'v5_p_top3')}\n"
        share += f"- Formal V5: {formal_availability['V5']}; Formal V6: {formal_availability['V6']}\n"
        share += "- Consensus: " + "; ".join(f"#{row['horse_number']} {row['horse_name']} ({row['system_count']} systems)" for row in consensus) + "\n"
        share_path.write_text(share, encoding="utf-8")
    indexed = [path for path in output.iterdir() if path.is_file() and path.name != "artifact_hashes.json"]
    (output / "artifact_hashes.json").write_text(json.dumps({"self_hash_excluded": True, "indexed_artifacts": {path.name: sha(path) for path in indexed}}, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return output
