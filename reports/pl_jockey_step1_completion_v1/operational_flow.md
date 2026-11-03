# PL+Jockey Step 1 operational order

Authority: `APPROVE_PLJ_ADDENDUM_STEP1_COMPLETION_V1`. This is a future-date runbook, not a PRE or POST execution record.

1. Validate official PRE input; freeze Current PRE and its manifest/race index.
2. Freeze EXP-024 PRE.
3. Freeze PL+Jockey PRE under its unchanged parent protocol.
4. Freeze A_new and other required higher-priority PRE lanes.
5. Freeze E1 PRE.
6. Before the independently verified first race start and before Result access, run `review/pl_jockey_step1_operations_v1.py` PRE derivation using frozen Current, PL+Jockey, E1 outputs. Store source SHAs, derived membership SHA, time, N and eligible-race count. No Result file existence check or Result-based selection is allowed. If this step is missed and Result is accessed, record `NOT_EVALUABLE_PRE_NOT_FROZEN`; do not backfill a formal diagnostic.
7. Only after all PRE freezes, access Result and complete formal POST.
8. Generate EXP-024 POST first. Pass its **formal POST path** as the E1 POST crosscheck source. Do not use an earlier ad hoc POST or rewrite existing E1 POST artifacts.
9. Aggregate PL+Jockey versus Current using the frozen addendum and the Step 1 stateful checkpoint service. Each new eligible date is appended once. Parent SUSPEND/technical STOP takes precedence. The first 12-date/60-race and final 24-date/120-race checkpoint are each decided only at first arrival; a terminal decision cannot be revised by later dates.

`ELIGIBLE_RACE` is derived from the frozen Current race index plus PL+Jockey race rows: `current_k > 0`, same race, `candidate_k == current_k`, and both selected lists have length `k`. The PL+Jockey artifact's broad `eligible_race_count` is not Gate authority. For 2026-11-01, a PRE-only read produced 6 Gate-eligible Current BUY races from 13 processed races; this is a schema smoke check only, not new-gate evidence.

The PRE derivation runner uses `--mode freeze-pre` and requires three frozen PRE paths, the Current race index, and `--first-start-at` from independent first-start authority. It writes only a new output path; existing output is never overwritten. The operator must retain the independent first-start authority alongside the output. The code does not train, infer, read Result, use odds/popularity, or mutate Current/EXP-024/PL+Jockey/E1 PRE.

After verified formal POST, `--mode advance-state --verified-day <verified-post-summary.json> --previous-state <prior-state.json> --output <new-state.json>` persists a *new* state artifact, never overwriting the previous one. The supplied POST summary must assert verified Result join and carry the frozen per-race PRE identities and Current race-index counts. Its SHA and the preceding state SHA are recorded. This mode must not be run before Result access is authorized and was not run on actual POST data during Step 1 completion.
