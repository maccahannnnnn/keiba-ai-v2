# KeibaAI ML V4 BUY Selection Learning — Training Protocol v2

V1を`SUPERSEDED_DUE_TO_FEATURE_TRANSFORM_SPEC_ERROR`とし、既承認のfeature transformを機械的に訂正した。Model v1は`FREEZE_REJECT_DUE_TO_SUPERSEDED_PROTOCOL`であり、May OOSには使用しない。

## Fixed transform

20 semantic featuresは、Ability、PastPerformance、Distance、CourseShape、LapSuitability、RaceShape、PaceStyle、shadow_ai_rank、decision_score、final_score、adjusted_score、4 gate、consensus counts、risk/conflict count、race_stateの順。

`race_state`はmodel inputからDROPする。PLAY_CONVERGEDをreferenceとして`is_PLAY_UNCONVERGED_4PLUS`、`is_SKIP`を同位置に生成する。PaceStyleは必ず保持する。変換後列は21列で、未知stateおよび非boolean gateはFAIL_CLOSED。

V1からの変更はこのtransform訂正だけであり、Dataset、target、recipe、Gate、LODO、P50、May consumption、SKIP/UNCONVERGED boundaryは不変。fit、性能開示、Mayアクセス、OOS評価は0件。
