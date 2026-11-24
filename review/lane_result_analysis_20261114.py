"""Derived 11/14 lane diagnostic; consumes frozen PRE and completed formal POST."""
from __future__ import annotations

import csv
import hashlib
import itertools
import json
from collections import Counter, defaultdict
from datetime import datetime, timedelta, timezone
from pathlib import Path

from review.candidate_generation_training_dataset_readiness_v1 import JAPANESE_VENUE, outcome, parse_race_id
from review.formal_post_daily_v1 import result_sources, sha


ROOT = Path(__file__).resolve().parents[1]
DATE = "20261114"
OUT = ROOT / "reports/lane_result_analysis_20261114"
PRE = ROOT / f"reports/formal_pre_daily/{DATE}/summary.json"
POST_DIR = ROOT / f"reports/formal_post_daily_v1/{DATE}"
B1_PRE = ROOT / f"reports/formal_pre_daily/{DATE}/b1_diagnostic/selection.json"
LANES = ("CURRENT", "EXP024", "CURRENT_RANK1", "PL_JOCKEY", "A_NEW", "E1", "INDEPENDENT_V5")
VENUE = {"fukushima": "福島", "kyoto": "京都", "tokyo": "東京"}


def read(path: Path):
    return json.loads(path.read_text(encoding="utf-8"))


def path_of(value: str) -> Path:
    p = Path(value)
    return p if p.is_absolute() else ROOT / p


def write_csv(name: str, rows: list[dict], fields: list[str]) -> None:
    with (OUT / name).open("x", encoding="utf-8-sig", newline="") as stream:
        writer = csv.DictWriter(stream, fieldnames=fields, extrasaction="ignore")
        writer.writeheader()
        writer.writerows(rows)


def metric(keys, actual):
    keys = set(keys)
    valid = [actual[k][0] for k in keys if actual[k][0] is not None]
    return {"selected": len(keys), "valid": len(valid), "invalid": len(keys)-len(valid),
            "wins": sum(v == 1 for v in valid), "seconds": sum(v == 2 for v in valid),
            "thirds": sum(v == 3 for v in valid), "hits": sum(v <= 3 for v in valid),
            "fourth_plus": sum(v >= 4 for v in valid),
            "rate": sum(v <= 3 for v in valid)/len(valid) if valid else None,
            "races": len({r for r,n in keys})}


def race_label(rid: str) -> str:
    _, venue, number = parse_race_id(rid)
    return f"{VENUE[venue]}{number}R"


def describe(keys, actual, names):
    return "、".join(f"#{n} {names[rid,n]}({actual[rid,n][0] if actual[rid,n][0] is not None else '無効'}着)"
                    for rid,n in sorted(keys)) if keys else "—"


def main() -> None:
    if OUT.exists():
        raise RuntimeError("STOP_DIAGNOSTIC_OUTPUT_EXISTS")
    pre, complete = read(PRE), read(POST_DIR / "complete.json")
    lane_summary = read(POST_DIR / "lane_summary.json")
    selected_rows = read(POST_DIR / "selected_horse_outcomes.json")
    if (pre.get("status"), pre.get("race_count"), pre.get("horse_count"), pre.get("result_access_count")) != ("COMPLETE",19,277,0):
        raise RuntimeError("STOP_FORMAL_PRE_STATE")
    if complete.get("status") != "COMPLETE" or complete.get("date") != DATE or set(pre["lanes"]) != set(LANES):
        raise RuntimeError("STOP_FORMAL_POST_STATE")
    if sha(POST_DIR / "lane_summary.json") != complete["lane_summary_sha256"] or sha(POST_DIR / "selected_horse_outcomes.json") != complete["selected_horse_outcomes_sha256"]:
        raise RuntimeError("STOP_FORMAL_POST_SHA")
    for lane, record in pre["lanes"].items():
        if sha(path_of(record["selection_path"])) != record["selection_sha256"] or sha(path_of(record["authority_path"])) != record["authority_sha256"]:
            raise RuntimeError("STOP_PRE_SHA:"+lane)
    for lane, record in complete["lane_artifacts"].items():
        if sha(Path(record["path"])) != record["sha256"]:
            raise RuntimeError("STOP_POST_LANE_SHA:"+lane)
    b1_record = complete.get("b1_diagnostic", {})
    if b1_record.get("status") != "COMPLETE" or sha(Path(b1_record["path"])) != b1_record.get("sha256"):
        raise RuntimeError("STOP_B1_POST")
    b1_post = read(Path(b1_record["path"]))
    b1_pre = read(B1_PRE)
    if b1_post["selection_sha256"] != sha(B1_PRE) or b1_pre["evidence_credit"] != 0:
        raise RuntimeError("STOP_B1_PRE_OR_ROLE")
    sources, digests = result_sources(DATE)
    if digests != complete["result_sha256"]:
        raise RuntimeError("STOP_RESULT_SHA_CHANGED")
    current_root = ROOT / f"reports/prospective_prediction_{DATE}_formal_trace_v1"
    index = read(current_root / "race_index.json")["race_index"]
    if len(index) != 19 or sum(r["horse_count"] for r in index) != 277:
        raise RuntimeError("STOP_CURRENT_POPULATION")
    races = {r["race_id"]:read(current_root / r["artifact"]) for r in index}
    race_ids = sorted(races,key=lambda r:(list(VENUE).index(parse_race_id(r)[1]),parse_race_id(r)[2]))
    names, actual, current_horse, trace = {}, {}, {}, {}
    for rid, race in races.items():
        _,venue,number = parse_race_id(rid)
        source = sources[JAPANESE_VENUE[venue],number]
        trace[rid] = {int(h["horse_number"]):h for h in race["buy_gate_trace"]["horses"]}
        for h in race["ranked_results"]:
            key=(rid,int(h["horse_number"]))
            names[key]=h["horse_name"]
            current_horse[key]=h
            valid, finish, hit=outcome(source,key[1])
            actual[key]=(finish,valid,hit)
    if len(names)!=277 or any(len(trace[r])!=len(races[r]["ranked_results"]) for r in race_ids):
        raise RuntimeError("STOP_HORSE_IDENTITY")
    selected={lane:set() for lane in (*LANES,"B1")}
    for row in selected_rows:
        key=(row["race_id"],int(row["horse_number"]))
        if key not in names or row["finish"]!=actual[key][0] or bool(row["valid_result"])!=actual[key][1]:
            raise RuntimeError("STOP_FORMAL_OUTCOME_MISMATCH")
        selected[row["lane"]].add(key)
    for row in b1_post["selected_horse_outcomes"]["B1"]:
        key=(row["race_id"],int(row["horse_number"]))
        if key not in names or row["finish"]!=actual[key][0] or bool(row["valid_result"])!=actual[key][1]:
            raise RuntimeError("STOP_B1_OUTCOME_MISMATCH")
        selected["B1"].add(key)
    for lane in LANES:
        if metric(selected[lane],actual)["hits"]!=lane_summary["lane_metrics"][lane]["hits"] or len(selected[lane])!=pre["lanes"][lane]["selected_count"]:
            raise RuntimeError("STOP_LANE_METRIC_MISMATCH:"+lane)
    if metric(selected["B1"],actual)["hits"]!=b1_post["metrics"]["B1"]["top3_hits"]:
        raise RuntimeError("STOP_B1_METRIC_MISMATCH")

    # Only complete per-race rankings enter family and ranking comparisons.
    ranks={lane:defaultdict(dict) for lane in LANES}
    for key,h in current_horse.items():
        ranks["CURRENT"][key[0]][key[1]]=int(h["rank"])
    exp=read(path_of(pre["lanes"]["EXP024"]["selection_path"]))
    plj=read(path_of(pre["lanes"]["PL_JOCKEY"]["selection_path"]))
    anew=read(path_of(pre["lanes"]["A_NEW"]["selection_path"]))
    v5=read(path_of(pre["lanes"]["INDEPENDENT_V5"]["selection_path"]))
    rank1=read(path_of(pre["lanes"]["CURRENT_RANK1"]["selection_path"]))
    for lane,rows,horse_field,rank_field in (("EXP024",exp["races"],"horses","pl_rank"),("PL_JOCKEY",plj["races"],"horses","candidate_rank"),("A_NEW",anew["races"],"horses","a_new_rank")):
        for row in rows:
            for h in row[horse_field]:
                ranks[lane][row["race_id"]][int(h["horse_number"])]=int(h[rank_field])
    for row in v5["races"]:
        for h in row.get("candidate_horses",[]):
            ranks["INDEPENDENT_V5"][row["race_id"]][int(h["horse_number"])]=int(h["shadow_ai_rank"])
    for h in rank1["selections"]:
        ranks["CURRENT_RANK1"][h["race_id"]][int(h["selected_horse_number"])]=int(h["stored_rank"])

    OUT.mkdir(parents=False)
    lane_rows=[]
    for lane in (*LANES,"B1"):
        m=metric(selected[lane],actual)
        lane_rows.append({"lane":lane,"role":"FORMAL_BUY" if lane=="CURRENT" else "B1_DIAGNOSTIC_EVIDENCE_0" if lane=="B1" else "FROZEN_LANE_SELECTION",**m})
    write_csv("lane_performance.csv",lane_rows,list(lane_rows[0]))
    all_selected=set().union(*[selected[lane] for lane in LANES])
    overlap_rows=[]
    for group,keys in (("one_lane",{k for k in all_selected if sum(k in selected[l] for l in LANES)==1}),
                       ("two_lanes",{k for k in all_selected if sum(k in selected[l] for l in LANES)==2}),
                       ("three_plus",{k for k in all_selected if sum(k in selected[l] for l in LANES)>=3})):
        overlap_rows.append({"group":group,"lanes":"ALL_7",**metric(keys,actual),"horses":describe(keys,actual,names)})
    for count in (2,3):
        for combination in itertools.combinations(LANES,count):
            keys=set.intersection(*(selected[l] for l in combination))
            overlap_rows.append({"group":f"specific_{count}","lanes":"+".join(combination),**metric(keys,actual),"horses":describe(keys,actual,names)})
    write_csv("lane_overlap_performance.csv",overlap_rows,list(overlap_rows[0]))

    current_family={(rid,n) for rid in race_ids for n in ranks["CURRENT"][rid] if ranks["CURRENT"][rid][n]<=3}
    current_family|={(rid,n) for lane in ("CURRENT_RANK1","INDEPENDENT_V5") for rid in race_ids for n in ranks[lane][rid] if ranks[lane][rid][n]<=3}
    pl_family={(rid,n) for lane in ("EXP024","PL_JOCKEY","A_NEW") for rid in race_ids for n in ranks[lane][rid] if ranks[lane][rid][n]<=3}
    family_rows=[]
    for group,keys in (("CURRENT_AND_PL",current_family&pl_family),("CURRENT_ONLY",current_family-pl_family),("PL_ONLY",pl_family-current_family)):
        family_rows.append({"group":group,**metric(keys,actual),"horses":describe(keys,actual,names)})
    write_csv("family_agreement_performance.csv",family_rows,list(family_rows[0]))

    current_b1=[]
    for group,keys in (("BOTH",selected["CURRENT"]&selected["B1"]),("CURRENT_ONLY",selected["CURRENT"]-selected["B1"]),("B1_ONLY",selected["B1"]-selected["CURRENT"])):
        current_b1.append({"group":group,**metric(keys,actual),"horses":describe(keys,actual,names)})
    write_csv("current_vs_b1.csv",current_b1,list(current_b1[0]))

    ranking_rows=[]
    for lane in LANES:
        for band in ("rank1","rank2","rank3","top3","top5"):
            threshold={"rank1":1,"rank2":2,"rank3":3,"top3":3,"top5":5}[band]
            keys={(rid,n) for rid in race_ids for n,v in ranks[lane][rid].items() if (v==threshold if band.startswith("rank") else v<=threshold)}
            coverage=sum(bool(ranks[lane][rid]) for rid in race_ids)
            m=metric(keys,actual)
            actual_top3={key for key,val in actual.items() if key[0] in race_ids and val[2] is True}
            captured=len(keys&actual_top3)
            ranking_rows.append({"lane":lane,"band":band,"ranking_scope":"UNAVAILABLE" if lane=="E1" else "FULL_FIELD" if lane in ("CURRENT","EXP024","PL_JOCKEY","A_NEW") else "PARTIAL_SAVED_ONLY","races_with_rank":coverage,"actual_top3_captured":captured if band=="top3" else "",**m})
    write_csv("ranking_performance.csv",ranking_rows,list(ranking_rows[0]))

    gate_rows=[]
    for key,h in current_horse.items():
        if int(h["rank"])>3 or key in selected["CURRENT"]:
            continue
        tr=trace[key[0]][key[1]]
        reasons=[(name,not bool(tr.get(field))) for name,field in (("risk_guard","risk_guard_pass"),("absolute_quality","absolute_quality_pass"),("relative_superiority","relative_advantage_pass"),("reliability","effective_reliability_pass"))]
        reasons=[name for name,failed in reasons if failed]
        if "UNCONVERGED" in str(h.get("buy_v1_rc1_race_state","")):
            reasons.append("UNCONVERGED")
        if not reasons:
            reasons.append("OTHER_OR_UNKNOWN")
        gate_rows.append({"race_id":key[0],"race":race_label(key[0]),"horse_number":key[1],"horse_name":names[key],"rank":h["rank"],"finish":actual[key][0],"valid_result":actual[key][1],"top3":actual[key][2],"failed_gates":"|".join(reasons),"composite_major_risks":"重大リスクが複数" in h.get("risks",[]),"risk_text":"|".join(h.get("risks",[])),"rc1_reason":h.get("buy_v1_rc1_reason","")})
    write_csv("buy_gate_exclusion_review.csv",gate_rows,list(gate_rows[0]) if gate_rows else ["race_id","race","horse_number","horse_name","rank","finish","valid_result","top3","failed_gates","composite_major_risks","risk_text","rc1_reason"])

    pace_rows=[]
    for rid,by_horse in trace.items():
        for n,tr in by_horse.items():
            key=(rid,n)
            pace_rows.append({"race_id":rid,"race":race_label(rid),"horse_number":n,"horse_name":names[key],"predicted_pace":tr.get("pace_prediction","UNKNOWN"),"pace_style":tr.get("pace_style","UNKNOWN"),"current_buy":key in selected["CURRENT"],"finish":actual[key][0],"valid_result":actual[key][1],"top3":actual[key][2],"pace_risk":"|".join(x for x in tr.get("risk_summary",[]) if "展開" in x or "ペース" in x or "ラップ" in x)})
    write_csv("pace_style_review.csv",pace_rows,list(pace_rows[0]))

    detail=[]
    for key in sorted(names):
        rid,n=key
        h=current_horse[key]
        row={"race_id":rid,"race":race_label(rid),"horse_number":n,"horse_name":names[key],"finish":actual[key][0],"valid_result":actual[key][1],"top3":actual[key][2],"current_rank":h["rank"],"current_buy":key in selected["CURRENT"],"b1_diagnostic":key in selected["B1"],"current_pace":trace[rid][n].get("pace_prediction",""),"pace_style":trace[rid][n].get("pace_style","")}
        for lane in LANES[1:]:
            row[lane.lower()+"_selected"]=key in selected[lane]
            row[lane.lower()+"_rank"]=ranks[lane][rid].get(n,"")
        detail.append(row)
    write_csv("race_level_details.csv",detail,list(detail[0]))

    # Human-readable race review is limited to source-observed facts; no new rule.
    lines=["# 2026-11-14 正式POST・全19レース分析","","正式PREと正式POSTの照合。順位・選出は事前凍結Artifact、着順は承認済みResult semantics。B1は診断でBUY権限なし。",""]
    for rid in race_ids:
        keys={k for k in names if k[0]==rid}
        winners=sorted((k for k in keys if actual[k][2] is True),key=lambda k:actual[k][0])
        current={k for k in selected["CURRENT"] if k[0]==rid}
        b1={k for k in selected["B1"] if k[0]==rid}
        excluded=[k for k in keys if int(current_horse[k]["rank"])<=3 and k not in current and actual[k][2] is True]
        lines += [f"## {race_label(rid)}（{len(keys)}頭）","",f"- 実際の1〜3着: {describe(winners,actual,names)}",f"- Current BUY: {describe(current,actual,names)}",f"- B1診断: {describe(b1,actual,names)}"]
        for lane in LANES[1:]:
            lines.append(f"- {lane}選出: {describe({k for k in selected[lane] if k[0]==rid},actual,names)}")
        family_both=(current_family&pl_family)&keys
        lines += [f"- Current系・PL系ともTop3: {describe(family_both,actual,names)}",f"- Current Top3評価からBUY除外された好走馬: {describe(excluded,actual,names)}",f"- Current Rank1: {describe({k for k in keys if current_horse[k]['rank']==1},actual,names)}", "- 判断差: CurrentとB1の選出差およびPL系との順位差を上記とrace_level_details.csvで確認。原因は保存済みgate/risk情報の範囲に限定。", ""]
    (OUT/"race_analysis.md").write_text("\n".join(lines),encoding="utf-8")

    gate_hit=[row for row in gate_rows if row["top3"] is True]
    pace_count=Counter(row["predicted_pace"] for row in pace_rows if row["current_buy"])
    style_count=Counter(row["pace_style"] for row in pace_rows if row["current_buy"])
    daily=["# 2026-11-14 正式POST・レーン実績総括","",f"正式PRE 19レース277頭。11/15正式PRE Freeze後に11/14の確定Resultを照合。正式POST Manifest SHA256: {sha(POST_DIR/'complete.json')}。", "", "## レーン別選出成績","","| レーン | 有効/選出 | 3着以内 | 3着内率 | 1着 |", "|---|---:|---:|---:|---:|"]
    daily += [f"| {r['lane']} | {r['valid']}/{r['selected']} | {r['hits']} | {r['rate']:.1%} | {r['wins']} |" for r in lane_rows]
    daily += ["","## CurrentとB1","",f"共通 {current_b1[0]['selected']}頭・{current_b1[0]['hits']}的中、Currentのみ {current_b1[1]['selected']}頭・{current_b1[1]['hits']}的中、B1のみ {current_b1[2]['selected']}頭・{current_b1[2]['hits']}的中。B1の選出数はCurrentと同じだが配分レースが異なる。", "", "## Current系とPL系のTop3","", "Current/Rank1/V5をCurrent系、EXP024/PL+J/A_newをPL系とし、同一馬は各系統内で一度だけ数える。E1・B1には保存済みレース内順位がないため含めない。", ""]
    daily += [f"- {r['group']}: {r['hits']}/{r['valid']}（{r['rate']:.1%}）、{r['races']}レース" for r in family_rows]
    daily += ["","## BUY gateと展開","",f"Current Top3評価ながら非BUYの好走馬は {len(gate_hit)}頭。個別の不合格gateと複数理由の重複はbuy_gate_exclusion_review.csvを参照。",f"Current BUY馬の保存済み予測ペース分布: {dict(pace_count)}。脚質分布: {dict(style_count)}。実際のペースは承認済みResultに定義された項目がなく、着順から推測しない。", "", "## 解釈と次の検証", "", "B1・PL系の当日成績は探索的な診断。1日で優劣や改善効果は確定できない。PL系の複数レーンは情報源を共有するため、組み合わせ間の母集団は重複し、独立票数ではない。改善候補はCurrent Top3の非BUY・B1のみ選出の事前固定集合を別開催日でも照合すること。新BUY条件は作らない。", ""]
    (OUT/"daily_summary.md").write_text("\n".join(daily),encoding="utf-8")
    source_paths=[PRE,POST_DIR/"complete.json",POST_DIR/"lane_summary.json",POST_DIR/"selected_horse_outcomes.json",B1_PRE,Path(b1_record["path"]),current_root/"race_index.json"]
    source_paths += [current_root/r["artifact"] for r in index]
    source_paths += [path_of(record["selection_path"]) for record in pre["lanes"].values()]
    source_paths += [Path(record["path"]) for record in complete["lane_artifacts"].values()]
    source_paths += [ROOT/f"data/raw/target/daily_result_list/{kind}_{DATE}.csv" for kind in ("馬番順着順","着順馬番")]
    outputs=sorted(p for p in OUT.iterdir() if p.is_file())
    manifest={"date":DATE,"created_at_jst":datetime.now(timezone(timedelta(hours=9))).isoformat(),"role":"POST_DERIVED_EXPLORATORY_DIAGNOSTIC","formal_post_manifest_sha256":sha(POST_DIR/"complete.json"),"source_files":[{"path":str(p),"sha256":sha(p)} for p in dict.fromkeys(source_paths)],"output_files":[{"path":str(p),"sha256":sha(p)} for p in outputs],"limitations":["One race day only","E1/B1 lack per-race rank","Rank1/V5 rank coverage partial","Lane families share sources","Actual pace unavailable"]}
    with (OUT/"source_manifest.json").open("x",encoding="utf-8") as stream:
        json.dump(manifest,stream,ensure_ascii=False,indent=2)
        stream.write("\n")
    print(json.dumps({"status":"COMPLETE","races":len(race_ids),"horses":len(names),"lane_metrics":{r['lane']:(r['hits'],r['valid']) for r in lane_rows},"current_b1":{r['group']:(r['hits'],r['valid']) for r in current_b1},"family":{r['group']:(r['hits'],r['valid']) for r in family_rows},"gate_excluded_top3_hits":len(gate_hit)},ensure_ascii=False))


if __name__=="__main__":
    main()
