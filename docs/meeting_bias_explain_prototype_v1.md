# MeetingBias Explain Prototype v1

Status: R&D PROTOTYPE / NOT CONNECTED TO PRODUCTION

この文書は、MeetingBiasを将来ExplainEngineへ接続する場合の説明テンプレートとデータ構造の試作である。
Production の ExplainEngine / DecisionEngine / RaceDecisionEngine / BUY V1 RC1 / 各Evaluator には接続していない。
`score_impact` は常に `none` を返す。

実装: `review/meeting_bias_explain_renderer.py`
テスト: `tests/test_meeting_bias_explain_renderer.py`

## 1. 前提レイヤー定義

| レイヤー | 責務 | 時間スケール | 種別 |
|---|---|---|---|
| MeetingBias | 開催進行（開催段階・コース替わり・芝の傷み） | 開催全体 | **事前分布（prior）** |
| TrackBias | 当日の内外傾向 | 当日 | **実測（observed）** |
| RaceShape | 当該レースの展開・隊列構造 | 単一レース | **実測（observed）** |

原則: **実測は事前分布に優先する。** MeetingBiasは実測が存在しない軸でのみ「参照情報」として機能し、
実測と食い違った場合は自らの補正を抑制する。

## 2. 提案データモデル

### 2.1 入力

```python
{
  # 開催識別
  "racecourse": "函館",
  "surface": "turf",                       # turf / dirt
  "distance_category": "sprint",           # sprint / mile / middle / long

  # 開催段階と、その根拠の強さ
  "meeting_stage": "closing",              # opening / middle / closing / UNKNOWN
  "meeting_stage_source": "MEETING_DAY",   # EXPLICIT / MEETING_WEEK / MEETING_DAY / DERIVED_ORDER / UNKNOWN

  # Knowledge の由来と検証状態
  "knowledge_source": "daily_review_validated",  # manual_template / daily_review_validated / not_connected
  "validated": True,
  "support_races": 18,
  "support_meetings": 2,

  # MeetingBias の事前分布
  "inside_outside_tendency": "outside_watch",
  "front_closer_tendency": "stalk_closer",

  # 実測レイヤー（存在しない場合は available: False）
  "track_bias_observation": {"available": True, "inside_outside": "outside_watch"},
  "race_shape_observation": {"available": True, "front_closer": "stalk_closer"},
}
```

`meeting_stage_source` を独立フィールドにしている理由: 開催段階の「値」と「根拠の強さ」を分離しないと、
`race_date` からの推定値と JRA の 日目 メタデータが同じ重みで扱われてしまうため。

### 2.2 出力

```python
{
  "version": "meeting_bias_explain_prototype_v1",
  "explain_tier": "SUPPORTING",         # SUPPRESSED / CONTEXT_ONLY / SUPPORTING
  "evidence_tier": "VALIDATED",         # INSUFFICIENT / TEMPLATE_ONLY / PROVISIONAL / VALIDATED
  "suppression_reason": "",
  "relations": {"track_bias": "AGREEMENT", "race_shape": "AGREEMENT"},
  "lines": [...],
  "text": "...",
  "score_impact": "none",               # 常に none
  "audit": {...}                        # 判定根拠の全入力を保持
}
```

`audit` に正規化後の全入力を保持するのは、Explain文面だけを見て「なぜこの表現になったか」を
後から再構成できるようにするため（Explainability First）。

## 3. Tier 判定ロジック

### 3.1 evidence_tier（証拠の強さ）

上から順に評価し、最初に該当したものを採用する。

| 順 | 条件 | evidence_tier | suppression_reason |
|---:|---|---|---|
| 1 | `meeting_stage` が opening/middle/closing 以外 | INSUFFICIENT | `meeting_stage_unknown` |
| 2 | `meeting_stage_source` が UNKNOWN | INSUFFICIENT | `meeting_stage_source_unknown` |
| 3 | Knowledge 未接続 | INSUFFICIENT | `meeting_bias_knowledge_not_connected` |
| 4 | `validated == False` | TEMPLATE_ONLY | `manual_template_not_validated` |
| 5 | `support_races < 15` | PROVISIONAL | `support_races_below_minimum` |
| 6 | `support_meetings < 2` | PROVISIONAL | `support_meetings_below_minimum` |
| 7 | 上記以外 | VALIDATED | `""` |

閾値 15レース / 2開催 は、Diagnostic Shadow の開始条件（1場×1馬場×3段階×各5レース、
かつ異なる2開催での再現）と同一に揃えてある。片方だけ緩めると過学習検知が働かなくなるため。

### 3.2 explain_tier（表示の強さ）

| evidence_tier | 実測との競合 | explain_tier |
|---|---|---|
| INSUFFICIENT | — | **SUPPRESSED** |
| TEMPLATE_ONLY | — | CONTEXT_ONLY |
| PROVISIONAL | — | CONTEXT_ONLY |
| VALIDATED | なし | **SUPPORTING** |
| VALIDATED | あり（TrackBias または RaceShape と CONFLICT） | **CONTEXT_ONLY へ降格** |

最終行の降格が「実測優先」原則をデータ構造として強制している部分である。
検証済みEvidenceであっても、当日実測と食い違えば自動的に参考情報へ落ちる。

### 3.3 relations（軸ごとの関係）

| 軸 | 対応する実測レイヤー | 値 |
|---|---|---|
| 内外（進路） | TrackBias | AGREEMENT / CONFLICT / NO_OBSERVATION / NOT_APPLICABLE |
| 前後（脚質） | RaceShape | 同上 |

内外を TrackBias、前後を RaceShape に割り当てているのは、責務境界（第1節）に対応させるため。

## 4. 日本語説明テンプレート

### 4.1 抑制時（SUPPRESSED）

| reason | 文面 |
|---|---|
| `meeting_stage_unknown` | 開催段階を特定できないため、MeetingBiasは評価に使用しない。 |
| `meeting_stage_source_unknown` | {開催段階}と推定されるが、根拠が不明なため、MeetingBiasは評価に使用しない。 |
| `meeting_bias_knowledge_not_connected` | MeetingBias Knowledgeが未接続のため、MeetingBiasは評価に使用しない。 |

### 4.2 Evidence強度別（本文2行目）

| evidence_tier | 文面 |
|---|---|
| TEMPLATE_ONLY | 手動テンプレート由来の一般傾向では、{事前分布}。**検証済みEvidenceではないため、評価には使用しない。** |
| PROVISIONAL | 事前分布では、{事前分布}。ただし裏付けレース数・開催数が基準に達していないため、参考情報にとどめる。 |
| VALIDATED | 開催進行の事前分布では、{事前分布}。 |

### 4.3 TrackBias との関係（内外軸）

| relation | 文面 |
|---|---|
| AGREEMENT | 当日のTrackBiasも{内外}で、事前傾向と実測は同方向。 |
| **CONFLICT** | **ただし当日のTrackBiasは{内外}。当日実測を優先し、MeetingBiasによる進路の補正は抑制する。** |
| NO_OBSERVATION | 当日のTrackBias情報がないため、進路傾向は事前分布としてのみ参照する。 |

### 4.4 RaceShape との関係（前後軸）

| relation | 文面 |
|---|---|
| AGREEMENT | 当該レースのRaceShapeも{脚質}寄りで、展開構造とも整合している。 |
| **CONFLICT** | **一方でRaceShapeは{脚質}を示す。レース固有の展開を優先し、MeetingBiasによる脚質の補正は抑制する。** |
| NO_OBSERVATION | RaceShapeの展開情報がないため、脚質傾向は事前分布としてのみ参照する。 |

### 4.5 CONTEXT_ONLY 時の末尾行

> MeetingBiasは参考レイヤーであり、スコアや判定には反映しない。

### 4.6 禁止表現

固定テストで以下の断定表現の混入を検査している。

`必ず` / `確実` / `間違いなく` / `断定` / `確定的`

## 5. Explain-only 出力例

### 例1: 現在の実データ（38件全てがこの状態）

入力: `meeting_stage: UNKNOWN`

```text
開催段階を特定できないため、MeetingBiasは評価に使用しない。
```

`explain_tier: SUPPRESSED` / `evidence_tier: INSUFFICIENT`

### 例2: 現在の Knowledge（manual_template）を使った場合

入力: 函館 / turf / sprint / opening / EXPLICIT / manual_template / validated=False / 実測なし

```text
函館芝短距離の開催前半。
手動テンプレート由来の一般傾向では、進路は内寄り、脚質は前目・好位。検証済みEvidenceではないため、評価には使用しない。
当日のTrackBias情報がないため、進路傾向は事前分布としてのみ参照する。
RaceShapeの展開情報がないため、脚質傾向は事前分布としてのみ参照する。
MeetingBiasは参考レイヤーであり、スコアや判定には反映しない。
```

`explain_tier: CONTEXT_ONLY` / `evidence_tier: TEMPLATE_ONLY`

### 例3: 将来（検証済み・実測と一致）

入力: 函館 / turf / sprint / closing / MEETING_DAY / validated=True / 18レース / 2開催 / TrackBias=外 / RaceShape=差し

```text
函館芝短距離の開催後半。
開催進行の事前分布では、進路は外寄り、脚質は差し・追込。
当日のTrackBiasも外寄りで、事前傾向と実測は同方向。
当該レースのRaceShapeも差し・追込寄りで、展開構造とも整合している。
```

`explain_tier: SUPPORTING` / `evidence_tier: VALIDATED`

### 例4: 将来（検証済みだが当日実測と競合 → 降格）

入力: 例3と同じ、ただし TrackBias=内

```text
函館芝短距離の開催後半。
開催進行の事前分布では、進路は外寄り、脚質は差し・追込。
ただし当日のTrackBiasは内寄り。当日実測を優先し、MeetingBiasによる進路の補正は抑制する。
当該レースのRaceShapeも差し・追込寄りで、展開構造とも整合している。
MeetingBiasは参考レイヤーであり、スコアや判定には反映しない。
```

`explain_tier: CONTEXT_ONLY`（VALIDATED から降格） / `relations.track_bias: CONFLICT`

## 6. Option E タイブレーク利用時の将来説明案

`MeetingBiasExplainRenderer.tiebreak_note()` は、将来 Option E（BUY選抜後段タイブレーク）を
実装する場合に必要となる文面のみを生成する。**選抜・順位付け・スコアリングは一切行わない。**

- `explain_tier == "SUPPORTING"` のときだけ `available: True` を返す。
- 戻り値の `feature_state` は常に `NOT_IMPLEMENTED`。
- 戻り値の `score_impact` は常に `none`。

生成される文面:

```text
【将来案・未実装】候補が3頭に収束しない場合に限り、差し・追込の傾向を並び順の補助情報として参照する案がある。
この案でもゲート閾値・スコア・BUY上限は変更しない。
```

「未実装」と「変更しない」の2語は固定テストで存在を検査している。
Explain上でこの案が既存機能であるかのように読まれることを防ぐため。

## 7. 固定テスト

`tests/test_meeting_bias_explain_renderer.py` — 16テスト。

| 分類 | テスト |
|---|---|
| 抑制 | UNKNOWN stage / UNKNOWN source / Knowledge未接続 / 空入力 |
| Evidence階層 | manual_template → TEMPLATE_ONLY・「評価には使用しない」含有 / support不足 → PROVISIONAL（レース数・開催数の両方） / 検証済み+一致 → SUPPORTING |
| 実測優先 | TrackBias競合 → 降格+「抑制」含有 / RaceShape競合 → 降格 / 実測なし → 事前分布のみ |
| 安全性 | `score_impact` が全tierで `none` / 断定表現の不在 / Production モジュール非依存 |
| Option E | SUPPORTING時のみ生成 / `NOT_IMPLEMENTED` 明示 |

## 8. Production 接続時の注意

1. **`score_impact` を `none` 以外にする変更は、このRendererの責務外である。** 本Rendererは文面生成のみを行い、
   スコアリングの可否判断は Feature Flag 側に置くこと。
2. **`explain_tier == "SUPPORTING"` はスコア反映の許可ではない。** 表示の強さのみを表す。
   スコア反映の可否は Diagnostic Shadow / Score Impact Shadow の結果と Human Review 承認で決まる。
3. **MeetingBias を ConsensusProfile の評価器として追加しないこと。**
   `ShadowBUYSpecV1Config.MIN_POSITIVE_EVALUATORS = 5` は現在7評価器に対する閾値であり、
   8番目を足すと「7分の5」が「8分の5」に変わり、MeetingBiasと無関係な全レースのConsensusが緩む。
4. TrackBias / RaceShape が実測値を持つ軸では、MeetingBias の数値を加算しないこと。
   本プロトタイプの CONFLICT 降格は文面上の抑制にすぎず、スコア面の二重加点防止は別途必要。
5. 接続時は `review/diagnostic_safety_validator.py` の監視対象へ本Rendererを追加すること。

## 9. 既知の限界

- 本Rendererは `meeting_stage` が解決済みであることを前提とする。現時点の実データでは
  38件すべてが `UNKNOWN` であり、実運用では例1（SUPPRESSED）しか出力されない。
- `course_rotation`（A/B/Cコース）は現在どのデータソースにも存在せず、本プロトタイプでも扱っていない。
- 本Rendererは1レース単位の純関数であり、開催横断の集計・学習は行わない。
