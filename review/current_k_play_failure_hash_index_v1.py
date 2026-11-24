"""Hash the completed diagnostic artifacts without modifying any source evidence."""
from __future__ import annotations

import json
from pathlib import Path

from review.current_k_play_failure_decomposition_v1 import OUT, ROOT, sha


def main() -> None:
    required = (
        "primary_race_diagnostic.csv", "candidate_generation_diagnostic.json",
        "unconverged_4plus_diagnostic.json", "play_converged_k_diagnostic.json",
        "skip_diagnostic.json", "gate_loss_decomposition.json",
        "current_vs_pl_ordering.json", "temporal_stability.json",
        "primary_findings_951_frozen.json", "secondary_december_check.json",
        "secondary_january_check.json", "final_diagnostic_report.md",
    )
    if any(not (OUT / name).is_file() for name in required):
        raise RuntimeError("STOP_REQUIRED_ARTIFACT_MISSING")
    obj = {
        "role": "DEVELOPMENT_MECHANISM_DIAGNOSTIC_ONLY",
        "primary_frozen_before_secondary_result_access": True,
        "formal_evidence_credit": 0,
        "outputs": {name: {"sha256": sha(OUT / name), "bytes": (OUT / name).stat().st_size} for name in required},
        "implementation": {name: sha(ROOT / "review" / name) for name in (
            "current_k_play_failure_decomposition_v1.py",
            "current_k_play_failure_secondary_v1.py",
            "current_k_play_failure_hash_index_v1.py",
        )},
    }
    (OUT / "artifact_hashes.json").write_text(json.dumps(obj, ensure_ascii=False, sort_keys=True, indent=2) + "\n", encoding="utf-8")
    print("ARTIFACT_HASHES_SHA256=" + sha(OUT / "artifact_hashes.json"))


if __name__ == "__main__":
    main()
