"""Additive execution path for CURRENT_CORRECTED_SHADOW_V2.

The production adapter is never edited.  A local predictor proxy preserves
the real RacePacePredictor output for trace and supplies ``average`` to every
consumer reached by the existing production method (RaceStructure, RaceShape,
CourseShape, LapSuitability and Consistency).
"""
from __future__ import annotations

import hashlib
import json
from collections import Counter, defaultdict
from pathlib import Path
from typing import Any

from evaluation.target_trial_adapter import TargetTrialAdapter
from review import target_bulk_prediction_input_shadow_v1 as raw_runner
from review.current_corrected_shadow_v2 import CorrectionConfigV2, RISK_FIELDS, map_risk_text

ROOT = Path(__file__).resolve().parents[1]
CANONICAL_ROOT = ROOT / "reports" / "current_corrected_shadow_v1_raw_replay_v7" / "complete_payloads"

PACE_DEPENDENT_CONSUMERS = (
    "RacePacePredictor", "RaceStructureEngine", "RaceShapeEvaluator",
    "CourseShapeEvaluator", "LapSuitabilityEvaluator", "ConsistencyEngine",
)

def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()

class _AuthorityPaceProxy:
    def __init__(self, delegate, neutral: bool):
        self._delegate, self._neutral, self.original = delegate, neutral, None
    def predict(self, horse_results):
        result = self._delegate.predict(horse_results)
        self.original = result.get("pace_prediction", "average")
        if not self._neutral:
            return result
        corrected = dict(result)
        corrected["pace_prediction"] = "average"
        return corrected

class CorrectedAuthorityAdapter(TargetTrialAdapter):
    """V2-only adapter subclass: production method and source remain intact."""
    def __init__(self, *, neutral_pace: bool):
        super().__init__(learning_phase2_enabled=False, shadow_buy_spec_v1_enabled=False,
                         buy_v1_rc1_enabled=True, enable_learning_candidate_engine=False)
        self._pace_proxy = _AuthorityPaceProxy(self.race_pace_predictor, neutral_pace)
        self.race_pace_predictor = self._pace_proxy
        self._neutral_pace = neutral_pace
    def _apply_race_shape_and_final_scores(self, horse_results, race_defaults=None, track_bias_baseline=None):
        result = super()._apply_race_shape_and_final_scores(horse_results, race_defaults, track_bias_baseline)
        result["predicted_pace_original"] = self._pace_proxy.original
        result["pace_authority_input"] = "average" if self._neutral_pace else self._pace_proxy.original
        for row in horse_results:
            row["predicted_pace_original"] = self._pace_proxy.original
            row["pace_authority_input"] = result["pace_authority_input"]
        return result

def run_new_v2(race_id: str, race_bundle, config: CorrectionConfigV2) -> dict[str, Any]:
    """Execute the full existing pre-race path with an additive pace proxy.

    Temporarily substituting the imported runner's class keeps its orchestration
    byte-for-byte aligned while restoring the module global in ``finally``.
    It does not patch or mutate the production class or any production object.
    """
    original_class = raw_runner.TargetTrialAdapter
    class BoundAdapter(CorrectedAuthorityAdapter):
        def __init__(self, *args, **kwargs): super().__init__(neutral_pace=config.neutral_pace)
    raw_runner.TargetTrialAdapter = BoundAdapter
    try:
        output = raw_runner.run_new(race_id, race_bundle, trace=False)
    finally:
        raw_runner.TargetTrialAdapter = original_class
    pace = {
        "predicted_pace_original": output["ranked_results"][0].get("predicted_pace_original") if output.get("ranked_results") else None,
        "pace_authority_input": output["ranked_results"][0].get("pace_authority_input") if output.get("ranked_results") else None,
        "pace_dependent_consumers": list(PACE_DEPENDENT_CONSUMERS),
    }
    output["v2_pace_trace"] = pace
    return output

def inventory_risk_vocabulary(output_path: Path) -> dict[str, Any]:
    counts, sources = Counter(), defaultdict(Counter)
    race_count = horse_count = 0
    for path in sorted(CANONICAL_ROOT.glob("*.json")):
        payload = json.loads(path.read_text(encoding="utf-8"))
        rows = payload.get("current_replay", {}).get("ranked_results", [])
        race_count += 1; horse_count += len(rows)
        for row in rows:
            for field in RISK_FIELDS:
                values = row.get(field) or []
                for value in values if isinstance(values, list) else [values]:
                    text = str(value); counts[text] += 1; sources[text][field] += 1
    items=[]; unmapped=[]
    for text,count in sorted(counts.items(), key=lambda item:(item[0])):
        mapped=map_risk_text(text)
        if mapped is None:
            unmapped.append(text)
            mapped={"raw_text":text,"normalized_text":text,"category":None,"semantic_cause":None,"authority":None,"severe":None}
        mapped.update({"count":count,"producer_sources":dict(sorted(sources[text].items()))})
        items.append(mapped)
    result={"schema_version":"CURRENT_CORRECTED_SHADOW_V2_RISK_VOCABULARY_V1","canonical_population":{"races":race_count,"horses":horse_count},"items":items,"UNMAPPED_RISK_TEXT_COUNT":len(unmapped),"unmapped":unmapped}
    output_path.parent.mkdir(parents=True,exist_ok=True)
    output_path.write_text(json.dumps(result,ensure_ascii=False,indent=2)+"\n",encoding="utf-8")
    return result
