"""Independent read-only validator for the REG-009 result cohort V1."""

from __future__ import annotations

import argparse
import hashlib
import json
from collections import Counter
from pathlib import Path
from typing import Any

from review.reg009_retrospective_oos_result_cohort_generator_v1 import (
    REQUIRED_ARTIFACTS,
    SCHEMA_VERSION,
    CohortGenerationError,
    ResultCohortGeneratorConfig,
    sha256_path,
)


class Reg009RetrospectiveOOSResultCohortValidatorV1:
    """Validate without repairing, rewriting, or normalizing cohort artifacts."""

    def __init__(self, config: ResultCohortGeneratorConfig | None = None):
        self.config = config or ResultCohortGeneratorConfig()

    def validate(self, output_root: str | Path) -> dict[str, Any]:
        root = Path(output_root)
        if not root.is_dir():
            return self._fail("OUTPUT_ROOT_NOT_FOUND")
        names = sorted(path.name for path in root.iterdir() if path.is_file())
        if names != sorted(REQUIRED_ARTIFACTS):
            return self._fail("REQUIRED_ARTIFACT_SET_MISMATCH", {"actual": names, "expected": sorted(REQUIRED_ARTIFACTS)})
        try:
            docs = {name: json.loads((root / name).read_text(encoding="utf-8")) for name in REQUIRED_ARTIFACTS if name.endswith(".json")}
        except (UnicodeDecodeError, json.JSONDecodeError) as exc:
            return self._fail("JSON_SYNTAX_ERROR", str(exc))

        manifest = docs["cohort_manifest.json"]
        races_doc = docs["race_results.json"]
        horses_doc = docs["horse_results.json"]
        reconciliation = docs["population_reconciliation.json"]
        derivation = docs["derivation_validation.json"]
        provenance = docs["provenance.json"]
        for name, doc in docs.items():
            if doc.get("schema_version") != SCHEMA_VERSION:
                return self._fail("SCHEMA_VERSION_MISMATCH", name)

        if manifest.get("status") != "COHORT_GENERATION_COMPLETE" or manifest.get("exclusive_create") is not True:
            return self._fail("MANIFEST_STATUS_OR_EXCLUSIVE_CREATE_INVALID")
        if manifest.get("required_artifacts") != list(REQUIRED_ARTIFACTS):
            return self._fail("MANIFEST_REQUIRED_ARTIFACTS_INVALID")
        if tuple(manifest.get("allowed_dates", [])) != self.config.allowed_dates:
            return self._fail("ALLOWED_DATES_MISMATCH")
        if manifest.get("source_raw_sha256") != self.config.raw_sha256 or sha256_path(self.config.raw_path) != self.config.raw_sha256:
            return self._fail("SOURCE_SHA256_MISMATCH")
        if manifest.get("population_record_sha256") != self.config.population_sha256 or sha256_path(self.config.population_path) != self.config.population_sha256:
            return self._fail("POPULATION_SHA256_MISMATCH")
        authority = provenance.get("authority", {})
        if authority.get("authority_sha256") != self.config.authority_sha256:
            return self._fail("AUTHORITY_SHA256_MISMATCH")
        if authority.get("frozen_spec_sha256") != self.config.frozen_spec_sha256:
            return self._fail("FROZEN_SPEC_SHA256_MISMATCH")
        if authority.get("generation_spec_sha256") != self.config.generation_spec_sha256:
            return self._fail("GENERATION_SPEC_SHA256_MISMATCH")

        races = races_doc.get("records")
        horses = horses_doc.get("records")
        if not isinstance(races, list) or not isinstance(horses, list):
            return self._fail("RECORD_ARRAY_MISSING")
        if races_doc.get("record_count") != len(races) or horses_doc.get("record_count") != len(horses):
            return self._fail("RECORD_COUNT_MISMATCH")
        if len(races) != self.config.expected_population_all:
            return self._fail("RACE_COUNT_MISMATCH", len(races))
        included = [r for r in races if r.get("included_in_oos_cohort")]
        excluded = [r for r in races if not r.get("included_in_oos_cohort")]
        if len(included) != self.config.expected_population_included or len(excluded) != self.config.expected_population_all - self.config.expected_population_included:
            return self._fail("POPULATION_COUNTS_MISMATCH")
        if len({r.get("canonical_race_id") for r in races}) != len(races):
            return self._fail("DUPLICATE_RACE_ID")
        if races != sorted(races, key=lambda r: r["canonical_race_id"]):
            return self._fail("RACE_ORDER_NOT_DETERMINISTIC")
        if horses != sorted(horses, key=lambda h: (h["canonical_race_id"], int(h["horse_number"]), h["horse_name"])):
            return self._fail("HORSE_ORDER_NOT_DETERMINISTIC")

        included_ids = {r["canonical_race_id"] for r in included}
        identities: set[str] = set()
        by_race: dict[str, list[dict[str, Any]]] = {}
        for horse in horses:
            required = {
                "canonical_race_id", "source_race_id", "source_row_number", "horse_number", "horse_name",
                "stable_source_horse_id", "identity_key", "raw_finish", "parsed_finish", "raw_abnormal_status",
                "derived_valid_result", "derived_actual_top3", "derivation_reason", "source_raw_sha256",
            }
            if not required.issubset(horse):
                return self._fail("HORSE_SCHEMA_MISSING_FIELDS", sorted(required.difference(horse)))
            race_id = str(horse["canonical_race_id"])
            if race_id not in included_ids:
                return self._fail("HORSE_FROM_EXCLUDED_OR_UNKNOWN_RACE", race_id)
            identity = str(horse["identity_key"])
            expected_identity = f"{race_id}|{int(horse['horse_number'])}"
            if identity != expected_identity or identity in identities:
                return self._fail("HORSE_IDENTITY_INVALID", identity)
            identities.add(identity)
            if not str(horse["horse_name"]).strip():
                return self._fail("HORSE_NAME_MISSING", identity)
            try:
                finish = int(horse["parsed_finish"])
                abnormal = int(str(horse["raw_abnormal_status"]))
            except (TypeError, ValueError):
                return self._fail("DERIVATION_PARSE_INVALID", identity)
            valid = bool(horse["derived_valid_result"])
            top3 = bool(horse["derived_actual_top3"])
            if abnormal == 0:
                if not valid or finish <= 0:
                    return self._fail("VALID_RESULT_DERIVATION_INVALID", identity)
            elif valid:
                return self._fail("ABNORMAL_RESULT_MARKED_VALID", identity)
            expected_top3 = bool(valid and finish in {1, 2, 3})
            if top3 != expected_top3 or (not valid and top3):
                return self._fail("ACTUAL_TOP3_DERIVATION_INVALID", identity)
            if horse.get("source_raw_sha256") != self.config.raw_sha256:
                return self._fail("HORSE_SOURCE_SHA_MISMATCH", identity)
            by_race.setdefault(race_id, []).append(horse)

        for race_id, race_horses in by_race.items():
            counts = Counter(int(h["parsed_finish"]) for h in race_horses if h["derived_valid_result"])
            expected = 1
            for rank in sorted(counts):
                if rank != expected:
                    return self._fail("INVALID_SKIP_RANK_SEQUENCE", {"race_id": race_id, "expected": expected, "actual": rank})
                expected += counts[rank]

        race_map = {r["canonical_race_id"]: r for r in included}
        for race_id, race in race_map.items():
            actual = by_race.get(race_id, [])
            if len(actual) != int(race["source_horse_row_count"]):
                return self._fail("HORSE_COUNT_RECONCILIATION_FAILED", race_id)
            valid_count = sum(bool(h["derived_valid_result"]) for h in actual)
            if valid_count != int(race["derived_valid_horse_count"]):
                return self._fail("VALID_HORSE_COUNT_MISMATCH", race_id)

        if reconciliation.get("status") != "PASS" or reconciliation.get("missing_race_count") != 0 or reconciliation.get("extra_race_count") != 0:
            return self._fail("POPULATION_RECONCILIATION_FAILED")
        counts = reconciliation.get("counts", {})
        if counts.get("all") != self.config.expected_population_all or counts.get("included") != self.config.expected_population_included:
            return self._fail("POPULATION_RECONCILIATION_COUNT_MISMATCH")
        if derivation.get("status") != "PASS" or derivation.get("derivation_failure_count") != 0 or derivation.get("inferred_value_count") != 0:
            return self._fail("DERIVATION_VALIDATION_FAILED")
        cross = derivation.get("crosscheck", {})
        if cross.get("status") != "PASS" or any(cross.get(k) != 0 for k in ("identity_mismatch_count", "row_set_mismatch_count", "valid_result_mismatch_count", "actual_top3_mismatch_count")):
            return self._fail("CROSSCHECK_FAILED")
        if cross.get("race_count") != self.config.expected_crosscheck_races or cross.get("horse_count") != self.config.expected_crosscheck_horses:
            return self._fail("CROSSCHECK_COUNT_MISMATCH")

        artifact_hashes = provenance.get("artifact_sha256_excluding_provenance")
        if not isinstance(artifact_hashes, dict) or set(artifact_hashes) != set(REQUIRED_ARTIFACTS).difference({"provenance.json"}):
            return self._fail("ARTIFACT_HASH_MANIFEST_INVALID")
        for name, expected_sha in artifact_hashes.items():
            if sha256_path(root / name) != expected_sha:
                return self._fail("ARTIFACT_SHA256_MISMATCH", name)
        if provenance.get("exclusive_create") is not True:
            return self._fail("EXCLUSIVE_CREATE_PROVENANCE_MISSING")
        for key in ("oos_evaluation_count", "prediction_count", "shadow_count", "production_connection_count", "feature_flag_connection_count", "data_results_write_count", "prohibited_field_use_count"):
            if provenance.get(key) != 0:
                return self._fail("PROHIBITED_OPERATION_RECORDED", key)
        return {
            "status": "PASS",
            "reason_code": None,
            "artifact_count": len(REQUIRED_ARTIFACTS),
            "race_count": len(races),
            "horse_count": len(horses),
            "duplicate_count": 0,
            "collision_count": 0,
            "ambiguous_count": 0,
            "missing_count": 0,
            "artifact_sha_mismatch_count": 0,
            "mutated_artifact_count": 0,
        }

    @staticmethod
    def _fail(reason: str, details: Any = None) -> dict[str, Any]:
        return {"status": "FAIL", "reason_code": reason, "details": details, "mutated_artifact_count": 0}


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Read-only validator for a REG-009 retrospective OOS result cohort.")
    parser.add_argument("--output-root", type=Path, required=True)
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    result = Reg009RetrospectiveOOSResultCohortValidatorV1().validate(args.output_root)
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0 if result["status"] == "PASS" else 1


if __name__ == "__main__":
    raise SystemExit(main())
