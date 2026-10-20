# KeibaAI Iteration 3 — Offset PL Raw History V1 Preregistration

`EXPERIMENT_ID = EXP-025`  
`EXPERIMENT_NAME = ITERATION3_OFFSET_PL_RAW_HISTORY_V1`  
`STATUS = FROZEN_BEFORE_TRAINING_AND_RESULT_EVALUATION`  
`EVIDENCE_ROLE = DEVELOPMENT_ONLY_NON_EVIDENTIAL`

## Purpose and boundary

This preregisters one development-only candidate: an Offset Plackett–Luce model with a fixed base PL utility and exactly seven Raw History coefficients. It authorizes neither implementation nor training. It changes no Production component, Current BUY authority, Current Top5 restriction, gate, volume rule, Formal Evidence role, EXP-024 component, or Prospective Evidence count.

Result access, target-race finish, odds, popularity, marks, hyperparameter search, feature search, threshold search, and any model execution before this freeze are prohibited.

## PIT and input authority

- Identity rule: `APPROVED_NAME_SIRE_MATERNAL_GRANDSIRE_V1`.
- PIT qualification: `ITERATION3_RAW_HISTORY_FINAL_PIT_QUALIFICATION`.
- Qualified population: 74 dates, 1,285 flat races, 17,344 horses; 2 previously approved race exclusions and 1 previously approved exact identity exception only.
- Required input authority: the SHA-bound WS2 deterministic regeneration record or formal input manifest, as established by the final PIT audit.
- Valid historical record: race date strictly before target date; numeric finish >= 1; field size >= 2; cancellation, exclusion, disqualification, and non-finish records excluded.
- V1 history window `W`: latest up to three valid historical records only.

## Model and offset

Objective: the Iteration 2 equal-race-weight top-3 partial Plackett–Luce likelihood. The base PL utility is fixed inside each V2 fit; only the seven listed Raw History coefficients are learned. No intercept, second-stage gate, BUY-volume modification, race-authority modification, or Current Top5 restriction is introduced.

### Rolling-OOS development offset

For evaluation month `m`, train the base PL using only 2026-02 through month `m-1`, using the verified `pl_fit` implementation. Before Offset PL V2 evaluation, its base predictions must exactly reproduce the corrected Iteration 2 `p_hgb` semantic field for the corresponding fold. Failure is `STOP_BASE_PL_REPRODUCTION_FAILURE`; V2 evaluation is prohibited. Frozen full-period PL Forward v1 must not be used as a March–September rolling offset.

### Final candidate offset

The only final-model offset is Frozen PL Forward v1 utility, model SHA256 `418fc9b4cefe1757f79dfc22a7d49b7c1592b91084cca97f88f55bb1389b0585`. Final V2 training data are restricted to 2026-02-01 through 2026-09-13. No later data may enter final training.

## Frozen feature set

Exactly these seven features are permitted. No later addition, deletion, redefinition, or alternate history window is allowed.

1. `RECENT_FINISH_PCT`: for each `i` in `W`, `(finish_i - 1) / (field_size_i - 1)`; mean over `W`; missing if `W` is empty.
2. `RECENT_MARGIN`: mean of `clip(finish_margin_seconds_i, 0.0, 3.0)` over records in `W` having a margin; missing if none.
3. `RECENT_CORNER4_PCT`: use the final available running-position number; `(corner_position_i - 1) / (field_size_i - 1)`; mean over usable records; missing if none.
4. `DISTANCE_GAP`: `min(abs(target_distance - d_i) / 1000)` over `W`; missing if `W` is empty.
5. `SURFACE_SWITCH`: most recent valid history surface equals target surface -> 0, differs -> 1; missing without valid history.
6. `LOG_REST`: use the most recent PRE-safe historical record regardless of valid-race status; `log(1 + min(target_date - prior_date, 365))`; missing with no prior record.
7. `HISTORY_DEPTH`: `number_of_valid_records_in_W / 3`; values 0, 1/3, 2/3, or 1; never missing.

Training-fold-only mean/std standardization applies only to features 1–4 and 6. Missing standardized values are 0, meaning the training-fold mean. `SURFACE_SWITCH` stays binary and `HISTORY_DEPTH` is unchanged. There are no missing indicators. The only clipping is margin at 3.0 seconds and rest at 365 days.

Excluded from V1: final3F, class and class-change features, carried-weight history, body-weight history, PCI, RPCI, going/track condition, jockey, target-day body weight, and cumulative/snapshot-state values.

## Fitting and evaluation freeze

`L2_REGULARIZATION = 0.0`. No fallback L2, hyperparameter search, or numerical repair is allowed. A numerical failure stops the candidate.

Rolling test months: March, April, May, June, July, August, and 2026-09-01 through 2026-09-13. For each month: refit base PL on prior months, reproduce `p_hgb`, calculate training-only scaling, fit seven coefficients on training data, predict the test month, and atomically freeze the fold output. No target-month labels may enter fitting or scaling.

Primary population: Current BUY races. Race authority is `CURRENT`; volume authority is the frozen Current BUY count `k`. Comparators are Current BUY, fold-specific base PL same-volume, and Offset PL V2 same-volume. The primary race quantity is `V2 top3 hit count - base PL top3 hit count`.

## Frozen gates

All gates must pass.

1. Date-cluster bootstrap of mean race-top3 delta: 10,000 iterations, two-sided 95% interval, lower bound > 0. `BOOTSTRAP_SEED = 20261020`; this is a new preregistration-time seed, not a result-selected seed and not a reused protocol seed.
2. V2 >= base PL in at least 5 of 7 evaluation months.
3. Common-valid-race Rank1 precision: V2 >= base PL - 1.00 percentage point.
4. Overall Brier V2 <= base PL and monthly Brier worse in no more than 2 months.
5. The existing Roadmap Candidate Gate versus `CURRENT_GLOBAL` continues to pass, using the existing Roadmap definition without redefinition.

Secondary diagnostics only: Top5 inside/outside, k=1/2/3, rank buckets, coefficients/signs, missing rates, global daily top-N detail, rank1 monthly results, and calibration monthly results. They cannot create a post-hoc rule.

## Consumed secondary and prospective boundaries

2026-09-19 through 2026-10-12 is `CONSUMED_FOR_DESIGN_SECONDARY`; only the final frozen candidate may be checked there. It is neither independent OOS, Prospective Evidence, nor Production Gate evidence. A failure records failure only: it cannot trigger an eighth feature, changed window, clipping, missing policy, L2, or gate.

Any later prospective program requires a separate EXP-ID, protocol, independent review, Human approval, frozen model, and post-freeze dates. EXP-024 remains unchanged. The research deadline is 2026-11-11 and does not relax any gate.

## Safety state

`MODEL_TRAINED = FALSE`  
`PERFORMANCE_EVALUATED = FALSE`  
`RESULT_ACCESS = 0`  
`EXP024_CHANGED = FALSE`  
`PRODUCTION_CHANGED = FALSE`
