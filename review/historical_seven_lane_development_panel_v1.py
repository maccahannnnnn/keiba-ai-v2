"""Result-blind Phase 1 selection lock and separately approved Phase 2 join."""
from __future__ import annotations

import hashlib
import json
from collections import Counter, defaultdict
from pathlib import Path

from review.historical_lane_coverage_registry_v1 import (
    CoverageStop, LANES, assert_prediction_result_free, read_json, read_prediction, require_human_phase_approval, safe_prediction_path, sha,
)


def _selection_keys(lane: str, path: Path, value: dict, date: str | None = None) -> set[tuple[str, int]]:
    if path.name == "runtime_pre_only_output.json":
        rows = [row for row in value["generated_rows"] if date is None or row["date"] == date]
        if lane == "CURRENT":
            pairs = [(row["race_id"], int(row["horse_number"])) for row in rows
                     if row["values"]["post_rc1_decision"] == "BUY"]
        elif lane == "CURRENT_RANK1":
            from review.current_unconverged_rank1_resolution_shadow_v1 import select
            selected, _ = select(rows, len({row["race_id"] for row in rows}))
            pairs = [(row["race_id"], int(row["horse_number"])) for row in selected if row["shadow_addition"]]
        else:
            raise CoverageStop("STOP_RUN_C_LANE")
    elif path.name == "pre_freeze.json":
        branch = "A0" if lane == "PL_JOCKEY" else "A_new" if lane == "A_NEW" else None
        if branch is None:
            raise CoverageStop("STOP_FOLD_LANE")
        pairs = [(row["race_id"], int(row["horse_number"])) for row in value["selections"][branch]
                 if date is None or row["date"] == date]
    elif path.name == "current_pre.json" and lane == "CURRENT":
        pairs = [(str(row[0]), int(row[1])) for row in value["selected"]
                 if date is None or str(row[0]).startswith("race_" + date + "_")]
    elif lane == "CURRENT":
        index = read_json(path.with_name("race_index.json"))["race_index"]
        pairs = []
        for item in index:
            artifact = (path.parent / item["artifact"]).resolve()
            if artifact.parent != path.parent.resolve() or artifact.name == "result_join.json":
                raise CoverageStop("STOP_CURRENT_ARTIFACT_PATH")
            race = read_json(artifact)
            assert_prediction_result_free(race)
            pairs.extend((item["race_id"], int(h["horse_number"])) for h in race["buys"])
    elif lane == "EXP024":
        pairs = [(race["race_id"], int(n)) for race in value["races"] for n in race["treatment_selected_horses"]]
    elif lane == "CURRENT_RANK1":
        pairs = [(row["race_id"], int(row["selected_horse_number"])) for row in value["selections"]]
    elif lane == "PL_JOCKEY":
        pairs = [(race["race_id"], int(n)) for race in value["races"] for n in race["candidate_selected_horses"]]
    elif lane == "A_NEW":
        pairs = [(race["race_id"], int(n)) for race in value["races"] for n in race["a_new_selected_horses"]]
    elif lane in ("E1", "B1"):
        pairs = [(row["race_id"], int(row["horse_number"])) for row in value["selected_horses"]]
    elif lane == "INDEPENDENT_V5":
        pairs = [(race["race_id"], int(h["horse_number"])) for race in value["races"] for h in race["selected_horses"]]
    else:
        raise CoverageStop("STOP_UNKNOWN_LANE")
    if len(pairs) != len(set(pairs)):
        raise CoverageStop("STOP_DUPLICATE_SELECTED_HORSE:" + lane)
    return set(pairs)


def _rank_gate_rows(lane: str, path: Path, value: dict, date: str) -> list[dict]:
    """Only explicitly stored PRE rank/gate fields; no inferred ranking."""
    fields = []
    if path.name == "runtime_pre_only_output.json" and lane in ("CURRENT", "CURRENT_RANK1"):
        fields = [(row["race_id"], row["horse_number"], row.get("rank"), row.get("values", {}))
                  for row in value["generated_rows"] if row.get("date") == date]
    elif path.name == "pre_freeze.json" and lane in ("PL_JOCKEY", "A_NEW"):
        branch = "A0" if lane == "PL_JOCKEY" else "A_new"
        fields = [(row["race_id"], row["horse_number"], row.get("race_rank"), {})
                  for row in value["predictions"][branch] if row.get("date") == date]
    elif lane == "PL_JOCKEY" and isinstance(value.get("races"), list):
        fields = [(race["race_id"], horse["horse_number"], horse.get("candidate_rank"), {})
                  for race in value["races"] for horse in race.get("horses", [])]
    elif lane == "CURRENT" and path.name == "prediction_manifest.json":
        index = read_json(path.with_name("race_index.json"))["race_index"]
        for item in index:
            artifact = (path.parent / item["artifact"]).resolve()
            if artifact.parent != path.parent.resolve():
                raise CoverageStop("STOP_CURRENT_ARTIFACT_PATH")
            race = read_json(artifact)
            assert_prediction_result_free(race)
            fields.extend((item["race_id"], horse["horse_number"], horse.get("rank"), horse)
                          for horse in race.get("ranked_results", []))
    rows = []
    for rid, number, rank, gate in fields:
        if not rid.startswith("race_" + date + "_"):
            continue
        if rank is not None and (not isinstance(rank, int) or isinstance(rank, bool) or rank <= 0):
            raise CoverageStop("STOP_SAVED_RANK_INVALID")
        rows.append({"date": date, "race_id": rid, "horse_number": int(number), "lane": lane,
                     "rank": rank, "buy_gate": gate.get("post_rc1_decision", gate.get("decision")),
                     "risk_guard_pass": gate.get("risk_guard_pass")})
    keys = [(row["race_id"], row["horse_number"]) for row in rows]
    if len(keys) != len(set(keys)):
        raise CoverageStop("STOP_DUPLICATE_RANKING_HORSE")
    return rows


def _source_keys(rows: list[dict]) -> dict[tuple[str, str], dict]:
    by = {}
    for row in rows:
        key = (row["date"], row["lane"])
        source = {k: row[k] for k in ("prediction_path", "prediction_sha256", "source_role")}
        if key in by and by[key] != source:
            raise CoverageStop("STOP_INCONSISTENT_DAILY_LANE_SOURCE")
        by[key] = source
    return by


def prepare_phase1(phase0_path: Path, approval: dict, output: Path) -> dict:
    """Read only prediction sources; write only with an explicit Phase 1 approval."""
    require_human_phase_approval(approval, 1)
    if output.exists():
        raise CoverageStop("STOP_OUTPUT_EXISTS")
    phase0 = read_json(phase0_path)
    require_human_phase_approval(phase0.get("approval", {}), 0)
    registry = phase0["registry"]
    if registry["new_panel_evidence_credit"] != 0 or any(row["new_panel_evidence_credit"] != 0 for row in registry["rows"]):
        raise CoverageStop("STOP_EVIDENCE_CREDIT")
    race_keys = {row["race_id"] for row in registry["rows"]}
    if len(registry["rows"]) != len(race_keys) * len(LANES):
        raise CoverageStop("STOP_PHASE0_POPULATION")
    sources = _source_keys(registry["rows"])
    selected = []
    ranking = []
    issues = []
    for (date, lane), source in sorted(sources.items()):
        eligible = {row["race_id"] for row in registry["rows"] if row["date"] == date and row["lane"] == lane and row["technical_predictable"]}
        if not eligible:
            issues.append({"date": date, "lane": lane, "reason": "TECHNICAL_NOT_AVAILABLE"})
            continue
        path = safe_prediction_path(Path(source["prediction_path"]))
        if not path.is_file() or sha(path) != source["prediction_sha256"]:
            raise CoverageStop("STOP_PREDICTION_SOURCE_DRIFT:" + lane + ":" + date)
        value = read_prediction(path)
        assert_prediction_result_free(value)
        keys = _selection_keys(lane, path, value, date)
        if not {rid for rid, _ in keys} <= eligible:
            raise CoverageStop("STOP_SELECTION_OUTSIDE_COVERAGE:" + lane + ":" + date)
        for rid, number in sorted(keys):
            if number <= 0:
                raise CoverageStop("STOP_HORSE_NUMBER")
            selected.append({"date": date, "race_id": rid, "horse_number": number, "lane": lane,
                             "source_path": str(path), "source_sha256": source["prediction_sha256"],
                             "source_role": source["source_role"], "new_panel_evidence_credit": 0})
        ranking.extend(row for row in _rank_gate_rows(lane, path, value, date) if row["race_id"] in eligible)
    per = defaultdict(lambda: defaultdict(set))
    for row in selected:
        per[row["date"]][row["lane"]].add((row["race_id"], row["horse_number"]))
    comparisons = []
    for date, lanes in sorted(per.items()):
        for a,b in (("CURRENT", "PL_JOCKEY"), ("CURRENT", "A_NEW"), ("PL_JOCKEY", "EXP024"),
                    ("E1", "B1"), ("E1", "PL_JOCKEY")):
            aa,bb=lanes.get(a,set()),lanes.get(b,set())
            races_a,races_b={rid for rid,_ in aa},{rid for rid,_ in bb}
            counts_a,counts_b=Counter(rid for rid,_ in aa),Counter(rid for rid,_ in bb)
            comparable=races_a & races_b
            comparisons.append({"date":date,"lane_a":a,"lane_b":b,
                                "comparison_mode": "SAME_DAILY_N" if (a,b)==("E1","B1") else "COMBINATION" if (a,b)==("E1","PL_JOCKEY") else "SAME_RACE_SAME_K",
                                "common_selected_race_count":len(comparable),
                                "same_selected_race_set":races_a==races_b,"same_daily_selected_volume":len(aa)==len(bb),
                                "same_k_on_common_races":all(counts_a[rid]==counts_b[rid] for rid in comparable),
                                "lane_a_selected":len(aa),"lane_b_selected":len(bb),"common_selected_horses":len(aa&bb)})
    result={"schema_version":"HISTORICAL_SEVEN_LANE_DEVELOPMENT_PANEL_V1_PHASE1",
            "phase0_path":str(phase0_path),"phase0_sha256":sha(phase0_path),"approval":approval,
            "phase1_code_sha256": sha(Path(__file__)),
            "selected_horses":selected,"ranking_rows":ranking,
            "comparison_identity":comparisons,"issues":issues,
            "new_panel_evidence_credit":0,"result_access_count":0}
    output.parent.mkdir(parents=True, exist_ok=True)
    with output.open("x",encoding="utf-8") as stream:
        json.dump(result,stream,ensure_ascii=False,sort_keys=True);stream.write("\n")
    return result


def official_labels(date: str, keys: set[tuple[str, int]]) -> dict[tuple[str, int], tuple[bool, int | None, bool | None]]:
    """Import existing Result semantics only after Phase 2 gates have passed."""
    from review.candidate_generation_training_dataset_readiness_v1 import JAPANESE_VENUE, outcome, parse_race_id
    from review.formal_post_daily_v1 import result_sources

    sources, _ = result_sources(date)
    labels = {}
    for rid, number in keys:
        _, venue, race_number = parse_race_id(rid)
        labels[rid, number] = outcome(sources[JAPANESE_VENUE[venue], race_number], number)
    return labels


def evaluate_phase2(phase1_path: Path, approval: dict, output: Path, *, label_provider=official_labels) -> dict:
    """Development-only Result join. Deny protected periods before loader call."""
    require_human_phase_approval(approval, 2)
    if output.exists():
        raise CoverageStop("STOP_OUTPUT_EXISTS")
    phase1 = read_json(phase1_path)
    if approval.get("phase1_sha256") != sha(phase1_path):
        raise CoverageStop("STOP_PHASE1_APPROVED_SHA_MISMATCH")
    if phase1.get("new_panel_evidence_credit") != 0 or phase1.get("result_access_count") != 0:
        raise CoverageStop("STOP_PHASE1_ROLE")
    source_path = Path(phase1["phase0_path"])
    if sha(source_path) != phase1["phase0_sha256"]:
        raise CoverageStop("STOP_PHASE0_SHA_DRIFT")
    registry = read_json(source_path)["registry"]
    authorized = approval.get("authorized_dates")
    if not isinstance(authorized,list) or not authorized or len(authorized)!=len(set(authorized)):
        raise CoverageStop("STOP_PHASE2_DATE_SCOPE")
    policy = {day["date"]: next(row["result_policy"] for row in registry["rows"] if row["date"]==day["date"])
              for day in registry["dates"]}
    for date in authorized:
        if date not in policy or policy[date] in ("DENIED_UNLESS_EXISTING_POLICY_AND_NEW_HUMAN_APPROVAL", "HOLD"):
            raise CoverageStop("STOP_RESULT_PERIOD_NOT_AUTHORIZED:" + date)
        if date < "20260201":
            raise CoverageStop("STOP_CONSUMED_HOLDOUT_RESULT_ACCESS:" + date)
    selected = [row for row in phase1["selected_horses"] if row["date"] in authorized]
    ranking = [row for row in phase1.get("ranking_rows", []) if row["date"] in authorized]
    by_date=defaultdict(set)
    for row in selected:
        by_date[row["date"]].add((row["race_id"],row["horse_number"]))
    for row in ranking:
        by_date[row["date"]].add((row["race_id"],row["horse_number"]))
    labels={}
    for date in authorized:
        labels.update(label_provider(date,by_date[date]))
    if set(labels)!=set().union(*by_date.values()):
        raise CoverageStop("STOP_RESULT_JOIN_COVERAGE")
    outcomes=[]
    for row in selected:
        valid,finish,top3=labels[row["race_id"],row["horse_number"]]
        if valid not in (True,False) or (valid and (finish is None or top3 is None)) or (not valid and (finish is not None or top3 is not None)):
            raise CoverageStop("STOP_RESULT_SEMANTICS")
        outcomes.append({**row,"valid_result":valid,"finish":finish,"actual_top3":top3})
    totals={}
    for lane in LANES:
        rows=[row for row in outcomes if row["lane"]==lane]
        valid=[row for row in rows if row["valid_result"]]
        hits=sum(row["actual_top3"] is True for row in valid)
        totals[lane]={"selected":len(rows),"valid":len(valid),"invalid":len(rows)-len(valid),
                      "hits":hits,"rate":hits/len(valid) if valid else None}
    by_race_lane = defaultdict(list)
    for row in outcomes:
        by_race_lane[row["race_id"], row["lane"]].append(row)
    pairwise = {}
    for a, b in (("CURRENT", "PL_JOCKEY"), ("CURRENT", "A_NEW"),
                 ("PL_JOCKEY", "EXP024")):
        candidate_races = {rid for rid, lane in by_race_lane if lane == a} & {
            rid for rid, lane in by_race_lane if lane == b}
        comparable = {rid for rid in candidate_races
                      if len(by_race_lane[rid, a]) == len(by_race_lane[rid, b])}
        pair_rows = {lane: [row for rid in comparable for row in by_race_lane[rid, lane]] for lane in (a, b)}
        pair_metrics = {}
        for lane, lane_rows in pair_rows.items():
            valid = [row for row in lane_rows if row["valid_result"]]
            hits = sum(row["actual_top3"] is True for row in valid)
            pair_metrics[lane] = {"selected": len(lane_rows), "valid": len(valid), "hits": hits,
                                  "rate": hits / len(valid) if valid else None}
        pairwise[a + "__" + b] = {
            "comparison_mode": "SAME_RACE_SAME_K",
            "same_k_race_count": len(comparable),
            "excluded_k_mismatch_race_count": len(candidate_races - comparable),
            "lane_metrics": pair_metrics,
            "hit_delta_b_minus_a": pair_metrics[b]["hits"] - pair_metrics[a]["hits"],
        }
    same_daily_n = {}
    for date in authorized:
        a_rows = [row for row in outcomes if row["date"] == date and row["lane"] == "E1"]
        b_rows = [row for row in outcomes if row["date"] == date and row["lane"] == "B1"]
        same_daily_n[date] = {"comparison_mode": "SAME_DAILY_N", "e1_n": len(a_rows), "b1_n": len(b_rows),
                              "comparable": bool(a_rows and b_rows and len(a_rows) == len(b_rows)),
                              "e1_hits": sum(row["actual_top3"] is True for row in a_rows if row["valid_result"]),
                              "b1_hits": sum(row["actual_top3"] is True for row in b_rows if row["valid_result"])}
    combinations = {}
    for date in authorized:
        for a, b in (("E1", "PL_JOCKEY"), ("E1", "B1")):
            a_keys = {(row["race_id"], row["horse_number"]) for row in outcomes if row["date"] == date and row["lane"] == a}
            b_keys = {(row["race_id"], row["horse_number"]) for row in outcomes if row["date"] == date and row["lane"] == b}
            groups = {"AND": a_keys & b_keys, "OR": a_keys | b_keys,
                      "A_ONLY": a_keys - b_keys, "B_ONLY": b_keys - a_keys}
            for mode, keys in groups.items():
                valid = [labels[key] for key in keys if labels[key][0]]
                hits = sum(label[2] is True for label in valid)
                combinations[date + "__" + a + "__" + b + "__" + mode] = {
                    "comparison_mode": "COMBINATION", "selected": len(keys), "valid": len(valid),
                    "hits": hits, "rate": hits / len(valid) if valid else None}
    daily_totals = {}
    for date in authorized:
        daily_totals[date] = {}
        for lane in LANES:
            lane_rows = [row for row in outcomes if row["date"] == date and row["lane"] == lane]
            valid = [row for row in lane_rows if row["valid_result"]]
            daily_totals[date][lane] = {"selected": len(lane_rows), "valid": len(valid),
                                        "hits": sum(row["actual_top3"] is True for row in valid)}
    rank_totals = {}
    gate_totals = {}
    for lane in LANES:
        for rank in (1, 2, 3):
            keys = {(row["race_id"], row["horse_number"]) for row in ranking
                    if row["lane"] == lane and row["rank"] == rank}
            valid = [labels[key] for key in keys if labels[key][0]]
            rank_totals[lane + "__RANK" + str(rank)] = {"selected": len(keys), "valid": len(valid),
                                                       "hits": sum(label[2] is True for label in valid)}
        if lane == "CURRENT":
            for gate in sorted({str(row["buy_gate"]) for row in ranking if row["lane"] == lane and row["buy_gate"] is not None}):
                keys = {(row["race_id"], row["horse_number"]) for row in ranking
                        if row["lane"] == lane and str(row["buy_gate"]) == gate}
                valid = [labels[key] for key in keys if labels[key][0]]
                gate_totals[gate] = {"selected": len(keys), "valid": len(valid),
                                     "hits": sum(label[2] is True for label in valid)}
    result={"schema_version":"HISTORICAL_SEVEN_LANE_DEVELOPMENT_PANEL_V1_PHASE2",
            "phase1_path":str(phase1_path),"phase1_sha256":sha(phase1_path),"approval":approval,
            "authorized_dates":authorized,"outcomes":outcomes,"lane_totals":totals,
            "pairwise_same_k":pairwise,"same_daily_n":same_daily_n,
            "combinations":combinations,"daily_lane_totals":daily_totals,
            "ranking_totals":rank_totals,"current_buy_gate_totals":gate_totals,
            "new_panel_evidence_credit":0,"role":"HISTORICAL_DEVELOPMENT_DIAGNOSTIC"}
    output.parent.mkdir(parents=True,exist_ok=True)
    with output.open("x",encoding="utf-8") as stream:
        json.dump(result,stream,ensure_ascii=False,sort_keys=True);stream.write("\n")
    return result
