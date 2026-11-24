"""Append-only, artifact-derived Formal state authority for protocol v1."""
from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from review.current_corrected_shadow_v2_prospective_protocol_v1 import ROOT, Stop, sha


DEFAULT_EVENT_ROOT = ROOT / "reports" / "current_corrected_shadow_v2_prospective_state_v1"
PROTOCOL_IDENTITY = "CURRENT_CORRECTED_SHADOW_V2_PROSPECTIVE_PROTOCOL_V1"
DATE_STATES = {"UNCLAIMED", "ATTEMPT_STARTED", "PRE_FROZEN", "NO_PRE", "POST_FROZEN", "CUMULATED"}
PROTOCOL_STATES = {"NOT_STARTED", "RUNNING", "SUSPENDED", "HOLD:EVIDENCE_QUANTITY", "HOLD_VOLUME_CONFOUNDED", "ACCEPT", "REJECT"}
CANDIDATE_STATES = {"PRODUCTION_DESIGN_REVIEW_ELIGIBLE"}
DATE_TRANSITIONS = {("UNCLAIMED", "ATTEMPT_STARTED"), ("ATTEMPT_STARTED", "PRE_FROZEN"), ("ATTEMPT_STARTED", "NO_PRE"), ("PRE_FROZEN", "POST_FROZEN"), ("POST_FROZEN", "CUMULATED")}
PROTOCOL_TRANSITIONS = {
    ("NOT_STARTED", "RUNNING"),
    ("RUNNING", "HOLD:EVIDENCE_QUANTITY"), ("RUNNING", "SUSPENDED"),
    ("RUNNING", "HOLD_VOLUME_CONFOUNDED"), ("RUNNING", "ACCEPT"), ("RUNNING", "REJECT"),
    ("HOLD:EVIDENCE_QUANTITY", "RUNNING"), ("HOLD:EVIDENCE_QUANTITY", "SUSPENDED"),
    ("HOLD:EVIDENCE_QUANTITY", "HOLD_VOLUME_CONFOUNDED"),
    ("HOLD:EVIDENCE_QUANTITY", "ACCEPT"), ("HOLD:EVIDENCE_QUANTITY", "REJECT"),
    ("SUSPENDED", "RUNNING"),
}
REQUIRED_PRE_ARTIFACTS = {
    "population.json", "current_comparator.json", "primary_selection.json", "natural_buy.json",
    "integrity_check.json", "exclusion_record.json", "provenance.json", "summary.json",
    "safety.json", "report.md", "artifact_hashes.json", "pre_freeze_manifest.json",
}
REQUIRED_POST_ARTIFACTS = {
    "post_manifest.json", "frozen_pre_reference.json", "result_source_manifest.json",
    "joined_rows.json", "race_metrics.json", "primary_post.json", "natural_post.json",
    "summary.json", "provenance.json", "safety.json", "report.md", "artifact_hashes.json",
}


def canonical_date(value: str) -> str:
    if not isinstance(value, str) or len(value) != 8 or not value.isdigit():
        raise Stop("STOP_INVALID_TARGET_DATE")
    try:
        datetime.strptime(value, "%Y%m%d")
    except ValueError as exc:
        raise Stop("STOP_INVALID_TARGET_DATE") from exc
    return value


def validate_transition(before: str, after: str, *, protocol_level: bool = False, human_resume: bool = False) -> None:
    table = PROTOCOL_TRANSITIONS if protocol_level else DATE_TRANSITIONS
    universe = PROTOCOL_STATES if protocol_level else DATE_STATES
    if before not in universe or after not in universe or (before, after) not in table:
        raise Stop("STOP_ILLEGAL_PROTOCOL_TRANSITION" if protocol_level else "STOP_ILLEGAL_DATE_TRANSITION")
    if protocol_level and before == "SUSPENDED" and after == "RUNNING" and not human_resume:
        raise Stop("STOP_HUMAN_RESUME_REQUIRED")


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def protocol_state_from_cumulative_events(event_root: Path) -> str:
    """Read the immutable cumulative ledger without granting it write access."""
    root = event_root / "cumulative_events"
    if not root.exists():
        return "NOT_STARTED"
    if not root.is_dir():
        raise Stop("STOP_CUMULATIVE_EVENT_INTEGRITY")
    events = []
    for path in sorted(root.glob("*.json")):
        try:
            value = json.loads(path.read_text(encoding="utf-8"))
        except Exception as exc:
            raise Stop("STOP_CUMULATIVE_EVENT_INTEGRITY") from exc
        if not isinstance(value, dict):
            raise Stop("STOP_CUMULATIVE_EVENT_INTEGRITY")
        events.append(value)
    if not events:
        return "NOT_STARTED"
    from review.current_corrected_shadow_v2_prospective_cumulative_fold_v1 import fold_cumulative_evidence
    return str(fold_cumulative_evidence(events)["protocol_state_after"])


def require_protocol_accepts_new_evidence(event_root: Path) -> None:
    if protocol_state_from_cumulative_events(event_root) in {"HOLD_VOLUME_CONFOUNDED", "CURRENT_CORRECTED_SHADOW_V2_PROSPECTIVE_ACCEPT", "CURRENT_CORRECTED_SHADOW_V2_PROSPECTIVE_REJECT"}:
        raise Stop("STOP_EVALUATION_POINT_CONSUMED")


class _EventStore:
    """Private event writer; only transition objects use it."""
    def __init__(self, event_root: Path):
        self.event_root = event_root

    def date_root(self, target_date: str) -> Path:
        return self.event_root / canonical_date(target_date)

    def _append_event(self, target_date: str, filename: str, event: str, payload: dict[str, Any]) -> Path:
        root = self.date_root(target_date)
        root.mkdir(parents=True, exist_ok=True)
        path = root / filename
        value = {"event": event, "target_date": target_date, "recorded_at": _now(), **payload}
        try:
            with path.open("x", encoding="utf-8") as handle:
                json.dump(value, handle, ensure_ascii=False, indent=2)
                handle.write("\n")
        except FileExistsError as exc:
            raise Stop("STOP_FORMAL_DATE_ALREADY_ATTEMPTED") from exc
        return path


@dataclass(frozen=True)
class StateReader:
    """Read-only view of the append-only Formal state event registry."""
    event_root: Path = DEFAULT_EVENT_ROOT

    def _events(self, target_date: str) -> list[tuple[str, Path, dict[str, Any]]]:
        target_date = canonical_date(target_date)
        root = self.event_root / target_date
        if not root.exists():
            return []
        if not root.is_dir():
            raise Stop("STOP_DATE_STATE_CORRUPT")
        allowed = {"001_attempt_started.json": "ATTEMPT_STARTED", "002_pre_frozen.json": "PRE_FROZEN", "002_no_pre.json": "NO_PRE", "003_post_frozen.json": "POST_FROZEN", "004_cumulated.json": "CUMULATED"}
        values = []
        for path in sorted(root.glob("*.json")):
            if path.name not in allowed:
                raise Stop("STOP_DATE_STATE_CORRUPT")
            try:
                value = json.loads(path.read_text(encoding="utf-8"))
            except Exception as exc:
                raise Stop("STOP_DATE_STATE_CORRUPT") from exc
            if not isinstance(value, dict) or value.get("event") != allowed[path.name] or value.get("target_date") != target_date:
                raise Stop("STOP_DATE_STATE_CORRUPT")
            values.append((allowed[path.name], path, value))
        return values

    def get_date_state(self, target_date: str) -> str:
        state = "UNCLAIMED"
        for event, _, _ in self._events(target_date):
            validate_transition(state, event)
            state = event
        return state

    def event_history(self, target_date: str) -> tuple[dict[str, Any], ...]:
        return tuple(value for _, _, value in self._events(target_date))

    def attempt_identity(self, target_date: str) -> str:
        events = self._events(target_date)
        if not events or events[0][0] != "ATTEMPT_STARTED" or not isinstance(events[0][2].get("attempt_id"), str):
            raise Stop("STOP_DATE_STATE_CORRUPT")
        return events[0][2]["attempt_id"]


@dataclass(frozen=True)
class PreStateTransitions:
    """The sole public writer for PRE date-state events."""
    event_root: Path = DEFAULT_EVENT_ROOT

    @property
    def reader(self) -> StateReader:
        return StateReader(self.event_root)

    @property
    def _store(self) -> _EventStore:
        return _EventStore(self.event_root)

    def claim_date(self, target_date: str, *, attempt_id: str, metadata: dict[str, Any]) -> Path:
        target_date = canonical_date(target_date)
        require_protocol_accepts_new_evidence(self.event_root)
        if self.reader.get_date_state(target_date) != "UNCLAIMED" or not isinstance(attempt_id, str) or not attempt_id:
            raise Stop("STOP_FORMAL_DATE_ALREADY_ATTEMPTED")
        return self._store._append_event(target_date, "001_attempt_started.json", "ATTEMPT_STARTED", {"attempt_id": attempt_id, "metadata": metadata})

    def mark_no_pre(self, target_date: str, *, reason: str) -> Path:
        target_date = canonical_date(target_date)
        if self.reader.get_date_state(target_date) != "ATTEMPT_STARTED":
            raise Stop("STOP_ILLEGAL_DATE_TRANSITION")
        return self._store._append_event(target_date, "002_no_pre.json", "NO_PRE", {"reason": reason})

    def mark_pre_frozen_from_artifact(self, target_date: str, *, attempt_id: str, pre_directory: Path) -> Path:
        """Derive every PRE_FROZEN identity from verified PRE artifacts."""
        target_date = canonical_date(target_date)
        if self.reader.get_date_state(target_date) != "ATTEMPT_STARTED" or self.reader.attempt_identity(target_date) != attempt_id:
            raise Stop("STOP_ILLEGAL_DATE_TRANSITION")
        if not pre_directory.is_dir():
            raise Stop("STOP_PRE_ARTIFACT_INTEGRITY")
        required = {pre_directory / name for name in REQUIRED_PRE_ARTIFACTS}
        if not all(path.is_file() for path in required):
            raise Stop("STOP_PRE_ARTIFACT_INTEGRITY")
        try:
            manifest = json.loads((pre_directory / "pre_freeze_manifest.json").read_text(encoding="utf-8"))
            index = json.loads((pre_directory / "artifact_hashes.json").read_text(encoding="utf-8"))
            provenance = json.loads((pre_directory / "provenance.json").read_text(encoding="utf-8"))
            safety = json.loads((pre_directory / "safety.json").read_text(encoding="utf-8"))
        except Exception as exc:
            raise Stop("STOP_PRE_ARTIFACT_INTEGRITY") from exc
        indexed = index.get("indexed_artifacts")
        if not isinstance(indexed, dict):
            raise Stop("STOP_PRE_ARTIFACT_INTEGRITY")
        actual = {str(path.relative_to(pre_directory)).replace("\\", "/") for path in pre_directory.rglob("*") if path.is_file()} - {"artifact_hashes.json", "pre_freeze_manifest.json"}
        if set(indexed) != actual or any(not isinstance(value, str) or sha(pre_directory / name) != value for name, value in indexed.items()):
            raise Stop("STOP_PRE_ARTIFACT_INTEGRITY")
        authorization_id = self.reader.event_history(target_date)[0].get("metadata", {}).get("authorization_id")
        identity = (manifest.get("status") == "PRE_FROZEN" and manifest.get("target_date") == target_date and manifest.get("attempt_id") == attempt_id and manifest.get("protocol_identity") == PROTOCOL_IDENTITY and manifest.get("authorization_id") == authorization_id and manifest.get("artifact_hashes_sha256") == sha(pre_directory / "artifact_hashes.json"))
        boundary = (provenance.get("target_date") == target_date and provenance.get("attempt_id") == attempt_id and provenance.get("protocol_identity") == PROTOCOL_IDENTITY and provenance.get("authorization_id") == authorization_id and provenance.get("result_data_access_count") == 0 and safety.get("result_data_access_count") == 0)
        if not identity or not boundary:
            raise Stop("STOP_PRE_ARTIFACT_INTEGRITY")
        return self._store._append_event(target_date, "002_pre_frozen.json", "PRE_FROZEN", {
            "attempt_id": attempt_id,
            "pre_path": str(pre_directory),
            "pre_manifest_sha256": sha(pre_directory / "pre_freeze_manifest.json"),
            "artifact_index_sha256": sha(pre_directory / "artifact_hashes.json"),
            "frozen_at": datetime.fromtimestamp((pre_directory / "pre_freeze_manifest.json").stat().st_mtime, tz=timezone.utc).isoformat(),
            "result_data_access_count": 0,
        })


def _verify_indexed_directory(directory: Path, *, required: set[str], stop: str) -> tuple[dict[str, Any], dict[str, Any]]:
    """Verify an exact, non-self-referential artifact set."""
    if not directory.is_dir() or not all((directory / name).is_file() for name in required):
        raise Stop(stop)
    try:
        index = json.loads((directory / "artifact_hashes.json").read_text(encoding="utf-8"))
        manifest = json.loads((directory / "post_manifest.json").read_text(encoding="utf-8"))
    except Exception as exc:
        raise Stop(stop) from exc
    indexed = index.get("indexed_artifacts")
    if not isinstance(indexed, dict):
        raise Stop(stop)
    # The manifest pins the index after the index is complete.  Excluding both
    # files prevents a self-referential hash cycle, exactly as PRE does.
    actual = {str(path.relative_to(directory)).replace("\\", "/") for path in directory.rglob("*") if path.is_file()} - {"artifact_hashes.json", "post_manifest.json"}
    if set(indexed) != actual or any(not isinstance(value, str) or sha(directory / name) != value for name, value in indexed.items()):
        raise Stop(stop)
    return manifest, index


@dataclass(frozen=True)
class PostStateTransitions:
    """The sole POST_FROZEN writer; state comes only from a verified POST."""
    event_root: Path = DEFAULT_EVENT_ROOT

    @property
    def reader(self) -> StateReader:
        return StateReader(self.event_root)

    @property
    def _store(self) -> _EventStore:
        return _EventStore(self.event_root)

    def mark_post_frozen_from_artifact(self, target_date: str, *, post_directory: Path, governance_ledger_head_sha256: str | None = None) -> Path:
        target_date = canonical_date(target_date)
        if self.reader.get_date_state(target_date) != "PRE_FROZEN":
            raise Stop("STOP_POST_REQUIRES_PRE_FROZEN")
        history = self.reader.event_history(target_date)
        pre_event = next((item for item in history if item.get("event") == "PRE_FROZEN"), None)
        if not isinstance(pre_event, dict):
            raise Stop("STOP_DATE_STATE_CORRUPT")
        expected_pre_path = pre_event.get("pre_path")
        expected_pre_manifest = pre_event.get("pre_manifest_sha256")
        if not isinstance(expected_pre_path, str) or not isinstance(expected_pre_manifest, str):
            raise Stop("STOP_DATE_STATE_CORRUPT")
        manifest, _ = _verify_indexed_directory(post_directory, required=REQUIRED_POST_ARTIFACTS, stop="STOP_POST_ARTIFACT_INTEGRITY")
        # Formal callers pass their just-validated ledger head.  The fallback
        # preserves the private technical replay hook without turning a PRE
        # claim head into a POST checkpoint head.
        checkpoint_head = governance_ledger_head_sha256 if governance_ledger_head_sha256 is not None else manifest.get("governance_ledger_head_sha256")
        try:
            pre_ref = json.loads((post_directory / "frozen_pre_reference.json").read_text(encoding="utf-8"))
            source = json.loads((post_directory / "result_source_manifest.json").read_text(encoding="utf-8"))
            summary = json.loads((post_directory / "summary.json").read_text(encoding="utf-8"))
            provenance = json.loads((post_directory / "provenance.json").read_text(encoding="utf-8"))
            joined = json.loads((post_directory / "joined_rows.json").read_text(encoding="utf-8"))["rows"]
            stored_metrics = json.loads((post_directory / "race_metrics.json").read_text(encoding="utf-8"))["races"]
            stored_primary = json.loads((post_directory / "primary_post.json").read_text(encoding="utf-8"))
            stored_secondary = json.loads((post_directory / "natural_post.json").read_text(encoding="utf-8"))
            pre_summary = json.loads((Path(expected_pre_path) / "summary.json").read_text(encoding="utf-8"))
            population = json.loads((Path(expected_pre_path) / "population.json").read_text(encoding="utf-8"))["races"]
            current_rows = json.loads((Path(expected_pre_path) / "current_comparator.json").read_text(encoding="utf-8"))["frozen_current_buy_rows"]
            primary_rows = json.loads((Path(expected_pre_path) / "primary_selection.json").read_text(encoding="utf-8"))["rows"]
            secondary_rows = json.loads((Path(expected_pre_path) / "natural_buy.json").read_text(encoding="utf-8"))["rows"]
        except Exception as exc:
            raise Stop("STOP_POST_ARTIFACT_INTEGRITY") from exc
        valid = (
            manifest.get("status") == "POST_FROZEN"
            and manifest.get("target_date") == target_date
            and manifest.get("protocol_identity") == PROTOCOL_IDENTITY
            and pre_ref.get("pre_path") == expected_pre_path
            and pre_ref.get("pre_manifest_sha256") == expected_pre_manifest
            and isinstance(source.get("primary_sha256"), str)
            and isinstance(source.get("auxiliary_sha256"), str)
            and summary.get("target_date") == target_date
            and summary.get("block_id") == pre_summary.get("central_jra_meeting_week_id")
            and provenance.get("authorization_id") == history[0].get("metadata", {}).get("authorization_id")
            and manifest.get("governance_ledger_head_sha256") == provenance.get("governance_ledger_head_sha256")
            and manifest.get("governance_ledger_head_sha256") == checkpoint_head
            and manifest.get("artifact_hashes_sha256") == sha(post_directory / "artifact_hashes.json")
        )
        if not valid:
            raise Stop("STOP_POST_ARTIFACT_INTEGRITY")
        # Re-derive the entire POST content from the PRE selection and joined
        # Result rows.  A self-consistent hash index alone is not authority.
        def keys(rows: list[dict[str, Any]]) -> set[tuple[str, int]]:
            return {(str(row["race_id"]), int(row["horse_number"])) for row in rows}
        expected = {"current": keys(current_rows), "corrected": keys(primary_rows), "secondary": keys(secondary_rows)}
        observed = {"current": set(), "corrected": set(), "secondary": set()}
        by_race: dict[str, list[dict[str, Any]]] = {}
        for row in joined:
            if not isinstance(row, dict) or not isinstance(row.get("valid_result"), bool) or not isinstance(row.get("actual_top3"), bool):
                raise Stop("STOP_POST_ARTIFACT_CONTENT_MISMATCH")
            key = (str(row.get("race_id")), int(row.get("horse_number")))
            for arm, flag in (("current", "current_selected"), ("corrected", "corrected_selected"), ("secondary", "secondary_selected")):
                if row.get(flag) is True: observed[arm].add(key)
                elif row.get(flag) not in {False, None}: raise Stop("STOP_POST_ARTIFACT_CONTENT_MISMATCH")
            by_race.setdefault(key[0], []).append(row)
        if observed != expected or set(by_race) != {race for arm in expected.values() for race, _ in arm}:
            raise Stop("STOP_POST_ARTIFACT_CONTENT_MISMATCH")
        target_k = {str(item["race_id"]): int(item["target_k"]) for item in population}
        def arm(rows: list[dict[str, Any]], name: str) -> dict[str, int]:
            selected = [row for row in rows if row.get(name + "_selected") is True]
            valid_rows = [row for row in selected if row["valid_result"] is True]
            return {"selected_n_raw": len(selected), "invalid_n": len(selected) - len(valid_rows), "valid_selected_n": len(valid_rows), "hits": sum(bool(row["actual_top3"]) for row in valid_rows)}
        derived_metrics = []
        for race_id, rows in sorted(by_race.items()):
            comparator, primary, secondary = arm(rows, "current"), arm(rows, "corrected"), arm(rows, "secondary")
            selected_primary = sum(1 for key in expected["corrected"] if key[0] == race_id)
            derived_metrics.append({"target_date": target_date, "race_id": race_id, "block_id": pre_summary["central_jra_meeting_week_id"], "target_k": target_k[race_id], "primary_selected_n_raw_from_pre": selected_primary, "comparator": comparator, "primary": primary, "secondary": secondary, "counted": comparator["valid_selected_n"] > 0 and primary["valid_selected_n"] > 0, "shortfall": max(0, target_k[race_id] - selected_primary)})
        if stored_metrics != derived_metrics:
            raise Stop("STOP_POST_ARTIFACT_CONTENT_MISMATCH")
        counted = [item for item in derived_metrics if item["counted"]]
        counted_ids = {item["race_id"] for item in counted}
        pool = [row for race, rows in by_race.items() if race in counted_ids for row in rows]
        derived_primary = {"comparator": arm(pool, "current"), "primary": arm(pool, "corrected"), "counted_races": len(counted), "pooled_lift_pt": None, "shortfall": sum(item["shortfall"] for item in counted)}
        if derived_primary["comparator"]["valid_selected_n"] and derived_primary["primary"]["valid_selected_n"]:
            derived_primary["pooled_lift_pt"] = ((derived_primary["primary"]["hits"] / derived_primary["primary"]["valid_selected_n"]) - (derived_primary["comparator"]["hits"] / derived_primary["comparator"]["valid_selected_n"])) * 100
        if stored_primary != derived_primary or stored_secondary != arm(joined, "secondary") or summary.get("shortfall") != derived_primary["shortfall"] or summary.get("counted_races") != len(counted) or summary.get("pooled_lift_pt") != derived_primary["pooled_lift_pt"]:
            raise Stop("STOP_POST_ARTIFACT_CONTENT_MISMATCH")
        return self._store._append_event(target_date, "003_post_frozen.json", "POST_FROZEN", {
            "post_path": str(post_directory),
            "post_manifest_sha256": sha(post_directory / "post_manifest.json"),
            "artifact_index_sha256": sha(post_directory / "artifact_hashes.json"),
            "pre_path": expected_pre_path,
            "block_id": summary["block_id"],
            "governance_ledger_head_sha256": checkpoint_head,
        })


@dataclass(frozen=True)
class CumulativeStateTransitions:
    """The sole CUMULATED writer; it verifies the immutable ledger event."""
    event_root: Path = DEFAULT_EVENT_ROOT

    @property
    def reader(self) -> StateReader:
        return StateReader(self.event_root)

    @property
    def _store(self) -> _EventStore:
        return _EventStore(self.event_root)

    def mark_cumulated_from_event(self, target_date: str, *, event_path: Path, governance_ledger_head_sha256: str | None = None) -> Path:
        target_date = canonical_date(target_date)
        canonical = self.event_root / "cumulative_events" / f"{target_date}.json"
        if self.reader.get_date_state(target_date) != "POST_FROZEN" or not event_path.is_file() or event_path.resolve() != canonical.resolve():
            raise Stop("STOP_CUMULATE_REQUIRES_POST_FROZEN")
        try:
            event = json.loads(event_path.read_text(encoding="utf-8"))
        except Exception as exc:
            raise Stop("STOP_CUMULATIVE_EVENT_INTEGRITY") from exc
        history = self.reader.event_history(target_date)
        post = next((item for item in history if item.get("event") == "POST_FROZEN"), None)
        # Public callers pass the current validated governance head.  The
        # private technical hook derives it from the immutable event itself.
        checkpoint_head = governance_ledger_head_sha256 if governance_ledger_head_sha256 is not None else event.get("governance_ledger_head_sha256")
        try:
            from review.current_corrected_shadow_v2_prospective_cumulative_v1 import _post_entry
            canonical_post = _post_entry(Path(post["post_path"]), target_date=target_date)
            canonical_rows = [row for row in canonical_post["races"] if row.get("counted") is True]
        except Exception as exc:
            raise Stop("STOP_CUMULATIVE_EVENT_CONTENT_MISMATCH") from exc
        valid = (
            event.get("target_date") == target_date
            and event.get("post_manifest_sha256") == post.get("post_manifest_sha256")
            and event.get("pre_path") == post.get("pre_path")
            and event.get("governance_ledger_head_sha256") == checkpoint_head
            and isinstance(event.get("counted_races"), int)
            and isinstance(event.get("accumulated_races_after_append"), int)
            and isinstance(event.get("accumulated_dates_after_append"), int)
            and event.get("evaluation_point_consumed") in {True, False}
        )
        if not valid:
            raise Stop("STOP_CUMULATIVE_EVENT_INTEGRITY")
        if event.get("counted_race_rows") != canonical_rows:
            raise Stop("STOP_CUMULATIVE_EVENT_CONTENT_MISMATCH")
        try:
            from review.current_corrected_shadow_v2_prospective_cumulative_fold_v1 import fold_cumulative_evidence
            ledger=[]
            canonical_root = self.event_root / "cumulative_events"
            canonical_self = canonical_root / f"{target_date}.json"
            if event_path.resolve() != canonical_self.resolve():
                raise Stop("STOP_CUMULATIVE_EVENT_INTEGRITY")
            for path in sorted(canonical_root.glob("*.json")):
                if path.resolve() != canonical_self.resolve():
                    prior = json.loads(path.read_text(encoding="utf-8"))
                    if str(prior.get("target_date")) >= target_date:
                        raise Stop("STOP_NON_MONOTONIC_CUMULATIVE_DATE")
                    ledger.append(prior)
            expected_before = "NOT_STARTED" if not ledger else fold_cumulative_evidence(ledger)["protocol_state_after"]
            if event.get("protocol_state_before") != expected_before:
                raise Stop("STOP_CUMULATIVE_EVENT_CONTENT_MISMATCH")
            ledger.append(event)
            folded=fold_cumulative_evidence(ledger)
        except Stop:
            # Strict chronology is a distinct fail-closed invariant.
            raise
        except Exception as exc:
            raise Stop("STOP_CUMULATIVE_EVENT_CONTENT_MISMATCH") from exc
        checks={"accumulated_races_after_append":folded["counted_races"],"accumulated_dates_after_append":folded["counted_dates"],"accumulated_blocks_after_append":folded["accumulated_blocks"],"comparator":folded["comparator"],"primary":folded["primary"],"secondary":folded["secondary"],"shortfall":folded["shortfall"],"pooled_lift_pt":folded["pooled_lift_pt"],"protocol_state_after":folded["protocol_state_after"],"evaluation_point_consumed":folded["evaluation_point_consumed"],"terminal_verdict":folded["terminal_verdict"],"candidate_label":folded["candidate_label"]}
        if any(event.get(key) != value for key,value in checks.items()):
            raise Stop("STOP_CUMULATIVE_EVENT_CONTENT_MISMATCH")
        return self._store._append_event(target_date, "004_cumulated.json", "CUMULATED", {
            "cumulative_event_path": str(event_path),
            "cumulative_event_sha256": sha(event_path),
            "post_manifest_sha256": post["post_manifest_sha256"],
            "protocol_state_after": event.get("protocol_state_after"),
            "evaluation_point_consumed": event["evaluation_point_consumed"],
            "governance_ledger_head_sha256": checkpoint_head,
        })


@dataclass(frozen=True)
class ProtocolStateTransitions:
    """Artifact-derived protocol writer; no caller boolean may resume it."""
    event_root: Path = DEFAULT_EVENT_ROOT

    def _events(self) -> list[dict[str, Any]]:
        root = self.event_root / "protocol_events"
        if not root.exists():
            return []
        if not root.is_dir():
            raise Stop("STOP_PROTOCOL_STATE_CORRUPT")
        events = []
        for path in sorted(root.glob("*.json")):
            try:
                event = json.loads(path.read_text(encoding="utf-8"))
            except Exception as exc:
                raise Stop("STOP_PROTOCOL_STATE_CORRUPT") from exc
            if not isinstance(event, dict) or event.get("event") != "PROTOCOL_STATE":
                raise Stop("STOP_PROTOCOL_STATE_CORRUPT")
            events.append(event)
        return events

    def state(self) -> str:
        events = self._events()
        return "NOT_STARTED" if not events else str(events[-1].get("state_after"))

    def _append(self, before: str, after: str, payload: dict[str, Any]) -> Path:
        validate_transition(before, after, protocol_level=True)
        root = self.event_root / "protocol_events"
        root.mkdir(parents=True, exist_ok=True)
        path = root / f"{len(self._events()) + 1:03d}_{after.lower().replace(':', '_')}.json"
        try:
            with path.open("x", encoding="utf-8") as handle:
                json.dump({"event": "PROTOCOL_STATE", "recorded_at": _now(), "state_before": before, "state_after": after, **payload}, handle, ensure_ascii=False, indent=2)
                handle.write("\n")
        except FileExistsError as exc:
            raise Stop("STOP_PROTOCOL_STATE_CORRUPT") from exc
        return path

    def mark_from_cumulative_event(self, event_path: Path) -> Path | None:
        """Legacy non-authority: Stage 3A governance owns run state."""
        raise Stop("STOP_LEGACY_PROTOCOL_STATE_WRITER_DISABLED")
        """Derive protocol change from an already frozen cumulative event."""
        try:
            event = json.loads(event_path.read_text(encoding="utf-8"))
        except Exception as exc:
            raise Stop("STOP_CUMULATIVE_EVENT_INTEGRITY") from exc
        # The event is immutable authority for the private technical hook;
        # public callers supply the separately validated current ledger head.
        checkpoint_head = governance_ledger_head_sha256 if governance_ledger_head_sha256 is not None else event.get("governance_ledger_head_sha256")
        before = self.state()
        source_after = event.get("protocol_state_after")
        mapped = {"RUNNING": "RUNNING", "HOLD_VOLUME_CONFOUNDED": "HOLD_VOLUME_CONFOUNDED", "CURRENT_CORRECTED_SHADOW_V2_PROSPECTIVE_ACCEPT": "ACCEPT", "CURRENT_CORRECTED_SHADOW_V2_PROSPECTIVE_REJECT": "REJECT"}.get(source_after)
        if mapped is None:
            raise Stop("STOP_CUMULATIVE_EVENT_INTEGRITY")
        if before == mapped:
            return None
        if before not in {"NOT_STARTED", "RUNNING", "HOLD:EVIDENCE_QUANTITY"}:
            raise Stop("STOP_EVALUATION_POINT_CONSUMED")
        return self._append(before, mapped, {"source": "CUMULATIVE_EVENT", "cumulative_event_path": str(event_path), "cumulative_event_sha256": sha(event_path), "evaluation_point_consumed": event.get("evaluation_point_consumed")})

    def resume_from_artifact(self, artifact_path: Path) -> Path:
        """Legacy non-authority: Stage 3A governance owns run state."""
        raise Stop("STOP_LEGACY_PROTOCOL_STATE_WRITER_DISABLED")
