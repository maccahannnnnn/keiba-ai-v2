"""Read-only source collector for MeetingBias evidence.

This collector builds the minimum analysis/result shape needed by
MeetingBiasEvidenceExtractor from saved artifacts only. It never imports or
constructs the Production adapter and never recalculates evaluator, Decision,
BUY, or score output.
"""

from __future__ import annotations

import csv
import hashlib
import json
import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from review.meeting_stage_resolver import MeetingStageResolver


class MeetingBiasReadOnlyCollector:
    """Collect MeetingBias evidence inputs from persisted review artifacts."""

    VERSION = "meeting_bias_read_only_collector_v1"
    REVIEW_DIR_RE = re.compile(r"^review_(?P<date>\d{8})$")
    RACE_CSV_RE = re.compile(r"^race_summary_(?P<date>\d{8})(?:_v(?P<version>\d+))?\.csv$")
    HORSE_CSV_RE = re.compile(r"^horse_review_(?P<date>\d{8})(?:_v(?P<version>\d+))?\.csv$")
    LEGACY_RACE_CSV = "race_review.csv"
    LEGACY_HORSE_CSV = "horse_review.csv"

    def __init__(
        self,
        root: Path | str = Path("."),
        reports_dir: Path | str = "reports",
        pre_race_dir: Path | str = "reports/pre_race",
        results_dir: Path | str = "data/results",
        analysis_dir: Path | str = "data/analysis",
        meeting_stage_resolver: MeetingStageResolver | None = None,
    ) -> None:
        self.root = Path(root)
        self.reports_dir = self.root / Path(reports_dir)
        self.pre_race_dir = self.root / Path(pre_race_dir)
        self.results_dir = self.root / Path(results_dir)
        self.analysis_dir = self.root / Path(analysis_dir)
        self.meeting_stage_resolver = meeting_stage_resolver or MeetingStageResolver(self.root)

    def collect(self) -> dict[str, Any]:
        """Return saved MeetingBias source records without Production execution."""

        records: list[dict[str, Any]] = []
        horse_rows: list[dict[str, Any]] = []
        errors: list[dict[str, Any]] = []
        manifest: list[dict[str, Any]] = []

        for review_dir in self._review_dirs():
            pair = self._latest_review_pair(review_dir)
            if not pair:
                continue
            race_rows = self._read_csv(pair["race_csv"])
            review_horse_rows = self._read_csv(pair["horse_csv"])
            race_map = {row.get("race_id"): row for row in race_rows if row.get("race_id")}
            horse_map: dict[str, list[dict[str, Any]]] = {}
            for row in review_horse_rows:
                horse_map.setdefault(row.get("race_id") or "", []).append(row)

            for race_id, race_row in race_map.items():
                try:
                    race_horses = horse_map.get(race_id, [])
                    result_paths = self._result_paths(race_id)
                    pre_race_row = self._pre_race_race_row(race_id)
                    official = self._official_payload(race_id, result_paths)
                    stage_resolution = self.meeting_stage_resolver.resolve_one(race_id)
                    analysis = self._analysis_payload(race_id, race_row, pre_race_row, race_horses, stage_resolution)
                    ranked = analysis["ranked_results"]
                    records.append(
                        {
                            "race_set": {
                                "race_id": race_id,
                                "source_review_dir": str(review_dir),
                                "source_race_summary_path": str(pair["race_csv"]),
                                "source_horse_review_path": str(pair["horse_csv"]),
                                "race_result_path": str(result_paths.get("race_result_path") or ""),
                                "horse_result_path": str(result_paths.get("horse_result_path") or ""),
                                "replay_mode": "READ_ONLY_SAVED_ARTIFACTS",
                                "production_adapter_used": "NO",
                                "result_data_used_as_evaluation_input": "NO",
                            },
                            "race_id": race_id,
                            "analysis": analysis,
                            "official": official,
                            "ranked_rows": ranked,
                            "official_map": self._official_map(official.get("horse_results")),
                        }
                    )
                    for index, row in enumerate(ranked, start=1):
                        merged = dict(row)
                        result = self._lookup(records[-1]["official_map"], row.get("horse_name"))
                        merged.update(
                            {
                                "race_id": race_id,
                                "actual_finish": self._to_int((result or {}).get("finish_position")),
                                "official_result": result or {},
                                "top5": index <= 5,
                                "ai_rank": index,
                                "replay_mode": "READ_ONLY_SAVED_ARTIFACTS",
                            }
                        )
                        horse_rows.append(merged)
                    manifest.append(self._manifest_row(review_dir, pair, race_id, result_paths, pre_race_row, stage_resolution))
                except Exception as exc:  # pragma: no cover - defensive evidence safety
                    errors.append({"race_id": race_id, "error": str(exc), "source": "MeetingBiasReadOnlyCollector"})

        return {
            "race_records": records,
            "horse_rows": horse_rows,
            "errors": errors,
            "source_manifest": manifest,
            "collector_version": self.VERSION,
            "created_at": datetime.now(timezone.utc).isoformat(),
            "replay_mode": "READ_ONLY_SAVED_ARTIFACTS",
            "evaluator_reexecuted": "NO",
            "decision_recalculated": "NO",
            "buy_recalculated": "NO",
            "production_adapter_used": "NO",
            "result_data_used_as_evaluation_input": "NO",
        }

    def _review_dirs(self) -> list[Path]:
        if not self.reports_dir.exists():
            return []
        return sorted(
            path
            for path in self.reports_dir.iterdir()
            if path.is_dir() and self.REVIEW_DIR_RE.match(path.name)
        )

    def _latest_review_pair(self, review_dir: Path) -> dict[str, Path] | None:
        race_files = self._versioned_files(review_dir, self.RACE_CSV_RE)
        horse_files = self._versioned_files(review_dir, self.HORSE_CSV_RE)
        date = review_dir.name.replace("review_", "")
        race_csv = race_files.get(date)
        horse_csv = horse_files.get(date)
        legacy_race = review_dir / self.LEGACY_RACE_CSV
        legacy_horse = review_dir / self.LEGACY_HORSE_CSV
        if not race_csv and legacy_race.exists():
            race_csv = legacy_race
        if not horse_csv and legacy_horse.exists():
            horse_csv = legacy_horse
        if not race_csv or not horse_csv:
            return None
        return {"race_csv": race_csv, "horse_csv": horse_csv}

    def _versioned_files(self, directory: Path, pattern: re.Pattern[str]) -> dict[str, Path]:
        selected: dict[str, tuple[int, Path]] = {}
        for path in directory.iterdir():
            if not path.is_file():
                continue
            match = pattern.match(path.name)
            if not match:
                continue
            date = match.group("date")
            version = int(match.group("version") or 0)
            if date not in selected or version > selected[date][0]:
                selected[date] = (version, path)
        return {date: item[1] for date, item in selected.items()}

    def _pre_race_race_row(self, race_id: str) -> dict[str, Any]:
        date = self._race_id_part(race_id, 1)
        path = self.pre_race_dir / date / f"pre_race_{date}_race_summary.csv"
        if not path.exists():
            return {}
        for row in self._read_csv(path):
            if row.get("race_id") == race_id:
                return row
        return {}

    def _result_paths(self, race_id: str) -> dict[str, Path | None]:
        suffix = race_id.replace("race_", "")
        return {
            "race_result_path": self.results_dir / f"race_{suffix}_result.csv",
            "horse_result_path": self.results_dir / f"horse_{suffix}_result.csv",
            "entry_path": self.analysis_dir / f"race_{suffix}_entry.csv",
            "horses_path": self.analysis_dir / f"race_{suffix}_horses.csv",
        }

    def _official_payload(self, race_id: str, paths: dict[str, Path | None]) -> dict[str, Any]:
        race_result = {}
        race_path = paths.get("race_result_path")
        if race_path and race_path.exists():
            rows = self._read_csv(race_path)
            race_result = self._normalize_race_result(race_id, rows[0] if rows else {})
        horse_results = []
        horse_path = paths.get("horse_result_path")
        if horse_path and horse_path.exists():
            horse_results = [self._normalize_horse_result(row) for row in self._read_csv(horse_path)]
        return {"race_result": race_result, "horse_results": horse_results}

    def _analysis_payload(
        self,
        race_id: str,
        race_row: dict[str, Any],
        pre_race_row: dict[str, Any],
        horse_rows: list[dict[str, Any]],
        stage_resolution: Any,
    ) -> dict[str, Any]:
        race_structure = self._json_cell(pre_race_row.get("race_structure"))
        race_output = race_structure.get("race_structure_result", {}).get("race_structure", {})
        if not isinstance(race_output, dict):
            race_output = {}
        if not race_output:
            race_output = {
                "racecourse": race_row.get("course") or self._race_id_part(race_id, 2),
                "distance": "",
                "surface": "",
                "track_condition": "",
            }
        if stage_resolution and getattr(stage_resolution, "meeting_stage", "UNKNOWN") != "UNKNOWN":
            race_output["meeting_stage"] = stage_resolution.meeting_stage
            race_output["meeting_stage_source"] = stage_resolution.meeting_stage_source
            race_output["meeting_stage_derivation_method"] = stage_resolution.derivation_method
            race_output["meeting_stage_derivation_confidence"] = stage_resolution.derivation_confidence
            race_output["meeting_day"] = stage_resolution.meeting_day_index
            race_output["meeting_week"] = stage_resolution.meeting_week
        meeting_bias = race_structure.get("meeting_bias_result", {})
        if isinstance(meeting_bias, dict):
            meeting_bias = dict(meeting_bias)
            meeting_bias["selected_meeting_stage"] = getattr(stage_resolution, "meeting_stage", "UNKNOWN")
            meeting_bias["meeting_stage_source"] = getattr(stage_resolution, "meeting_stage_source", "UNKNOWN")
        ranked = []
        for row in sorted(horse_rows, key=lambda item: self._to_int(item.get("ai_rank")) or 999):
            ranked.append(
                {
                    "horse_name": row.get("horse_name"),
                    "decision": row.get("decision"),
                    "legacy_decision": row.get("legacy_decision"),
                    "final_rank": self._to_int(row.get("ai_rank")),
                    "ai_rank": self._to_int(row.get("ai_rank")),
                    "final_score": row.get("final_score"),
                    "adjusted_score": row.get("adjusted_score"),
                    "shape_score": row.get("race_shape_score"),
                    "track_bias_score": row.get("track_bias_score"),
                    "pace_style": row.get("pace_style") or row.get("running_style"),
                    "confidence": row.get("confidence"),
                }
            )
        return {
            "ranked_results": ranked,
            "race_output": race_output,
            "meeting_bias_result": meeting_bias if isinstance(meeting_bias, dict) else {},
            "race_structure": race_structure,
            "manual_track_bias": race_output.get("manual_track_bias"),
            "source_evaluation_origin": "SAVED_REVIEW_OR_PRE_RACE_OUTPUT",
        }

    def _normalize_race_result(self, race_id: str, row: dict[str, Any]) -> dict[str, Any]:
        return {
            "race_id": race_id,
            "race_date": f"{row.get('年','')}{row.get('月','')}{row.get('日','')}" or self._race_id_part(race_id, 1),
            "racecourse": self._race_id_part(race_id, 2),
            "race_number": f"{row.get('R') or self._race_id_part(race_id, 3)}",
            "surface": self._surface(row.get("芝・ダート")),
            "distance": row.get("距離"),
            "track_condition": row.get("馬場状態"),
        }

    def _normalize_horse_result(self, row: dict[str, Any]) -> dict[str, Any]:
        return {
            "finish_position": row.get("確定着順") or row.get("finish_position"),
            "frame_number": row.get("枠番") or row.get("frame_number"),
            "horse_number": row.get("馬番") or row.get("horse_number"),
            "horse_name": row.get("馬名") or row.get("horse_name"),
            "fourth_corner_position": row.get("通過4") or row.get("fourth_corner_position"),
            "last_3f": row.get("上り3F") or row.get("last_3f"),
        }

    def _manifest_row(
        self,
        review_dir: Path,
        pair: dict[str, Path],
        race_id: str,
        result_paths: dict[str, Path | None],
        pre_race_row: dict[str, Any],
        stage_resolution: Any,
    ) -> dict[str, Any]:
        paths = {
            "race_summary": pair["race_csv"],
            "horse_review": pair["horse_csv"],
            **{key: value for key, value in result_paths.items() if value},
        }
        return {
            "race_id": race_id,
            "source_file": str(pair["horse_csv"]),
            "source_version": pair["horse_csv"].stem,
            "source_sha256": self._sha256(pair["horse_csv"]),
            "source_evaluation_origin": "SAVED_REVIEW_OR_PRE_RACE_OUTPUT",
            "replay_mode": "READ_ONLY_SAVED_ARTIFACTS",
            "evaluator_reexecuted": "NO",
            "decision_recalculated": "NO",
            "buy_recalculated": "NO",
            "production_adapter_used": "NO",
            "result_data_used_as_evaluation_input": "NO",
            "review_dir": str(review_dir),
            "pre_race_source_available": bool(pre_race_row),
            "analysis_exists": bool((result_paths.get("entry_path") or Path()).exists()),
            "results_exists": bool((result_paths.get("horse_result_path") or Path()).exists()),
            "source_files": {
                key: {
                    "path": str(path),
                    "exists": path.exists(),
                    "sha256": self._sha256(path) if path.exists() else "",
                }
                for key, path in paths.items()
            },
            "created_at": datetime.now(timezone.utc).isoformat(),
            "collector_version": self.VERSION,
            "meeting_stage_resolution": stage_resolution.to_dict() if stage_resolution else {},
        }

    def _official_map(self, horse_results: Any) -> dict[str, dict[str, Any]]:
        return {
            self._norm(row.get("horse_name")): row
            for row in self._list(horse_results)
            if row.get("horse_name")
        }

    def _lookup(self, mapping: dict[str, dict[str, Any]], name: Any) -> dict[str, Any] | None:
        return mapping.get(self._norm(name))

    def _read_csv(self, path: Path) -> list[dict[str, Any]]:
        last_error: UnicodeDecodeError | None = None
        for encoding in ("utf-8-sig", "cp932"):
            try:
                with path.open("r", encoding=encoding, newline="") as handle:
                    return [dict(row) for row in csv.DictReader(handle)]
            except UnicodeDecodeError as exc:
                last_error = exc
        if last_error:
            raise last_error
        return []

    def _json_cell(self, value: Any) -> dict[str, Any]:
        if value in (None, ""):
            return {}
        try:
            loaded = json.loads(str(value))
        except json.JSONDecodeError:
            return {}
        return loaded if isinstance(loaded, dict) else {}

    def _sha256(self, path: Path) -> str:
        digest = hashlib.sha256()
        with path.open("rb") as handle:
            for chunk in iter(lambda: handle.read(1024 * 1024), b""):
                digest.update(chunk)
        return digest.hexdigest()

    def _surface(self, value: Any) -> str:
        text = str(value or "").strip().lower()
        if text in {"芝", "turf"}:
            return "turf"
        if text in {"ダート", "ダ", "dirt"}:
            return "dirt"
        return text

    def _race_id_part(self, race_id: str, index: int) -> str:
        parts = str(race_id or "").split("_")
        return parts[index] if len(parts) > index else ""

    def _to_int(self, value: Any) -> int | None:
        if isinstance(value, bool) or value in (None, ""):
            return None
        try:
            return int(float(str(value).strip()))
        except (TypeError, ValueError):
            return None

    def _norm(self, value: Any) -> str:
        return "".join(str(value or "").split())

    def _list(self, value: Any) -> list[Any]:
        return value if isinstance(value, list) else []
