"""Locate historical four-file race assets without executing evaluation."""
from __future__ import annotations
import re
from collections import defaultdict
from pathlib import Path

PATTERNS={
 "entry":re.compile(r"^(race_\d{8}_[^_]+_[^_]+)_entry\.csv$"),
 "horses":re.compile(r"^(race_\d{8}_[^_]+_[^_]+)_horses\.csv$"),
 "race_result":re.compile(r"^(race_\d{8}_[^_]+_[^_]+)_result\.csv$"),
 "horse_result":re.compile(r"^horse_(\d{8}_[^_]+_[^_]+)_result\.csv$"),
}

def discover(root):
    found=defaultdict(lambda:{key:[] for key in PATTERNS})
    for path in Path(root).rglob("*.csv"):
        for role,pattern in PATTERNS.items():
            match=pattern.match(path.name)
            if match:
                race_id=match.group(1) if role!="horse_result" else "race_"+match.group(1)
                found[race_id][role].append(path.resolve());break
    rows=[]
    for race_id,assets in sorted(found.items()):
        missing=[key for key,paths in assets.items() if not paths]
        duplicate=[key for key,paths in assets.items() if len(paths)>1]
        status="READY" if not missing and not duplicate else ("DUPLICATE" if duplicate else "+".join(x.upper()+"_MISSING" for x in missing))
        parts=race_id.split("_")
        rows.append({"race_id":race_id,"race_date":parts[1],"racecourse":parts[2],"race_number":parts[3],"status":status,"missing":missing,"duplicate":duplicate,"assets":{key:[str(x) for x in value] for key,value in assets.items()}})
    return rows

