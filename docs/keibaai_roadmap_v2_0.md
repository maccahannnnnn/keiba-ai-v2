# KeibaAI Roadmap v2.0

Version: 2.0  
Date: 2026/08/01

## 開発理念

KeibaAIは「馬券を当てるAI」ではない。

中央競馬（JRA）のレース構造・コース特性・馬の能力を客観的に評価し、

- なぜBUYなのか
- なぜ危険なのか
- なぜPASSなのか

を説明できる Explainable AI を目指す。

人気・オッズ・印は評価対象にしない。

Explainability を犠牲にして精度だけを追う改善は禁止する。

## 最終目標

最終KPI:

- BUY馬複勝率 80%以上

ただし、BUY頭数を恣意的に増減して達成することは禁止する。

評価品質を維持したまま80%を目指す。

## 品質KPI

精度KPIとは別に品質KPIを管理する。

品質KPI:

- Explainability維持
- Human Review運用率
- Shadow Validation実施率
- SELF_CHECK_CONFLICT 0件維持
- Review→改善サイクル継続
- Production無事故運用

品質改善と精度改善は区別して評価する。

## 開発思想

- Review First
- Human Review First
- Evidence First
- Explainability First
- Additive Design
- Production Safe
- Shadow Validation

AIはProductionを直接変更しない。

必ず以下の順序を守る。

1. Review
2. Human Review
3. Shadow
4. Production

## 現在の完成状況

完成済:

- Analyzer
- Knowledge Base
- Course Knowledge
- Bloodline Knowledge
- 各Evaluator
- DecisionEngine
- RaceDecisionEngine
- ConfidenceEngine
- ExplainEngine
- RaceSummary
- TrialReport
- BUY V1 RC1
- MeetingBias
- Learning Candidate
- Priority Manager
- Human Review Engine
- Shadow Validation
- Review Pipeline
- Operation Quality Phase1
- Operation Quality Phase2-1
- Operation Quality Phase2-2
- Human Review Operation
- RaceDecision × BUY Synchronization
- Daily Review

## Priority完了状況

### Priority1: Human Review Operation

状態: COMPLETE

内容:

- WATCH巻き戻り修正
- status_source
- Human Review CLI
- 代表証拠表示
- 構造化Review
- Validator
- 固定テスト

Claude Review: ACCEPT  
ChatGPT: GO

### Priority2: RaceDecision × BUY Synchronization

状態: COMPLETE

内容:

- RaceDecisionBuySynchronizer
- PASS + BUY → PLAY同期
- RaceDecision Original保持
- SELF_CHECK_CONFLICT 8件 → 0件

Claude Review: ACCEPT  
ChatGPT: GO

## 現在の成熟度

品質成熟度: FAIR+

今回改善されたのは以下であり、予測精度そのものはまだ改善していない。

- 運用品質
- Explainability
- Human Review

Consensus Reliability、RaceShape、DecisionEngine などは今後の対象。

## AI Collaboration Framework（MAGI Model）

MAGIは役割分担モデルである。

AI多数決システムではない。

Human ReviewおよびProduction採用は必ずHumanが最終承認する。

### ChatGPT

担当:

- 全体設計
- 長期ロードマップ
- 開発優先順位
- Codex実装指示
- Claudeレビュー統合
- GO / NOGO判断

### Codex

担当:

- Repository実装
- テスト
- py_compile
- Validator
- Shadow Validation
- レポート生成

### Claude

担当:

- Repository監査
- 第三者レビュー
- 品質監査
- ROI評価
- Additive Design確認
- リスク分析
- 設計レビュー

### Human

担当:

- Human Review
- Production採用
- 最終承認

## Development Workflow

1. Issue
2. ChatGPT設計
3. Codex実装
4. Claude第三者レビュー
5. ChatGPT GO / NOGO
6. Human Production採用
7. Daily Review
8. Human Review
9. WATCH
10. 十分な証拠
11. Shadow
12. Production改善

## Daily Review運用

Daily Reviewでは以下を確認する。

- BUY結果
- Top5品質
- RaceDecision
- Explain一致度
- 改善候補

単日結果だけでは実装判断しない。

改善候補は WATCH または REVIEW_REQUIRED として蓄積する。

## Human Review運用

AIは以下を決定しない。

- APPROVED
- WATCH
- REJECTED

AIは候補提示のみ。

最終判断はHuman。

## BUY評価ルール

BUYは最大3頭、下限なし。

毎回3頭選ぶ仕様ではない。

BUY複勝率は評価可能なBUY馬のみを対象とする。

対象外候補:

- finish=0
- 取消
- 除外
- 競走中止

失格については「AI評価精度」と「馬券払戻基準」のどちらを採用するか今後正式定義する。

## 改善判断ルール

分析だけで終了しない。

十分な証拠が揃った改善候補は以下の順で進める。

1. Analysis
2. Implementation
3. Validation
4. Production

ただし、単発事例のみで実装しない。

Evidenceが十分に蓄積されるまでは WATCH または ADDITIONAL_DATA_REQUIRED とする。

## 今後のPriority

### Priority3: Operation Data Collection

- Daily Review蓄積
- Human Review蓄積
- WATCH蓄積

### Priority4: Consensus Reliability改善

### Priority5: RaceShapeEvaluator改善

### Priority6: DecisionEngine改善

### Priority7: TrackBias / MeetingBias データ強化

## ロードマップ運用方針

Roadmapは固定文書ではない。

以下を通して継続的に更新する。

- 実装
- レビュー
- Shadow
- Daily Review
- Human Review
- Claude監査

ただし、以下の基本思想は変更しない。

- 開発理念
- Explainability
- Review First
- Human Review First
- Additive Design
- Production Safe
