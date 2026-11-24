"""Regression coverage for date-independent PRE-only analysis export."""
from __future__ import annotations

import csv
import json
import shutil
from pathlib import Path

from review.all_active_systems_analysis_export_v1 import ROOT, build


def _temporary(name: str) -> Path:
    path = ROOT / "reports" / name
    if path.exists():
        raise AssertionError(f"temporary output already exists: {path}")
    return path


def _pre(path: Path, date: str) -> dict:
    return json.loads((path / f"{date}_all_active_systems_pre.json").read_text(encoding="utf-8"))


def _selection_rows(path: Path, date: str) -> set[tuple[str, str, str, str]]:
    with (path / f"{date}_all_active_systems_horse_analysis.csv").open(encoding="utf-8-sig", newline="") as handle:
        return {
            (row["race_id"], row["horse_number"], lane, row[column])
            for row in csv.DictReader(handle)
            for lane, column in (
                ("CURRENT", "current_buy"), ("INDEPENDENT_V5", "independent_v5_selected"),
                ("TRACKCONDITION_SEMANTIC", "trackcondition_selected"),
                ("DAILY_V5_SAME_VOLUME", "daily_v5_selected"), ("FORMAL_V5", "formal_v5_selected"),
                ("FORMAL_V6", "formal_v6_selected"),
            )
            if row[column] == "True"
        }


def test_20261003_semantic_regression_uses_temporary_output() -> None:
    output = _temporary("_all_active_20261003_export_regression")
    try:
        result = build("20261003", output_dir=output)
        assert result["selected_counts"] == {"CURRENT": 14, "INDEPENDENT_V5": 6, "TRACKCONDITION_SEMANTIC": 8, "DAILY_V5_SAME_VOLUME": 14, "FORMAL_V5": 13, "FORMAL_V6": 13}
        assert result["current_race_states"] == {"PLAY_CONVERGED": 8, "PLAY_UNCONVERGED_4PLUS": 2, "SKIP": 5}
        assert result["daily_difference"] == {"retained": 5, "removed_from_current": 9, "newly_selected_by_daily_v5": 9, "changed_races": 8, "eligible_races": 8}
        assert result["v5_v6"] == {"probability_values_different_horses": 129, "probability_rank_changed_horses": 18, "probability_rank_changed_races": 6, "exact5_set_divergence_races": 0, "exact5_internal_order_divergence_races": 3, "final_selection_divergence_races": 0}
        existing = ROOT / "reports"
        assert _selection_rows(output, "20261003") == _selection_rows(existing, "20261003")
        generated = _pre(output, "20261003")
        existing_pre = json.loads((existing / "20261003_all_active_systems_pre.json").read_text(encoding="utf-8"))
        assert generated["active_lanes"] == existing_pre["active_lanes"]
    finally:
        shutil.rmtree(output)


def test_20261004_generalization_and_pre_fixed_union() -> None:
    output = _temporary("_all_active_20261004_export_generalization")
    try:
        result = build("20261004", output_dir=output)
        assert result["selected_counts"] == {"CURRENT": 7, "INDEPENDENT_V5": 13, "TRACKCONDITION_SEMANTIC": 8, "DAILY_V5_SAME_VOLUME": 7, "FORMAL_V5": 7, "FORMAL_V6": 7}
        assert result["current_race_states"] == {"PLAY_CONVERGED": 5, "PLAY_UNCONVERGED_4PLUS": 6, "SKIP": 2}
        assert result["daily_difference"] == {"retained": 3, "removed_from_current": 4, "newly_selected_by_daily_v5": 4, "changed_races": 4, "eligible_races": 5}
        assert result["v5_v6"]["probability_values_different_horses"] == 85
        assert result["v5_v6"]["probability_rank_changed_races"] == 4
        assert result["v5_v6"]["probability_rank_changed_horses"] == 15
        assert result["v5_v6"]["exact5_set_divergence_races"] == 2
        union = json.loads((output / "20261004_all_active_systems_union_phase_a_selection.json").read_text(encoding="utf-8"))
        assert union["union_unique_count"] == 28
        assert union["generated_before_result"] is True and union["result_access_count"] == 0
        assert union["family_definition_version"] == "PRE_FIXED_UNION_FAMILY_DEFINITION_V2"
    finally:
        shutil.rmtree(output)
