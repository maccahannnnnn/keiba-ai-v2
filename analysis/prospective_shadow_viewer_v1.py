"""Prospective, read-only Jockey Tier V1 comparison viewer.

The viewer consumes an already-saved Production pre-race horse summary and
TARGET entry CSVs.  It never constructs TargetTrialAdapter and never runs an
Evaluator, Decision Engine, Learning, Knowledge, or Replay component.
"""
from __future__ import annotations

import argparse
import copy
import csv
import hashlib
import json
import os
import re
import sys
from collections import defaultdict
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from analysis.jockey_shadow_read_only_parser_v1 import parse_entry_file
from analysis.jockey_tier_generation_v1 import stable_hash


REPORTS = ROOT / "reports"
FLAG_NAME = "PROSPECTIVE_SHADOW_VIEWER_ENABLED"
FLAG_DEFAULT = "OFF"
TIER_TABLE = REPORTS / "jockey_tier_table_v1.json"

FIELDS = [
    "race_id", "racecourse", "race_number", "horse_name",
    "Production_rank", "Production_decision", "Production_buy",
    "Shadow_rank", "Shadow_decision", "Shadow_buy", "rank_change",
    "decision_changed", "buy_changed", "jockey_tier", "tier_adjustment",
    "comment",
]

PROTECTED = {
    "target_trial_adapter": ROOT / "evaluation" / "target_trial_adapter.py",
    "decision_engine": ROOT / "engine" / "decision_engine.py",
    "race_decision_engine": ROOT / "engine" / "race_decision_engine.py",
    "target_entry_importer": ROOT / "importer" / "target_entry_importer.py",
    "learning": ROOT / "learning",
    "knowledge": ROOT / "knowledge",
}


class ViewerInputError(RuntimeError):
    pass


def flag_enabled(value=None) -> bool:
    raw = os.environ.get(FLAG_NAME, FLAG_DEFAULT) if value is None else value
    return raw is True or str(raw).strip().upper() in {"1", "TRUE", "ON", "YES"}


def _sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _tree_hash(path: Path) -> str:
    if path.is_file():
        return _sha(path)
    if not path.exists():
        return "MISSING"
    digest = hashlib.sha256()
    for item in sorted(p for p in path.rglob("*") if p.is_file() and "__pycache__" not in p.parts and p.suffix not in {".pyc", ".pyo"}):
        digest.update(item.relative_to(path).as_posix().encode("utf-8"))
        digest.update(hashlib.sha256(item.read_bytes()).digest())
    return digest.hexdigest()


def protected_snapshot() -> dict[str, str]:
    return {name: _tree_hash(path) for name, path in PROTECTED.items()}


def _int(value, default=0) -> int:
    try:
        return int(float(value))
    except (TypeError, ValueError):
        return default


def _float(value, default=0.0) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


def load_tiers(path: Path = TIER_TABLE) -> tuple[dict[str, dict], dict]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    if stable_hash(payload.get("rows", [])) != payload.get("table_sha256"):
        raise ViewerInputError("TIER_TABLE_SHA_MISMATCH")
    return {row["jockey_name"]: row for row in payload["rows"]}, payload


def load_production(path: Path, target_date: str) -> list[dict]:
    if not path.is_file():
        raise ViewerInputError(f"PRODUCTION_INPUT_MISSING:{path}")
    with path.open("r", encoding="utf-8-sig", newline="") as handle:
        reader = csv.DictReader(handle)
        required = {"race_id", "rank", "horse_name", "decision", "adjusted_score"}
        if not reader.fieldnames or not required <= set(reader.fieldnames):
            raise ViewerInputError("PRODUCTION_SCHEMA_INVALID")
        rows = [dict(row) for row in reader]
    if not rows:
        raise ViewerInputError("PRODUCTION_INPUT_EMPTY")
    keys = [(row["race_id"], row["horse_name"]) for row in rows]
    if len(keys) != len(set(keys)):
        raise ViewerInputError("PRODUCTION_HORSE_DUPLICATE")
    prefix = f"race_{target_date}_"
    if any(not row["race_id"].startswith(prefix) for row in rows):
        raise ViewerInputError("PRODUCTION_DATE_MISMATCH")
    return rows


def load_entries(paths: list[Path]) -> dict[tuple[str, str], dict]:
    grouped: dict[tuple[str, str], list[dict]] = defaultdict(list)
    for path in sorted(paths):
        for row in parse_entry_file(path):
            grouped[(row["race_id"], row["horse_name"])].append(row)
    lookup = {}
    for key, rows in grouped.items():
        jockeys = {row["jockey_name"] for row in rows}
        if len(jockeys) != 1:
            raise ViewerInputError(f"ENTRY_JOCKEY_COLLISION:{key[0]}:{key[1]}")
        lookup[key] = rows[0]
    return lookup


def _race_parts(race_id: str) -> tuple[str, str]:
    match = re.fullmatch(r"race_\d{8}_([^_]+)_([0-9]+R)", race_id, re.IGNORECASE)
    if not match:
        raise ViewerInputError(f"RACE_ID_INVALID:{race_id}")
    return match.group(1), match.group(2).upper()


def compare_rows(production: list[dict], entries: dict, tiers: dict, enabled=None) -> list[dict]:
    """Return Viewer rows; OFF returns an exact deep copy of Production input.

    Shadow decision/BUY are a rank-slot projection only.  The decision engine is
    intentionally not rerun: each Shadow rank receives the decision recorded at
    the same Production rank in that race.  Thus decision/BUY counts per race are
    conserved and the fields must not be interpreted as Production output.
    """
    if not flag_enabled(enabled):
        return copy.deepcopy(production)
    by_race: dict[str, list[dict]] = defaultdict(list)
    for source in production:
        by_race[source["race_id"]].append(dict(source))
    output = []
    for race_id, race_rows in sorted(by_race.items()):
        ranks = [_int(row["rank"]) for row in race_rows]
        if sorted(ranks) != list(range(1, len(race_rows) + 1)):
            raise ViewerInputError(f"PRODUCTION_RANK_SEQUENCE_INVALID:{race_id}")
        decision_by_rank = {_int(row["rank"]): str(row["decision"]).upper() for row in race_rows}
        enriched = []
        for row in race_rows:
            entry = entries.get((race_id, row["horse_name"]))
            if entry is None:
                raise ViewerInputError(f"ENTRY_MISSING:{race_id}:{row['horse_name']}")
            tier = tiers.get(entry["jockey_name"])
            tier_name = tier["tier"] if tier else "UNKNOWN"
            adjustment = _int(tier["shadow_score"]) if tier else 0
            enriched.append({**row, "_tier": tier_name, "_adjustment": adjustment,
                             "_shadow_score": _float(row["adjusted_score"]) + adjustment})
        ordered = sorted(enriched, key=lambda row: (-row["_shadow_score"], _int(row["rank"])))
        for shadow_rank, row in enumerate(ordered, start=1):
            production_rank = _int(row["rank"])
            production_decision = str(row["decision"]).upper()
            shadow_decision = decision_by_rank[shadow_rank]
            production_buy = production_decision == "BUY"
            shadow_buy = shadow_decision == "BUY"
            racecourse, race_number = _race_parts(race_id)
            comments = ["REFERENCE_ONLY_RANK_SLOT_PROJECTION", "NOT_DECISION_ENGINE_OUTPUT"]
            if production_decision != "BUY" and shadow_buy:
                comments.insert(0, "PRODUCTION_NON_BUY_TO_SHADOW_BUY")
            if row["_tier"] == "UNKNOWN":
                comments.append("TRACE_UNKNOWN_JOCKEY_TIER")
            output.append({
                "race_id": race_id, "racecourse": racecourse, "race_number": race_number,
                "horse_name": row["horse_name"], "Production_rank": production_rank,
                "Production_decision": production_decision, "Production_buy": production_buy,
                "Shadow_rank": shadow_rank, "Shadow_decision": shadow_decision,
                "Shadow_buy": shadow_buy, "rank_change": production_rank - shadow_rank,
                "decision_changed": production_decision != shadow_decision,
                "buy_changed": production_buy != shadow_buy, "jockey_tier": row["_tier"],
                "tier_adjustment": row["_adjustment"], "comment": ";".join(comments),
            })
    return sorted(output, key=lambda row: (row["race_id"], row["Shadow_rank"]))


def _write_csv(path: Path, rows: list[dict]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8-sig", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=FIELDS, extrasaction="ignore")
        writer.writeheader()
        writer.writerows(rows)


def _write_json(path: Path, payload: dict) -> None:
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def summary_markdown(target_date: str, rows: list[dict], status: str, reason: str = "") -> str:
    shadow_buys = [row for row in rows if row.get("Shadow_buy")]
    new_buys = [row for row in rows if not row.get("Production_buy") and row.get("Shadow_buy")]
    pass_to_buys = [row for row in new_buys if row.get("Production_decision") == "PASS"]
    rises = sorted((row for row in rows if _int(row.get("rank_change")) > 0), key=lambda row: (-_int(row["rank_change"]), row["race_id"], row["Shadow_rank"]))[:10]
    def listing(values, text):
        return "\n".join(f"- {row['race_id']} {row['horse_name']}: {text(row)}" for row in values) or "- 該当なし"
    pending = f"\n- Reason: `{reason}`\n" if reason else ""
    return f"""# Prospective Shadow Viewer {target_date}

- Status: **{status}**{pending}- Candidate: `JOCKEY_TIER_ADDITIVE_V1` (reference only / formally closed)
- Shadow Decision/BUY: Production rank-slot projection; not Decision Engine output
- Rank change: `Production_rank - Shadow_rank`（正数が順位上昇）

## Shadow BUY一覧

{listing(shadow_buys, lambda row: f"Production {row['Production_rank']}位/{row['Production_decision']} → Shadow {row['Shadow_rank']}位/{row['Shadow_decision']}")}

## Production PASS → Shadow BUY

{listing(pass_to_buys, lambda row: f"{row['Production_rank']}位 → {row['Shadow_rank']}位 (差 {row['rank_change']:+d})")}

## Shadow順位上昇TOP10

{listing(rises, lambda row: f"{row['Production_rank']}位 → {row['Shadow_rank']}位 (差 {row['rank_change']:+d}, Tier {row['jockey_tier']} {row['tier_adjustment']:+d})")}

## Productionとの差分まとめ

- 対象レース: {len({row['race_id'] for row in rows})}
- 対象馬: {len(rows)}
- Shadow BUY: {len(shadow_buys)}
- Production非BUY → Shadow BUY: {len(new_buys)}
- 順位変動: {sum(row.get('Production_rank') != row.get('Shadow_rank') for row in rows)}
- Decision差分: {sum(bool(row.get('decision_changed')) for row in rows)}
- BUY差分: {sum(bool(row.get('buy_changed')) for row in rows)}

> 本Viewerは前向き観測専用です。Production採用判断には使用しません。
"""


def run(target_date: str, enabled=None, production_path: Path | None = None,
        entry_paths: list[Path] | None = None, output_dir: Path | None = None,
        test_status: str = "PENDING_EXTERNAL_TEST_COMMAND") -> dict:
    if not re.fullmatch(r"\d{8}", target_date):
        raise ViewerInputError("TARGET_DATE_INVALID")
    if not flag_enabled(enabled):
        return {"status": "FLAG_OFF_NO_OUTPUT", "feature_flag": FLAG_NAME, "output_count": 0}
    output_dir = output_dir or REPORTS / "prospective_shadow"
    production_path = production_path or REPORTS / "pre_race" / target_date / f"pre_race_{target_date}_horse_summary.csv"
    compare_path = output_dir / f"{target_date}_shadow_compare.csv"
    summary_path = output_dir / f"{target_date}_shadow_summary.md"
    safety_path = output_dir / f"{target_date}_shadow_safety.json"
    zero_path = output_dir / f"{target_date}_shadow_zero_delta.json"
    tests_path = output_dir / f"{target_date}_shadow_test_manifest.json"
    before = protected_snapshot()
    generated_at = datetime.now(timezone.utc).isoformat()
    if not production_path.is_file():
        _write_csv(compare_path, [])
        summary_path.write_text(summary_markdown(target_date, [], "INPUT_PENDING", "PRODUCTION_INPUT_MISSING"), encoding="utf-8")
        after = protected_snapshot()
        safety = {"status": "PASS", "generated_at": generated_at, "observation_status": "INPUT_PENDING",
                  "target_trial_adapter_run_count": 0, "evaluator_run_count": 0, "decision_engine_run_count": 0,
                  "learning_update_count": 0, "knowledge_update_count": 0, "protected_unchanged": before == after}
        zero = {"status": "PASS" if before == after else "FAIL", "feature_flag_off_default": True,
                "protected_before": before, "protected_after": after}
        tests = {"status": test_status, "py_compile": test_status, "fixed_test_method_count": 7,
                 "command": "python -m unittest -v tests.test_prospective_shadow_viewer_v1"}
        _write_json(safety_path, safety); _write_json(zero_path, zero); _write_json(tests_path, tests)
        return {"status": "INPUT_PENDING", "row_count": 0, "safety": safety["status"], "zero_delta": zero["status"]}
    production = load_production(production_path, target_date)
    production_sha_before = _sha(production_path)
    entry_paths = entry_paths if entry_paths is not None else sorted((ROOT / "data" / "analysis").rglob(f"race_{target_date}_*_entry.csv"))
    if not entry_paths:
        raise ViewerInputError("ENTRY_INPUT_MISSING")
    entries = load_entries(entry_paths)
    tiers, table = load_tiers()
    rows = compare_rows(production, entries, tiers, enabled=True)
    _write_csv(compare_path, rows)
    summary_path.write_text(summary_markdown(target_date, rows, "READY"), encoding="utf-8")
    after = protected_snapshot()
    production_sha_after = _sha(production_path)
    safety = {"status": "PASS" if before == after else "FAIL", "generated_at": generated_at,
              "tier_table_sha256": table["table_sha256"], "production_input_sha256": _sha(production_path),
              "production_input_unchanged": production_sha_before == production_sha_after,
              "entry_file_count": len(entry_paths), "target_trial_adapter_run_count": 0,
              "evaluator_run_count": 0, "decision_engine_run_count": 0, "learning_update_count": 0,
              "knowledge_update_count": 0, "protected_unchanged": before == after}
    zero = {"status": "PASS" if before == after else "FAIL", "feature_flag_off_default": True,
            "off_returns_exact_deep_copy": compare_rows(production, entries, tiers, enabled=False) == production,
            "production_decision_counts_conserved_by_race": all(
                sorted(row["Production_decision"] for row in rows if row["race_id"] == race_id) ==
                sorted(row["Shadow_decision"] for row in rows if row["race_id"] == race_id)
                for race_id in {row["race_id"] for row in rows}),
            "protected_before": before, "protected_after": after}
    tests = {"status": test_status, "py_compile": test_status, "fixed_test_method_count": 7,
             "command": "python -m unittest -v tests.test_prospective_shadow_viewer_v1"}
    _write_json(safety_path, safety); _write_json(zero_path, zero); _write_json(tests_path, tests)
    return {"status": "READY" if safety["status"] == zero["status"] == "PASS" else "SAFETY_HOLD",
            "race_count": len({row["race_id"] for row in rows}), "row_count": len(rows),
            "new_shadow_buy_count": sum(not row["Production_buy"] and row["Shadow_buy"] for row in rows),
            "safety": safety["status"], "zero_delta": zero["status"]}


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--date", required=True)
    parser.add_argument("--enable", action="store_true")
    parser.add_argument("--production-csv", type=Path)
    parser.add_argument("--tests-passed", action="store_true")
    args = parser.parse_args()
    print(json.dumps(run(args.date, enabled=args.enable, production_path=args.production_csv,
                         test_status="PASS" if args.tests_passed else "PENDING_EXTERNAL_TEST_COMMAND"), ensure_ascii=False))


if __name__ == "__main__":
    main()
