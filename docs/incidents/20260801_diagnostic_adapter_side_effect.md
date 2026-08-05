# 2026-08-01 Diagnostic Adapter Side Effect

## Summary

During the TrackCondition metadata root cause audit, a diagnostic utility called
`TargetTrialAdapter.run()` to inspect representative race metadata. The adapter
is part of the production analysis path and can trigger Learning Candidate
repository persistence. As a result, `learning/improvement_candidates.json`
received an `updated_at` refresh during diagnosis.

## Scope

- Target diagnostic: `review/track_condition_metadata_root_cause_audit.py`
- Affected artifact: `learning/improvement_candidates.json`
- Observed change: timestamp/update metadata changed
- Unchanged: record count, aggregate count, Production scoring, BUY, Score, Decision

## Severity

LOW_TO_MEDIUM

This was not a scoring or decision incident, but it was an operation-quality
incident because a read-only diagnostic invoked a production adapter with
persistence side effects.

## Root Cause

The diagnostic used a production adapter for evidence extraction. In KeibaAI,
`TargetTrialAdapter.run()` is not read-only; it can call Learning Candidate
generation and repository save paths.

## Why No Restoration Was Performed

The affected JSON is an untracked operational artifact in this workspace, and
the confirmed content impact was limited to update metadata. Reconstructing a
previous timestamp or inferring legacy values would create a larger integrity
risk than documenting the incident.

## Prevention

- Diagnostic scripts must avoid production adapters unless explicitly approved.
- Static safety validation must flag production adapter imports and run calls.
- Read-only audits should use saved records, reports, or temporary fixture data.
- Protected production data hashes should be checked before and after diagnostics.

## Final Judgment

The incident is documented. No evaluator, decision, score, BUY, CSV, Knowledge,
or production logic change was made.

## 2026-08-01 Follow-up: Safety Validator v1.1

Claude Code review identified that Diagnostic Safety Validator v1.0 could detect
direct calls such as `TargetTrialAdapter().run(...)`, but could miss variable
mediated calls such as:

```python
adapter = TargetTrialAdapter()
adapter.run(...)
```

The confirmed production-risk pattern exists in `review/daily_review_20260801.py`:

- import: `TargetTrialAdapter` at line 16
- construct: `adapter = TargetTrialAdapter()` at line 130
- run: `adapter.run(...)` at line 131

Safety Validator v1.1 now tracks simple same-scope adapter assignments and
classifies this pattern as `TARGET_TRIAL_ADAPTER_RUN_VIA_VARIABLE` with `HIGH`
severity. Import, construct, and load-only usage remain informational and are
kept separate from run calls.

Confirmed facts:

- The v1.0 validator had a run-detection gap for variable-mediated calls.
- The v1.1 validator detects the daily review variable-mediated run pattern.
- Historical before-hash for runs before this incident was not available, so
  historical content differences are documented as `HISTORICAL_HASH_NOT_AVAILABLE`
  rather than inferred.
- Current validator executions persist protected hash before/after data in
  diagnostic safety validation JSON reports.
- Existing reports and historical JSON were not rewritten.

Unconfirmed items:

- Exact historical execution count from process logs is not independently
  recoverable from the current repository state.
- Exact historical content delta before the first diagnostic side effect cannot
  be proven without a trusted prior artifact hash.

Prevention update:

- Static validator tests now cover direct run, variable-mediated run, import
  alias run, construct-only, load-only, unrelated `run()`, and same variable
  names in different scopes.
- Diagnostic utilities should prefer saved review artifacts or a future explicit
  read-only replay wrapper over direct production adapter execution.
