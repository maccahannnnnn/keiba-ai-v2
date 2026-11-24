"""Result-free, date-specific comparison of frozen 2026-11-15 PRE artifacts."""
from __future__ import annotations

import csv
import hashlib
import itertools
import json
from collections import Counter, defaultdict
from datetime import datetime, timedelta, timezone
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
DATE = "20261115"
OUT = ROOT / "reports/lane_prediction_comparison_20261115"
SUMMARY = ROOT / f"reports/formal_pre_daily/{DATE}/summary.json"
LANES = ("CURRENT", "EXP024", "CURRENT_RANK1", "PL_JOCKEY", "A_NEW", "E1", "INDEPENDENT_V5")
VENUE = {"tokyo": "東京", "kyoto": "京都", "fukushima": "福島"}


def sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def read(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def source(path_text: str) -> Path:
    path = Path(path_text)
    return path if path.is_absolute() else ROOT / path


def write_csv(name: str, fields: list[str], rows: list[dict]) -> None:
    with (OUT / name).open("x", encoding="utf-8-sig", newline="") as stream:
        writer = csv.DictWriter(stream, fieldnames=fields, extrasaction="ignore")
        writer.writeheader()
        writer.writerows(rows)


def label(rid: str) -> str:
    parts = rid.split("_")
    return f"{VENUE.get(parts[2], parts[2])}{parts[3]}"


def horse_text(numbers: list[int], names: dict[tuple[str, int], str], rid: str) -> str:
    return "、".join(f"#{n} {names[rid, n]}" for n in numbers) if numbers else "—"


def main() -> None:
    if OUT.exists():
        raise RuntimeError("STOP_REPORT_OUTPUT_EXISTS")
    summary = read(SUMMARY)
    if summary.get("status") != "COMPLETE" or summary.get("date") != DATE or summary.get("result_access_count") != 0:
        raise RuntimeError("STOP_FORMAL_PRE_NOT_COMPLETE")
    if set(summary["lanes"]) != set(LANES):
        raise RuntimeError("STOP_LANE_SET")
    for lane, info in summary["lanes"].items():
        for path_key, sha_key in (("selection_path", "selection_sha256"), ("authority_path", "authority_sha256")):
            if sha(source(info[path_key])) != info[sha_key]:
                raise RuntimeError("STOP_FROZEN_SHA:" + lane)
    b1_path = ROOT / f"reports/formal_pre_daily/{DATE}/b1_diagnostic/selection.json"
    b1_freeze_path = b1_path.with_name("freeze_manifest.json")
    b1 = read(b1_path)
    b1_freeze = read(b1_freeze_path)
    if b1.get("date") != DATE or b1.get("result_access_count") != 0 or b1.get("evidence_credit") != 0:
        raise RuntimeError("STOP_B1_ROLE")
    if b1_freeze.get("selection_sha256") != sha(b1_path):
        raise RuntimeError("STOP_B1_SHA")

    current_root = ROOT / f"reports/prospective_prediction_{DATE}_formal_trace_v1"
    index_path = current_root / "race_index.json"
    race_index = read(index_path)["race_index"]
    if len(race_index) != summary["race_count"]:
        raise RuntimeError("STOP_RACE_COUNT")
    races = {item["race_id"]: read(current_root / item["artifact"]) for item in race_index}
    race_ids = sorted(races, key=lambda x: (list(VENUE).index(x.split("_")[2]), int(x.split("_")[3][:-1])))
    names = {(rid, int(h["horse_number"])): h["horse_name"] for rid, race in races.items() for h in race["ranked_results"]}
    if len(names) != summary["horse_count"]:
        raise RuntimeError("STOP_HORSE_COUNT")

    data = {lane: read(source(info["selection_path"])) for lane, info in summary["lanes"].items() if lane != "CURRENT"}
    selections: dict[str, dict[str, set[int]]] = {lane: defaultdict(set) for lane in (*LANES, "B1")}
    for lane, info in summary["lanes"].items():
        for horse in info["selected_horses"]:
            selections[lane][horse["race_id"]].add(int(horse["horse_number"]))
        if sum(map(len, selections[lane].values())) != info["selected_count"]:
            raise RuntimeError("STOP_SELECTION_COUNT:" + lane)
    for horse in b1["selected_horses"]:
        selections["B1"][horse["race_id"]].add(int(horse["horse_number"]))
    if sum(map(len, selections["B1"].values())) != b1["selected_count"]:
        raise RuntimeError("STOP_B1_SELECTION_COUNT")

    # These are only rankings explicitly persisted by each frozen lane. E1 and
    # B1 persist PL probabilities/allocations, not an independent per-race rank.
    ranks: dict[str, dict[str, dict[int, int]]] = {lane: defaultdict(dict) for lane in LANES}
    probs: dict[str, dict[str, dict[int, float]]] = {lane: defaultdict(dict) for lane in LANES}
    reasons: dict[str, dict[str, dict[int, str]]] = {lane: defaultdict(dict) for lane in LANES}
    risks: dict[str, dict[str, dict[int, str]]] = {lane: defaultdict(dict) for lane in LANES}
    for rid, race in races.items():
        for h in race["ranked_results"]:
            n = int(h["horse_number"])
            ranks["CURRENT"][rid][n] = int(h["rank"])
            reasons["CURRENT"][rid][n] = h.get("explain_summary", "")
            risks["CURRENT"][rid][n] = "、".join(h.get("risks", [])[:3])
    for row in data["EXP024"]["races"]:
        rid = row["race_id"]
        for h in row["horses"]:
            n = int(h["horse_number"])
            ranks["EXP024"][rid][n] = int(h["pl_rank"])
            probs["EXP024"][rid][n] = float(h["pl_probability"])
            risks["EXP024"][rid][n] = "、".join(h.get("low_history_flags", {}).get("risks", [])[:3])
    for row in data["PL_JOCKEY"]["races"]:
        rid = row["race_id"]
        for h in row["horses"]:
            n = int(h["horse_number"])
            ranks["PL_JOCKEY"][rid][n] = int(h["candidate_rank"])
            probs["PL_JOCKEY"][rid][n] = float(h["candidate_p_top3"])
            reasons["PL_JOCKEY"][rid][n] = f"騎手lift={h['jockey_top3_lift']:+.3f}"
    for row in data["A_NEW"]["races"]:
        rid = row["race_id"]
        for h in row["horses"]:
            n = int(h["horse_number"])
            ranks["A_NEW"][rid][n] = int(h["a_new_rank"])
            probs["A_NEW"][rid][n] = float(h["a_new_p_top3"])
            reasons["A_NEW"][rid][n] = f"騎手lift={h['formal_jockey_top3_lift']:+.3f}"
    for row in data["CURRENT_RANK1"]["selections"]:
        rid, n = row["race_id"], int(row["selected_horse_number"])
        ranks["CURRENT_RANK1"][rid][n] = int(row["stored_rank"])
        reasons["CURRENT_RANK1"][rid][n] = row.get("selection_reason", "")
    for row in data["INDEPENDENT_V5"]["races"]:
        rid = row["race_id"]
        for h in row.get("candidate_horses", []):
            n = int(h["horse_number"])
            ranks["INDEPENDENT_V5"][rid][n] = int(h["shadow_ai_rank"])
            probs["INDEPENDENT_V5"][rid][n] = float(h["p_top3"])
            reasons["INDEPENDENT_V5"][rid][n] = "risk_guard=" + str(h["risk_guard_pass"])

    # Verify that all selected horses belong to the frozen Current population.
    for lane, by_race in selections.items():
        for rid, nums in by_race.items():
            if rid not in races or not nums <= {n for r, n in names if r == rid}:
                raise RuntimeError("STOP_SELECTION_IDENTITY:" + lane)

    OUT.mkdir(parents=False)
    source_paths = [SUMMARY, index_path, b1_path, b1_freeze_path]
    source_paths.extend(source(info["selection_path"]) for info in summary["lanes"].values())
    source_paths.extend(source(info["authority_path"]) for info in summary["lanes"].values())
    source_paths.extend(current_root / item["artifact"] for item in race_index)

    lane_rows = []
    comparison_rows = []
    top3_rows, top5_rows, buy_rows, disagreement_rows = [], [], [], []
    race_lines = ["# 2026-11-15 凍結PRE・7レーン比較", "", "Result未参照。7レーンの選出は各レーンのShadow選出であり、Currentの正式BUYとは別です。E1・B1には独立したレース内順位が保存されていません。Current Rank1は該当レースの選出1頭のみ、V5は保存された候補範囲のみを順位として扱います。", ""]
    for lane in (*LANES, "B1"):
        selected_races = sum(bool(selections[lane][rid]) for rid in race_ids)
        lane_rows.append({"lane": lane, "role": "PRODUCTION_BUY" if lane == "CURRENT" else ("DIAGNOSTIC_EVIDENCE_0" if lane == "B1" else "FROZEN_SHADOW_SELECTION"), "races_in_scope": len(race_ids), "horses_in_scope": len(names), "selected_count": sum(map(len, selections[lane].values())), "selected_races": selected_races, "ranking_available": lane not in ("E1", "B1"), "probability_available": lane in ("EXP024", "PL_JOCKEY", "A_NEW", "E1", "INDEPENDENT_V5", "B1")})
    for rid in race_ids:
        venue_race = label(rid)
        race = races[rid]
        all_numbers = {n for r, n in names if r == rid}
        top3_by_horse = defaultdict(list)
        top5_by_horse = defaultdict(list)
        for lane in LANES:
            for n, rank in ranks[lane][rid].items():
                if rank <= 3:
                    top3_by_horse[n].append(lane)
                if rank <= 5:
                    top5_by_horse[n].append(lane)
        selected_by_horse = defaultdict(list)
        for lane in LANES:
            for n in selections[lane][rid]:
                selected_by_horse[n].append(lane)
        for n, members in sorted(top3_by_horse.items(), key=lambda x: (-len(x[1]), x[0])):
            top3_rows.append({"race_id": rid, "race": venue_race, "horse_number": n, "horse_name": names[rid, n], "lane_count": len(members), "lanes": "|".join(members)})
        for n, members in sorted(top5_by_horse.items(), key=lambda x: (-len(x[1]), x[0])):
            top5_rows.append({"race_id": rid, "race": venue_race, "horse_number": n, "horse_name": names[rid, n], "lane_count": len(members), "lanes": "|".join(members)})
        for n, members in sorted(selected_by_horse.items(), key=lambda x: (-len(x[1]), x[0])):
            buy_rows.append({"race_id": rid, "race": venue_race, "horse_number": n, "horse_name": names[rid, n], "selected_lane_count": len(members), "selected_lanes": "|".join(members), "current_formal_buy": "CURRENT" in members, "b1_diagnostic_selected": n in selections["B1"][rid]})
        race_lines += [f"## {venue_race}（{len(all_numbers)}頭・Current {race['race_decision']}）", "", "| レーン | Rank1 / Rank2 / Rank3 | Top5 | 選出 | 主な保存情報 |", "|---|---|---|---|---|"]
        for lane in LANES:
            ranked = sorted(ranks[lane][rid], key=lambda n: (ranks[lane][rid][n], n))
            rank3 = " / ".join(f"#{n} {names[rid,n]}" for n in ranked[:3]) or "未保存"
            top5 = horse_text(ranked[:5], names, rid) if ranked else "未保存"
            selected = horse_text(sorted(selections[lane][rid]), names, rid)
            reason_bits = []
            for n in ranked[:1]:
                if reasons[lane][rid].get(n):
                    reason_bits.append(reasons[lane][rid][n].replace("|", "/"))
                if risks[lane][rid].get(n):
                    reason_bits.append("警戒: " + risks[lane][rid][n].replace("|", "/"))
            if probs[lane][rid] and ranked:
                reason_bits.append(f"上位p={probs[lane][rid].get(ranked[0], 0):.3f}")
            if lane == "E1":
                reason_bits.append("PL全頭確率による日別配分。独立順位なし")
            if lane == "CURRENT_RANK1" and not ranked:
                reason_bits.append("当該レースの選出なし。全頭順位なし")
            if lane == "INDEPENDENT_V5":
                reason_bits.append("保存候補範囲の順位")
            race_lines.append(f"| {lane} | {rank3} | {top5} | {selected} | {'; '.join(reason_bits) or '説明未保存'} |")
            comparison_rows.append({"race_id": rid, "race": venue_race, "lane": lane, "race_horses": len(all_numbers), "rank1": horse_text(ranked[:1], names, rid) if ranked else "UNAVAILABLE", "rank2": horse_text(ranked[1:2], names, rid) if len(ranked)>1 else "UNAVAILABLE", "rank3": horse_text(ranked[2:3], names, rid) if len(ranked)>2 else "UNAVAILABLE", "top5": top5, "selected": selected, "selected_count": len(selections[lane][rid]), "rank_scope": "FULL_FIELD" if lane in ("CURRENT", "EXP024", "PL_JOCKEY", "A_NEW") else ("SAVED_CANDIDATES_ONLY" if lane in ("CURRENT_RANK1", "INDEPENDENT_V5") else "UNAVAILABLE"), "reason": "; ".join(reason_bits)})
        race_lines.append(f"| B1診断 | 独立順位なし | 独立順位なし | {horse_text(sorted(selections['B1'][rid]), names, rid)} | PL+J全頭確率・日別配分、Evidence credit 0 |")
        agreement = [(n, lanes) for n, lanes in top3_by_horse.items() if len(lanes) >= 2]
        agreement.sort(key=lambda x: (-len(x[1]), x[0]))
        agree_text = "、".join(f"#{n} {names[rid,n]}（{len(ls)}レーン: {','.join(ls)}）" for n, ls in agreement) or "該当なし"
        diverged = []
        for n in all_numbers:
            full = [lane for lane in ("CURRENT", "EXP024", "PL_JOCKEY", "A_NEW") if n in ranks[lane][rid]]
            vals = [ranks[lane][rid][n] for lane in full]
            if vals and max(vals)-min(vals) >= 5 and min(vals) <= 3:
                diverged.append((n, min(vals), max(vals)))
                disagreement_rows.append({"race_id": rid, "race": venue_race, "horse_number": n, "horse_name": names[rid,n], "min_rank": min(vals), "max_rank": max(vals), "rank_spread": max(vals)-min(vals), "current_risk": risks["CURRENT"][rid].get(n,""), "explanation": "保存済み順位差。因果理由はUNKNOWN"})
        div_text = "、".join(f"#{n} {names[rid,n]}（順位{lo}–{hi}）" for n,lo,hi in sorted(diverged)) or "大きな順位差なし"
        current_set, b1_set = selections["CURRENT"][rid], selections["B1"][rid]
        race_lines += ["", f"- 一致評価: {agree_text}", f"- 不一致評価: {div_text}", f"- Current/B1: 共通 {horse_text(sorted(current_set & b1_set), names, rid)}／Currentのみ {horse_text(sorted(current_set-b1_set), names, rid)}／B1のみ {horse_text(sorted(b1_set-current_set), names, rid)}", "- 展開・リスク: Current上位の保存済み説明・警戒要因は表を参照。レーン共通の展開評価が別途保存されていない場合はUNKNOWN。", "- 統合コメント: 上位一致は順位表、選出の差はCurrent/B1欄で確認。順位差の因果は保存済み情報を超えて断定しない。", ""]

    write_csv("lane_prediction_summary.csv", list(lane_rows[0]), lane_rows)
    write_csv("race_by_race_comparison.csv", list(comparison_rows[0]), comparison_rows)
    write_csv("top3_consensus.csv", list(top3_rows[0]), top3_rows)
    write_csv("top5_consensus.csv", list(top5_rows[0]), top5_rows)
    write_csv("buy_consensus.csv", list(buy_rows[0]), buy_rows)
    write_csv("lane_disagreement.csv", list(disagreement_rows[0]), disagreement_rows)
    combinations = []
    for a,b in itertools.combinations((*LANES,"B1"),2):
        shared = [(rid,n) for rid in race_ids for n in selections[a][rid] & selections[b][rid]]
        combinations.append({"lane_a": a,"lane_b": b,"common_selected_horses":len(shared),"common_selected_races":len({rid for rid,n in shared}),"horses":"; ".join(f"{label(rid)} #{n} {names[rid,n]}" for rid,n in shared),"semantics":"CURRENT=FORMAL_BUY; OTHERS=SHADOW_OR_DIAGNOSTIC_SELECTION"})
    write_csv("lane_combination_summary.csv", list(combinations[0]), combinations)
    (OUT / "race_analysis.md").write_text("\n".join(race_lines), encoding="utf-8")
    top3_ge = {k:sum(r["lane_count"]>=k for r in top3_rows) for k in (2,3,4,7)}
    current_all = {(rid,n) for rid in race_ids for n in selections["CURRENT"][rid]}
    b1_all = {(rid,n) for rid in race_ids for n in selections["B1"][rid]}
    top3_best = sorted(top3_rows,key=lambda x:(-x["lane_count"],x["race_id"],x["horse_number"]))[:15]
    daily = ["# 2026-11-15 正式PRE・予測比較総括", "", f"- 正式PRE: {summary['status']}／{summary['race_count']}レース・{summary['horse_count']}頭。凍結後のResult参照は0。", f"- 09:00 JSTはKeibaAI保守的Freeze期限であり公式発走時刻ではない。official_time_verified={str(summary['official_time_verified']).lower()}。", "- 7レーンは正式Freeze済み。B1は別枠診断でEvidence credit 0。", "", "## レーン別選出", "", "| レーン | 選出頭数 | 選出レース数 | 役割 |", "|---|---:|---:|---|"]
    daily += [f"| {r['lane']} | {r['selected_count']} | {r['selected_races']} | {r['role']} |" for r in lane_rows]
    daily += ["", "## 上位一致", "", f"明示的な保存順位に基づくTop3一致馬数: 2レーン以上 {top3_ge[2]}、3以上 {top3_ge[3]}、4以上 {top3_ge[4]}、全7レーン {top3_ge[7]}。E1・B1の未保存順位は母数に含めない。", "", "| 馬 | Top3レーン数 | レーン |", "|---|---:|---|"]
    daily += [f"| {r['race']} #{r['horse_number']} {r['horse_name']} | {r['lane_count']} | {r['lanes']} |" for r in top3_best]
    daily += ["", "## CurrentとB1の選出配分", "", f"共通 {len(current_all & b1_all)}頭、Currentのみ {len(current_all-b1_all)}頭、B1のみ {len(b1_all-current_all)}頭。Currentは正式BUY、B1はEvidence credit 0の追加診断でありBUY権限はない。", "", "## 解釈上の注意", "", "EXP024・PL+Jockey・A_newはPL系情報を共有し、一致レーン数は独立根拠数ではない。確率・スコアの尺度はレーン間で直接比較しない。順位・選出の違いは保存済みArtifactに基づくが、因果要因が保存されていなければUNKNOWN。結果、的中率、回収率は扱わない。次回POSTでは一致上位馬、Current/B1差分、CurrentのBUYと他レーン選出の乖離を事前固定した集合のまま検証する。", ""]
    (OUT / "daily_summary.md").write_text("\n".join(daily), encoding="utf-8")
    outputs = sorted((p for p in OUT.iterdir() if p.is_file()), key=lambda p:p.name)
    manifest = {"date":DATE,"created_at_jst":datetime.now(timezone(timedelta(hours=9))).isoformat(),"role":"RESULT_FREE_FROZEN_PRE_COMPARISON","result_access_count":0,"formal_pre_summary":{"path":str(SUMMARY),"sha256":sha(SUMMARY)},"sources":[{"path":str(p),"sha256":sha(p)} for p in dict.fromkeys(source_paths)],"outputs":[{"path":str(p),"sha256":sha(p)} for p in outputs],"limitations":["E1 and B1 have no independent per-race ranking", "CURRENT_RANK1 and V5 rank coverage is partial", "Shadow selections are not production BUY"]}
    with (OUT / "source_manifest.json").open("x",encoding="utf-8") as stream:
        json.dump(manifest,stream,ensure_ascii=False,indent=2)
        stream.write("\n")
    print(json.dumps({"status":"COMPLETE","races":len(race_ids),"horses":len(names),"lanes":{r['lane']:r['selected_count'] for r in lane_rows},"top3_ge":top3_ge,"current_b1_overlap":len(current_all&b1_all),"output":str(OUT)},ensure_ascii=False))


if __name__ == "__main__":
    main()
