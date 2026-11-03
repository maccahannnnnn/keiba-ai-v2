# PL+Jockey derived diagnostic definitions v1

Authority: `APPROVED_ROLE_REALLOCATION_DESIGN_V1`. All selection sets are constructed from PRE artifacts before opening Results. These definitions are frozen for dates strictly after the addendum freeze. They create no lane, BUY rule, Production authority or formal Evidence credit. Missing PRE authority or post-freeze selection is `NOT_EVALUABLE`, not a reason to infer or optimize selections.

## Field size

For every selected horse with PRE field size `f > 0`, `b_f = min(3,f)/f`. For PL+Jockey, Current and E1 separately, report PRE selected N, field-size distribution and mean size. On the valid-result selected subset only, report `EXPECTED_HITS_FROM_FIELD_SIZE = sum(b_f)`, `EXCESS_HITS = actual Top3 hits - expected hits`, `MEAN_FIELD_SIZE_BASE_RATE = mean(b_f)`, and `BASE_RATE_RATIO = (hits / valid N) / mean(b_f)`. Also report `STATISTICAL_ODDS_RATIO = [p/(1-p)] / [b/(1-b)]`, where `p=hits/valid N` and `b=mean(b_f)`; a zero denominator or endpoint 0/1 is `NOT_DEFINED`, not silently smoothed. This is a statistical outcome odds ratio, not a betting-odds field. Invalid selections appear in PRE N and invalid count but not valid-result hit/rate/expected-hit calculations. Field size is the frozen PRE field size, never a Result-derived headcount.

## Simple smallest-field-first benchmark

Diagnostic-only, per date. Use the same frozen daily Current BUY total N and the existing PRE eligible horse universe. Order races by ascending PRE field size, then canonical PRE `race_id` string ascending. Within each race order horses by integer horse number ascending. Take at most three horses per race in this single scan until N slots are filled. If N cannot be filled, mark `NOT_EVALUABLE`; do not add a new source/race. No score, Result, odds or popularity is consulted. This horse-number fallback is intentionally non-predictive. Compare E1 to this benchmark at the same N and report any E1 difference not exceeding benchmark as `FIELD_SIZE_COMPOSITION_EFFECT`, not `ALLOCATION_SKILL_GAIN`. The E1 Rule A endpoint, ordinary BUY_TOP3_RATE and prospective gate do not change.

## PL+Jockey ∩ E1

Within identical date/race/horse keys, partition the frozen selections into (A) `PL_JOCKEY_E1_OVERLAP`, (B) PL+Jockey only, (C) E1 only. Each partition reports selected, invalid, valid, hits, ordinary rate, field-size expected hits, excess hits and base-rate ratio. Report raw rate and excess-hit-per-valid-horse differences of A versus B and A versus C; unavailable denominators are `NOT_DEFINED`. No subgroup matching or optimization. This overlap has no BUY or decision gate and formal Evidence credit 0.

## PL+Jockey global allocation candidate

`PL_JOCKEY_GLOBAL_RANK_DIAGNOSTIC` uses the frozen full-field PL+Jockey Top3-inclusion probability as a **ranking score only**. Across the approved PRE eligible race/horse universe for each date, sort score descending, then canonical PRE race_id string ascending, then integer horse number ascending. Scan once, take up to three per race, stop at frozen Current daily N. Missing full-field score or insufficient capacity is `NOT_EVALUABLE`; do not infer scores or change N. It is neither calibrated expected monetary value nor a calibrated Top3-probability sum. This candidate is diagnostic only: prediction lane NO, BUY lane NO, Production authority NONE, formal Evidence credit 0. A new Allocation Authority would require a separate approval and protocol.

## Safety

POST diagnostic code must refuse to run when official Result is absent; it cannot create or change PRE selections after seeing Result. No 2026-10-31/11-01 or historical diagnostic receives the new positive-gate evidence credit. Neither field-size effects nor any favorable subgroup can rescue the primary PL+Jockey decision.
