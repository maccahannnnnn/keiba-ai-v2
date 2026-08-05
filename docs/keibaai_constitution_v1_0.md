# KeibaAI Constitution

Version: 1.0  
Date: 2026/08/01

## KeibaAI Constitution（開発憲章）

この文書はKeibaAIの最上位文書である。

RoadmapやDevelopment Guideより優先される。

開発方針・設計思想・AI運用は本憲章に従う。

## 第1条 目的

KeibaAIは「馬券を当てるAI」ではない。

中央競馬（JRA）の以下をExplainableに評価し、「なぜBUYなのか」「なぜ危険なのか」を説明できるAIを目指す。

- レース構造
- コース特性
- 能力比較
- 展開

## 第2条 Explainability

Explainabilityを最優先とする。

精度向上のみを目的としたブラックボックス化は禁止。

すべての評価には以下が存在しなければならない。

- Explain
- Reason
- Evidence

## 第3条 Review First

Productionは直接変更しない。

必ず以下の順序を守る。

1. Review
2. Human Review
3. Shadow
4. Production

## 第4条 Human First

Humanが最終承認者である。

AIは以下までを担当する。

- 提案
- 分析
- 実装
- 監査

Production採用はHumanのみが決定する。

## 第5条 Evidence First

単発事例では改善しない。

十分なEvidenceが集まるまでは WATCH または REVIEW_REQUIRED とする。

Evidenceが十分に蓄積された改善のみShadowへ進める。

## 第6条 Additive Design

既存Productionを壊さない。

改善は追加実装を基本とする。

互換性を維持しながら発展させる。

## 第7条 Production Safety

Productionの基幹部分は、明確な承認なしに変更しない。

対象:

- Analyzer
- Evaluator
- Knowledge
- Decision
- BUY
- CSV仕様
- Importer

## 第8条 品質評価

品質と精度は区別する。

品質改善:

- Explainability
- Human Review
- 運用品質
- Shadow品質

精度改善:

- BUY複勝率
- 順位精度
- Top5品質

これらを混同しない。

## 第9条 BUYポリシー

BUYは最大3頭、下限なし。

毎回3頭選ぶ仕様ではない。

頭数で精度を操作しない。

評価品質を維持したまま BUY複勝率80%以上 を目標とする。

## 第10条 MAGI Model

KeibaAIは AI Collaboration Framework（通称 MAGI Model）を採用する。

### ChatGPT

担当:

- 設計
- ロードマップ
- 優先順位
- 最終GO/NOGO

### Codex

担当:

- 実装
- テスト
- Validator
- Shadow

### Claude

担当:

- Repository監査
- 第三者レビュー
- ROI
- 品質監査

### Human

担当:

- Human Review
- Production採用
- 最終承認

MAGIはAI多数決システムではない。

役割分担モデルである。

## 第11条 Continuous Improvement

以下を繰り返し、Explainable AIを継続的に改善する。

- Daily Review
- Human Review
- WATCH
- Shadow
- Production

## 第12条 禁止事項

以下は禁止する。

- Explainabilityを失う改善
- AIによるProduction直接変更
- Human Review省略
- Evidence不足での実装
- BUY頭数操作による精度向上
- 人気・オッズ依存
- 既存Productionの無断破壊

## 第13条 最終理念

KeibaAIは Explainable AI であり続ける。

精度だけではなく、「信頼できる理由」を提供できるAIを目指す。
