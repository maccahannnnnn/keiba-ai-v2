"""Stateful, additive ledger for Ranking Provenance PRE/POST artifacts."""
from __future__ import annotations

import csv
import hashlib
import json
from pathlib import Path


def _sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def _read(path):
    path = Path(path)
    return json.loads(path.read_text(encoding="utf-8")) if path.exists() else {
        "ledger": "ranking_provenance_v1", "entries": []
    }


def _write(path, payload):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return payload


def register_pre(path, manifest):
    payload = _read(path)
    with Path(manifest["summary_file"]).open(encoding="utf-8-sig", newline="") as handle:
        summary = list(csv.DictReader(handle))
    existing = {(row["race_id"], row["pipeline_version"]) for row in payload["entries"]}
    for race_id in sorted({row["race_id"] for row in summary}):
        key = (race_id, manifest["pipeline_version"])
        if key in existing:
            continue
        group = [row for row in summary if row["race_id"] == race_id]
        payload["entries"].append({
            "race_id": race_id,
            "race_date": manifest["race_date"],
            "pipeline_version": manifest["pipeline_version"],
            "source_version": manifest["source_version"],
            "pre_race_status": "PRE_RACE_COMPLETE",
            "post_race_status": "POST_RACE_PENDING",
            "pre_race_sha256": manifest["summary_sha256"],
            "post_race_sha256": "",
            "post_race_error": "",
            "horse_count": len(group),
            "provenance_complete_count": sum(str(row["provenance_complete"]).lower() == "true" for row in group),
            "trace_count": sum(int(row["trace_count"]) for row in group),
            "top5_boundary_tie_count": int(any(str(row["top5_boundary_tie"]).lower() == "true" for row in group)),
        })
        existing.add(key)
    return _write(path, payload)


def record_post(path, pre_race_file, post_race_file=None, error=""):
    payload = _read(path)
    pre_hash = _sha(pre_race_file)
    matched = [row for row in payload["entries"] if row.get("pre_race_sha256") == pre_hash]
    if not matched:
        raise ValueError("LEDGER_PRE_RACE_ENTRY_NOT_FOUND")
    post_hash = _sha(post_race_file) if post_race_file and Path(post_race_file).exists() else ""
    for row in matched:
        row["post_race_status"] = "POST_RACE_FAILED" if error else "POST_RACE_COMPLETE"
        row["post_race_sha256"] = post_hash
        row["post_race_error"] = str(error)
    return _write(path, payload)
