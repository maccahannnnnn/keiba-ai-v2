# KeibaAI checkpoint record — 2026-10-13

STATUS = `CHECKPOINT_READY`

PRIMARY_NEXT_TARGET = `FULL_FIELD_RANKING_PROBABILITY_REDESIGN`

## DecisionEngine deterministic tie-break fix

ROOT_CAUSE = `TIE_BREAK_BY_OBJECT_ID`

CHANGE = `deterministic tie-break only`

THRESHOLD_CHANGED = `FALSE`

GATE_CHANGED = `FALSE`

SCORE_FORMULA_CHANGED = `FALSE`

PRODUCTION_MODEL_CHANGED = `FALSE`

PRODUCTION_BUY_RULE_CHANGED = `FALSE`

Tests:

- UNIT_TEST = `PASS`
- REGRESSION_TEST = `PASS`

PRE-only regeneration:

- RUN_C_D = `IDENTICAL`
- ROWS = `14870`
- DIFFERENCE_COUNT = `0`
- RESULT_ACCESS = `0`
- POST_ACCESS = `0`
- LEARNING_ACCESS = `0`
- NETWORK_ACCESS = `0`
- DECEMBER_2025_USAGE = `0`
- PIT_SEMANTIC_EQUIVALENCE = `NOT_PROVEN`

## Iter0 development results

- CURRENT_RANK_SAME_VOLUME = `252 / 713 = 35.34%`
- PP_WITH_CURRENT_TIEBREAK = `291 / 713 = 40.81%`
- V5_PROCEDURE_FULL_FIELD_TRAINED = `287 / 713 = 40.25%`

These same-volume values are a Current-BUY-race-conditioned secondary metric,
not the formal Execution Spec primary.  The intended primary is the daily
global top-N comparison.

Iteration status:

- ITERATION_1 = `PARTIALLY_EXECUTED_IN_ITER0`
- Full-field-trained V5 counts as part of Iteration 1.
- One of the three iteration-budget slots has been used.
- Completing missing comparisons does not consume an additional iteration.
- PP_ONLY_DETERMINISTIC is the primary simplicity baseline.
- A complex model candidate requires evidence exceeding PP.
- Current-derived feature-removal ablation is `DEFER`.

Treatment status:

- TREATMENT1_NEW_IMPLEMENTATION = `STOP`
- DAILY_V5 = `OBSERVE_ONLY`
- INDEPENDENT_V5 = `OBSERVE_ONLY`

## Local evidence references

The evidence directories remain local and are intentionally not staged by this
checkpoint:

- `reports/decision_engine_determinism_fix_v1/`
- `reports/decision_engine_determinism_fix_v1_production_regression_addendum_v1/`
- `reports/full_field_redesign_iter0_v1_retry8/`

Relevant SHA256 values:

| Artifact | SHA256 |
| --- | --- |
| Determinism artifact index | `60e54781123b80f4e19101cf504fd9d79c04e457d8cc5a906a7f7ad4d753773f` |
| Root-cause record | `53608d3134bba54f62f38d13f5f0c73d1579bb1c9932957ae626f5a0a1dfa464` |
| Run-C/Run-D comparison | `46cb4e7d4238277a83a6ce6ed4a9bb9fdc6423f87ee45ded8fd9e391979cf570` |
| Regression-addendum index | `295674c3a21f96a21f8bf11cbf62f59d001cdde33faada6171ccc7f7705a87fa` |
| Iter0 retry8 artifact index | `68e99539d026d7489a1e71ccbcfad200899a72921404de9d63a5d711907a284` |

This record does not replace the referenced evidence artifacts, change model
semantics, or authorize a new BUY rule.
