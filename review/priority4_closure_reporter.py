"""Freeze already-saved normalized baseline CSVs; never invokes production code."""
from __future__ import annotations
import argparse, csv, hashlib, json
from pathlib import Path

DATES=("20260704","20260705","20260711","20260712","20260725","20260726","20260801","20260802")

def sha(path: Path) -> str: return hashlib.sha256(path.read_bytes()).hexdigest()
def rows(path: Path):
    with path.open(encoding="utf-8-sig",newline="") as f: return list(csv.DictReader(f))
def canonical_hash(data, fields):
    value=sorted([[str(r.get(k,"")) for k in fields] for r in data])
    return hashlib.sha256(json.dumps(value,ensure_ascii=False,separators=(",",":")).encode()).hexdigest()

def build(race: Path, horse: Path, sources: Path, out: Path) -> dict:
    out.mkdir(parents=True,exist_ok=True); rr,hh=rows(race),rows(horse)
    src=json.loads(sources.read_text(encoding="utf-8")); covered=sorted({str(x.get("race_date","")) for x in rr})
    source_dates=sorted({str(x.get("race_date","")) for x in src.get("sources",[])})
    errors=[]
    if source_dates != list(DATES): errors.append("SOURCE_DATE_COVERAGE_MISMATCH")
    if any(x.get("source_evaluation_origin") == "READ_ONLY_REPLAY" for x in src.get("sources",[])):
        errors.append("READ_ONLY_REPLAY_OUTPUT_USED_AS_SOURCE")
    if any(not x.get("source_race_sha256") or not x.get("source_horse_sha256") for x in src.get("sources",[]) if x.get("race_count",0)):
        errors.append("SOURCE_HASH_MISSING")
    rp=out/"keibaai_baseline_8days_v1_race.csv"; hp=out/"keibaai_baseline_8days_v1_horse.csv"
    rp.write_bytes(race.read_bytes()); hp.write_bytes(horse.read_bytes())
    hashes={"race_baseline_sha256":sha(rp),"horse_baseline_sha256":sha(hp),
      "buy_set_sha256":canonical_hash([x for x in hh if str(x.get("buy_flag",x.get("decision",""))).upper() in ("1","TRUE","BUY")],("race_id","horse_number","horse_name")),
      "decision_set_sha256":canonical_hash(rr,("race_id","race_decision","race_state","buy_count")),
      "score_manifest_sha256":canonical_hash(hh,("race_id","horse_number","final_score","adjusted_score","decision_score"))}
    (out/"keibaai_baseline_8days_v1_sources.json").write_text(json.dumps(src,ensure_ascii=False,indent=2)+"\n",encoding="utf-8")
    hashes["source_manifest_sha256"]=sha(out/"keibaai_baseline_8days_v1_sources.json")
    status="BASELINE_FREEZE_COMPLETE" if not errors else "BASELINE_FREEZE_INCOMPLETE"
    manifest={"schema_version":"v1","status":status,"target_dates":list(DATES),"race_dates_with_rows":covered,
              "race_count":len(rr),"horse_count":len(hh),"buy_count":sum(str(x.get("buy_flag",x.get("decision",""))).upper() in ("1","TRUE","BUY") for x in hh),"hashes":hashes,"errors":errors}
    (out/"keibaai_baseline_8days_v1_manifest.json").write_text(json.dumps(manifest,ensure_ascii=False,indent=2)+"\n",encoding="utf-8")
    (out/"keibaai_baseline_8days_v1_summary.json").write_text(json.dumps(manifest,ensure_ascii=False,indent=2)+"\n",encoding="utf-8")
    return manifest

def main():
    p=argparse.ArgumentParser(); p.add_argument("--race",type=Path,required=True); p.add_argument("--horse",type=Path,required=True)
    p.add_argument("--sources",type=Path,required=True); p.add_argument("--output-dir",type=Path,default=Path("reports/baseline")); a=p.parse_args()
    print(json.dumps(build(a.race,a.horse,a.sources,a.output_dir),ensure_ascii=False,indent=2)); return 0
if __name__=="__main__": raise SystemExit(main())
