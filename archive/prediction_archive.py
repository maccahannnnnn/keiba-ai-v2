"""PredictionArchive storage for KeibaAI history records.

This module only stores and retrieves archive JSON files. It does not modify
scores, decisions, confidence, knowledge, CSV schemas, or learning behavior.
"""

import json
import uuid
from datetime import datetime, timezone
from pathlib import Path


class PredictionArchive:
    """Save, list, load, and search archived prediction-related records."""

    SCHEMA_VERSION = "prediction_archive_v1"
    ALLOWED_TYPES = {"prediction", "statistics", "review", "learning", "unknown"}
    METADATA_KEYS = (
        "race_id",
        "racecourse",
        "course",
        "surface",
        "distance",
        "track_condition",
        "decision",
        "confidence",
        "source",
    )

    def __init__(self, archive_dir="data/prediction_archive"):
        self.archive_dir = Path(archive_dir)
        self.archive_dir.mkdir(parents=True, exist_ok=True)

    def save(self, payload, archive_type="prediction", metadata=None, summary=None, tags=None):
        """Wrap payload in archive format, save it as JSON, and return archive info."""

        archive_record = self._build_archive_record(payload, archive_type, metadata, summary, tags)
        archive_id = archive_record.get("metadata", {}).get("archive_id")
        created_at = archive_record.get("metadata", {}).get("created_at", "")
        timestamp = self._filename_timestamp(created_at)
        filename = f"archive_{timestamp}_{archive_id}.json"
        output_path = self.archive_dir / filename

        try:
            with output_path.open("w", encoding="utf-8") as handle:
                json.dump(archive_record, handle, ensure_ascii=False, indent=2)
        except (OSError, TypeError):
            return None
        return {"archive_id": archive_id, "path": str(output_path)}

    def list_archives(self, archive_type=None, limit=None):
        """Return metadata for saved archives, newest first."""

        archives = []
        for path in self._archive_files():
            record = self._safe_load_json(path)
            if not isinstance(record, dict):
                continue
            metadata = record.get("metadata")
            if not isinstance(metadata, dict):
                continue
            if archive_type is not None and str(metadata.get("archive_type")) != str(archive_type):
                continue
            archives.append(dict(metadata))

        archives.sort(key=lambda item: str(item.get("created_at", "")), reverse=True)
        if isinstance(limit, int) and limit >= 0:
            return archives[:limit]
        return archives

    def load(self, archive_id):
        """Load the archive whose metadata.archive_id matches archive_id."""

        if archive_id in {None, ""}:
            return None
        for path in self._archive_files():
            record = self._safe_load_json(path)
            if not isinstance(record, dict):
                continue
            metadata = record.get("metadata")
            if isinstance(metadata, dict) and str(metadata.get("archive_id")) == str(archive_id):
                return record
        return None

    def search(self, filters=None, limit=None):
        """Search archives by exact metadata values."""

        if not filters:
            return self.list_archives(limit=limit)

        metadata_filters = dict(filters) if isinstance(filters, dict) else {}
        archive_type = metadata_filters.pop("archive_type", None)
        candidates = self.list_archives(archive_type=archive_type)
        matches = []
        for metadata in candidates:
            if all(str(metadata.get(key, "")) == str(value) for key, value in metadata_filters.items()):
                matches.append(metadata)
        if isinstance(limit, int) and limit >= 0:
            return matches[:limit]
        return matches

    def _build_archive_record(self, payload, archive_type, metadata, summary, tags):
        """Build the standard archive dictionary."""

        warnings = []
        converted_payload = self._payload_to_dict(payload, warnings)
        source_metadata = metadata if isinstance(metadata, dict) else {}
        if not source_metadata:
            warnings.append("metadata is empty")
        if not converted_payload:
            warnings.append("payload is empty")

        normalized_type = archive_type if archive_type in self.ALLOWED_TYPES else "unknown"
        if normalized_type == "unknown":
            warnings.append("archive_type is unknown")

        archive_id = str(source_metadata.get("archive_id") or uuid.uuid4())
        created_at = datetime.now(timezone.utc).isoformat()
        archive_metadata = {
            "archive_id": archive_id,
            "archive_type": normalized_type,
            "schema_version": self.SCHEMA_VERSION,
            "created_at": created_at,
            "source": "",
            "race_id": "",
            "racecourse": "",
            "course": "",
            "surface": "",
            "distance": "",
            "track_condition": "",
            "decision": "",
            "confidence": "",
        }
        for key in self.METADATA_KEYS:
            if key in source_metadata and source_metadata.get(key) is not None:
                archive_metadata[key] = str(source_metadata.get(key))

        archive_summary = summary if isinstance(summary, dict) else {}
        archive_tags = tags if isinstance(tags, list) else []

        return {
            "metadata": archive_metadata,
            "summary": archive_summary,
            "payload": converted_payload,
            "tags": archive_tags,
            "warnings": warnings,
        }

    def _safe_load_json(self, path):
        """Safely load JSON and return None on failure."""

        try:
            with Path(path).open("r", encoding="utf-8") as handle:
                return json.load(handle)
        except (OSError, json.JSONDecodeError, TypeError):
            return None

    def _payload_to_dict(self, payload, warnings):
        if isinstance(payload, dict):
            return payload
        if hasattr(payload, "to_dict") and callable(payload.to_dict):
            try:
                value = payload.to_dict()
            except Exception:
                warnings.append("to_dict conversion failed")
                return {}
            if isinstance(value, dict):
                return value
            warnings.append("to_dict did not return dict")
            return {}
        if payload is None:
            return {}
        warnings.append("payload is not dict")
        return {"value": payload}

    def _archive_files(self):
        if not self.archive_dir.exists():
            return []
        return sorted(self.archive_dir.glob("archive_*.json"), key=lambda path: path.stat().st_mtime, reverse=True)

    def _filename_timestamp(self, created_at):
        try:
            parsed = datetime.fromisoformat(str(created_at).replace("Z", "+00:00"))
            return parsed.strftime("%Y%m%d_%H%M%S")
        except ValueError:
            return datetime.now().strftime("%Y%m%d_%H%M%S")


if __name__ == "__main__":
    archive = PredictionArchive()
    saved = archive.save({"sample": True}, metadata={"racecourse": "tokyo"})
    print(saved)
