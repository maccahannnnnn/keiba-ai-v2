# PL Same-Volume Reselection Shadow V1 Protocol

Human-approved implementation; Production promotion and prospective evidence start are not authorized by this record.

## Identity and frozen authority

- Treatment: `PL_SAME_VOLUME_RESELECTION_SHADOW_V1`.
- Race authority: Current. Volume authority: Current BUY count, deliberately fixed; this protocol makes no new Volume Authority claim.
- Selection authority: frozen PL Forward full-field rank. This is an EXP-022 sibling, not a simple rerun: its selection model is PL full-field ranking. Unlike Formal V5 it does not exclude Treatment horses by risk guard; unlike Lane D it is not restricted to Current Top5.
- Model `models/pl_forward_shadow_v1/pl_forward_shadow_v1_model.json`: SHA256 `418fc9b4cefe1757f79dfc22a7d49b7c1592b91084cca97f88f55bb1389b0585`.
- Manifest `models/pl_forward_shadow_v1/pl_forward_shadow_v1_manifest.json`: SHA256 `18443426b16dba4c28374d39841eeac0a98af4dd4e617b8ae8457dcee2f6494e`.
- PL inference implementation `review/pl_forward_shadow_v1.py`: SHA256 `1a36902f2afee91bd03f99394cc52bf15ba8a8e2b1e99afa009b8df159f8b3cc`.
- PL probability implementation `review/full_field_redesign_iteration2_v1.py`: SHA256 `5df9e31df983516e015dec03c856f462e04e5bd63f50ac6616f367f5e64ab0ae`.
- Model, scaler, feature list, coefficients and inference implementation remain fixed throughout an evidence block. Any change stops that block and requires Human Review. Adaptive PL is excluded.

## PRE selection and failure

For each race, k is the number of Current BUY horses. If k=0, select none; otherwise select frozen PL ranks 1 through k from the full field. The existing PL ordering is probability descending then horse number ascending, with the existing sum-of-probabilities tolerance `1e-8`. Do not use Current Top5, Current BUY membership or Current risk guard as a Treatment exclusion. Preserve race, full-field probabilities/ranks, Current and Treatment selections, differences, ties, gate/risk/history traces, source/model/code hashes and a Current execution-environment fingerprint. An inference failure in a Current BUY race is `PL_INFERENCE_FAILED`: no fallback, no invented selection, exclude it from paired analysis, and report coverage and reason.

Freeze the selection and its SHA before Result access. For prospective evidence record selection freeze time and independently substantiated first start time, and require freeze before the first start; record Result source SHA and Result read time and require that time to be strictly later than freeze. Fail closed if these cannot be verified. Historical 10/17–10/18 smoke is `NON_EVIDENTIAL_IMPLEMENTATION_SMOKE` and cannot be prospective evidence.

## Evaluation

Keep prediction-time selected counts. For KPI, invalid results are excluded from valid denominators. A race is `PAIR_VALID` only if Current and Treatment valid selected counts match; report exclusions with race IDs and reasons. Separately recalculate all-race sensitivity treating invalid selections as misses. If the sign of the primary and sensitivity differences differs, require Human Review.

For PAIR_VALID races use race delta = Treatment top-three count minus Current top-three count. Report same-volume rates and the difference in hits divided by valid selected horses. Bootstrap by DATE, sampling dates with replacement and retaining all their races, 10,000 iterations, seed 20261018, percentile 95% interval for mean race delta.

KPI hard gate: Treatment BUY_TOP3_RATE >= 40.0%. Superiority hard gate: date-cluster bootstrap 95% lower bound > 0. The +6.0 percentage point target is reference only, not a hard gate. Evaluate once at the first point both >=12 prospective dates and >=60 eligible races are met. If both gates pass, `SHADOW_CANDIDATE_PASS` and Human Review; otherwise allow one extension. At checkpoint 1, KPI below 40% and mean race delta <=0 produces a futility warning without automatic stop. At the first point both >=24 dates and >=120 eligible races are met, final checkpoint: both gates pass or `HOLD_NO_GO`; no further extension.

Always report daily, chronological block, leave-one-date-out, concentration and monthly stability, plus raw hit and race-level differences, better/equal race counts, race success rate, overlap, PL-only/Current-only selections, the PL Rank1 vs frozen Current Rank1 2x2, outside-Current-Top5 counts/rates, Current BUY PL-rank distribution, and `PL_RANK1_PRECISION_DIAGNOSTIC`. The latter is a diagnostic only, not an evidence gate or Production candidate. Do not invent a Current Rank1 when its authority is unavailable.

Current is both comparator and PL input authority. Record Current prediction source, run_new/equivalent entrypoint and DecisionEngine hashes, knowledge tree fingerprint and available canonical environment fingerprint. Changes split evidence blocks; no automatic cross-block primary pooling. Prospective evidence starts only after protocol freeze, implementation completion, Claude implementation review PASS, and final Human implementation approval, and never retroactively.
