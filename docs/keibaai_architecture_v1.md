# KeibaAI v1.0 Architecture Design

## 1. KeibaAIの目的

KeibaAIは、中央競馬専用のExplainable AIです。

目的は単純な的中率の最大化ではなく、レース構造を理解し、なぜその馬を評価したのかを説明できるAIに育てることです。

評価では、人気・オッズ・予想印は使用しません。馬そのものの情報、過去走、血統、コース、馬場、展開、ラップ、当日のバイアスをもとに、説明可能な評価を行います。

## 2. 現在のEvaluator構成

Phase3完了時点の試運転Evaluation Engineは、以下の順番で評価します。

```text
BloodlineEvaluator
↓
PastPerformanceEvaluator
↓
PaceStyleEvaluator
↓
DistanceSuitabilityEvaluator
↓
TrackConditionSuitabilityEvaluator
↓
RacePacePredictor
↓
RaceShapeEvaluator
↓
CourseShapeEvaluator
↓
TrackBiasEvaluator
↓
LapSuitabilityEvaluator
↓
ScoreWeightEvaluator
↓
FinalScoreIntegrator
↓
ImpactEvaluator
```

## 3. 各Evaluatorの役割

### BloodlineEvaluator

血統・コース・距離・馬場適性を評価します。

### PastPerformanceEvaluator

過去最大5走から、着順、着差、PCI、RPCI、上がり3F、安定度を評価します。

### PaceStyleEvaluator

通過順から脚質を `escape` / `front` / `stalk` / `closer` / `deep_closer` / `unknown` に分類します。

### DistanceSuitabilityEvaluator

同距離実績、距離延長、距離短縮、今回距離が得意レンジに入るかを評価します。

### TrackConditionSuitabilityEvaluator

良・稍重・重・不良への馬場適性を評価します。

### RacePacePredictor

全馬の脚質構成から、今回のレースペースを `slow` / `average` / `fast` / `very_fast` として予測します。

### RaceShapeEvaluator

予測ペースと各馬の脚質を組み合わせ、今回の展開が向くか不向きかを評価します。

### CourseShapeEvaluator

展開、脚質、コース形状、枠順の噛み合わせを評価します。

### TrackBiasEvaluator

当日の内外・前後バイアスと、脚質・枠順の噛み合わせを評価します。

### LapSuitabilityEvaluator

瞬発戦、持続戦、消耗戦への適性を評価します。

### ScoreWeightEvaluator

レース構造に応じて、各評価項目の重みを決定します。

### FinalScoreIntegrator

各スコアを統合し、`final_score` / `integrated_score` を生成します。

### ImpactEvaluator

展開影響を補正し、最終的な `adjusted_score` を生成します。

## 4. 現在の主な出力項目

Phase3完了時点の主な出力項目は以下です。

```text
bloodline_score
past_score
pace_style
pace_score
distance_score
track_condition_score
pace_prediction
shape_score
shape_comment
course_shape_score
course_shape_comment
track_bias_score
track_bias_comment
lap_style
lap_score
lap_comment
score_weights
weight_comment
weighted_score
weighted_score_breakdown
final_score
score_breakdown
integrated_score
impact_score
adjusted_score
impact_comment
warnings
```

## 5. スコア統合の考え方

Phase2までは、各Evaluatorの評価を単純加算する考え方が中心でした。

Phase3では、以下の構造評価を追加しました。

- 展開とコース形状
- 当日トラックバイアス
- ラップ適性
- レース構造に応じた重み付け

現在は、以下の流れで総合評価します。

```text
各Evaluator
↓
ScoreWeightEvaluator
↓
FinalScoreIntegrator
↓
ImpactEvaluator
```

各Evaluatorは個別の観点から評価理由を作り、`ScoreWeightEvaluator` が今回のレース構造に応じて重要度を調整します。その後、`FinalScoreIntegrator` が統合スコアを作り、最後に `ImpactEvaluator` が展開影響を補正します。

## 6. Phase4の設計方針

Phase4では `RaceStructureEngine` を作成します。

`RaceStructureEngine` は新しい単独Evaluatorではなく、レース全体を解析する司令塔です。

主な役割は以下です。

- 今回のレース構造を整理する
- 重要要素を抽出する
- 展開、馬場、コース、ラップを統合して読む
- `ScoreWeightEvaluator` や `ExplainEngine` の判断材料を作る

想定出力は以下です。

```text
race_structure
structure_comment
key_factors
```

## 7. Phase4以降の予定

```text
Phase4-1
RaceStructureEngine

Phase4-2
ExplainEngine

Phase4-3
SelfReviewEngine強化
```

## 8. 開発思想

KeibaAIは当てるAIではありません。

なぜ評価したかを説明するAIです。

人気・オッズ・予想印は評価に使用しません。

すべての評価にはExplainが存在することを重視します。

また、既存コードとの互換性を重視します。新しい機能を追加するときも、既存のAnalyzer、Importer、CSV仕様、Knowledge Base、Self Review Engineを不用意に壊さない構成を維持します。

## 9. 開発ポリシー

今後、新しいEvaluatorを追加する前に、必ず「既存Evaluatorで実現できない理由」を確認します。

同じ役割のEvaluatorを増やさず、Explainable AIとして責務を明確に分離します。

Phase4以降は `RaceStructureEngine` を中心に、各Evaluatorは独立した責務を持つ構造を維持します。

Evaluator間の依存は最小限にし、後から拡張しやすい設計を保ちます。
