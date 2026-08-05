"""Join result labels to frozen Ranking Provenance without recalculation."""
from __future__ import annotations
import csv,hashlib
from pathlib import Path

ALLOWED_RESULT_FIELDS=("actual_finish","actual_top3","actual_top5","valid_result","invalid_result_reason")
def sha(path):return hashlib.sha256(Path(path).read_bytes()).hexdigest()
def load(path):
    with Path(path).open(encoding="utf-8-sig",newline="") as handle:return list(csv.DictReader(handle))
def join(pre_race_file,result_file,output_file,ledger_path=None):
    pre_race_file,result_file,output_file=map(Path,(pre_race_file,result_file,output_file))
    try:
        pre=load(pre_race_file);results=load(result_file)
        result_map={(row["race_id"],row["horse_number"]):row for row in results};out=[];pre_hash=sha(pre_race_file)
        for row in pre:
            result=result_map.get((row["race_id"],row["horse_number"]),{});joined=dict(row)
            for field in ALLOWED_RESULT_FIELDS:joined[field]=result.get(field,"")
            joined["pre_race_sha256"]=pre_hash;out.append(joined)
        if not out:raise ValueError("EMPTY_PRE_RACE_ARTIFACT")
        output_file.parent.mkdir(parents=True,exist_ok=True)
        with output_file.open("w",encoding="utf-8-sig",newline="") as handle:
            writer=csv.DictWriter(handle,fieldnames=list(out[0]));writer.writeheader();writer.writerows(out)
        if ledger_path:
            from review.ranking_provenance_ledger import record_post
            record_post(ledger_path,pre_race_file,output_file)
        return out
    except Exception as exc:
        if ledger_path and pre_race_file.exists():
            from review.ranking_provenance_ledger import record_post
            record_post(ledger_path,pre_race_file,error=str(exc))
        raise
