"""Append-only-by-key ledger for Shadow Evidence; existing race keys are immutable."""
from __future__ import annotations
import json
from datetime import datetime,timezone
from pathlib import Path
from review.unconverged_shadow_evidence_collector import PIPELINE_VERSION
LEDGER_SCHEMA_VERSION="1.1"
def update_ledger(path,post_summary):
 path=Path(path);payload=json.loads(path.read_text(encoding="utf-8")) if path.exists() else {"ledger_schema_version":LEDGER_SCHEMA_VERSION,"pipeline_version":PIPELINE_VERSION,"entries":[]};existing={(x["race_id"],x["pipeline_version"]) for x in payload["entries"]}
 if payload.get("ledger_schema_version")!=LEDGER_SCHEMA_VERSION:raise ValueError("INVALID_RACE_LEVEL_AGGREGATION")
 for rid,race in post_summary.get("per_race",{}).items():
  key=(rid,PIPELINE_VERSION)
  if key in existing:continue
  payload["entries"].append({**race,"pre_race_status":"COMPLETE","post_race_status":"COMPLETE","source_sha256":post_summary.get("pre_race_sha256",""),"observed_at":datetime.now(timezone.utc).isoformat(),"pipeline_version":PIPELINE_VERSION})
  existing.add(key)
 path.parent.mkdir(parents=True,exist_ok=True);path.write_text(json.dumps(payload,ensure_ascii=False,indent=2)+"\n",encoding="utf-8");return payload
def trigger(payload):
 if payload.get("ledger_schema_version")!=LEDGER_SCHEMA_VERSION:return "INVALID_LEDGER_REJECTED"
 rows=payload.get("entries",[]);races=len(rows);days=len({x["race_date"] for x in rows});courses=len({x["race_id"].split("_")[2] for x in rows});post=all(x["post_race_status"]=="COMPLETE" for x in rows)
 if races<5:return "EVIDENCE_ACCUMULATING"
 if not post or days<2 or courses<2:return "REEVALUATION_HOLD"
 return "REEVALUATION_READY"
