# PL+Jockey decision addendum freeze

`HUMAN_APPROVAL = APPROVED_ROLE_REALLOCATION_DESIGN_V1`

Parent protocol and selection authority are unchanged. The positive gate and four derived diagnostics were SHA-pinned in `addendum_manifest.json` before any new-gate evidence date. The 2026-10-31 and 2026-11-01 observations remain pre-addendum and carry no credit. No Result was opened during this step; no prediction, training, BUY or Production action was executed.

The first possible gate decision requires both 12 eligible dates and 60 eligible races. The final decision requires both 24 eligible dates and 120 eligible races. The existing SUSPEND remains prior authority. The four derived diagnostics are not new lanes or BUY rules.

No new experiment ID was assigned: this is an addendum to the existing PL+Jockey workstream. Its additive Ledger entry is the registry record; the Fingerprint Index was not changed.

Validation caveat: all 16 new synthetic tests pass, but the combined parent-protocol regression is not clean (2 failures, 2 errors against an already-modified formal snapshot manifest). See `test_report.md`. This does not rewrite the freeze; it prevents a claim of complete regression clearance or Step 2 readiness.
