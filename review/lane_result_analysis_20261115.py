"""Derived 11/15 and 11/14-15 diagnostics from completed Formal POST only."""
from __future__ import annotations

import csv
import itertools
import json
from collections import Counter, defaultdict
from datetime import datetime, timedelta, timezone
from pathlib import Path

from review.candidate_generation_training_dataset_readiness_v1 import JAPANESE_VENUE, outcome, parse_race_id
from review.formal_post_daily_v1 import result_sources, sha
from review.lane_result_analysis_20261114 import LANES, VENUE, metric, race_label, read, path_of, describe


ROOT = Path(__file__).resolve().parents[1]
DATE = "20261115"
OUT = ROOT / "reports/lane_result_analysis_20261115"
TWO = ROOT / "reports/lane_result_summary_20261114_15"


def write_csv(folder: Path, name: str, rows: list[dict], fields: list[str]) -> None:
    with (folder / name).open("x", encoding="utf-8-sig", newline="") as stream:
        writer = csv.DictWriter(stream, fieldnames=fields, extrasaction="ignore")
        writer.writeheader()
        writer.writerows(rows)


def load_day(date: str) -> dict:
    pre_path = ROOT / f"reports/formal_pre_daily/{date}/summary.json"
    post_path = ROOT / f"reports/formal_post_daily_v1/{date}/complete.json"
    pre, post = read(pre_path), read(post_path)
    if pre.get("status") != post.get("status") or pre.get("status") != "COMPLETE" or pre.get("date") != post.get("date") or pre.get("date") != date:
        raise RuntimeError("STOP_PRE_POST_STATE:" + date)
    if pre.get("result_access_count") != 0 or set(pre["lanes"]) != set(LANES):
        raise RuntimeError("STOP_PRE_ROLE:" + date)
    for lane, item in pre["lanes"].items():
        if sha(path_of(item["selection_path"])) != item["selection_sha256"] or sha(path_of(item["authority_path"])) != item["authority_sha256"]:
            raise RuntimeError("STOP_PRE_SHA:" + lane)
    for lane, item in post["lane_artifacts"].items():
        if sha(Path(item["path"])) != item["sha256"]:
            raise RuntimeError("STOP_POST_SHA:" + lane)
    post_root = post_path.parent
    if sha(post_root / "lane_summary.json") != post["lane_summary_sha256"] or sha(post_root / "selected_horse_outcomes.json") != post["selected_horse_outcomes_sha256"]:
        raise RuntimeError("STOP_POST_COORDINATOR_SHA")
    lane_summary = read(post_root / "lane_summary.json")
    b1_post_meta = post.get("b1_diagnostic", {})
    if b1_post_meta.get("status") != "COMPLETE" or sha(Path(b1_post_meta["path"])) != b1_post_meta.get("sha256"):
        raise RuntimeError("STOP_B1_POST:" + date)
    b1_post = read(Path(b1_post_meta["path"]))
    b1_pre_path = ROOT / f"reports/formal_pre_daily/{date}/b1_diagnostic/selection.json"
    b1_pre = read(b1_pre_path)
    if b1_pre["evidence_credit"] != 0 or b1_post["selection_sha256"] != sha(b1_pre_path):
        raise RuntimeError("STOP_B1_PRE:" + date)
    sources, digests = result_sources(date)
    if digests != post["result_sha256"]:
        raise RuntimeError("STOP_RESULT_SHA:" + date)
    current_root = ROOT / f"reports/prospective_prediction_{date}_formal_trace_v1"
    index_path = current_root / "race_index.json"
    index = read(index_path)["race_index"]
    if len(index) != pre["race_count"] or sum(int(x["horse_count"]) for x in index) != pre["horse_count"]:
        raise RuntimeError("STOP_PRE_POPULATION:" + date)
    races = {x["race_id"]:read(current_root / x["artifact"]) for x in index}
    race_ids = sorted(races,key=lambda rid:(list(VENUE).index(parse_race_id(rid)[1]),parse_race_id(rid)[2]))
    names, actual, current_horse, traces = {}, {}, {}, {}
    for rid,race in races.items():
        _,venue,number = parse_race_id(rid)
        source = sources[JAPANESE_VENUE[venue],number]
        traces[rid] = {int(h["horse_number"]):h for h in race["buy_gate_trace"]["horses"]}
        for h in race["ranked_results"]:
            key=(rid,int(h["horse_number"]))
            if key in names:
                raise RuntimeError("STOP_DUPLICATE_HORSE")
            names[key]=h["horse_name"]
            current_horse[key]=h
            valid,finish,hit=outcome(source,key[1])
            actual[key]=(finish,valid,hit)
    if len(names)!=pre["horse_count"]:
        raise RuntimeError("STOP_HORSE_COUNT")
    selected={lane:set() for lane in (*LANES,"B1")}
    for row in read(post_root / "selected_horse_outcomes.json"):
        key=(row["race_id"],int(row["horse_number"]))
        if key not in actual or row["finish"] != actual[key][0] or bool(row["valid_result"]) != actual[key][1]:
            raise RuntimeError("STOP_SELECTED_RESULT_JOIN")
        selected[row["lane"]].add(key)
    for row in b1_post["selected_horse_outcomes"]["B1"]:
        key=(row["race_id"],int(row["horse_number"]))
        if key not in actual or row["finish"] != actual[key][0] or bool(row["valid_result"]) != actual[key][1]:
            raise RuntimeError("STOP_B1_RESULT_JOIN")
        selected["B1"].add(key)
    for lane in LANES:
        m=metric(selected[lane],actual)
        if m["hits"]!=lane_summary["lane_metrics"][lane]["hits"] or m["valid"]!=lane_summary["lane_metrics"][lane]["valid"] or m["selected"]!=pre["lanes"][lane]["selected_count"]:
            raise RuntimeError("STOP_LANE_METRIC:"+lane)
    b1_m=metric(selected["B1"],actual)
    if (b1_m["selected"],b1_m["valid"],b1_m["hits"]) != tuple(b1_post["metrics"]["B1"][k] for k in ("selected","valid","top3_hits")):
        raise RuntimeError("STOP_B1_METRIC")

    data={lane:read(path_of(pre["lanes"][lane]["selection_path"])) for lane in LANES if lane!="CURRENT"}
    ranks={lane:defaultdict(dict) for lane in LANES}
    for key,h in current_horse.items():
        ranks["CURRENT"][key[0]][key[1]]=int(h["rank"])
    for lane,field in (("EXP024","pl_rank"),("PL_JOCKEY","candidate_rank"),("A_NEW","a_new_rank")):
        for row in data[lane]["races"]:
            for h in row["horses"]:
                ranks[lane][row["race_id"]][int(h["horse_number"])]=int(h[field])
    for row in data["CURRENT_RANK1"]["selections"]:
        ranks["CURRENT_RANK1"][row["race_id"]][int(row["selected_horse_number"])]=int(row["stored_rank"])
    for row in data["INDEPENDENT_V5"]["races"]:
        for h in row.get("candidate_horses",[]):
            ranks["INDEPENDENT_V5"][row["race_id"]][int(h["horse_number"])]=int(h["shadow_ai_rank"])
    plj_h={(row["race_id"],int(h["horse_number"])):h for row in data["PL_JOCKEY"]["races"] for h in row["horses"]}
    e1_h={(h["race_id"],int(h["horse_number"])):h for h in data["E1"]["frozen_probabilities_consumed"]}
    b1_h={(h["race_id"],int(h["horse_number"])):h for h in b1_pre["selected_horses"]}
    if set(plj_h)!=set(names) or set(e1_h)!=set(names):
        raise RuntimeError("STOP_PROBABILITY_COVERAGE")
    current_family={(rid,n) for lane in ("CURRENT","CURRENT_RANK1","INDEPENDENT_V5") for rid in race_ids for n,rank in ranks[lane][rid].items() if rank<=3}
    pl_family={(rid,n) for lane in ("EXP024","PL_JOCKEY","A_NEW") for rid in race_ids for n,rank in ranks[lane][rid].items() if rank<=3}
    sources_list=[pre_path,post_path,post_root/"lane_summary.json",post_root/"selected_horse_outcomes.json",b1_pre_path,Path(b1_post_meta["path"]),index_path]
    sources_list += [current_root/x["artifact"] for x in index]
    sources_list += [path_of(x["selection_path"]) for x in pre["lanes"].values()]
    sources_list += [Path(x["path"]) for x in post["lane_artifacts"].values()]
    sources_list += [ROOT/f"data/raw/target/daily_result_list/{kind}_{date}.csv" for kind in ("馬番順着順","着順馬番")]
    return locals()


def e1_b1_groups(day: dict) -> list[dict]:
    a,b=day["selected"]["E1"],day["selected"]["B1"]
    return [{"group":group,**metric(keys,day["actual"])} for group,keys in (("AND",a&b),("OR",a|b),("E1_ONLY",a-b),("B1_ONLY",b-a))]


def family_groups(day: dict) -> list[dict]:
    a,b=day["current_family"],day["pl_family"]
    return [{"group":group,**metric(keys,day["actual"])} for group,keys in (("CURRENT_AND_PL",a&b),("CURRENT_ONLY",a-b),("PL_ONLY",b-a))]


def ranking_rows(day: dict) -> list[dict]:
    rows=[]
    for lane in LANES:
        for band in ("rank1","rank2","rank3","top3","top5"):
            cap={"rank1":1,"rank2":2,"rank3":3,"top3":3,"top5":5}[band]
            keys={(rid,n) for rid in day["race_ids"] for n,rank in day["ranks"][lane][rid].items() if (rank==cap if band.startswith("rank") else rank<=cap)}
            m=metric(keys,day["actual"])
            rows.append({"lane":lane,"band":band,"ranking_scope":"UNAVAILABLE" if lane=="E1" else "FULL_FIELD" if lane in ("CURRENT","EXP024","PL_JOCKEY","A_NEW") else "PARTIAL_SAVED_ONLY","races_with_rank":sum(bool(day["ranks"][lane][rid]) for rid in day["race_ids"]),"actual_top3_captured":m["hits"] if band=="top3" else "",**m})
    return rows


def gate_rows(day: dict) -> list[dict]:
    rows=[]
    for key,h in day["current_horse"].items():
        if int(h["rank"])>3 or key in day["selected"]["CURRENT"]:
            continue
        tr=day["traces"][key[0]][key[1]]
        reasons=[name for name,field in (("risk_guard","risk_guard_pass"),("absolute_quality","absolute_quality_pass"),("relative_superiority","relative_advantage_pass"),("reliability","effective_reliability_pass")) if not tr.get(field)]
        if "UNCONVERGED" in str(h.get("buy_v1_rc1_race_state","")):
            reasons.append("UNCONVERGED")
        if not reasons:
            reasons.append("OTHER_OR_UNKNOWN")
        rows.append({"race_id":key[0],"race":race_label(key[0]),"horse_number":key[1],"horse_name":day["names"][key],"rank":h["rank"],"finish":day["actual"][key][0],"valid_result":day["actual"][key][1],"top3":day["actual"][key][2],"failed_gates":"|".join(reasons),"composite_major_risks":"重大リスクが複数" in h.get("risks",[]),"risk_text":"|".join(h.get("risks",[])),"rc1_reason":h.get("buy_v1_rc1_reason","")})
    return rows


def main() -> None:
    if OUT.exists() or TWO.exists():
        raise RuntimeError("STOP_DIAGNOSTIC_OUTPUT_EXISTS")
    day=load_day(DATE)
    previous=load_day("20261114")
    if sha(previous["pre_path"]) != sha(ROOT/"reports/formal_pre_daily/20261114/summary.json") or sha(previous["post_path"]) != sha(ROOT/"reports/formal_post_daily_v1/20261114/complete.json"):
        raise RuntimeError("STOP_PREVIOUS_DAY_SHA")
    OUT.mkdir(parents=False)
    TWO.mkdir(parents=False)
    actual,names,selected=day["actual"],day["names"],day["selected"]
    lane_rows=[{"lane":lane,"role":"FORMAL_BUY" if lane=="CURRENT" else "B1_DIAGNOSTIC_EVIDENCE_0" if lane=="B1" else "FROZEN_LANE_SELECTION",**metric(selected[lane],actual)} for lane in (*LANES,"B1")]
    write_csv(OUT,"lane_performance.csv",lane_rows,list(lane_rows[0]))
    eb=e1_b1_groups(day)
    write_csv(OUT,"e1_b1_analysis.csv",eb,list(eb[0]))
    eb_h=[]
    for rid,n in sorted(selected["E1"]|selected["B1"]):
        key=(rid,n)
        eb_h.append({"race_id":rid,"race":race_label(rid),"horse_number":n,"horse_name":names[key],"e1_selected":key in selected["E1"],"b1_selected":key in selected["B1"],"pl_p_top3":day["e1_h"][key]["pl_probability"],"pl_jockey_p_top3":day["plj_h"][key]["candidate_p_top3"],"jockey_top3_lift":day["plj_h"][key]["jockey_top3_lift"],"finish":actual[key][0],"valid_result":actual[key][1],"top3":actual[key][2]})
    write_csv(OUT,"e1_b1_horse_details.csv",eb_h,list(eb_h[0]))
    pairs=[]
    for a,b in itertools.combinations((*LANES,"B1"),2):
        keys=selected[a]&selected[b]
        pairs.append({"lane_a":a,"lane_b":b,**metric(keys,actual),"horses":describe(keys,actual,names)})
    write_csv(OUT,"lane_pair_combinations.csv",pairs,list(pairs[0]))
    triples=[]
    for combo in itertools.combinations((*LANES,"B1"),3):
        keys=set.intersection(*(selected[lane] for lane in combo))
        triples.append({"lanes":"+".join(combo),**metric(keys,actual),"horses":describe(keys,actual,names)})
    write_csv(OUT,"lane_triple_combinations.csv",triples,list(triples[0]))
    family=family_groups(day)
    write_csv(OUT,"family_agreement_performance.csv",family,list(family[0]))
    ranking=ranking_rows(day)
    write_csv(OUT,"ranking_performance.csv",ranking,list(ranking[0]))
    gates=gate_rows(day)
    write_csv(OUT,"buy_gate_exclusion_review.csv",gates,list(gates[0]))
    detail=[]
    for rid,n in sorted(names):
        key=(rid,n); h=day["current_horse"][key]; tr=day["traces"][rid][n]
        row={"race_id":rid,"race":race_label(rid),"horse_number":n,"horse_name":names[key],"finish":actual[key][0],"valid_result":actual[key][1],"top3":actual[key][2],"current_rank":h["rank"],"current_buy":key in selected["CURRENT"],"b1_selected":key in selected["B1"],"predicted_pace":tr.get("pace_prediction","UNKNOWN"),"pace_style":tr.get("pace_style","UNKNOWN")}
        for lane in LANES[1:]:
            row[lane.lower()+"_selected"]=key in selected[lane]
            row[lane.lower()+"_rank"]=day["ranks"][lane][rid].get(n,"")
        detail.append(row)
    write_csv(OUT,"race_level_details.csv",detail,list(detail[0]))
    lines=["# 2026-11-15 正式POST・全21レース分析","","正式PREの保存済み選出と正式POSTを照合。B1は診断、Currentのみ正式BUY。実際のペースはResultにないため推測しない。",""]
    for rid in day["race_ids"]:
        keys={k for k in names if k[0]==rid}
        winners=sorted((k for k in keys if actual[k][2] is True),key=lambda k:actual[k][0])
        e1_b1=(selected["E1"]&selected["B1"])&keys
        excluded={k for k in keys if day["current_horse"][k]["rank"]<=3 and k not in selected["CURRENT"] and actual[k][2] is True}
        captured={k for k in keys if day["ranks"]["CURRENT"][rid].get(k[1],99)<=3 and actual[k][2] is True}
        lines += [f"## {race_label(rid)}（{len(keys)}頭）","",f"- 実際の1〜3着: {describe(winners,actual,names)}",f"- Current BUY: {describe(selected['CURRENT']&keys,actual,names)}"]
        for lane in LANES[1:]:
            lines.append(f"- {lane}選出: {describe(selected[lane]&keys,actual,names)}")
        lines += [f"- B1診断: {describe(selected['B1']&keys,actual,names)}",f"- E1×B1一致: {describe(e1_b1,actual,names)}",f"- Current系×PL系Top3一致: {describe((day['current_family']&day['pl_family'])&keys,actual,names)}",f"- Current順位Top3が捉えた好走馬: {describe(captured,actual,names)}",f"- Current Top3でBUYから外れた好走馬: {describe(excluded,actual,names)}","- 判断差の原因は保存済みgate・risk・確率情報の範囲で確認。順位を持たないE1/B1に順位を補わない。",""]
    (OUT/"race_analysis.md").write_text("\n".join(lines),encoding="utf-8")
    gate_hits=[r for r in gates if r["top3"] is True]
    buy_styles=Counter(day["traces"][rid][n].get("pace_style","UNKNOWN") for rid,n in selected["CURRENT"])
    buy_paces=Counter(day["traces"][rid][n].get("pace_prediction","UNKNOWN") for rid,n in selected["CURRENT"])
    daily=["# 2026-11-15 正式POST・実績総括","",f"対象21レース306頭。正式POST Manifest SHA256: {sha(day['post_path'])}。B1は別枠診断、正式BUYはCurrentのみ。", "", "| レーン | 有効/選出 | 3着以内 | 3着内率 | 無効 |", "|---|---:|---:|---:|---:|"]
    daily += [f"| {r['lane']} | {r['valid']}/{r['selected']} | {r['hits']} | {r['rate']:.1%} | {r['invalid']} |" for r in lane_rows]
    daily += ["","## E1とB1","", "| 集合 | 的中/有効 | 率 | 対象レース |", "|---|---:|---:|---:|"]
    daily += [f"| {r['group']} | {r['hits']}/{r['valid']} | {r['rate']:.1%} | {r['races']} |" for r in eb]
    daily += ["","## Current系・PL系Top3","", "Current/Rank1/V5をCurrent系、EXP024/PL+J/A_newをPL系として同一馬を系統内で一度だけ数える。E1/B1には保存されたレース内順位がない。", ""]
    daily += [f"- {r['group']}: {r['hits']}/{r['valid']}（{r['rate']:.1%}）" for r in family]
    daily += ["","## BUY gateと脚質","",f"Current順位Top3の非BUY馬で3着以内だった馬: {len(gate_hits)}頭。gateの理由は重複を含む。",f"Current BUYの保存済み予測脚質: {dict(buy_styles)}。予測ペース: {dict(buy_paces)}。実際のペースはUNKNOWN。", "", "2日分だけで新BUY条件を採用しない。各組み合わせは探索的で、同一馬が複数組み合わせへ重複する。", ""]
    (OUT/"daily_summary.md").write_text("\n".join(daily),encoding="utf-8")

    # Two-day totals use unique date-scoped keys and sums of hits/valid counts.
    combined_actual={**previous["actual"],**actual}
    if len(combined_actual)!=len(previous["actual"])+len(actual):
        raise RuntimeError("STOP_TWO_DAY_RACE_DUPLICATE")
    combined_selected={lane:previous["selected"][lane]|selected[lane] for lane in (*LANES,"B1")}
    two_lane=[]
    for lane in (*LANES,"B1"):
        a,b=metric(previous["selected"][lane],previous["actual"]),metric(selected[lane],actual)
        c=metric(combined_selected[lane],combined_actual)
        if (c["hits"],c["valid"])!=(a["hits"]+b["hits"],a["valid"]+b["valid"]):
            raise RuntimeError("STOP_TWO_DAY_SUM")
        two_lane.append({"lane":lane,"day14_hits":a["hits"],"day14_valid":a["valid"],"day15_hits":b["hits"],"day15_valid":b["valid"],"total_selected":c["selected"],"total_valid":c["valid"],"total_invalid":c["invalid"],"total_hits":c["hits"],"total_rate":c["rate"]})
    write_csv(TWO,"lane_performance_two_day.csv",two_lane,list(two_lane[0]))
    two_eb=[]
    for group in ("AND","OR","E1_ONLY","B1_ONLY"):
        ea,ba=previous["selected"]["E1"],previous["selected"]["B1"]
        eb15,bb15=selected["E1"],selected["B1"]
        get=lambda x,y: x&y if group=="AND" else x|y if group=="OR" else x-y if group=="E1_ONLY" else y-x
        a,b=get(ea,ba),get(eb15,bb15)
        c=metric(a|b,combined_actual)
        two_eb.append({"group":group,"day14_hits":metric(a,previous["actual"])["hits"],"day14_valid":metric(a,previous["actual"])["valid"],"day15_hits":metric(b,actual)["hits"],"day15_valid":metric(b,actual)["valid"],**c})
    write_csv(TWO,"e1_b1_two_day.csv",two_eb,list(two_eb[0]))
    two_family=[]
    for group in ("CURRENT_AND_PL","CURRENT_ONLY","PL_ONLY"):
        get=lambda x,y: x&y if group=="CURRENT_AND_PL" else x-y if group=="CURRENT_ONLY" else y-x
        a,b=get(previous["current_family"],previous["pl_family"]),get(day["current_family"],day["pl_family"])
        two_family.append({"group":group,**metric(a|b,combined_actual)})
    write_csv(TWO,"family_agreement_two_day.csv",two_family,list(two_family[0]))
    two_rank=[]
    for a,b in zip(ranking_rows(previous),ranking):
        if (a["lane"],a["band"],a["ranking_scope"])!=(b["lane"],b["band"],b["ranking_scope"]):
            raise RuntimeError("STOP_RANK_DEFINITION_MISMATCH")
        total=a["valid"]+b["valid"]
        two_rank.append({"lane":a["lane"],"band":a["band"],"ranking_scope":a["ranking_scope"],"day14_hits":a["hits"],"day14_valid":a["valid"],"day15_hits":b["hits"],"day15_valid":b["valid"],"total_hits":a["hits"]+b["hits"],"total_valid":total,"total_rate":(a["hits"]+b["hits"])/total if total else None})
    write_csv(TWO,"ranking_two_day.csv",two_rank,list(two_rank[0]))
    prior_gate=gate_rows(previous)
    two_lines=["# 2026-11-14・15 正式POST 2日間総括","",f"11/14 PRE SHA {sha(previous['pre_path'])}、POST SHA {sha(previous['post_path'])}。11/15 PRE SHA {sha(day['pre_path'])}、POST SHA {sha(day['post_path'])}。", "", "| レーン | 11/14 | 11/15 | 2日合計 |", "|---|---:|---:|---:|"]
    two_lines += [f"| {r['lane']} | {r['day14_hits']}/{r['day14_valid']} | {r['day15_hits']}/{r['day15_valid']} | {r['total_hits']}/{r['total_valid']}（{r['total_rate']:.1%}） |" for r in two_lane]
    two_lines += ["","## E1とB1","", "| 集合 | 11/14 | 11/15 | 2日合計 |", "|---|---:|---:|---:|"]
    two_lines += [f"| {r['group']} | {r['day14_hits']}/{r['day14_valid']} | {r['day15_hits']}/{r['day15_valid']} | {r['hits']}/{r['valid']}（{r['rate']:.1%}） |" for r in two_eb]
    two_lines += ["","## 注意と次回観測","",f"Current Top3非BUYの好走馬は11/14に{sum(x['top3'] is True for x in prior_gate)}頭、11/15に{len(gate_hits)}頭。BUY gateの因果効果を示すものではない。", "2開催日だけでB1やE1+B1の性能を確定しない。B1は既定の正式6開催日時点でHumanが確認する。PL系の複数レーンは情報源を共有し、組み合わせ母集団は重複する。", ""]
    (TWO/"two_day_summary.md").write_text("\n".join(two_lines),encoding="utf-8")
    all_sources=list(dict.fromkeys(day["sources_list"]+previous["sources_list"]))
    for folder in (OUT,TWO):
        outputs=sorted(x for x in folder.iterdir() if x.is_file())
        manifest={"date_scope":["20261115"] if folder==OUT else ["20261114","20261115"],"created_at_jst":datetime.now(timezone(timedelta(hours=9))).isoformat(),"role":"POST_DERIVED_EXPLORATORY_DIAGNOSTIC","source_files":[{"path":str(p),"sha256":sha(p)} for p in all_sources],"output_files":[{"path":str(p),"sha256":sha(p)} for p in outputs],"limitations":["Two days only","E1/B1 have no saved per-race rank","Rank1/V5 rank coverage partial","Family lanes share information","Actual pace unavailable"]}
        with (folder/"source_manifest.json").open("x",encoding="utf-8") as stream:
            json.dump(manifest,stream,ensure_ascii=False,indent=2); stream.write("\n")
    print(json.dumps({"status":"COMPLETE","date":DATE,"races":len(day["race_ids"]),"horses":len(names),"lane":{r['lane']:(r['hits'],r['valid']) for r in lane_rows},"e1_b1":{r['group']:(r['hits'],r['valid']) for r in eb},"two_day":{r['lane']:(r['total_hits'],r['total_valid']) for r in two_lane}},ensure_ascii=False))


if __name__=="__main__":
    main()
