# PL+Jockey Step 1 completion tests

Command: `.venv_keibaai_ml_v4/Scripts/python.exe -m unittest tests.test_frozen_pl_v1_jockey_offset_provisional_v1 tests.test_pl_jockey_decision_addendum_v1 tests.test_pl_jockey_step1_operations_v1 -q`

Result: **55 / 55 PASS**; 0 failures, 0 errors, 0 skips. Legacy 22/22, original addendum synthetic 16/16, Step 1 operations synthetic 17/17.

The append-only formal snapshot manifest itself was not changed. The legacy tests now construct their original fixed genesis subset and explicit 2026-10-31 append row. The duplicate-date test asserts `STOP_FORMAL_SNAPSHOT_DUPLICATE_OR_ORDER`; the ordering test swaps two *post-genesis* rows and asserts that same intended STOP, rather than passing from `STOP_FORMAL_SNAPSHOT_GENESIS_CHANGED`. Missing expected date and SHA mismatch tests retain their strict STOP assertions.

Step 1 tests cover positive-k eligible races, frozen Current race/k comparison, count derivation rather than a broad artifact counter, both one-time checkpoint boundaries, irreversible `INCONCLUSIVE_CLOSE`, pre-addendum/reference exclusion including compact dates, verified POST guard, parent suspension priority, same-scorer deterministic ordering and scorer authority, late PRE refusal, and no Result/odds/popularity path in the PRE runner.

PRE-only schema smoke: the existing 2026-11-01 frozen PL+Jockey, E1 and Current race-index artifacts were read without Result; 13 processed races yielded 6 positive-`k` Gate-eligible races and daily N=14. No diagnostic artifact was backfilled for this past date.
