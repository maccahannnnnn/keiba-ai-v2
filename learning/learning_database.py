"""Durable storage for Learning Phase2 records.

The database writes record dictionaries to JSON Lines. This keeps the storage
implementation separate from the LearningRecord data shape and can later be
replaced by SQLite, CSV, JSON arrays, or Parquet without changing callers.
"""

import json
from pathlib import Path

from .learning_record import LearningRecord


class LearningDatabase:
    """Append-only Learning Phase2 record store."""

    DEFAULT_PATH = Path("learning") / "learning_phase2_records.jsonl"

    def __init__(self, storage_path=None):
        self.storage_path = Path(storage_path) if storage_path else self.DEFAULT_PATH

    def save_records(self, records):
        rows = [self._record_to_dict(record) for record in records]
        if not rows:
            return {
                "saved": False,
                "record_count": 0,
                "storage_path": str(self.storage_path),
            }

        self.storage_path.parent.mkdir(parents=True, exist_ok=True)
        with self.storage_path.open("a", encoding="utf-8", newline="\n") as file:
            for row in rows:
                file.write(json.dumps(row, ensure_ascii=False, sort_keys=True))
                file.write("\n")

        return {
            "saved": True,
            "record_count": len(rows),
            "storage_path": str(self.storage_path),
        }

    def load_records(self):
        if not self.storage_path.exists():
            return []
        rows = []
        with self.storage_path.open("r", encoding="utf-8") as file:
            for line in file:
                text = line.strip()
                if not text:
                    continue
                rows.append(json.loads(text))
        return rows

    def _record_to_dict(self, record):
        if isinstance(record, LearningRecord):
            return record.to_dict()
        if isinstance(record, dict):
            return dict(record)
        raise TypeError("LearningDatabase accepts LearningRecord or dict rows only.")
