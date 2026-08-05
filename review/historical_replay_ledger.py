"""Isolated per-run ledger for CURRENT_CODE_REPLAY."""
from __future__ import annotations
import json
from datetime import datetime,timezone
from pathlib import Path

def now():return datetime.now(timezone.utc).isoformat()
def write(path,payload):
    path=Path(path)
    if path.exists():raise FileExistsError(f"HISTORICAL_LEDGER_ALREADY_EXISTS:{path}")
    path.write_text(json.dumps(payload,ensure_ascii=False,indent=2)+"\n",encoding="utf-8")
def save(path,run_id,entries):write(path,{"run_id":run_id,"pipeline_version":"HR_V1","entries":entries})
def entry(race_id,date,horse_count,status="DISCOVERED",**extra):
    stamp=now();value={"race_id":race_id,"race_date":date,"horse_count":horse_count,"provenance_complete_count":0,"trace_count":0,"top5_boundary_tie_count":0,"pre_race_sha256":"","post_race_sha256":"","status":status,"error":"","created_at":stamp,"updated_at":stamp};value.update(extra);return value

