# Addendum synthetic validation

Command: `.venv_keibaai_ml_v4/Scripts/python.exe -m unittest tests.test_pl_jockey_decision_addendum_v1 -v`

Result: 16 tests run, 16 PASS, 0 FAIL. Synthetic inputs only; no Result artifact opened. Tests cover same-race/k/volume, invalid Rule A versus ordinary rate, both checkpoint boundaries, ACCEPT, REJECT, INCONCLUSIVE, top-two removal, second half, field-size expectation, deterministic smallest-field ordering, overlap partition, missing-Result POST refusal, and no odds/popularity dependency.

Existing PL+Jockey regression was also run with the new tests: 38 total, 2 failures and 2 errors in `tests.test_frozen_pl_v1_jockey_offset_provisional_v1`. The existing test fixtures assume an earlier `docs/KeibaAI_JOCKEY_FORMAL_PRE_SNAPSHOT_MANIFEST_V1.json` state, whereas that manifest was already modified before this task. Failures are `STOP_FORMAL_SNAPSHOT_DUPLICATE_OR_ORDER` and a missing-date expectation that no longer triggers. Neither the manifest nor the pre-existing test was changed here. Thus `ADDENDUM_SYNTHETIC_TESTS=PASS` but `COMBINED_RELEVANT_REGRESSION=FAIL`; this freeze is not represented as a clean full regression pass.

This is implementation-level validation of a new reporting/decision helper, not prospective performance evidence. Parent protocol runners and existing PRE/POST artifacts are unchanged.
