"""Single-entry, immutable Formal POST authority for prospective protocol v1."""
from __future__ import annotations

import csv
import json
from pathlib import Path
from typing import Any, Callable

from review.current_corrected_shadow_v2_prospective_protocol_v1 import ROOT, Stop, aggregate_arm, load_protocol, sha, validate_authorization_artifact
from review.current_corrected_shadow_v2_prospective_runtime_binding_v1 import FORMAL_RUNTIME_MODULES
from review.current_corrected_shadow_v2_prospective_formal_pre_v1 import validate_runtime_freeze_binding
from review.current_corrected_shadow_v2_prospective_state_v1 import PROTOCOL_IDENTITY, REQUIRED_PRE_ARTIFACTS, PostStateTransitions, StateReader, require_protocol_accepts_new_evidence
from review.current_corrected_shadow_v2_prospective_validators_v1 import validate_post
from review.target_daily_result_list_schema_v2_validator import validate_source_pair
from review.current_corrected_shadow_v2_prospective_governance_v1 import GovernanceLedger, require_governance_allows_operation, _now_utc
from review.current_corrected_shadow_v2_prospective_human_artifact_store_v1 import HumanArtifactStoreBinding

VENUE = {"sapporo":"札幌", "hakodate":"函館", "fukushima":"福島", "niigata":"新潟", "tokyo":"東京", "nakayama":"中山", "chukyo":"中京", "kyoto":"京都", "hanshin":"阪神", "kokura":"小倉"}
ABNORMAL = {"中止", "除外", "取消", "失格", "0"}
REQUIRED_POST_ARTIFACTS = {"post_manifest.json", "frozen_pre_reference.json", "result_source_manifest.json", "joined_rows.json", "race_metrics.json", "primary_post.json", "natural_post.json", "summary.json", "provenance.json", "safety.json", "report.md", "artifact_hashes.json"}


def _read_json(path: Path, stop: str) -> dict[str, Any]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except Exception as exc:
        raise Stop(stop) from exc
    if not isinstance(value, dict):
        raise Stop(stop)
    return value


def verify_pre_hashes(pre_root: Path, *, target_date: str | None = None, authorization_id: str | None = None) -> dict[str, Any]:
    """Re-validate an exact Stage-1 PRE artifact; callers cannot waive fields."""
    if not pre_root.is_dir() or not all((pre_root / name).is_file() for name in REQUIRED_PRE_ARTIFACTS):
        raise Stop("STOP_PRE_FREEZE_INTEGRITY_FAILURE")
    index = _read_json(pre_root / "artifact_hashes.json", "STOP_PRE_FREEZE_INTEGRITY_FAILURE")
    manifest = _read_json(pre_root / "pre_freeze_manifest.json", "STOP_PRE_FREEZE_INTEGRITY_FAILURE")
    provenance = _read_json(pre_root / "provenance.json", "STOP_PRE_FREEZE_INTEGRITY_FAILURE")
    indexed = index.get("indexed_artifacts")
    actual = {str(path.relative_to(pre_root)).replace("\\", "/") for path in pre_root.rglob("*") if path.is_file()} - {"artifact_hashes.json", "pre_freeze_manifest.json"}
    if not isinstance(indexed, dict) or set(indexed) != actual or any(not isinstance(value, str) or sha(pre_root / name) != value for name, value in indexed.items()):
        raise Stop("STOP_PRE_FREEZE_INTEGRITY_FAILURE")
    if manifest.get("status") != "PRE_FROZEN" or manifest.get("protocol_identity") != PROTOCOL_IDENTITY or manifest.get("artifact_hashes_sha256") != sha(pre_root / "artifact_hashes.json"):
        raise Stop("STOP_PRE_FREEZE_INTEGRITY_FAILURE")
    if target_date is not None and (manifest.get("target_date") != target_date or provenance.get("target_date") != target_date):
        raise Stop("STOP_PRE_FREEZE_INTEGRITY_FAILURE")
    if authorization_id is not None and (manifest.get("authorization_id") != authorization_id or provenance.get("authorization_id") != authorization_id):
        raise Stop("STOP_PRE_FREEZE_INTEGRITY_FAILURE")
    for name in ("population.json", "current_comparator.json", "primary_selection.json", "natural_buy.json"):
        _read_json(pre_root / name, "STOP_PRE_FREEZE_INTEGRITY_FAILURE")
    return {"pre_root": str(pre_root), "pre_manifest_sha256": sha(pre_root / "pre_freeze_manifest.json"), "artifact_hashes_sha256": sha(pre_root / "artifact_hashes.json"), "attempt_id": manifest.get("attempt_id")}


def _selection_sets(pre_root: Path) -> tuple[set[tuple[str, int]], set[tuple[str, int]], set[tuple[str, int]]]:
    current = _read_json(pre_root / "current_comparator.json", "STOP_POST_FROZEN_SELECTION_REQUIRED")
    primary = _read_json(pre_root / "primary_selection.json", "STOP_POST_FROZEN_SELECTION_REQUIRED")
    secondary = _read_json(pre_root / "natural_buy.json", "STOP_POST_FROZEN_SELECTION_REQUIRED")
    current_rows = current.get("frozen_current_buy_rows")
    if not isinstance(current_rows, list) or not isinstance(primary.get("rows"), list) or not isinstance(secondary.get("rows"), list):
        raise Stop("STOP_POST_FROZEN_SELECTION_REQUIRED")
    def to_set(rows: list[dict[str, Any]]) -> set[tuple[str, int]]:
        try:
            return {(str(row["race_id"]), int(row["horse_number"])) for row in rows}
        except (KeyError, TypeError, ValueError) as exc:
            raise Stop("STOP_POST_FROZEN_SELECTION_REQUIRED") from exc
    return to_set(current_rows), to_set(primary["rows"]), to_set(secondary["rows"])


def _join_frozen_selection(pre_root: Path, result_rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    current, primary, secondary = _selection_sets(pre_root)
    all_selected = current | primary | secondary
    indexed: dict[tuple[str, int], dict[str, Any]] = {}
    for row in result_rows:
        try:
            key = (str(row["race_id"]), int(row["horse_number"]))
        except (KeyError, TypeError, ValueError) as exc:
            raise Stop("STOP_POST_RESULT_SEMANTICS") from exc
        if key in indexed:
            raise Stop("STOP_POST_DUPLICATE_HORSE")
        indexed[key] = dict(row)
    if all_selected - set(indexed):
        raise Stop("STOP_POST_MISSING_HORSE")
    joined: list[dict[str, Any]] = []
    for key in sorted(all_selected):
        row = dict(indexed[key])
        if not isinstance(row.get("valid_result"), bool) or not isinstance(row.get("actual_top3"), bool):
            raise Stop("STOP_POST_RESULT_SEMANTICS")
        if not row["valid_result"] and row["actual_top3"]:
            raise Stop("STOP_POST_INVALID_TOP3")
        row.update({"current_selected": key in current, "corrected_selected": key in primary, "secondary_selected": key in secondary})
        joined.append(row)
    validate_post(True, joined)
    return joined


def _race_metrics(rows: list[dict[str, Any]], *, pre_root: Path, target_date: str, block_id: str) -> list[dict[str, Any]]:
    population = _read_json(pre_root / "population.json", "STOP_PRE_FREEZE_INTEGRITY_FAILURE").get("races")
    if not isinstance(population, list):
        raise Stop("STOP_PRE_FREEZE_INTEGRITY_FAILURE")
    target_k = {str(item.get("race_id")): int(item.get("target_k")) for item in population if isinstance(item, dict) and isinstance(item.get("target_k"), int)}
    _, primary_set, _ = _selection_sets(pre_root)
    metrics: list[dict[str, Any]] = []
    for race_id in sorted({str(row["race_id"]) for row in rows}):
        race_rows = [row for row in rows if row["race_id"] == race_id]
        comparator, primary, secondary = aggregate_arm(race_rows, "current"), aggregate_arm(race_rows, "corrected"), aggregate_arm(race_rows, "secondary")
        if race_id not in target_k:
            raise Stop("STOP_PRE_FREEZE_INTEGRITY_FAILURE")
        primary_selected_raw = sum(1 for candidate in primary_set if candidate[0] == race_id)
        # B1: selection-volume shortfall is frozen before Result join. Invalid
        # finishes alter only the valid denominator, never this value.
        shortfall = max(0, target_k[race_id] - primary_selected_raw)
        metrics.append({"target_date": target_date, "race_id": race_id, "block_id": block_id, "target_k": target_k[race_id], "primary_selected_n_raw_from_pre": primary_selected_raw, "comparator": comparator, "primary": primary, "secondary": secondary, "counted": comparator["valid_selected_n"] > 0 and primary["valid_selected_n"] > 0, "shortfall": shortfall})
    return metrics


def _source_pair(date: str, result_root: Path) -> tuple[Path, Path]:
    primary, auxiliary = result_root / f"馬番順着順_{date}.csv", result_root / f"着順馬番_{date}.csv"
    if not primary.is_file() and not auxiliary.is_file(): raise Stop("STOP_RESULT_SOURCE_NOT_FOUND")
    if not primary.is_file() or not auxiliary.is_file(): raise Stop("STOP_RESULT_SOURCE_AMBIGUOUS")
    return primary, auxiliary


def _canonical_result_loader(date: str, pre_root: Path, result_root: Path) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    """Production-capable loader, reached only through the public Formal POST."""
    primary, auxiliary = _source_pair(date, result_root)
    pair = validate_source_pair(primary, auxiliary, date)
    with primary.open("r", encoding="cp932", newline="") as handle: races = {row[0]: row for row in csv.reader(handle)}
    by_identity = {(value["venue_name"], int(value["race_number"])): key for key, value in pair["source_d_primary"]["race_index"].items()}
    current, corrected, secondary = _selection_sets(pre_root); rows = []
    for race_id, horse_number in sorted(current | corrected | secondary):
        parts = race_id.split("_"); source_id = by_identity.get((VENUE.get(parts[-2]), int(parts[-1].removesuffix("R"))))
        if source_id is None: raise Stop("STOP_POST_MISSING_RACE")
        raw = races[source_id][11 + horse_number]
        if raw.isdigit() and int(raw) > 0: valid, finish = True, int(raw)
        elif raw in ABNORMAL: valid, finish = False, None
        else: raise Stop("STOP_POST_RESULT_SEMANTICS")
        rows.append({"race_id": race_id, "horse_number": horse_number, "valid_result": valid, "actual_top3": bool(valid and finish <= 3), "actual_finish": finish, "raw_result": raw})
    return rows, {"target_date": date, "primary": str(primary.relative_to(ROOT)).replace("\\", "/"), "auxiliary": str(auxiliary.relative_to(ROOT)).replace("\\", "/"), "primary_sha256": sha(primary), "auxiliary_sha256": sha(auxiliary), "schema": pair}


def _write_json(path: Path, value: Any) -> None:
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def _write_immutable_post(target_date: str, *, pre_root: Path, pre: dict[str, Any], authorization_id: str, output_root: Path, result_rows: list[dict[str, Any]], source_manifest: dict[str, Any], governance_ledger_head_sha256: str | None = None) -> Path:
    if output_root.exists(): raise Stop("STOP_POST_OUTPUT_EXISTS")
    block_id = _read_json(pre_root / "summary.json", "STOP_PRE_FREEZE_INTEGRITY_FAILURE").get("central_jra_meeting_week_id")
    if not isinstance(block_id, str) or not block_id: raise Stop("STOP_PRE_BLOCK_ID_REQUIRED")
    joined = _join_frozen_selection(pre_root, result_rows); metrics = _race_metrics(joined, pre_root=pre_root, target_date=target_date, block_id=block_id); counted = [row for row in metrics if row["counted"]]; counted_ids = {row["race_id"] for row in counted}
    comparator, primary, secondary = aggregate_arm([row for row in joined if row["race_id"] in counted_ids], "current"), aggregate_arm([row for row in joined if row["race_id"] in counted_ids], "corrected"), aggregate_arm(joined, "secondary")
    lift = None if not comparator["valid_selected_n"] or not primary["valid_selected_n"] else ((primary["hits"] / primary["valid_selected_n"]) - (comparator["hits"] / comparator["valid_selected_n"])) * 100
    shortfall = sum(int(row["shortfall"]) for row in counted); output_root.mkdir(parents=True, exist_ok=False)
    payloads: dict[str, Any] = {
        "frozen_pre_reference.json": {"pre_path": str(pre_root), "pre_manifest_sha256": pre["pre_manifest_sha256"], "pre_artifact_hashes_sha256": pre["artifact_hashes_sha256"], "attempt_id": pre["attempt_id"]},
        "result_source_manifest.json": source_manifest, "joined_rows.json": {"rows": joined}, "race_metrics.json": {"races": metrics},
        "primary_post.json": {"comparator": comparator, "primary": primary, "counted_races": len(counted), "pooled_lift_pt": lift, "shortfall": shortfall}, "natural_post.json": secondary,
        "summary.json": {"status": "POST_FROZEN", "target_date": target_date, "block_id": block_id, "counted_races": len(counted), "shortfall": shortfall, "pooled_lift_pt": lift},
        "provenance.json": {"target_date": target_date, "protocol_identity": PROTOCOL_IDENTITY, "authorization_id": authorization_id, "pre_manifest_sha256": pre["pre_manifest_sha256"], "governance_ledger_head_sha256": governance_ledger_head_sha256, "result_access_count": 1},
        "safety.json": {"selection_recalculation_count": 0, "rank_recalculation_count": 0, "result_access_count": 1, "production_changed": False},
    }
    for name, value in payloads.items(): _write_json(output_root / name, value)
    (output_root / "report.md").write_text("# Current Corrected Shadow V2 Formal POST\n\nImmutable Formal POST artifact.\n", encoding="utf-8")
    indexed = {str(path.relative_to(output_root)).replace("\\", "/"): sha(path) for path in output_root.rglob("*") if path.is_file()}
    _write_json(output_root / "artifact_hashes.json", {"self_hash_excluded": True, "manifest_hash_excluded": True, "indexed_artifacts": indexed})
    _write_json(output_root / "post_manifest.json", {"status": "POST_FROZEN", "target_date": target_date, "protocol_identity": PROTOCOL_IDENTITY, "authorization_id": authorization_id, "pre_manifest_sha256": pre["pre_manifest_sha256"], "governance_ledger_head_sha256": governance_ledger_head_sha256, "artifact_hashes_sha256": sha(output_root / "artifact_hashes.json")})
    return output_root


def _state_pre_reference(target_date: str, reader: StateReader) -> tuple[Path, str]:
    if reader.get_date_state(target_date) != "PRE_FROZEN": raise Stop("STOP_POST_REQUIRES_PRE_FROZEN")
    history = reader.event_history(target_date); start, pre = history[0], history[-1]
    authorization_id = start.get("metadata", {}).get("authorization_id")
    if pre.get("event") != "PRE_FROZEN" or not isinstance(pre.get("pre_path"), str) or not isinstance(authorization_id, str): raise Stop("STOP_DATE_STATE_CORRUPT")
    return Path(pre["pre_path"]), authorization_id


def _run_post(target_date: str, *, event_root: Path, output_root: Path, result_loader: Callable[[str, Path], tuple[list[dict[str, Any]], dict[str, Any]]], governance_ledger_head_sha256: str | None = None) -> Path:
    require_protocol_accepts_new_evidence(event_root)
    reader = StateReader(event_root)
    pre_root, authorization_id = _state_pre_reference(target_date, reader)
    history = reader.event_history(target_date)
    head = governance_ledger_head_sha256 if governance_ledger_head_sha256 is not None else (history[0].get("metadata", {}).get("governance_ledger_head_sha256") if history else None)
    pre = verify_pre_hashes(pre_root, target_date=target_date, authorization_id=authorization_id)
    rows, sources = result_loader(target_date, pre_root)
    post = _write_immutable_post(target_date, pre_root=pre_root, pre=pre, authorization_id=authorization_id, output_root=output_root, result_rows=rows, source_manifest=sources, governance_ledger_head_sha256=head)
    PostStateTransitions(event_root).mark_post_frozen_from_artifact(target_date, post_directory=post, governance_ledger_head_sha256=head)
    return post


def run_formal_post(target_date: str, output_root: Path, *, result_root: Path | None = None, authorization_path: Path | None = None) -> Path:
    """The one public Formal POST authority; every identity is state-derived."""
    protocol = load_protocol(); authorization_path = authorization_path or ROOT / protocol["execution_authorization"]["artifact_path"]
    authorization = validate_authorization_artifact(target_date, protocol, authorization_path)
    validate_runtime_freeze_binding(ROOT / authorization["authoritative_freeze_path"], runtime_modules=FORMAL_RUNTIME_MODULES)
    state_root = ROOT / "reports" / "current_corrected_shadow_v2_prospective_state_v1"
    history = StateReader(state_root).event_history(target_date)
    head = history[0].get("metadata", {}).get("governance_ledger_head_sha256") if history else None
    authorization_sha = sha(authorization_path)
    ledger = GovernanceLedger(ROOT / "reports" / "current_corrected_shadow_v2_prospective_governance_v1", authorization["authorization_id"], authorization_sha, HumanArtifactStoreBinding.from_authorization(authorization, authorization_sha))
    view = require_governance_allows_operation(ledger=ledger, target_date=target_date, operation="POST", state_reader=StateReader(state_root), as_of=_now_utc(), claim_head=head)
    root = result_root or ROOT / "data" / "raw" / "target" / "daily_result_list"
    return _run_post(target_date, event_root=state_root, output_root=output_root, result_loader=lambda date, pre: _canonical_result_loader(date, pre, root), governance_ledger_head_sha256=view["current_ledger_head_sha256"])


def _run_formal_post_for_test(target_date: str, *, event_root: Path, output_root: Path, result_loader: Callable[[str, Path], tuple[list[dict[str, Any]], dict[str, Any]]], governance_ledger_head_sha256: str | None = None) -> Path:
    """Private TECHNICAL_TEST_ONLY hook; never a Formal authority."""
    return _run_post(target_date, event_root=event_root, output_root=output_root, result_loader=result_loader, governance_ledger_head_sha256=governance_ledger_head_sha256)


def build_post(*_args: Any, **_kwargs: Any) -> None:
    raise Stop("STOP_LEGACY_CALLER_ROWS_POST_DISABLED")
