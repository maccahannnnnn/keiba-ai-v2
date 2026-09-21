# KeibaAI 実験・分析履歴台帳

`STATUS = AUTHORITATIVE`  
`AUTHORITATIVE = YES`  
`HUMAN_APPROVED = YES`  
`CLAUDE_FINAL_REVIEW = ACCEPT_WITH_MINOR`  
`CHATGPT_INTEGRATED_REVIEW = ACCEPT_WITH_MINOR`  
`AUTHORITATIVE_FINALIZATION_DATE = 2026-09-02`  
`PURPOSE = PREVENT_DUPLICATE_OR_RENAMED_REEXECUTION_OF_PREVIOUS_KEIBAAI_ANALYSES_AND_EXPERIMENTS`

## Authoritative Metadata

- File: `KeibaAI_EXPERIMENT_ANALYSIS_LEDGER.md`
- Source draft: `KeibaAI_EXPERIMENT_ANALYSIS_LEDGER_DRAFT_V3.md`
- Source index: `KeibaAI_EXPERIMENT_FINGERPRINT_INDEX_DRAFT_V3.json`
- Logical entries: 43
- Unresolved NEEDS_REVIEW: 5
- Unresolved conflicts: 1
- Finalization scope: DRAFT V3を正本化し、Claude最終レビューのMINOR-1〜4のみを反映した。DRAFT V1/V2/V3は履歴として保持する。2026-09-04にANA-020を加算し、REG009-STATE-001の未解決scopeを正確なstate label provenanceへ狭小化した。2026-09-11にHuman承認済みDevelopment Experiment EXP-020を事前登録した。

## Mandatory Duplicate Precheck

新しいDevelopment Experiment / Analysisの前に、必ず次の順で [正式Index](KeibaAI_EXPERIMENT_FINGERPRINT_INDEX.json) を確認する。

1. Mechanism Family
2. Alias / Potential Alias Terms
3. Experiment Fingerprint
4. DO NOT REPEAT
5. REOPEN CONDITION
6. Provenance

既存entryと実質同一なら `DUPLICATE_OR_RENAMED_REPEAT` として原則STOPする。実質的に新しいmechanismがある場合のみ、Claude → ChatGPT → Humanの設計レビューへ進める。

## Finalization Corrections

| Minor | 正式化修正 |
|---|---|
| MINOR-1 | EXP-007 provenanceに `reports/ml_v4_buy_selection_dataset_v2/` を追加 |
| MINOR-2 | GATE-002 provenanceに `reports/march_2026_historical_external_holdout_v1/` を追加 |
| MINOR-3 | EXP-008 provenanceに `reports/ml_v4_buy_selection_dataset_v4/` を復元 |
| MINOR-4 | GATE-005 minimum evidenceの一次sourceを `reports/v4_model_v3_prospective_protocol_v1/protocol.json` と確定。`independent_eligible_races=60` かつ `independent_eligible_dates=12` |

## Authoritative Summary

- Raw mechanism families: 18
- Normalized mechanism families: 17
- Development disposition: NOT_SUPPORTED 5 / INCONCLUSIVE 3 / CLOSED 10 / OBSERVATION_ONLY 16 / NOT_APPLICABLE 9
- Evidence gate: PASS 3 / ACCEPT 5 / CONSUMED 1 / HOLD 5 / REJECT 3 / PENDING 5 / NOT_APPLICABLE 21
- Operational: ACTIVE 2 / PAUSE 1 / READY 1 / HOLD 1 / CLOSED 21 / COMPLETE 17

## Preservation of Open Issues

以下は正本化により解決済みと扱わない。

- NEEDS_REVIEW: EXP-017, ANA-003, ANA-004, ANA-007, ANA-012
- Conflict: `REG009-STATE-001`
  - `EXACT_STATE_LABEL = RETROSPECTIVE_NOT_FORMALLY_REPRODUCIBLE`
  - `EXACT_STATE_LABEL_PROVENANCE = NOT_RECOVERED`
  - `UNDERLYING_JUSTIFICATION = INDEPENDENTLY_REPRODUCED_FROM_REPOSITORY`
  - `SEMANTIC_DECISION_PROVENANCE = SUBSTANTIALLY_RECOVERED`
  - `REPOSITORY_DELETION_CONFIRMED = NO`
  - `REG009_PROSPECTIVE_OOS = HOLD` / `PRODUCTION = HOLD`
  - 未解決範囲は exact state label のoriginal author・original authoritative source・exact first occurrenceのみである。

## Closure Scope Guardrails

- Frozen HGB configuration が NOT_SUPPORTED であって、全非線形モデルが不支持という意味ではない。
- Frozen symmetric Pairwise Logistic recipe が NOT_SUPPORTED であって、全Ranking Objectiveが不支持という意味ではない。
- February Additiveは 194/498→196/498（+2、+0.40pt）だが、May除外LOFOで -1 / -0.32pt のため INCONCLUSIVE のまま維持する。
- CF_TOP3_RANK_ANCHOREDとV4 Model v3 Formal Prospective Shadowは、Productionから隔離されたFormal Prospective evidence collectionである。

## Complete Authoritative Entry Set

正式な各entryの全field（stable ID、canonical name、aliases、raw/normalized mechanism family、evidence role、三軸status、fingerprint、DO NOT REPEAT、reopen condition、provenance）は companion JSON に固定する。

`ANA-001, ANA-002, ANA-003, ANA-004, ANA-005, ANA-006, ANA-007, ANA-012, ANA-013, ANA-014, ANA-015, ANA-016, ANA-017, ANA-018, ANA-019`  
`ANA-020`  
`EXP-001, EXP-002, EXP-003, EXP-004, EXP-005, EXP-006, EXP-007, EXP-008, EXP-009, EXP-010, EXP-011, EXP-012, EXP-013, EXP-014, EXP-015, EXP-016, EXP-017, EXP-018, EXP-019, EXP-020, EXP-021, EXP-022`  
`GATE-001, GATE-002, GATE-003, GATE-004, GATE-005`

`TOTAL_LOGICAL_ENTRIES = 43`

## Authoritative Additive Entry — 2026-09-04

| Field | ANA-020 |
|---|---|
| Canonical name | Candidate Generation Observability Feasibility |
| Aliases | Full-field candidate universe observability; Candidate Generation Phase A |
| Mechanism family | CANDIDATE_GENERATION (normalized: CANDIDATE_GENERATION) |
| Evidence role | NON_EVIDENTIAL_DEVELOPMENT_FEASIBILITY |
| Development disposition / Evidence gate / Operational state | OBSERVATION_ONLY / NOT_APPLICABLE / COMPLETE |
| Primary result | FULL_FIELD_OBSERVABILITY_CONFIRMED |
| L1 | PASS — MEDIUM deterministic, result-independent DG/DE/DS → Adapter → evaluator-input code path; evaluator snapshots are not used as L1 evidence. |
| L2 | PASS — STRONG; all 20 frozen semantic fields present for full-field rows in Prospective, February, March, and May representative artifacts; missing 0. |
| Scope | Technical full-field observability only. Candidate performance, Candidate Model validity, Phase B, training, Production, and historical-corpus completeness are not established. |
| DO NOT REPEAT | YES — same generator/schema/data-lineage observability question must not be renamed and rerun. |
| Reopen condition | Material change to Prediction generator, Adapter population semantics, persistence schema, evaluator-input lineage, or full-field export semantics. |
| Provenance | `reports/candidate_generation_observability_feasibility_v1/`; `reports/candidate_generation_observability_feasibility_v1_retry1/`; retry hash indexes `bbe643…`, `2bca2a…`, `b69e29…`. Initial STOP is retained as history. |

## Authoritative Version History

- Previous authoritative version (before this update): MD SHA256 `4a9c6836d836caa648b4f67e6b6e82fbdf1c7e8bba08a4bc15fe218ec26f3c87`; JSON SHA256 `c5fd4c9f31afbf6661064914b79c41736616db21c9b1eaf7500cef5f25254cd3`.
- This update adds ANA-020 and narrows—without deleting—REG009-STATE-001's conflict scope. New current hashes are recorded in the companion JSON and update audit.

## Authoritative GATE-001 Finalization Override — 2026-09-07

GATE-001のimmutable base `evidence_gate_status = PENDING` は履歴fieldとして保持する。実効のHistorical finalizationは正本Fingerprintの `finalization_overrides.GATE-001.historical_finalization` を参照する。April Historical evaluationは完了し、classificationは `INCONCLUSIVE` のまま変更しない。Candidate Generation Development reuseはHuman-approvedだが、future Candidate independent OOS／untouched holdout／first-look OOSには使用しない。Technical Full-field readinessは `PENDING`。Historical independent-review provenanceは `UNCLEAR`。

## Authoritative Additive Entry — 2026-09-11

| Field | EXP-020 |
|---|---|
| Canonical name | Raw History Representation Candidate Generation V1 |
| Mechanism family | CANDIDATE_GENERATION |
| Evidence role | NON_EVIDENTIAL_DEVELOPMENT_EXPERIMENT |
| Major axis | Existing 20 semantic features + frozen HISTORY_DEPTH_V1=10 raw-history representation |
| Baseline / Treatment | Current Top5 training rows / Full-field training rows |
| Output / downstream | EXACT5 / Frozen Stage B + Frozen Selection Policy v2 |
| Fold authority | `ace55d0d48e24d066cee92e5a11aebbcf908f5256622303d5dd03bc1e5de099e` |
| Boundary | Development only; untouched holdout and Formal Prospective are prohibited. |
| Result / Operational state | STOP_MODEL_CONVERGENCE_FAILURE / CLOSED |
| DO NOT REPEAT | YES_WITH_UNCHANGED_FROZEN_RECIPE |
| Provenance | `reports/raw_history_representation_candidate_generation_v1/` |

## Authoritative Additive Entry — 2026-09-11 — EXP-021

| Field | EXP-021 |
|---|---|
| Canonical name | Raw History Representation Candidate Generation V2 |
| Parent | EXP-020（CLOSEDのまま不変） |
| Evidence role | NON_EVIDENTIAL_DEVELOPMENT_ONLY |
| Single changed parameter | Rich TEST arm max_iter 100 → 1000 |
| Fixed | Same representation / HISTORY_DEPTH=10 / folds / Exact5 / Stage B / 45d・828r |
| Operational state | READY（PRE-EXECUTION） |
| Boundary | Untouched holdout・Formal Prospective・Productionは禁止 |
| Provenance | `reports/raw_history_representation_candidate_generation_v2/` |

### EXP-021 Result Finalization

- Result: `COMPLETE`
- Operational state: `COMPLETE`
- EXP-020 remains CLOSED / STOP_MODEL_CONVERGENCE_FAILURE.


### EXP-021 Post-Review Record Completion

- `EXP021_RESULT_INTEGRITY = ACCEPT`
- `EXP021_PRIMARY_RESULT = RATE_POSITIVE_HIT_TRADEOFF`
- `RICH_HISTORY_CANDIDATE_INFORMATION_SIGNAL = POSITIVE`
- `RICH_HISTORY_INFORMATION_DIRECTION = SUPPORTED_AT_CANDIDATE_LEVEL`
- `EXP021_END_TO_END_ADOPTION_STATUS = HOLD_RATE_HIT_TRADEOFF`
- `PRIMARY_BOTTLENECK = SELECTION_TO_BUY_INTERFACE_MISMATCH`


## Authoritative Additive Entry — 2026-09-12 — EXP-022

| Field | EXP-022 |
|---|---|
| Canonical name | RICH_CANDIDATE_PROBABILITY_BUY_AUTHORITY_MATCHED_VOLUME_V1 |
| Parent | EXP-021 |
| Role | Selection → BUY interface experiment |
| Candidate / ranking | EXP-021 frozen Rich Exact5 / frozen Rich probability |
| Volume | Same-lane CONTROL natural Stage B BUY count |
| Safety eligibility | frozen risk_guard_pass veto only |
| Evidence role | NON_EVIDENTIAL_DEVELOPMENT_ONLY |
| Fingerprint ID | `ca38b6989b3a81312bea128b44ccfdb46fe4e25a80c3e06c49e56db4935dd673` |
| Operational state | READY（PRE-RESULT） |


### EXP-022 Result Finalization

- Result: `RATE_POSITIVE_HIT_NONPOSITIVE`
- Operational state: `COMPLETE`
- Evidence role: `NON_EVIDENTIAL_DEVELOPMENT_ONLY`

## Authoritative Recent Development Consolidation — 2026-09-13

この節は既存43論理Entryの削除・上書き・再採番を行わない補足正本レコードである。新しいExperimentの開始、既存Evidence roleの変更、Model・Production・BUY Logicの変更を伴わない。

### A. V4 Learning Lifecycle Repair

- `V4_LEARNING_LIFECYCLE_REPAIR = COMPLETE`
- Acquired/consumed source scope: `2026-02-01`～`2026-09-13`、62日、2,094 races、14,890 source horses。
- Former Daily reference: `V4 Model v3`。
- V4 Model v3 training: 36日 / 1,248 races。
- V4 Model v4 training: 45日 / 1,548 races。
- Repaired gap: 17日 / 546 races。取得・消費済みだが旧状態ではV4 Trainingへ未還流だった。
- V4 Model v5 training: 62日 / 2,094 races、trainable rows 5,530、training cutoff `2026-09-13`。
- V5 Model SHA256: `d3b17e3022768690d0b1013ab131b35c5a64aa8e4a816fb3e1349bad95fb87a2`。
- V5 Dataset SHA256: `15c77e5c13ccbff2255912fa5440e68baf43e0df753218d84420d4bf29da3b3a`。
- Independent deterministic reproduction: `PASS`。
- Daily Reference activation effective date: `2026-09-19`。
- Role boundary: V5はCurrent AIと並走する `REFERENCE / SHADOW ML SYSTEM` であり、Current BUYへ直接合流していない。`V5 Production BUY Model` と表記してはならない。
- Provenance: `reports/ml_v4_buy_selection_dataset_v5/`、`reports/ml_v4_buy_selection_model_v5/`、`reports/v4_learning_lifecycle/learning_cycle_policy.json`。

### V4 Learning Cycle Policy

- Cadence: `WEEKLY_MEETING_CYCLE`。
- 同一開催週内はFrozen Versionを固定する。
- 開催週終了かつPRE→POST完了後、正常Consumed dataを次Version Trainingへ追加する。
- 新Version activationはHuman承認必須。
- `AUTO_LEARNING = NO`。
- `HUMAN_APPROVED_PERIODIC_RETRAINING = YES`。
- 旧Versionは保存し、Comparatorとして利用可能とする。

### B. Selection Authority / EXP-022 Integrated Status

- Experiment: `RICH_CANDIDATE_PROBABILITY_BUY_AUTHORITY_MATCHED_VOLUME_V1`。
- `EXP022_PRIMARY_ADOPTION_STATUS = HOLD_NOT_ADOPTED`。
- `PRIMARY_BASELINE_RESULT = RATE_POSITIVE_HIT_NONPOSITIVE`。
- `INTERFACE_AUTHORITY_SIGNAL = POSITIVE_HIGH_CONFIDENCE`。
- `RICH_INFORMATION_INCREMENTAL_SIGNAL = MIXED_LOW_CONFIDENCE_CONFOUNDED_BY_SAFETY_SHORTFALL`。
- `TREATMENT_SIGNAL_STATUS = STRONG_BUT_SECONDARY_NOT_ADOPTABLE`。
- `SELECTION_TO_BUY_INTERFACE_DIRECTION_STATUS = PARTIALLY_SUPPORTED`。
- Candidate probabilityをSelection Authorityとして使う方向にはDevelopment上のPositive Signalがある。ただしBUY Volume Authorityはlegacy k依存のままである。
- EXP-022の既存Entryと結果履歴は変更せず、この節を統合状態の補足記録とする。

### C. Volume Authority Lineage Closure

- `VOLUME_AUTHORITY_LINEAGE_FINAL_STATUS = CLOSED_WITH_HOLD`。
- Diagnostic: `VOLUME_AUTHORITY_STRUCTURAL_SHAPE_PREFLIGHT_V1`。Outcome blindで実行され、`RESULT_ACCESS = 0`、`ACTUAL_TOP3_ACCESS = 0`。
- Baseline: legacy BUY 679 → risk-safe capped hypothetical BUY 1,456、`+777 / +114.433%`。
- Treatment: legacy BUY 720 → risk-safe capped hypothetical BUY 1,550、`+830 / +115.278%`。
- proposed < legacy: Baseline 0 races / Treatment 0 races。
- legacy k=0 → proposed k>0: Baseline 164 / 327、Treatment 181 / 309。
- `PLAY_UNCONVERGED_4PLUS`: Baseline 10 / 11 races、Treatment 9 / 9 racesでBUY-positiveへ反転。
- `VOLUME_EXPANSION_RISK = CONFIRMED`。
- `ABSTENTION_SEMANTIC_CONTRADICTION = CONFIRMED`。
- `SAFETY_ELIGIBILITY_AS_VOLUME_AUTHORITY = NOT_JUSTIFIED`。
- `RISK_SAFE_COUNT_BEST_SEMANTIC_ROLE = MAX_SAFE_VOLUME_CAP`。
- `INDEPENDENT_VOLUME_AUTHORITY_STATUS = HOLD`。
- `LEGACY_K_ROLE = TEMPORARY_BRIDGE`。
- `NEW_VOLUME_EXPERIMENT_AUTHORIZED = NO`。
- Provenance: `reports/volume_authority_structural_shape_preflight_v1/`。

#### DO NOT REPEAT — Volume Authority

- risk_guard pass頭数を、そのままBUY desired count / Volume Authorityとして再提案しない。
- Safety Eligibility系のhorse-level pass countを、独立したrace-level BUY Volume信号と同一視しない。
- `PLAY_UNCONVERGED_4PLUS`をrisk-safe countだけでBUY-positiveへ反転させるRuleを再提案しない。
- Volume Authority familyは、新しい独立race-level signalが見つからない限り再開しない。

### D. Recent Prior Meeting Track Context — Initial STOP Safety Record

- Initial Source Audit: `STOPPED`。
- Stop reason: schema provenance検索でrepository横断rgの対象が広すぎ、既存Result Review成果物の`actual_finish` / `actual_top3`がterminalへ表示された。
- `OUTCOME_ACCESS = NONZERO`、`PERFORMANCE_JOIN = 0`、formal artifacts = 0。
- このSTOPはperformance evidenceではなくSafety lessonとして保持する。

#### DO NOT REPEAT — Outcome-Blind Source Audit

- Outcome-blind auditでrepository-wide rg / grepを使用しない。
- Result Sourceを使用する場合は必要metadata列だけをsafe projectionする。
- Outcome fieldをterminal表示・DataFrame保持・中間artifact保存しない。

### E. Recent Prior Meeting Track Context — Clean Retry

- `RECENT_PRIOR_MEETING_TRACK_CONTEXT_SOURCE_AUDIT_V1_RETRY1 = COMPLETE`。
- `SOURCE_PROVENANCE = PASS`、`SAFE_PROJECTION = PASS`、`REPOSITORY_WIDE_SEARCH = 0`。
- `VENUE_MAPPING = PASS`、`SURFACE_MAPPING = PASS`、`TEMPORAL_BOUNDARY = PASS`、`CONTEXT_REPLAY_FEASIBILITY = PASS`。
- Target population: 62 dates、1,112 flat races、349 date×venue×surface groups。
- Official condition values: 良 1,456、稍重 423、重 138、不良 53、blank 0、malformed 0。
- Context age（date×venue×surface）: age 1 = 168、age 3 = 4、age 4 = 4、age 6 = 133、age >7 = 20、NO_PRIOR = 20。
- Within 1 day: 168 / 349 = 48.14%。Within 7 days: 309 / 349 = 88.54%。NOT_AVAILABLE: 40 / 349。
- Race-level: within 1 day 555 / 1,112、within 7 days 991 / 1,112、NOT_AVAILABLE 121 / 1,112。
- Intraday condition-change groups: 52。
- `TARGET_DAY_RESULT_ACCESS = 0`、`OUTCOME_ACCESS = 0`、`ACTUAL_TOP3_ACCESS = 0`、`PERFORMANCE_JOIN = 0`。
- `CURRENT_TRACK_CONDITION_SEMANTIC_REPAIR_REQUIRED = YES`。
- `READY_FOR_SEMANTIC_REPAIR_DESIGN = YES`。
- Evidence role: `RECENT_PRIOR_MEETING_TRACK_CONTEXT = VALID_DEVELOPMENT_CANDIDATE_NOT_YET_PERFORMANCE_TESTED`。
- Provenance: `reports/recent_prior_meeting_track_context_source_audit_v1_retry1/`。
- 未証明: BUY_TOP3_RATE改善、ML performance改善、Current AI performance改善、Selection改善。`SUPPORTED_IMPROVEMENT`と誤記してはならない。

### F. Track Condition Semantic Separation

- `TRACK_CONDITION_SEMANTIC_SEPARATION = REPAIR_REQUIRED`。
- Current target-day official conditionとhorse historical track-condition suitabilityが、target race condition欠損時にhorse past racesのdominant valueを用いるfallback経路によって混同される可能性がある。
- `TRACK_CONDITION_SEMANTIC_REPAIR_STATUS = REQUIRED_NOT_IMPLEMENTED`。今回、実装・Evaluator変更・fallback変更は行わない。

### G. Next Strategic Review Theme

- `PRIMARY_STRATEGIC_QUESTION = FULL_FIELD_INDEPENDENT_ML_VS_CURRENT_AI_IMPROVEMENT`。
- A — `FULL_FIELD_INDEPENDENT_ML`: Current Top5やCurrent評価への依存を可能な限り外し、全出走馬をML自身が直接評価する。
- B — `CURRENT_AI_IMPROVEMENT`: 能力・距離・コース・脚質・展開・Candidate Generation等、Current Evaluator自体の精度を改善する。
- C — `HYBRID_CURRENT_ML`: Current Explainable AIとFull-field Independent MLを独立評価し、最終Selection / BUYで統合する。
- 次回はBUY_TOP3_RATE 50%への最短経路として、runtimeで実際に使われる入力・Evaluator、dead/unfed Evaluatorの有無、Current Top5非依存MLの実行可能性、full-field raw/history features、Current由来Featureと独立Featureの分離、Independent ML training population、Candidate Generation failureの救済可能性、A/Bのコスト・期待効果、Hybrid実現可能性をレビューする。
- この記録はStrategic Reviewの論点固定のみであり、実装・学習・Experiment開始を許可しない。

## Consolidation Safety State

- `RECENT_DEVELOPMENT_LEDGER_CONSOLIDATION = COMPLETE`
- `TRACK_CONTEXT_PERFORMANCE_STATUS = NOT_TESTED`
- `MODEL_CHANGE = 0`
- `PRODUCTION_CHANGE = 0`
- `BUY_LOGIC_CHANGE = 0`
- `GIT_COMMIT = 0`
- `GIT_PUSH = 0`
- `NEXT = CHATGPT_HUMAN_LEDGER_REVIEW_THEN_STRATEGIC_REVIEW`

## Authoritative Additive Entry — 2026-09-15 — EXP-023

### Selection Authority Protocol V1 Formal Freeze

| Field | Value |
|---|---|
| Status | `FROZEN_PRE_IMPLEMENTATION` |
| Strategic role | `CURRENT_AI_IMPROVEMENT_PRIMARY` |
| Evidence role | `EXP022_DERIVED_NEW_PROSPECTIVE_HYPOTHESIS` |
| Model | `V4 Model v5` |
| Model SHA | `d3b17e3022768690d0b1013ab131b35c5a64aa8e4a816fb3e1349bad95fb87a2` |
| Protocol path | `docs/selection_authority_protocol_v1.json` |
| Protocol SHA | `01bad1cc325f0ec1e35cb149bc65e20c07582c6d4013f0e344c0d521bb21106f` |
| Fingerprint ID | `df82984c3a8304a7b7e1e93e462ac165332bb6f0985c371f7f2c97b0af37d39a` |
| Fingerprint stable ID | `EXP-023` |
| Parent | `EXP-022` — `DIRECTIONAL_ONLY_NOT_FORMAL_CONTINUATION` |
| Formal evidence | `NOT_STARTED` |
| Target k | `CURRENT_PRE_FROZEN_BUY_COUNT` |
| Target k role | `MATCHED_VOLUME_COMPARATOR_CONSTRAINT` |
| New Volume Authority | `NO` |
| Race eligibility | `CURRENT_PRE_BUY_COUNT>=1 AND FULL_FIELD_V5_INPUT_VALID` |
| Candidate | `FULL_FIELD_V5_PROBABILITY_TOP5_EXACT5` |
| Risk guard | `ELIGIBILITY_VETO_AFTER_EXACT5_BEFORE_K` |
| Outside fill | `PROHIBITED` |
| Shortfall | `DISCLOSE_ALL / NO_EXCLUSION / NO_FILL / ANY_SHORTFALL=>HOLD_VOLUME_CONFOUNDED` |
| Primary metric | `POOLED_BUY_TOP3_RATE` |
| Minimum evidence | `races>=60 AND dates>=12` |
| Retroactive formalization | `PROHIBITED` |
| Next | `CLAUDE_INDEPENDENT_PRE_IMPLEMENTATION_FREEZE_REVIEW` |

#### DO NOT REPEAT

- Daily V4 shadowをEXP-022のformal continuationとして扱わない。
- `payload.top5`をProtocol V1 candidate poolとして使わない。
- risk_guard eligibility vetoを除去しない。
- target_kを新規learned volume ruleへ置換しない。
- Exact5外を補充せず、shortfall raceを除外せず、PRE freeze前raceを遡及編入しない。
- EXP-022のDevelopment結果をProtocol V1のFormal Evidenceとして再解釈しない。

## Authoritative Additive Record — 2026-09-15 — January 2026 Selection Authority Historical Holdout

| Field | Value |
|---|---|
| Status | `PRE_ACQUISITION_FROZEN` |
| Parent | `EXP-023` / `SELECTION_AUTHORITY_PROTOCOL_V1` |
| Parent Protocol SHA | `01bad1cc325f0ec1e35cb149bc65e20c07582c6d4013f0e344c0d521bb21106f` |
| Evidence role | `TEMPORALLY_REVERSED_EXTERNAL_HOLDOUT_FOR_SELECTION_AUTHORITY_PROTOCOL_V1` |
| Purpose | `BACKWARD_TEMPORAL_GENERALIZATION_ONLY` |
| Prospective lane | `NOT_PROSPECTIVE_EVIDENCE = TRUE`; Formal Prospectiveとの合算は禁止 |
| Repository untouched | `VERIFIED` — January raw sourceの再探索は今回行わない |
| Human attestation | `ACCEPTED` — Human申告はRepository auditとは独立に保存 |
| Population | 2026年1月に実際に開催された全JRA日・全raceから新馬・障害のみ除外、未勝利は含む |
| One-shot | `FULL_JANUARY_ONE_SHOT = YES`。結果開封後の再定義・再評価は禁止 |
| Model | `V4 Model v5`、SHA `d3b17e3022768690d0b1013ab131b35c5a64aa8e4a816fb3e1349bad95fb87a2`、cutoff `2026-09-13` |
| Historical Current reconstruction | `ACCEPT`、`DS_FUTURE_OR_SAME_DAY_FAIL_CLOSED = REQUIRED` |
| target_k / Candidate | `HISTORICAL_CURRENT_PRE_FROZEN_BUY_COUNT` / `FULL_FIELD_V5_PROBABILITY_TOP5_EXACT5` |
| Safety / volume | Exact5後のfrozen `risk_guard_pass` veto、Exact5外fill禁止、新Volume Authorityなし |
| Result boundary | 両Historical PRE Freeze、Claude・ChatGPT review、Human PRE Approvalの後までResult access禁止 |
| Production limitation | `PROHIBITED_FROM_JANUARY_ALONE`。最終Production GateはFormal Prospectiveのまま |
| Realized population | `PENDING_SOURCE_ACQUISITION` |
| Data / Result access | `JANUARY_DATA_ACQUISITION = 0`、`RESULT_ACCESS = 0` |
| Dedicated fingerprint | `NO`。EXP-023をreopenせず、Fingerprint Index変更なし |
| Provenance | `docs/selection_authority_protocol_v1_january_2026_historical_holdout.json`; `reports/selection_authority_protocol_v1_january_2026_historical_holdout/` |
| Next | `CLAUDE_INDEPENDENT_JANUARY_PRE_ACQUISITION_FREEZE_REVIEW` |

`LEDGER_SUMMARY_COUNTER_UPDATE = DEFERRED_UNRESOLVED`。既存summary counterがこの種のadditive governance recordを論理Entry数・状態別集計へ算入する明示的な仕様はRepositoryから確認できないため、推測でcounterを変更しない。

## Authoritative Additive Amendment — 2026-09-16 — January 2026 Population Scope Correction

| Field | Value |
|---|---|
| Status | `PRE_OUTCOME_POPULATION_CORRECTION_COMPLETE` |
| Corrected artifact | `docs/selection_authority_protocol_v1_january_2026_historical_holdout.json` |
| Previous protocol SHA | `e5a3252263f4cdcb5e4da4c58a4f5dbc688fb11ffabf6d57d3627a44e1ac5f16` |
| Corrected population scope | `PREDICTION_BUY_1WIN_PLUS_FLAT` |
| Previous wording | 新馬・障害のみ除外、未勝利を含む |
| Corrected wording | JRA平地の1勝クラス以上。新馬・未勝利・障害を除外 |
| Authority | `docs/historical_development_cohort_20260627_20260628_population_scope_clarification_v1.md`、`docs/keibaai_development_rules_v0_4.md`、Current runner population semantics |
| Evidence boundary | `RESULT_ACCESS = 0`、`OUTCOME_ACCESS = 0`、`ACTUAL_TOP3_ACCESS = 0`、`PERFORMANCE_EVALUATION = 0` |
| Validity | `JANUARY_HOLDOUT_VALIDITY = PRESERVED`。訂正根拠はJanuary outcomeではなく、source取得以前から存在する正式Current AI scopeのみ。 |
| Raw data | 再取得なし。既存30 sourceのSHA再照合後にのみ既存manifestを再利用する。 |
| Existing January entry | 既存entryは変更しない。この追記はadditive amendmentである。 |

## Authoritative Additive Record — 2026-09-17 — V4 Model v6 Dataset Expansion and December 2025 Pre-Acquisition Freeze

| Field | Value |
|---|---|
| Status | `FROZEN_DEVELOPMENT_CANDIDATE_ONLY` |
| Model | `V4 Model v6` |
| Change class | `DATASET_EXPANSION_ONLY` |
| Parent | `V4 Model v5` — SHA `d3b17e3022768690d0b1013ab131b35c5a64aa8e4a816fb3e1349bad95fb87a2` |
| Parent rows | `5530`、`PARENT_ROW_SEMANTIC_DELTA = 0` |
| January role | `TRAINING_ALLOWED_EVALUATION_PROHIBITED`。旧V5 Historical Evidenceはimmutableのまま保持 |
| January addition | `741` trainable rows、positive `234`、negative `507`、invalid `4` excluded |
| V6 population | `6271` rows / `72` dates / `2243` races / `16935` horse appearances |
| Dataset | `ML_V4_TRAIN_DATASET_V6` — SHA `b92b0c448dcd074b17105cf1860818d621a12447c095814e630b48ab5fff75ef` |
| Model / scaler | model SHA `68af6d39647e46a9f7104f648c32b1db8dca46fed979bbfd4d25bf9ca4c1a152`; scaler SHA `3629e0030a3fb57defe96ca36fb2d0bc5831a66584549cce1e5413ae4efedd0b` |
| Recipe | `EXACT_V5_RECIPE`; parent reproduction `PASS`; double-fit determinism `PASS` |
| December holdout | Source acquisition前に `TEMPORALLY_REVERSED_EXTERNAL_HOLDOUT_FOR_V4_MODEL_V6` としてfreeze。`PREDICTION_BUY_1WIN_PLUS_FLAT`、source/result cohort未接触を確認。 |
| December boundary | `DECEMBER_DATA_ACQUISITION = 0`、`DECEMBER_RESULT_ACCESS = 0`、`DECEMBER_V6_INFERENCE = 0` |
| Activation / evaluation | auto activation禁止。January V6 evaluation、December V6 inference、V6 performance evaluationはいずれも `0`。 |
| Preserved authority | V5、Selection Authority Protocol V1、Current Formal Prospective、January Protocol/PRE/POST、Fingerprint Index、Productionはいずれも変更なし。 |
| Fingerprint | `NEW_FINGERPRINT_REQUIRED = NO`。Fingerprint Index変更なし。 |
| Next | `CLAUDE_INDEPENDENT_V6_TRAINING_REVIEW` |

`LEDGER_SUMMARY_COUNTER_UPDATE = DEFERRED_UNRESOLVED`。既存summary counterへこのadditive training recordを算入する明示仕様は確認できないため、推測でcounterを変更しない。

## Authoritative Reopen Record — 2026-09-20 — Independent Race Selection Sibling Shadow

| Field | Value |
|---|---|
| Status | `REOPENED_FOR_FORMAL_PROSPECTIVE_SHADOW_IMPLEMENTATION` |
| Reopen scope | `INDEPENDENT_RACE_SELECTION_SIBLING_DEVELOPMENT_ONLY` |
| Closed-family conflict | `NO` — closed risk-safe-count Volume Authority is not resumed |
| New independent signal | Frozen V4 Model v5 `P(top3)` with fixed `tau=0.3796765822155326` |
| Candidate pool | Current Top5、`shadow_ai_rank<=5`、frozen `risk_guard_pass=true` |
| risk_guard role | `ELIGIBILITY_VETO_ONLY`; desired count / Volume Authorityには使用しない |
| Current race state | selection gateではない。frozen model featureとしてのみ使用 |
| Volume | `NATURAL_VOLUME` primary; matched volumeはdiagnostic only |
| Evidence role | `FORMAL_PROSPECTIVE_INDEPENDENT_RACE_SELECTION_SHADOW` |
| Production | `PRODUCTION_AUTHORIZATION = FALSE` |
| Protocol | `docs/independent_race_selection_prospective_protocol_v1.json` |
| Historical reference | `reports/independent_race_selection_dev_diagnostic_v1/` — development-only / non-evidential |
| Historical candidate | 492 selected races、791 horses、346 hits、43.742098609355246% |
| Explicit exclusion | `tau=0.37` is post-development counterfactual and prohibited |
| Controlled Trial discussion | independent blocks>=2、dates>=4、actual selected races>=60 の後にのみ、別Human承認で検討 |
| No retune | block間のmodel/tau/pool/risk_guard/semantics変更は禁止 |

`LEDGER_SUMMARY_COUNTER_UPDATE = DEFERRED_UNRESOLVED`。本記録は既存closed familyの状態を置換せず、Human承認済みの別sibling scopeをadditiveに登録する。

