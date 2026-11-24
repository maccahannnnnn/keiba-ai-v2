"""One-date POST join for frozen active-system PRE artifacts; no re-selection."""
from __future__ import annotations

import csv
import hashlib
import json
from collections import Counter
from pathlib import Path

from review.daily_v5_same_volume_cumulative_tracker import evaluate as daily_cumulative
from review.target_daily_result_list_schema_v2_validator import validate_source_pair

ROOT = Path(__file__).resolve().parents[1]
SYSTEMS = ("CURRENT", "INDEPENDENT_V5", "TRACKCONDITION_SEMANTIC", "DAILY_V5_SAME_VOLUME", "FORMAL_V5", "FORMAL_V6")
VENUE = {"sapporo": "札幌", "hakodate": "函館", "fukushima": "福島", "niigata": "新潟", "tokyo": "東京", "nakayama": "中山", "chukyo": "中京", "kyoto": "京都", "hanshin": "阪神", "kokura": "小倉"}
ABNORMAL = {"中止", "除外", "取消", "失格"}


def sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def read(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def dump(path: Path, value: object) -> None:
    path.write_text(json.dumps(value, ensure_ascii=False, sort_keys=True, indent=2) + "\n", encoding="utf-8")


def identity(race_id: str) -> tuple[str, int]:
    parts = race_id.split("_")
    return parts[-2], int(parts[-1].removesuffix("R"))


def metrics(rows: list[dict]) -> dict:
    valid = [row for row in rows if row["valid_result"]]
    hits = [row for row in valid if row["actual_top3"]]
    return {"selected_n": len(rows), "invalid_n": len(rows) - len(valid), "valid_n": len(valid), "hits": len(hits),
            "rate": len(hits) / len(valid) if valid else None, "selected_races": len({row["race_id"] for row in rows}),
            "successful_buy_races": len({row["race_id"] for row in hits})}


def combine_metrics(items: list[dict]) -> dict:
    """Add already-frozen, result-joined metric objects; never reselect horses."""
    selected_n = sum(item["selected_n"] for item in items)
    invalid_n = sum(item["invalid_n"] for item in items)
    valid_n = sum(item["valid_n"] for item in items)
    hits = sum(item["hits"] for item in items)
    return {"selected_n": selected_n, "invalid_n": invalid_n, "valid_n": valid_n,
            "hits": hits, "rate": hits / valid_n if valid_n else None,
            "selected_races": sum(item.get("selected_races", 0) for item in items),
            "successful_buy_races": sum(item.get("successful_buy_races", 0) for item in items)}


def direction(candidate: dict, control: dict) -> str:
    """Descriptive direction only; this function makes no advancement decision."""
    if candidate["rate"] is None or control["rate"] is None:
        return "NEUTRAL"
    if candidate["rate"] > control["rate"] and candidate["hits"] >= control["hits"]:
        return "POSITIVE"
    if candidate["rate"] < control["rate"] and candidate["hits"] <= control["hits"]:
        return "NEGATIVE"
    return "NEUTRAL"


def run(date: str = "20260926") -> Path:
    out = ROOT / f"reports/{date}_all_active_systems_post"
    if out.exists():
        raise RuntimeError("STOP_OUTPUT_EXISTS")
    current_root = ROOT / f"reports/daily_pre_analysis_{date}/current_frozen"
    independent_root = ROOT / f"reports/independent_race_selection_prospective/{date}_pre"
    tc_root = ROOT / f"reports/track_condition_semantic_shadow_prospective/{date}_pre"
    daily_root = ROOT / f"reports/daily_v5_same_volume_prospective/{date}_pre"
    formal_root = ROOT / f"reports/selection_authority_protocol_v1_v6_forward_shadow/pre/{date}"
    manifest = read(current_root / "prediction_manifest.json")
    if any(sha(current_root / item["relative_path"]) != item["sha256"] for item in manifest["files"]):
        raise RuntimeError("STOP_CURRENT_PRE_SHA_MISMATCH")
    current = {item["race_id"]: read(current_root / item["artifact"]) for item in read(current_root / "race_index.json")["race_index"]}
    selected: dict[str, dict[str, dict[int, str]]] = {system: {} for system in SYSTEMS}
    for race_id, payload in current.items():
        selected["CURRENT"][race_id] = {int(row["horse_number"]): row["horse_name"] for row in payload["buys"]}
    for row in read(independent_root / "selection_manifest.json")["races"]:
        selected["INDEPENDENT_V5"][row["race_id"]] = {int(x["horse_number"]): x["horse_name"] for x in row["selected_horses"]}
    for row in read(tc_root / "horse_level_trace.json")["rows"]:
        if row["shadow_selected"]:
            selected["TRACKCONDITION_SEMANTIC"].setdefault(row["race_id"], {})[int(row["horse_number"])] = row["horse_name"]
    for row in read(daily_root / "selection.json")["races"]:
        selected["DAILY_V5_SAME_VOLUME"][row["race_id"]] = {int(x["horse_number"]): x["horse_name"] for x in row["selected_horses"]}
    for outer in read(formal_root / "dual_pre_semantic.json")["races"]:
        for system, arm in (("FORMAL_V5", "v5"), ("FORMAL_V6", "v6")):
            row = outer[arm]
            selected[system][row["race_id"]] = {int(x["horse_number"]): x["horse_name"] for x in row["horses"] if x["selected_by_protocol"]}
    raw = ROOT / "data/raw/target/daily_result_list"
    primary, auxiliary = raw / f"馬番順着順_{date}.csv", raw / f"着順馬番_{date}.csv"
    pair = validate_source_pair(primary, auxiliary, date)
    with primary.open("r", encoding="cp932", newline="") as source:
        result_rows = {row[0]: row for row in csv.reader(source)}
    result_index = pair["source_d_primary"]["race_index"]
    result_by_identity = {(item["venue_name"], int(item["race_number"])): key for key, item in result_index.items()}
    all_rows, race_board = [], []
    for race_id, payload in current.items():
        venue, number = identity(race_id); key = result_by_identity.get((VENUE[venue], number))
        if key is None:
            raise RuntimeError("STOP_RESULT_RACE_IDENTITY_MISMATCH:" + race_id)
        result = result_rows[key]; field_size = len(payload["ranked_results"])
        if field_size != int(result_index[key]["head_count"]):
            raise RuntimeError("STOP_RESULT_HORSE_IDENTITY_MISMATCH:" + race_id)
        selections = {system: selected[system].get(race_id, {}) for system in SYSTEMS}
        board = {"race_id": race_id, "venue": venue, "race_number": number,
                 "current_state": payload["buy_gate_trace"]["race"]["shadow_race_state"]}
        for system, horses in selections.items():
            shown = []
            for horse_number, horse_name in horses.items():
                raw_finish = result[11 + horse_number]
                valid = raw_finish.isdigit() and int(raw_finish) > 0
                if not valid and raw_finish not in ABNORMAL and raw_finish != "0":
                    raise RuntimeError("STOP_UNKNOWN_RESULT_STATUS:" + raw_finish)
                finish = int(raw_finish) if valid else None
                record = {"date": date, "race_id": race_id, "venue": venue, "race_number": number, "horse_number": horse_number,
                          "horse_name": horse_name, "system": system, "raw_result": raw_finish, "actual_finish": finish,
                          "valid_result": valid, "actual_top3": bool(valid and finish <= 3)}
                all_rows.append(record)
                shown.append(f"#{horse_number} {horse_name} {'○' if record['actual_top3'] else ('×' if valid else 'INVALID')}")
            board[system] = ", ".join(shown) if shown else "NO_BUY"
        race_board.append(board)
    by_system = {system: metrics([row for row in all_rows if row["system"] == system]) for system in SYSTEMS}
    keys = {system: {(row["race_id"], row["horse_number"]) for row in all_rows if row["system"] == system} for system in SYSTEMS}
    rows_by_key = {(row["race_id"], row["horse_number"]): row for row in all_rows}
    def group(values: set[tuple[str, int]]) -> dict:
        return metrics([rows_by_key[value] for value in values])
    current_keys, daily_keys, independent_keys, tc_keys = keys["CURRENT"], keys["DAILY_V5_SAME_VOLUME"], keys["INDEPENDENT_V5"], keys["TRACKCONDITION_SEMANTIC"]
    daily = {"common": group(current_keys & daily_keys), "current_only": group(current_keys - daily_keys), "daily_only": group(daily_keys - current_keys),
             "raw_hit_delta_daily_minus_current": by_system["DAILY_V5_SAME_VOLUME"]["hits"] - by_system["CURRENT"]["hits"],
             "rate_delta_daily_minus_current": by_system["DAILY_V5_SAME_VOLUME"]["rate"] - by_system["CURRENT"]["rate"],
             "horse_detail": [row for row in all_rows if row["system"] in {"CURRENT", "DAILY_V5_SAME_VOLUME"} and (row["race_id"], row["horse_number"]) in current_keys ^ daily_keys]}
    state = {race_id: payload["buy_gate_trace"]["race"]["shadow_race_state"] for race_id, payload in current.items()}
    independent = {"common": group(current_keys & independent_keys), "current_only": group(current_keys - independent_keys), "independent_only": group(independent_keys - current_keys),
                   "added_from_UNCONVERGED": group({key for key in independent_keys - current_keys if state[key[0]].startswith("PLAY_UNCONVERGED")}),
                   "converged_reselection": group({key for key in independent_keys - current_keys if state[key[0]] == "PLAY_CONVERGED"}),
                   "added_from_SKIP": group({key for key in independent_keys - current_keys if state[key[0]] == "SKIP"})}
    tc = {"common": group(current_keys & tc_keys), "tc_only": group(tc_keys - current_keys), "current_only": group(current_keys - tc_keys)}
    formal = {"v5": by_system["FORMAL_V5"], "v6": by_system["FORMAL_V6"], "discriminative_value": "ZERO", "relation": "IDENTICAL" if keys["FORMAL_V5"] == keys["FORMAL_V6"] else "DIFFERENT"}
    missed = []
    for key, row in rows_by_key.items():
        if row["actual_top3"] and key not in current_keys:
            owners = [system for system in SYSTEMS[1:] if key in keys[system]]
            if owners: missed.append({**row, "selected_by_systems": owners})
    recovery = {system: sum(system in row["selected_by_systems"] for row in missed) for system in SYSTEMS[1:]}
    daily_post = {"date": date, "block": date, "eligible_selected_races": by_system["DAILY_V5_SAME_VOLUME"]["selected_races"],
                  "combined": {"current": {"valid_selected_count": by_system["CURRENT"]["valid_n"], "top3_count": by_system["CURRENT"]["hits"]}, "daily_v5": {"valid_selected_count": by_system["DAILY_V5_SAME_VOLUME"]["valid_n"], "top3_count": by_system["DAILY_V5_SAME_VOLUME"]["hits"]}}}
    daily_tracker = daily_cumulative([daily_post])
    def hold_cumulative(system: str) -> dict:
        mine, control = by_system[system], by_system["CURRENT"]
        return {"status": "HOLD", "dates": 1, "blocks": 1, "selected_races": mine["selected_races"], "minimum": {"dates": 4, "blocks": 2, "selected_races": 60}, "system": mine, "current_same_period": control,
                "hit_delta": mine["hits"] - control["hits"], "rate_delta": mine["rate"] - control["rate"] if mine["rate"] is not None and control["rate"] is not None else None}
    out.mkdir(parents=True)
    prior_root = ROOT / "reports/20260926_all_active_systems_post"
    prior_systems = read(prior_root / "all_system_performance.json")
    prior_daily = read(prior_root / "current_vs_daily_v5.json")
    prior_independent = read(prior_root / "independent_outcomes.json")
    prior_tc = read(prior_root / "trackcondition_outcomes.json")
    prior_post = {"date": "20260926", "block": "20260926", "eligible_selected_races": prior_systems["DAILY_V5_SAME_VOLUME"]["selected_races"],
                  "combined": {"current": {"valid_selected_count": prior_systems["CURRENT"]["valid_n"], "top3_count": prior_systems["CURRENT"]["hits"]},
                               "daily_v5": {"valid_selected_count": prior_systems["DAILY_V5_SAME_VOLUME"]["valid_n"], "top3_count": prior_systems["DAILY_V5_SAME_VOLUME"]["hits"]}}}
    two_day_daily = daily_cumulative([prior_post, daily_post])
    two_day_daily.update({
        "raw_hit_delta_daily_minus_current": two_day_daily["daily_v5"]["hits"] - two_day_daily["current"]["hits"],
        "rate_delta_daily_minus_current": two_day_daily["daily_v5"]["rate"] - two_day_daily["current"]["rate"],
        "current_only": combine_metrics([prior_daily["current_only"], daily["current_only"]]),
        "daily_only": combine_metrics([prior_daily["daily_only"], daily["daily_only"]]),
    })
    def two_day_hold(system: str, prior_groups: dict, today_groups: dict) -> dict:
        system_total = combine_metrics([prior_systems[system], by_system[system]])
        current_total = combine_metrics([prior_systems["CURRENT"], by_system["CURRENT"]])
        group_names = ("added_from_UNCONVERGED", "added_from_SKIP", "converged_reselection") if system == "INDEPENDENT_V5" else ("tc_only", "current_only")
        groups = {name: combine_metrics([prior_groups[name], today_groups[name]]) for name in group_names}
        return {"status": "HOLD", "dates": 2, "blocks": 1, "selected_races": system_total["selected_races"],
                "minimum": {"dates": 4, "blocks": 2, "selected_races": 60}, "system": system_total,
                "current_same_period": current_total, "hit_delta": system_total["hits"] - current_total["hits"],
                "rate_delta": system_total["rate"] - current_total["rate"], "groups": groups}
    two_day_independent = two_day_hold("INDEPENDENT_V5", prior_independent, independent)
    two_day_tc = two_day_hold("TRACKCONDITION_SEMANTIC", prior_tc, tc)
    g1_race_id = f"race_{date}_nakayama_11R"
    g1_payload = current[g1_race_id]
    g1_venue, g1_number = identity(g1_race_id)
    g1_result_key = result_by_identity[(VENUE[g1_venue], g1_number)]
    g1_result = result_rows[g1_result_key]
    g1_names = {int(row["horse_number"]): row["horse_name"] for row in g1_payload["ranked_results"]}
    g1_reference = {"race_id": g1_race_id, "official_selection": {"CURRENT": "SKIP / BUY 0", "INDEPENDENT_V5": "#3 ママコチャ", "TRACKCONDITION_SEMANTIC": "NO_BUY", "DAILY_V5_SAME_VOLUME": "OUT_OF_SCOPE", "FORMAL_V5": "OUT_OF_SCOPE", "FORMAL_V6": "OUT_OF_SCOPE"},
                    "reference_only": True, "not_used_for_buy_evaluation": True,
                    "reference_outcomes": [{"horse_number": number, "horse_name": g1_names.get(number), "finish": int(g1_result[11 + number])} for number in (3, 7, 15)]}
    full_history = ["# 2026-09-27 POST — Full-History Review Input", "", "## Frozen prospective facts", "", "### 2026-09-26", "- Current 8/16", "- Daily V5 5/16", "- Independent 7/14", "- TC 5/8", "", "### 2026-09-27"]
    full_history += [f"- {system}: {value['hits']}/{value['valid_n']} ({value['rate']:.4%})" for system, value in by_system.items()]
    full_history += ["", "### 2026-09-26 + 2026-09-27 cumulative", f"- Daily V5: {two_day_daily['daily_v5']['hits']}/{two_day_daily['daily_v5']['valid']} vs Current {two_day_daily['current']['hits']}/{two_day_daily['current']['valid']}", f"- Independent: {two_day_independent['system']['hits']}/{two_day_independent['system']['valid_n']}", f"- TC: {two_day_tc['system']['hits']}/{two_day_tc['system']['valid_n']}", "", "### December frozen facts", "- Current 36/130 = 27.69%", "- Daily V5 43/131 = 32.82%", "- Independent 33/108 = 30.56%", "- TC 26/89 = 29.21%", "- Formal V5 37/118 = 31.36%", "- Formal V6 39/120 = 32.50%", "- Independent UNCONVERGED 21/61 = 34.43%; SKIP 1/9 = 11.11%", "- TC-only 9/36 = 25%; Current-only vs TC 19/77 = 24.68%", "- Daily V5 same-volume: +7 hit vs Current in December; -3 hit on 2026-09-26.", "", "No new conclusion or selection change is made by this document."]
    source_manifest = {"date": date, "primary": str(primary.relative_to(ROOT)), "auxiliary": str(auxiliary.relative_to(ROOT)), "primary_sha256": sha(primary), "auxiliary_sha256": sha(auxiliary), "schema": pair}
    artifacts = {"result_source_manifest.json": source_manifest, "result_join_integrity.json": {"status": "PASS", "population_races": len(current), "population_horses": sum(len(x["ranked_results"]) for x in current.values()), "joined_selection_rows": len(all_rows), "invalid_result_count": sum(not row["valid_result"] for row in all_rows)},
                 "all_system_performance.json": by_system, "current_vs_daily_v5.json": daily, "independent_outcomes.json": independent, "trackcondition_outcomes.json": tc, "formal_v5_v6_outcomes.json": formal,
                 "current_missed_top3_recovery.json": {"counts": recovery, "horses": missed}, "g1_reference_outcome.json": g1_reference,
                 "two_day_daily_v5_cumulative.json": two_day_daily, "two_day_independent_cumulative.json": two_day_independent, "two_day_trackcondition_cumulative.json": two_day_tc}
    for name, value in artifacts.items(): dump(out / name, value)
    fields = ["race_id", "venue", "race_number", "current_state", *SYSTEMS]
    with (out / "race_by_race_result_board.csv").open("w", encoding="utf-8", newline="") as target:
        writer = csv.DictWriter(target, fieldnames=fields); writer.writeheader(); writer.writerows(race_board)
    lines = [f"# {date} Result Board", "", "| Race | State | Current | Independent | TC | Daily V5 | Formal V5 | Formal V6 |", "|---|---|---|---|---|---|---|---|"]
    lines += [f"| {row['race_id']} | {row['current_state']} | {row['CURRENT']} | {row['INDEPENDENT_V5']} | {row['TRACKCONDITION_SEMANTIC']} | {row['DAILY_V5_SAME_VOLUME']} | {row['FORMAL_V5']} | {row['FORMAL_V6']} |" for row in race_board]
    (out / "race_by_race_result_board.md").write_text("\n".join(lines) + "\n", encoding="utf-8")
    share = [f"# {date} POST — Claude Work Share", "", "## N / Hits / Rate"]
    share += [f"- {system}: {value['selected_n']} / {value['hits']} / {value['rate']}" for system, value in by_system.items()]
    share += [f"", f"- Daily V5 vs Current hit delta: {daily['raw_hit_delta_daily_minus_current']}", f"- Independent UNCONVERGED: {independent['added_from_UNCONVERGED']}", f"- TC-only: {tc['tc_only']}", f"- Current-missed recovery: {recovery}", f"- Two-day Daily cumulative: {two_day_daily['decision']}", f"- Direction Daily: {direction(two_day_daily['daily_v5'] | {'selected_n': two_day_daily['daily_v5']['valid'], 'invalid_n': 0, 'valid_n': two_day_daily['daily_v5']['valid'], 'hits': two_day_daily['daily_v5']['hits']}, two_day_daily['current'] | {'selected_n': two_day_daily['current']['valid'], 'invalid_n': 0, 'valid_n': two_day_daily['current']['valid'], 'hits': two_day_daily['current']['hits']})}", "- 2026-09-27 PRE unchanged."]
    (out / "claude_share_summary.md").write_text("\n".join(share) + "\n", encoding="utf-8")
    (out / "full_history_review_input_summary.md").write_text("\n".join(full_history) + "\n", encoding="utf-8")
    dump(out / "SUCCESS", {"status": "SUCCESS", "result_access_date": date, "production_change": 0})
    refresh_artifact_hashes(out)
    return out


def refresh_artifact_hashes(out: Path) -> None:
    """Refresh the non-self-referential output hash index without a POST rerun."""
    indexed = [path for path in out.iterdir() if path.is_file() and path.name != "artifact_hashes.json"]
    dump(out / "artifact_hashes.json", {"self_hash_excluded": True, "indexed_artifacts": {path.name: sha(path) for path in indexed}})
