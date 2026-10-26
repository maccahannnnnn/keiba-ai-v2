# CURRENT_UNCONVERGED_RANK1_RESOLUTION_SHADOW_V1 — Prospective Protocol

Status: HUMAN_APPROVED_FROZEN_BEFORE_FIRST_ELIGIBLE_PRE  
Human approval: `docs/KeibaAI_CURRENT_UNCONVERGED_RANK1_PROSPECTIVE_SHADOW_V1_HUMAN_APPROVAL.json`  
Priority: SECONDARY_TO_EXP024  
Production authority: NO

## PRE-only selection

The input is the officially frozen, date-specific Current PRE artifact, including its input manifest, provenance, prediction manifest, and complete race predictions. Verify their SHA identities before selecting. Do not read a Result source during PRE.

An eligible race has the persisted Current `buy_v1_rc1_race_state` equal to `PLAY_UNCONVERGED_4PLUS`. Use only horses with persisted `buy_v1_rc1_candidate=true`. Select exactly one: the candidate with the smallest persisted Current `rank`. The original Current PRE runner ranks by `adjusted_score` descending, then horse number descending; the Shadow consumes its stored rank and does not invent a tie-break. If state, candidate status, rank, identity, or ordering cannot be verified uniquely, fail closed without selection.

`shadow_k=1` fixed. `selection_reason=CURRENT_SCORE_RANK1_FIXED_K1`. Threshold: NONE. No fallback, replacement horse, PL, Adaptive, Jockey, risk-guard count, or candidate recomputation. Current BUY and all other race states remain unchanged. The Shadow output is separate from Current and Production.

Record each eligible race's date, venue, race number and ID, race state, candidate count, selected horse number/name, stored rank, persisted adjusted score, protocol SHA, implementation SHA, input PRE SHA, UTC creation timestamp, and Result-access count 0. Write once to a new date-specific Shadow root and freeze the selection artifact SHA before any Result access. No historical replay or late-created selection receives prospective evidence credit.

## Result join and primary metrics

Use the frozen PRE selections only. Existing KeibaAI invalid-result semantics (finish 0, cancellation, exclusion, or other invalid result) exclude the horse from both hit and valid denominator; never replace it. Keep raw and valid counts separately.

`ADDED_BUY_TOP3_RATE = valid Top3 hits among eligible Shadow additions / valid eligible Shadow additions`.

`SAME_DATE_CURRENT_BUY_TOP3_RATE = valid Top3 hits among all original Current BUY selections on the same formally PRE-frozen calendar dates / valid original Current BUY selections on those dates`. Include a date if it contributes at least one eligible Shadow race. Do not substitute the historical overall Current rate. If either valid denominator is zero, mark the comparison NOT_EVALUABLE; do not impute a rate.

Primary condition: `ADDED_BUY_TOP3_RATE >= SAME_DATE_CURRENT_BUY_TOP3_RATE`.

For the identical evidence dates, compare the original Current BUY set with its union with eligible Shadow additions. `combined precision delta (percentage points) = 100 × (combined valid hits / combined valid N − original Current valid hits / original Current valid N)`. The `PRECISION_IMPROVEMENT_GATE` requires this raw point estimate to be strictly greater than 0.0 percentage points.

The safety/non-inferiority gate requires the 95% date-cluster bootstrap confidence interval's lower bound for combined precision delta to be at least −1.0 percentage points. Non-inferiority alone does not satisfy precision improvement.

## Frozen bootstrap

Repetitions: 10,000. Seed: 20261026. Cluster: calendar date. At each repetition, sample the observed evidence dates with replacement, with sample size equal to the number of evidence dates. Carry every original Current BUY and eligible Shadow selection on each sampled date together; aggregate hits and valid N across sampled date clusters, then recompute combined minus Current precision in percentage points. Report raw counts, raw delta, bootstrap mean delta, and 2.5th/97.5th percentiles (linear interpolation between adjacent ordered replicates). A replicate with a zero required denominator is invalid and must be counted and reported, not silently assigned zero. If a valid 95% interval cannot be obtained, mark the non-inferiority gate NOT_EVALUABLE.

## Preregistered checkpoints

Checkpoint 1 occurs only after **both** at least 12 independent prospective dates and at least 60 eligible `PLAY_UNCONVERGED_4PLUS` races. It is not automatic promotion. At Checkpoint 1, if the additions' rate is more than 5.0 percentage points below the same-date Current BUY rate, record `PROSPECTIVE_HARM_WARNING` and require Human review. No automatic retuning follows.

The final checkpoint occurs only after **both** at least 24 independent prospective dates and at least 120 eligible races. Do not conduct opportunistic gate decisions between these checkpoints. Evidence dates must have PRE selections formally frozen before Result access; repeated runs or revisions of a date do not count as new independent dates.

At both checkpoints report leave-one-date-out results, date and venue concentration, month stability, eligible race count, valid horse count, and historical Independent UNCONVERGED overlap (same horse / different horse / not comparable). These are descriptive diagnostics, not new selection conditions.

## Evidence and governance boundary

The 2026-03–09 `101/228` result is `DERIVATION_SET_REPRODUCTION`. December and January are separate reused consumed Development blocks. All have formal evidence credit 0. Prospective evidence begins only after a new date's Result-blind PRE freeze. The Shadow has no Production authority. EXP-024 has higher priority; its protocol, runner, Frozen PL, engine, evaluation, and knowledge must remain unchanged. Block001 remains pending until its actual first eligible formal PRE environment is established.
