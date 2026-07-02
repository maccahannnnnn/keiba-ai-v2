# KeibaAI Phase4-1 RaceStructureEngine Design

## 1. RaceStructureEngineの目的

`RaceStructureEngine` は、KeibaAIにおけるレース構造解析の司令塔です。

各馬を個別に評価する前に、今回のレース全体がどのような構造になるかを整理します。

主な目的は以下です。

- 今回のレース構造を把握する
- 重要要素を抽出する
- 各Evaluatorが同じ前提で評価できるようにする
- `ScoreWeightEvaluator` と `ExplainEngine` の判断材料を作る

人気・オッズ・予想印は使用しません。

## 2. RaceStructureEngineはEvaluatorではない

`RaceStructureEngine` は、各馬に直接点数を付けるEvaluatorではありません。

役割は「レース全体の前提」を作ることです。

整理する情報の例は以下です。

- 想定ペース
- 脚質構成
- コース形状
- 枠順影響
- 馬場状態
- トラックバイアス
- 想定ラップ質
- 重要評価項目

個別の加点・減点は各Evaluatorが担当し、`RaceStructureEngine` はそれらの判断に使う共通コンテキストを作ります。

## 3. 入力情報

`RaceStructureEngine` は、可能な範囲で以下の情報を利用します。

```text
racecourse
course
surface
distance
track_condition
horses
pace_prediction
escape_count
front_count
stalk_count
closer_count
deep_closer_count
unknown_count
course_shape_score
course_shape_comment
track_bias_score
track_bias_comment
lap_style
lap_score
lap_comment
score_weights
weight_comment
```

Course Knowledge から取得できる場合は、以下も利用します。

```text
course_features
pace_tendency
draw_bias
favorable_styles
score_modifiers
explain
```

存在しない情報があっても処理は止めません。不足情報は `unknown` / `neutral` として扱います。

## 4. 出力情報

`RaceStructureEngine` の想定出力は以下です。

```text
race_structure
structure_comment
key_factors
structure_flags
recommended_weights_hint
```

## 5. race_structureの内容

`race_structure` は辞書形式を想定します。

例:

```python
race_structure = {
    "racecourse": "東京",
    "surface": "芝",
    "distance": 1600,
    "pace": "average",
    "pace_pressure": "medium",
    "dominant_styles": ["stalk", "closer"],
    "course_shape": "long_straight_one_turn",
    "draw_impact": "moderate",
    "track_bias": "neutral",
    "lap_profile": "instant",
    "key_factors": [
        "late_speed",
        "positioning",
        "course_shape",
        "lap_suitability",
    ],
}
```

## 6. structure_commentの内容

`structure_comment` は、今回のレース構造を自然文で説明します。

例:

```text
東京芝1600mはワンターンで直線が長く、平均ペース想定では瞬発力と位置取りが重要になる。
今回の脚質構成では先行馬と差し馬のバランスが取れており、極端な前崩れよりも直線での加速力を評価したい。
```

## 7. key_factorsの内容

`key_factors` は、今回のレースで特に重要な評価要素を配列で持ちます。

候補は以下です。

```text
course_shape
pace
positioning
draw
track_bias
lap_suitability
distance_fit
bloodline_fit
track_condition
stamina
early_speed
late_speed
sustained_speed
```

## 8. structure_flagsの内容

`structure_flags` は、構造判断用の補助フラグです。

例:

```text
is_sprint
is_mile
is_middle_distance
is_long_distance
is_turf
is_dirt
is_one_turn
is_two_turn
is_long_straight
is_small_turn
is_high_pace
is_slow_pace
is_bias_available
is_lap_profile_clear
```

これらのフラグにより、後続処理がレース構造を安全に参照できます。

## 9. recommended_weights_hint

`recommended_weights_hint` は、将来的に `ScoreWeightEvaluator` が参照できる重みヒントです。

例:

```python
recommended_weights_hint = {
    "course_shape_score": 1.3,
    "lap_score": 1.4,
    "shape_score": 1.2,
    "track_bias_score": 1.0,
    "bloodline_score": 1.1,
}
```

Phase4-1は設計段階のため、この重みヒントはまだ実装必須ではありません。

## 10. 既存Evaluatorとの関係

`RaceStructureEngine` は、既存Evaluatorを置き換えるものではありません。

既存Evaluatorの前提情報を整理するための司令塔です。

将来的な接続イメージは以下です。

```text
RacePacePredictor
↓
RaceStructureEngine
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

## 11. エラー対策

情報が不足していても処理を止めません。

不足情報は以下のように扱います。

- 数値がない場合は 0 または `None`
- 分類できない場合は `unknown`
- バイアスが取れない場合は `neutral`
- コメントには情報不足の旨を明記

`race_structure` には取得できた情報だけを入れ、`structure_comment` では不足情報がある場合にその旨を説明します。

## 12. Phase4実装方針

Phase4の実装予定は以下です。

```text
Phase4-1
RaceStructureEngine設計書作成

Phase4-2
RaceStructureEngine本体実装

Phase4-3
ScoreWeightEvaluatorがrace_structureを参照できるようにする

Phase4-4
ExplainEngineと接続する
```

## 13. 開発ポリシー

新しいEvaluatorを追加する前に、既存Evaluatorで実現できない理由を確認します。

同じ役割のEvaluatorを増やしません。

責務は以下のように分離します。

```text
RaceStructureEngine: 司令塔
Evaluator: 個別評価
ExplainEngine: 説明生成
SelfReviewEngine: 改善分析
```

人気・オッズ・予想印は評価に使用しません。

互換性を重視し、Analyzer、Knowledge Base、CSV仕様、Importer、Self Review Engine、`main.py` を不用意に変更しない方針を維持します。
