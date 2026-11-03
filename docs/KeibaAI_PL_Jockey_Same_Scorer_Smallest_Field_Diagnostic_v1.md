# SMALLEST_FIELD_FIRST_SAME_SCORER — frozen diagnostic v1

Human authority: `APPROVE_PLJ_ADDENDUM_STEP1_COMPLETION_V1`. This is a new **derived diagnostic**, not a prediction lane, BUY rule, decision gate, Production authority, or formal Evidence source. Evidence credit = 0. The already-frozen `SIMPLE_SMALLEST_FIELD_FIRST` is unchanged and remains a `FIELD_SIZE_ONLY_REFERENCE` with horse-number ordering inside a race.

For each date, use only the already-frozen PRE full-field universe and the frozen Current daily BUY total `N`. Sort races by ascending PRE field size and then canonical PRE `race_id` string. Inside each race, rank horses by the comparator's frozen PRE score descending; break equal scores by integer horse number ascending. Scan races once, select at most three horses per race, and stop at exactly `N`. If the frozen score is missing or capacity is insufficient, the diagnostic is `NOT_EVALUABLE`, never repaired from Result.

For the E1 comparison the scorer is **Frozen PL** `pl_probability` as persisted in E1's `frozen_probabilities_consumed`. For the PL+Jockey global-allocation comparison the scorer is **PL+Jockey** `candidate_p_top3` as persisted in the frozen PL+Jockey PRE. These scores are ranking values only; no calibrated expected-value or betting-odds claim is made. Result, popularity, odds and marks are not read or used to establish membership. Membership SHA is frozen before Result access.

Report the field-size-only benchmark, this same-scorer benchmark, and actual E1 / PL+Jockey allocation separately. This helps describe `FIELD_SIZE_COMPOSITION_EFFECT` versus `GLOBAL_ALLOCATION_VALUE` but cannot alter any existing gate or rescue a failed primary comparison. A new authority would need a new Human-approved protocol.
