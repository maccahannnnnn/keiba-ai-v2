"""POST-only result join for frozen Historical Replay PRE artifacts."""
from __future__ import annotations
import csv,hashlib,json
from pathlib import Path

HORSE_NUMBER_FIELDS=("馬番","horse_number")
FINISH_FIELDS=("確定着順","finish_position")
ABNORMAL_FIELDS=("異常コード","abnormal_code")

def sha(path):return hashlib.sha256(Path(path).read_bytes()).hexdigest()
def read_csv(path):
    for enc in ("utf-8-sig","cp932"):
        try:
            with Path(path).open(encoding=enc,newline="") as handle:return list(csv.DictReader(handle))
        except UnicodeDecodeError:continue
    raise ValueError(f"RESULT_ENCODING_UNSUPPORTED:{path}")
def _field(row,names,index,default=""):
    for name in names:
        if name in row:return row.get(name)
    values=list(row.values())
    return values[index] if len(values)>index else default
def result_horse_number(row):return str(_field(row,HORSE_NUMBER_FIELDS,4) or "").strip()
def result_semantics(row):
    raw_finish=str(_field(row,FINISH_FIELDS,0) or "").strip();abnormal=str(_field(row,ABNORMAL_FIELDS,1,"0") or "").strip()
    try:finish=int(raw_finish)
    except (TypeError,ValueError):finish=0
    valid=finish>0 and abnormal in {"","0"}
    return {"actual_finish":finish,"actual_top3":valid and finish<=3,"actual_top5":valid and finish<=5,"valid_result":valid}
def join(pre_file,race_result_file,horse_result_file,output_dir):
    pre_file=Path(pre_file);output_dir=Path(output_dir);payload=json.loads(pre_file.read_text(encoding="utf-8"));expected=payload["freeze"]["pre_race_sha256"]
    if sha(pre_file)!=expected:raise ValueError("PRE_SHA256_MISMATCH")
    results=read_csv(horse_result_file);lookup={result_horse_number(row):row for row in results};joined=[]
    for row in payload["horses"]:
        result=lookup.get(str(row.get("horse_number") or "").strip(),{});item=dict(row);item.update(result_semantics(result));joined.append(item)
    output_dir.mkdir(parents=True,exist_ok=True);out=output_dir/"post_joined.json"
    if out.exists():raise FileExistsError(f"HISTORICAL_POST_ALREADY_EXISTS:{out}")
    post={"cohort_type":"CURRENT_CODE_REPLAY","result_joined_after_pre_race_freeze":"YES","pre_race_sha256":expected,"race_result_path":str(Path(race_result_file).resolve()),"horse_result_path":str(Path(horse_result_file).resolve()),"race_result_sha256":sha(race_result_file),"horse_result_sha256":sha(horse_result_file),"horses":joined};out.write_text(json.dumps(post,ensure_ascii=False,indent=2)+"\n",encoding="utf-8")
    return out,sha(out),joined
